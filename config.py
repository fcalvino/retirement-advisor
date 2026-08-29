"""Central configuration for the Retirement Advisor system."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DB_DIR = BASE_DIR / "data" / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "retirement_advisor.db"

# Version of the numeric engine (Monte Carlo + decumulation + optimizer μ).
# Stamped onto every saved PlanSnapshot so a plan can be traced back to the
# maths that produced it. Bump ONLY when a change alters the numbers a saved
# plan would produce, so the UI can flag stale snapshots.
#
#   2026.08-tier0 — audit D1/D2/D3 fix: withdrawals remove capital (were a
#                   constant nominal level), ruin is absorbing, and the
#                   optimizer's μ no longer depends on the risk profile.
#                   See docs/AUDITORIA_2026-08.md.
#   2026.08-tier1 — U2-2: drawdown/SORR (sorr_early_drawdown_pct,
#                   median_max_drawdown_pct, pct_paths_severe_drawdown,
#                   *_year_of_max_dd) are measured on the market series —
#                   the bootstrap path before drags and before cash flows.
#                   Plans saved under tier0 counted planned withdrawals as a
#                   crash and persist inflated SORR figures.
#   2026.08-tier2 — U4-1/U4-2: contributions arrive monthly instead of as one
#                   deposit in week 52, and a plan with no starting capital no
#                   longer discards its savings. Plans saved under tier0/tier1
#                   with contributions understate the final capital; those with
#                   no initial capital reported it as zero, at 0 % probability.
#   2026.08-tier3 — U5-6: the optimizer's μ paid a moat twice — once through the
#                   adjusted_score that already contains the moat bonus, and
#                   again through a term of its own — so wide-moat companies
#                   were overweighted against the engine's own valuation. μ
#                   falls 0.50 pp on average; plans saved under tier0-tier2 hold
#                   allocations tilted toward moat.
ENGINE_VERSION = "2026.08-tier3"


@dataclass
class FundamentalThresholds:
    """Score thresholds used in fundamental analysis. All adjustable."""

    # --- Profitability (25 pts total) ---
    roe_excellent: float = 20.0       # % — full score
    roe_good: float = 15.0            # % — partial score
    roe_min: float = 8.0              # % — minimum acceptable

    roic_excellent: float = 15.0
    roic_good: float = 10.0
    roic_min: float = 6.0

    net_margin_excellent: float = 20.0
    net_margin_good: float = 10.0
    net_margin_min: float = 5.0

    gross_margin_excellent: float = 50.0
    gross_margin_good: float = 30.0

    # --- Financial Health (20 pts total) ---
    max_debt_equity_excellent: float = 0.5
    max_debt_equity_good: float = 1.0
    max_debt_equity_acceptable: float = 2.0

    min_current_ratio_good: float = 2.0
    min_current_ratio_ok: float = 1.5

    min_interest_coverage_excellent: float = 10.0
    min_interest_coverage_good: float = 5.0
    min_interest_coverage_ok: float = 3.0

    # --- Valuation (25 pts total) ---
    pe_excellent: float = 15.0
    pe_good: float = 25.0
    pe_acceptable: float = 35.0

    peg_excellent: float = 1.0
    peg_good: float = 1.5
    peg_acceptable: float = 2.0

    ev_ebitda_excellent: float = 10.0
    ev_ebitda_good: float = 15.0
    ev_ebitda_acceptable: float = 20.0

    # --- REIT valuation (auditoría por industria, 2026-08-22) ---
    # A REIT is valued on price over funds from operations, not over accounting
    # profit: depreciation is the largest charge on its income statement and is not
    # a cash outflow, so the P/E bands above measure something else entirely (DLR
    # showed 244.7×, O 45.7×). Own bands rather than reusing pe_* because a P/FFO of
    # 15 is the sector median — calling it "excellent" would repeat the category
    # error this fix exists to remove. Measured range on the universe: 11.8 to 53.5.
    # These are a calibration choice, not an empirical finding; see StrategyConfig
    # on where the evidence to settle them would come from.
    p_ffo_excellent: float = 13.0
    p_ffo_good: float = 18.0
    p_ffo_acceptable: float = 23.0

    pb_excellent: float = 1.5
    pb_good: float = 3.0
    pb_acceptable: float = 5.0

    # --- Graham intrinsic value (D14) ---
    # Y in V = EPS × (8.5 + 2g) × 4.4 / Y  (AAA corporate bond yield proxy %)
    graham_aaa_yield_pct: float = 4.5

    # Ceiling on `g` inside the Graham formula (audit 2026-08-22, P1-1). `g` is
    # meant to be the sustainable 7-10 year growth rate; the engine was feeding it
    # yfinance's `earningsGrowth`, a **quarterly year-over-year** figure that hits
    # triple digits off a depressed base (VLO 453%, LMT 444%, GOOGL 294% on the
    # cached universe). `8.5 + 2g` is linear in g, so those produced intrinsic
    # values in the thousands and a margin of safety above 80% for 40 of 149
    # companies — which is what unlocks STRONG BUY via `require_margin_of_safety`.
    # Graham himself did not project high rates that far out. The cap applies only
    # inside the formula: the growth rate reported to the UI is never truncated.
    graham_max_growth_pct: float = 15.0

    # --- Growth (20 pts total) ---
    revenue_cagr_excellent: float = 15.0   # % 5Y CAGR
    revenue_cagr_good: float = 8.0
    revenue_cagr_ok: float = 3.0

    eps_cagr_excellent: float = 15.0
    eps_cagr_good: float = 8.0
    eps_cagr_ok: float = 3.0

    fcf_growth_excellent: float = 10.0
    fcf_growth_good: float = 5.0

    # --- Dividend Quality (10 pts total) ---
    div_yield_sweet_spot_low: float = 1.5   # % — below = growth stock
    div_yield_sweet_spot_high: float = 4.0  # % — above = potentially risky
    # Growth CAGR window. `cagr_target_years` is the window we'd prefer;
    # `cagr_min_years` is the shortest one still worth scoring. yfinance ships 4
    # annual statements, so in practice the revenue/earnings CAGR is measured over
    # 3 years — asking for a fixed 5 made the metric None for 78/78 companies and
    # silently killed the 7 revenue-growth points. See compute_cagr_available().
    cagr_target_years: int = 5
    cagr_min_years: int = 3
    # Sanity ceiling for a *normalized* dividend yield, in percent. Nothing real
    # sustains this; a value above it means the feed field was read in the wrong
    # unit (yfinance mixes fractions and percents across its dividend fields —
    # SCHD once scored on a "313%" yield). See normalize_dividend_yield_pct().
    max_plausible_dividend_yield_pct: float = 30.0
    # % — sustainable payout. **The single cut**: the dividend dimension grades against
    # it (`_score_dividends`) and the decision engine reads the same number for the
    # "may cut dividend" risk (`_build_rationale`). They used to disagree — the risk
    # compared a literal 80 against the *accounting* payout — so a REIT could be scored
    # as paying comfortably and warned about cutting in the same breath (U2-6).
    # What it is measured against is `payout_basis`: FFO for a REIT, earnings otherwise
    # (see effective_payout_pct). REIT-specific bands are U5-4's call, not this one's.
    max_payout_ratio: float = 75.0
    # REIT bands (U5-4). A REIT distributes over 90 % of taxable income BY LAW and
    # pays it out of FFO, so the industrial cuts are not stricter — they are the
    # wrong ruler. Measured on the 13 cached REITs, not one reached ≤40 % (the
    # lowest is 49 %) and four were warned "may cut dividend" at 78–82 %, which is
    # ordinary on FFO. ≤70 % is comfortable and >90 % is genuinely stretched.
    #
    # These two are a calibration choice, not an empirical finding: 13 REITs with
    # no scored outcomes cannot settle a threshold. They are grounded in what the
    # distribution requirement makes possible, not in observed hit rates.
    reit_payout_excellent: float = 70.0
    reit_max_payout_ratio: float = 90.0
    # % — top payout band (3 pts). A literal 40 used to live in `_score_dividends`;
    # the cut belongs here with the other dividend thresholds. Missing payout is
    # not this band (it scores 0); a reported 0 % still is.
    payout_excellent: float = 40.0


@dataclass
class StrategyConfig:
    """Decision engine thresholds.

    The score ladder (re-anchored 2026-08-22). These cut ``adjusted_score``, not
    ``total_score``, and that distinction is the whole reason the numbers moved.

    ``75/60/45`` were calibrated for ``total_score`` — the 0–100 sum of the five
    fundamental dimensions — as the module docstring of ``analysis/strategy.py``
    still describes. But ``use_adjusted_score_for_decision`` (below, default True)
    feeds the ladder ``adjusted_score``, which adds consistency (0–15), the
    Piotroski bonus, moat (up to +10) and tailwind on top. Measured over the 149
    cached equities that is **+20.3 points on average**: the marks never moved, the
    ruler underneath them grew. What each cut actually selected:

        cut               on total_score      on adjusted_score (what runs)
        75  STRONG BUY          4 %                  33 %
        60  BUY                16 %                  76 %
        45  HOLD               63 %                  98 %

    Three quarters of an already-curated quality universe carrying a buy signal is
    the same defect ``analysis/ranking.py`` documents for the Screener (item 06):
    an absolute cut calibrated against the whole market cannot discriminate inside
    a pre-filtered list. And ``hold=45`` left 3 of 149 names below it, so REDUCE
    and SELL were dead letters.

    The values below restore roughly the intended severity (STRONG BUY ≈ top
    quintile, ~15 % in REDUCE/SELL) while keeping the ladder's shape — the gaps
    were 15/15/10 and are now 14/13/10. They deliberately do **not** claw back the
    full +20.3: the bonuses are real quality signals, and a wide-moat compounder
    with a Piotroski of 8 *should* reach top conviction more easily. What was never
    intended is a third of the universe being STRONG BUY.

    **This is percentile anchoring, not calibration.** The empirical answer — do
    STRONG BUYs actually outperform BUYs? — lives in ``recommendation_outcome``,
    which has zero rows because ``scripts/score_track_record.py`` has never run.
    Until it does, these are a statement about how demanding the tool should be.
    """

    strong_buy_score: float = 82.0
    buy_score: float = 68.0
    hold_score: float = 55.0
    # Below hold_score → REDUCE, and below reduce_score → SELL. This last rung was
    # a bare `35` inside decide() until 2026-08-22 — the only step of the ladder
    # that did not live here, against the "never hardcode numbers in analysis code"
    # standard of docs/CONTEXT.md §5.
    reduce_score: float = 45.0

    # Technical confirmation required for BUY
    require_technical_uptrend: bool = True

    # Margin of Safety: only buy when price < intrinsic value estimate
    require_margin_of_safety: bool = True
    min_margin_of_safety_pct: float = 10.0  # %

    # P0 audit D2: use adjusted_score (moat+consistency+piotroski+tailwind) so
    # decision layer aligns with optimizer/screener ranking. Set False for legacy
    # total_score-only matrix (equity only; crypto always uses adjusted_score).
    use_adjusted_score_for_decision: bool = True

    # P0 audit D3: hard-block leverage threshold (was magic 3.0 in strategy.py)
    max_debt_equity: float = 3.0

    # Audit 2026-08-22 (P1-3): companies with negative shareholders' equity have no
    # defined D/E, so `max_debt_equity` above never fires for them and neither does
    # the negative-book guard (yfinance omits priceToBook rather than reporting it
    # negative). MCD, SBUX, ABBV, YUM and LOW passed both. Negative equity is not
    # insolvency — in those names it comes from buybacks — so this caps the action
    # at HOLD and states the reason instead of blocking outright.
    negative_equity_caps_action: bool = True

    # Portfolio risk limits
    max_position_pct: float = 8.0     # max % of portfolio per stock
    max_sector_pct: float = 25.0      # max % of portfolio per sector
    min_positions: int = 10           # minimum diversification


@dataclass
class AlertConfig:
    email_enabled: bool = bool(os.getenv("EMAIL_FROM"))
    email_from: str = os.getenv("EMAIL_FROM", "")
    email_to: str = os.getenv("EMAIL_TO", "")
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")

    telegram_enabled: bool = bool(os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN"))
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Alert engine thresholds (adjustable without touching code)
    score_change_threshold: float = 8.0   # pts — minimum change to trigger score alert
    alerts_enabled: bool = True            # master switch

    # Phase 6: frequency & portfolio alert settings
    check_frequency_hours: int = int(os.getenv("ALERT_INTERVAL_HOURS", "24"))
    frequency_mode: str = os.getenv("ALERT_FREQUENCY_MODE", "daily")  # daily | weekly | critical_only
    portfolio_loss_threshold_pct: float = 8.0    # % loss vs avg_cost to trigger PORTFOLIO_LOSS
    portfolio_drift_threshold_pct: float = 5.0   # % drift from optimizer weight to trigger PORTFOLIO_DRIFT
    portfolio_rebalance_threshold_pct: float = 8.0  # total drift to trigger PORTFOLIO_REBALANCE
    sorr_high_threshold_pct: float = 30.0          # SORR early drawdown % to trigger SORR_HIGH
    goal_risk_prob_drop_pct: float = 15.0          # probability drop to trigger GOAL_RISK
    # Proactive coach (backlog 12): "plan sigue OK" after a material portfolio drop
    coach_drop_threshold_pct: float = 8.0          # fire when portfolio return ≤ -this
    coach_plan_prob_floor_pct: float = 40.0        # below this, coach severity escalates
    # Fase E: suggested alignment trades (plan target vs tracker positions)
    alignment_min_trade_usd: float = 200.0   # ignore trades smaller than this (noise / fees)
    alignment_max_trades: int = 6            # cap the suggested-trades list (prioritized)
    ai_explanations_enabled: bool = field(
        default_factory=lambda: os.getenv("ALERT_AI_EXPLANATIONS", "true").lower() in ("true", "1", "yes")
    )
    # Only call AI for alerts at or above this severity (saves tokens on INFO alerts)
    ai_explanations_min_severity: str = field(
        default_factory=lambda: os.getenv("ALERT_AI_MIN_SEVERITY", "warning")
    )
    # Minimum severity to dispatch by profile (conservador=warning, others=info)
    min_severity_conservador: str = "warning"
    min_severity_moderado: str = "info"
    min_severity_agresivo: str = "info"


@dataclass
class ReportConfig:
    """PDF report configuration."""
    output_dir: str = field(default_factory=lambda: os.getenv("REPORT_OUTPUT_DIR", "reports"))
    top_n_opportunities: int = 10         # rows in the top-opportunities table
    include_charts: bool = True           # embed matplotlib charts in PDF
    # Scheduler cadence (used by scripts/run_scheduler.py)
    alert_check_interval_hours: int = int(os.getenv("ALERT_INTERVAL_HOURS", "24"))
    report_day_of_month: int = int(os.getenv("REPORT_DAY", "1"))  # 1 = first of month


CACHE_TTL_HOURS: int = int(os.getenv("CACHE_TTL_HOURS", "24"))

# ---------------------------------------------------------------------------
# Crypto asset detection & normalization
# ---------------------------------------------------------------------------

# All accepted ticker forms for known crypto assets (case-insensitive at runtime)
CRYPTO_TICKERS: Set[str] = {"BTC", "BTC-USD", "BITCOIN", "ETH", "ETH-USD", "ETHEREUM"}

# Canonical form accepted by yfinance for each crypto
_CRYPTO_NORM: Dict[str, str] = {
    "BTC":      "BTC-USD",
    "BITCOIN":  "BTC-USD",
    "ETH":      "ETH-USD",
    "ETHEREUM": "ETH-USD",
}


def is_crypto(symbol: str) -> bool:
    """Return True if *symbol* is a known crypto asset."""
    return symbol.upper() in CRYPTO_TICKERS


def normalize_crypto_ticker(symbol: str) -> str:
    """Map user-facing crypto symbol to the yfinance canonical form.

    Examples:
        "BTC"     → "BTC-USD"
        "BTC-USD" → "BTC-USD"   (already canonical)
        "ETH"     → "ETH-USD"
    """
    s = symbol.upper()
    return _CRYPTO_NORM.get(s, s)


# Default universe — edit freely
DEFAULT_TICKERS: List[str] = [
    # US Mega-Cap Quality
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B",
    # Financials
    "JPM", "V", "MA", "BAC",
    # Healthcare
    "JNJ", "UNH", "ABBV", "PFE",
    # Consumer Staples
    "PG", "KO", "PEP", "WMT",
    # Industrials / Other
    "HD", "CAT", "HON",
    # Dividend Aristocrats
    "O", "T", "XOM", "CVX",
    # ETFs (treated as non-fundamental)
    "SPY", "QQQ", "VTI", "BND",
    # Crypto
    "BTC-USD",
    # Argentina ADRs
    "YPF", "PAM", "CEPU", "LOMA", "MELI", "GLOB", "TEO", "EDN",
]

# Sectors for diversification analysis
SECTOR_MAP: Dict[str, List[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "MELI", "GLOB"],
    "Consumer Discretionary": ["AMZN", "HD"],
    "Financials": ["JPM", "BRK-B", "V", "MA", "BAC"],
    "Healthcare": ["JNJ", "UNH", "ABBV", "PFE"],
    "Consumer Staples": ["PG", "KO", "PEP", "WMT"],
    "Energy": ["XOM", "CVX", "YPF", "PAM", "CEPU"],
    "Industrials": ["CAT", "HON", "LOMA"],
    "Telecom / REIT": ["T", "O", "TEO"],
    "Utilities": ["EDN"],
    # Fallback only — analysis/asset_class.py resolves by quoteType first. Kept in
    # sync so a feed without quoteType still classifies the shipped universes.
    "ETF": ["SPY", "QQQ", "VTI", "BND", "VGT", "SCHD", "VOO", "VXUS", "AGG"],
    "Crypto": ["BTC-USD", "ETH-USD"],
}

# Asset allocation by age (bonds % = age rule + buffer for conservative)
def recommended_bond_pct(age: int) -> float:
    """Conservative: bond % = age. Aggressive: bond % = age - 10."""
    return min(float(age), 80.0)


@dataclass
class AIConfig:
    provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "claude"))
    model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "claude-sonnet-4-6"))
    # Unified key: reads from whichever env-var matches the active provider.
    # Order: Anthropic → xAI → OpenAI (set only the one you need in .env)
    api_key: str = field(default_factory=lambda: (
        os.getenv("ANTHROPIC_API_KEY", "")
        or os.getenv("XAI_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
    ))
    enabled: bool = field(default_factory=lambda: os.getenv("AI_ENABLED", "").lower() in ("true", "1", "yes"))
    use_in_screener: bool = field(default_factory=lambda: os.getenv("AI_USE_IN_SCREENER", "false").lower() in ("true", "1", "yes"))
    # Offline measurement (U0-2). When True the AI enriches the SCORE (moat and
    # tailwind, both cached) but the decision stays rule-based. The decision
    # layer has no cache, so it is the one part of the AI path that cannot run
    # without the network — and `AIAnalyzer.analyze` swallows every failure and
    # falls back silently, so letting it try would produce a rule-based answer
    # while looking like an AI one. Never set from the environment.
    enrich_only: bool = False


@dataclass
class ConsistencyThresholds:
    roe_std_max_excellent: float = 5.0
    roe_std_max_acceptable: float = 12.0
    margin_volatility_max: float = 6.0
    # P1 audit D6: insufficient history must NOT gift ~2.5 pts/dimension (was
    # "neutral"). 0.0 is the conservative retirement default.
    missing_data_score: float = 0.0


@dataclass
class PiotroskiConfig:
    strong_threshold: int = 7
    bonus_strong: float = 12.0
    bonus_good: float = 6.0


@dataclass
class BacktestConfig:
    default_period_years: int = 5
    default_top_n: int = 10
    default_benchmark: str = "SPY"
    risk_free_rate: float = 0.045       # 4.5% annual (10Y Treasury proxy)
    min_history_weeks: int = 52         # minimum weeks of price data required
    results_max_saved: int = 10         # cap saved backtest files shown in UI
    default_rebalance_freq: str = "annual"  # "annual" | "quarterly" | "monthly" | "buy_and_hold"


@dataclass
class CryptoMoatConfig:
    """
    Thresholds for the crypto-specific AI moat scoring system.

    Crypto moat is evaluated entirely via AI qualitative analysis (no
    quantitative financial-statement layer).  Five crypto-native dimensions
    sum to a total of 0–8 pts, matching the equity AI-moat scale exactly.

    Classification thresholds (applied to ai_total alone, 0–8):
      wide_threshold    ≥ 6.0  — only BTC is a realistic Wide-Moat crypto
      narrow_threshold  ≥ 4.0  — strong second-tier assets (ETH, etc.)
      minimal_threshold ≥ 2.0  — limited structural advantage

    Bonus formula: min(total × bonus_factor, max_bonus)
      P1 D9 recalibration: more weight on structural moat vs short-term tech.
      max_bonus = 8.0, bonus_factor = 1.0 → Wide (8pts) can add full +8

    Scoring formula (adjusted_score crypto):
      base_score + tech_pts − vol_penalty − dd_penalty + moat_bonus
      base lowered (28) and tech max lowered (30) so momentum alone rarely reaches BUY.

    max_vol_for_buy: annualized vol % above which strategy caps BUY→HOLD (retirement).

    ai_cache_ttl_hours: 7 days — halvings don't change weekly.
    """
    wide_threshold: float = 6.0
    narrow_threshold: float = 4.0
    minimal_threshold: float = 2.0
    max_bonus: float = 8.0
    bonus_factor: float = 1.0
    ai_cache_ttl_hours: int = 168
    # Crypto adjusted_score components (D9)
    base_score: float = 28.0
    tech_pts_bullish_strong: float = 30.0
    tech_pts_bullish: float = 24.0
    tech_pts_neutral: float = 16.0
    tech_pts_bearish: float = 8.0
    tech_pts_bearish_strong: float = 4.0
    max_vol_for_buy: float = 70.0


@dataclass
class TaxConfig:
    """Statutory corporate income-tax rates, by the country that levies them.

    NOPAT is ``EBIT × (1 − t)``, so ``t`` decides how much of the operating
    profit the company actually keeps — and it is set by law where the company
    is taxed, not where its ADR trades. Both ROIC computations used to hardcode
    the United States' 21 % for every issuer (U3-8): an Argentine company taxed
    at 35 % was credited with keeping 79 cents of every operating dollar.

    Ireland is the reason this is not a one-directional conservatism: at 12.5 %
    the US rate *understates* what the company keeps.

    These are headline statutory rates, not effective rates — a company's real
    tax bill depends on credits, carry-forwards and where it books profit. Using
    the statutory rate is the standard NOPAT convention and is what makes the
    figure comparable across companies; it is an approximation either way, and
    the point of this table is that it is now an approximation per jurisdiction
    instead of one country's rate applied to all of them.
    """

    #: Country name as the data feed reports it → statutory rate, %.
    corporate_tax_rate_pct: dict = field(default_factory=lambda: {
        "United States": 21.0,
        "Argentina": 35.0,
        "Brazil": 34.0,
        "Chile": 27.0,
        "Mexico": 30.0,
        "Colombia": 35.0,
        "Peru": 29.5,
        "Ireland": 12.5,
        "Luxembourg": 24.9,
        "United Kingdom": 25.0,
        "Canada": 26.5,
        "Germany": 29.9,
        "France": 25.0,
        "Spain": 25.0,
        "Netherlands": 25.8,
        "Switzerland": 19.7,
        "Israel": 23.0,
        "China": 25.0,
        "Japan": 29.7,
        "India": 25.2,
        "Australia": 30.0,
        "South Africa": 27.0,
        "Uruguay": 25.0,
    })
    #: Used when the feed reports no country, or one not listed above. Deliberately
    #: NOT the US rate: an unknown jurisdiction is an assumption, and defaulting to
    #: a specific country's rate disguises it as a fact. Roughly the OECD average.
    default_corporate_tax_rate_pct: float = 23.0


@dataclass
class MoatConfig:
    """
    Thresholds and limits for the Economic Moat scoring system.

    Moat total score = quantitative (0–12) + AI qualitative (0–8) = 0–20.

    Classification thresholds (tunable without touching analysis code):
      wide_threshold    — total ≥ 14 → Wide Moat   (Buffett's 20-year moat)
      narrow_threshold  — total ≥  8 → Narrow Moat  (solid but more vulnerable)
      minimal_threshold — total ≥  4 → Minimal Moat  (some protection, eroding)
      below minimal     — None Moat   (commodity / no identifiable advantage)

    Bonus formula: min(moat_total × 0.5, max_bonus)
      max_bonus = 10.0 → a Wide Moat (score ≥ 20) adds at most +10 pts to adjusted_score.
      This is intentionally capped so moat never dominates the full fundamental score.

    ai_cache_ttl_hours: how long AI qualitative results are cached per ticker.
      Default 168h (7 days) — moat is structural and doesn't change week-to-week.

    P2 audit D5 — ROIC vs cost-of-equity proxy (Buffett/Morningstar alignment):
      use_roic_wacc_spread — score roic_sustained by the ROIC *spread* over the
        hurdle, not by absolute ROIC
      risk_free_proxy_pct / default_sector_erp_pct — the hurdle is rf + ERP
      sector_erp_pct — optional per-sector ERP overrides (empty → default)
      roic_spread_* — spread thresholds (percentage points) for 2.0 / 1.0 / 0.5 pts

    U1-4 — the hurdle is a **cost of equity**, not a WACC: rf + a flat sector ERP
      carries no debt, no D/(D+E) weight and no tax shield (and it is not CAPM
      either — there is no beta). The ``*_wacc_*`` identifiers below keep their
      names for backward compatibility; the value they hold is Ke. Building a
      real WACC would need a capital structure and is deliberately out of scope.
      User-facing copy says "costo de equity proxy" (``data/product_ux.py``).
    """
    wide_threshold: float = 14.0
    narrow_threshold: float = 8.0
    minimal_threshold: float = 4.0
    # Quant-only mode (U3-7). The thresholds above live on the 0–20 scale that
    # only exists once the AI layer has run; the quantitative tramo tops out at
    # 12, so measured across the 164-ticker cached universe NOT ONE ticker could
    # ever be Wide without AI. These are the thresholds for that shorter ruler.
    #
    # They are not the 0–20 set rescaled by 12/20 (that would be 8.4/4.8/2.4).
    # Proportional rescaling agrees with the AI-on label on only 58 % of the
    # universe, because a strong quantitative moat predicts a strong qualitative
    # one rather than being independent of it. Fitted against the AI-on label
    # instead, these reach 86 % with no error larger than one step, and they err
    # conservative: 16 understatements against 7 overstatements, and 2 false
    # Wide out of 13. Reproduce with `scripts/measure_score_impact.py --matrix`.
    quant_only_wide_threshold: float = 11.0
    quant_only_narrow_threshold: float = 6.5
    quant_only_minimal_threshold: float = 2.5
    max_bonus: float = 10.0
    ai_cache_ttl_hours: int = 168
    # Offline measurement (U0-2). When True a cache miss returns the
    # quantitative result untouched instead of calling the provider, so a run
    # with AI enabled can never reach the network. Flipped in-process by
    # scripts/measure_score_impact.py; never persisted.
    ai_cache_only: bool = False
    # ROIC − cost-of-equity-proxy spread scoring (D5; name kept per U1-4)
    use_roic_wacc_spread: bool = True
    risk_free_proxy_pct: float = 4.0
    default_sector_erp_pct: float = 5.0
    sector_erp_pct: dict = field(default_factory=lambda: {
        "Technology": 5.0,
        "Healthcare": 4.5,
        "Financials": 5.5,
        "Energy": 6.0,
        "Utilities": 4.0,
        "Consumer Defensive": 4.5,
        "Consumer Cyclical": 5.5,
        "Communication Services": 5.0,
        "Industrials": 5.0,
        "Real Estate": 5.5,
        "Basic Materials": 5.5,
        "Materials": 5.5,
    })
    roic_spread_excellent: float = 10.0   # spread ≥ this → 2.0 pts
    roic_spread_good: float = 4.0         # spread ≥ this → 1.0 pts
    roic_spread_min: float = 0.0          # spread ≥ this → 0.5 pts


@dataclass
class ProfileConfig:
    """
    Risk profile for portfolio optimization.

    Constraints fed directly into the SLSQP optimizer:
      max_position_pct   — hard upper bound per ticker (prevents concentration)
      max_volatility_pct — annualized portfolio volatility ceiling
      min_dividend_yield_pct — portfolio-level weighted dividend yield floor
      max_sector_pct     — hard upper bound per GICS sector
      min_positions      — minimum number of positions (diversification floor)

    Preference / ranking weights (must sum to 1.0) — NOT expected returns:
      score_weight    — weight of adjusted_score when RANKING candidates
      dividend_weight — weight of dividend yield when RANKING candidates
      moat_weight     — weight of moat score when RANKING candidates

      These express what the investor *prefers to own*, and are used by
      ``_select_candidates_for_profile`` (down-select) and
      ``_score_weighted_optimize`` (no-covariance fallback).

      They must NOT feed the expected-return vector μ. Until the 2026-08 audit
      they did, which made the same asset "yield" 5.08% for a conservative
      investor and 7.72% for an aggressive one — an artifact, since an asset's
      return does not depend on who is looking at it. μ now comes from the
      profile-independent ``VIEW_WEIGHTS`` (audit D3).

    Risk appetite:
      risk_aversion — δ in the Black-Litterman prior Π = δ·Σ·w_market. This is
                      where the profile legitimately belongs: a conservative
                      investor demands more return per unit of risk, so the
                      equilibrium anchor tilts defensive. Higher = more averse.

    Large-universe controls:
      pre_filter_top_k           — max candidates entering SLSQP after profile-tilt ranking.
                                   Limits cov matrix size and ensures manageable output.
      target_max_human_positions — ideal core portfolio size for the deterministic core selector.
                                   Used by _select_core_holdings() without LLM.
    """
    name: str
    description: str
    max_position_pct: float
    max_volatility_pct: float
    min_dividend_yield_pct: float
    max_sector_pct: float
    min_positions: int
    score_weight: float
    dividend_weight: float
    moat_weight: float
    max_crypto_pct: float = 3.0   # hard cap per crypto ticker (% of portfolio)
    pre_filter_top_k: int = 30    # max candidates into SLSQP (profile-tilt down-select)
    target_max_human_positions: int = 12  # ideal core size for deterministic core selector
    risk_aversion: float = 2.5    # δ for the Black-Litterman equilibrium prior


# Module-level profile definitions (importable by name)
CONSERVATIVE_PROFILE = ProfileConfig(
    name="Conservador",
    description="Preservación de capital + ingreso por dividendos. Volatilidad controlada.",
    max_position_pct=8.0,
    max_volatility_pct=12.0,
    min_dividend_yield_pct=3.5,
    max_sector_pct=20.0,
    min_positions=10,
    score_weight=0.35,
    dividend_weight=0.45,
    moat_weight=0.20,
    max_crypto_pct=3.0,
    pre_filter_top_k=20,       # conservative: smaller, income-tilted pool
    target_max_human_positions=10,
    risk_aversion=4.0,         # most risk-averse → defensive equilibrium anchor
)

MODERATE_PROFILE = ProfileConfig(
    name="Moderado",
    description="Balance entre crecimiento e ingreso. Exposición al riesgo controlada.",
    max_position_pct=12.0,
    max_volatility_pct=18.0,
    min_dividend_yield_pct=2.5,
    max_sector_pct=25.0,
    min_positions=8,
    score_weight=0.50,
    dividend_weight=0.30,
    moat_weight=0.20,
    max_crypto_pct=5.0,
    pre_filter_top_k=30,       # moderate: balanced pool
    target_max_human_positions=12,
    risk_aversion=2.5,         # textbook default δ
)

AGGRESSIVE_PROFILE = ProfileConfig(
    name="Agresivo",
    description="Maximización de crecimiento a largo plazo. Mayor tolerancia al riesgo.",
    max_position_pct=18.0,
    max_volatility_pct=25.0,
    min_dividend_yield_pct=1.5,
    max_sector_pct=30.0,
    min_positions=5,
    score_weight=0.65,
    dividend_weight=0.15,
    moat_weight=0.20,
    max_crypto_pct=10.0,
    pre_filter_top_k=45,       # aggressive: larger pool for growth coverage
    target_max_human_positions=15,
    risk_aversion=1.5,         # most risk-tolerant → growth-tilted anchor
)

OPTIMIZER_PROFILES: Dict[str, ProfileConfig] = {
    "conservative": CONSERVATIVE_PROFILE,
    "moderate":     MODERATE_PROFILE,
    "aggressive":   AGGRESSIVE_PROFILE,
}


@dataclass
class ViewWeightConfig:
    """
    Weights of the score-derived *view* on expected returns (audit D3, 2026-08).

    In the Black-Litterman framing the optimizer already uses
    (``portfolio/black_litterman.py``), the market equilibrium Π = δ·Σ·w_market
    is the prior and the product's quality score is a **view** on top of it.

    These weights build that view. They are deliberately a single global set,
    NOT per-profile: an asset's expected return is a property of the asset, not
    of the investor looking at it. The investor's profile enters through
    ``ProfileConfig.risk_aversion`` (δ) and through the SLSQP constraints
    (max position, max volatility, dividend floor, sector caps).

    **There is no moat weight, and it is not an omission (U5-6).** A third term
    used to add the moat directly, but ``adjusted_score`` already contains the
    moat bonus — ``min(moat_total × 0.5, MOAT.max_bonus)``, added in
    ``FundamentalAnalyzer.analyze`` — so the moat was paid twice and the
    optimizer overweighted wide-moat companies relative to what the rest of the
    engine says they are worth. The moat now reaches μ exactly once, through the
    score, which is where the engine decided what it was worth.

    **These two no longer sum to 1.0, deliberately.** Renormalising them to
    0.625/0.375 would keep the sum tidy and undo the fix: it inflates the moat
    contribution that legitimately survives inside the score along with
    everything else. Measured over the 150 cached equities, that would RAISE μ by
    1.24 pp, against the 0.50 pp the duplicate removal takes off. They are
    per-component scalers, not shares of a whole; ``OptimizerConfig``'s
    ``er_absolute_cap`` is what keeps the total economically plausible.
    """
    score: float = 0.50       # weight of adjusted_score in the view
    dividend: float = 0.30    # weight of dividend yield in the view

    def as_dict(self) -> dict:
        return {"score": self.score, "dividend": self.dividend}


VIEW_WEIGHTS = ViewWeightConfig()


@dataclass
class OptimizerConfig:
    """
    Global settings for the portfolio optimizer (profile-independent).

    default_profile       — profile key used when no selection is made
    risk_free_rate        — annual Rf subtracted in the attractiveness/vol ratio
                            (the same rate feeds the historical Sharpe of
                            BacktestConfig, which is a real one)
    price_history_years   — years of weekly prices for covariance estimation
    frontier_points       — Monte Carlo portfolios rendered on the Efficient Frontier
    min_weight_pct        — minimum per-ticker allocation (avoids dust positions)
    min_score_threshold   — tickers below this adjusted_score are excluded
    ars_risk_discount     — composite-score multiplier for Argentine ADR tickers
                            in conservative/moderate profiles (reflects currency risk)
    max_ai_screener_tickers — when the selected universe has more than this many tickers,
                              the dashboard auto-disables AI in the screener and shows a
                              banner. AI bulk scoring N>this adds latency/cost without
                              meaningfully changing optimizer output (quant scores suffice).
    price_fetch_max_workers — parallel workers for price matrix fetch
    er_absolute_cap         — P2 audit D4: hard annual expected-return ceiling per ticker
                              (fraction, e.g. 0.14 = 14%). Score-proxy μ can otherwise
                              imply ~18%+ with no economic anchor. Set 0 to disable.
                              NOTE (2026-08 D3): with the global VIEW_WEIGHTS the
                              proxy now tops out at 13%, so this ceiling no longer
                              binds. It is kept as a guardrail in case the view
                              weights or component scales are widened later.
    max_dd_vol_multiple     — U1-10: the **rule of thumb** behind
                              ``max_drawdown_estimate_pct`` (1-year horizon):
                              MaxDD ≈ −multiple × annual volatility. It is not a
                              model — nothing is simulated and this portfolio's
                              own price history is never read — so every surface
                              that shows the number says so
                              (``data/product_ux.max_dd_estimate_help``). The
                              simulated drawdown is a different figure and lives
                              in ``MonteCarloResult.median_max_drawdown_pct``
                              (measured on the market series, see U2-2).
    """
    default_profile: str = "conservative"
    risk_free_rate: float = 0.045
    price_history_years: int = 2
    frontier_points: int = 300
    min_weight_pct: float = 1.0
    min_score_threshold: float = 30.0
    ars_risk_discount: float = 0.85
    max_ai_screener_tickers: int = 40
    price_fetch_max_workers: int = 6
    er_absolute_cap: float = 0.14
    max_dd_vol_multiple: float = 1.5


@dataclass
class TailwindConfig:
    """
    Sector-Country structural tailwind layer (Idea 2 — "colas de viento").

    Captures multi-year structural outlooks for (sector, country) or
    (industry, country) combinations — e.g. Argentine oil & gas benefiting
    from the Vaca Muerta ramp — so that national/industry context becomes a
    first-class, auditable input to scoring, the optimizer and plans, instead
    of incidental LLM knowledge.

    Data source: curated JSON at ``data/tailwinds/sector_country.json``
    (human-maintained, intentionally NOT scraped live — auditability over hype).
    The curated data is the source of truth; the optional AI layer only
    interprets/enriches, never invents tailwinds.

    Score scale: -5 (strong headwind) … +10 (strong tailwind). Neutral = 0.

    Classification thresholds (applied to tailwind_score):
      strong_threshold    ≥ +6.0 → "Strong"    (Strong Tailwind)
      moderate_threshold  ≥ +3.0 → "Moderate"  (Moderate Tailwind)
      headwind_threshold  ≤ −2.0 → "Headwind"
      otherwise                  → "Neutral"   (bonus = 0, behavior identical to pre-feature)

    Bonus formula (added to adjusted_score, moat-bonus precedent):
      bonus = clamp(score × bonus_factor, −max_bonus, +max_bonus)
      Defaults: max +8 pts (Strong AR Energy ≈ +6.4) — intentionally smaller
      than the moat cap (+10) so the tailwind never dominates fundamentals.

    optimizer_er_tilt — small extra expected-return tilt per unit of tailwind
      in the optimizer's composite proxy (max ≈ ±0.9% annual at score ±10).
      Set to 0.0 to rely purely on the adjusted_score flow-through.

    ai_cache_ttl_hours: 720h (30 days) — structural outlooks move slowly.
    enabled: master switch — False restores pre-feature behavior everywhere.
    """
    enabled: bool = True
    strong_threshold: float = 6.0
    moderate_threshold: float = 3.0
    headwind_threshold: float = -2.0
    bonus_factor: float = 0.8
    max_bonus: float = 8.0
    optimizer_er_tilt: float = 0.05
    ai_cache_ttl_hours: int = 720
    ai_cache_only: bool = False   # see MoatConfig.ai_cache_only (U0-2)
    data_file: str = "data/tailwinds/sector_country.json"


@dataclass
class DataQualityConfig:
    """
    Thresholds for the data-quality transparency layer (Fase E + P0 policy).

    The whole pipeline (scores, moat, optimizer, MC, plan deltas) depends on
    yfinance. Missing fields silently degrade scores to neutral values, so the
    dashboard surfaces a per-ticker quality badge instead of hiding it.

    Key-field counting (see analysis.fundamental.compute_data_quality):
      partial_missing_fields — at or above this many missing key metrics the
                               ticker is flagged "partial" (🟡)
      poor_missing_fields    — at or above this many, "poor" (🔴). Missing
                               financial statements always mean "poor".
      stale_warning_hours    — cached info older than this is flagged stale
                               (independent dimension from completeness).

    Signal / optimizer policy (P0 — quality governs decisions without rewriting
    scored fundamentals):
      partial_caps_strong_buy — STRONG BUY demoted to BUY when level is partial
      partial_max_confidence  — confidence ceiling for partial (e.g. MEDIUM)
      exclude_poor_from_optimizer — drop poor tickers from SLSQP eligible set
      partial_optimizer_score_haircut — multiply adjusted_score for partial
                               candidates (1.0 = no haircut; default mild 0.95)

    Universe-level rollup (audit item 03 — the Screener used to print a literal
    "calidad good" that contradicted its own per-row column two lines below):
      universe_poor_pct    — share of 🔴 rows at or above which the whole run is "poor"
      universe_partial_pct — share of degraded rows (🔴+🟡) at or above which it is "partial"
    """
    stale_warning_hours: float = 48.0
    partial_missing_fields: int = 3
    poor_missing_fields: int = 6
    partial_caps_strong_buy: bool = True
    partial_max_confidence: str = "MEDIUM"
    exclude_poor_from_optimizer: bool = True
    partial_optimizer_score_haircut: float = 0.95
    universe_poor_pct: float = 10.0
    universe_partial_pct: float = 20.0


@dataclass
class ScreenerConfig:
    """
    The Opportunity Screener's shortlist funnel (audit item 06).

    Measured on US Quality (78 companies, 2026-08-17): 67 of them — 86 % — carried
    a buy signal, and the median adjusted score was 74.8, i.e. the "Strong Buy ≥75"
    line sat on the median of the universe. That is what absolute thresholds do to
    an already-curated quality list: ``STRATEGY.strong_buy_score`` / ``buy_score``
    were calibrated against the whole market, so applied to a pre-filtered
    population they must approve nearly all of it.

    These knobs add the missing *relative* dimension without touching the engine's
    absolute verdict, which is still the right answer to "is this a good company?".

    Update (2026-08-22): the absolute thresholds were re-anchored to 82/68/55 once
    it turned out they were cutting ``adjusted_score`` while calibrated for
    ``total_score`` — see ``StrategyConfig``. That narrows the funnel's "buy
    signal" step considerably, but it does not replace this layer: a re-anchored
    absolute cut still cannot answer "how does this name rank against the others in
    *this* run", which is what ``shortlist_percentile`` is for.

    Fields:
      shortlist_percentile      — minimum percentile within the analyzed run
      shortlist_max_names       — hard cap on the shortlist (0 = no cap)
      shortlist_exclude_poor_data — drop 🔴 tickers before ranking
      shortlist_require_buy_signal — keep only STRONG BUY / BUY
      concentration_warn_pct    — warn when one sector exceeds this share of the
                                  shortlist (audit item 07 — the top-15 measured
                                  12/15 Technology with no warning at all)
    """

    shortlist_percentile: float = 75.0
    shortlist_max_names: int = 10
    shortlist_exclude_poor_data: bool = True
    shortlist_require_buy_signal: bool = True
    concentration_warn_pct: float = 50.0
    # How many names the ranking chart draws. Drawing one bar per company turned
    # into a ~1.700px wall that repeated the table above it (audit item 19).
    chart_top_n: int = 15

    # Run cost and persistence (audit items 13/15/16/17).
    #   default_max_tickers  — where the "how many to analyse" slider starts. The
    #                          old default was the whole universe, i.e. the slowest
    #                          possible first run (~5 min measured on 85 tickers).
    #   persist_runs         — keep the last run on disk so reopening the app is
    #                          not another cold run.
    #   run_max_age_hours    — a stored run older than this is offered for refresh.
    #   fallback_seconds_per_ticker — ETA seed before any run has been measured.
    default_max_tickers: int = 25
    persist_runs: bool = True
    run_max_age_hours: float = 12.0
    fallback_seconds_per_ticker: float = 3.5

    # Named filter presets for the full table (audit item 09). Keys must match
    # ``analysis.ranking.FilterCriteria`` fields; values are plain data so the
    # presets can be edited here without touching the page.
    filter_presets: Dict[str, Dict[str, Any]] = field(
        default_factory=lambda: {
            "Compras con datos completos": {
                "signals": ("STRONG BUY", "BUY"),
                "quality_levels": ("good",),
            },
            "Foso ancho": {"moats": ("Wide",)},
            "Paga dividendo y es barata": {
                "signals": ("STRONG BUY", "BUY"),
                "min_percentile": 50.0,
            },
            "Lo que descarté": {"signals": ("HOLD", "REDUCE", "SELL", "AVOID")},
            "Solo mi watchlist": {"only_watchlist": True},
        }
    )


@dataclass
class AssetClassConfig:
    """
    Which assets the fundamental scorer is allowed to judge (audit item 01).

    An index ETF, a bond fund and a coin have no ROE, no Piotroski F-Score and no
    economic moat *by construction* — they have no financial statements at all.
    Running them through the equity scorer does not produce a weak score, it
    produces a **meaningless** one: measured on the US Quality universe, SPY /
    QQQ / VTI / BND / SCHD / VGT all landed at 22–25 and were the six worst of
    85, each with a SELL signal. For a retirement product those are precisely the
    canonical core holdings.

    The classification is resolved from yfinance's ``quoteType`` first (so a new
    ETF added to any universe is recognised without editing a list), and only
    falls back to the curated ``SECTOR_MAP`` / sector names when the feed gives
    nothing. That fallback order is the fix for the drift we measured: VGT and
    SCHD are ETFs that were missing from ``SECTOR_MAP["ETF"]`` and so resolved to
    sector "Unknown" and were scored as if they were companies.

    Fields:
      fund_quote_types    — quoteType values that mean "pooled vehicle"
      crypto_quote_types  — quoteType values that mean "cryptocurrency"
      fund_sectors        — sector strings that imply a fund when quoteType is absent
      crypto_sectors      — sector strings that imply crypto when quoteType is absent
      scorable_classes    — classes the fundamental score/signal is valid for
      labels              — UI label per class (Spanish, table-cell sized)
    """

    fund_quote_types: tuple = ("ETF", "MUTUALFUND", "INDEX", "CLOSEDENDFUND", "MONEYMARKET")
    crypto_quote_types: tuple = ("CRYPTOCURRENCY",)
    fund_sectors: tuple = ("ETF", "Index", "Fund")
    crypto_sectors: tuple = ("Crypto", "Crypto / Digital Asset")
    scorable_classes: tuple = ("equity",)
    labels: Dict[str, str] = field(
        default_factory=lambda: {
            "equity": "Acción",
            "fund": "Fondo / ETF",
            "crypto": "Cripto",
        }
    )


@dataclass
class MonteCarloConfig:
    """
    Monte Carlo simulation parameters.

    Conservative adjustments applied to historical returns before simulation:
      vol_adjustment  — multiply deviations by this factor (>1 = more volatile)
      mean_haircut    — multiply expected return by this factor (<1 = lower return)
    These reflect two realities: (1) future volatility tends to exceed historical,
    (2) future expected returns for equities are likely lower than 2010-2024 history.

    min_history_weeks — minimum weeks of history required to run simulation.
    default_n_sims    — simulation count shown in the dashboard by default.

    P2 D11 transparency:
      warn_static_weights / warn_crypto_without_extra_vol — append human-readable
      assumptions to MonteCarloResult.warnings (no change to path math).
      default_vol_scale_* — suggested caller overrides by profile (informational).

    Cash-flow cadence (U4-1). How many times a year money moves in or out:
      contribution_periods_per_year — 12 = the saver deposits monthly, which is
        the unit the profile asks for ("Ahorro mensual aproximado"). Setting it
        to 1 reproduces the pre-tier2 engine exactly: a single deposit in week
        52, which cost eleven of the twelve deposits their partial year of
        growth. Kept configurable so both cadences stay under test.
      withdrawal_periods_per_year — 1. Retirement withdrawals stay annual on
        purpose: the guardrails strategy IS an annual review, so paying monthly
        while deciding annually is a separate design question (backlog U4-1c),
        not a side effect of fixing the contribution cadence.
    """
    vol_adjustment: float = 1.10         # +10% volatility (conservative)
    mean_haircut: float = 0.80           # -20% expected return (conservative)
    contribution_periods_per_year: int = 12
    withdrawal_periods_per_year: int = 1
    min_history_weeks: int = 104         # 2 years minimum
    default_n_sims: int = 10_000
    default_horizon_years: int = 20
    block_size_weeks: int = 4            # bootstrap block size (preserves autocorrelation)
    warn_static_weights: bool = True
    warn_crypto_without_extra_vol: bool = True
    default_vol_scale_conservative: float = 1.15
    default_vol_scale_moderate: float = 1.0
    default_vol_scale_aggressive: float = 0.95


@dataclass
class EconomicDragConfig:
    """
    Real-world economic "drags" applied on top of the (already conservative)
    Monte Carlo engine to fight the "Retirement Advisor" expectation mismatch:
    the base numbers implicitly assume zero fees, zero dividend tax, zero
    rebalance cost and no AR-specific frictions. This layer makes those
    assumptions explicit, configurable and *traceable*.

    Philosophy (mirrors TailwindConfig): curated/config first-class, never
    silent, the deterministic path stays valid. Drags are OPT-IN at the engine
    level — ``MonteCarloSimulator.run(drags=...)`` only applies them when an
    explicit drags dict is passed, so every existing caller and test keeps
    byte-identical results. The UI passes the active drags; the result then
    carries BOTH "base" (no-drag, reference) and "with-drags" metrics.

    All fields are annual percentages (e.g. 0.20 == 0.20% per year):
      annual_fee_pct            — TER + advisory drag (typical low-cost ETF ≈ 0.2%)
      dividend_tax_drag_pct     — effective annual drag from dividend tax for a
                                  non-resident (suggest 15-30% of the gross yield;
                                  expressed here directly as an annual % of NAV)
      rebalance_cost_annual_pct — spreads + commissions from periodic rebalancing
      ar_buffer_pct             — extra conservative haircut for AR residents
                                  (cepo / FX vol / inflation differential proxy).
                                  AVOID DOUBLE-COUNTING: the optimizer already
                                  applies ``OptimizerConfig.ars_risk_discount``
                                  (0.85×) to Argentine ADR scores in the
                                  Conservative/Moderate profiles, tilting the
                                  allocation away from AR risk. This buffer is for
                                  plan-level country risk NOT already captured by
                                  how the portfolio was selected; keep it at 0
                                  when the ARS score discount is doing that job.
      enabled                   — master switch (UI default; engine still opt-in)
    """
    enabled: bool = True
    annual_fee_pct: float = 0.20
    dividend_tax_drag_pct: float = 0.0
    rebalance_cost_annual_pct: float = 0.05
    ar_buffer_pct: float = 0.0

    def total_annual_drag_pct(self) -> float:
        """Sum of all enabled drag components, as an annual percentage."""
        return float(
            self.annual_fee_pct
            + self.dividend_tax_drag_pct
            + self.rebalance_cost_annual_pct
            + self.ar_buffer_pct
        )

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "annual_fee_pct": self.annual_fee_pct,
            "dividend_tax_drag_pct": self.dividend_tax_drag_pct,
            "rebalance_cost_annual_pct": self.rebalance_cost_annual_pct,
            "ar_buffer_pct": self.ar_buffer_pct,
            "total_annual_drag_pct": round(self.total_annual_drag_pct(), 4),
        }


@dataclass
class WithdrawalConfig:
    """
    Decumulation / withdrawal-strategy parameters (Fase H.1).

    The base Monte Carlo engine already supports a *fixed real* withdrawal
    (a constant inflation-adjusted dollar amount). This config makes the
    full set of decumulation strategies first-class and configurable —
    never hardcoded — mirroring the philosophy of EconomicDragConfig and
    TailwindConfig: curated/config first, deterministic path always valid,
    AI only narrates.

    Strategies (``kind``):
      "fixed_real"   — constant inflation-adjusted dollar amount (4% rule
                       style). Highest ruin risk but most predictable income.
      "constant_pct" — withdraw a fixed % of the *current* portfolio value
                       each year. Never fully depletes, but income varies.
      "guardrails"   — **simplified** Guyton-Klinger: start at
                       ``base_withdrawal_pct`` of the initial value, then cut
                       spending when the current withdrawal rate breaches the
                       upper guardrail (portfolio fell) and raise it when it
                       falls below the lower guardrail (portfolio grew).
                       Balances stability and longevity.
                       Two of the four GK rules run (capital preservation and
                       prosperity); the inflation rule, the portfolio-management
                       rule and the time bound on the cut do not — see
                       ``portfolio/decumulation`` and U1-6. The bands below are
                       the whole method: nothing else about GK is implemented.

    All percentages are human-scale (4.0 == 4% per year). Bands and step
    sizes are fractions (0.20 == 20%). ``enabled`` is a UI default; the engine
    stays opt-in — ``MonteCarloSimulator.run(withdrawal_strategy=...)`` only
    activates a strategy when one is explicitly passed, so every existing
    caller and test keeps byte-identical results.
    """
    enabled: bool = True
    default_strategy: str = "fixed_real"
    base_withdrawal_pct: float = 4.0          # initial annual withdrawal rate
    constant_pct: float = 4.0                 # % of current value for "constant_pct"
    # Guardrails (simplified Guyton-Klinger), as fractions of the initial rate:
    guardrail_ceiling_band: float = 0.20      # WR this much ABOVE initial → cut spending
    guardrail_floor_band: float = 0.20        # WR this much BELOW initial → raise spending
    guardrail_cut_pct: float = 0.10           # spending cut when upper guardrail hit
    guardrail_raise_pct: float = 0.10         # spending raise when lower guardrail hit
    default_longevity_years: int = 30         # planning horizon for "outliving money"

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "default_strategy": self.default_strategy,
            "base_withdrawal_pct": self.base_withdrawal_pct,
            "constant_pct": self.constant_pct,
            "guardrail_ceiling_band": self.guardrail_ceiling_band,
            "guardrail_floor_band": self.guardrail_floor_band,
            "guardrail_cut_pct": self.guardrail_cut_pct,
            "guardrail_raise_pct": self.guardrail_raise_pct,
            "default_longevity_years": self.default_longevity_years,
        }


@dataclass
class PlanHealthConfig:
    """
    Longitudinal plan-health history parameters (Fase H.2).

    A "health record" is a lightweight periodic snapshot of how a saved plan is
    holding up vs the market (weighted price drift since save, score at save,
    Monte Carlo P50, data quality). Recording these over time turns the plan
    from a one-off snapshot into a *living* target with a visible trend, and
    enables early detection of silent structural drift ("plan envejecido").

    Philosophy (mirrors the rest of the project): config first-class, nothing
    hardcoded, opt-in. Recording is explicit (a button) or, when ``auto_record``
    is enabled, performed by the background scheduler.

    Fields:
      enabled                 — master switch for the feature (UI default).
      auto_record             — let the scheduler record health on its run.
      max_records             — cap of stored records per plan (oldest trimmed).
      min_days_between_records — dedup window for automatic recording (days).
      degradation_drift_pct   — |weighted drift| this high, sustained, flags
                                "plan health degradation".
      degradation_min_records — records required before degradation can fire.
    """
    enabled: bool = True
    auto_record: bool = False
    max_records: int = 60
    min_days_between_records: int = 1
    degradation_drift_pct: float = 15.0
    degradation_min_records: int = 2

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "auto_record": self.auto_record,
            "max_records": self.max_records,
            "min_days_between_records": self.min_days_between_records,
            "degradation_drift_pct": self.degradation_drift_pct,
            "degradation_min_records": self.degradation_min_records,
        }


@dataclass
class SensitivityConfig:
    """
    Sensitivity / scenario-lab parameters (Fase H.3).

    Drives the "what-if" workbench: how far to move each assumption when
    building a tornado (one factor at a time) and the predefined retirement
    scenarios. Mirrors the project philosophy — magnitudes are config, never
    hardcoded; the engine is pure and re-uses the existing Monte Carlo.

    Fields (deltas applied symmetrically low/high unless noted):
      inflation_delta_pct  — ± percentage points on the withdrawal growth rate.
      fee_drag_delta_pct   — ± annual % on the economic-drag total.
      real_return_delta    — ± relative change on the return scale (0.10 = ±10%).
      vol_delta            — ± relative change on the volatility scale.
      longevity_delta_years— ± years for the "live longer / shorter" scenario.
      full_drag_pct        — realistic full-friction total for the "drags full"
                             scenario (fees + tax + rebalance + AR buffer).
      n_sims               — lighter simulation count for the lab (speed; the
                             main Monte Carlo tab keeps MONTE_CARLO.default_n_sims).
    """
    enabled: bool = True
    inflation_delta_pct: float = 1.0
    fee_drag_delta_pct: float = 0.30
    real_return_delta: float = 0.10
    vol_delta: float = 0.10
    longevity_delta_years: int = 5
    full_drag_pct: float = 1.00
    n_sims: int = 2_000

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "inflation_delta_pct": self.inflation_delta_pct,
            "fee_drag_delta_pct": self.fee_drag_delta_pct,
            "real_return_delta": self.real_return_delta,
            "vol_delta": self.vol_delta,
            "longevity_delta_years": self.longevity_delta_years,
            "full_drag_pct": self.full_drag_pct,
            "n_sims": self.n_sims,
        }


@dataclass
class GoalCardConfig:
    """
    Umbrales de la card "🎯 Resultados por meta" (`7_Simulaciones.py`).

    Existe para que la UI de metas deje de hardcodear números y, sobre todo,
    para que el semáforo SORR del dashboard **no contradiga al motor de
    alertas** (auditoría de la card, 2026-08).

    Semáforo SORR — la regla es «cualquiera de los dos ejes basta»:
        🔴 Alto  : sorr >= high_sorr_pct  OR  drawdown >= high_dd_pct
        🟢 Bajo  : sorr <  low_sorr_pct   AND drawdown <  low_dd_pct
        🟡 Medio : el resto
    `high_sorr_pct` se alinea deliberadamente con
    `ALERTS.sorr_high_threshold_pct`: sin eso, un plan con SORR 35 % dispara
    un email SORR_HIGH mientras el dashboard lo pinta de amarillo.

    Fields:
      high_sorr_pct        — SORR temprano (%) a partir del cual el riesgo es Alto.
      high_dd_pct          — drawdown mediano (%) a partir del cual el riesgo es Alto.
      low_sorr_pct         — SORR por debajo del cual (junto a low_dd_pct) es Bajo.
      low_dd_pct           — drawdown por debajo del cual (junto a low_sorr_pct) es Bajo.
      success_target_pct   — probabilidad objetivo del consejo de ahorro y del
                             KPI "metas con >X% de prob. de éxito".
      advice_n_sims        — sims por iteración del solver de ahorro (lab liviano,
                             mismo criterio que SENSITIVITY.n_sims).
      advice_max_iter      — iteraciones de bisección del solver de ahorro.
      chart_log_scale_ratio— si la meta supera N× el escenario optimista (p95),
                             el eje Y del fan chart pasa a escala logarítmica;
                             si no, la meta aplasta la proyección contra el 0.
    """
    high_sorr_pct: float = 30.0        # == ALERTS.sorr_high_threshold_pct
    high_dd_pct: float = 45.0
    low_sorr_pct: float = 25.0
    low_dd_pct: float = 30.0
    success_target_pct: float = 80.0
    advice_n_sims: int = 2_000
    advice_max_iter: int = 12
    chart_log_scale_ratio: float = 4.0

    def as_dict(self) -> dict:
        return {
            "high_sorr_pct": self.high_sorr_pct,
            "high_dd_pct": self.high_dd_pct,
            "low_sorr_pct": self.low_sorr_pct,
            "low_dd_pct": self.low_dd_pct,
            "success_target_pct": self.success_target_pct,
            "advice_n_sims": self.advice_n_sims,
            "advice_max_iter": self.advice_max_iter,
            "chart_log_scale_ratio": self.chart_log_scale_ratio,
        }


@dataclass
class PersonalBookConfig:
    """
    Parámetros del análisis de sizing para el **Libro Personal** (Fase I).

    IMPORTANTE — filosofía opuesta al optimizer de retiro:
    El resto del proyecto (CONSERVATIVE/MODERATE/AGGRESSIVE profiles,
    ``STRATEGY.max_position_pct`` = 8%, ``min_positions`` = 10, constraints SLSQP)
    está diseñado **conservador y diversificado** para una cuenta de retiro.

    Este config modela lo contrario: un **libro personal individual** (NO un fondo,
    hedge fund ni mandato institucional). La ventaja estructural del individuo es la
    **libertad de concentración**: puede mantener 20-30%+ en una idea de altísima
    convicción porque no tiene mandatos de diversificación regulatorios, ni límites
    por emisor (~5-10% típicos en fondos), ni riesgo de redenciones que fuerzan
    ventas en iliquidez, ni comités de riesgo ni "career risk". El sizing concentrado
    puede ser una **fuente de alpha** (edge de convicción profunda + paciencia).

    Este config vive **en paralelo** y NO debe contaminar ni relajar los paths de
    retiro. Todos los thresholds son ajustables (config-first, nada hardcodeado).

    Campos:
      enabled                            — master switch de la feature (UI).
      core_high_conviction_max_pct       — techo "core" para alta convicción (%).
      satellite_max_pct                  — techo sugerido para posiciones satélite.
      trim_concentration_threshold_pct   — > esto + tesis intacta sin catalyst nuevo
                                           → se sugiere TRIM parcial (disciplina de
                                           tamaño / re-asignación de convicción).
      max_practical_concentration_single_name — hard ceiling personal; más allá es
                                           "demasiado incluso para un individuo".
      min_score_for_core_concentration   — adjusted_score mínimo para ser "core".
      aggressive_accumulate_weight_pct   — debajo de este peso, un core elegible se
                                           sugiere ACUMULAR_AGRESIVO.
      moderate_accumulate_weight_pct     — techo de peso para ACUMULAR_MODERADO.
      min_score_for_moderate_accumulate  — score mínimo para acumular moderado.
      sell_all_score                     — score por debajo del cual la tesis se
                                           considera rota → VENDER_TODO/PARTE.
      drawdown_shock_pct                 — shock hipotético para estimar impacto en
                                           el libro ("-X% aquí mueve el libro -Y%").
      high_concentration_risk_note_pct   — peso a partir del cual SIEMPRE se agrega
                                           una nota de riesgo de concentración.
      require_user_high_conviction_for_over_15pct — exigir convicción HIGH del
                                           usuario para permitir >15% intencional.
      wide_moat_bonus_for_concentration  — un moat Wide habilita más concentración.
      default_conviction                 — convicción asumida cuando el usuario no
                                           la declaró para un ticker ("MEDIUM").
    """
    enabled: bool = True
    core_high_conviction_max_pct: float = 30.0
    satellite_max_pct: float = 10.0
    trim_concentration_threshold_pct: float = 25.0
    max_practical_concentration_single_name: float = 40.0
    min_score_for_core_concentration: float = 72.0
    aggressive_accumulate_weight_pct: float = 12.0
    moderate_accumulate_weight_pct: float = 15.0
    min_score_for_moderate_accumulate: float = 60.0
    sell_all_score: float = 40.0
    drawdown_shock_pct: float = 35.0
    high_concentration_risk_note_pct: float = 20.0
    require_user_high_conviction_for_over_15pct: bool = True
    wide_moat_bonus_for_concentration: bool = True
    default_conviction: str = "MEDIUM"

    # Ponderación documentada de los 4 ejes de decisión (suma 100). Se muestra en
    # la UI y se referencia en las justificaciones para transparencia total.
    weight_quality_moat_tailwind: int = 45
    weight_valuation_technical: int = 20
    weight_user_conviction: int = 20
    weight_book_context_risk: int = 15

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "core_high_conviction_max_pct": self.core_high_conviction_max_pct,
            "satellite_max_pct": self.satellite_max_pct,
            "trim_concentration_threshold_pct": self.trim_concentration_threshold_pct,
            "max_practical_concentration_single_name": self.max_practical_concentration_single_name,
            "min_score_for_core_concentration": self.min_score_for_core_concentration,
            "aggressive_accumulate_weight_pct": self.aggressive_accumulate_weight_pct,
            "moderate_accumulate_weight_pct": self.moderate_accumulate_weight_pct,
            "min_score_for_moderate_accumulate": self.min_score_for_moderate_accumulate,
            "sell_all_score": self.sell_all_score,
            "drawdown_shock_pct": self.drawdown_shock_pct,
            "high_concentration_risk_note_pct": self.high_concentration_risk_note_pct,
            "require_user_high_conviction_for_over_15pct": self.require_user_high_conviction_for_over_15pct,
            "wide_moat_bonus_for_concentration": self.wide_moat_bonus_for_concentration,
            "default_conviction": self.default_conviction,
            "weight_quality_moat_tailwind": self.weight_quality_moat_tailwind,
            "weight_valuation_technical": self.weight_valuation_technical,
            "weight_user_conviction": self.weight_user_conviction,
            "weight_book_context_risk": self.weight_book_context_risk,
        }


@dataclass
class TrackRecordConfig:
    """
    Track record / calibration parameters (Gran Salto — Fase 1).

    Every recommendation the engine emits is logged; outcomes are scored at
    fixed horizons against a benchmark. This config keeps the scoring rules
    out of the modules — mirroring the project philosophy (config centralizada,
    nunca hardcodear números en módulos de análisis).

    Fields:
      horizons_days        — horizons, in CALENDAR days, at which each
                             recommendation is scored. The scorer adds
                             ``timedelta(days=h)`` to the log date, so this must
                             be calendar days and nothing else. It used to hold
                             252 — the number of *trading* days in a year —
                             described as "≈ 12 trading months", which made the
                             annual horizon last 8.3 months (U5-15).
      benchmark            — symbol used as the comparison benchmark.
      hold_band_pct_by_horizon — the HOLD band per horizon. One band for every
                             horizon graded a month and a year the same way, and
                             dispersion grows with the square root of time: at
                             ±5 % almost any equity is outside the band over
                             twelve months, so a HOLD was close to automatically
                             wrong at the long horizon (U5-15). The 30-day value
                             is the shipped, calibrated anchor; the others are
                             scaled from it by √t and are a calibration choice,
                             not an empirical finding — the sample is far too
                             young to settle them (22 outcomes, all at 30 days).
      hold_band_pct        — fallback for a horizon not listed above. For HOLD
                             recommendations, a hit means the ticker's
                             absolute return stayed within ±this band (i.e. "hold"
                             was the right call — no big move missed/avoided).
      min_confidence_for_calibration — confidence levels tracked for calibration.
      enabled              — master switch for the capture hooks.
      dedupe_same_day      — collapse repeated (symbol, action) logs within the
                             same UTC day so a refresh loop doesn't inflate counts.
    """
    horizons_days: tuple = (30, 90, 365)
    benchmark: str = "SPY"
    hold_band_pct: float = 5.0
    hold_band_pct_by_horizon: dict = field(default_factory=lambda: {
        30: 5.0,     # shipped anchor
        90: 8.7,     # 5.0 × √(90/30)
        365: 17.4,   # 5.0 × √(365/30)
    })
    min_confidence_for_calibration: tuple = ("HIGH", "MEDIUM", "LOW")
    enabled: bool = True
    dedupe_same_day: bool = True

    # Which actions count as bullish / bearish for directional hit scoring.
    bullish_actions: tuple = ("STRONG BUY", "BUY")
    bearish_actions: tuple = ("REDUCE", "SELL", "AVOID")

    def as_dict(self) -> dict:
        return {
            "horizons_days": list(self.horizons_days),
            "benchmark": self.benchmark,
            "hold_band_pct": self.hold_band_pct,
            "hold_band_pct_by_horizon": dict(self.hold_band_pct_by_horizon),
            "enabled": self.enabled,
            "dedupe_same_day": self.dedupe_same_day,
            "bullish_actions": list(self.bullish_actions),
            "bearish_actions": list(self.bearish_actions),
        }


@dataclass
class EvalConfig:
    """
    AI evaluation harness parameters (Gran Salto — Fase 2A).

    The harness scores the *quality* of AI decisions against a set of golden
    cases — the prerequisite that lets the multi-agent committee (Fase 2B) be
    improved without flying blind. Thresholds live here, never hardcoded in the
    harness, mirroring the rest of the project.

    Fields:
      conservative_alloc_cap_pct — a single conservative recommendation should
                                   never suggest more than this % in one name;
                                   above it is a red flag for a retirement tool.
      min_reasoning_chars        — narrative shorter than this counts as "empty".
      max_macro_factors          — hard cap on macro_factors list length (matches
                                   the prompt spec: 0, 1 or máximo 2).
      case_pass_threshold        — fraction of weighted checks a case must pass
                                   to be considered "passed".
      suite_pass_threshold       — fraction of cases that must pass for the whole
                                   suite to be considered green.
      require_risk_on_buy        — a BUY/STRONG BUY must still name ≥1 risk
                                   (anti-complacency: combats LLM sycophancy).
    """
    conservative_alloc_cap_pct: float = 15.0
    min_reasoning_chars: int = 80
    max_macro_factors: int = 2
    case_pass_threshold: float = 1.0
    suite_pass_threshold: float = 0.8
    require_risk_on_buy: bool = True

    def as_dict(self) -> dict:
        return {
            "conservative_alloc_cap_pct": self.conservative_alloc_cap_pct,
            "min_reasoning_chars": self.min_reasoning_chars,
            "max_macro_factors": self.max_macro_factors,
            "case_pass_threshold": self.case_pass_threshold,
            "suite_pass_threshold": self.suite_pass_threshold,
            "require_risk_on_buy": self.require_risk_on_buy,
        }


@dataclass
class CommitteeConfig:
    """
    Multi-agent investment committee parameters (Gran Salto — Fase 2B).

    The committee runs specialised agents that debate and produce a verdict with
    explicit dissent, replacing the single-shot AI call for weighty decisions.
    Aggregation is deterministic and auditable; weights and thresholds live here.

    Fields:
      enabled            — master switch for committee mode.
      max_workers        — thread pool size for running agents in parallel
                          (threads, not asyncio — the project is synchronous).
      cache_ttl_hours    — verdict cache TTL; the committee is reserved for
                          weighty decisions, not for refreshing dozens of tickers.
      vote_weights       — per-role weight in the (deterministic) consensus vote.
                          The Devil's Advocate has a moderate vote but its concerns
                          are ALWAYS surfaced as dissent regardless of the vote.
      strong_buy_lean / buy_lean / reduce_lean / sell_lean — thresholds mapping the
                          weighted lean score back to an action.
      downgrade_confidence_on_strong_dissent — when the bear case is strong, drop
                          the verdict confidence one notch (conservative bias).
    """
    enabled: bool = True
    max_workers: int = 5
    cache_ttl_hours: int = 24

    vote_weights: dict = field(default_factory=lambda: {
        "Analista Fundamental": 1.0,
        "Estratega Macro":      0.8,
        "Abogado del Diablo":   0.7,
        "Portfolio Manager":    1.0,
        "Behavioral Coach":     0.3,
    })

    strong_buy_lean: float = 1.5
    buy_lean: float = 0.5
    reduce_lean: float = -0.5
    sell_lean: float = -1.5
    downgrade_confidence_on_strong_dissent: bool = True

    # --- Portfolio-level committee (evalúa el PLAN, no un ticker) --------- #
    # Reuses the same deterministic aggregation + lean thresholds; only the
    # per-role weights and the display labels differ. The Devil's Advocate keeps
    # the exact role name so the always-on dissent logic works unchanged.
    portfolio_vote_weights: dict = field(default_factory=lambda: {
        "Estratega del Plan": 1.0,
        "Gestor de Riesgo":   1.0,
        "Estratega Macro":    0.7,
        "Abogado del Diablo": 0.8,
    })

    # Map the internal stance/action vocabulary to plan-health labels for display.
    portfolio_action_labels: dict = field(default_factory=lambda: {
        "STRONG BUY": "Plan muy sólido",
        "BUY":        "Plan sólido",
        "HOLD":       "Mantener con ajustes",
        "REDUCE":     "Necesita ajustes",
        "SELL":       "Reestructurar",
    })

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "max_workers": self.max_workers,
            "cache_ttl_hours": self.cache_ttl_hours,
            "vote_weights": dict(self.vote_weights),
            "strong_buy_lean": self.strong_buy_lean,
            "buy_lean": self.buy_lean,
            "reduce_lean": self.reduce_lean,
            "sell_lean": self.sell_lean,
            "downgrade_confidence_on_strong_dissent": self.downgrade_confidence_on_strong_dissent,
            "portfolio_vote_weights": dict(self.portfolio_vote_weights),
            "portfolio_action_labels": dict(self.portfolio_action_labels),
        }


@dataclass
class MultiSourceConfig:
    """
    Multi-source data + reconciliation parameters (Gran Salto — Fase 3A).

    Everything enters through yfinance today (garbage in, garbage out). This layer
    pulls the same raw facts from more than one source (SEC EDGAR filings, FRED,
    yfinance) and a reconciliation step flags discrepancies between them, so a
    silently wrong number gets surfaced instead of trusted blindly.

    Fields:
      enabled              — master switch for multi-source reconciliation.
      attach_in_pipeline   — when True (and enabled), FundamentalAnalyzer.analyze
                            best-effort attaches cross-source quality to the
                            badge. UI Calidad de Datos works regardless.
                            Was briefly OFF on 2026-08-18: the cross-check
                            compared periods that did not match (yfinance TTM vs
                            SEC's last closed FY, plus dead us-gaap tags serving
                            FY2010 figures), downgrading 22 of 25 tickers that had
                            **zero** missing metrics and demoting 16 STRONG BUY to
                            BUY. Back ON now that ``reconcile()`` refuses to
                            compare mismatched periods: re-measured on the same 24
                            companies, 0 conflicts (was 38) and 0 false
                            downgrades.
                            **Know what this buys you.** Once periods align, every
                            comparable field agrees to Δ=0.00% — yfinance's annual
                            statements are derived from the same SEC filings, so
                            this is a *provenance* check (does the number the score
                            used trace to the current 10-K?), not independent
                            verification. It cannot catch a wrong figure common to
                            both. Real independent verification needs the third
                            source: set FMP_API_KEY.
                            Cost: ~1.2 s/ticker of SEC downloads against the
                            screener's 3.5 s/ticker budget. Set SEC_USER_AGENT to a
                            real contact before running large universes — the
                            default below is a placeholder and SEC throttles on
                            fair-access grounds.
      source_priority      — order used to pick the "chosen" value per field
                            (earlier = more trusted). SEC filings beat yfinance.
      discrepancy_pct      — relative difference (%) above which two sources are
                            considered in conflict for a field.
      conflict_downgrades_quality — a material conflict drops the data-quality
                            badge one level (good→partial→poor).
      sec_user_agent       — SEC EDGAR requires a descriptive User-Agent string.
      fred_api_key         — optional FRED key (macro series); read from env.
      request_timeout_s    — network timeout for source adapters.
    """
    enabled: bool = True
    attach_in_pipeline: bool = True
    source_priority: tuple = ("sec_edgar", "yfinance", "fred", "fmp", "alpha_vantage")
    discrepancy_pct: float = 5.0
    conflict_downgrades_quality: bool = True
    sec_user_agent: str = field(
        default_factory=lambda: os.getenv("SEC_USER_AGENT", "retirement-advisor contact@example.com")
    )
    fred_api_key: str = field(default_factory=lambda: os.getenv("FRED_API_KEY", ""))
    fmp_api_key: str = field(default_factory=lambda: os.getenv("FMP_API_KEY", ""))
    request_timeout_s: float = 10.0

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "attach_in_pipeline": self.attach_in_pipeline,
            "source_priority": list(self.source_priority),
            "discrepancy_pct": self.discrepancy_pct,
            "conflict_downgrades_quality": self.conflict_downgrades_quality,
            "has_fred_key": bool(self.fred_api_key),
            "has_fmp_key": bool(self.fmp_api_key),
            "request_timeout_s": self.request_timeout_s,
        }


@dataclass
class MacroRagConfig:
    """
    Real-time macro RAG parameters (Gran Salto — Fase 3B).

    Instead of asking the LLM to "use your current macro knowledge" (training data,
    potentially stale or invented), we index dated macro facts (Fed releases, FRED
    series, economic news) and inject the most relevant ones as **fresh, dated
    context** into the prompts. macro_factors stops being an act of faith and gets
    anchored to verifiable, time-stamped facts.

    Fields:
      enabled        — master switch for macro-context injection.
      top_k          — how many retrieved docs to inject.
      max_age_days   — ignore docs older than this (freshness gate); a "fresh"
                      context must actually be fresh.
      min_score      — minimum retrieval relevance (0-1) to include a doc.
      max_context_chars — cap injected context size to control token cost.
    """
    enabled: bool = True
    top_k: int = 4
    max_age_days: int = 120
    min_score: float = 0.02
    max_context_chars: int = 1200

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "top_k": self.top_k,
            "max_age_days": self.max_age_days,
            "min_score": self.min_score,
            "max_context_chars": self.max_context_chars,
        }


@dataclass
class ChatConfig:
    """
    Conversational agent parameters (Gran Salto — Fase 4).

    "Hablá con tu plan": a chat where an orchestrator agent routes a natural
    language question to the right deterministic tool, runs it, and narrates over
    the REAL numbers — never inventing figures (strict tool-calling).

    Fields:
      enabled            — master switch for the chat.
      max_router_tokens  — token budget for the routing (tool-selection) call.
      max_narrate_tokens — token budget for the narration call.
      show_raw_data      — surface the raw tool data alongside the narrative
                          (the product already shows the hard number next to the
                          story; this keeps that anti-hallucination guarantee).
    """
    enabled: bool = True
    max_router_tokens: int = 300
    max_narrate_tokens: int = 700
    show_raw_data: bool = True

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "max_router_tokens": self.max_router_tokens,
            "max_narrate_tokens": self.max_narrate_tokens,
            "show_raw_data": self.show_raw_data,
        }


def _env_rate(name: str) -> Optional[float]:
    """Read an FX override from the environment, or ``None``.

    An unset, unreadable *or non-positive* variable is not an override:
    returning ``None`` for all three keeps ``rate_source`` honest — a typo'd
    ``USD_ARS_OFICIAL`` leaves the placeholders in place and says so instead of
    labelling them "env" — and keeps a zero out of a divisor, where it would
    take down every page that renders the dual view.
    """
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        rate = float(raw)
    except ValueError:
        return None
    return rate if rate > 0 else None


def _rate_or(name: str, fallback: float) -> float:
    rate = _env_rate(name)
    return fallback if rate is None else rate


# Pesos per 1 USD when nobody has told us the real number. They are NOT a
# quote and must never be rendered as one — see ``ArFxConfig.rate_source``.
AR_FX_PLACEHOLDER_OFICIAL = 1000.0
AR_FX_PLACEHOLDER_PARALLEL = 1200.0


@dataclass
class ArFxConfig:
    """
    Argentina dual-currency presentation (backlog 10).

    Product context only: show USD amounts also in ARS (oficial + optional parallel)
    so LatAm users see the brecha. Not a tax/compliance engine; not a live FX feed
    by default — rates are user/config overrideable.

    ``rate_source`` (audit U2-5) says where the numbers came from, because the
    defaults are invented: ``placeholder`` (nobody set anything), ``env`` (the
    operator exported ``USD_ARS_*``) or ``manual`` (a caller passed its own
    rates). The UI reads it to label the conversion as an assumption and to
    withhold the brecha — a gap between two placeholders is arithmetic, not a
    market observation.
    """
    enabled: bool = True
    # Pesos per 1 USD — defaults are placeholders; override in Settings/session.
    # default_factory, not a module-import default: the env is read when an
    # instance is built, so a test can set USD_ARS_* without reloading `config`
    # — reloading swaps every singleton in this module out from under the code
    # that already imported them.
    usd_ars_oficial: float = field(
        default_factory=lambda: _rate_or("USD_ARS_OFICIAL", AR_FX_PLACEHOLDER_OFICIAL)
    )
    usd_ars_parallel: float = field(
        default_factory=lambda: _rate_or("USD_ARS_PARALLEL", AR_FX_PLACEHOLDER_PARALLEL)
    )
    # Resolved in __post_init__ when left empty; pass a value to override.
    rate_source: str = ""
    # Free-form "as of" for the rates (env USD_ARS_ASOF). Empty = unknown.
    rate_asof: str = field(default_factory=lambda: os.getenv("USD_ARS_ASOF", ""))

    def __post_init__(self) -> None:
        if self.rate_source:
            return
        env_of, env_par = _env_rate("USD_ARS_OFICIAL"), _env_rate("USD_ARS_PARALLEL")
        # What the environment (or, failing that, the placeholders) would have
        # produced. The label has to describe the values actually held, so a
        # caller passing its own rates reads "manual" even under a set env.
        from_env = (
            AR_FX_PLACEHOLDER_OFICIAL if env_of is None else env_of,
            AR_FX_PLACEHOLDER_PARALLEL if env_par is None else env_par,
        )
        if (float(self.usd_ars_oficial), float(self.usd_ars_parallel)) != from_env:
            self.rate_source = "manual"
        elif env_of is not None or env_par is not None:
            self.rate_source = "env"
        else:
            self.rate_source = "placeholder"

    @property
    def is_placeholder(self) -> bool:
        """True when the rates are the invented defaults — never a quote."""
        return self.rate_source == "placeholder"

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "usd_ars_oficial": self.usd_ars_oficial,
            "usd_ars_parallel": self.usd_ars_parallel,
            "rate_source": self.rate_source,
            "rate_asof": self.rate_asof,
        }


@dataclass
class BlackLittermanConfig:
    """
    Black-Litterman + covariance-shrinkage parameters (Gran Salto — Fase 5).

    Model-depth upgrade over the score-proxy expected returns and the raw sample
    covariance. Opt-in and graceful: when data is thin or anything fails, the
    optimizer falls back to the existing deterministic path, so results stay valid.

    Fields:
      enabled            — use the Black-Litterman posterior as the optimizer's
                          expected returns (score proxy becomes the *views*).
      shrinkage_enabled  — use Ledoit-Wolf shrinkage for the covariance matrix.
      tau                — BL prior uncertainty scalar (typical 0.025-0.05).
      risk_aversion      — δ in the reverse-optimisation Π = δ·Σ·w_market.
      use_score_confidence — scale per-view uncertainty by the asset's score
                          (higher score → more confident view → pulls harder).
    """
    enabled: bool = True
    shrinkage_enabled: bool = True
    tau: float = 0.05
    risk_aversion: float = 2.5
    use_score_confidence: bool = True

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "shrinkage_enabled": self.shrinkage_enabled,
            "tau": self.tau,
            "risk_aversion": self.risk_aversion,
            "use_score_confidence": self.use_score_confidence,
        }


THRESHOLDS = FundamentalThresholds()
STRATEGY = StrategyConfig()
ALERTS = AlertConfig()
AI_CONFIG = AIConfig()
CONSISTENCY = ConsistencyThresholds()
PIOTROSKI = PiotroskiConfig()
BACKTEST = BacktestConfig()
MOAT = MoatConfig()
TAXES = TaxConfig()
CRYPTO_MOAT = CryptoMoatConfig()
OPTIMIZER = OptimizerConfig()
REPORT = ReportConfig()
MONTE_CARLO = MonteCarloConfig()
DATA_QUALITY = DataQualityConfig()
ASSET_CLASS = AssetClassConfig()
SCREENER = ScreenerConfig()
TAILWINDS = TailwindConfig()
DRAGS = EconomicDragConfig()
WITHDRAWAL = WithdrawalConfig()
HEALTH = PlanHealthConfig()
SENSITIVITY = SensitivityConfig()
GOAL_CARD = GoalCardConfig()
PERSONAL_BOOK = PersonalBookConfig()
TRACK_RECORD = TrackRecordConfig()
EVAL = EvalConfig()
COMMITTEE = CommitteeConfig()
MULTI_SOURCE = MultiSourceConfig()
MACRO_RAG = MacroRagConfig()
CHAT = ChatConfig()
AR_FX = ArFxConfig()
BLACK_LITTERMAN = BlackLittermanConfig()
