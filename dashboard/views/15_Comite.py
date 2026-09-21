"""Comité de inversión — panel multi-agente con disenso explícito (Fase 2B)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from loguru import logger

from dashboard.shared import (
    AI_BADGE,
    CALC_BADGE,
    _get_ai_config,
    cached_full_analysis,
    consensus_empty_caption,
    dissent_empty_caption,
    render_ai_badge,
    render_committee_status,
)
from data.product_ux import guided_empty_state

st.title("🏛️ Comité de Inversión")
st.caption(
    "En vez de una sola opinión de IA, un panel de agentes especializados debate y produce un "
    "dictamen con **disenso explícito**. El Abogado del Diablo siempre arma el bear case, así "
    "el desacuerdo queda a la vista en lugar de barrerse bajo la alfombra."
)

# Coherent research experience (backlog 6)
_c1, _c2 = st.columns(2)
if _c1.button("🔍 Ver ficha completa", key="comite_to_sa", width="stretch"):
    st.switch_page(str(Path(__file__).parent / "2_Stock_Analysis.py"))
if _c2.button("💬 Preguntar en el chat", key="comite_to_chat", width="stretch"):
    st.switch_page(str(Path(__file__).parent / "18_Chat.py"))

ai_cfg = _get_ai_config()
if not getattr(ai_cfg, "enabled", False):
    st.warning(
        "El comité necesita la IA habilitada. Andá a **Settings**, activá la IA y elegí un "
        "proveedor/modelo, después volvé acá."
    )
    st.stop()

_default_sym = st.session_state.get("comite_last_symbol") or "MSFT"
# Keyed + seeded once: a key-less widget whose `value` changes after each run is
# rebuilt by Streamlit, dropping the ticker typed for the next convene.
st.session_state.setdefault("comite_symbol_input", _default_sym)
symbol = st.text_input("Ticker a evaluar", key="comite_symbol_input").strip().upper()
run = st.button("🏛️ Convocar al comité", type="primary")

# Show last verdict instead of a dead-empty page (backlog 2)
_last = st.session_state.get("comite_last_verdict")
if not run and _last and _last.get("symbol"):
    st.success(
        f"Último dictamen en esta sesión: **{_last['symbol']}** → {_last.get('action', '—')} "
        f"(conf. {_last.get('confidence', '—')}). Convocá de nuevo para actualizar.",
        icon="📋",
    )
elif not run:
    _es = guided_empty_state("comite")
    st.info(
        f"**{_es['title']}** — {_es['body']}  \n{_es['demo_hint']}",
        icon="🏛️",
    )
    if st.button(f"Probar con {_es['demo_ticker']}", key="comite_demo"):
        st.session_state["comite_last_symbol"] = _es["demo_ticker"]
        # The input is already instantiated: drop it so the rerun re-seeds it.
        st.session_state.pop("comite_symbol_input", None)
        st.rerun()

if run and symbol:
    with st.spinner(f"Analizando {symbol}…"):
        # Quant only — moat/decisión AI here would burn the same Groq TPM the
        # panel needs. The committee is the AI surface on this page.
        fund, tech, _ = cached_full_analysis(
            symbol, ai_cfg.provider, ai_cfg.model, False, ai_cfg.api_key
        )

    # The PM sizes against the REAL book (tracker values fetched once; no recompute).
    portfolio_ctx = None
    _pf = st.session_state.get("portfolio")
    if _pf is not None and getattr(_pf, "positions", None):
        try:
            from analysis.committee import build_ticker_portfolio_context
            from data.plan_context import get_active_plan

            _values = _pf.get_current_values()
            _total_mv = sum(v["market_value"] for v in _values.values()) or 1.0
            _pos_w = {s: v["market_value"] / _total_mv * 100 for s, v in _values.items()}
            _sec_w: dict[str, float] = {}
            for v in _values.values():
                _sec_w[v["sector"]] = _sec_w.get(v["sector"], 0.0) + v["market_value"] / _total_mv * 100
            portfolio_ctx = build_ticker_portfolio_context(
                symbol, getattr(fund, "sector", ""),
                position_weights=_pos_w, sector_weights=_sec_w, active_plan=get_active_plan(),
            )
        except Exception as exc:  # pragma: no cover - UI guard, PM falls back to no-book prompt
            logger.warning(f"comité page: portfolio context skipped — {exc}")
            portfolio_ctx = None

    with st.spinner("El comité está deliberando (varios agentes en paralelo)…"):
        try:
            from analysis.committee import CommitteeAnalyzer

            verdict = CommitteeAnalyzer(ai_config=ai_cfg).analyze(fund, tech, portfolio_ctx)
        except Exception as exc:  # pragma: no cover - UI guard
            logger.error(f"comité page: failed — {exc}")
            st.error(f"No se pudo ejecutar el comité: {exc}")
            st.stop()

    st.session_state["comite_last_symbol"] = symbol
    if not verdict.complete:
        st.session_state.pop("comite_last_verdict", None)
    if not render_committee_status(verdict):
        st.stop()

    # Log to track record only a complete panel — a 429 that drops PM/Macro
    # reweights the lean toward the Devil's Advocate.
    if verdict.complete:
        try:
            from analysis.track_record import track_record_store

            track_record_store.log_recommendation(
                verdict.to_decision(fund, tech),
                source="committee",
                price_at_rec=getattr(fund, "current_price", None) or None,
                fundamental=fund,
            )
        except Exception:
            pass

    # Verdict banner
    _color = {"STRONG BUY": "#1a7f37", "BUY": "#2da44e", "HOLD": "#bf8700",
              "REDUCE": "#bc4c00", "SELL": "#cf222e"}.get(verdict.action, "#888")
    st.markdown(
        f"<div style='padding:14px;border-radius:10px;background:{_color}1a;"
        f"border-left:6px solid {_color}'>"
        f"<b style='color:{_color};font-size:1.3em'>Dictamen {symbol}: {verdict.action}</b>"
        f" &nbsp;|&nbsp; Confianza: <b>{verdict.confidence}</b>"
        f" &nbsp;|&nbsp; Lean: {verdict.lean:+.2f}</div>",
        unsafe_allow_html=True,
    )

    col_c, col_d = st.columns(2)
    with col_c:
        st.subheader("✅ Consenso")
        if verdict.consensus_points:
            for p in verdict.consensus_points:
                st.markdown(f"- {p}")
        else:
            st.caption(consensus_empty_caption(verdict))
    with col_d:
        st.subheader("⚖️ Disenso (bear case)")
        if verdict.dissent:
            for d in verdict.dissent:
                st.markdown(f"- {d}")
        else:
            st.caption(dissent_empty_caption(verdict))

    st.divider()
    st.subheader("🗣️ Opiniones por agente")
    for op in verdict.opinions:
        title = f"{op.role} — {op.stance} ({op.confidence})"
        if op.error:
            title = f"{op.role} — ⚠️ error"
        with st.expander(title):
            if op.error:
                st.error(op.error)
                continue
            if op.key_points:
                st.markdown("**Argumentos:**")
                for k in op.key_points:
                    st.markdown(f"- {k}")
            if op.concerns:
                st.markdown("**Preocupaciones:**")
                for c in op.concerns:
                    st.markdown(f"- {c}")

    render_ai_badge("dictamen multi-agente; se apoya en cálculos, no los reemplaza")
    st.caption(f"{CALC_BADGE} base del análisis · {AI_BADGE} votación del panel")
    if verdict.complete:
        st.caption("Este dictamen quedó registrado en el Track Record con fuente `committee`.")
    if portfolio_ctx:
        st.caption(
            f"El Portfolio Manager dimensionó sobre tu cartera real: {symbol} pesa "
            f"{portfolio_ctx['weight_pct']:.1f}% y su sector {portfolio_ctx['sector_weight_pct']:.1f}%."
        )
    st.session_state["comite_last_symbol"] = symbol
    if verdict.complete:
        st.session_state["comite_last_verdict"] = {
            "symbol": symbol,
            "action": getattr(verdict, "action", ""),
            "confidence": getattr(verdict, "confidence", ""),
        }
