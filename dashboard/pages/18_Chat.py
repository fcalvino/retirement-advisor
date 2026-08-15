"""Chat — "Hablá con tu plan": asesor conversacional con tool-calling (Fase 4)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from loguru import logger

from config import CHAT
from dashboard.shared import AI_BADGE, CALC_BADGE, _get_ai_config, get_user_prefs
from data.product_ux import (
    chat_missing_context_message,
    chat_suggested_questions,
    guided_empty_state,
)

st.title("💬 Hablá con tu plan")
st.caption(
    "Preguntá en lenguaje natural y el asesor elige la herramienta correcta, "
    "corre el cálculo real y te responde. Nunca inventa cifras: siempre podés ver el dato crudo."
)

# Research experience deep-links (backlog 6)
_rl1, _rl2 = st.columns(2)
if _rl1.button("🔍 Abrir ficha (Stock Analysis)", key="chat_to_sa", width="stretch"):
    st.switch_page(str(Path(__file__).parent / "2_Stock_Analysis.py"))
if _rl2.button("🏛️ Convocar comité", key="chat_to_comite", width="stretch"):
    st.switch_page(str(Path(__file__).parent / "15_Comite.py"))

if not CHAT.enabled:
    st.warning("El chat está desactivado en config (`CHAT.enabled`).")
    st.stop()

ai_cfg = _get_ai_config()
if not getattr(ai_cfg, "enabled", False):
    st.warning("El chat necesita la IA habilitada. Activala en **Settings** y elegí un proveedor.")
    st.stop()

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []  # list of {role, content, data}

_prefs = get_user_prefs()
_has_plan = bool((getattr(_prefs, "active_plan_id", "") or "").strip())
try:
    _has_portfolio = bool(getattr(st.session_state.get("portfolio"), "positions", None))
except Exception:
    _has_portfolio = False

_ctx_tip = chat_missing_context_message(
    has_active_plan=_has_plan, has_goal_target=True, tool_name=""
)
if _ctx_tip:
    st.info(_ctx_tip, icon="💡")

# Replay history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            st.caption(f"{AI_BADGE} · respuesta en palabras; el dato duro es {CALC_BADGE}")
        if msg.get("data") and CHAT.show_raw_data:
            with st.expander("📊 Calculado · dato crudo usado (sin inventar)"):
                st.json(msg["data"])
        if msg.get("tool") and msg["tool"] != "none":
            st.caption(f"Herramienta: `{msg['tool']}`")

# Suggested clickable questions (backlog 5)
_SUGGESTED = chat_suggested_questions(
    has_active_plan=_has_plan, has_portfolio=_has_portfolio
)
if not st.session_state.chat_history:
    _es = guided_empty_state("chat")
    st.markdown(f"**{_es['title']}** — {_es['body']}")
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

        # Human messages when tools report missing plan/meta (never raw misleading 0%).
        _tool = getattr(resp, "tool_used", "") or ""
        _data = getattr(resp, "data", None) or {}
        _human = None
        if isinstance(_data, dict) and not _data.get("ok", True):
            _err = str(_data.get("error") or "")
            if "plan" in _err.lower():
                _human = chat_missing_context_message(
                    has_active_plan=False, has_goal_target=False, tool_name=_tool or "plan_status"
                )
        if isinstance(_data, dict) and _data.get("prob_achieve_target_pct_available") is False:
            _human = chat_missing_context_message(
                has_active_plan=True, has_goal_target=False, tool_name="retirement_projection"
            )
        if _human:
            st.info(_human, icon="🧭")
        st.markdown(resp.answer)
        st.caption(f"{AI_BADGE} · respuesta en palabras; el dato duro es {CALC_BADGE}")
        if resp.data and CHAT.show_raw_data:
            with st.expander("📊 Calculado · dato crudo usado (sin inventar)"):
                st.json(resp.data)
        if resp.tool_used and resp.tool_used != "none":
            st.caption(f"Herramienta: `{resp.tool_used}`")

    st.session_state.chat_history.append({
        "role": "assistant", "content": resp.answer,
        "data": resp.data, "tool": resp.tool_used,
    })
