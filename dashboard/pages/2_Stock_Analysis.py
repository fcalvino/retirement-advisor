"""Stock Deep Dive — full fundamental, technical and AI analysis for a single ticker."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from analysis.fundamental import eps_growth_label
from config import MOAT
from dashboard.shared import (
    _MOAT_DESCRIPTION,
    _MOAT_EMOJI,
    ACTION_COLOR,
    _dim_bar_html,
    _get_ai_config,
    _moat_badge_html,
    _tailwind_badge_html,
    cached_full_analysis,
    render_ai_badge,
    render_calc_badge,
)
from data.fetcher import get_history
from data.preferences import UserPreferences
from data.product_ux import (
    FAST_MA_SHORT,
    MID_MA_SHORT,
    TREND_MA_HELP,
    TREND_MA_SHORT,
    roic_sustained_help,
)
from data.universe_loader import load_universe
from portfolio.tracker import Portfolio

# Display labels make crypto searchable by full name (Bitcoin, Ethereum…)
_TICKER_DISPLAY_NAMES: dict[str, str] = {
    "BTC-USD": "BTC-USD — Bitcoin",
    "ETH-USD": "ETH-USD — Ethereum",
}

_CRYPTO_ALIASES: dict[str, str] = {
    "BTC": "BTC-USD", "BITCOIN": "BTC-USD",
    "ETH": "ETH-USD", "ETHEREUM": "ETH-USD",
}


def _normalize_ticker(s: str) -> str:
    return _CRYPTO_ALIASES.get(s.upper(), s)


@st.cache_data(ttl=3600, show_spinner=False)
def _cross_source_check(symbol: str) -> dict | None:
    """Cross-source reconciliation for the data-quality panel (Fase 3A).

    Cached an hour so it never slows reruns; isolated from the analysis hot path
    (the screener never calls this). Returns a small dict for display or None.
    """
    from analysis.data_reconciliation import reconcile_sources
    from data.data_sources import default_fundamental_sources

    report = reconcile_sources(symbol, default_fundamental_sources())
    return report.as_dict()

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
st.caption(
    "Ficha + enlaces al **Comité** y al **Chat** (misma pregunta, tres capas: "
    "números · debate · conversación)."
)
_rx1, _rx2 = st.columns(2)
from pathlib import Path as _PathSA

if _rx1.button("🏛️ Convocar comité sobre este ticker", key="sa_to_comite", width="stretch"):
    if st.session_state.get("sa_last_symbol"):
        st.session_state["comite_last_symbol"] = st.session_state["sa_last_symbol"]
    st.switch_page(str(_PathSA(__file__).parent / "15_Comite.py"))
if _rx2.button("💬 Preguntar en el chat", key="sa_to_chat", width="stretch"):
    st.switch_page(str(_PathSA(__file__).parent / "18_Chat.py"))

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
        width="stretch",
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
        _manual = _normalize_ticker(_manual_raw) if _manual_raw else ""
        if _manual and _manual != _manual_raw:
            st.caption(f"🔄 '{_manual_raw}' → `{_manual}`")
    with _mc2:
        if st.button("Analizar", key="analyze_manual", disabled=not _manual,
                     width="stretch"):
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
    st.session_state["sa_last_symbol"] = symbol
    ai_cfg = _get_ai_config()
    with st.spinner(f"Analizando {symbol}…"):
        fund, tech, decision = cached_full_analysis(
            symbol, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
        )

    # Track record capture (Gran Salto, Fase 1) — dedupe protects against reruns.
    try:
        from analysis.track_record import track_record_store

        track_record_store.log_recommendation(
            decision,
            source=("ai" if ai_cfg.enabled else "rule_based"),
            price_at_rec=getattr(fund, "current_price", None) or None,
            fundamental=fund,
        )
    except Exception:
        pass  # never let logging break the page

    # Cross-source data check (Gran Salto, Fase 3A) — verifies the numbers against
    # a second source (SEC EDGAR) when available. Isolated + cached.
    # Also surfaces second_source_quality_signal on the decision path (backlog 9).
    try:
        from config import MULTI_SOURCE
        from data.product_ux import second_source_quality_signal

        _dq = getattr(fund, "data_quality", None) or {}
        _xs = None
        if MULTI_SOURCE.enabled and not getattr(fund, "is_crypto", False):
            _xs = _cross_source_check(symbol)
        _sig = second_source_quality_signal(_xs, data_quality=_dq if isinstance(_dq, dict) else None)
        st.caption(f"🔬 {_sig['message']}")
        if _xs and len(_xs.get("sources_used", [])) >= 2:
            _agree = _xs.get("agreement_pct")
            _ncf = _xs.get("n_conflicts", 0)
            _label = (
                f"🔬 Verificación entre fuentes: {', '.join(_xs['sources_used'])}"
                f" · acuerdo {_agree:.0f}%" if _agree is not None else "🔬 Verificación entre fuentes"
            )
            with st.expander(_label, expanded=bool(_ncf)):
                if _ncf:
                    st.warning(f"{_ncf} discrepancia(s) entre fuentes — revisá antes de confiar en el score.")
                    for _c in _xs.get("fields", []):
                        if _c.get("conflict"):
                            _vals = " vs ".join(f"{s}={v:,.0f}" for s, v in _c["values"].items())
                            st.markdown(f"- **{_c['field']}**: {_vals}  (Δ {_c['max_rel_diff_pct']:.0f}%)")
                else:
                    st.success("Los datos crudos coinciden entre las fuentes consultadas.")
    except Exception:
        pass  # cross-source check is best-effort

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
            if st.button("❌ Quitar watchlist", width="stretch", key="wl_rm"):
                _prefs.unwatch(symbol)
                st.session_state.user_prefs = _prefs
                st.toast(f"{symbol} eliminado de la watchlist", icon="❌")
                st.rerun()
        else:
            if st.button("📋 Watchlist", type="secondary", width="stretch", key="wl_add"):
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
    render_calc_badge("score fundamental y señal calculados con fórmulas (sin IA)")

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
            delta_color="off",
            delta_arrow="off",
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
        # U3-7: the scale depends on whether the AI layer ran, and so do the
        # thresholds. Showing "/20" on a quant-only score invited a comparison
        # with an AI-enriched one — the reason the same ticker looked like a
        # different company depending on the screen.
        _md = getattr(fund, "moat_detail", None)
        _moat_ai = bool(getattr(_md, "ai_available", False))
        _moat_max = getattr(_md, "scale_max", 20.0)
        _moat_mode = getattr(_md, "mode_label", "cuantitativo + IA")
        _th = (
            (MOAT.wide_threshold, MOAT.narrow_threshold, MOAT.minimal_threshold)
            if _moat_ai else
            (MOAT.quant_only_wide_threshold, MOAT.quant_only_narrow_threshold,
             MOAT.quant_only_minimal_threshold)
        )
        col4.metric(
            "Economic Moat",
            f"{_moat_score:.1f}/{_moat_max:.0f}",
            delta=f"{_moat_class} · {_moat_mode}",
            delta_color="off",
            delta_arrow="off",
            help=(
                f"Ventaja competitiva sostenible, medida en modo **{_moat_mode}** "
                f"(Wide ≥{_th[0]:g} | Narrow ≥{_th[1]:g} | Minimal ≥{_th[2]:g}). "
                "Sin la capa de IA el tramo cuantitativo topea en 12, así que los "
                "umbrales son otros — no es la misma escala corrida."
            ),
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
            st.markdown(
                _moat_badge_html(_moat_class, _moat_score, _moat_bonus, _moat_max),
                unsafe_allow_html=True,
            )
            st.caption(_MOAT_DESCRIPTION.get(_moat_class, ""))
            st.divider()

            st.markdown("**📊 Cuantitativo (0–12 pts)** — calculado con datos financieros reales")
            _quant_dims = [
                ("Gross Margin nivel",       _moat_detail.gross_margin_level,
                 "Margen bruto % vs umbrales (≥50%=2, ≥35%=1, ≥20%=0.5) — proxy de pricing power"),
                ("Gross Margin estabilidad", _moat_detail.gross_margin_stability,
                 "Desviación estándar del GM en 4Y (≤3pp=2, ≤8pp=1) — estabilidad del poder de precios"),
                ("ROIC sostenido",           _moat_detail.roic_sustained,
                 roic_sustained_help()),
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

            _quant_pct = _moat_detail.quant_pct
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
                _ai_pct = _moat_detail.ai_pct
                st.markdown(
                    f"<small><b>Subtotal AI: {_ai_total:.1f}/8 ({_ai_pct:.0f}%)</b></small>",
                    unsafe_allow_html=True,
                )
                if _moat_detail.ai_reasoning:
                    st.info(f"💬 {_moat_detail.ai_reasoning}")

                # Structured macro for moat (structural)
                _mmfs = getattr(_moat_detail, "macro_factors", None) or []
                if _mmfs:
                    st.caption("🌍 Macro que influyó en el moat / asignación:")
                    for mf in _mmfs[:2]:
                        st.caption(f"- {mf.get('factor','')}: {mf.get('effect_on_allocation_or_conviction','') or mf.get('impact','')}")

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

    # Sector-country structural tailwind (Idea 2) — equity only, visible even sin AI
    _tw_detail = getattr(fund, "tailwind_detail", None)
    if _tw_detail is not None and not _is_crypto:
        _tw_class = getattr(fund, "tailwind_classification", "Neutral")
        if _tw_class != "Neutral":
            _tw_bonus = getattr(fund, "tailwind_bonus", 0.0)
            with st.expander(
                f"{_tw_detail.emoji} Cola de viento sector-país — {_tw_detail.label_es} "
                f"({_tw_detail.tailwind_score:+.1f})",
                expanded=False,
            ):
                st.markdown(
                    _tailwind_badge_html(_tw_class, _tw_detail.tailwind_score, _tw_bonus),
                    unsafe_allow_html=True,
                )
                st.markdown(f"**Rationale (curado):** {_tw_detail.explanation}")
                tc1, tc2, tc3 = st.columns(3)
                tc1.metric(
                    "Durabilidad estimada",
                    f"~{_tw_detail.durability_years} años" if _tw_detail.durability_years else "n/d",
                    help="Años que se estima dura el factor estructural (curado)",
                )
                tc2.metric(
                    "Efecto en score",
                    f"{_tw_bonus:+.1f} pts",
                    help="Bonus/penalización ya incluido en el Score Ajustado (cap configurable)",
                )
                tc3.metric(
                    "Match",
                    _tw_detail.matched_on or "—",
                    help="Cómo se asignó: ticker explícito, industria+país o sector+país",
                )
                if getattr(_tw_detail, "ai_available", False) and _tw_detail.ai_reasoning:
                    st.info(f"💬 {_tw_detail.ai_reasoning}")
                    for _twf in (getattr(_tw_detail, "factors", None) or []):
                        st.caption(
                            f"- {_twf.get('factor', '')}: "
                            f"{_twf.get('effect_on_allocation_or_conviction', '') or _twf.get('impact', '')}"
                        )
                st.caption(
                    f"⚠️ Outlook estructural basado en datos curados a "
                    f"{_tw_detail.last_reviewed or 'n/d'} — no es garantía de retornos. "
                    "El factor afecta convicción y tamaño de posición, no reemplaza fundamentales."
                )

    # Verdict thesis up top: the conclusion (3 pros / 3 risks) before the detail.
    if decision.rationale or decision.risks:
        _t1, _t2 = st.columns(2)
        with _t1:
            st.markdown("**💡 Tesis (a favor)**")
            if decision.rationale:
                for _r in decision.rationale[:3]:
                    st.markdown(f"✅ {_r}")
            else:
                st.caption("Sin factores positivos destacados.")
        with _t2:
            st.markdown("**⚠️ Riesgos**")
            if decision.risks:
                for _rk in decision.risks[:3]:
                    st.markdown(f"⚠️ {_rk}")
            else:
                st.caption("Sin riesgos destacados.")
        st.caption("Resumen arriba; el detalle completo está en las pestañas de abajo.")

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
                # For a REIT the earnings multiple that drives the score is P/FFO;
                # P/E stays above for reference but measures the wrong thing.
                *([("P/FFO",         fund.p_ffo,            "x")] if fund.p_ffo else []),
                ("PEG Ratio",        fund.peg_ratio,        "x"),
                ("EV/EBITDA",        fund.ev_ebitda,        "x"),
                ("P/B Ratio",        fund.pb_ratio,         "x"),
                (f"Revenue CAGR {fund.revenue_cagr_years}Y" if fund.revenue_cagr_years
                 else "Revenue CAGR",  fund.revenue_cagr_5y,  "%"),
                (eps_growth_label(fund),  fund.eps_cagr_5y,      "%"),
                ("FCF Yield",        fund.fcf_yield,        "%"),
                ("Dividend Yield",   fund.dividend_yield,   "%"),
                ("Payout Ratio",     fund.payout_ratio,     "%"),
                *([("Payout s/ FFO", fund.ffo_payout_pct,   "%")] if fund.ffo_payout_pct else []),
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
                        delta_arrow="off",
                    )

    with tab_tech:
        col1, col2, col3 = st.columns(3)
        col1.metric("Signal",          f"{tech.signal}")
        col2.metric("Signal Strength", f"{tech.signal_strength:+d}/100")
        col3.metric("ADX (Trend Power)",f"{tech.adx:.1f}" if tech.adx else "N/A")

        col1, col2, col3, col4 = st.columns(4)
        # Tres estados, no dos: "—" es no tener historial suficiente para la
        # ventana, que no es lo mismo que cotizar debajo de ella (U3-1).
        _trend_mark = {True: "✅", False: "❌"}
        col1.metric(
            f"Sobre {TREND_MA_SHORT}", _trend_mark.get(tech.above_sma200, "—"),
            help=TREND_MA_HELP + (
                "  ·  «—» = la serie de precios es más corta que la ventana, "
                "así que no hay media que comparar."
            ),
        )
        col2.metric(f"Sobre {MID_MA_SHORT}", _trend_mark.get(tech.above_sma100, "—"))
        col3.metric("MACD Bullish",  "✅" if tech.macd_bullish  else "❌")
        col4.metric("RSI (weekly)", f"{tech.rsi_weekly:.1f}" if tech.rsi_weekly else "N/A")

        col1, col2 = st.columns(2)
        col1.metric(f"Pendiente {TREND_MA_SHORT} (26 sem.)", f"{tech.sma200_slope_pct:+.1f}%", help=TREND_MA_HELP)
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
            fig.add_trace(go.Scatter(x=hist.index, y=sma50,  name=FAST_MA_SHORT,  line=dict(color="#FF9800", width=1.5, dash="dot")))
            fig.add_trace(go.Scatter(x=hist.index, y=sma200, name=TREND_MA_SHORT, line=dict(color="#F44336", width=2)))
            fig.update_layout(
                title=f"{symbol} — 10 Year Weekly Chart",
                yaxis_title="Price (USD)",
                xaxis_title="",
                height=500,
                legend=dict(orientation="h"),
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.warning("Historial de precios no disponible.")

    with tab_decision:
        if decision.ai_reasoning:
            st.subheader(f"🤖 Análisis AI — {ai_cfg.model}")
            render_ai_badge("texto del modelo; los scores y métricas de abajo son cálculos")
            st.markdown(decision.ai_reasoning)

            # New: structured macro_factors display (structural improvement)
            _mfs = getattr(decision, "macro_factors", None) or []
            if _mfs:
                with st.expander("🌍 Factores macro considerados por Grok (estructurado)", expanded=False):
                    for mf in _mfs:
                        factor = mf.get("factor", "factor")
                        why = mf.get("why_relevant", "")
                        impact = mf.get("impact", "")
                        effect = mf.get("effect_on_allocation_or_conviction", "")
                        st.markdown(f"**{factor}**")
                        if why:
                            st.caption(f"Relevancia: {why}")
                        if impact:
                            st.caption(f"Impacto: {impact}")
                        if effect:
                            st.caption(f"Efecto en asignación/convicción: {effect}")
                        st.divider()
            st.divider()

        # Grok allocation recommendation banner
        _grok_alloc = getattr(decision, "recommended_max_allocation_pct", None)
        if _grok_alloc is not None:
            st.success(
                f"🎯 **Grok sugiere máximo {_grok_alloc:.0f}% de asignación** para **{symbol}** "
                f"en tu portfolio según su análisis de convicción y riesgo.",
                icon="🤖",
            )
        elif decision.ai_reasoning:
            st.caption("ℹ️ Grok no sugirió un porcentaje específico de asignación en este análisis.")

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

        _portfolio: Portfolio = st.session_state.portfolio
        # Use cost basis as portfolio value proxy (no API calls needed)
        _portfolio_cost = sum(
            p.shares * p.avg_cost for p in _portfolio.positions.values()
        ) if _portfolio.positions else 0.0
        _grok_alloc_pct = getattr(decision, "recommended_max_allocation_pct", None)
        _price = fund.current_price or 100.0

        _suggested_shares = 10.0
        _shares_caption = None
        if _grok_alloc_pct and _portfolio_cost > 0 and _price > 0:
            _suggested_shares = max(0.01, (_portfolio_cost * _grok_alloc_pct / 100) / _price)
            _shares_caption = (
                f"💡 Sugerido por Grok: máximo {_grok_alloc_pct:.0f}% del portafolio "
                f"(costo base ${_portfolio_cost:,.0f}) → {_suggested_shares:.2f} acciones @ ${_price:,.2f}"
            )

        col1, col2, col3 = st.columns(3)
        with col1:
            shares = st.number_input("Acciones", min_value=0.01, value=float(_suggested_shares), step=1.0)
            if _shares_caption:
                st.caption(_shares_caption)
        with col2:
            cost = st.number_input("Costo promedio (USD)", min_value=0.01, value=_price)
        with col3:
            buy_date = st.date_input("Fecha de compra")
        if st.button("Agregar posición", type="secondary"):
            _portfolio.add_position(symbol, shares, cost, str(buy_date))
            st.success(f"✅ {shares:.0f} × {symbol} agregado @ ${cost:.2f}")
            st.session_state.portfolio = _portfolio
