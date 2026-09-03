"""Settings — stock universe, watchlist, AI configuration and cache."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import ar_fx_from_market
from dashboard.shared import (
    _save_ai_config_to_env,
    cache_stats,
    clear_data_cache,
    usd_ars_quote,
)
from data.preferences import UserPreferences
from data.universe_loader import UNIVERSE_META, load_universe

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("⚙️ Configuración")  # noqa: RUF001

# Defensive guard for direct navigation
if "user_prefs" not in st.session_state:
    st.warning("Por favor empezá desde la página **Inicio** para inicializar correctamente la aplicación.")
    st.stop()

_prefs: UserPreferences = st.session_state.user_prefs

# ------------------------------------------------------------------ #
#  Mi Perfil (onboarding — Fase A)                                    #
# ------------------------------------------------------------------ #

from dashboard.onboarding import render_onboarding_wizard, render_profile_summary

st.subheader("🧭 Mi Perfil de retiro")
st.caption(
    "Tus datos personales alimentan los valores por defecto del Optimizer "
    "(perfil + capital), las Simulaciones (horizonte + capital inicial) y la Asignación."
)
if _prefs.is_onboarded:
    render_profile_summary(_prefs)
    st.markdown("")
    with st.expander("✏️ Editar mi perfil"):
        if render_onboarding_wizard(key_prefix="settings_onb"):
            st.rerun()
else:
    if render_onboarding_wizard(key_prefix="settings_onb"):
        st.rerun()

st.divider()

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
#  Custom tickers (Item 3) — extend the universe with warnings        #
# ------------------------------------------------------------------ #

st.subheader("🧪 Tickers personalizados")
st.caption(
    "Agregá acciones/ADRs/ETFs que te importan y no están en el universo curado "
    "(ej. **VIST** por Vaca Muerta). Se integran al Screener, Optimizer y Plan, "
    "pero con **advertencias fuertes**: su scoring puede ser parcial/pobre y su "
    "calidad de datos se marca como *Custom*. El universo curado sigue siendo la "
    "fuente confiable; estos son experimentales."
)
_ct1, _ct2 = st.columns([2, 3])
with _ct1:
    _new_sym = st.text_input("Ticker", key="custom_ticker_symbol", placeholder="VIST")
with _ct2:
    _new_note = st.text_input("Nota (opcional)", key="custom_ticker_note", placeholder="Tesis Vaca Muerta")
if st.button("➕ Agregar (con advertencias)", key="add_custom_ticker_btn"):
    if _prefs.add_custom_ticker(_new_sym, _new_note):
        # Re-merge into the live universe so it shows up immediately.
        from dashboard.shared import load_universe_with_customs
        _ak = st.session_state.get("active_universe_key", getattr(_prefs, "active_universe", "default") or "default")
        st.session_state.universe = load_universe_with_customs(_ak, _prefs)
        st.toast(f"Ticker personalizado agregado: {_new_sym.upper().strip()}", icon="🧪")
        st.rerun()
    else:
        st.warning("Ticker inválido o ya existente. Usá 1-12 caracteres (letras, números, '.', '-').")

if _prefs.custom_tickers:
    st.markdown("**Tus tickers personalizados:**")
    for _c in _prefs.custom_tickers:
        _csym = _c.get("symbol", "")
        _r1, _r2 = st.columns([5, 1])
        with _r1:
            _note = f" — {_c.get('note')}" if _c.get("note") else ""
            st.caption(f"⚠️ **{_csym}** (Custom · calidad de datos parcial){_note} · agregado {_c.get('added_at', '')}")
        with _r2:
            if st.button("🗑️", key=f"del_custom_{_csym}", help=f"Quitar {_csym}"):
                _prefs.remove_custom_ticker(_csym)
                from dashboard.shared import load_universe_with_customs
                _ak = st.session_state.get("active_universe_key", getattr(_prefs, "active_universe", "default") or "default")
                st.session_state.universe = load_universe_with_customs(_ak, _prefs)
                st.toast(f"Ticker personalizado quitado: {_csym}", icon="🗑️")
                st.rerun()
else:
    st.caption("Todavía no agregaste tickers personalizados.")

# Item 3 — data snapshot export (backup / offline reproducibility).
with st.expander("💾 Exportar snapshot de datos del universo (backup/offline)", expanded=False):
    st.caption(
        "Guardá un JSON con el último precio y datos clave del universo activo. "
        "Sirve como respaldo y para reproducir el análisis offline (dentro del TTL "
        "del cache) si yfinance falla."
    )
    if st.button("📸 Generar snapshot del universo activo", key="snapshot_btn"):
        from dashboard.shared import plan_price_lookup
        from data.fetcher import get_info
        from data.snapshot import export_universe_data_snapshot, snapshot_to_bytes
        with st.spinner("Capturando datos del universo…"):
            _snap = export_universe_data_snapshot(
                list(st.session_state.universe),
                info_lookup=get_info, price_lookup=plan_price_lookup,
            )
        st.session_state["_universe_snapshot_bytes"] = snapshot_to_bytes(_snap)
        st.session_state["_universe_snapshot_n"] = _snap["n_tickers"]
    if st.session_state.get("_universe_snapshot_bytes"):
        import datetime as _dt
        st.download_button(
            f"📥 Descargar snapshot ({st.session_state.get('_universe_snapshot_n', 0)} tickers)",
            data=st.session_state["_universe_snapshot_bytes"],
            file_name=f"universe_snapshot_{_dt.date.today().isoformat()}.json",
            mime="application/json", key="snapshot_dl",
        )

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
#  Cotización del peso (N1)                                           #
# ------------------------------------------------------------------ #

st.subheader("💵 Cotización del peso")
st.caption(
    "El **oficial** se toma del mercado (`ARS=X`) con la misma caché que el resto "
    "de los precios. El **paralelo** no tiene una fuente gratuita, así que lo "
    "ponés vos — y la app lo muestra como tuyo, no como una cotización."
)

_fx_now = ar_fx_from_market(
    quote_lookup=usd_ars_quote,
    usd_ars_parallel=(_prefs.usd_ars_parallel or None),
    parallel_asof=_prefs.usd_ars_parallel_asof,
)
_fc1, _fc2 = st.columns(2)
_fc1.metric(
    "Oficial (pesos/USD)", f"${_fx_now.usd_ars_oficial:,.0f}",
    help=(
        "Origen: **market** — cotizado de `ARS=X`."
        if _fx_now.source_oficial == "market"
        else "Origen: **placeholder** — no se pudo cotizar, así que es un valor de "
             "referencia inventado, no un dato."
    ),
)
_par_actual = float(_prefs.usd_ars_parallel or 0.0)
_par_nuevo = _fc2.number_input(
    "Paralelo (pesos/USD) — 0 = sin cargar",
    min_value=0.0, max_value=1_000_000.0, step=50.0,
    value=_par_actual, format="%.0f", key="usd_ars_parallel_input",
    help="El que vos observás. Con 0 la app no muestra brecha, porque una brecha "
         "contra un valor por defecto no dice nada del mercado.",
)
if st.button("Guardar cotización", key="save_usd_ars_parallel"):
    _prefs.usd_ars_parallel = float(_par_nuevo)
    _prefs.usd_ars_parallel_asof = (
        datetime.now().date().isoformat() if _par_nuevo > 0 else ""
    )
    _prefs.save()
    st.success("Cotización guardada." if _par_nuevo > 0 else "Paralelo borrado.")
    st.rerun()

if _fx_now.rate_source == "placeholder":
    st.info(
        "La **brecha** no se muestra hasta que las dos cotizaciones tengan origen: "
        "restar dos números inventados —o uno real y uno inventado— no describe "
        "al mercado.",
        icon="ℹ️",
    )
else:
    st.caption(
        f"Brecha actual: **{(_fx_now.usd_ars_parallel / _fx_now.usd_ars_oficial - 1) * 100:+.1f}%** "
        f"· oficial *{_fx_now.source_oficial}* · paralelo *{_fx_now.source_parallel}*"
        + (f" · {_fx_now.rate_asof}" if _fx_now.rate_asof else "")
    )

# ------------------------------------------------------------------ #
#  Caché                                                              #
# ------------------------------------------------------------------ #

st.subheader("🗄️ Caché")
st.caption("Almacena respuestas de Yahoo Finance para reducir llamadas a la API y acelerar el análisis.")

_stats = cache_stats()
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
        clear_data_cache()
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
    with st.popover("🔴 Resetear a defaults", width="stretch"):
        st.warning(
            "**¿Confirmar reset?**\n\n"
            "Se restablecerán:\n"
            "- Universo activo → **Default** (38 tickers)\n"
            "- Perfil del Optimizer → **Conservador**\n"
            "- AI en el Screener → **desactivado**\n"
            "- Mi Perfil de retiro (edad, capital, metas) → **sin definir**\n\n"
            "La Watchlist y las alertas de precio **no se modifican**.",
            icon="⚠️",
        )
        if st.button("✅ Sí, resetear preferencias", type="primary", width="stretch"):
            # Reset UserPreferences fields
            _prefs.active_universe        = "default"
            _prefs.default_profile        = "Conservador"
            _prefs.ai_enabled_in_screener = False
            _prefs.preferred_currency     = "USD"
            _prefs.last_used_universe     = []
            # Personal profile (onboarding) reset
            _prefs.onboarded            = False
            _prefs.age                  = 0
            _prefs.retirement_age       = 65
            _prefs.current_capital      = 0.0
            _prefs.monthly_savings      = 0.0
            _prefs.risk_tolerance       = "conservadora"
            _prefs.primary_goal_type    = "retiro"
            _prefs.dividend_preference  = "balance"
            _prefs.save()
            st.session_state.pop("_profile_defaults_seeded", None)

            # Sync session_state: universe
            _default_tickers = load_universe("default")
            st.session_state.universe          = _default_tickers
            st.session_state.active_universe_key = "default"

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

# ------------------------------------------------------------------ #
#  Modo desarrollador                                                 #
# ------------------------------------------------------------------ #

st.subheader("🛠️ Modo desarrollador")
st.caption(
    "Muestra las herramientas técnicas en el menú: **Eval IA**, **Calidad de Datos** "
    "y **Macro RAG**. Están pensadas para diagnóstico, no para el uso diario."
)
_dev_on = st.toggle(
    "Mostrar herramientas de desarrollo en el menú",
    value=bool(st.session_state.get("dev_mode", False)),
    help="También se puede activar con la variable de entorno DEV_MODE.",
)
if _dev_on != bool(st.session_state.get("dev_mode", False)):
    st.session_state["dev_mode"] = _dev_on
    st.rerun()

st.divider()
st.caption(
    "Retirement Advisor v1.1.0 — datos de Yahoo Finance (yfinance). "
    "No constituye asesoramiento financiero."
)
