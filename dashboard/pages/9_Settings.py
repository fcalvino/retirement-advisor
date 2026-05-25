"""Settings — stock universe, watchlist, AI configuration and cache."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from dashboard.shared import _save_ai_config_to_env
from data.cache import cache
from data.preferences import UserPreferences

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("⚙️ Settings")  # noqa: RUF001

_prefs: UserPreferences = st.session_state.user_prefs

# ------------------------------------------------------------------ #
#  Stock Universe                                                     #
# ------------------------------------------------------------------ #

st.subheader("Stock Universe")
universe_text = st.text_area(
    "Tickers (one per line or comma-separated)",
    value="\n".join(st.session_state.universe),
    height=200,
)
col_save, col_restore = st.columns(2)
with col_save:
    if st.button("Save Universe"):
        raw = universe_text.replace(",", "\n").split()
        st.session_state.universe = [t.upper().strip() for t in raw if t.strip()]
        _prefs.last_used_universe = list(st.session_state.universe)
        _prefs.save()
        st.toast(f"Universo guardado: {len(st.session_state.universe)} tickers", icon="✅")
with col_restore:
    if _prefs.favorite_universe and st.button(
        "↩ Restaurar favorito",
        help=f"{len(_prefs.favorite_universe)} tickers guardados",
    ):
        st.session_state.universe = list(_prefs.favorite_universe)
        st.toast(f"Universo favorito restaurado: {len(_prefs.favorite_universe)} tickers", icon="↩")
        st.rerun()

st.divider()

# ------------------------------------------------------------------ #
#  Watchlist                                                          #
# ------------------------------------------------------------------ #

st.subheader("📌 Watchlist")
watched_text = st.text_area(
    "Tickers a seguir (uno por línea)",
    value="\n".join(_prefs.watched_tickers),
    height=100,
    help="Tickers que querés monitorear de cerca. Se guardan automáticamente.",
)
if st.button("Guardar Watchlist"):
    raw_w = watched_text.replace(",", "\n").split()
    _prefs.watched_tickers = [t.upper().strip() for t in raw_w if t.strip()]
    _prefs.save()
    st.toast(f"Watchlist guardada: {len(_prefs.watched_tickers)} tickers", icon="📌")

st.divider()

# ------------------------------------------------------------------ #
#  AI Analysis                                                        #
# ------------------------------------------------------------------ #

st.subheader("🤖 AI Analysis")
st.caption("Activá un modelo de AI para reemplazar el scoring rule-based con análisis cualitativo.")

_MODEL_OPTIONS = {
    "Claude (Anthropic)":              ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"],
    "GPT-4o (OpenAI)":                 ["gpt-4o", "gpt-4o-mini"],
    "xAI / Grok (via Hermes OAuth)":   ["grok-4.3", "grok-4.20-0309-non-reasoning", "grok-4.20-0309-reasoning", "grok-build-0.1"],
    "Hermes / Nous Research":          ["nousresearch/hermes-4-70b", "nousresearch/hermes-4-405b", "openrouter/owl-alpha"],
}
_PROVIDER_KEY_TO_LABEL = {
    "claude": "Claude (Anthropic)",
    "openai": "GPT-4o (OpenAI)",
    "xai":    "xAI / Grok (via Hermes OAuth)",
    "nous":   "Hermes / Nous Research",
}

current_provider      = st.session_state.get("ai_provider", "claude")
default_provider_label = _PROVIDER_KEY_TO_LABEL.get(current_provider, "Claude (Anthropic)")
provider_label = st.selectbox(
    "Proveedor",
    list(_MODEL_OPTIONS.keys()),
    index=list(_MODEL_OPTIONS.keys()).index(default_provider_label),
)

if "Claude" in provider_label:
    provider_key = "claude"
elif "xAI" in provider_label or "Grok" in provider_label:
    provider_key = "xai"
elif "Nous" in provider_label or "Hermes" in provider_label:
    provider_key = "nous"
else:
    provider_key = "openai"

model_list    = _MODEL_OPTIONS[provider_label]
current_model = st.session_state.get("ai_model", model_list[0])
model_index   = model_list.index(current_model) if current_model in model_list else 0
ai_model_sel  = st.selectbox("Modelo", model_list, index=model_index)

if provider_key in ("nous", "xai"):
    st.info("🔐 Usa tu sesión local de Hermes OAuth. La API key es opcional.")
    st.session_state.ai_enabled = True

ai_key_input = st.text_input(
    "API Key" + (" (opcional para Hermes)" if provider_key == "nous" else ""),
    type="password",
    value=st.session_state.get("ai_api_key", ""),
    placeholder="sk-ant-... / sk-... / dejar vacío si usás hermes login",
)
use_in_screener = st.toggle(
    "Usar AI también en el Screener",
    value=st.session_state.get("ai_use_in_screener", False),
    help="Desactivado por defecto. El Screener usa scoring rule-based (rápido y sin costo).",
)
if use_in_screener:
    n = len(st.session_state.get("universe", []))
    st.warning(
        f"⚠️ Activar AI en el Screener hará **{n} llamadas al API** por cada refresh "
        f"(~{n * 2}–{n * 5} segundos y costo real de tokens). "
        "Recomendado solo para universos pequeños (<10 tickers)."
    )

ai_enabled_now = st.session_state.get("ai_enabled", False)
st.caption(
    f"Estado actual: {'🟢 AI activo' if ai_enabled_now else '⚪ Usando scoring clásico'} "
    f"| Screener: {'🤖 AI' if use_in_screener else '⚡ Rule-based'}"
)

if st.button("Guardar configuración AI", type="primary"):
    prev_provider = st.session_state.get("ai_provider", "")
    prev_model    = st.session_state.get("ai_model",    "")

    st.session_state.ai_provider        = provider_key
    st.session_state.ai_model           = ai_model_sel
    st.session_state.ai_api_key         = ai_key_input
    st.session_state.ai_use_in_screener = use_in_screener

    ai_on = bool(ai_key_input.strip()) or provider_key in ("nous", "xai")
    st.session_state.ai_enabled = ai_on

    _save_ai_config_to_env(provider_key, ai_model_sel, ai_key_input, ai_on, use_in_screener)

    if provider_key != prev_provider or ai_model_sel != prev_model:
        st.cache_data.clear()

    if provider_key == "xai":
        st.success(f"✅ AI activado — {ai_model_sel} vía xAI OAuth (Hermes).")
    elif provider_key == "nous":
        st.success(f"✅ AI activado — {ai_model_sel} vía Hermes (sesión local).")
    elif ai_key_input.strip():
        st.success(f"✅ AI activado — {ai_model_sel}.")
    else:
        st.info("API Key vacía — se usará el scoring clásico.")

st.divider()

# ------------------------------------------------------------------ #
#  Cache                                                              #
# ------------------------------------------------------------------ #

st.subheader("Cache")
col1, col2 = st.columns(2)
with col1:
    if st.button("Clear All Cache", type="secondary"):
        cache.clear_all()
        st.cache_data.clear()
        st.success("Cache cleared — next analysis will re-fetch all data")
with col2:
    st.caption("Cache stores fetched data for 24h to avoid API rate limits.")

st.divider()
st.caption(
    "Retirement Advisor v1.0.0 — datos de Yahoo Finance (yfinance). "
    "No constituye asesoramiento financiero."
)
