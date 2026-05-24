"""
Streamlit dashboard — main UI for the Retirement Advisor.

Pages:
  1. 🏠 Screener       — ranked opportunity table across the universe
  2. 🔍 Stock Analysis — deep-dive on a single ticker
  3. 💼 Portfolio      — current holdings + performance metrics
  4. 📐 Allocation     — asset allocation advisor
  5. ⚙️  Settings       — adjust universe and thresholds
"""

import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from loguru import logger

from pathlib import Path
from analysis.backtesting import BacktestEngine, BacktestResult
from analysis.strategy import full_analysis
from config import BACKTEST, DEFAULT_TICKERS, SECTOR_MAP, AIConfig

_ENV_PATH = Path(__file__).parent.parent / ".env"

def _load_env_vars() -> dict:
    """Read key=value pairs from .env file."""
    env = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

def _save_ai_config_to_env(provider: str, model: str, api_key: str, enabled: bool, use_in_screener: bool = False):
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

    lines = []
    for k, v in env.items():
        lines.append(f"{k}={v}")
    _ENV_PATH.write_text("\n".join(lines) + "\n")
from data.cache import cache
from data.fetcher import get_history, get_info
from portfolio.allocation import AllocationAdvisor
from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Page config                                                         #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="Retirement Advisor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------ #
#  Sidebar navigation                                                  #
# ------------------------------------------------------------------ #

st.sidebar.title("📈 Retirement Advisor")
st.sidebar.caption("Long-term investment decisions for retirement")

page = st.sidebar.radio(
    "Navigation",
    ["🏠 Screener", "🔍 Stock Analysis", "💼 Portfolio", "📐 Allocation", "📊 Backtesting", "⚙️ Settings"],
)

# ------------------------------------------------------------------ #
#  Shared state                                                        #
# ------------------------------------------------------------------ #

if "universe" not in st.session_state:
    st.session_state.universe = DEFAULT_TICKERS.copy()

if "portfolio" not in st.session_state:
    st.session_state.portfolio = Portfolio()

# Load AI config from .env on first run
if "ai_provider" not in st.session_state:
    _env = _load_env_vars()
    st.session_state.ai_provider = _env.get("AI_PROVIDER", "claude")
    st.session_state.ai_model = _env.get("AI_MODEL", "claude-sonnet-4-6")
    st.session_state.ai_api_key = _env.get("AI_API_KEY", "")
    st.session_state.ai_enabled = _env.get("AI_ENABLED", "").lower() in ("true", "1", "yes")
    st.session_state.ai_use_in_screener = _env.get("AI_USE_IN_SCREENER", "false").lower() in ("true", "1", "yes")

portfolio: Portfolio = st.session_state.portfolio

# ------------------------------------------------------------------ #
#  Helper                                                              #
# ------------------------------------------------------------------ #

ACTION_COLOR = {
    "STRONG BUY": "#00C851",
    "BUY": "#39b54a",
    "HOLD": "#ffbb33",
    "REDUCE": "#ff8800",
    "SELL": "#ff4444",
    "AVOID": "#cc0000",
}

def score_bar(score: float) -> str:
    filled = int(score / 10)
    return "█" * filled + "░" * (10 - filled) + f"  {score:.0f}/100"


