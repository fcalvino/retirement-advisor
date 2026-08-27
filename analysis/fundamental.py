"""
Fundamental analysis module.

Scoring model (0–100):
  Profitability     25 pts  — ROE, ROIC, net margin, gross margin
  Financial Health  20 pts  — D/E, current ratio, interest coverage
  Valuation         25 pts  — P/E, PEG, EV/EBITDA, P/B
  Growth            20 pts  — revenue CAGR, EPS CAGR, FCF growth
  Dividend Quality  10 pts  — yield, payout ratio, growth streak

Crypto assets (BTC, ETH …) are routed to CryptoAnalyzer early in analyze()
and bypass the equity-specific scoring entirely.  They return the same
FundamentalResult with equity fields set to None and is_crypto=True.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Optional

import pandas as pd
from loguru import logger

from analysis.moat import MoatAnalyzer, MoatDetail
from analysis.scoring import ConsistencyDetail, EnhancedScoring, PiotroskiDetail
from analysis.tailwind import TailwindAnalyzer, TailwindDetail
from config import STRATEGY
from config import THRESHOLDS as T
from data.fetcher import (
    _safe_float,
    compute_cagr,
    compute_cagr_available,
    get_dividends,
    get_financials,
    get_info,
)
from data.product_ux import dividend_streak_note


@dataclass
class FundamentalResult:
    symbol: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float = 0.0
    current_price: float = 0.0

    # Sub-scores (0–max_pts each)
    profitability_score: float = 0.0   # /25
    health_score: float = 0.0          # /20
    valuation_score: float = 0.0       # /25
    growth_score: float = 0.0          # /20
    dividend_score: float = 0.0        # /10
    total_score: float = 0.0           # /100

    # Key metrics (for display)
    roe: Optional[float] = None
    roic: Optional[float] = None
    net_margin: Optional[float] = None
    gross_margin: Optional[float] = None
    debt_equity: Optional[float] = None
    # True when the balance sheet reports negative shareholders' equity. yfinance
    # simply omits `debtToEquity` for these companies, so the ratio is None — not
    # high — and both the leverage guard and the negative-book guard in
    # analysis/strategy.py used to skip them silently. See _score_financial_health.
    negative_equity: bool = False
    current_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    pe_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    pb_ratio: Optional[float] = None
    revenue_cagr_5y: Optional[float] = None
    eps_cagr_5y: Optional[float] = None
    # Window each CAGR was actually measured over, in years (0 = not computed).
    # yfinance ships 4 annual statements, so these are typically 3 — the "5y" in
    # the field names above is historical and the UI must read these instead of
    # labelling the numbers "5Y". See compute_cagr_available().
    revenue_cagr_years: int = 0
    eps_cagr_years: int = 0
    # Where the earnings-growth figure came from: "statement_cagr" (compounded off
    # the annual income statements — preferred) or "yoy" (yfinance's `earningsGrowth`,
    # a single quarter against the same quarter a year earlier, hence the window of
    # 1). The two are not interchangeable and the UI must not label the second a CAGR.
    eps_growth_source: str = ""
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    # Dividends over accounting profit, in percent — the figure that reconciles with a
    # filing, kept unchanged for reporting. It is **not** what the engine judges: for a
    # REIT it routinely exceeds 100 % by construction (O 236 %, MAA 178 %). Anything
    # that decides whether a dividend is sustainable reads the pair below instead,
    # which the dividend dimension fills in from effective_payout_pct().
    payout_ratio: Optional[float] = None
    payout_ratio_effective: Optional[float] = None
    payout_basis: str = "earnings"          # "ffo" for REITs with FFO | "earnings"

    # Intrinsic value estimate (Graham formula)
    graham_value: Optional[float] = None
    margin_of_safety_pct: Optional[float] = None

    # REIT metrics (audit por industria, 2026-08-22). Populated only for companies
    # classified as REITs by analysis/company_type.py; None everywhere else. A REIT
    # is valued on funds from operations because depreciation — its largest income
    # statement charge — is not a cash outflow, so P/E and the accounting payout
    # measure something other than what their thresholds assume.
    ffo: Optional[float] = None
    p_ffo: Optional[float] = None
    ffo_payout_pct: Optional[float] = None

    # Shareholders' equity over total assets, in percent. Not scored today: it is
    # captured so the open question — which capital ratio separates a solid bank
    # from a fragile one — has data to be answered from. A bank's whole Financial
    # Health dimension is unmeasurable with the working-capital ratios (37 of its
    # 100 points), and this is the ratio that replaces them; big US banks sit around
    # 8–12 %. It cannot be reconstructed after the fact, which is why it is stored
    # before anyone knows the bands.
    equity_to_assets_pct: Optional[float] = None

    # Enhanced scoring (Phase 1.5)
    consistency_score: float = 0.0          # 0–15 pts
    piotroski_score: int = 0                # 0–9
    piotroski_bonus: float = 0.0            # bonus applied to adjusted_score
    adjusted_score: float = 0.0             # total_score + consistency + piotroski_bonus + moat_bonus, capped at 100
    # Same sum, uncapped (audit item 11). The [0,100] clamp on adjusted_score keeps
    # the scale legible and every existing threshold valid, but it destroys ordering
    # exactly at the top, where it matters most: INTU/META/GOOGL all display 100.0
    # while really scoring 107.9 / 104.0 / 103.0. Consumers that need to *rank* read
    # this; consumers that need to *judge* keep reading adjusted_score.
    raw_adjusted_score: float = 0.0
    consistency_detail: Optional[ConsistencyDetail] = None   # per-signal breakdown
    piotroski_detail: Optional[PiotroskiDetail] = None       # per-criterion F1–F9 breakdown

    # Moat scoring (Phase 3)
    moat_score: float = 0.0                 # 0–20 equity (quant 0–12 + AI 0–8) | 0–8 crypto (AI only)
    moat_bonus: float = 0.0                 # added to adjusted_score
    moat_classification: str = "None"       # Wide | Narrow | Minimal | None
    moat_detail: Optional[MoatDetail] = None

    # Sector-country structural tailwind (Idea 2)
    tailwind_score: float = 0.0                  # -5…+10 curated structural outlook
    tailwind_bonus: float = 0.0                  # capped additive bonus (can be negative)
    tailwind_classification: str = "Neutral"     # Strong | Moderate | Neutral | Headwind
    tailwind_detail: Optional[TailwindDetail] = None

    # Asset class (audit item 01) — "equity" | "fund" | "crypto".
    # Funds and crypto have no financial statements, so total_score/adjusted_score
    # and the signal derived from them do not apply to them. See analysis/asset_class.py.
    asset_class: str = "equity"

    # Crypto asset fields (Phase 4)
    is_crypto: bool = False                  # True when analyzed via CryptoAnalyzer
    crypto_moat_detail: Optional[Any] = None # CryptoMoatDetail — typed as Any to avoid circular import

    # Internal: TechnicalResult cached by CryptoAnalyzer to avoid duplicate yfinance call
    # full_analysis() in strategy.py reuses this instead of calling TechnicalAnalyzer again.
    _cached_tech: Optional[Any] = None

    # Data-quality transparency (Fase E) — see compute_data_quality()
    data_quality: Optional[Dict[str, Any]] = None

    # Human-readable breakdown
    notes: Dict[str, str] = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def is_value_stock(self) -> bool:
        return (
            self.margin_of_safety_pct is not None
            and self.margin_of_safety_pct >= STRATEGY.min_margin_of_safety_pct
        )


# ------------------------------------------------------------------ #
#  Data quality (Fase E)                                               #
# ------------------------------------------------------------------ #

# Equity key metrics whose absence (None) means yfinance returned partial
# data and the corresponding score dimension silently fell back to neutral.
# dividend_yield is deliberately excluded: None is legitimate for growth stocks.
def normalize_dividend_yield_pct(
    info: Dict[str, Any],
    *,
    warnings: Optional[list] = None,
    config=None,
) -> Optional[float]:
    """Resolve a dividend yield **in percent** from a yfinance ``info`` dict.

    Pure function (no network) so the unit handling is testable offline.

    yfinance does not use one convention for its dividend fields, and the mix is
    what produced yields like 313% on the Screener (measured 2026-08-17,
    yfinance 1.4.0):

        field                         unit         SCHD      SPY       KO
        trailingAnnualDividendRate    $/share      0.0       5.662     2.08
        trailingAnnualDividendYield   fraction     0.0       0.0073    0.0237
        dividendYield                 PERCENT      3.13      1.01      2.42

    The old code did ``(trailingAnnualDividendYield or dividendYield) * 100``.
    For SCHD the first term is a falsy 0.0, so it fell through to ``dividendYield``
    — already a percent — and multiplied it by 100 again. SCHD 3.13% became 313%,
    BND 4.03% became 403%, VGT 0.38% became 38%. That is not only a display bug:
    ``_score_dividends`` grades against ``div_yield_sweet_spot_high``, so those
    tickers were scored as dangerously high-yield instead of healthy.

    Resolution order, each step with a known unit rather than a guess:
      1. ``trailingAnnualDividendRate / price`` — the definition itself
         (trailing 12m dividends over current price), so no unit ambiguity
      2. ``trailingAnnualDividendYield`` — documented fraction, ×100
      3. ``dividendYield`` — already a percent in yfinance ≥ 0.2, used as-is

    Step 1 stays first so every ticker that already resolved correctly keeps its
    exact value; only the ones that used to fall through change.

    Returns ``None`` when no field yields a usable number, or when the result is
    implausible (above ``THRESHOLDS.max_plausible_dividend_yield_pct``) — a
    yield that large means the feed changed conventions again, and a loud None
    beats a confident wrong number.
    """
    if config is None:
        from config import THRESHOLDS as config  # noqa: N811 — singleton default

    div_yield: Optional[float] = None
    source = ""

    # 1. Derived from the definition — immune to the feed's unit choices.
    annual_rate = _safe_float(info.get("trailingAnnualDividendRate"))
    price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
    if annual_rate > 0 and price > 0:
        div_yield = annual_rate / price * 100
        source = "trailingAnnualDividendRate/price"

    # 2. Documented as a fraction of price.
    if div_yield is None:
        tay = _safe_float(info.get("trailingAnnualDividendYield"))
        if tay > 0:
            div_yield = tay * 100
            source = "trailingAnnualDividendYield"

    # 3. Already a percent — must NOT be multiplied. This is the step the old
    #    code got wrong, and the one ETFs and bond funds actually land on.
    if div_yield is None:
        dy = _safe_float(info.get("dividendYield"))
        if dy > 0:
            div_yield = dy
            source = "dividendYield"

    if div_yield is None or div_yield <= 0:
        return None

    ceiling = float(getattr(config, "max_plausible_dividend_yield_pct", 30.0))
    if div_yield > ceiling:
        msg = (
            f"Dividend yield descartado por implausible: {div_yield:.1f}% "
            f"(fuente {source}, techo {ceiling:.0f}%) — probable cambio de unidad en el feed."
        )
        logger.warning(msg)
        if warnings is not None:
            warnings.append(msg)
        return None

    return div_yield


def reported_metric(info: Dict[str, Any], *keys: str) -> Optional[float]:
    """First of *keys* the feed actually reports as a finite number, else ``None``.

    Pure function. Exists to keep "the feed omitted this" distinguishable from
    "the feed says zero" — ``_safe_float`` collapses both to ``0.0``, and every
    scoring band in this module is an *upper* bound, so a collapsed ``0.0`` walks
    straight into the "cheap / low debt" branch. See ``reported_positive_metric``.
    """
    for key in keys:
        raw = info.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
            continue
        return value
    return None


def reported_positive_metric(info: Dict[str, Any], *keys: str) -> Optional[float]:
    """Like :func:`reported_metric` but only for metrics a non-positive value kills.

    A negative or zero P/E, PEG, EV/EBITDA or P/B is not a cheap multiple — it is
    a company with no earnings, no EBITDA or no book value, i.e. a multiple that
    cannot be scored at all. Returning ``None`` sends those to zero points rather
    than to the top band.
    """
    value = reported_metric(info, *keys)
    return value if value is not None and value > 0 else None


#: Row names yfinance uses for depreciation & amortization, in preference order.
_DA_ROWS = (
    "Depreciation And Amortization",
    "Depreciation Amortization Depletion",
    "Depreciation & Amortization",
    "Reconciled Depreciation",
)

#: Row names for dividends actually paid (a negative number on the cash flow).
_DIVIDENDS_PAID_ROWS = (
    "Cash Dividends Paid",
    "Common Stock Dividend Paid",
    "Dividends Paid",
)


def _latest_row_value(df: pd.DataFrame, names) -> Optional[float]:
    """Most recent non-NaN value for the first matching row, or None."""
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            series = df.loc[name].dropna()
            if not series.empty:
                try:
                    return float(series.iloc[0])
                except (TypeError, ValueError):
                    continue
    return None


def compute_ffo(income_stmt: pd.DataFrame, cashflow: pd.DataFrame) -> Optional[float]:
    """Funds from operations: ``net income + depreciation & amortization``.

    Pure function. This is the standard approximation and **not** the NAREIT
    definition, which also backs out gains on property sales — those are not
    separable from the statements yfinance ships, so a REIT that sold a building
    at a profit will show FFO slightly high here. Worth knowing before quoting the
    number as if it came from a filing.

    Why a REIT needs it at all: depreciation is the largest charge on its income
    statement and is not a cash outflow, so accounting profit understates what the
    business actually earned and overstates every multiple built on it. Measured on
    the universe (2026-08-22), O showed a P/E of 45.7 against a P/FFO of 16.5, and
    a payout of 236 % against 70 %. Computable for 12 of the 13 cached REITs.
    """
    net_income = _latest_row_value(income_stmt, ["Net Income"])
    da = _latest_row_value(cashflow, _DA_ROWS)
    if da is None:
        da = _latest_row_value(income_stmt, _DA_ROWS)

    if net_income is None or da is None:
        return None

    ffo = net_income + da
    return ffo if ffo > 0 else None


def compute_ffo_payout_pct(cashflow: pd.DataFrame, ffo: Optional[float]) -> Optional[float]:
    """Dividends paid over FFO, in percent — the payout that means something here.

    Taken from the definition (cash actually distributed over funds from
    operations) rather than by rescaling the accounting payout, because
    ``Cash Dividends Paid`` is present in 13 of 13 cached REITs. The row is
    negative on the cash flow statement, hence the ``abs``.
    """
    if not ffo or ffo <= 0:
        return None
    paid = _latest_row_value(cashflow, _DIVIDENDS_PAID_ROWS)
    if paid is None:
        return None
    return abs(paid) / ffo * 100


def effective_payout_pct(result: Any) -> tuple[Optional[float], str]:
    """The payout this company must be judged on, and what it is measured against.

    Returns ``(percent, basis)`` with ``basis`` in ``{"ffo", "earnings"}``. Pure and
    tolerant of any result-shaped object, so a caller downstream of the scorer — or a
    hand-built ``FundamentalResult`` — gets the same answer the scorer used.

    Why the accounting payout is not that number for everyone: a REIT distributes over
    90 % of taxable income by law and funds it out of FFO, so its payout against
    accounting profit routinely exceeds 100 % without meaning anything is wrong.
    Measured on the cached universe (2026-08-22), O reported 236 % against an FFO
    payout of 70 %, EQR 121 % against 63 %, MAA 178 % against 74 %.

    ``payout_ratio`` stays the accounting figure — it is the one that reconciles with a
    filing — so this is the accessor for anyone who *judges* sustainability rather than
    reports it.
    """
    ffo_payout = getattr(result, "ffo_payout_pct", None)
    if ffo_payout is not None:
        return ffo_payout, "ffo"
    payout = getattr(result, "payout_ratio", None)
    if payout is None or payout < 0:
        return None, "earnings"
    return payout, "earnings"


def eps_growth_label(result: Any) -> str:
    """Label for the earnings-growth figure that names what it actually measures.

    ``eps_cagr_5y`` holds one of two different things (see
    ``FundamentalResult.eps_growth_source``), and calling the quarterly one a
    "CAGR" is how a +453% VLO reading looked plausible on screen. Pure and shared
    so the dashboard, the decision prompt and the committee prompt cannot drift.
    """
    source = getattr(result, "eps_growth_source", "") or ""
    years = int(getattr(result, "eps_cagr_years", 0) or 0)
    if source == "yoy":
        return "Crec. ganancias YoY (1 trim.)"
    if years:
        return f"EPS CAGR {years}Y"
    return "EPS CAGR"


def annual_dividend_totals(
    divs: pd.Series,
    *,
    today: Optional[date] = None,
) -> pd.Series:
    """Dividends summed per **complete** calendar year, most recent first.

    Pure function (no network) so the year handling is testable offline.

    The in-progress year is the whole point. ``_score_dividends`` grades a
    consecutive-growth streak by walking the annual totals from newest to oldest,
    and the old code summed straight off ``divs.resample("YE")`` — whose newest
    bucket is the year we are *living in*, holding two or three payments where the
    prior year holds four. The first comparison therefore fails for any normal
    quarterly payer, and the streak breaks at zero before it starts.

    Measured on the cached universe (2026-08-22): **134 of 141** dividend payers
    scored a streak of 0, JNJ among them — a company that has raised its dividend
    for 63 consecutive years. MCD showed 0 against 50 real years, XOM 0 against 42.
    Excluding the partial year drops that to 22 of 141, which is the true count of
    tickers without a two-year streak. The three points behind ``streak >= 10`` were
    unreachable for essentially the entire universe, and the growth-streak note
    could never fire. (That note used to call the company a "Dividend Aristocrat";
    U1-5 renamed it to what is actually counted — see ``dividend_streak_note``.)

    A ``"YE"`` bucket is labelled by its last day, so "already closed" is exactly
    ``label <= today``. ``today`` is injectable to keep tests deterministic — same
    pattern as ``_halving_position(today=None)`` in ``data/crypto_fetcher.py``.
    """
    if divs is None or divs.empty:
        return pd.Series(dtype=float)

    series = divs.dropna()
    if series.empty:
        return pd.Series(dtype=float)

    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index)

    annual = series.resample("YE").sum()
    annual = annual[annual > 0]
    if annual.empty:
        return pd.Series(dtype=float)

    cutoff = today or date.today()
    closed = annual[[d <= cutoff for d in annual.index.date]]
    return closed.sort_index(ascending=False)


_QUALITY_KEY_FIELDS = (
    "roe", "roic", "net_margin", "gross_margin",
    "debt_equity", "current_ratio",
    "pe_ratio", "pb_ratio",
    "revenue_cagr_5y", "eps_cagr_5y",
)


def compute_data_quality(
    result: "FundamentalResult",
    *,
    freshness_hours: Optional[float] = None,
    has_financials: bool = True,
    config=None,
) -> Dict[str, Any]:
    """Assess how complete/fresh the underlying yfinance data is for a ticker.

    Pure function (no network, no Streamlit) so it stays unit-testable offline.

    Returns a small JSON-serializable dict:
        level           — "good" | "partial" | "poor"
        missing_fields  — list of key metric names that came back empty
        n_missing / n_checked
        freshness_hours — age of the cached info (None = unknown / just fetched)
        stale           — True when freshness exceeds DATA_QUALITY.stale_warning_hours
        warnings        — human-readable notes for the UI

    Crypto and index/ETF tickers have no financial statements by design, so
    they are only checked for a usable market price.
    """
    if config is None:
        from config import DATA_QUALITY as config  # noqa: N811 — singleton default

    stale = bool(freshness_hours is not None and freshness_hours >= config.stale_warning_hours)
    warnings: list = []
    if stale:
        warnings.append(f"Datos cacheados hace {freshness_hours:.0f}h — considerá refrescar.")

    # Non-fundamental assets: only a usable price matters.
    if getattr(result, "is_crypto", False) or result.sector in ("Crypto", "Index", "ETF"):
        has_price = float(getattr(result, "current_price", 0.0) or 0.0) > 0
        if not has_price:
            warnings.append("Sin precio de mercado disponible.")
        return {
            "level": "good" if has_price else "poor",
            "missing_fields": [] if has_price else ["current_price"],
            "n_missing": 0 if has_price else 1,
            "n_checked": 1,
            "freshness_hours": round(freshness_hours, 1) if freshness_hours is not None else None,
            "stale": stale,
            "warnings": warnings,
        }

    missing = [f for f in _QUALITY_KEY_FIELDS if getattr(result, f, None) is None]
    n_missing = len(missing)

    if not has_financials:
        level = "poor"
        warnings.append("Sin estados financieros — scores de salud/crecimiento son neutrales.")
    elif n_missing >= config.poor_missing_fields:
        level = "poor"
        warnings.append(f"{n_missing} métricas clave sin datos — el score puede estar subestimado.")
    elif n_missing >= config.partial_missing_fields:
        level = "partial"
        warnings.append(f"{n_missing} métricas clave sin datos.")
    else:
        level = "good"

    return {
        "level": level,
        "missing_fields": missing,
        "n_missing": n_missing,
        "n_checked": len(_QUALITY_KEY_FIELDS),
        "freshness_hours": round(freshness_hours, 1) if freshness_hours is not None else None,
        "stale": stale,
        "warnings": warnings,
    }


class FundamentalAnalyzer:
    """
    Analyze a stock's fundamentals and return a FundamentalResult with
    a weighted 0–100 score. All data sourced from yfinance.
    """

    @staticmethod
    def _attach_cross_source_quality(result: "FundamentalResult") -> None:
        """Best-effort multi-source fold into ``result.data_quality`` (P0.1).

        Gated by ``MULTI_SOURCE.enabled`` and ``attach_in_pipeline``. Never
        raises; never overwrites scored metrics — only badge metadata/warnings.
        """
        try:
            from config import MULTI_SOURCE
            if not MULTI_SOURCE.enabled or not MULTI_SOURCE.attach_in_pipeline:
                return
            from analysis.data_reconciliation import attach_cross_source_quality
            attach_cross_source_quality(result)
        except Exception as exc:  # pragma: no cover - defensive
            from loguru import logger as _logger
            _logger.debug(f"cross-source attach skipped: {exc}")

    def analyze(self, symbol: str, ai_config=None) -> FundamentalResult:
        symbol = symbol.upper()

        # ── Crypto fast-path ──────────────────────────────────────────────
        # Detected before any yfinance financial-statement calls.
        # Returns the same FundamentalResult type with is_crypto=True.
        from config import is_crypto, normalize_crypto_ticker
        if is_crypto(symbol):
            from analysis.crypto_analyzer import CryptoAnalyzer
            from data.fetcher import get_info_age_hours
            crypto_result = CryptoAnalyzer().analyze(normalize_crypto_ticker(symbol), ai_config)
            crypto_result.data_quality = compute_data_quality(
                crypto_result, freshness_hours=get_info_age_hours(crypto_result.symbol),
            )
            return crypto_result
        # ─────────────────────────────────────────────────────────────────

        result = FundamentalResult(symbol=symbol)

        info = get_info(symbol)
        if not info:
            result.warnings.append("No data available from yfinance.")
            result.data_quality = compute_data_quality(result, has_financials=False)
            self._attach_cross_source_quality(result)
            return result

        financials = get_financials(symbol)
        income_stmt = financials.get("income_stmt", pd.DataFrame())
        balance_sheet = financials.get("balance_sheet", pd.DataFrame())
        cashflow = financials.get("cashflow", pd.DataFrame())

        # Basic info
        result.company_name = info.get("longName", symbol)
        from config import SECTOR_MAP
        _etf_tickers    = set(SECTOR_MAP.get("ETF", []))
        _crypto_tickers = set(SECTOR_MAP.get("Crypto", []))
        raw_sector = info.get("sector", "")
        if raw_sector:
            result.sector = raw_sector
        elif symbol in _crypto_tickers:
            result.sector = "Crypto"
        elif symbol in _etf_tickers:
            result.sector = "Index"
        else:
            result.sector = "Unknown"
        if symbol in _crypto_tickers:
            result.industry = "Cryptocurrency"
        elif symbol in _etf_tickers:
            result.industry = "Index"
        else:
            result.industry = info.get("industry", "") or "Unknown"
        result.market_cap = _safe_float(info.get("marketCap"))
        result.current_price = _safe_float(
            info.get("currentPrice") or info.get("regularMarketPrice")
        )

        # Asset class (audit item 01). Resolved from the feed's quoteType first so a
        # newly added ETF is recognised without editing SECTOR_MAP. The scores below
        # are still computed for every asset (nothing about the engine changes) —
        # this field is what lets consumers stop *presenting* them for funds/crypto.
        from analysis.asset_class import classify_asset
        result.asset_class = classify_asset(
            symbol,
            quote_type=info.get("quoteType"),
            sector=result.sector,
            is_crypto=bool(getattr(result, "is_crypto", False)),
        )

        # Capital ratio — captured for calibration, not scored. See the field's note.
        _equity = self._extract_annual_series(
            balance_sheet,
            ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"],
        )
        _assets = self._extract_annual_series(balance_sheet, ["Total Assets"])
        if not _equity.empty and not _assets.empty and float(_assets.iloc[0]) > 0:
            result.equity_to_assets_pct = round(
                float(_equity.iloc[0]) / float(_assets.iloc[0]) * 100, 2
            )

        # REIT metrics, before the dimensions that read them. This is the only place
        # with all three statements *and* a resolved market cap, and both the
        # valuation and the dividend dimension need the same two numbers.
        from analysis.company_type import is_reit
        if is_reit(result):
            result.ffo = compute_ffo(income_stmt, cashflow)
            if result.ffo and result.market_cap > 0:
                result.p_ffo = round(result.market_cap / result.ffo, 2)
            result.ffo_payout_pct = compute_ffo_payout_pct(cashflow, result.ffo)
            if result.ffo is None:
                result.notes["ffo"] = (
                    "Sin D&A en los estados — se usa la valuación contable, "
                    "que para un REIT subestima el resultado"
                )

        # Run each scoring dimension
        result.profitability_score = self._score_profitability(info, income_stmt, balance_sheet, result)
        result.health_score = self._score_financial_health(info, balance_sheet, income_stmt, result)
        result.valuation_score = self._score_valuation(info, result)
        result.growth_score = self._score_growth(info, income_stmt, cashflow, result)
        result.dividend_score = self._score_dividends(info, result)

        result.total_score = (
            result.profitability_score
            + result.health_score
            + result.valuation_score
            + result.growth_score
            + result.dividend_score
        )

        # Graham intrinsic value: V = EPS × (8.5 + 2g) × 4.4 / Y
        # where g = expected growth %, Y = AAA bond yield proxy (config D14)
        # `g` is the growth resolved above (statement CAGR when available), capped:
        # the formula is linear in g, so an unbounded quarterly figure produced
        # intrinsic values in the thousands and handed 40 of 149 companies a margin
        # of safety above 80% — which is exactly what `require_margin_of_safety`
        # reads to unlock STRONG BUY. The cap lives in the formula only; the growth
        # rate reported elsewhere is never truncated.
        from config import THRESHOLDS as _TH
        eps = _safe_float(info.get("trailingEps"))
        growth_estimate = float(result.eps_cagr_5y or 0.0)
        g_cap = float(getattr(_TH, "graham_max_growth_pct", 15.0) or 15.0)
        growth_used = min(growth_estimate, g_cap)
        y_aaa = float(getattr(_TH, "graham_aaa_yield_pct", 4.5) or 4.5)
        if y_aaa <= 0:
            y_aaa = 4.5
        if eps > 0 and growth_used > 0:
            graham = eps * (8.5 + 2 * growth_used) * 4.4 / y_aaa
            result.graham_value = round(graham, 2)
            if result.current_price > 0:
                mos = (graham - result.current_price) / graham * 100
                result.margin_of_safety_pct = round(mos, 1)

        # Enhanced scoring: Consistency + Piotroski (pass real cashflow for OCF)
        enhanced = EnhancedScoring().get_enhanced_score(
            result.total_score, info, income_stmt, balance_sheet,
            cashflow=cashflow,
        )
        result.consistency_score = enhanced.consistency_score
        result.piotroski_score = enhanced.piotroski_score
        result.piotroski_bonus = enhanced.piotroski_bonus
        result.consistency_detail = enhanced.consistency_detail
        result.piotroski_detail = enhanced.piotroski_detail
        for rec in enhanced.recommendations:
            result.notes[f"enhanced_{len(result.notes)}"] = rec

        # Moat scoring: quantitative always, AI qualitative when ai_config is enabled
        moat_analyzer = MoatAnalyzer()
        moat = moat_analyzer.analyze(symbol, info, income_stmt, balance_sheet, cashflow)
        if ai_config and getattr(ai_config, "enabled", False):
            moat = moat_analyzer.analyze_with_ai(moat, symbol, info, ai_config)
        result.moat_score = moat.total
        result.moat_bonus = moat.bonus
        result.moat_classification = moat.classification
        result.moat_detail = moat

        # Sector-country structural tailwind (Idea 2): curated always, AI enrichment optional.
        # Neutral (no curated match / disabled) → bonus 0 → numbers identical to pre-feature.
        tailwind_analyzer = TailwindAnalyzer()
        tailwind = tailwind_analyzer.analyze(
            symbol,
            sector=result.sector,
            country=info.get("country", "") or "",
            industry=result.industry,
        )
        if ai_config and getattr(ai_config, "enabled", False):
            tailwind = tailwind_analyzer.analyze_with_ai(tailwind, symbol, info, ai_config)
        result.tailwind_score = tailwind.tailwind_score
        result.tailwind_bonus = tailwind.bonus
        result.tailwind_classification = tailwind.classification
        result.tailwind_detail = tailwind

        # Final adjusted_score = base + consistency + piotroski_bonus + moat_bonus
        #                        + tailwind_bonus (can be negative), capped to [0, 100]
        _raw = (
            result.total_score + result.consistency_score +
            result.piotroski_bonus + result.moat_bonus +
            result.tailwind_bonus
        )
        # Uncapped companion (audit item 11) — the clamp below merges the top of the
        # ranking into ties, so keep the real number for anything that sorts.
        result.raw_adjusted_score = round(_raw, 1)
        result.adjusted_score = round(min(max(_raw, 0.0), 100.0), 1)

        # Data quality (Fase E): completeness of key metrics + cache freshness.
        from data.fetcher import get_info_age_hours
        result.data_quality = compute_data_quality(
            result,
            freshness_hours=get_info_age_hours(symbol),
            has_financials=bool(financials),
        )
        # Multi-source badge (P0.1): fold SEC/yfinance reconciliation into the
        # same data_quality dict. Best-effort; never rewrites scored metrics.
        self._attach_cross_source_quality(result)
        if result.data_quality and result.data_quality.get("level") != "good":
            for w in result.data_quality.get("warnings") or []:
                if w not in result.warnings:
                    result.warnings.append(w)

        logger.info(
            f"{symbol}: base={result.total_score:.1f} consistency={result.consistency_score:.1f} "
            f"piotroski={result.piotroski_score}/9 moat={result.moat_score:.1f}/{result.moat_classification} "
            f"tailwind={result.tailwind_classification}({result.tailwind_bonus:+.1f}) "
            f"adjusted={result.adjusted_score:.1f}"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Profitability — 25 pts                                              #
    # ------------------------------------------------------------------ #

    def _score_profitability(
        self,
        info: dict,
        income_stmt: pd.DataFrame,
        balance_sheet: pd.DataFrame,
        result: FundamentalResult,
    ) -> float:
        score = 0.0
        missing: list = []

        # ROE (8 pts). A reported zero is a fact about the company; only an absent
        # field is missing data. Scoring `roe_reported or 0.0` then warning
        # "Low ROE: 0.0%" treated an omitted field as unprofitable.
        roe_reported = reported_metric(info, "returnOnEquity")
        if roe_reported is None:
            result.roe = None
            missing.append("ROE")
        else:
            roe = roe_reported * 100
            result.roe = roe
            if roe >= T.roe_excellent:
                score += 8
                result.notes["roe"] = f"Excellent ROE {roe:.1f}%"
            elif roe >= T.roe_good:
                score += 5
                result.notes["roe"] = f"Good ROE {roe:.1f}%"
            elif roe >= T.roe_min:
                score += 2
                result.notes["roe"] = f"Acceptable ROE {roe:.1f}%"
            else:
                result.warnings.append(f"Low ROE: {roe:.1f}%")

        # ROIC (7 pts) — approximated if not directly available
        roic_raw = _safe_float(info.get("returnOnAssets")) * 100
        # Improve with ROIC proxy = NOPAT / Invested Capital
        roic = self._compute_roic(income_stmt, balance_sheet) or roic_raw
        result.roic = roic if roic != 0 else None
        if roic >= T.roic_excellent:
            score += 7
            result.notes["roic"] = f"Excellent ROIC {roic:.1f}%"
        elif roic >= T.roic_good:
            score += 4
            result.notes["roic"] = f"Good ROIC {roic:.1f}%"
        elif roic >= T.roic_min:
            score += 2
            result.notes["roic"] = f"Acceptable ROIC {roic:.1f}%"

        # Net Margin (5 pts). Same omitted-vs-zero split as ROE.
        nm_reported = reported_metric(info, "profitMargins")
        if nm_reported is None:
            result.net_margin = None
            missing.append("Net margin")
        else:
            nm = nm_reported * 100
            result.net_margin = nm
            if nm >= T.net_margin_excellent:
                score += 5
            elif nm >= T.net_margin_good:
                score += 3
            elif nm >= T.net_margin_min:
                score += 1
            else:
                result.warnings.append(f"Thin net margin: {nm:.1f}%")

        # Gross Margin (5 pts)
        gm = _safe_float(info.get("grossMargins")) * 100
        result.gross_margin = gm if gm != 0 else None
        if gm >= T.gross_margin_excellent:
            score += 5
        elif gm >= T.gross_margin_good:
            score += 3
        elif gm > 0:
            score += 1

        if missing:
            result.notes["profitability_missing"] = (
                f"Sin datos de {', '.join(missing)} — esas dimensiones suman 0, no se estiman"
            )

        return min(score, 25.0)

    def _compute_roic(self, income_stmt: pd.DataFrame, balance_sheet: pd.DataFrame) -> Optional[float]:
        """ROIC = NOPAT / (Total Equity + Long-term Debt). Returns %."""
        try:
            if income_stmt.empty or balance_sheet.empty:
                return None
            ebit = self._row(income_stmt, ["EBIT", "Operating Income"])
            tax_rate = 0.21  # US corporate tax rate
            nopat = ebit * (1 - tax_rate)

            equity = self._row(balance_sheet, ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"])
            ltd = self._row(balance_sheet, ["Long Term Debt", "Long-Term Debt"])
            invested_capital = equity + ltd
            if invested_capital <= 0:
                return None
            return float(nopat / invested_capital * 100)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  Financial Health — 20 pts                                           #
    # ------------------------------------------------------------------ #

    def _score_financial_health(
        self,
        info: dict,
        balance_sheet: pd.DataFrame,
        income_stmt: pd.DataFrame,
        result: FundamentalResult,
    ) -> float:
        score = 0.0
        missing: list = []

        # Debt/Equity (7 pts) — an unreported D/E is not low debt.
        # `_safe_float(None) → 0.0` used to land in the `<= 0.5` branch, so the 30
        # tickers whose feed omits `debtToEquity` collected the full 7 points *and*
        # the note "Very low debt D/E=0.00". Five of them (MCD, SBUX, ABBV, YUM, LOW)
        # have negative shareholders' equity — MCD carries $54.8B of debt against
        # −$1.79B of equity — which is precisely why the field is absent.
        de = reported_metric(info, "debtToEquity")
        if de is not None:
            de = de / 100.0  # yfinance reports it ×100 (45 means 0.45)
        if de is None or de < 0:
            de = self._derive_debt_equity(balance_sheet, result)
        result.debt_equity = de
        if de is None:
            missing.append("D/E")
        elif de <= T.max_debt_equity_excellent:
            score += 7
            result.notes["debt_equity"] = f"Very low debt D/E={de:.2f}"
        elif de <= T.max_debt_equity_good:
            score += 5
        elif de <= T.max_debt_equity_acceptable:
            score += 2
        else:
            result.warnings.append(f"High leverage D/E={de:.2f}")

        # Current Ratio (5 pts). Same distinction as ROE above: reported zero vs absent.
        cr_reported = reported_metric(info, "currentRatio")
        cr = cr_reported or 0.0
        result.current_ratio = cr_reported
        if cr >= T.min_current_ratio_good:
            score += 5
        elif cr >= T.min_current_ratio_ok:
            score += 3
        elif cr > 0:
            score += 1
            result.warnings.append(f"Current ratio low: {cr:.2f}")

        # Interest Coverage (5 pts) — EBIT / Interest Expense
        ic = self._compute_interest_coverage(income_stmt)
        result.interest_coverage = ic
        if ic is not None:
            if ic >= T.min_interest_coverage_excellent:
                score += 5
            elif ic >= T.min_interest_coverage_good:
                score += 3
            elif ic >= T.min_interest_coverage_ok:
                score += 1
            else:
                result.warnings.append(f"Interest coverage thin: {ic:.1f}x")

        # Quick Ratio (3 pts)
        qr = _safe_float(info.get("quickRatio"))
        if qr >= 1.5:
            score += 3
        elif qr >= 1.0:
            score += 2
        elif qr > 0:
            score += 1

        if missing:
            result.notes["health_missing"] = (
                f"Sin datos de {', '.join(missing)} — esas dimensiones suman 0, no se estiman"
            )

        return min(score, 20.0)

    def _derive_debt_equity(
        self,
        balance_sheet: pd.DataFrame,
        result: FundamentalResult,
    ) -> Optional[float]:
        """D/E straight from the balance sheet when the feed omits it.

        yfinance drops ``debtToEquity`` for two very different populations, and the
        old code treated both as "no debt":

          * **banks** (JPM, BAC, WFC…), where the ratio is not a meaningful figure
            but ``Total Debt`` and ``Stockholders Equity`` are both reported — so it
            can simply be computed;
          * **negative-equity companies** (MCD, SBUX, ABBV, YUM, LOW), where the
            ratio is mathematically undefined. MCD carries $54.8B of debt against
            −$1.79B of equity. Reporting a negative D/E would be worse than
            reporting none: the leverage guard compares ``> max_debt_equity`` and a
            negative number passes it.

        ``Total Debt`` and ``Stockholders Equity`` are present in 149/149 cached
        balance sheets, so this costs no extra network — the statements are already
        fetched for the scoring dimensions above.

        **Banks are excluded**, and the marker is structural rather than a label.
        ``Total Debt / Equity`` for a deposit-taking bank omits deposits, which are
        its main funding: JPM reports $500B of debt against $4.06 *trillion* of total
        liabilities. The resulting ratio (0.22–2.76 across the nine cached banks)
        clears the ``max_debt_equity`` guard comfortably and lands in the paying
        bands — BSBR collected 7 points for "very low debt" while levered 9:1. An
        entity with no ``Current Assets`` has no working-capital structure, which is
        the premise of every band in this dimension; measured on the cache, "no
        ``debtToEquity`` from the feed **and** no ``Current Assets``" selects exactly
        those nine banks and nobody else. Insurers have no current assets either but
        do report ``debtToEquity``, so this path never runs for them.

        Returns the ratio, or ``None`` when it cannot be defined; sets
        ``result.negative_equity`` as the honest signal for the decision layer.
        """
        if balance_sheet is None or balance_sheet.empty:
            return None

        if "Current Assets" not in balance_sheet.index:
            return None

        equity_series = self._extract_annual_series(
            balance_sheet,
            ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"],
        )
        if equity_series.empty:
            return None
        equity = float(equity_series.iloc[0])

        if equity < 0:
            result.negative_equity = True
            result.warnings.append(
                f"Patrimonio neto negativo (${equity/1e9:.2f}B) — D/E indefinido, "
                "el apalancamiento no es verificable con este dato"
            )
            return None

        debt_series = self._extract_annual_series(balance_sheet, ["Total Debt"])
        if debt_series.empty or equity == 0:
            return None

        ratio = float(debt_series.iloc[0]) / equity
        result.notes["debt_equity_source"] = "D/E derivado de los estados (el feed no lo reporta)"
        return ratio

    def _compute_interest_coverage(self, income_stmt: pd.DataFrame) -> Optional[float]:
        try:
            if income_stmt.empty:
                return None
            ebit = self._row(income_stmt, ["EBIT", "Operating Income"])
            interest = self._row(income_stmt, ["Interest Expense"])
            if interest == 0:
                return None
            return float(ebit / abs(interest))
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  Valuation — 25 pts                                                  #
    # ------------------------------------------------------------------ #

    def _score_valuation(self, info: dict, result: FundamentalResult) -> float:
        """Valuation — 25 pts. A multiple the feed does not report scores zero.

        Every band here is an upper bound, and the old code fed them
        ``_safe_float(None) → 0.0``, so *missing* data fell through to the second
        band: P/E +5, PEG +4, EV/EBITDA +3, P/B +3. Measured on the cached universe
        (2026-08-22), 24 companies collected points for data nobody had — the nine
        banks (+10 each, because banks structurally have neither EV/EBITDA nor a
        meaningful D/E) and the negative-equity names, whose P/B yfinance omits.
        A ticker with no multiples at all scored 15 of 25 for valuation.
        """
        score = 0.0
        missing: list = []

        # Earnings multiple (8 pts). For a REIT the multiple that means anything is
        # price over funds from operations — see compute_ffo(). P/E is still reported
        # for display, it just does not drive the band.
        p_ffo = getattr(result, "p_ffo", None)
        if p_ffo is not None:
            result.pe_ratio = reported_positive_metric(info, "trailingPE", "forwardPE")
            if p_ffo <= T.p_ffo_excellent:
                score += 8
            elif p_ffo <= T.p_ffo_good:
                score += 5
            elif p_ffo <= T.p_ffo_acceptable:
                score += 2
            else:
                result.warnings.append(f"P/FFO exigente: {p_ffo:.1f}x")
        else:
            pe = reported_positive_metric(info, "trailingPE", "forwardPE")
            result.pe_ratio = pe
            if pe is None:
                missing.append("P/E")
            elif pe <= T.pe_excellent:
                score += 8
            elif pe <= T.pe_good:
                score += 5
            elif pe <= T.pe_acceptable:
                score += 2
            else:
                result.warnings.append(f"Expensive P/E: {pe:.1f}x")

        # PEG (7 pts)
        peg = reported_positive_metric(info, "pegRatio")
        result.peg_ratio = peg
        if peg is None:
            missing.append("PEG")
        elif peg <= T.peg_excellent:
            score += 7
            result.notes["peg"] = f"Attractive PEG {peg:.2f}"
        elif peg <= T.peg_good:
            score += 4
        elif peg <= T.peg_acceptable:
            score += 2

        # EV/EBITDA (5 pts)
        ev_ebitda = reported_positive_metric(info, "enterpriseToEbitda")
        result.ev_ebitda = ev_ebitda
        if ev_ebitda is None:
            missing.append("EV/EBITDA")
        elif ev_ebitda <= T.ev_ebitda_excellent:
            score += 5
        elif ev_ebitda <= T.ev_ebitda_good:
            score += 3
        elif ev_ebitda <= T.ev_ebitda_acceptable:
            score += 1

        # P/B (5 pts)
        pb = reported_positive_metric(info, "priceToBook")
        result.pb_ratio = pb
        if pb is None:
            missing.append("P/B")
        elif pb <= T.pb_excellent:
            score += 5
        elif pb <= T.pb_good:
            score += 3
        elif pb <= T.pb_acceptable:
            score += 1

        if missing:
            result.notes["valuation_missing"] = (
                f"Sin datos de {', '.join(missing)} — esas dimensiones suman 0, no se estiman"
            )

        return min(score, 25.0)

    # ------------------------------------------------------------------ #
    #  Growth — 20 pts                                                     #
    # ------------------------------------------------------------------ #

    def _score_growth(
        self,
        info: dict,
        income_stmt: pd.DataFrame,
        cashflow: pd.DataFrame,
        result: FundamentalResult,
    ) -> float:
        score = 0.0

        # Revenue CAGR (7 pts) — over the longest window the statements support.
        # This used to demand a fixed 5-year window, i.e. 6 annual points; yfinance
        # returns 4, so the branch never fired for any company and its 7 points
        # were unreachable across the whole product.
        rev_series = self._extract_annual_series(income_stmt, ["Total Revenue", "Revenue"])
        rev_cagr, rev_years = compute_cagr_available(
            rev_series, target_years=T.cagr_target_years, min_years=T.cagr_min_years
        )
        if rev_cagr is not None:
            result.revenue_cagr_5y = round(rev_cagr * 100, 1)
            result.revenue_cagr_years = rev_years
            pct = result.revenue_cagr_5y
            if pct >= T.revenue_cagr_excellent:
                score += 7
            elif pct >= T.revenue_cagr_good:
                score += 4
            elif pct >= T.revenue_cagr_ok:
                score += 2
            else:
                result.warnings.append(f"Slow revenue growth: {pct:.1f}% CAGR")

        # Earnings growth (7 pts) — compounded off the statements, not off a quarter.
        #
        # This used to read yfinance's `earningsGrowth` first and only fall back to
        # the income statements when it was absent or negative. `earningsGrowth` is a
        # **single quarter against the same quarter a year earlier**, so off a
        # depressed base it reaches triple digits: measured on the cached universe
        # (2026-08-22) 49 of 149 companies published an "EPS CAGR" above 50% — VLO
        # 453%, LMT 444%, GOOGL 294% — each collecting the full 7 points and feeding
        # the same number to Graham's `g` and to the LLM prompt.
        #
        # Worse, the old fallback was silent: a company whose earnings had *fallen*
        # (negative `earningsGrowth`, 34 of 164 tickers) skipped straight to a
        # multi-year net-income CAGR that could be positive off a low base. CLX, with
        # earnings down 50% year over year, reported +57.9% and scored 7 of 7.
        #
        # The statements are the honest source: a rate compounded over the window the
        # data actually supports, with the window reported alongside. The quarterly
        # figure survives only as a labelled fallback (`eps_cagr_years == 1`).
        ni_series = self._extract_annual_series(income_stmt, ["Net Income"])
        ni_cagr, ni_years = compute_cagr_available(
            ni_series, target_years=T.cagr_target_years, min_years=T.cagr_min_years
        )
        if ni_cagr is not None:
            result.eps_cagr_5y = round(ni_cagr * 100, 1)
            result.eps_cagr_years = ni_years
            result.eps_growth_source = "statement_cagr"
        else:
            yoy = _safe_float(info.get("earningsGrowth")) * 100
            if yoy > 0:
                result.eps_cagr_5y = round(yoy, 1)
                result.eps_cagr_years = 1
                result.eps_growth_source = "yoy"

        eps_growth = result.eps_cagr_5y
        if eps_growth is not None and eps_growth > 0:
            if eps_growth >= T.eps_cagr_excellent:
                score += 7
            elif eps_growth >= T.eps_cagr_good:
                score += 4
            elif eps_growth >= T.eps_cagr_ok:
                score += 2

        # FCF Yield + Growth (6 pts)
        fcf_series = self._extract_annual_series(cashflow, ["Free Cash Flow"])
        market_cap = result.market_cap
        if not fcf_series.empty and market_cap > 0:
            fcf_latest = fcf_series.iloc[0]
            fcf_yield = fcf_latest / market_cap * 100
            result.fcf_yield = round(fcf_yield, 2)
            if fcf_yield >= 4:
                score += 3
            elif fcf_yield >= 2:
                score += 2
            elif fcf_yield > 0:
                score += 1

            fcf_cagr = compute_cagr(fcf_series, years=3)
            if fcf_cagr is not None:
                if fcf_cagr * 100 >= T.fcf_growth_excellent:
                    score += 3
                elif fcf_cagr * 100 >= T.fcf_growth_good:
                    score += 2
                elif fcf_cagr > 0:
                    score += 1

        return min(score, 20.0)

    # ------------------------------------------------------------------ #
    #  Dividend Quality — 10 pts                                           #
    # ------------------------------------------------------------------ #

    def _score_dividends(self, info: dict, result: FundamentalResult) -> float:
        score = 0.0

        div_yield = normalize_dividend_yield_pct(info, warnings=result.warnings) or 0.0
        result.dividend_yield = round(div_yield, 2) if div_yield > 0 else None

        # A REIT distributes over 90% of taxable income by law and funds it out of
        # FFO, so its payout against accounting profit routinely exceeds 100% —
        # 12 of 13 tripped the "unsustainable" warning, which for this asset class
        # is the definition of working as intended. Grade against the FFO payout.
        #
        # Resolved *before* the no-dividend early return and persisted rather than
        # kept local (U2-6): the score used to be the only consumer that knew which
        # payout it had judged, so `analysis/strategy.py` re-derived the risk off the
        # accounting field and told a healthy REIT it might cut its dividend.
        payout_raw = reported_metric(info, "payoutRatio")
        result.payout_ratio = (payout_raw * 100.0) if payout_raw is not None else None
        payout, result.payout_basis = effective_payout_pct(result)
        result.payout_ratio_effective = payout

        # Non-dividend stocks: neutral (growth companies reinvest instead)
        if div_yield == 0:
            score += 3  # partial credit — not a flaw for growth stocks
            result.notes["dividend"] = "No dividend — growth company reinvests FCF"
            return score

        # Yield in sweet spot (4 pts)
        if T.div_yield_sweet_spot_low <= div_yield <= T.div_yield_sweet_spot_high:
            score += 4
            result.notes["dividend"] = f"Healthy yield {div_yield:.2f}%"
        elif div_yield > T.div_yield_sweet_spot_high:
            score += 1
            result.warnings.append(f"High yield may signal risk: {div_yield:.2f}%")
        else:
            score += 2

        # Payout ratio (3 pts). `max_payout_ratio` is the single cut: the same one
        # `_build_rationale` reads for the decision risk, so the score and the
        # explanation can never disagree about whether a dividend is stretched.
        # A missing payout is not an excellent/acceptable upper bound — do not
        # coerce None to 0.0. A reported 0 % still scores.
        missing: list = []
        if payout is None:
            missing.append("Payout")
        elif 0 < payout <= T.payout_excellent:
            score += 3
        elif payout <= T.max_payout_ratio:
            score += 2
        elif payout > T.max_payout_ratio:
            base = "sobre FFO" if result.payout_basis == "ffo" else "sobre ganancias"
            result.warnings.append(
                f"Payout alto {payout:.0f}% {base} — el dividendo puede no ser sostenible"
            )

        # Dividend growth streak (3 pts) — complete calendar years only, since the
        # year in progress is always short a payment and would break every streak.
        annual = annual_dividend_totals(get_dividends(result.symbol))
        if not annual.empty:
            streak = self._consecutive_growth_streak(annual)
            if streak >= 10:
                score += 3
                # U1-5: the note reports the streak the feed supports, not the
                # S&P Dividend Aristocrats index (25 years + S&P 500 membership),
                # which this cut of 10 years never verified. The cut is untouched.
                result.notes["div_growth"] = dividend_streak_note(streak)
            elif streak >= 5:
                score += 2
            elif streak >= 2:
                score += 1

        if missing:
            result.notes["dividend_missing"] = (
                f"Sin datos de {', '.join(missing)} — esas dimensiones suman 0, no se estiman"
            )

        return min(score, 10.0)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _row(self, df: pd.DataFrame, candidates: list) -> float:
        """Most recent **reported** annual value for a matching row, else 0.0.

        The ``dropna()`` matters: this used to read ``iloc[0]`` off the raw row, so a
        NaN in the newest column became a silent ``0.0`` while its twin
        ``_extract_annual_series`` skipped to the newest *reported* period — the two
        helpers could return figures from different fiscal years for the same
        statement. Measured on the cache: 4 tickers, including AAPL and LLY, whose
        latest ``Interest Expense`` is blank and who therefore lost interest coverage
        entirely.
        """
        for name in candidates:
            if name in df.index:
                series = df.loc[name].dropna()
                if series.empty:
                    return 0.0
                return _safe_float(series.iloc[0])
        return 0.0

    def _extract_annual_series(self, df: pd.DataFrame, candidates: list) -> pd.Series:
        """Return a Series of annual values (most recent first) for a matching row."""
        for name in candidates:
            if name in df.index:
                series = df.loc[name].dropna()
                series.index = pd.to_datetime(series.index)
                return series.sort_index(ascending=False)
        return pd.Series(dtype=float)

    def _consecutive_growth_streak(self, annual: pd.Series) -> int:
        """Count how many consecutive years the dividend grew."""
        annual = annual.sort_index(ascending=False)
        streak = 0
        for i in range(len(annual) - 1):
            if annual.iloc[i] > annual.iloc[i + 1]:
                streak += 1
            else:
                break
        return streak
