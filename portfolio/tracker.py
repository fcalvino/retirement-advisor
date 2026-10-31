"""
Portfolio tracker — records positions and computes performance metrics.

Metrics computed:
  - Total return, and an annualised growth of cost → value. **Not an IRR** — see
    ``ANNUALIZED_RETURN_CAVEAT`` (U5-12). A real money-weighted return is X-02.
  - Sharpe Ratio y Sortino (MAR = tasa libre de riesgo — U1-9b)
  - Max Drawdown
  - Portfolio Beta (vs SPY)
  - Sector weights
  - Dividend income received
"""

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from analysis.utils import downside_deviation
from config import DB_PATH, PORTFOLIO, RISK_FREE
from data.fetcher import get_history, get_info

PORTFOLIO_FILE = DB_PATH.parent / "portfolio.json"


def position_currency_skip_reason(currency: Optional[str]) -> Optional[str]:
    """Por qué una posición **no** entra al portfolio, o ``None`` si entra.

    El tracker suma costo y valor de mercado de cada posición como si fueran
    ``PORTFOLIO.base_currency``: 10 acciones de 7203.T a 3025 JPY pesaban como
    30 250 dólares en el total, la concentración y la deriva (PORTFOLIO-CCY).
    Hasta que exista la conversión (#154), solo entra la moneda de la cartera.
    Una moneda desconocida no bloquea — mismo contrato que
    ``analysis.track_record.admission_skip_reason``. Pura, así la página dice lo
    mismo que el store.
    """
    ccy = str(currency or "").strip()
    if not ccy or ccy == PORTFOLIO.base_currency:
        return None
    return (
        f"cotiza en {ccy} y la cartera se lleva en {PORTFOLIO.base_currency}: "
        f"su costo y su valor se sumarían como si fueran {PORTFOLIO.base_currency} "
        f"(la conversión es #154)"
    )

#: What the annualised figure is, in the words a surface can show (U5-12).
ANNUALIZED_RETURN_CAVEAT = (
    "Crecimiento anualizado del costo total al valor actual, medido desde la "
    "**primera compra**. No es un IRR: no pondera cada aporte por su propia fecha, "
    "así que una compra reciente recibe el mismo tiempo de capitalización que la "
    "más antigua. Un retorno ponderado por dinero es trabajo aparte (X-02). Con menos de "
    "un año desde la primera compra no se anualiza: «—», y el P&L total es el retorno del período."
)


#: Defaults for a lot that does not say where or what it was (IDEA-5, D10): the
#: user's holdings are shares in a broker abroad. They decide, in PR 2, whether a
#: sale is exempt or taxed — never inferred from the ticker.
DEFAULT_LOT_MARKET = "broker del exterior"
DEFAULT_LOT_INSTRUMENT = "acción"
#: A position from before IDEA5-LOTES only had a weighted average: its single
#: lot carries this label so nobody reads it as a real purchase (D8).
MIGRATED_LOT_LABEL = "costo promedio migrado"