def _get_ai_config(context: str = "detailed_analysis") -> AIConfig:
    enabled = st.session_state.get("ai_enabled", False)
    use_in_screener = st.session_state.get("ai_use_in_screener", False)
    # Disable AI for screener unless explicitly opted-in
    effective_enabled = enabled and (context != "screener" or use_in_screener)
    return AIConfig(
        provider=st.session_state.get("ai_provider", "claude"),
        model=st.session_state.get("ai_model", "claude-sonnet-4-6"),
        api_key=st.session_state.get("ai_api_key", ""),
        enabled=effective_enabled,
        use_in_screener=use_in_screener,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def cached_full_analysis(symbol: str, ai_provider: str = "", ai_model: str = "", ai_enabled: bool = False, ai_api_key: str = ""):
    ai_cfg = AIConfig(
        provider=ai_provider,
        model=ai_model,
        api_key=ai_api_key,
        enabled=ai_enabled,
    )
    fund, tech, decision = full_analysis(symbol, ai_config=ai_cfg)
    return fund, tech, decision


# ================================================================== #
#  PAGE 1: SCREENER                                                    #
# ================================================================== #

if page == "🏠 Screener":
    st.title("🏠 Opportunity Screener")
    st.caption("Ranked by fundamental quality score. Updated every 24h via cache.")

    tickers = st.session_state.universe
    max_tickers = st.sidebar.slider("Max tickers to screen", 5, len(tickers), len(tickers))
    selected = tickers[:max_tickers]

    if st.button("🔄 Refresh Analysis", type="primary"):
        st.cache_data.clear()

    rows = []
    progress = st.progress(0)
    status = st.empty()

    ai_cfg = _get_ai_config(context="screener")
    for i, sym in enumerate(selected):
        status.text(f"Analyzing {sym}... ({i+1}/{len(selected)})")
        progress.progress((i + 1) / len(selected))
        try:
            fund, tech, decision = cached_full_analysis(sym, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key)
            rows.append({
                "Ticker": sym,
                "Company": fund.company_name[:25],
                "Sector": fund.sector,
                "Signal": f"{decision.action_emoji} {decision.action}",
                "Adj. Score": fund.adjusted_score,
                "Base Score": fund.total_score,
                "Score Bar": score_bar(fund.adjusted_score),
                "Consistency": fund.consistency_score,
                "Piotroski": fund.piotroski_score,
                "Technical": tech.signal,
                "P/E": fund.pe_ratio,
                "ROE %": fund.roe,
                "Rev CAGR 5Y": fund.revenue_cagr_5y,
                "Div Yield %": fund.dividend_yield,
                "MoS %": fund.margin_of_safety_pct,
                "Price": fund.current_price,
            })
        except Exception as exc:
            logger.error(f"{sym}: {exc}")

    progress.empty()
    status.empty()

    if not rows:
        st.warning("No data returned. Check internet connection.")
        st.stop()

    df = pd.DataFrame(rows).sort_values("Adj. Score", ascending=False)

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    buy_count = df["Signal"].str.contains("BUY").sum()
    hold_count = df["Signal"].str.contains("HOLD").sum()
    sell_count = df["Signal"].str.contains("SELL|REDUCE|AVOID").sum()
    col1.metric("Strong/Buy signals", buy_count)
    col2.metric("Hold signals", hold_count)
    col3.metric("Sell/Reduce signals", sell_count)
    col4.metric("Stocks screened", len(df))

    # Table
    st.dataframe(
        df[[
            "Ticker", "Company", "Sector", "Signal", "Score Bar",
            "Consistency", "Piotroski",
            "Technical", "P/E", "ROE %", "Rev CAGR 5Y", "Div Yield %", "MoS %", "Price"
        ]].rename(columns={"Consistency": "Consist./15", "Piotroski": "Piotroski/9"}),
        use_container_width=True,
        hide_index=True,
    )

    # Score distribution chart
    fig = px.bar(
        df.sort_values("Adj. Score", ascending=True),
        x="Adj. Score",
        y="Ticker",
        orientation="h",
        color="Adj. Score",
        color_continuous_scale="RdYlGn",
        range_color=[0, 100],
        title="Adjusted Score Ranking (Base + Consistency + Piotroski)",
    )
    fig.add_vline(x=75, line_dash="dash", line_color="green", annotation_text="Strong Buy")
    fig.add_vline(x=60, line_dash="dash", line_color="orange", annotation_text="Buy")
    fig.update_layout(height=max(400, len(df) * 22), yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)


# ================================================================== #
#  PAGE 2: STOCK ANALYSIS                                              #
# ================================================================== #

elif page == "🔍 Stock Analysis":
    st.title("🔍 Stock Deep Dive")

    col1, col2 = st.columns([2, 1])
    with col1:
        symbol = st.text_input("Ticker symbol", value="AAPL").upper().strip()
    with col2:
        analyze_btn = st.button("Analyze", type="primary", use_container_width=True)

    if symbol:
        ai_cfg = _get_ai_config()
        with st.spinner(f"Analyzing {symbol}..."):
            fund, tech, decision = cached_full_analysis(symbol, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key)

        # Header
        st.markdown(f"## {decision.action_emoji} {fund.company_name} ({symbol})")
        caption = f"{fund.sector} · {fund.industry} · Market Cap: ${fund.market_cap/1e9:.1f}B"
        if decision.ai_reasoning:
            caption += f" · 🤖 {ai_cfg.model}"
        st.caption(caption)

        # Decision banner
        action_color = ACTION_COLOR.get(decision.action, "#888")
        st.markdown(
            f"""<div style="background:{action_color}22;border-left:4px solid {action_color};
            padding:12px;border-radius:4px;margin:8px 0">
            <b style="color:{action_color};font-size:1.2em">{decision.action_emoji} {decision.action}</b>
            &nbsp;|&nbsp; Confidence: {decision.confidence}
            &nbsp;|&nbsp; Fundamental: {decision.score_badge}
            </div>""",
            unsafe_allow_html=True,
        )

        # Score breakdown
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Profitability", f"{fund.profitability_score:.0f}/25")
        col2.metric("Fin. Health", f"{fund.health_score:.0f}/20")
        col3.metric("Valuation", f"{fund.valuation_score:.0f}/25")
        col4.metric("Growth", f"{fund.growth_score:.0f}/20")
        col5.metric("Dividend", f"{fund.dividend_score:.0f}/10")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Base Score", f"{fund.total_score:.1f}/100")
        col2.metric(
            "Consistency",
            f"{fund.consistency_score:.1f}/15",
            help="ROE stability + EPS growth CV + Net margin stability",
        )
        col3.metric(
            "Piotroski F-Score",
            f"{fund.piotroski_score}/9",
            help="Calidad contable YoY (≥7 = fuerte, ≤3 = débil)",
        )
        col4.metric("Score Ajustado", f"{fund.adjusted_score:.1f}/100")

        # Consistency sub-scores
        if getattr(fund, "consistency_detail", None):
            cd = fund.consistency_detail
            with st.expander(f"📊 Detalle Consistency ({cd.total:.1f}/15)", expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.metric("ROE Stability", f"{cd.roe_score:.1f}/5")
                c2.metric("EPS Stability", f"{cd.eps_score:.1f}/5")
                c3.metric("Margin Stability", f"{cd.margin_score:.1f}/5")
                if cd.notes:
                    for note in cd.notes:
                        st.caption(f"⚠️ {note}")

        # Piotroski F-score detail
        if getattr(fund, "piotroski_detail", None):
            pd_obj = fund.piotroski_detail
            _piotroski_labels = {
                "f1_roa_positive":          "F1 — ROA > 0 (actual)",
                "f2_ocf_positive":          "F2 — Operating Cash Flow > 0",
                "f3_roa_improving":         "F3 — ROA mejoró YoY",
                "f4_leverage_decreasing":   "F4 — Deuda/Activos ↓ YoY",
                "f5_liquidity_improving":   "F5 — Current Ratio ↑ YoY",
                "f6_no_dilution":           "F6 — Sin dilución accionaria (≤2%)",
                "f7_gross_margin_improving":"F7 — Margen bruto ↑ YoY",
                "f8_asset_turnover_improving":"F8 — Asset Turnover ↑ YoY",
                "f9_accruals_quality":      "F9 — OCF > Net Income (accruals)",
            }
            score_color = "#00C851" if pd_obj.score >= 7 else ("#ffbb33" if pd_obj.score >= 5 else "#ff4444")
            with st.expander(
                f"🏦 Detalle Piotroski F-Score ({pd_obj.score}/9)",
                expanded=False,
            ):
                for attr, label in _piotroski_labels.items():
                    passed = getattr(pd_obj, attr, False)
                    st.markdown(f"{'✅' if passed else '❌'} {label}")

        # Tabs
        tab_fund, tab_tech, tab_chart, tab_decision = st.tabs(
            ["📊 Fundamentals", "📈 Technical", "📉 Price Chart", "🎯 Decision"]
        )

        with tab_fund:
            cols = st.columns(3)
            metrics = [
                ("ROE", fund.roe, "%"),
                ("ROIC", fund.roic, "%"),
                ("Net Margin", fund.net_margin, "%"),
                ("Gross Margin", fund.gross_margin, "%"),
                ("Debt/Equity", fund.debt_equity, "x"),
                ("Current Ratio", fund.current_ratio, "x"),
                ("Interest Coverage", fund.interest_coverage, "x"),
                ("P/E Ratio", fund.pe_ratio, "x"),
                ("PEG Ratio", fund.peg_ratio, "x"),
                ("EV/EBITDA", fund.ev_ebitda, "x"),
                ("P/B Ratio", fund.pb_ratio, "x"),
                ("Revenue CAGR 5Y", fund.revenue_cagr_5y, "%"),
                ("EPS CAGR 5Y", fund.eps_cagr_5y, "%"),
                ("FCF Yield", fund.fcf_yield, "%"),
                ("Dividend Yield", fund.dividend_yield, "%"),
                ("Payout Ratio", fund.payout_ratio, "%"),
            ]
            for i, (label, value, unit) in enumerate(metrics):
                with cols[i % 3]:
                    if value is not None:
                        st.metric(label, f"{value:.2f}{unit}")
                    else:
                        st.metric(label, "N/A")

            if fund.graham_value:
                st.divider()
                col1, col2 = st.columns(2)
                col1.metric("Graham Intrinsic Value", f"${fund.graham_value:.2f}")
                if fund.margin_of_safety_pct is not None:
                    delta_color = "normal" if fund.margin_of_safety_pct > 0 else "inverse"
                    col2.metric(
                        "Margin of Safety",
                        f"{fund.margin_of_safety_pct:.1f}%",
                        delta=f"vs ${fund.current_price:.2f} current",
                        delta_color=delta_color,
                    )

        with tab_tech:
            col1, col2, col3 = st.columns(3)
            col1.metric("Signal", f"{tech.signal}")
            col2.metric("Signal Strength", f"{tech.signal_strength:+d}/100")
            col3.metric("ADX (Trend Power)", f"{tech.adx:.1f}" if tech.adx else "N/A")

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Above SMA200", "✅" if tech.above_sma200 else "❌")
            col2.metric("Above SMA100", "✅" if tech.above_sma100 else "❌")
            col3.metric("MACD Bullish", "✅" if tech.macd_bullish else "❌")
            col4.metric("RSI (weekly)", f"{tech.rsi_weekly:.1f}" if tech.rsi_weekly else "N/A")

            col1, col2 = st.columns(2)
            col1.metric("SMA200 Slope (26w)", f"{tech.sma200_slope_pct:+.1f}%")
            col2.metric("vs 52w High", f"{tech.price_vs_52w_high_pct:+.1f}%")

            if tech.notes:
                st.success("  ·  ".join(tech.notes))
            if tech.warnings:
                st.warning("  ·  ".join(tech.warnings))

        with tab_chart:
            hist = get_history(symbol, period="10y", interval="1wk")
            if not hist.empty:
                price = hist["close"]
                sma50 = price.rolling(50).mean()
                sma200 = price.rolling(200).mean()

                fig = go.Figure()
                fig.add_trace(go.Scatter(x=hist.index, y=price, name="Price", line=dict(color="#2196F3", width=2)))
                fig.add_trace(go.Scatter(x=hist.index, y=sma50, name="SMA 50", line=dict(color="#FF9800", width=1.5, dash="dot")))
                fig.add_trace(go.Scatter(x=hist.index, y=sma200, name="SMA 200", line=dict(color="#F44336", width=2)))
                fig.update_layout(
                    title=f"{symbol} — 10 Year Weekly Chart",
                    yaxis_title="Price (USD)",
                    xaxis_title="",
                    height=500,
                    legend=dict(orientation="h"),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Price history not available")

        with tab_decision:
            if decision.ai_reasoning:
                st.subheader(f"🤖 Análisis AI — {ai_cfg.model}")
                st.markdown(decision.ai_reasoning)
                st.divider()

            st.subheader("Investment Rationale")
            if decision.rationale:
                for r in decision.rationale:
                    st.success(f"✅ {r}")
            else:
                st.info("No specific positive factors flagged.")

            if decision.risks:
                st.subheader("Risks & Concerns")
                for risk in decision.risks:
                    st.warning(f"⚠️ {risk}")

            if decision.blocked:
                st.error(f"🚫 BLOCKED: {decision.block_reason}")

            # Add to watchlist / portfolio
            st.divider()
            st.subheader("Add to Portfolio")
            col1, col2, col3 = st.columns(3)
            with col1:
                shares = st.number_input("Shares", min_value=0.01, value=10.0, step=1.0)
            with col2:
                cost = st.number_input("Avg Cost (USD)", min_value=0.01, value=fund.current_price or 100.0)
            with col3:
                buy_date = st.date_input("Purchase Date")
            if st.button("Add Position", type="secondary"):
                portfolio.add_position(symbol, shares, cost, str(buy_date))
                st.success(f"Added {shares:.0f} × {symbol} @ ${cost:.2f}")
                st.session_state.portfolio = portfolio


# ================================================================== #
#  PAGE 3: PORTFOLIO                                                   #
# ================================================================== #

elif page == "💼 Portfolio":
    st.title("💼 My Portfolio")

    if not portfolio.positions:
        st.info("No positions yet. Analyze a stock and add it from the Stock Analysis page.")
        st.stop()

    values = portfolio.get_current_values()
    metrics = portfolio.compute_metrics()

    # Summary metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Value", f"${metrics.total_value:,.0f}")
    col2.metric("Total P&L", f"${metrics.total_pnl:,.0f}", f"{metrics.total_pnl_pct:.1f}%")
    col3.metric("Ann. Return", f"{metrics.annualized_return_pct:.1f}%")
    col4.metric("Sharpe Ratio", f"{metrics.sharpe_ratio:.2f}")
    col5.metric("Max Drawdown", f"{metrics.max_drawdown_pct:.1f}%")

    col1, col2, col3 = st.columns(3)
    col1.metric("Sortino Ratio", f"{metrics.sortino_ratio:.2f}")
    col2.metric("Portfolio Beta", f"{metrics.beta:.2f}")
    col3.metric("Positions", metrics.num_positions)

    st.divider()

    # Holdings table
    st.subheader("Holdings")
    rows = list(values.values())
    df = pd.DataFrame(rows)
    df["pnl_pct"] = df["pnl_pct"].round(1)
    df["pnl"] = df["pnl"].round(0)
    df["market_value"] = df["market_value"].round(0)
    df["weight_pct"] = (df["market_value"] / metrics.total_value * 100).round(1)

    st.dataframe(
        df[["symbol", "sector", "shares", "avg_cost", "current_price",
            "cost_basis", "market_value", "pnl", "pnl_pct", "weight_pct"]].rename(columns={
            "symbol": "Ticker", "sector": "Sector", "shares": "Shares",
            "avg_cost": "Avg Cost", "current_price": "Price",
            "cost_basis": "Cost Basis", "market_value": "Mkt Value",
            "pnl": "P&L ($)", "pnl_pct": "P&L %", "weight_pct": "Weight %",
        }),
        use_container_width=True,
        hide_index=True,
    )

    # Charts
    col1, col2 = st.columns(2)
    with col1:
        sector_weights = portfolio.get_sector_weights()
        fig = px.pie(
            names=list(sector_weights.keys()),
            values=list(sector_weights.values()),
            title="Sector Allocation",
            hole=0.4,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        pos_weights = portfolio.get_position_weights()
        fig = px.bar(
            x=list(pos_weights.keys()),
            y=list(pos_weights.values()),
            title="Position Weights (%)",
            color=list(pos_weights.values()),
            color_continuous_scale="Blues",
        )
        fig.add_hline(y=8, line_dash="dash", line_color="red", annotation_text="Max 8%")
        fig.update_layout(yaxis_title="%", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    # Remove position
    st.divider()
    st.subheader("Remove / Trim Position")
    col1, col2 = st.columns(2)
    with col1:
        sym_to_remove = st.selectbox("Ticker", list(portfolio.positions.keys()))
    with col2:
        shares_to_remove = st.number_input("Shares (blank = close all)", min_value=0.0, value=0.0)
    if st.button("Remove", type="secondary"):
        portfolio.remove_position(sym_to_remove, shares_to_remove if shares_to_remove > 0 else None)
        st.session_state.portfolio = portfolio
        st.rerun()


# ================================================================== #
#  PAGE 4: ALLOCATION                                                  #
# ================================================================== #

elif page == "📐 Allocation":
    st.title("📐 Asset Allocation Advisor")

    col1, col2 = st.columns(2)
    with col1:
        age = st.slider("Your current age", 20, 80, 35)
    with col2:
        retirement_age = st.slider("Target retirement age", age + 1, 80, max(age + 5, 65))

    sector_weights = portfolio.get_sector_weights() if portfolio.positions else {}
    position_weights = portfolio.get_position_weights() if portfolio.positions else {}

    advisor = AllocationAdvisor()
    advice = advisor.advise(age, retirement_age, sector_weights, position_weights)

    # Allocation pie
    fig = px.pie(
        names=["US Equities", "International", "Real Estate", "Bonds", "Cash"],
        values=[
            advice.us_large_cap_pct,
            advice.international_pct,
            advice.real_estate_pct,
            advice.bonds_pct,
            advice.cash_pct,
        ],
        title=f"Recommended Allocation — Age {age}",
        color_discrete_sequence=px.colors.qualitative.Set2,
        hole=0.3,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Detail
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Equities", f"{advice.equity_pct:.0f}%")
    col2.metric("Bonds", f"{advice.bonds_pct:.0f}%")
    col3.metric("Cash Buffer", f"{advice.cash_pct:.0f}%")

    st.info(f"💡 {advice.inflation_note}")

    if advice.concentration_warnings:
        st.subheader("⚠️ Concentration Issues")
        for w in advice.concentration_warnings:
            st.warning(w)

    if advice.rebalancing_actions:
        st.subheader("🔄 Rebalancing Actions")
        for a in advice.rebalancing_actions:
            st.info(f"→ {a}")


# ================================================================== #
#  PAGE 5: BACKTESTING                                                 #
# ================================================================== #

elif page == "📊 Backtesting":
    st.title("📊 Backtesting Engine")
    st.caption(
        "Simula una cartera equal-weight de los top-N tickers por score ajustado "
        "y compara su performance histórica vs el benchmark."
    )
    st.warning(
        "⚠️ **Limitación conocida:** Los scores se calculan con fundamentals actuales "
        "(yfinance no provee snapshots históricos). Las métricas de precio (CAGR, Sharpe, "
        "Drawdown) son limpias. Los resultados miden si las empresas que hoy puntúan alto "
        "también tuvieron buenos retornos históricos.",
        icon="⚠️",
    )

    # ---- Configuración ----
    with st.expander("⚙️ Configuración del backtest", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            period_years = st.selectbox(
                "Período", [1, 3, 5, 10],
                index=2,
                format_func=lambda y: f"{y} año{'s' if y > 1 else ''}",
            )
        with col2:
            top_n = st.slider("Top-N tickers", min_value=3, max_value=20, value=BACKTEST.default_top_n)
        with col3:
            benchmark = st.selectbox("Benchmark", ["SPY", "QQQ", "VTI", "BND"], index=0)

        col1, col2 = st.columns(2)
        with col1:
            _FREQ_OPTIONS = {
                "Anual": "annual",
                "Trimestral": "quarterly",
                "Mensual": "monthly",
                "Buy & Hold (sin rebalanceo)": "buy_and_hold",
            }
            freq_label = st.selectbox(
                "Frecuencia de rebalanceo",
                list(_FREQ_OPTIONS.keys()),
                index=0,
                help="Con qué frecuencia se redistribuye el capital en partes iguales entre los top-N tickers.",
            )
            rebalance_freq = _FREQ_OPTIONS[freq_label]
        with col2:
            universe_choice = st.selectbox(
                "Universo",
                ["Universo completo", "Solo US Large Cap", "Solo Argentina ADRs"],
            )

    _US_LARGE_CAP = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B",
                     "JPM", "V", "MA", "JNJ", "UNH", "PG", "KO", "HD", "XOM"]
    _ARGENTINA_ADR = ["YPF", "PAM", "CEPU", "LOMA", "MELI", "GLOB", "TEO", "EDN"]

    if universe_choice == "Solo US Large Cap":
        backtest_universe = _US_LARGE_CAP
    elif universe_choice == "Solo Argentina ADRs":
        backtest_universe = _ARGENTINA_ADR
    else:
        backtest_universe = [t for t in st.session_state.universe if t not in (benchmark,)]

    st.caption(f"Universo seleccionado: {len(backtest_universe)} tickers — {', '.join(backtest_universe[:10])}{'...' if len(backtest_universe) > 10 else ''}")

    col_run, col_load = st.columns([2, 1])
    run_btn = col_run.button("▶ Correr Backtest", type="primary", use_container_width=True)
    saved_files = BacktestEngine.list_saved()
    load_choice = col_load.selectbox(
        "Cargar resultado guardado",
        ["— nuevo —"] + [f.name for f in saved_files[:BACKTEST.results_max_saved]],
        label_visibility="collapsed",
    )

    # ---- Load or run ----
    bt_result: BacktestResult | None = None

    if load_choice != "— nuevo —":
        target = next((f for f in saved_files if f.name == load_choice), None)
        if target:
            try:
                bt_result = BacktestEngine.load(target)
                st.info(f"Resultado cargado: **{load_choice}**")
            except Exception as e:
                st.error(f"Error al cargar: {e}")

    if run_btn:
        with st.spinner(f"Obteniendo scores para {len(backtest_universe)} tickers..."):
            ai_cfg = _get_ai_config(context="screener")
            fund_results = []
            prog = st.progress(0)
            for i, sym in enumerate(backtest_universe):
                try:
                    fund, _tech, _dec = cached_full_analysis(
                        sym, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
                    )
                    fund_results.append(fund)
                except Exception as exc:
                    logger.warning(f"Backtest: skipping {sym} — {exc}")
                prog.progress((i + 1) / len(backtest_universe))
            prog.empty()

        if not fund_results:
            st.error("No se pudieron obtener datos fundamentales.")
            st.stop()

        with st.spinner(f"Calculando backtest {period_years}Y vs {benchmark} ({freq_label})..."):
            engine = BacktestEngine()
            bt_result = engine.run(
                fund_results,
                period_years=period_years,
                top_n=top_n,
                benchmark=benchmark,
                rebalance_freq=rebalance_freq,
            )
            saved_path = engine.save(bt_result)
            st.success(f"Backtest completado y guardado en `{saved_path.name}`")

    # ---- Display results ----
    if bt_result is None:
        st.info("Configurá los parámetros y presioná **▶ Correr Backtest**, o cargá un resultado anterior.")
        st.stop()

    # Summary metrics
    st.divider()
    st.subheader("📈 Performance Summary")

    alpha_color = "normal" if bt_result.alpha_pct >= 0 else "inverse"
    rebal_label = bt_result.rebalance_freq.replace("_", " ").title()
    st.caption(f"Rebalanceo: **{rebal_label}** · Top-{bt_result.top_n} · {bt_result.period_years}Y · vs {bt_result.benchmark}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Portfolio CAGR",
        f"{bt_result.portfolio_cagr_pct:+.1f}%",
        f"α {bt_result.alpha_pct:+.1f}% vs {bt_result.benchmark}",
        delta_color=alpha_color,
    )
    col2.metric("Benchmark CAGR", f"{bt_result.benchmark_cagr_pct:+.1f}%")
    col3.metric("Total Return Portfolio", f"{bt_result.portfolio_total_return_pct:+.1f}%")
    col4.metric("Total Return Benchmark", f"{bt_result.benchmark_total_return_pct:+.1f}%")

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Sharpe Ratio", f"{bt_result.portfolio_sharpe:.2f}", help="(CAGR − Rf) / Vol total")
    col2.metric(
        "Sortino Ratio",
        f"{getattr(bt_result, 'portfolio_sortino', 0):.2f}",
        help="(CAGR − Rf) / Vol bajista — penaliza solo pérdidas",
    )
    col3.metric("Max Drawdown", f"{bt_result.portfolio_max_drawdown_pct:.1f}%")
    col4.metric("Win Rate vs Bench", f"{bt_result.portfolio_win_rate_pct:.0f}%")
    col5.metric("Calmar Ratio", f"{bt_result.calmar_ratio:.2f}", help="CAGR / |Max Drawdown|")

    # ---- Charts ----
    tab_curve, tab_drawdown, tab_scatter, tab_tickers = st.tabs(
        ["📈 Equity Curve", "📉 Drawdown", "🔵 Score vs Retorno", "📋 Por Ticker"]
    )

    with tab_curve:
        if bt_result.portfolio_curve and bt_result.benchmark_curve:
            port_s = pd.Series(bt_result.portfolio_curve)
            bench_s = pd.Series(bt_result.benchmark_curve)
            port_s.index = pd.to_datetime(port_s.index)
            bench_s.index = pd.to_datetime(bench_s.index)

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=port_s.index, y=port_s.values,
                name=f"Top-{bt_result.top_n} Portfolio",
                line=dict(color="#2196F3", width=2.5),
            ))
            fig.add_trace(go.Scatter(
                x=bench_s.index, y=bench_s.values,
                name=bt_result.benchmark,
                line=dict(color="#FF9800", width=2, dash="dot"),
            ))
            fig.update_layout(
                title=f"Equity Curve — {bt_result.period_years}Y (base = 100)",
                yaxis_title="Valor Normalizado",
                height=420,
                legend=dict(orientation="h"),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin datos de curva de equity.")

    with tab_drawdown:
        if bt_result.drawdown_curve:
            dd_s = pd.Series(bt_result.drawdown_curve)
            dd_s.index = pd.to_datetime(dd_s.index)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dd_s.index, y=dd_s.values,
                name="Drawdown %",
                fill="tozeroy",
                line=dict(color="#F44336", width=1.5),
                fillcolor="rgba(244,67,54,0.15)",
            ))
            fig.update_layout(
                title="Portfolio Drawdown",
                yaxis_title="Drawdown %",
                height=300,
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)

    with tab_scatter:
        if bt_result.score_vs_return:
            scatter_df = pd.DataFrame(bt_result.score_vs_return)
            fig = px.scatter(
                scatter_df,
                x="score",
                y="cagr_pct",
                text="symbol",
                color="cagr_pct",
                color_continuous_scale="RdYlGn",
                size=[8] * len(scatter_df),
                title="Score Ajustado vs CAGR Histórico",
                labels={"score": "Score Ajustado", "cagr_pct": "CAGR % (histórico)"},
            )
            fig.update_traces(textposition="top center", marker=dict(size=10))
            # Correlation annotation
            if len(scatter_df) > 3:
                corr = scatter_df["score"].corr(scatter_df["cagr_pct"])
                fig.add_annotation(
                    xref="paper", yref="paper", x=0.02, y=0.97,
                    text=f"Correlación score↔CAGR: r = {corr:.2f}",
                    showarrow=False,
                    bgcolor="rgba(255,255,255,0.8)",
                    bordercolor="#888",
                )
            fig.add_hline(
                y=bt_result.benchmark_cagr_pct,
                line_dash="dash", line_color="orange",
                annotation_text=f"{bt_result.benchmark} CAGR",
            )
            fig.update_layout(height=480, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Cada punto es un ticker del universo. La línea naranja es el CAGR del benchmark.")

    with tab_tickers:
        if bt_result.ticker_results:
            rows = [
                {
                    "Ticker": t.symbol,
                    "Score": t.score,
                    "CAGR %": t.cagr_pct,
                    "Alpha %": t.alpha_pct,
                    "Sharpe": t.sharpe,
                    "Sortino": getattr(t, "sortino", 0),
                    "Max DD %": t.max_drawdown_pct,
                    "Volatilidad %": t.volatility_pct,
                    "Win Rate %": t.win_rate_pct,
                    "Retorno Total %": t.total_return_pct,
                    "En Portfolio": "✅" if t.symbol in [r["symbol"] for r in bt_result.score_vs_return[:bt_result.top_n]] else "",
                }
                for t in sorted(bt_result.ticker_results, key=lambda x: x.score, reverse=True)
            ]
            tdf = pd.DataFrame(rows)
            st.dataframe(
                tdf.style.background_gradient(subset=["CAGR %", "Alpha %"], cmap="RdYlGn"),
                use_container_width=True,
                hide_index=True,
            )

            # Download
            csv = tdf.to_csv(index=False)
            st.download_button(
                "⬇️ Descargar CSV",
                data=csv,
                file_name=f"backtest_{bt_result.period_years}y_{bt_result.run_date[:10]}.csv",
                mime="text/csv",
            )

    # Notes
    if bt_result.notes:
        with st.expander("📝 Notas del backtest"):
            for note in bt_result.notes:
                st.caption(note)


# ================================================================== #
#  PAGE 6: SETTINGS                                                    #
# ================================================================== #

elif page == "⚙️ Settings":
    st.title("⚙️ Settings")  # noqa: RUF001

    st.subheader("Stock Universe")
    universe_text = st.text_area(
        "Tickers (one per line or comma-separated)",
        value="\n".join(st.session_state.universe),
        height=200,
    )
    if st.button("Save Universe"):
        raw = universe_text.replace(",", "\n").split()
        st.session_state.universe = [t.upper().strip() for t in raw if t.strip()]
        st.success(f"Universe updated: {len(st.session_state.universe)} tickers")

    st.divider()
    st.subheader("🤖 AI Analysis")
    st.caption("Activá un modelo de AI para reemplazar el scoring rule-based con análisis cualitativo.")

    _MODEL_OPTIONS = {
        "Claude (Anthropic)": ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"],
        "GPT-4o (OpenAI)": ["gpt-4o", "gpt-4o-mini"],
        "xAI / Grok (via Hermes OAuth)": ["grok-4.3", "grok-4.20-0309-non-reasoning", "grok-4.20-0309-reasoning", "grok-build-0.1"],
        "Hermes / Nous Research": [
            "nousresearch/hermes-4-70b",
            "nousresearch/hermes-4-405b",
            "openrouter/owl-alpha",
        ],
    }
    _PROVIDER_KEY_TO_LABEL = {
        "claude": "Claude (Anthropic)",
        "openai": "GPT-4o (OpenAI)",
        "xai": "xAI / Grok (via Hermes OAuth)",
        "nous": "Hermes / Nous Research",
    }
    current_provider = st.session_state.get("ai_provider", "claude")
    default_provider_label = _PROVIDER_KEY_TO_LABEL.get(current_provider, "Claude (Anthropic)")
    provider_label = st.selectbox("Proveedor", list(_MODEL_OPTIONS.keys()),
                                  index=list(_MODEL_OPTIONS.keys()).index(default_provider_label))
    if "Claude" in provider_label:
        provider_key = "claude"
    elif "xAI" in provider_label or "Grok" in provider_label:
        provider_key = "xai"
    elif "Nous" in provider_label or "Hermes" in provider_label:
        provider_key = "nous"
    else:
        provider_key = "openai"

    model_list = _MODEL_OPTIONS[provider_label]
    current_model = st.session_state.get("ai_model", model_list[0])
    model_index = model_list.index(current_model) if current_model in model_list else 0
    ai_model_sel = st.selectbox("Modelo", model_list, index=model_index)

    if provider_key in ("nous", "xai"):
        st.info("🔐 Usa tu sesión local de Hermes OAuth. La API key es opcional.")
        st.session_state.ai_enabled = True
    ai_key_input = st.text_input(
        "API Key" + (" (opcional para Hermes)" if provider_key == "nous" else ""),
        type="password",
        value=st.session_state.get("ai_api_key", ""),
        placeholder="sk-ant-... / sk-... / dejar vacío si usás hermes login",
    )
    use_in_screener = st.toggle(
        "Usar AI también en el Screener",
        value=st.session_state.get("ai_use_in_screener", False),
        help="Desactivado por defecto. El Screener usa scoring rule-based (rápido y sin costo).",
    )
    if use_in_screener:
        n = len(st.session_state.get("universe", []))
        st.warning(
            f"⚠️ Activar AI en el Screener hará **{n} llamadas al API** por cada refresh "
            f"(~{n * 2}–{n * 5} segundos y costo real de tokens). "
            "Recomendado solo para universos pequeños (<10 tickers)."
        )
    ai_enabled_now = st.session_state.get("ai_enabled", False)
    st.caption(f"Estado actual: {'🟢 AI activo' if ai_enabled_now else '⚪ Usando scoring clásico'} | Screener: {'🤖 AI' if use_in_screener else '⚡ Rule-based'}")

    if st.button("Guardar configuración AI", type="primary"):
        st.session_state.ai_provider = provider_key
        st.session_state.ai_model = ai_model_sel
        st.session_state.ai_api_key = ai_key_input
        st.session_state.ai_use_in_screener = use_in_screener
        # Nous activates via local hermes session even without explicit API key
        ai_on = bool(ai_key_input.strip()) or provider_key in ("nous", "xai")
        prev_provider = st.session_state.get("ai_provider", "")
        prev_model = st.session_state.get("ai_model", "")
        st.session_state.ai_enabled = ai_on
        _save_ai_config_to_env(provider_key, ai_model_sel, ai_key_input, ai_on, use_in_screener)
        # Only clear Streamlit cache if provider/model changed — avoids slow screener reload
        if provider_key != prev_provider or ai_model_sel != prev_model:
            st.cache_data.clear()
        if provider_key == "xai":
            st.success(f"✅ AI activado — {ai_model_sel} vía xAI OAuth (Hermes).")
        elif provider_key == "nous":
            st.success(f"✅ AI activado — {ai_model_sel} vía Hermes (sesión local).")
        elif ai_key_input.strip():
            st.success(f"✅ AI activado — {ai_model_sel}.")
        else:
            st.info("API Key vacía — se usará el scoring clásico.")

    st.divider()
    st.subheader("Cache")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Clear All Cache", type="secondary"):
            cache.clear_all()
            st.cache_data.clear()
            st.success("Cache cleared — next analysis will re-fetch all data")
    with col2:
        st.caption("Cache stores fetched data for 24h to avoid API rate limits.")

    st.divider()
    st.subheader("About")
    st.markdown("""
    **Retirement Advisor** — v1.0

    A long-term investment analysis tool combining:
    - Fundamental quality scoring (100-point model)
    - Technical trend confirmation (long-term, weekly bars)
    - Benjamin Graham margin-of-safety valuation
    - Portfolio risk management for retirement

    > ⚠️ This tool is for educational purposes. Not financial advice.
    > Always consult a licensed financial advisor before making investment decisions.
    """)
