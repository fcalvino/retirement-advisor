"""Central configuration for the Retirement Advisor system."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DB_DIR = BASE_DIR / "data" / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "retirement_advisor.db"


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

    pb_excellent: float = 1.5
    pb_good: float = 3.0
    pb_acceptable: float = 5.0

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
    max_payout_ratio: float = 75.0          # % — sustainable payout


@dataclass
class StrategyConfig:
    """Decision engine thresholds."""

    strong_buy_score: float = 75.0
    buy_score: float = 60.0
    hold_score: float = 45.0
    # Below hold_score → SELL signal

    # Technical confirmation required for BUY
    require_technical_uptrend: bool = True

    # Margin of Safety: only buy when price < intrinsic value estimate
    require_margin_of_safety: bool = True
    min_margin_of_safety_pct: float = 10.0  # %

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

    telegram_enabled: bool = bool(os.getenv("TELEGRAM_TOKEN"))
    telegram_token: str = os.getenv("TELEGRAM_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")


CACHE_TTL_HOURS: int = int(os.getenv("CACHE_TTL_HOURS", "24"))

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
    "ETF": ["SPY", "QQQ", "VTI", "BND"],
}

# Asset allocation by age (bonds % = age rule + buffer for conservative)
def recommended_bond_pct(age: int) -> float:
    """Conservative: bond % = age. Aggressive: bond % = age - 10."""
    return min(float(age), 80.0)


@dataclass
class AIConfig:
    provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "claude"))
    model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "claude-sonnet-4-6"))
    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("OPENAI_API_KEY", ""))
    enabled: bool = field(default_factory=lambda: os.getenv("AI_ENABLED", "").lower() in ("true", "1", "yes"))
    use_in_screener: bool = field(default_factory=lambda: os.getenv("AI_USE_IN_SCREENER", "false").lower() in ("true", "1", "yes"))


@dataclass
class ConsistencyThresholds:
    roe_std_max_excellent: float = 5.0
    roe_std_max_acceptable: float = 12.0
    margin_volatility_max: float = 6.0


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
    """
    wide_threshold: float = 14.0
    narrow_threshold: float = 8.0
    minimal_threshold: float = 4.0
    max_bonus: float = 10.0
    ai_cache_ttl_hours: int = 168


THRESHOLDS = FundamentalThresholds()
STRATEGY = StrategyConfig()
ALERTS = AlertConfig()
AI_CONFIG = AIConfig()
CONSISTENCY = ConsistencyThresholds()
PIOTROSKI = PiotroskiConfig()
BACKTEST = BacktestConfig()
MOAT = MoatConfig()
