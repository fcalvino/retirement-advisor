"""Comité de inversión — panel multi-agente con disenso explícito (Fase 2B)."""

from __future__ import annotations

import streamlit as st
from loguru import logger

from dashboard.shared import _get_ai_config, cached_full_analysis

st.title("🏛️ Comité de Inversión")
st.caption(
    "En vez de una sola opinión de IA, un panel de agentes especializados debate y produce un "
    "dictamen con **disenso explícito**. El Abogado del Diablo siempre arma el bear case, así "
    "el desacuerdo queda a la vista en lugar de barrerse bajo la alfombra."
)

ai_cfg = _get_ai_config()
if not getattr(ai_cfg, "enabled", False):
    st.warning(
        "El comité necesita la IA habilitada. Andá a **Settings**, activá la IA y elegí un "
        "proveedor/modelo, después volvé acá."
    )
    st.stop()

symbol = st.text_input("Ticker a evaluar", value="MSFT").strip().upper()
run = st.button("🏛️ Convocar al comité", type="primary")

if not run:
    st.info(
        "Escribí un ticker y tocá **🏛️ Convocar al comité**. Vas a ver el dictamen de un panel de "
        "agentes — **Analista Fundamental**, **Analista Técnico**, **Gestor de Riesgo** y el "
        "**Abogado del Diablo** (que siempre arma el bear case) — con su nivel de acuerdo y el "
        "desacuerdo a la vista.",
        icon="🏛️",
    )

if run and symbol:
    with st.spinner(f"Analizando {symbol}…"):
        fund, tech, _ = cached_full_analysis(
            symbol, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
        )

    with st.spinner("El comité está deliberando (varios agentes en paralelo)…"):
        try:
            from analysis.committee import CommitteeAnalyzer

            verdict = CommitteeAnalyzer(ai_config=ai_cfg).analyze(fund, tech)
        except Exception as exc:  # pragma: no cover - UI guard
            logger.error(f"comité page: failed — {exc}")
            st.error(f"No se pudo ejecutar el comité: {exc}")
            st.stop()

    # Log to track record as a committee-sourced recommendation.
    try:
        from analysis.track_record import track_record_store

        track_record_store.log_recommendation(
            verdict.to_decision(fund, tech),
            source="committee",
            price_at_rec=getattr(fund, "current_price", None) or None,
        )
    except Exception:
        pass

    # Verdict banner
    _color = {"STRONG BUY": "#1a7f37", "BUY": "#2da44e", "HOLD": "#bf8700",
              "REDUCE": "#bc4c00", "SELL": "#cf222e"}.get(verdict.action, "#888")
    st.markdown(
        f"<div style='padding:14px;border-radius:10px;background:{_color}1a;"
        f"border-left:6px solid {_color}'>"
        f"<b style='color:{_color};font-size:1.3em'>Dictamen: {verdict.action}</b>"
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
            st.caption("Sin puntos de consenso fuertes.")
    with col_d:
        st.subheader("⚖️ Disenso (bear case)")
        if verdict.dissent:
            for d in verdict.dissent:
                st.markdown(f"- {d}")
        else:
            st.caption("El comité no registró disenso material.")

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

    st.caption("Este dictamen quedó registrado en el Track Record con fuente `committee`.")
