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
from config import normalize_crypto_ticker
from data.fetcher import get_history
from data.preferences import UserPreferences
from data.universe_loader import load_universe
from portfolio.tracker import Portfolio

# Display labels make crypto searchable by full name (Bitcoin, Ethereum…)
_TICKER_DISPLAY_NAMES: dict[str, str] = {
    "BTC-USD": "BTC-USD — Bitcoin",
    "ETH-USD": "ETH-USD — Ethereum",
}

# ------------------------------------------------------------------ #
#  Session guard (fresh-session direct navigation)                     #
# ------------------------------------------------------------------ #

if "user_prefs" not in st.session_state:
    st.session_state.user_prefs = UserPreferences.load()
if "universe" not in st.session_state:
    _uk = getattr(st.session_state.user_prefs, "active_universe", "default") or "default"
    st.session_state.universe = load_universe(_uk)
    st.session_state.active_universe_key = _uk
if "portfolio" not in st.session_state:
    st.session_state.portfolio = Portfolio()

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("🔍 Análisis Profundo")

_universe_tickers = sorted(st.session_state.get("universe", []))

# Build display labels: crypto tickers get full name so "Bitcoin"/"BTC" both match
_option_labels = [_TICKER_DISPLAY_NAMES.get(t, t) for t in _universe_tickers]
_label_to_ticker = {_TICKER_DISPLAY_NAMES.get(t, t): t for t in _universe_tickers}

# --- Ticker selector -------------------------------------------------
_sc1, _sc2 = st.columns([3, 1])
with _sc1:
    _selected_label = st.selectbox(
        "ticker_select",
        options=_option_labels,
        index=None,
        placeholder="🔍 Escribí para buscar... (Ej: AAPL, MSFT, BTC, Bitcoin)",
        label_visibility="collapsed",
    )
_selected = _label_to_ticker.get(_selected_label) if _selected_label else None
with _sc2:
    _analyze_btn = st.button(
        "🔍 Analizar",
        type="primary",
        disabled=_selected is None,
        use_container_width=True,
    )

# Manual ticker outside universe (with crypto alias resolution)
with st.expander("¿No está en el universo? Ingresalo manualmente"):
    _mc1, _mc2 = st.columns([3, 1])
    with _mc1:
        _manual_raw = st.text_input(
            "manual_ticker",
            placeholder="Ej: NVDA, BRK-B, MELI, BTC, BITCOIN",
            label_visibility="collapsed",
        ).upper().strip()
        _manual = normalize_crypto_ticker(_manual_raw) if _manual_raw else ""
        if _manual and _manual != _manual_raw:
            st.caption(f"🔄 '{_manual_raw}' → `{_manual}`")
    with _mc2:
        if st.button("Analizar", key="analyze_manual", disabled=not _manual,
                     use_container_width=True):
            st.session_state.analysis_target = _manual

# Gate: only trigger analysis on explicit button click
if _analyze_btn and _selected:
    st.session_state.analysis_target = _selected

# Empty state — no ticker analyzed yet
_target = st.session_state.get("analysis_target")
if not _target:
    st.info(
        "👆 Seleccioná un ticker del universo activo y presioná **Analizar** para ver el análisis completo.",
        icon="🔍",
    )
    if _universe_tickers:
        st.caption(
            f"Universo activo: **{len(_universe_tickers)} tickers** disponibles — "
            "podés buscar por símbolo o nombre (ej: BTC, Bitcoin, AAPL, Apple)."
        )
    st.stop()

# Stale warning: selected ≠ analyzed
if _selected and _selected != _target:
    st.info(
        f"Mostrando análisis de **{_target}**. "
        f"Seleccionaste **{_selected}** — presioná **Analizar** para actualizarlo.",
        icon="ℹ️",
    )

symbol = _target