def _parse_date(raw: Any) -> Optional[datetime]:
    """An ISO date as a naive ``datetime``, or ``None`` when it is empty or unreadable.

    A date with a UTC offset is read and its offset dropped: the rest of the tracker compares naive
    datetimes, and subtracting an aware one from ``datetime.now()`` raises.
    """
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _usable_price(info: Optional[Dict]) -> Optional[float]:
    """The quote in ``info`` when it is a finite number above zero; ``None`` otherwise."""
    for key in ("currentPrice", "regularMarketPrice"):
        try:
            price = float((info or {}).get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            return price
    return None


def priced_values(values: Dict[str, Dict]) -> Dict[str, Dict]:
    """The rows of ``get_current_values()`` that have a quote."""
    return {sym: v for sym, v in values.items() if v.get("priced", True)}


def unpriced_symbols(values: Dict[str, Dict]) -> List[str]:
    """The symbols of ``get_current_values()`` with no quote, in book order."""
    return [sym for sym, v in values.items() if not v.get("priced", True)]


def position_weights_from(values: Dict[str, Dict], require_complete: bool = False) -> Dict[str, float]:
    """symbol → % of the book's value, over the positions that have a quote.

    A position with no quote has no weight: it is absent from the result (the page shows "—"),
    never 0 % (AUDIT-NUMB-2). The weights of the priced ones are shares of the PRICED total, so
    with a missing quote they add up to 100 over a book that is not the whole book: any decision
    that reads them (drift, rebalancing, concentration) passes ``require_complete=True`` and gets
    ``{}`` instead, and says which symbols are missing.
    """
    if require_complete and unpriced_symbols(values):
        return {}
    priced = priced_values(values)
    total = sum(v["market_value"] for v in priced.values())
    if total == 0:
        return {}
    return {sym: round(v["market_value"] / total * 100, 1) for sym, v in priced.items()}


def sector_weights_from(values: Dict[str, Dict], require_complete: bool = False) -> Dict[str, float]:
    """sector → % of the book's value; same rules as ``position_weights_from``."""
    if require_complete and unpriced_symbols(values):
        return {}
    priced = priced_values(values)
    total = sum(v["market_value"] for v in priced.values())
    if total == 0:
        return {}
    sector_totals: Dict[str, float] = {}
    for v in priced.values():
        sector_totals[v["sector"]] = sector_totals.get(v["sector"], 0) + v["market_value"]
    return {k: round(v / total * 100, 1) for k, v in sorted(sector_totals.items(), key=lambda x: -x[1])}


@dataclass
class Lot:
    """One purchase. The law takes cost by FIFO (LIG arts. 149 and 65), so each
    buy is kept on its own instead of being averaged into the position."""

    date: str                # ISO format YYYY-MM-DD
    shares: float
    price_usd: float         # USD per share
    market: str = DEFAULT_LOT_MARKET
    instrument: str = DEFAULT_LOT_INSTRUMENT
    label: str = ""


class Position:
    """A holding as a list of lots (IDEA5-LOTES).

    ``shares``, ``avg_cost``, ``cost_basis`` and ``purchase_date`` are derived
    from the lots, so the thirteen modules that read them did not change. It
    still accepts the old arguments (``shares``, ``avg_cost``,
    ``purchase_date``), which build a single lot.
    """

    def __init__(
        self,
        symbol: str,
        shares: Optional[float] = None,
        avg_cost: Optional[float] = None,
        purchase_date: Optional[str] = None,
        sector: str = "Unknown",
        notes: str = "",
        lots: Optional[List[Lot]] = None,
    ):
        self.symbol = symbol
        self.sector = sector
        self.notes = notes
        if lots is None:
            lots = [Lot(date=purchase_date or "", shares=float(shares or 0.0),
                        price_usd=float(avg_cost or 0.0))]
        self.lots: List[Lot] = list(lots)

    @property
    def shares(self) -> float:
        return sum(lot.shares for lot in self.lots)

    @property
    def cost_basis(self) -> float:
        return sum(lot.shares * lot.price_usd for lot in self.lots)

    @property
    def avg_cost(self) -> float:
        """USD per share, weighted over the lots — what the average used to store."""
        shares = self.shares
        return self.cost_basis / shares if shares else 0.0

    @property
    def purchase_date(self) -> str:
        """The oldest lot's date: the first purchase, i.e. how long the position has been held.

        Not the date it reached the size it has today — that is its newest lot, and it is
        what the risk curve needs (``Portfolio._held_from``).
        """
        dates = [lot.date for lot in self.lots if lot.date]
        return min(dates) if dates else ""

    def to_dict(self) -> Dict:
        return {"symbol": self.symbol, "sector": self.sector, "notes": self.notes,
                "lots": [asdict(lot) for lot in self.lots]}

    @classmethod
    def from_dict(cls, raw: Dict) -> "Position":
        """Read either format: ``lots`` (new) or ``shares``/``avg_cost`` (old)."""
        if "lots" in raw:
            return cls(symbol=raw["symbol"], sector=raw.get("sector", "Unknown"),
                       notes=raw.get("notes", ""), lots=[Lot(**lot) for lot in raw["lots"]])
        pos = cls(symbol=raw["symbol"], shares=raw["shares"], avg_cost=raw["avg_cost"],
                  purchase_date=raw["purchase_date"], sector=raw.get("sector", "Unknown"),
                  notes=raw.get("notes", ""))
        pos.lots[0].label = MIGRATED_LOT_LABEL
        return pos

    def __repr__(self) -> str:
        return (f"Position({self.symbol!r}, shares={self.shares}, avg_cost={self.avg_cost}, "
                f"lots={len(self.lots)})")


@dataclass
class PortfolioMetrics:
    total_value: float = 0.0
    total_cost: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    #: (total_value / total_cost) ** (1/years) − 1, with ``years`` measured from
    #: the EARLIEST purchase. Not an IRR: it weights no cash flow by its own
    #: timing (U5-12). See ``ANNUALIZED_RETURN_CAVEAT``. ``None`` when no position has a readable
    #: purchase date (or no cost): there is no age to annualize over, and 0.0 would read as measured.
    #: Also ``None`` under ``PORTFOLIO.min_annualize_years`` of age: weeks compounded into a year are
    #: not a rate anyone earned (AUDIT-NUMB-6); ``total_pnl_pct`` is the return of the period.
    annualized_return_pct: Optional[float] = None
    #: The day the book turns ``PORTFOLIO.min_annualize_years`` old and the annualised figure appears;
    #: ``None`` when it is already old enough (or has no readable date).
    annualized_measurable_from: Optional[str] = None
    #: The four risk metrics are ``None`` when they were not measured — too short
    #: a shared curve, no spread, no SPY overlap — never 0 or beta 1.0: the page
    #: and the portfolio committee read them as measured (PORTFOLIO-RISK-CERO).
    sharpe_ratio: Optional[float] = None
    #: Sortino: (retorno anualizado − Rf) / desviación bajista contra MAR = Rf
    #: — see ``data.product_ux.DOWNSIDE_RATIO_HELP`` (U1-9b).
    downside_vol_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    beta: Optional[float] = None
    #: Weekly points in the shared curve, and — when that is below
    #: ``PORTFOLIO.min_risk_curve_points`` — the day it will have enough.
    risk_curve_points: int = 0
    risk_measurable_from: Optional[str] = None
    #: Symbols with a lot whose purchase date is missing or unreadable. The risk curve cannot be
    #: windowed without it (AUDIT-RESIDUALES), so the four risk metrics stay ``None`` and these
    #: are the ones to ask a date for.
    risk_undated_symbols: List[str] = field(default_factory=list)
    dividend_income_ytd: float = 0.0
    num_positions: int = 0
    #: Positions the market feed returned no usable price for. They are left out of
    #: ``total_value`` / ``total_cost`` / ``total_pnl`` (never valued at cost): the totals are those
    #: of the priced positions, and the page says which ones are missing (AUDIT-NUMB-2).
    unpriced_symbols: List[str] = field(default_factory=list)


class Portfolio:
    """
    Manages the user's investment portfolio with persistent JSON storage.
    Computes performance metrics on demand.
    """

    def __init__(self, file_path: Path = PORTFOLIO_FILE):
        self.file_path = file_path
        self.positions: Dict[str, Position] = {}
        self._load()

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def add_position(
        self,
        symbol: str,
        shares: float,
        avg_cost: float,
        purchase_date: str,
        notes: str = "",
    ) -> Optional[str]:
        """Add a position, or a new lot to one already held. Returns ``None`` when it was added,
        or the reason it was not — see ``position_currency_skip_reason``."""
        symbol = symbol.upper()
        info = get_info(symbol)
        reason = position_currency_skip_reason(info.get("currency"))
        if reason:
            logger.warning(f"{symbol} not added to portfolio — {reason}")
            return reason
        sector = info.get("sector", "Unknown")

        if symbol in self.positions:
            # IDEA5-LOTES: a new buy is a new lot, not an average (FIFO needs each one).
            existing = self.positions[symbol]
            existing.lots.append(Lot(date=purchase_date, shares=shares, price_usd=avg_cost))
            logger.info(
                f"Added a lot to {symbol}: {existing.shares:.2f} shares @ ${existing.avg_cost:.2f}"
            )
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                shares=shares,
                avg_cost=avg_cost,
                purchase_date=purchase_date,
                sector=sector,
                notes=notes,
            )
            logger.info(f"Added {symbol}: {shares:.2f} shares @ ${avg_cost:.2f}")
        self._save()
        return None

    def update_position(
        self,
        symbol: str,
        shares: float,
        avg_cost: float,
        purchase_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Overwrite an existing position's editable fields and persist.

        Unlike add_position (which adds a lot to an existing holding),
        this sets the values directly — used by the "Editar posición" UI.
        Cost basis, P&L and weights recompute on demand from these values.

        With more than one lot only the notes change (IDEA5-LOTES), and it
        returns False: setting shares and cost would average the lots away.

        Returns True on success, False if the symbol is not held or has lots.
        """
        symbol = symbol.upper()
        if symbol not in self.positions:
            logger.warning(f"{symbol} not in portfolio — cannot update")
            return False

        pos = self.positions[symbol]
        if notes is not None:
            pos.notes = notes
        if len(pos.lots) > 1:
            # IDEA5-LOTES (Q2): overwriting shares and cost would average the lots
            # back into one and lose each purchase. Only the notes change; lots are
            # edited one by one in IDEA-5's PR 2.
            self._save()
            logger.warning(f"{symbol} has {len(pos.lots)} lots — only its notes were updated")
            return False

        lot = pos.lots[0]
        lot.shares = shares
        lot.price_usd = avg_cost
        if purchase_date is not None:
            lot.date = purchase_date

        self._save()
        logger.info(f"Updated {symbol}: {shares:.2f} shares @ ${avg_cost:.2f}")
        return True

    def remove_position(self, symbol: str, shares: Optional[float] = None) -> None:
        symbol = symbol.upper()
        if symbol not in self.positions:
            logger.warning(f"{symbol} not in portfolio")
            return
        if shares is None or shares >= self.positions[symbol].shares:
            del self.positions[symbol]
            logger.info(f"Closed {symbol}")
        else:
            # FIFO (LIG arts. 149 and 65): the oldest lots go first.
            pos = self.positions[symbol]
            left = shares
            for lot in sorted(pos.lots, key=lambda lot: lot.date):
                taken = min(lot.shares, left)
                lot.shares -= taken
                left -= taken
                if left <= 0:
                    break
            pos.lots = [lot for lot in pos.lots if lot.shares > 0]
            logger.info(f"Reduced {symbol} by {shares:.2f} shares")
        self._save()

    # ------------------------------------------------------------------ #
    #  Valuation & Metrics                                                 #
    # ------------------------------------------------------------------ #

    def get_current_values(self) -> Dict[str, Dict]:
        """Return current market value per position.

        A position with no usable quote is NOT valued at its cost (AUDIT-NUMB-2): its row carries
        ``priced: False`` and ``None`` in ``current_price`` / ``market_value`` / ``pnl`` /
        ``pnl_pct``. Valuing it at cost made a position the market could not price read as +0 %,
        added a number nobody observed to the total and diluted every weight. Callers sum the
        priced rows (``priced_values``) and name the others (``unpriced_symbols``).
        """
        values = {}
        for sym, pos in self.positions.items():
            info = get_info(sym)
            price = _usable_price(info)
            row = {
                "symbol": sym,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "current_price": price,
                "cost_basis": pos.cost_basis,
                "market_value": None,
                "pnl": None,
                "pnl_pct": None,
                "sector": pos.sector,
                "purchase_date": pos.purchase_date,
                "priced": price is not None,
            }
            if price is not None:
                row["market_value"] = price * pos.shares
                row["pnl"] = row["market_value"] - pos.cost_basis
                row["pnl_pct"] = row["pnl"] / pos.cost_basis * 100 if pos.cost_basis > 0 else 0
            values[sym] = row
        return values

    def compute_metrics(self) -> PortfolioMetrics:
        metrics = PortfolioMetrics()
        if not self.positions:
            return metrics

        values = self.get_current_values()
        metrics.num_positions = len(values)
        # Totals over the positions with a quote: value and cost of the same set, so the P&L of
        # the book is not a priced value minus an unpriced cost (AUDIT-NUMB-2).
        priced = priced_values(values)
        metrics.unpriced_symbols = unpriced_symbols(values)
        metrics.total_value = sum(v["market_value"] for v in priced.values())
        metrics.total_cost = sum(v["cost_basis"] for v in priced.values())
        metrics.total_pnl = metrics.total_value - metrics.total_cost
        metrics.total_pnl_pct = (
            metrics.total_pnl / metrics.total_cost * 100 if metrics.total_cost > 0 else 0
        )

        # Annualised growth of cost → value. NOT an IRR (U5-12): `years` comes
        # from the earliest purchase, so every dollar is credited with the age of
        # the oldest one. See ANNUALIZED_RETURN_CAVEAT.
        # The age is that of the priced positions: the totals above leave the unpriced ones out, and
        # an old unpriced position must not set the exponent of a value it is not part of.
        dates = [d for d in (_parse_date(self.positions[s].purchase_date) for s in priced) if d]
        if dates:
            start = min(dates)
            years = (datetime.now() - start).days / 365.25
            if years < PORTFOLIO.min_annualize_years:
                # Younger than the minimum: not annualised (AUDIT-NUMB-6). The first day that
                # reaches it, counted in the same whole days the age above uses.
                metrics.annualized_measurable_from = (
                    start + timedelta(days=math.ceil(PORTFOLIO.min_annualize_years * 365.25))
                ).date().isoformat()
            elif metrics.total_cost > 0:
                metrics.annualized_return_pct = (
                    (metrics.total_value / metrics.total_cost) ** (1 / years) - 1
                ) * 100

        # Sharpe / downside-vol ratio / Drawdown from portfolio equity curve.
        # Below the minimum they stay None: not measured is not 0 (and beta is
        # not 1.0) — PORTFOLIO-RISK-CERO.
        min_points = PORTFOLIO.min_risk_curve_points
        metrics.risk_undated_symbols = self.undated_symbols()
        equity_curve = self._build_equity_curve()
        metrics.risk_curve_points = 0 if equity_curve is None else len(equity_curve)
        if metrics.risk_curve_points < min_points:
            # The curve is short for one of two reasons. Usually the newest lot: it opens
            # on the first weekly bar after that purchase, and the date is the purchase
            # plus the missing weeks. But a position whose feed has fewer bars than the
            # window (a recent listing) opens the curve LATER than the purchase, and a
            # date counted from the purchase would be in the past — "measurable from
            # 2025-02-03" in October 2026. Then the first bar of the curve is the anchor.
            anchor = self._held_from()
            if equity_curve is not None and len(equity_curve):
                first_bar = equity_curve.index[0]
                if anchor is None or first_bar - anchor > pd.Timedelta(weeks=1):
                    anchor = first_bar
            if anchor is not None:
                metrics.risk_measurable_from = (
                    anchor + pd.Timedelta(weeks=min_points - 1)
                ).date().isoformat()
        if equity_curve is not None and len(equity_curve) >= min_points:
            returns = equity_curve.pct_change().dropna()
            annual_factor = 52  # weekly returns
            mean_ret = returns.mean() * annual_factor
            std_ret = returns.std() * np.sqrt(annual_factor)
            rf = RISK_FREE.annual_fraction  # unified 10Y Treasury proxy (U5-10)

            metrics.sharpe_ratio = round((mean_ret - rf) / std_ret, 2) if std_ret > 0 else None

            # Sortino (U1-9b): the Sharpe's excess over the downside deviation
            # of every week against MAR = Rf — the helper Backtesting uses too.
            # No week below the MAR: undefined, so None.
            downside_std = downside_deviation(returns, rf, annual_factor)
            metrics.downside_vol_ratio = (
                round((mean_ret - rf) / downside_std, 2) if downside_std else None
            )

            rolling_max = equity_curve.cummax()
            drawdown = (equity_curve - rolling_max) / rolling_max
            metrics.max_drawdown_pct = round(float(drawdown.min()) * 100, 2)

            # Beta vs SPY
            spy = get_history("SPY", period="5y", interval="1wk")
            if not spy.empty:
                spy_ret = spy["close"].pct_change().dropna()
                port_ret = returns.reindex(spy_ret.index).dropna()
                spy_ret = spy_ret.reindex(port_ret.index).dropna()
                if len(port_ret) >= min_points:
                    cov = np.cov(port_ret, spy_ret)
                    metrics.beta = round(cov[0, 1] / cov[1, 1], 2) if cov[1, 1] != 0 else None

        return metrics

    def get_sector_weights(self, require_complete: bool = False) -> Dict[str, float]:
        """Return sector → % of portfolio weight. See ``sector_weights_from``."""
        return sector_weights_from(self.get_current_values(), require_complete)

    def get_position_weights(self, require_complete: bool = False) -> Dict[str, float]:
        """Return symbol → % of portfolio weight. See ``position_weights_from``."""
        return position_weights_from(self.get_current_values(), require_complete)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _build_equity_curve(self) -> Optional[pd.Series]:
        """Weekly equity curve over the window in which every position was held.

        U5-12: this used to multiply five years of prices by ``pos.shares`` — the
        count as of *now* — for every holding regardless of when it was bought, so
        a stock bought last month sat in the portfolio's 2021 drawdown at full
        size. Sharpe, the downside-vol ratio, max drawdown and beta are all read
        off this series, so the fabricated history reached four metrics at once.

        The window therefore starts at the **latest** purchase date — of any *lot*,
        not of any position: ``pos.shares`` sums every lot, so a position with 10
        shares from 2022 and 10 more from last month entered every week since 2022
        at 20 shares (IDEA5-LOTES reintroduced the fabrication inside a position;
        see ``_held_from``). Shorter is the honest answer, and ``compute_metrics``
        leaves the metrics ``None`` when too little of it survives rather than
        estimating from it — ``None``, not the 0 / beta 1.0 defaults it used to
        leave (PORTFOLIO-RISK-CERO).

        Zeroing each position before its own purchase is the other way to keep the
        share counts honest, and it is worse: a purchase would enter the series as
        a step change, and a purchase is not a return. Measured on a two-position
        book it reported 60.8 % volatility against 18.8 %.
        """
        undated = self.undated_symbols()
        if undated:
            # A lot with no readable date cannot be placed in time, so neither can the window:
            # without it the curve multiplies five years of prices by today's shares. Not measured.
            logger.info(f"Equity curve not built: lots without a readable date in {', '.join(undated)}")
            return None
        try:
            curves = []
            for sym, pos in self.positions.items():
                hist = get_history(sym, period="5y", interval="1wk")
                if hist.empty:
                    continue
                weighted = hist["close"] * pos.shares
                curves.append(weighted)
            if not curves:
                return None
            # Only the weeks in which EVERY position has a price. ``sum(axis=1)`` skips
            # NaN, so a missing price used to count that position as 0: 0700.HK and
            # 7203.T have no bar for the current week until their market opens, and the
            # whole value of the position vanished in the curve's last point. (The
            # ``.dropna()`` that sat after the sum never fired — a sum of NaN is 0.)
            combined = pd.concat(curves, axis=1).dropna(how="any").sum(axis=1)

            held_from = self._held_from()
            if held_from is not None:
                combined = combined[combined.index >= held_from]
            return combined if not combined.empty else None
        except Exception as exc:
            logger.error(f"Equity curve error: {exc}")
            return None

    def _held_from(self) -> Optional[pd.Timestamp]:
        """The date from which every position was held at the size it has today.

        That is the date of the newest **lot** of any position: ``Position.shares``
        sums every lot, and a lot bought last month was not in the portfolio three
        years ago. The oldest lot (``Position.purchase_date``) is the right date for
        "how long have I held this" and the wrong one here. A lot with no readable
        date returns ``None``: there is no way to say when those shares entered. That
        is not "no filter" for the curve — ``_build_equity_curve`` does not build one
        while a lot is undated (``undated_symbols``) — it only leaves no anchor date.
        """
        dates = []
        for pos in self.positions.values():
            for lot in pos.lots:
                parsed = _parse_date(lot.date)
                if parsed is None:
                    return None
                dates.append(pd.Timestamp(parsed))
        return max(dates) if dates else None

    def undated_symbols(self) -> List[str]:
        """Symbols with at least one lot whose purchase date is missing or unreadable, sorted."""
        return sorted(
            sym for sym, pos in self.positions.items()
            if any(_parse_date(lot.date) is None for lot in pos.lots)
        )

    def _save(self) -> None:
        if self._legacy_on_disk:
            # IDEA5-LOTES: the first write in the lots format keeps the old file.
            backup = self.file_path.with_name(self.file_path.name + ".bak-pre-lotes")
            if not backup.exists():
                backup.write_text(self.file_path.read_text())
                logger.info(f"Portfolio backed up before the lots format: {backup}")
            self._legacy_on_disk = False
        if self._unreadable_on_disk:
            # A file that failed to load would be overwritten with the empty
            # portfolio in memory: set it aside first, untouched.
            aside = self.file_path.with_name(
                f"{self.file_path.name}.unreadable-{datetime.now():%Y%m%d-%H%M%S}"
            )
            self.file_path.replace(aside)
            logger.error(f"Portfolio file could not be read; kept as {aside}")
            self._unreadable_on_disk = False
        elif self.file_path.exists():
            # Rolling backup: if an older checkout overwrites the file (it cannot
            # read lots and starts empty), the last state written here survives.
            self.file_path.with_name(self.file_path.name + ".bak").write_text(
                self.file_path.read_text()
            )
        data = {sym: pos.to_dict() for sym, pos in self.positions.items()}
        self.file_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        self._legacy_on_disk = False
        self._unreadable_on_disk = False
        if self.file_path.exists():
            try:
                data = json.loads(self.file_path.read_text())
                self.positions = {sym: Position.from_dict(pos) for sym, pos in data.items()}
                self._legacy_on_disk = any("lots" not in pos for pos in data.values())
            except Exception as exc:
                self.positions = {}
                self._unreadable_on_disk = True
                logger.error(f"Failed to load portfolio: {exc}")
