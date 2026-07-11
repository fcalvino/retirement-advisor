"""Chat — "Hablá con tu plan": asesor conversacional con tool-calling (Fase 4)."""

from __future__ import annotations

import streamlit as st
from loguru import logger

from config import CHAT
from dashboard.shared import AI_BADGE, _get_ai_config

st.title("💬 Hablá con tu plan")
st.caption(
    "Preguntá en lenguaje natural (\"¿conviene comprar AAPL?\", \"¿cómo viene mi plan?\", "
    "\"¿me alcanza si me jubilo en 15 años?\") y el asesor elige la herramienta correcta, "
    "corre el cálculo real y te responde. Nunca inventa cifras: siempre podés ver el dato crudo."
)

if not CHAT.enabled:
    st.warning("El chat está desactivado en config (`CHAT.enabled`).")
    st.stop()

ai_cfg = _get_ai_config()
if not getattr(ai_cfg, "enabled", False):
    st.warning("El chat necesita la IA habilitada. Activala en **Settings** y elegí un proveedor.")
    st.stop()

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []  # list of {role, content, data}

# Replay history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            st.caption(f"{AI_BADGE} · respuesta en palabras; el dato duro está abajo")
        if msg.get("data") and CHAT.show_raw_data:
            with st.expander("📊 Calculado · dato crudo usado (sin inventar)"):
                st.json(msg["data"])
        if msg.get("tool") and msg["tool"] != "none":
            st.caption(f"Herramienta: `{msg['tool']}`")

# Suggested clickable questions when the conversation is empty — a blank chat
# paralyses; examples teach what can be asked.
_SUGGESTED = [
    "¿Conviene comprar AAPL?",
    "¿Cómo viene mi plan?",
    "¿Me alcanza si me jubilo en 15 años?",
    "¿Qué riesgos tiene mi cartera?",
]
if not st.session_state.chat_history:
    st.markdown("**Probá con una de estas preguntas:**")
    _sug_cols = st.columns(2)
    for _i, _q in enumerate(_SUGGESTED):
        if _sug_cols[_i % 2].button(_q, key=f"chat_sug_{_i}", width="stretch"):
            st.session_state["_chat_pending"] = _q
            st.rerun()

prompt = st.chat_input("Preguntá sobre una acción, tu plan o una proyección…")
if not prompt and st.session_state.get("_chat_pending"):
    prompt = st.session_state.pop("_chat_pending")
if prompt:
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Pensando y corriendo los cálculos…"):
            try:
                from analysis.chat_agent import ChatAgent

                resp = ChatAgent(ai_config=ai_cfg).ask(prompt)
            except Exception as exc:  # pragma: no cover - UI guard
                logger.error(f"chat page: failed — {exc}")
                st.error(f"No pude procesar la consulta: {exc}")
                st.stop()

        st.markdown(resp.answer)
        st.caption(f"{AI_BADGE} · respuesta en palabras; el dato duro está abajo")
        if resp.data and CHAT.show_raw_data:
            with st.expander("📊 Calculado · dato crudo usado (sin inventar)"):
                st.json(resp.data)
        if resp.tool_used and resp.tool_used != "none":
            st.caption(f"Herramienta: `{resp.tool_used}`")

    st.session_state.chat_history.append({
        "role": "assistant", "content": resp.answer,
        "data": resp.data, "tool": resp.tool_used,
    })
