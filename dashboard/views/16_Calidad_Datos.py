"""Calidad de Datos — reconciliación multi-fuente y discrepancias (Fase 3A)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from loguru import logger

from config import MULTI_SOURCE

st.title("🔬 Calidad de Datos")
st.caption(
    "Hoy casi todo entra por una sola fuente (yfinance). Esta página trae los mismos datos "
    "crudos de varias fuentes (yfinance + SEC EDGAR) y marca dónde no coinciden, para que un "
    "número silenciosamente mal no se cuele en el análisis."
)

if not MULTI_SOURCE.enabled:
    st.warning("La reconciliación multi-fuente está desactivada en config (`MULTI_SOURCE.enabled`).")
    st.stop()

st.info(
    "**yfinance** está siempre disponible. **SEC EDGAR** funciona para acciones de EE. UU. "
    "(usa los filings oficiales); puede no devolver datos para ADRs o si no hay red. "
    "**FRED** (macro) requiere una clave API en el entorno.",
    icon="ℹ️",
)

symbol = st.text_input("Ticker a verificar", value="AAPL").strip().upper()
run = st.button("🔬 Reconciliar fuentes", type="primary")

if run and symbol:
    with st.spinner(f"Consultando fuentes para {symbol}…"):
        try:
            from analysis.data_reconciliation import data_quality_agent, reconcile_sources
            from data.data_sources import default_fundamental_sources

            report = reconcile_sources(symbol, default_fundamental_sources())
        except Exception as exc:  # pragma: no cover - UI guard
            logger.error(f"calidad de datos: failed — {exc}")
            st.error(f"No se pudo reconciliar: {exc}")
            st.stop()

    sources = report.sources_used
    c1, c2, c3 = st.columns(3)
    c1.metric("Fuentes consultadas", len(sources))
    c2.metric("Campos en conflicto", report.n_conflicts)
    c3.metric(
        "Acuerdo entre fuentes",
        f"{report.agreement_pct:.0f}%" if report.agreement_pct is not None else "—",
    )
    st.caption(f"Fuentes: {', '.join(sources) or '—'} · Umbral de discrepancia: {MULTI_SOURCE.discrepancy_pct:.0f}%")

    if len(sources) < 2:
        st.warning(
            "Solo respondió una fuente, así que no hay verificación cruzada. Para acciones "
            "de EE. UU. probá un ticker con filings en SEC EDGAR (ej. AAPL, MSFT, KO)."
        )

    # Per-field table
    rows = []
    for f in report.fields:
        row = {"Campo": f.field, "Elegido": f.chosen_value, "Fuente elegida": f.chosen_source,
               "Δ máx %": round(f.max_rel_diff_pct, 1), "Conflicto": "⚠️" if f.conflict else "✅"}
        for src in sources:
            row[src] = f.values.get(src)
        rows.append(row)
    if rows:
        st.subheader("Campos reconciliados")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    # Conflicts detail
    if report.conflicts:
        st.subheader("⚠️ Discrepancias detectadas")
        for f in report.conflicts:
            vals = " vs ".join(f"{s}={v:,.0f}" for s, v in f.values.items())
            st.markdown(f"- **{f.field}**: {vals}  (Δ {f.max_rel_diff_pct:.0f}%)")

    # Quality badge folded with reconciliation
    base_quality = {"level": "good", "warnings": []}
    merged = data_quality_agent(base_quality, report)
    badge = {"good": "🟢 good", "partial": "🟡 partial", "poor": "🔴 poor"}.get(merged["level"], merged["level"])
    st.subheader("Badge de calidad (con verificación cruzada)")
    st.markdown(f"**Nivel:** {badge}")
    for w in merged.get("warnings", []):
        st.caption(f"• {w}")
