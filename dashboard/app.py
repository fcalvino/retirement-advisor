"""
Streamlit dashboard — main UI for the Retirement Advisor.

Pages:
  1. 🏠 Screener       — ranked opportunity table across the universe
  2. 🔍 Stock Analysis — deep-dive on a single ticker
  3. 💼 Portfolio      — current holdings + performance metrics
  4. 📐 Allocation     — asset allocation advisor
  5. 📈 Optimizer      — Mean-Variance portfolio optimization with 3 risk profiles
  6. 📊 Backtesting    — historical strategy simulation
  7. ⚙️  Settings       — adjust universe and thresholds
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
from config import BACKTEST, DEFAULT_TICKERS, MOAT, SECTOR_MAP, AIConfig

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
    ["🏠 Screener", "🔍 Stock Analysis", "💼 Portfolio", "📐 Allocation", "📈 Optimizer", "📊 Backtesting", "⚙️ Settings"],
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

_MOAT_COLOR = {
    "Wide":    "#00C851",
    "Narrow":  "#39b54a",
    "Minimal": "#ffbb33",
    "None":    "#888888",
}

_MOAT_EMOJI = {
    "Wide":    "🏰",
    "Narrow":  "🟢",
    "Minimal": "🟡",
    "None":    "⚪",
}

_MOAT_DESCRIPTION = {
    "Wide":    "Ventaja duradera 20+ años — protección estructural fuerte (ej: MSFT, AAPL, V)",
    "Narrow":  "Ventaja sólida ~10 años — más vulnerable a disrupción (ej: MELI, HD)",
    "Minimal": "Protección limitada o erosionándose — monitorear cada año",
    "None":    "Sin ventaja competitiva identificable — sensible a precios y competencia",
}

def score_bar(score: float) -> str:
    filled = int(score / 10)
    return "█" * filled + "░" * (10 - filled) + f"  {score:.0f}/100"

def _moat_badge_html(classification: str, score: float, bonus: float) -> str:
    """Return an HTML badge colored by moat classification for st.markdown()."""
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
                "Moat Score": getattr(fund, "moat_score", 0.0),
                "Moat": f"{_MOAT_EMOJI.get(getattr(fund, 'moat_classification', ''), '⚪')} {getattr(fund, 'moat_classification', '—')}",
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
            "Consistency", "Piotroski", "Moat Score", "Moat",
            "Technical", "P/E", "ROE %", "Rev CAGR 5Y", "Div Yield %", "MoS %", "Price"
        ]].rename(columns={
            "Consistency": "Consist./15",
            "Piotroski": "Piotroski/9",
            "Moat Score": "Moat/20",
        }),
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
        title="Adjusted Score Ranking (Base + Consistency + Piotroski + Moat)",
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

        col1, col2, col3, col4, col5 = st.columns(5)
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
        _moat_score = getattr(fund, "moat_score", 0.0)
        _moat_class = getattr(fund, "moat_classification", "—")
        col4.metric(
            "Economic Moat",
            f"{_moat_score:.1f}/20",
            delta=_moat_class,
            help="Ventaja competitiva sostenible (Wide ≥14 | Narrow ≥8 | Minimal ≥4)",
        )
        col5.metric("Score Ajustado", f"{fund.adjusted_score:.1f}/100")

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

        # Moat detail expander
        _moat_detail = getattr(fund, "moat_detail", None)
        if _moat_detail is not None:
            _moat_class = getattr(fund, "moat_classification", "None")
            _moat_score = getattr(fund, "moat_score", 0.0)
            _moat_bonus = getattr(fund, "moat_bonus", 0.0)
            _moat_emoji = _MOAT_EMOJI.get(_moat_class, "⚪")
            with st.expander(
                f"{_moat_emoji} Economic Moat — {_moat_class} ({_moat_score:.1f}/20)",
                expanded=False,
            ):
                # Colored classification badge + description
                st.markdown(
                    _moat_badge_html(_moat_class, _moat_score, _moat_bonus),
                    unsafe_allow_html=True,
                )
                st.caption(_MOAT_DESCRIPTION.get(_moat_class, ""))
                st.divider()

                # Quantitative breakdown with inline progress bars
                st.markdown("**📊 Cuantitativo (0–12 pts)** — calculado con datos financieros reales")
                _quant_dims = [
                    ("Gross Margin nivel", _moat_detail.gross_margin_level,
                     "Margen bruto % vs umbrales (≥50%=2, ≥35%=1, ≥20%=0.5) — proxy de pricing power"),
                    ("Gross Margin estabilidad", _moat_detail.gross_margin_stability,
                     "Desviación estándar del GM en 4Y (≤3pp=2, ≤8pp=1) — estabilidad del poder de precios"),
                    ("ROIC sostenido", _moat_detail.roic_sustained,
                     "ROIC promedio histórico (≥20%=2, ≥12%=1) — retorno sobre capital invertido"),
                    ("Revenue defensividad", _moat_detail.revenue_defensiveness,
                     "Años con caída de ingresos (0 años=2, 1 año=1) — resiliencia ante recesiones"),
                    ("FCF Conversion", _moat_detail.fcf_conversion,
                     "Promedio OCF/Net Income (≥1.2=2, ≥0.9=1) — ganancias respaldadas por caja real"),
                    ("FCF Margin", _moat_detail.fcf_margin,
                     "FCF/Revenue promedio % (≥20%=2, ≥10%=1) — escalabilidad del modelo de negocio"),
                ]
                qcols = st.columns(3)
                for i, (label, val, tip) in enumerate(_quant_dims):
                    with qcols[i % 3]:
                        st.metric(label, f"{val:.1f}/2", help=tip)
                        st.markdown(_dim_bar_html(val), unsafe_allow_html=True)

                _quant_pct = round(getattr(_moat_detail, "quant_total", 0) / 12 * 100)
                st.markdown(
                    f"<small><b>Subtotal cuantitativo: {_moat_detail.quant_total:.1f}/12 "
                    f"({_quant_pct:.0f}%)</b></small>",
                    unsafe_allow_html=True,
                )

                # AI qualitative breakdown
                st.divider()
                if _moat_detail.ai_available:
                    st.markdown(f"**🤖 Cualitativo AI (0–8 pts)** — `{ai_cfg.model}`")
                    _ai_dims = [
                        ("Brand Strength", _moat_detail.brand_strength,
                         "Reconocimiento de marca, confianza y poder de fijar precios premium"),
                        ("Network Effects", _moat_detail.network_effects,
                         "El valor del servicio aumenta con más usuarios (Ley de Metcalfe)"),
                        ("Switching Costs", _moat_detail.switching_costs,
                         "Fricción real para cambiar de proveedor: tiempo, integración, riesgo operativo"),
                        ("Regulatory / IP", _moat_detail.regulatory_ip,
                         "Patentes, licencias exclusivas o regulaciones que protegen la posición"),
                    ]
                    acols = st.columns(4)
                    for i, (label, val, tip) in enumerate(_ai_dims):
                        with acols[i]:
                            st.metric(label, f"{val:.1f}/2", help=tip)
                            st.markdown(_dim_bar_html(val), unsafe_allow_html=True)

                    _ai_pct = round(getattr(_moat_detail, "ai_total", 0) / 8 * 100) if getattr(_moat_detail, "ai_total", 0) > 0 else 0
                    st.markdown(
                        f"<small><b>Subtotal AI: {_moat_detail.ai_total:.1f}/8 "
                        f"({_ai_pct:.0f}%)</b></small>",
                        unsafe_allow_html=True,
                    )
                    if _moat_detail.ai_reasoning:
                        st.info(f"💬 {_moat_detail.ai_reasoning}")
                else:
                    st.caption(
                        "🔒 Análisis cualitativo AI no disponible — "
                        "activá un proveedor AI en **⚙️ Settings** para evaluar brand, "
                        "network effects, switching costs y barreras regulatorias."
                    )

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
#  PAGE 5: OPTIMIZER                                                   #
# ================================================================== #

elif page == "📈 Optimizer":
    from portfolio.optimizer import PortfolioOptimizer, _ARS_TICKERS
    from config import OPTIMIZER_PROFILES, OPTIMIZER

    st.title("📈 Portfolio Optimizer")
    st.caption(
        "Construye una cartera óptima combinando Score Ajustado, Moat y Dividend Yield "
        "con restricciones de riesgo según tu perfil de retiro. "
        "💵 Todos los valores están denominados en **USD** (los ADRs argentinos cotizan en USD en NYSE/NASDAQ)."
    )

    # ------------------------------------------------------------------ #
    #  Profile selector — persisted in session state                      #
    # ------------------------------------------------------------------ #
    _PROFILE_LABELS = {
        "conservative": "🛡️  Conservador",
        "moderate":     "⚖️  Moderado",
        "aggressive":   "🚀 Agresivo",
    }
    _PROFILE_KEYS = {v: k for k, v in _PROFILE_LABELS.items()}

    if "optimizer_profile_key" not in st.session_state:
        st.session_state.optimizer_profile_key = "conservative"

    prev_profile_key = st.session_state.optimizer_profile_key
    profile_label = st.sidebar.radio(
        "Perfil de riesgo",
        list(_PROFILE_LABELS.values()),
        index=list(_PROFILE_LABELS.keys()).index(prev_profile_key),
        help="Conservador: preserva capital con dividendos. Moderado: balance crecimiento/ingreso. Agresivo: maximiza crecimiento a largo plazo.",
    )
    profile_key = _PROFILE_KEYS[profile_label]
    profile_changed = profile_key != prev_profile_key
    st.session_state.optimizer_profile_key = profile_key
    prof = OPTIMIZER_PROFILES[profile_key]

    max_tickers = st.sidebar.slider(
        "Tickers a analizar", 10, len(st.session_state.universe), len(st.session_state.universe),
        help="Reducir el universo acelera el análisis. El optimizador filtrará tickers por score mínimo y tipo.",
    )
    selected_universe = st.session_state.universe[:max_tickers]

    if st.sidebar.button("🔄 Re-analizar universo", type="secondary"):
        for k in ["optimizer_scored", "optimizer_universe", "optimizer_prev_result"]:
            st.session_state.pop(k, None)
        st.cache_data.clear()

    # ------------------------------------------------------------------ #
    #  Profile card (main area)                                           #
    # ------------------------------------------------------------------ #
    _PROFILE_DESC = {
        "conservative": "Preservación de capital + ingreso por dividendos. Volatilidad controlada.",
        "moderate":     "Balance entre crecimiento e ingreso. Exposición al riesgo controlada.",
        "aggressive":   "Maximización de crecimiento a largo plazo. Mayor tolerancia al riesgo.",
    }
    with st.expander(f"📋 Perfil: **{prof.name}** — {_PROFILE_DESC[profile_key]}", expanded=profile_changed):
        pc1, pc2, pc3, pc4, pc5 = st.columns(5)
        pc1.metric("Pos. máx.", f"{prof.max_position_pct:.0f}%")
        pc2.metric("Vol. máx.", f"{prof.max_volatility_pct:.0f}%")
        pc3.metric("Div. mín.", f"{prof.min_dividend_yield_pct:.1f}%")
        pc4.metric("Sector máx.", f"{prof.max_sector_pct:.0f}%")
        pc5.metric("Min. posiciones", prof.min_positions)
        st.caption(f"Pesos objetivo — Score: {prof.score_weight:.0%} · Dividendo: {prof.dividend_weight:.0%} · Moat: {prof.moat_weight:.0%}")

    # ------------------------------------------------------------------ #
    #  Gather scored tickers — cached in session_state per universe       #
    # ------------------------------------------------------------------ #
    universe_key = tuple(selected_universe)
    if "optimizer_scored" not in st.session_state or st.session_state.get("optimizer_universe") != universe_key:
        st.info("Analizando tickers del universo… (primera vez tarda ~30s, luego usa cache)")
        ai_cfg = _get_ai_config(context="screener")
        scored = []
        prog = st.progress(0)
        stat = st.empty()
        for i, sym in enumerate(selected_universe):
            stat.text(f"Analizando {sym}… ({i+1}/{len(selected_universe)})")
            prog.progress((i + 1) / len(selected_universe))
            try:
                fund, _tech, _dec = cached_full_analysis(sym, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key)
                scored.append({
                    "symbol": sym,
                    "adjusted_score": fund.adjusted_score,
                    "total_score": fund.total_score,
                    "dividend_yield": fund.dividend_yield or 0.0,
                    "moat_score": getattr(fund, "moat_score", 0.0),
                    "moat_classification": getattr(fund, "moat_classification", "None"),
                    "sector": fund.sector or "Unknown",
                    "company_name": fund.company_name,
                })
            except Exception as exc:
                logger.error(f"Optimizer {sym}: {exc}")
        prog.empty()
        stat.empty()
        if not scored:
            st.error("No se pudo analizar ningún ticker.")
            st.stop()
        st.session_state.optimizer_scored = scored
        st.session_state.optimizer_universe = universe_key
    else:
        scored = st.session_state.optimizer_scored
        st.caption(f"✓ Análisis cacheado — {len(scored)} tickers · cambia perfil instantáneamente · usa 'Re-analizar' para refrescar datos")

    # ------------------------------------------------------------------ #
    #  Run optimizer                                                      #
    # ------------------------------------------------------------------ #
    with st.spinner("Optimizando cartera…"):
        opt = PortfolioOptimizer(profile=profile_key)
        current_weights = {}
        try:
            current_weights = portfolio.get_position_weights()
        except Exception:
            pass
        result = opt.optimize(scored, current_weights=current_weights or None)

    # ------------------------------------------------------------------ #
    #  Profile-change delta banner                                        #
    # ------------------------------------------------------------------ #
    if profile_changed and "optimizer_prev_result" in st.session_state:
        prev = st.session_state.optimizer_prev_result
        prev_name = OPTIMIZER_PROFILES[prev_profile_key].name
        d_ret = result.expected_return_pct - prev.expected_return_pct
        d_vol = result.volatility_pct - prev.volatility_pct
        d_sh  = result.sharpe_ratio - prev.sharpe_ratio
        d_div = result.dividend_yield_pct - prev.dividend_yield_pct
        def _delta_str(v, unit="%", positive_good=True):
            sign = "+" if v >= 0 else ""
            color = "green" if (v >= 0) == positive_good else "red"
            return f'<span style="color:{color}">{sign}{v:.1f}{unit}</span>'
        st.markdown(
            f"**Cambio de perfil:** {prev_name} → {prof.name} &nbsp;|&nbsp; "
            f"Retorno {_delta_str(d_ret)} &nbsp; "
            f"Volatilidad {_delta_str(d_vol, positive_good=False)} &nbsp; "
            f"Sharpe {_delta_str(d_sh)} &nbsp; "
            f"Div Yield {_delta_str(d_div)}",
            unsafe_allow_html=True,
        )
        # Top movers between profiles
        prev_w = {a.symbol: a.weight_pct for a in prev.tickers}
        curr_w = {a.symbol: a.weight_pct for a in result.tickers}
        all_syms = set(prev_w) | set(curr_w)
        movers = sorted(
            [(s, curr_w.get(s, 0) - prev_w.get(s, 0)) for s in all_syms],
            key=lambda x: -abs(x[1])
        )[:6]
        mover_parts = []
        for sym, delta in movers:
            if abs(delta) >= 0.5:
                arrow = "▲" if delta > 0 else "▼"
                mover_parts.append(f"{sym} {arrow}{abs(delta):.1f}%")
        if mover_parts:
            st.caption("Principales cambios en posiciones: " + " · ".join(mover_parts))

    st.session_state.optimizer_prev_result = result

    # ------------------------------------------------------------------ #
    #  Status bar                                                         #
    # ------------------------------------------------------------------ #
    _method_badge = "🧮 Mean-Variance" if result.method == "mean-variance" else "⚖️ Score-weighted"
    st.success(f"{_method_badge} · Perfil **{result.profile_name}** · {len(result.tickers)} posiciones")
    if result.warnings:
        for w in result.warnings:
            st.warning(w)

    # ------------------------------------------------------------------ #
    #  Summary metrics row with deltas vs. profile limits                 #
    # ------------------------------------------------------------------ #
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("Retorno esperado", f"{result.expected_return_pct:.1f}%")
    mc2.metric("Volatilidad", f"{result.volatility_pct:.1f}%",
               delta=f"límite {prof.max_volatility_pct:.0f}%",
               delta_color="off")
    mc3.metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    mc4.metric("Div. Yield", f"{result.dividend_yield_pct:.2f}%",
               delta=f"mín {prof.min_dividend_yield_pct:.1f}%",
               delta_color="off")
    mc5.metric("Score Promedio", f"{result.adjusted_score_avg:.0f}/100")

    # ------------------------------------------------------------------ #
    #  Tabs                                                               #
    # ------------------------------------------------------------------ #
    tab_cart, tab_front, tab_metrics, tab_rebal = st.tabs(
        ["🧺 Cartera", "📉 Frontier", "📊 Métricas", "🔄 Rebalanceo"]
    )

    # ------------------------------------------------------------------ #
    #  Tab 1: Cartera                                                     #
    # ------------------------------------------------------------------ #
    with tab_cart:
        if not result.tickers:
            st.warning("No hay posiciones en la cartera optimizada.")
        else:
            scored_map = {t["symbol"]: t for t in scored}
            alloc_data = []
            for a in result.tickers:
                t = scored_map.get(a.symbol, {})
                moat_cls = t.get("moat_classification", "None")
                discount_note = f" (−{(1-OPTIMIZER.ars_risk_discount)*100:.0f}% ARS)" if a.score_discounted else ""
                alloc_data.append({
                    "Ticker": a.symbol,
                    "Empresa": (t.get("company_name", a.symbol) or a.symbol)[:28],
                    "Peso %": a.weight_pct,
                    "Score": a.adjusted_score,
                    "Moat": f"{_MOAT_EMOJI.get(moat_cls, '⚪')} {moat_cls}",
                    "Div %": a.dividend_yield_pct,
                    "Sector": a.sector,
                    "Notas": ("🇦🇷" + discount_note) if a.is_ars else "",
                })
            df_alloc = pd.DataFrame(alloc_data)

            # Horizontal bar chart — readable for many tickers
            df_bar = df_alloc[df_alloc["Peso %"] > 0].sort_values("Peso %")
            fig_bar = px.bar(
                df_bar, x="Peso %", y="Ticker", orientation="h",
                color="Score", color_continuous_scale="RdYlGn",
                range_color=[40, 100],
                title="Peso por ticker (coloreado por Score Ajustado)",
                text="Peso %",
            )
            fig_bar.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig_bar.add_vline(x=prof.max_position_pct, line_dash="dash",
                              line_color="orange", annotation_text=f"máx {prof.max_position_pct:.0f}%")
            fig_bar.update_layout(height=max(350, len(df_bar) * 22), yaxis_title="", coloraxis_showscale=False)
            st.plotly_chart(fig_bar, use_container_width=True)

            # Weights table
            st.dataframe(
                df_alloc,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Peso %": st.column_config.ProgressColumn("Peso %", min_value=0, max_value=prof.max_position_pct * 1.5, format="%.1f%%"),
                    "Score":  st.column_config.NumberColumn("Score", format="%.0f"),
                    "Div %":  st.column_config.NumberColumn("Div %", format="%.2f%%"),
                },
            )

            # Sector donut + pie side by side
            if result.sector_weights:
                col_sec, col_tick = st.columns(2)
                with col_sec:
                    sec_df = pd.DataFrame([{"Sector": k, "Peso %": v} for k, v in result.sector_weights.items()])
                    fig_sec = px.pie(sec_df, values="Peso %", names="Sector", title="Por Sector", hole=0.4)
                    fig_sec.update_traces(textposition="inside", textinfo="percent+label")
                    st.plotly_chart(fig_sec, use_container_width=True)
                with col_tick:
                    # Only top-10 tickers in pie to keep it readable
                    df_top = df_alloc.nlargest(10, "Peso %")
                    others_pct = 100 - df_top["Peso %"].sum()
                    if others_pct > 0.5:
                        df_top = pd.concat([df_top, pd.DataFrame([{"Ticker": "Otros", "Peso %": others_pct}])], ignore_index=True)
                    fig_pie = px.pie(df_top, values="Peso %", names="Ticker", title="Top-10 por Ticker", hole=0.3)
                    fig_pie.update_traces(textposition="inside", textinfo="percent+label")
                    st.plotly_chart(fig_pie, use_container_width=True)

            if any(a.is_ars for a in result.tickers):
                discount_pct = (1 - OPTIMIZER.ars_risk_discount) * 100
                ars_syms = ", ".join(a.symbol for a in result.tickers if a.is_ars)
                st.info(
                    f"🇦🇷 **ADRs argentinos ({ars_syms}):** cotizan y liquidan en **USD** en NYSE/NASDAQ "
                    f"— no hay conversión de moneda al comprar. Sin embargo, su valor en pesos argentinos "
                    f"es vulnerable a devaluaciones y controles de capital. "
                    f"Por eso, en perfil **{prof.name}**, se aplica un descuento de **{discount_pct:.0f}%** "
                    "al Score Ajustado al calcular el peso óptimo (no afecta el precio ni el dividend yield reportado)."
                )

        if result.excluded:
            with st.expander(f"Tickers excluidos de la optimización ({len(result.excluded)})"):
                for sym, reason in result.excluded:
                    st.caption(f"**{sym}** — {reason}")

    # ------------------------------------------------------------------ #
    #  Tab 2: Efficient Frontier                                          #
    # ------------------------------------------------------------------ #
    with tab_front:
        if not result.frontier_returns:
            st.info("Datos de precio insuficientes para calcular la Frontera Eficiente.")
        else:
            fig_front = px.scatter(
                x=result.frontier_vols,
                y=result.frontier_returns,
                color=result.frontier_sharpes,
                color_continuous_scale="RdYlGn",
                labels={"x": "Volatilidad % (anual)", "y": "Retorno Esperado % (anual)", "color": "Sharpe"},
                title=f"Frontera Eficiente — Monte Carlo ({OPTIMIZER.frontier_points} carteras)",
            )
            fig_front.add_scatter(
                x=[result.volatility_pct],
                y=[result.expected_return_pct],
                mode="markers",
                marker=dict(size=16, color="blue", symbol="star", line=dict(width=1, color="white")),
                name=f"Cartera {prof.name}",
            )
            # Vol ceiling line
            fig_front.add_vline(
                x=prof.max_volatility_pct,
                line_dash="dash", line_color="red",
                annotation_text=f"Vol máx. {prof.max_volatility_pct:.0f}%",
                annotation_position="top right",
            )
            fig_front.update_layout(height=520, legend=dict(yanchor="bottom", y=0.01, xanchor="right", x=0.99))
            st.plotly_chart(fig_front, use_container_width=True)
            st.caption(
                "La línea roja marca el techo de volatilidad del perfil. "
                "La estrella azul es la cartera óptima (máximo Sharpe dentro de las restricciones)."
            )

    # ------------------------------------------------------------------ #
    #  Tab 3: Métricas + Constraint Compliance                            #
    # ------------------------------------------------------------------ #
    with tab_metrics:
        m1, m2 = st.columns(2)

        with m1:
            st.subheader("Estadísticas de cartera")
            st.markdown(f"""
