"""Macro RAG — contexto macro fechado para anclar los prompts (Fase 3B)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from loguru import logger

from analysis.macro_rag import (
    example_macro_docs,
    ingest_from_fred,
    is_pinned_doc,
    is_seed_doc,
    macro_rag_store,
)
from config import MACRO_RAG, MULTI_SOURCE

st.title("🧭 Macro RAG")
st.caption(
    "En vez de pedirle a la IA que use su “conocimiento macro actual” (memoria de entrenamiento, "
    "potencialmente vieja o inventada), indexamos hechos macro **fechados** y le inyectamos los "
    "más relevantes como contexto fresco. Así el análisis macro queda anclado a hechos verificables."
)

n = macro_rag_store.count()
st.metric("Documentos macro indexados", n)

col1, col2 = st.columns(2)
with col1:
    if st.button("🌱 Cargar set de ejemplo (offline)"):
        added = macro_rag_store.ingest_many(example_macro_docs())
        st.success(
            f"Listo: {added} documentos de ejemplo cargados. Son texto de demo: sirven "
            "para ver esta página, pero no llegan a ningún prompt."
        )
        st.rerun()
with col2:
    fred_label = "📡 Ingerir desde FRED" + ("" if MULTI_SOURCE.fred_api_key else " (requiere clave)")
    if st.button(fred_label, disabled=not MULTI_SOURCE.fred_api_key):
        with st.spinner("Consultando FRED…"):
            added = ingest_from_fred(macro_rag_store)
        st.success(f"Ingeridos {added} documentos desde FRED.") if added else st.warning(
            "No se pudo ingerir desde FRED (sin datos o sin clave)."
        )
        st.rerun()

if n:
    if st.button("🗑️ Vaciar índice"):
        macro_rag_store.clear()
        st.rerun()

st.divider()

def _reaches_prompt(d) -> str:
    if is_seed_doc(d):
        return "no — ejemplo"
    if is_pinned_doc(d):
        return "sí, siempre (si está fresco)"
    return "si la consulta lo recupera (y está fresco)"


# Indexed docs
docs = macro_rag_store.all_docs()
if docs:
    st.subheader("Documentos indexados")
    st.dataframe(
        pd.DataFrame([
            {"Fecha": d.as_of or "s/f", "Título": d.title, "Fuente": d.source,
             "Tags": ", ".join(d.tags),
             "Llega al prompt": _reaches_prompt(d)}
            for d in docs
        ]),
        hide_index=True,
        use_container_width=True,
    )

# Retrieval tester
st.subheader("🔎 Probar recuperación")
query = st.text_input("Consulta (ej. 'tecnología tasas valuación' o 'argentina riesgo país')",
                      value="tecnología tasas valuación")
if st.button("Recuperar contexto") and query:
    try:
        hits = macro_rag_store.retrieve(query, k=MACRO_RAG.top_k)
    except Exception as exc:  # pragma: no cover - UI guard
        logger.error(f"macro rag page: retrieve failed — {exc}")
        st.error(f"Error al recuperar: {exc}")
        hits = []
    if not hits:
        st.info(
            "Sin resultados relevantes: ¿hay documentos reales (los de ejemplo no cuentan) "
            "dentro de la ventana de frescura?"
        )
    for doc, score in hits:
        st.markdown(f"**{doc.as_of or 's/f'} · {doc.title}**  _(score {score:.3f})_")
        st.caption(f"{doc.source} — {doc.body}")

    st.divider()
    st.markdown("**Bloque que se inyecta a los prompts (Estratega Macro y Analista Fundamental):**")
    st.code(
        macro_rag_store.build_context(query)
        or "(vacío — sin hechos macro reales, el Estratega Macro se abstiene)",
        language="text",
    )
