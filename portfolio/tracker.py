"""
Portfolio tracker — records positions and computes performance metrics.

Metrics computed:
  - Total return, and an annualised growth of cost → value. **Not an IRR** — see
    ``ANNUALIZED_RETURN_CAVEAT`` (U5-12). A real money-weighted return is X-02.
  - Sharpe Ratio, ratio retorno/vol bajista (no es Sortino — U1-9)
  - Max Drawdown
  - Portfolio Beta (vs SPY)
  - Sector weights
  - Dividend income received
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
from loguru import logger

from config import DB_PATH, RISK_FREE
from data.fetcher import get_history, get_info

PORTFOLIO_FILE = DB_PATH.parent / "portfolio.json"

#: What the annualised figure is, in the words a surface can show (U5-12).
ANNUALIZED_RETURN_CAVEAT = (
    "Crecimiento anualizado del costo total al valor actual, medido desde la "
    "**primera compra**. No es un IRR: no pondera cada aporte por su propia fecha, "
    "así que una compra reciente recibe el mismo tiempo de capitalización que la "
    "más antigua. Un retorno ponderado por dinero es trabajo aparte (X-02)."
)


@dataclass
class Position:
    symbol: str
    shares: float
    avg_cost: float          # USD per share
    purchase_date: str       # ISO format YYYY-MM-DD
    sector: str = "Unknown"
    notes: str = ""

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost


@dataclass
class PortfolioMetrics:
    total_value: float = 0.0
    total_cost: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    #: (total_value / total_cost) ** (1/years) − 1, with ``years`` measured from
    #: the EARLIEST purchase. Not an IRR: it weights no cash flow by its own
    #: timing (U5-12). See ``ANNUALIZED_RETURN_CAVEAT``.
    annualized_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    #: (retorno anualizado − Rf) / desvío de las semanas negativas. **Not a
    #: Sortino ratio** — see ``data.product_ux.DOWNSIDE_RATIO_HELP`` (U1-9).
    downside_vol_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    beta: float = 1.0
    dividend_income_ytd: float = 0.0
    num_positions: int = 0


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
    ) -> None:
        symbol = symbol.upper()
        info = get_info(symbol)
        sector = info.get("sector", "Unknown")

        if symbol in self.positions:
            # Average down/up
            existing = self.positions[symbol]
            total_shares = existing.shares + shares
            total_cost = existing.cost_basis + shares * avg_cost
            existing.shares = total_shares
            existing.avg_cost = total_cost / total_shares
            logger.info(f"Updated {symbol}: {total_shares:.2f} shares @ ${existing.avg_cost:.2f}")
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

        Unlike add_position (which averages cost into an existing holding),
        this sets the values directly — used by the "Editar posición" UI.
        Cost basis, P&L and weights recompute on demand from these values.

        Returns True on success, False if the symbol is not held.
        """
        symbol = symbol.upper()
        if symbol not in self.positions:
            logger.warning(f"{symbol} not in portfolio — cannot update")
            return False

        pos = self.positions[symbol]
        pos.shares = shares
        pos.avg_cost = avg_cost
        if purchase_date is not None:
            pos.purchase_date = purchase_date
        if notes is not None:
            pos.notes = notes

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
            self.positions[symbol].shares -= shares
            logger.info(f"Reduced {symbol} by {shares:.2f} shares")
        self._save()

    # ------------------------------------------------------------------ #
    #  Valuation & Metrics                                                 #
    # ------------------------------------------------------------------ #

    def get_current_values(self) -> Dict[str, Dict]:
        """Return current market value per position."""
        values = {}
        for sym, pos in self.positions.items():
            info = get_info(sym)
            price = float(info.get("currentPrice") or info.get("regularMarketPrice") or pos.avg_cost)
            market_value = price * pos.shares
            pnl = market_value - pos.cost_basis
            pnl_pct = pnl / pos.cost_basis * 100 if pos.cost_basis > 0 else 0
            values[sym] = {
                "symbol": sym,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "current_price": price,
                "cost_basis": pos.cost_basis,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "sector": pos.sector,
                "purchase_date": pos.purchase_date,
            }
        return values

    def compute_metrics(self) -> PortfolioMetrics:
        metrics = PortfolioMetrics()
        if not self.positions:
            return metrics

        values = self.get_current_values()
        metrics.num_positions = len(values)
        metrics.total_value = sum(v["market_value"] for v in values.values())
        metrics.total_cost = sum(v["cost_basis"] for v in values.values())
        metrics.total_pnl = metrics.total_value - metrics.total_cost
        metrics.total_pnl_pct = (
            metrics.total_pnl / metrics.total_cost * 100 if metrics.total_cost > 0 else 0
        )

        # Annualised growth of cost → value. NOT an IRR (U5-12): `years` comes
        # from the earliest purchase, so every dollar is credited with the age of
        # the oldest one. See ANNUALIZED_RETURN_CAVEAT.
        dates = [
            datetime.fromisoformat(self.positions[s].purchase_date)
            for s in self.positions
        ]
        if dates:
            start = min(dates)
            years = max((datetime.now() - start).days / 365.25, 0.1)
            if metrics.total_cost > 0:
                metrics.annualized_return_pct = (
                    (metrics.total_value / metrics.total_cost) ** (1 / years) - 1
                ) * 100

        # Sharpe / downside-vol ratio / Drawdown from portfolio equity curve
        equity_curve = self._build_equity_curve()
        if equity_curve is not None and len(equity_curve) > 10:
            returns = equity_curve.pct_change().dropna()
            annual_factor = 52  # weekly returns
            mean_ret = returns.mean() * annual_factor
            std_ret = returns.std() * np.sqrt(annual_factor)
            rf = RISK_FREE.annual_fraction  # unified 10Y Treasury proxy (U5-10)

            metrics.sharpe_ratio = round((mean_ret - rf) / std_ret, 2) if std_ret > 0 else 0

            # Not a Sortino ratio (U1-9): this is the spread of the losing
            # weeks around their own mean, where Sortino needs
            # √E[mín(r − MAR, 0)²] over every return, measured from the MAR.
            # The formula stays as it is on purpose — relabelling and
            # recomputing in one pass is the U1-9 ``no_hacer``.
            downside = returns[returns < 0]
            downside_std = downside.std() * np.sqrt(annual_factor) if len(downside) > 0 else 0
            metrics.downside_vol_ratio = (
                round((mean_ret - rf) / downside_std, 2) if downside_std > 0 else 0
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
                if len(port_ret) > 10:
                    cov = np.cov(port_ret, spy_ret)
                    metrics.beta = round(cov[0, 1] / cov[1, 1], 2) if cov[1, 1] != 0 else 1.0

        return metrics

    def get_sector_weights(self) -> Dict[str, float]:
        """Return sector → % of portfolio weight."""
        values = self.get_current_values()
        total = sum(v["market_value"] for v in values.values())
        if total == 0:
            return {}
        sector_totals: Dict[str, float] = {}
        for v in values.values():
            sector_totals[v["sector"]] = sector_totals.get(v["sector"], 0) + v["market_value"]
        return {k: round(v / total * 100, 1) for k, v in sorted(sector_totals.items(), key=lambda x: -x[1])}

    def get_position_weights(self) -> Dict[str, float]:
        values = self.get_current_values()
        total = sum(v["market_value"] for v in values.values())
        if total == 0:
            return {}
        return {sym: round(v["market_value"] / total * 100, 1) for sym, v in values.items()}

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

        The window therefore starts at the **latest** purchase date. Shorter is
        the honest answer, and ``compute_metrics`` already suppresses the metrics
        when too little of it survives rather than estimating from it.

        Zeroing each position before its own purchase is the other way to keep the
        share counts honest, and it is worse: a purchase would enter the series as
        a step change, and a purchase is not a return. Measured on a two-position
        book it reported 60.8 % volatility against 18.8 %.
        """
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
            combined = pd.concat(curves, axis=1).sum(axis=1).dropna()

            held_from = self._held_from()
            if held_from is not None:
                combined = combined[combined.index >= held_from]
            return combined if not combined.empty else None
        except Exception as exc:
            logger.error(f"Equity curve error: {exc}")
            return None

    def _held_from(self) -> Optional[pd.Timestamp]:
        """The date from which every current position was already held."""
        dates = []
        for pos in self.positions.values():
            try:
                dates.append(pd.Timestamp(datetime.fromisoformat(pos.purchase_date)))
            except (TypeError, ValueError):
                return None
        return max(dates) if dates else None

    def _save(self) -> None:
        data = {sym: asdict(pos) for sym, pos in self.positions.items()}
        self.file_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        if self.file_path.exists():
            try:
                data = json.loads(self.file_path.read_text())
                self.positions = {sym: Position(**pos) for sym, pos in data.items()}
            except Exception as exc:
                logger.error(f"Failed to load portfolio: {exc}")