if symbol:
    ai_cfg = _get_ai_config()
    with st.spinner(f"Analizando {symbol}…"):
        fund, tech, decision = cached_full_analysis(
            symbol, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
        )

    # Header
    _prefs: UserPreferences = st.session_state.user_prefs
    _in_watchlist = symbol in _prefs.watched_tickers
    _is_crypto = getattr(fund, "is_crypto", False)

    h_col, wl_col = st.columns([5, 1])
    with h_col:
        _crypto_badge = (
            ' <span style="background:#f7931a;color:white;font-size:0.7em;'
            'padding:2px 7px;border-radius:10px;vertical-align:middle;'
            'font-weight:700;letter-spacing:0.5px">🪙 CRYPTO</span>'
            if _is_crypto else ""
        )
        st.markdown(
            f"## {decision.action_emoji} {fund.company_name} ({symbol}){_crypto_badge}",
            unsafe_allow_html=True,
        )
        caption = f"{fund.sector} · {fund.industry} · Market Cap: ${fund.market_cap/1e9:.1f}B"
        if decision.ai_reasoning:
            caption += f" · 🤖 {ai_cfg.model}"
        st.caption(caption)
    with wl_col:
        st.markdown("<br>", unsafe_allow_html=True)
        if _in_watchlist:
            if st.button("❌ Quitar watchlist", use_container_width=True, key="wl_rm"):
                _prefs.unwatch(symbol)
                st.session_state.user_prefs = _prefs
                st.toast(f"{symbol} eliminado de la watchlist", icon="❌")
                st.rerun()
        else:
            if st.button("📋 Watchlist", type="secondary", use_container_width=True, key="wl_add"):
                _prefs.watch(symbol)
                st.session_state.user_prefs = _prefs
                st.toast(f"{symbol} agregado a la watchlist", icon="📋")
                st.rerun()

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

    if _is_crypto:
        # ── Crypto score panel ──────────────────────────────────────────
        _moat_detail_crypto = getattr(fund, "crypto_moat_detail", None)
        _moat_score = getattr(fund, "moat_score", 0.0)
        _moat_class = getattr(fund, "moat_classification", "None")
        _crypto_notes = getattr(fund, "notes", {})

        col1, col2, col3, col4 = st.columns(4)
        col1.metric(
            "Crypto Score",
            f"{fund.adjusted_score:.1f}/100",
            help="base(35) + técnico(0–45) − volatilidad(0–25) − drawdown(0–15) + moat(0–5)",
        )
        _vol_str  = _crypto_notes.get("crypto_vol",  "—").replace("Volatilidad anualizada (52s): ", "")
        _dd_str   = _crypto_notes.get("crypto_dd",   "—").replace("Drawdown máximo histórico: ", "")
        _cagr_str = _crypto_notes.get("crypto_cagr", "—").replace("CAGR precio 4 años: ", "")
        col2.metric("Volatilidad (52s)", _vol_str,  help="Volatilidad anualizada — BTC típico: 60–90%")
        col3.metric("Max Drawdown",      _dd_str,   help="Peak-to-trough histórico — BTC: −77% (2022)")
        col4.metric("CAGR 4 años",       _cagr_str, help="Precio compuesto 4 años — proxy de adopción")

        _halving_str = _crypto_notes.get("crypto_halving", "")
        _supply_str  = _crypto_notes.get("crypto_supply", "")
        col1b, col2b, col3b = st.columns(3)
        col1b.metric(
            "Crypto Moat",
            f"{_moat_score:.1f}/8" if _moat_detail_crypto and _moat_detail_crypto.ai_available else "N/A",
            delta=_moat_class,
            help="Moat crypto AI: network adoption + escasez monetaria + seguridad + regulatorio + tecnología",
        )
        col2b.metric("Ciclo Halving", _halving_str.replace("Ciclo halving: ", "") or "—")
        col3b.metric("Suministro emitido", _supply_str.replace("Suministro emitido: ", "") or "—")

        # Crypto moat detail expander
        if _moat_detail_crypto and _moat_detail_crypto.ai_available:
            _alloc_rec  = getattr(_moat_detail_crypto, "recommended_max_allocation_pct", None)
            _dur_years  = getattr(_moat_detail_crypto, "moat_durability_years", 0)
            _ret_risk   = getattr(_moat_detail_crypto, "retirement_risk_summary", "")
            _alloc_label = f" · Asignación Conservadora: ≤{_alloc_rec:.0f}%" if _alloc_rec else ""
            _dur_label   = f" · Durabilidad: ~{_dur_years}a" if _dur_years else ""
            with st.expander(
                f"🏰 Crypto Moat — {_moat_class} ({_moat_score:.1f}/8){_alloc_label}{_dur_label}",
                expanded=False,
            ):
                _cm = _moat_detail_crypto
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                mc1.metric("Red & Adopción",    f"{_cm.network_adoption}/2")
                mc2.metric("Escasez (Halving)", f"{_cm.monetary_scarcity}/2")
                mc3.metric("Seguridad",         f"{_cm.security_decentralization}/1.5")
                mc4.metric("Regulatorio",       f"{_cm.institutional_regulatory}/1.5")
                mc5.metric("Tecnología",        f"{_cm.tech_resilience}/1")
                if _cm.ai_reasoning:
                    st.info(f"💬 {_cm.ai_reasoning}")
                if _ret_risk:
                    st.error(f"🏥 **Riesgo para jubilados:** {_ret_risk}", icon="⚠️")
                if _alloc_rec:
                    st.warning(
                        f"🛡️ **Límite de asignación (perfil Conservador):** ≤{_alloc_rec:.0f}% "
                        f"del portafolio · Durabilidad estimada del moat: ~{_dur_years} años"
                        f" · Drawdown máx histórico: {_dd_str}.",
                    )
        elif _moat_detail_crypto and not _moat_detail_crypto.ai_available:
            st.caption(
                "🔒 Moat crypto AI no disponible — activá un proveedor AI en **⚙️ Settings** "
                "para evaluar network effects, escasez monetaria, seguridad y regulatorio."
            )

    else:
        # ── Equity score panel (original) ───────────────────────────────
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Profitability", f"{fund.profitability_score:.0f}/25")
        col2.metric("Fin. Health",   f"{fund.health_score:.0f}/20")
        col3.metric("Valuation",     f"{fund.valuation_score:.0f}/25")
        col4.metric("Growth",        f"{fund.growth_score:.0f}/20")
        col5.metric("Dividend",      f"{fund.dividend_score:.0f}/10")

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

    # Moat detail expander — equity only (crypto has its own moat panel above)
    _moat_detail = getattr(fund, "moat_detail", None)
    if _moat_detail is not None and not _is_crypto:
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
                # Show durability + allocation recommendation if provided by Grok
                _dur_eq  = getattr(_moat_detail, "moat_durability_years", 0)
                _alloc_eq = getattr(_moat_detail, "recommended_max_allocation_conservative", None)
                if _dur_eq or _alloc_eq:
                    _dur_txt   = f"Durabilidad estimada: ~{_dur_eq} años" if _dur_eq else ""
                    _alloc_txt = f"Asignación máx. conservadora: ≤{_alloc_eq}%" if _alloc_eq else ""
                    st.caption(f"🛡️ {' · '.join(x for x in [_dur_txt, _alloc_txt] if x)}")
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
        if _is_crypto:
            # ── Crypto fundamentals tab ──────────────────────────────────
            _crypto_notes = getattr(fund, "notes", {})
            st.info(
                "ℹ️ Bitcoin no tiene estados financieros corporativos (ROE, P/E, etc.). "
                "Los métricas relevantes son de red, suministro y riesgo de precio.",
                icon="🪙",
            )
            st.divider()
            cr1, cr2, cr3 = st.columns(3)
            cr1.metric(
                "Market Cap",
                f"${fund.market_cap/1e9:.1f}B",
                help="Capitalización de mercado en billones USD",
            )
            cr2.metric(
                "Precio Actual",
                f"${fund.current_price:,.0f}",
                help="Precio de mercado actual (USD)",
            )
            _moat_detail_c = getattr(fund, "crypto_moat_detail", None)
            _alloc_tip = ""
            if _moat_detail_c and _moat_detail_c.ai_available:
                _alloc_tip = f"Límite recomendado (Conservador): ≤{_moat_detail_c.recommended_max_allocation_pct:.0f}%"
            cr3.metric(
                "Crypto Moat",
                f"{getattr(fund,'moat_score',0):.1f}/8",
                delta=getattr(fund, "moat_classification", "None"),
                help=_alloc_tip or "AI moat: network + escasez + seguridad + regulatorio + tecnología",
            )

            st.subheader("Métricas de riesgo")
            rr1, rr2, rr3, rr4 = st.columns(4)
            _vol  = _crypto_notes.get("crypto_vol",  "—").replace("Volatilidad anualizada (52s): ", "")
            _dd   = _crypto_notes.get("crypto_dd",   "—").replace("Drawdown máximo histórico: ", "")
            _cagr = _crypto_notes.get("crypto_cagr", "—").replace("CAGR precio 4 años: ", "")
            _sc   = _crypto_notes.get("crypto_supply","—").replace("Suministro emitido: ", "")
            rr1.metric("Volatilidad 52s",    _vol,  help="Anualizada — BTC típico: 60–90%")
            rr2.metric("Max Drawdown",       _dd,   help="Peak-to-trough histórico completo")
            rr3.metric("CAGR 4 años",        _cagr, help="Proxy de adopción y crecimiento")
            rr4.metric("Suministro emitido", _sc,   help="% del cap de 21M ya en circulación")

            _halving = _crypto_notes.get("crypto_halving", "")
            if _halving:
                st.caption(f"🔄 {_halving}")

            for warning in fund.warnings:
                st.warning(warning)

        else:
            # ── Equity fundamentals tab (original) ───────────────────────
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
            st.warning("Historial de precios no disponible.")

    with tab_decision:
        if decision.ai_reasoning:
            st.subheader(f"🤖 Análisis AI — {ai_cfg.model}")
            st.markdown(decision.ai_reasoning)
            st.divider()

        st.subheader("💡 Fundamentos de inversión")
        if decision.rationale:
            for r in decision.rationale:
                st.success(f"✅ {r}")
        else:
            st.info("Sin factores positivos identificados.")

        if decision.risks:
            st.subheader("⚠️ Riesgos a considerar")
            for risk in decision.risks:
                st.warning(f"⚠️ {risk}")

        if decision.blocked:
            st.error(f"🚫 BLOQUEADO: {decision.block_reason}")

        # Add to portfolio
        st.divider()
        st.subheader("➕ Agregar al Portfolio")
        col1, col2, col3 = st.columns(3)
        with col1:
            shares = st.number_input("Acciones", min_value=0.01, value=10.0, step=1.0)
        with col2:
            cost = st.number_input("Costo promedio (USD)", min_value=0.01, value=fund.current_price or 100.0)
        with col3:
            buy_date = st.date_input("Fecha de compra")
        if st.button("Agregar posición", type="secondary"):
            portfolio: Portfolio = st.session_state.portfolio
            portfolio.add_position(symbol, shares, cost, str(buy_date))
            st.success(f"✅ {shares:.0f} × {symbol} agregado @ ${cost:.2f}")
            st.session_state.portfolio = portfolio
