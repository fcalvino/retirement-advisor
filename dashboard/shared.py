"""
Shared helpers, constants and cached functions used by every dashboard page.

Import pattern in each page:
    from dashboard.shared import (
        cached_full_analysis, _analyse_universe_parallel,
        _fetch_universe_parallel, _get_ai_config,
        score_bar, _MOAT_EMOJI, ACTION_COLOR, ...
    )
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Allow imports from project root when a page is run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from loguru import logger

from analysis.strategy import full_analysis
from config import DEFAULT_TICKERS, AIConfig

# ------------------------------------------------------------------ #
#  .env helpers                                                        #
# ------------------------------------------------------------------ #

_ENV_PATH = Path(__file__).parent.parent / ".env"


def _load_env_vars() -> dict:
    """Read key=value pairs from .env file."""
    env: dict[str, str] = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _save_ai_config_to_env(
    provider: str,
    model: str,
    api_key: str,
    enabled: bool,
    use_in_screener: bool = False,
) -> None:
    """Persist AI settings into .env without touching other keys."""
    env = _load_env_vars()
    env["AI_PROVIDER"] = provider
    env["AI_MODEL"] = model
    env["AI_ENABLED"] = "true" if enabled else "false"
    env["AI_USE_IN_SCREENER"] = "true" if use_in_screener else "false"
    if api_key:
        env["AI_API_KEY"] = api_key
    elif "AI_API_KEY" in env:
        del env["AI_API_KEY"]
    _ENV_PATH.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")


# ------------------------------------------------------------------ #
#  Visual constants                                                    #
# ------------------------------------------------------------------ #

ACTION_COLOR: dict[str, str] = {
    "STRONG BUY": "#00C851",
    "BUY":        "#39b54a",
    "HOLD":       "#ffbb33",
    "REDUCE":     "#ff8800",
    "SELL":       "#ff4444",
    "AVOID":      "#cc0000",
}

_MOAT_COLOR: dict[str, str] = {
    "Wide":    "#00C851",
    "Narrow":  "#39b54a",
    "Minimal": "#ffbb33",
    "None":    "#888888",
}

_MOAT_EMOJI: dict[str, str] = {
    "Wide":    "🏰",
    "Narrow":  "🟢",
    "Minimal": "🟡",
    "None":    "⚪",
}

_MOAT_DESCRIPTION: dict[str, str] = {
    "Wide":    "Ventaja duradera 20+ años — protección estructural fuerte (ej: MSFT, AAPL, V)",
    "Narrow":  "Ventaja sólida ~10 años — más vulnerable a disrupción (ej: MELI, HD)",
    "Minimal": "Protección limitada o erosionándose — monitorear cada año",
    "None":    "Sin ventaja competitiva identificable — sensible a precios y competencia",
}

# ------------------------------------------------------------------ #
#  Formatting helpers                                                  #
# ------------------------------------------------------------------ #

def score_bar(score: float) -> str:
    filled = int(score / 10)
    return "█" * filled + "░" * (10 - filled) + f"  {score:.0f}/100"


def _moat_badge_html(classification: str, score: float, bonus: float) -> str:
    """HTML badge colored by moat classification for st.markdown()."""
    color = _MOAT_COLOR.get(classification, "#888")
    emoji = _MOAT_EMOJI.get(classification, "⚪")
    return (
        f'<span style="background:{color}22;border:1px solid {color};color:{color};'
        f'padding:3px 12px;border-radius:14px;font-weight:700;font-size:0.9em;">'
        f'{emoji} {classification} Moat &nbsp;·&nbsp; {score:.1f}/20 &nbsp;·&nbsp; +{bonus:.1f} pts</span>'
    )


def _dim_bar_html(score: float, max_score: float = 2.0) -> str:
    """Inline HTML progress bar for a moat dimension (0–2 scale)."""
    pct = score / max_score * 100
    if pct >= 75:
        color = "#00C851"
    elif pct >= 40:
        color = "#ffbb33"
    elif pct > 0:
        color = "#ff8800"
    else:
        color = "#dddddd"
    return (
        f'<div style="background:#e8e8e8;border-radius:4px;height:7px;margin-top:2px;">'
        f'<div style="width:{pct:.0f}%;background:{color};height:7px;border-radius:4px;"></div>'
        f'</div>'
    )


# ------------------------------------------------------------------ #
#  AI config helper                                                    #
# ------------------------------------------------------------------ #

def _get_ai_config(context: str = "detailed_analysis") -> AIConfig:
    enabled = st.session_state.get("ai_enabled", False)
    use_in_screener = st.session_state.get("ai_use_in_screener", False)
    effective_enabled = enabled and (context != "screener" or use_in_screener)
    return AIConfig(
        provider=st.session_state.get("ai_provider", "claude"),
        model=st.session_state.get("ai_model", "claude-sonnet-4-6"),
        api_key=st.session_state.get("ai_api_key", ""),
        enabled=effective_enabled,
        use_in_screener=use_in_screener,
    )


# ------------------------------------------------------------------ #
#  Cached analysis                                                     #
# ------------------------------------------------------------------ #

@st.cache_data(ttl=3600, show_spinner=False)
def cached_full_analysis(
    symbol: str,
    ai_provider: str = "",
    ai_model: str = "",
    ai_enabled: bool = False,
    ai_api_key: str = "",
):
    ai_cfg = AIConfig(
        provider=ai_provider,
        model=ai_model,
        api_key=ai_api_key,
        enabled=ai_enabled,
    )
    fund, tech, decision = full_analysis(symbol, ai_config=ai_cfg)
    return fund, tech, decision


@st.cache_data(ttl=1800, show_spinner=False)
def cached_monte_carlo(
    symbols: tuple[str, ...],
    weights_tuple: tuple[float, ...] | None,
    horizon_years: int,
    n_sims: int,
    initial_value: float,
    annual_withdrawal: float,
    target_value: float,
    seed: int = 42,
):
    """Cache Monte Carlo runs for 30 min — same params = instant re-render."""
    import numpy as np

    from portfolio.monte_carlo import MonteCarloSimulator

    w_np = np.array(weights_tuple) if weights_tuple else None
    sim  = MonteCarloSimulator(list(symbols), w_np, seed=seed)
    return sim.run(
        horizon_years=horizon_years,
        n_sims=n_sims,
        initial_value=initial_value,
        annual_withdrawal=annual_withdrawal,
        target_value=target_value,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_stress_test(
    sector_weights: dict[str, float],
    initial_value: float,
):
    """Cache stress test results per sector allocation — recomputes only when weights change."""
    from portfolio.stress_test import StressTester

    tester = StressTester()
    return tester.run(sector_weights, initial_value=initial_value)


def _analyse_universe_parallel(
    symbols: list[str],
    ai_cfg: AIConfig,
    progress_bar,
    status_text,
) -> list[dict]:
    """
    Run cached_full_analysis for each symbol in a thread pool.
    Workers capped at min(16, cpu_count*2) to avoid hammering yfinance.
    A per-ticker exception never aborts the whole run.
    """
    max_workers = min(16, (os.cpu_count() or 4) * 2)
    total = len(symbols)
    completed = 0
    rows: list[dict] = []

    def _analyse_one(sym: str) -> dict | None:
        try:
            fund, tech, decision = cached_full_analysis(
                sym, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
            )
            return {
                "Ticker": sym,
                "Company": fund.company_name[:25],
                "Sector": fund.sector,
                "Signal": f"{decision.action_emoji} {decision.action}",
                "Adj. Score": fund.adjusted_score,
                "Base Score": fund.total_score,
                "Score Bar": score_bar(fund.adjusted_score),
                "Consistency": fund.consistency_score,
                "Piotroski": fund.piotroski_score,
                "Moat Score": getattr(fund, "moat_score", 0.0),
                "Moat": (
                    f"{_MOAT_EMOJI.get(getattr(fund, 'moat_classification', ''), '⚪')} "
                    f"{getattr(fund, 'moat_classification', '—')}"
                ),
                "Technical": tech.signal,
                "P/E": fund.pe_ratio,
                "ROE %": fund.roe,
                "Rev CAGR 5Y": fund.revenue_cagr_5y,
                "Div Yield %": fund.dividend_yield,
                "MoS %": fund.margin_of_safety_pct,
                "Price": fund.current_price,
            }
        except Exception as exc:
            logger.error(f"Screener: {sym} failed — {exc}")
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_analyse_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            completed += 1
            sym = futures[future]
            status_text.text(f"Analyzing… {completed}/{total} done (last: {sym})")
            progress_bar.progress(completed / total)
            result = future.result()
            if result is not None:
                rows.append(result)

    return rows


def _fetch_universe_parallel(
    symbols: list[str],
    ai_cfg: AIConfig,
    progress_bar,
    status_text,
    label: str = "Analizando",
) -> list[tuple]:
    """
    Generic parallel fetcher — returns (symbol, fund, tech, decision) tuples.
    Callers build their own output dicts from the raw analysis results.
    Workers capped at min(16, cpu_count*2). Per-ticker exceptions are logged
    and that ticker is silently dropped so the rest of the run continues.
    """
    max_workers = min(16, (os.cpu_count() or 4) * 2)
    total     = len(symbols)
    completed = 0
    results: list[tuple] = []

    def _fetch_one(sym: str) -> tuple | None:
        try:
            fund, tech, decision = cached_full_analysis(
                sym, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
            )
            return (sym, fund, tech, decision)
        except Exception as exc:
            logger.error(f"{label}: {sym} failed — {exc}")
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            completed += 1
            sym = futures[future]
            status_text.text(f"{label}… {completed}/{total} (último: {sym})")
            progress_bar.progress(completed / total)
            result = future.result()
            if result is not None:
                results.append(result)

    return results