| Métrica | Valor |
|---|---|
| Retorno esperado | **{result.expected_return_pct:.1f}%** anual |
| Volatilidad | **{result.volatility_pct:.1f}%** anual |
| Sharpe Ratio | **{result.sharpe_ratio:.2f}** |
| Dividend Yield | **{result.dividend_yield_pct:.2f}%** |
| Score promedio | **{result.adjusted_score_avg:.0f}**/100 |
| Moat promedio | **{result.moat_score_avg:.1f}**/20 |
| Posiciones | **{len(result.tickers)}** |
| Método | {result.method} |
""")

            st.subheader("Compliance de restricciones")
            _checks = [
                ("Volatilidad ≤ " + f"{prof.max_volatility_pct:.0f}%",
                 result.volatility_pct <= prof.max_volatility_pct,
                 f"{result.volatility_pct:.1f}%"),
                ("Div. Yield ≥ " + f"{prof.min_dividend_yield_pct:.1f}%",
                 result.dividend_yield_pct >= prof.min_dividend_yield_pct,
                 f"{result.dividend_yield_pct:.2f}%"),
                ("Pos. máx. ≤ " + f"{prof.max_position_pct:.0f}%",
                 all(a.weight_pct <= prof.max_position_pct + 0.1 for a in result.tickers),
                 f"máx actual {max((a.weight_pct for a in result.tickers), default=0):.1f}%"),
                ("Sector máx. ≤ " + f"{prof.max_sector_pct:.0f}%",
                 all(v <= prof.max_sector_pct + 0.1 for v in result.sector_weights.values()),
                 f"máx actual {max(result.sector_weights.values(), default=0):.1f}%"),
                ("Posiciones ≥ " + str(prof.min_positions),
                 len(result.tickers) >= prof.min_positions,
                 f"{len(result.tickers)} posiciones"),
            ]
            for label, ok, detail in _checks:
                icon = "✅" if ok else "❌"
                st.markdown(f"{icon} **{label}** — {detail}")

        with m2:
            st.subheader("Pesos por sector")
            if result.sector_weights:
                for sector, pct in result.sector_weights.items():
                    ratio = pct / prof.max_sector_pct
                    bar_pct = min(int(ratio * 100), 100)
                    color = "#ff4444" if pct > prof.max_sector_pct else ("#ffbb33" if pct > prof.max_sector_pct * 0.8 else "#00C851")
                    st.markdown(
                        f"**{sector}** — {pct:.1f}% / {prof.max_sector_pct:.0f}%"
                        f'<div style="background:#e8e8e8;border-radius:4px;height:8px;margin-bottom:6px;">'
                        f'<div style="width:{bar_pct}%;background:{color};height:8px;border-radius:4px;"></div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )

    # ------------------------------------------------------------------ #
    #  Tab 4: Rebalanceo                                                  #
    # ------------------------------------------------------------------ #
    with tab_rebal:
        # Rebalancing frequency recommendation — always shown
        if result.rebalance_frequency:
            _freq_icon = {"Anual": "📅", "Semestral": "🗓️", "Trimestral": "⏱️"}.get(result.rebalance_frequency, "📅")
            st.info(
                f"{_freq_icon} **Frecuencia recomendada: {result.rebalance_frequency}** — "
                f"{result.rebalance_rationale}"
            )

        if not result.rebalance_suggestions:
            if not current_weights:
                st.info(
                    "Para ver las acciones de rebalanceo específicas, agrega tus posiciones actuales "
                    "en la página 💼 **Portfolio**. El optimizador calculará cuánto comprar/vender de cada ticker."
                )
            else:
                st.success("✅ Tu cartera actual ya está alineada con la asignación óptima.")
        else:
            buys  = [s for s in result.rebalance_suggestions if s.action == "BUY"]
            sells = [s for s in result.rebalance_suggestions if s.action == "SELL"]
            holds = [s for s in result.rebalance_suggestions if s.action == "HOLD"]

            rb1, rb2, rb3 = st.columns(3)
            rb1.metric("Compras", len(buys))
            rb2.metric("Ventas", len(sells))
            rb3.metric("Sin cambio", len(holds))

            # Waterfall-style bar chart for delta
            rebal_data = [
                {
                    "Ticker": s.symbol,
                    "Actual %": s.current_pct,
                    "Objetivo %": s.target_pct,
                    "Δ %": s.delta_pct,
                    "Acción": s.action,
                }
                for s in result.rebalance_suggestions
                if abs(s.delta_pct) >= 0.5  # hide trivial changes
            ]
            df_rebal = pd.DataFrame(rebal_data)
            if not df_rebal.empty:
                fig_rebal = px.bar(
                    df_rebal.sort_values("Δ %"),
                    x="Δ %", y="Ticker", orientation="h",
                    color="Δ %", color_continuous_scale="RdYlGn",
                    range_color=[-20, 20],
                    title="Δ Peso recomendado vs. cartera actual",
                )
                fig_rebal.add_vline(x=0, line_color="gray", line_width=1)
                fig_rebal.update_layout(height=max(300, len(df_rebal) * 22), coloraxis_showscale=False)
                st.plotly_chart(fig_rebal, use_container_width=True)

            st.dataframe(
                pd.DataFrame(rebal_data) if rebal_data else pd.DataFrame(
                    [{"Ticker": s.symbol, "Actual %": s.current_pct, "Objetivo %": s.target_pct, "Δ %": s.delta_pct, "Acción": s.action}
                     for s in result.rebalance_suggestions]
                ),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Δ %": st.column_config.NumberColumn("Δ %", format="%.1f"),
                },
            )
            st.caption(
                "Solo se muestran movimientos ≥ 0.5%. Los pesos son porcentajes sobre el total de la cartera. "
                "⚠️ Estas sugerencias son orientativas y no constituyen asesoramiento financiero. "
                "Consultá con un asesor antes de ejecutar operaciones."
            )


# ================================================================== #
#  PAGE 6: BACKTESTING                                                 #
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
                tdf,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "CAGR %":    st.column_config.NumberColumn(format="%.1f%%"),
                    "Alpha %":   st.column_config.NumberColumn(format="%.1f%%"),
                    "Sharpe":    st.column_config.NumberColumn(format="%.2f"),
                    "Sortino":   st.column_config.NumberColumn(format="%.2f"),
                    "Max DD %":  st.column_config.NumberColumn(format="%.1f%%"),
                    "Win Rate %":st.column_config.NumberColumn(format="%.0f%%"),
                },
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
