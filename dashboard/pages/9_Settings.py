"""Settings — stock universe, watchlist, AI configuration and cache."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from dashboard.shared import _save_ai_config_to_env
from data.cache import cache
from data.preferences import UserPreferences
from data.universe_loader import UNIVERSE_META, load_universe

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("⚙️ Configuración")  # noqa: RUF001

_prefs: UserPreferences = st.session_state.user_prefs

# ------------------------------------------------------------------ #
#  Universo personalizado                                             #
# ------------------------------------------------------------------ #

st.subheader("🗂️ Universo personalizado")
st.caption(
    "Editá manualmente los tickers del universo activo. "
    "Para cambiar entre universos predefinidos (Default, Dividend Focus, etc.) "
    "usá el **selector en el sidebar izquierdo**, visible en todas las páginas."
)
universe_text = st.text_area(
    "Tickers (uno por línea o separados por comas)",
    value="\n".join(st.session_state.universe),
    height=200,
)
col_save, col_restore = st.columns(2)
with col_save:
    if st.button("💾 Guardar cambios"):
        raw = universe_text.replace(",", "\n").split()
        st.session_state.universe = [t.upper().strip() for t in raw if t.strip()]
        _prefs.last_used_universe = list(st.session_state.universe)
        _prefs.save()
        st.toast(f"Universo guardado: {len(st.session_state.universe)} tickers", icon="✅")
with col_restore:
    if _prefs.favorite_universe and st.button(
        "↩️ Restaurar favorito",
        help=f"{len(_prefs.favorite_universe)} tickers guardados como favorito",
    ):
        st.session_state.universe = list(_prefs.favorite_universe)
        st.toast(f"Universo favorito restaurado: {len(_prefs.favorite_universe)} tickers", icon="↩️")
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
if st.button("💾 Guardar watchlist"):
    raw_w = watched_text.replace(",", "\n").split()
    _prefs.watched_tickers = [t.upper().strip() for t in raw_w if t.strip()]
    _prefs.save()
    st.toast(f"Watchlist guardada: {len(_prefs.watched_tickers)} tickers", icon="📌")

st.divider()

# ------------------------------------------------------------------ #
#  AI Analysis                                                        #
# ------------------------------------------------------------------ #

st.subheader("🤖 Análisis con AI")
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
#  Caché                                                              #
# ------------------------------------------------------------------ #

st.subheader("🗄️ Caché")
st.caption("Almacena respuestas de Yahoo Finance para reducir llamadas a la API y acelerar el análisis.")

_stats = cache.get_stats()
_cs1, _cs2, _cs3, _cs4 = st.columns(4)
_cs1.metric("Entradas válidas",   _stats["valid"])
_cs2.metric("Entradas expiradas", _stats["expired"])
_cs3.metric("Tamaño DB",          f"{_stats['db_size_mb']} MB")
_cs4.metric("TTL configurado",    f"{_stats['ttl_hours']}h")

if _stats["newest"]:
    _newest_str = _stats["newest"].strftime("%d/%m %H:%M")
    _oldest_str = _stats["oldest"].strftime("%d/%m %H:%M") if _stats["oldest"] else "—"
    st.caption(f"Entrada más reciente: **{_newest_str}** · Entrada más antigua: **{_oldest_str}** (UTC)")

_cc1, _cc2 = st.columns(2)
with _cc1:
    if st.button("🗑️ Limpiar todo el caché", type="secondary"):
        cache.clear_all()
        st.cache_data.clear()
        st.success("✅ Caché limpiado — el próximo análisis va a re-obtener todos los datos.")
        st.rerun()
with _cc2:
    st.caption(
        f"El caché expira automáticamente a las **{_stats['ttl_hours']} horas**. "
        "Limpiar es útil si los datos parecen desactualizados."
    )

st.divider()

# ------------------------------------------------------------------ #
#  Preferencias — Reset a valores predeterminados                     #
# ------------------------------------------------------------------ #

st.subheader("🔄 Preferencias")
st.caption(
    "Restablece las preferencias del sistema a sus valores predeterminados. "
    "**No afecta la Watchlist ni las alertas de precio.**"
)

_r1, _r2 = st.columns([1, 2])
with _r1:
    with st.popover("🔴 Resetear a defaults", use_container_width=True):
        st.warning(
            "**¿Confirmar reset?**\n\n"
            "Se restablecerán:\n"
            "- Universo activo → **Default** (38 tickers)\n"
            "- Perfil del Optimizer → **Conservador**\n"
            "- AI en el Screener → **desactivado**\n\n"
            "La Watchlist y las alertas de precio **no se modifican**.",
            icon="⚠️",
        )
        if st.button("✅ Sí, resetear preferencias", type="primary", use_container_width=True):
            # Reset UserPreferences fields
            _prefs.active_universe        = "default"
            _prefs.default_profile        = "Conservador"
            _prefs.ai_enabled_in_screener = False
            _prefs.preferred_currency     = "USD"
            _prefs.last_used_universe     = []
            _prefs.save()

            # Sync session_state: universe
            _default_tickers = load_universe("default")
            st.session_state.universe          = _default_tickers
            st.session_state.active_universe_key = "default"

            # Sync sidebar universe selectbox key
            _default_label = f"{UNIVERSE_META['default']['name']} ({UNIVERSE_META['default']['count']})"
            st.session_state["sidebar_universe_selector"] = _default_label

            # Sync Optimizer profile
            st.session_state["optimizer_profile_label"]   = "🛡️  Conservador"
            st.session_state.optimizer_last_saved_profile = "Conservador"

            # Clear optimizer + screener caches
            for _k in [
                "optimizer_scored", "optimizer_universe",
                "optimizer_result", "optimizer_result_key",
                "optimizer_prev_result", "optimizer_prev_result_key",
                "optimizer_comparison_results", "optimizer_comparison_profile",
            ]:
                st.session_state.pop(_k, None)
            st.cache_data.clear()

            st.toast("✅ Preferencias restablecidas a valores predeterminados", icon="🔄")
            st.rerun()

with _r2:
    st.caption(
        f"Universo activo: **{UNIVERSE_META.get(st.session_state.get('active_universe_key', 'default'), {}).get('name', 'Default')}** "
        f"({len(st.session_state.get('universe', []))} tickers) · "
        f"Perfil: **{_prefs.default_profile}** · "
        f"AI Screener: {'🟢 activo' if _prefs.ai_enabled_in_screener else '⚪ inactivo'}"
    )

st.divider()
st.caption(
    "Retirement Advisor v1.1.0 — datos de Yahoo Finance (yfinance). "
    "No constituye asesoramiento financiero."
)
