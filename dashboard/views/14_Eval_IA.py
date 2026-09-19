"""Eval IA — calidad de las decisiones del motor de IA contra casos dorados (Fase 2A)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from loguru import logger

from analysis.eval_harness import LiveProvider, ReplayProvider, run_eval
from config import EVAL
from dashboard.shared import _get_ai_config

st.title("🧪 Eval IA")
st.caption(
    "Mide la *calidad* de las decisiones de la IA contra un set de casos dorados. Es la red "
    "de seguridad que permite mejorar los prompts (y el futuro comité multi-agente) sin volar "
    "a ciegas: cambiás algo, volvés a correr, y ves si mejoró o empeoró."
)

st.info(
    "**Modo replay** (por defecto) usa respuestas grabadas: es determinista, gratis y sin API. "
    "**Modo en vivo** corre el proveedor de IA configurado en Settings sobre los mismos casos.",
    icon="ℹ️",
)

mode = st.radio(
    "Modo de evaluación",
    options=["Replay (grabado)", "En vivo (IA real)"],
    horizontal=True,
)

run = st.button("▶️ Correr evaluación", type="primary")

if run:
    if mode.startswith("En vivo"):
        ai_cfg = _get_ai_config()
        if not getattr(ai_cfg, "enabled", False):
            st.warning("La IA no está habilitada en Settings. Corriendo en modo replay.")
            provider = ReplayProvider()
        else:
            provider = LiveProvider(ai_cfg)
    else:
        provider = ReplayProvider()

    with st.spinner(f"Evaluando casos [{provider.name}]…"):
        try:
            report = run_eval(provider)
        except Exception as exc:  # pragma: no cover - UI guard
            logger.error(f"eval page: run failed — {exc}")
            st.error(f"No se pudo correr la evaluación: {exc}")
            st.stop()

    # Headline
    color = "normal" if report.is_green else "inverse"
    c1, c2, c3 = st.columns(3)
    c1.metric("Casos OK", f"{report.n_passed}/{report.n_cases}")
    c2.metric("Tasa de aprobación", f"{report.suite_pass_rate * 100:.0f}%", delta_color=color)
    c3.metric("Estado", "🟢 GREEN" if report.is_green else "🔴 RED")

    st.caption(
        f"Umbral de suite: {EVAL.suite_pass_threshold * 100:.0f}% de casos deben pasar. "
        f"Proveedor: `{provider.name}`."
    )

    # Per-case table
    st.subheader("Resultado por caso")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Caso": r.case_id,
                    "Acción": r.action,
                    "Score": round(r.score * 100, 0),
                    "OK": "✅" if r.passed else "❌",
                    "Fallos": ", ".join(f.name for f in r.failures) or "—",
                }
                for r in report.results
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )

    # Failures detail
    failing = [r for r in report.results if not r.passed]
    if failing:
        st.subheader("Detalle de fallos")
        for r in failing:
            with st.expander(f"❌ {r.case_id} — {r.description}"):
                for f in r.failures:
                    st.markdown(f"- **{f.name}**: {f.detail}")

    # Per-check pass rates
    st.subheader("Tasa de aprobación por check")
    rates = report.check_pass_rates()
    if rates:
        st.bar_chart(pd.Series({k: v * 100 for k, v in rates.items()}).sort_values())
else:
    st.caption("Apretá **Correr evaluación** para ver los resultados.")
