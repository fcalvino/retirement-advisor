"""Stock Deep Dive — full fundamental, technical and AI analysis for a single ticker."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import plotly.graph_objects as go
import streamlit as st

from dashboard.shared import (
    _MOAT_DESCRIPTION,
    _MOAT_EMOJI,
    ACTION_COLOR,
    _dim_bar_html,
    _get_ai_config,
    _moat_badge_html,
    cached_full_analysis,
)
from data.fetcher import get_history
from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Page config                                                         #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="Stock Analysis — Retirement Advisor",
    page_icon="🔍",
    layout="wide",
)

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("🔍 Stock Deep Dive")

col1, col2 = st.columns([2, 1])
with col1:
    symbol = st.text_input("Ticker symbol", value="AAPL").upper().strip()
with col2:
    st.button("Analyze", type="primary", use_container_width=True)

if symbol:
    ai_cfg = _get_ai_config()
    with st.spinner(f"Analyzing {symbol}..."):
        fund, tech, decision = cached_full_analysis(
            symbol, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
        )

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

    # Score breakdown — row 1
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Profitability", f"{fund.profitability_score:.0f}/25")
    col2.metric("Fin. Health",   f"{fund.health_score:.0f}/20")
    col3.metric("Valuation",     f"{fund.valuation_score:.0f}/25")
    col4.metric("Growth",        f"{fund.growth_score:.0f}/20")
    col5.metric("Dividend",      f"{fund.dividend_score:.0f}/10")

    # Score breakdown — row 2
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
            c1.metric("ROE Stability",    f"{cd.roe_score:.1f}/5")
            c2.metric("EPS Stability",    f"{cd.eps_score:.1f}/5")
            c3.metric("Margin Stability", f"{cd.margin_score:.1f}/5")
            if cd.notes:
                for note in cd.notes:
                    st.caption(f"⚠️ {note}")

    # Piotroski F-score detail
    if getattr(fund, "piotroski_detail", None):
        pd_obj = fund.piotroski_detail
        _piotroski_labels = {
            "f1_roa_positive":            "F1 — ROA > 0 (actual)",
            "f2_ocf_positive":            "F2 — Operating Cash Flow > 0",
            "f3_roa_improving":           "F3 — ROA mejoró YoY",
            "f4_leverage_decreasing":     "F4 — Deuda/Activos ↓ YoY",
            "f5_liquidity_improving":     "F5 — Current Ratio ↑ YoY",
            "f6_no_dilution":             "F6 — Sin dilución accionaria (≤2%)",
            "f7_gross_margin_improving":  "F7 — Margen bruto ↑ YoY",
            "f8_asset_turnover_improving":"F8 — Asset Turnover ↑ YoY",
            "f9_accruals_quality":        "F9 — OCF > Net Income (accruals)",
        }
        with st.expander(f"🏦 Detalle Piotroski F-Score ({pd_obj.score}/9)", expanded=False):
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
            st.markdown(_moat_badge_html(_moat_class, _moat_score, _moat_bonus), unsafe_allow_html=True)
            st.caption(_MOAT_DESCRIPTION.get(_moat_class, ""))
            st.divider()

            st.markdown("**📊 Cuantitativo (0–12 pts)** — calculado con datos financieros reales")
            _quant_dims = [
                ("Gross Margin nivel",       _moat_detail.gross_margin_level,
                 "Margen bruto % vs umbrales (≥50%=2, ≥35%=1, ≥20%=0.5) — proxy de pricing power"),
                ("Gross Margin estabilidad", _moat_detail.gross_margin_stability,
                 "Desviación estándar del GM en 4Y (≤3pp=2, ≤8pp=1) — estabilidad del poder de precios"),
                ("ROIC sostenido",           _moat_detail.roic_sustained,
                 "ROIC promedio histórico (≥20%=2, ≥12%=1) — retorno sobre capital invertido"),
                ("Revenue defensividad",     _moat_detail.revenue_defensiveness,
                 "Años con caída de ingresos (0 años=2, 1 año=1) — resiliencia ante recesiones"),
                ("FCF Conversion",           _moat_detail.fcf_conversion,
                 "Promedio OCF/Net Income (≥1.2=2, ≥0.9=1) — ganancias respaldadas por caja real"),
                ("FCF Margin",               _moat_detail.fcf_margin,
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

            st.divider()
            if _moat_detail.ai_available:
                st.markdown(f"**🤖 Cualitativo AI (0–8 pts)** — `{ai_cfg.model}`")
                _ai_dims = [
                    ("Brand Strength",  _moat_detail.brand_strength,
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

                _ai_total = getattr(_moat_detail, "ai_total", 0)
                _ai_pct   = round(_ai_total / 8 * 100) if _ai_total > 0 else 0
                st.markdown(
                    f"<small><b>Subtotal AI: {_ai_total:.1f}/8 ({_ai_pct:.0f}%)</b></small>",
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
            ("ROE",              fund.roe,              "%"),
            ("ROIC",             fund.roic,             "%"),
            ("Net Margin",       fund.net_margin,       "%"),
            ("Gross Margin",     fund.gross_margin,     "%"),
            ("Debt/Equity",      fund.debt_equity,      "x"),
            ("Current Ratio",    fund.current_ratio,    "x"),
            ("Interest Coverage",fund.interest_coverage,"x"),
            ("P/E Ratio",        fund.pe_ratio,         "x"),
            ("PEG Ratio",        fund.peg_ratio,        "x"),
            ("EV/EBITDA",        fund.ev_ebitda,        "x"),
            ("P/B Ratio",        fund.pb_ratio,         "x"),
            ("Revenue CAGR 5Y",  fund.revenue_cagr_5y,  "%"),
            ("EPS CAGR 5Y",      fund.eps_cagr_5y,      "%"),
            ("FCF Yield",        fund.fcf_yield,        "%"),
            ("Dividend Yield",   fund.dividend_yield,   "%"),
            ("Payout Ratio",     fund.payout_ratio,     "%"),
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
        col1.metric("Signal",          f"{tech.signal}")
        col2.metric("Signal Strength", f"{tech.signal_strength:+d}/100")
        col3.metric("ADX (Trend Power)",f"{tech.adx:.1f}" if tech.adx else "N/A")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Above SMA200", "✅" if tech.above_sma200 else "❌")
        col2.metric("Above SMA100", "✅" if tech.above_sma100 else "❌")
        col3.metric("MACD Bullish",  "✅" if tech.macd_bullish  else "❌")
        col4.metric("RSI (weekly)", f"{tech.rsi_weekly:.1f}" if tech.rsi_weekly else "N/A")

        col1, col2 = st.columns(2)
        col1.metric("SMA200 Slope (26w)", f"{tech.sma200_slope_pct:+.1f}%")
        col2.metric("vs 52w High",        f"{tech.price_vs_52w_high_pct:+.1f}%")

        if tech.notes:
            st.success("  ·  ".join(tech.notes))
        if tech.warnings:
            st.warning("  ·  ".join(tech.warnings))

    with tab_chart:
        hist = get_history(symbol, period="10y", interval="1wk")
        if not hist.empty:
            price  = hist["close"]
            sma50  = price.rolling(50).mean()
            sma200 = price.rolling(200).mean()

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=hist.index, y=price,  name="Price",   line=dict(color="#2196F3", width=2)))
            fig.add_trace(go.Scatter(x=hist.index, y=sma50,  name="SMA 50",  line=dict(color="#FF9800", width=1.5, dash="dot")))
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

        # Add to portfolio
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
            portfolio: Portfolio = st.session_state.portfolio
            portfolio.add_position(symbol, shares, cost, str(buy_date))
            st.success(f"Added {shares:.0f} × {symbol} @ ${cost:.2f}")
            st.session_state.portfolio = portfolio
