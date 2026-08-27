"""
Retirement Advisor — Streamlit entry point.

Handles page config, one-time startup validation, shared session_state
initialization, sidebar branding, and multipage navigation.
All page logic lives in dashboard/pages/*.py.
All shared helpers live in dashboard/shared.py.

Run with:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Seed repo root (script dir is dashboard/) then canonicalize via bootstrap.
_sys_root = Path(__file__).resolve().parent.parent
if str(_sys_root) not in sys.path:
    sys.path.insert(0, str(_sys_root))
from bootstrap import ensure_project_root

ensure_project_root()

import streamlit as st
from loguru import logger

from config_validator import log_config_issues, validate_config
from dashboard.shared import (
    _load_env_vars,
    build_home_hub_for_prefs,
    is_dev_mode,
    next_priority_action,
    plan_journey_status,
    render_assumptions_disclaimer,
    seed_session_defaults_from_profile,
    track_record_home_line,
)
from data.preferences import _PREFS_PATH, UserPreferences
from data.universe_loader import UNIVERSE_META, list_universes
from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Production logging                                                  #
# ------------------------------------------------------------------ #

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_PATH = _LOG_DIR / "retirement_advisor.log"


def _ensure_logger() -> None:
    """Idempotent: adds the file sink at most once per Streamlit session."""
    if st.session_state.get("_retirement_logger_configured"):
        return
    for handler_id, handler in list(logger._core.handlers.items()):
        sink = getattr(handler, "_sink", None)
        sink_path = getattr(sink, "_path", None) if sink else None
        if sink_path and str(_LOG_PATH) in str(sink_path):
            logger.remove(handler_id)
    logger.add(
        _LOG_PATH,
        rotation="10 MB",
        retention="7 days",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
        enqueue=True,
    )
    st.session_state["_retirement_logger_configured"] = True


# ------------------------------------------------------------------ #
#  Page config  (must be first Streamlit call)                         #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="Retirement Advisor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

_ensure_logger()

# ------------------------------------------------------------------ #
#  Startup config validation (once per session)                        #
# ------------------------------------------------------------------ #

if "config_validated" not in st.session_state:
    issues = validate_config()
    log_config_issues(issues)
    st.session_state.config_issues = issues
    st.session_state.config_validated = True

# ------------------------------------------------------------------ #
#  Shared session_state initialization                                 #
# ------------------------------------------------------------------ #

if "user_prefs" not in st.session_state or not hasattr(st.session_state.user_prefs, "active_universe"):
    st.session_state.user_prefs = UserPreferences.load()

_prefs: UserPreferences = st.session_state.user_prefs

if "universe" not in st.session_state:
    _saved_key = getattr(_prefs, "active_universe", "default") or "default"
    # Item 3 — merge the user's custom tickers into the active universe.
    from dashboard.shared import load_universe_with_customs
    st.session_state.universe = load_universe_with_customs(_saved_key, _prefs)
    st.session_state.active_universe_key = _saved_key

if "portfolio" not in st.session_state:
    st.session_state.portfolio = Portfolio()

if "ai_provider" not in st.session_state:
    _env = _load_env_vars()
    st.session_state.ai_provider = _env.get("AI_PROVIDER", "claude")
    st.session_state.ai_model = _env.get("AI_MODEL", "claude-sonnet-4-6")
    st.session_state.ai_api_key = _env.get("AI_API_KEY", "")
    st.session_state.ai_enabled = _env.get("AI_ENABLED", "").lower() in ("true", "1", "yes")
    st.session_state.ai_use_in_screener = (
        _prefs.ai_enabled_in_screener
        or _env.get("AI_USE_IN_SCREENER", "false").lower() in ("true", "1", "yes")
    )

# Seed Optimizer/Simulaciones defaults from the personal profile (once per session)
seed_session_defaults_from_profile(_prefs)

# ------------------------------------------------------------------ #
#  Navigation — must be defined before any sidebar content             #
# ------------------------------------------------------------------ #

def _home_page() -> None:
    st.title("📈 Retirement Advisor")

    _u_key  = st.session_state.get("active_universe_key", "default")
    _u_meta = UNIVERSE_META.get(_u_key, {})
    _prefs_home: UserPreferences = st.session_state.user_prefs
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Universo activo", _u_meta.get("name", _u_key))
    col2.metric("Tickers en universo", len(st.session_state.universe))
    col3.metric("Perfil guardado", _prefs_home.default_profile)
    if _prefs_home.is_onboarded:
        col4.metric("Horizonte de retiro", f"{_prefs_home.primary_horizon_years} años")
    else:
        col4.metric("Perfil personal", "sin definir")

    st.divider()

    # ---- Daily hub: how is my plan? + one action + sample plan (backlog 1) ----
    _hub = build_home_hub_for_prefs(_prefs_home)
    _action = _hub.get("primary_action") or next_priority_action(_prefs_home)

    with st.container(border=True):
        st.markdown("### 🗺️ ¿Cómo viene tu plan?")
        if _hub.get("has_plan"):
            st.markdown(f"**Plan activo:** {_hub.get('plan_name') or '—'}")
            _hc1, _hc2, _hc3, _hc4 = st.columns(4)
            _prob = _hub.get("prob_target_pct")
            _hc1.metric(
                "Prob. de alcanzar la meta",
                f"{_prob:.0f}%" if _prob is not None else "—",
                help="Del último guardado del plan (no es un fetch en vivo).",
            )
            _drift = _hub.get("drift_pct")
            _hc2.metric(
                "Desvío vs mercado",
                f"{_drift:+.1f}%" if _drift is not None else "—",
                help="Deriva ponderada del último refresh en Mi Plan. Vacío = todavía no refrescaste.",
            )
            _median = _hub.get("median_terminal")
            _hc3.metric("Resultado mediano", f"${_median:,.0f}" if _median else "—")
            _n_al = int(_hub.get("unread_alerts") or 0)
            _age = _hub.get("data_age_days")
            _hc4.metric(
                "Alertas sin leer",
                str(_n_al),
                delta=("datos nunca refrescados" if _age is None else f"datos hace {_age}d"),
                delta_color="off",
                delta_arrow="off",
            )
            st.caption(
                "📊 Calculado · números del último guardado/refresh. "
                "Para actualizar vs el mercado andá a 🗺️ Mi Plan."
            )
        else:
            st.info(
                _hub.get("empty_reason")
                or "Todavía no tenés un plan activo. Completá el camino o probá un ejemplo.",
                icon="🗺️",
            )
            if _hub.get("sample_plan_available"):
                if st.button(
                    "🎁 Cargar y activar plan de ejemplo (1 clic)",
                    type="primary",
                    key="home_hub_sample",
                ):
                    from dashboard.shared import load_sample_plan_into_store
                    from data.plan_context import activate_plan, list_sample_plans

                    try:
                        _samples = list_sample_plans()
                        _snap = load_sample_plan_into_store(_samples[0]["key"])
                        activate_plan(_snap.id, _prefs_home)
                        st.session_state.user_prefs = _prefs_home
                        st.toast(f"✅ Ejemplo cargado: {_snap.name}", icon="🎁")
                        st.switch_page(str(_pages_dir / "12_Plan.py"))
                    except Exception as exc:
                        st.error(f"No se pudo cargar el ejemplo: {exc}")

        # Track record one-liner (backlog 15)
        _tr_line = _hub.get("track_record_line") or track_record_home_line()
        if _tr_line:
            st.caption(f"📒 {_tr_line}")

    with st.container(border=True):
        st.markdown(f"### {_action.get('icon', '🚀')} Hoy hacé esto")
        _tone = _action.get("tone") or "primary"
        if _tone == "ok":
            st.success(f"**{_action.get('label')}** — {_action.get('hint')}", icon=_action.get("icon", "✅"))
        elif _tone == "warning":
            st.warning(f"**{_action.get('label')}** — {_action.get('hint')}", icon=_action.get("icon", "⚠️"))
        else:
            st.info(f"**{_action.get('label')}** — {_action.get('hint')}", icon=_action.get("icon", "ℹ️"))
        if _action.get("page"):
            if st.button(f"➡️ {_action.get('label')}", type="primary", key="home_today_action"):
                st.switch_page(str(_pages_dir / _action["page"]))

    st.divider()

    # ---- Personal profile: wizard (first run) or summary (onboarded) ----
    from dashboard.onboarding import render_onboarding_wizard, render_profile_summary

    if _prefs_home.is_onboarded:
        with st.expander("🧭 Mi perfil de retiro", expanded=False):
            render_profile_summary(_prefs_home)
            st.caption("Editá estos datos cuando quieras desde **⚙️ Settings → Mi Perfil**.")
    else:
        with st.container(border=True):
            st.markdown("### 🧭 Definí tu perfil de retiro (1 minuto)")
            st.caption(
                "Respondé unas pocas preguntas y el Optimizer, las Simulaciones y la "
                "Asignación se ajustan automáticamente a tu situación. Es opcional — "
                "podés ignorarlo y usar los valores conservadores por defecto."
            )
            if render_onboarding_wizard(key_prefix="home_onb"):
                st.rerun()

    st.divider()

    # ---- Guided journey: from zero to an ACTIVE retirement plan (Fase E) ----
    _steps = plan_journey_status(_prefs_home)
    _n_done = sum(1 for s in _steps if s["done"])
    if _n_done < len(_steps):
        with st.container(border=True):
            st.markdown("### 🚀 Tu camino a un plan de retiro activo")
            st.progress(_n_done / len(_steps), text=f"{_n_done}/{len(_steps)} pasos completados")
            _next_step = next(s for s in _steps if not s["done"])
            for _i, _s in enumerate(_steps, start=1):
                _mark = "✅" if _s["done"] else ("👉" if _s is _next_step else "⬜")
                st.markdown(f"{_mark} **{_i}. {_s['label']}** — {_s['hint']}")
            if _next_step["page"] is not None:
                if st.button(
                    f"➡️ Siguiente paso: {_next_step['label']}",
                    type="primary", key="home_journey_next",
                ):
                    st.switch_page(str(_pages_dir / _next_step["page"]))
            else:
                st.caption("👆 Completá el wizard de perfil de arriba para avanzar.")

            # Let a brand-new user see the whole thing working in one click,
            # without loading their own data first.
            from data.plan_context import list_sample_plans
            _samples = list_sample_plans()
            if _samples:
                st.caption("¿Preferís ver el producto funcionando primero?")
                if st.button(
                    "🎁 Probar con un plan de ejemplo",
                    key="home_try_sample",
                ):
                    from dashboard.shared import load_sample_plan_into_store
                    from data.plan_context import activate_plan
                    try:
                        _snap = load_sample_plan_into_store(_samples[0]["key"])
                        activate_plan(_snap.id, _prefs_home)
                        st.session_state.user_prefs = _prefs_home
                        st.toast(f"✅ Ejemplo cargado y activado: {_snap.name}", icon="🎁")
                        st.switch_page(str(_pages_dir / "12_Plan.py"))
                    except Exception as exc:
                        st.error(f"No se pudo cargar el ejemplo: {exc}")
    else:
        st.success(
            "🎯 Tenés un **plan de retiro activo** — el tracker y las alertas lo monitorean. "
            "Revisalo en 🗺️ Mi Plan o mirá tu alineación en 💼 Portfolio.",
            icon="🚀",
        )
        # Item 2 — once a plan exists, nudge the user to protect it with a backup.
        st.info(
            "💾 **Respaldá tu plan:** exportalo a JSON desde 🗺️ Mi Plan y guardalo en tu "
            "nube/USB para que sobreviva una reinstalación o cambio de máquina.",
            icon="🛟",
        )

    # Item 1 — assumptions transparency, visible from Home.
    render_assumptions_disclaimer()

    st.divider()

    st.markdown("""
### ¿Por dónde empezar? (primera hora)

| Paso | Dónde | Qué lográs |
|---|---|---|
| 1 | **Inicio** / **🎁 plan de ejemplo** | Ver un plan vivo sin cargar datos |
| 2 | **🧭 Perfil** (1 min) | Edad, capital, ahorro, tolerancia |
| 3 | **📈 Optimizer** (+ asignación por edad) | Cartera objetivo según tu riesgo |
| 4 | **🎲 Simulaciones** | ¿Llegás a la meta? palancas si no |
| 5 | **🗺️ Mi Plan** | Guardar, activar, PDF, qué hacer este año |
| 6 | **💼 Portfolio + 🔔 Alertas** | Monitoreo y coach en caídas |
| Alt | **💬 Hablá con tu plan** | Preguntas en castellano con números reales |
| Invest | **Screener → Stock Analysis** (Comité/Chat enlazados) | Research sin perderse en 3 pantallas |
""")

    st.info(
        "💡 **Flujo de retiro recomendado:** "
        "Perfil → Optimizer → Simulaciones → 🗺️ Mi Plan (guardar + activar + respaldar) "
        "→ Portfolio + Alertas. El chat es un atajo a todo el motor.",
        icon="💡",
    )

    with st.expander("🧭 ¿Nuevo aquí? Camino de 5 minutos"):
        st.markdown("""
        1. Tocá **🎁 Cargar plan de ejemplo** arriba (o en Mi Plan).
        2. Mirá **¿cómo viene tu plan?** y **qué hacer este año**.
        3. En **Simulaciones**, revisá realista vs conservador y las palancas si no llegás.
        4. Exportá el **PDF para compartir** y un **respaldo JSON**.
        5. Cuando quieras lo tuyo: perfil → Optimizer → guardar como plan nuevo.
        """)
        st.caption("Valores en USD (con vista ARS opcional en plan/simulaciones). Educativo — no es asesoramiento financiero regulado.")


_pages_dir = Path(__file__).parent / "pages"

# Menu grouped by user intention (not by technical module). Developer/admin
# tools (Eval IA, Calidad de Datos, Macro RAG) only appear when dev mode is on,
# keeping the everyday menu clean — see is_dev_mode().
# Lean everyday menu (backlog 6): Allocation lives inside Optimizer; Comité is
# reachable from Stock Analysis / Chat and listed under Ajustes (not Investigar).
_ajustes_pages = [
    st.Page(str(_pages_dir / "9_Settings.py"), title="Settings", icon="⚙️"),
    st.Page(str(_pages_dir / "10_About.py"),   title="About",    icon="ℹ️"),
    st.Page(str(_pages_dir / "15_Comite.py"),  title="Comité",   icon="🏛️"),
    st.Page(str(_pages_dir / "4_Allocation.py"), title="Allocation (detalle)", icon="📊"),
]
if is_dev_mode():
    _ajustes_pages += [
        st.Page(str(_pages_dir / "14_Eval_IA.py"),       title="Eval IA",          icon="🧪"),
        st.Page(str(_pages_dir / "16_Calidad_Datos.py"), title="Calidad de Datos", icon="🔬"),
        st.Page(str(_pages_dir / "17_Macro_RAG.py"),     title="Macro RAG",        icon="🧭"),
    ]

pg = st.navigation(
    {
        "": [
            st.Page(_home_page, title="Inicio", icon="📈", default=True),
            st.Page(str(_pages_dir / "18_Chat.py"), title="Hablá con tu plan", icon="💬"),
        ],
        "Mi dinero": [
            st.Page(str(_pages_dir / "12_Plan.py"),      title="Mi Plan",    icon="🗺️"),
            st.Page(str(_pages_dir / "3_Portfolio.py"),  title="Portfolio",  icon="💼"),
            st.Page(str(_pages_dir / "5_Optimizer.py"),  title="Optimizer",  icon="📈"),
        ],
        "Investigar": [
            st.Page(str(_pages_dir / "1_Screener.py"),       title="Screener",       icon="🏠"),
            st.Page(str(_pages_dir / "2_Stock_Analysis.py"), title="Stock Analysis", icon="🔍"),
            st.Page(str(_pages_dir / "11_Watchlist.py"),     title="Watchlist",      icon="📋"),
        ],
        "Proyectar": [
            st.Page(str(_pages_dir / "7_Simulaciones.py"), title="Simulaciones", icon="🎲"),
            st.Page(str(_pages_dir / "6_Backtesting.py"),  title="Backtesting",  icon="📉"),
        ],
        "Seguimiento": [
            st.Page(str(_pages_dir / "8_Alertas.py"),        title="Alertas",      icon="🔔"),
            st.Page(str(_pages_dir / "13_Track_Record.py"),  title="Track Record", icon="📒"),
        ],
        "Ajustes": _ajustes_pages,
    }
)

# ------------------------------------------------------------------ #
#  Sidebar branding + universe selector + config warnings              #
# ------------------------------------------------------------------ #

st.sidebar.title("📈 Retirement Advisor")
st.sidebar.caption("Long-term investment decisions for retirement")

# --- Universe selector ------------------------------------------------
_universe_keys   = list_universes()
_universe_labels = {
    k: f"{UNIVERSE_META.get(k, {}).get('name', k)} ({UNIVERSE_META.get(k, {}).get('count', '?')})"
    for k in _universe_keys
}

# Consume pending universe from preset (must happen before widget instantiation)
if "_preset_universe_key" in st.session_state:
    _puk = st.session_state.pop("_preset_universe_key")
    if _puk in _universe_keys:
        from dashboard.shared import load_universe_with_customs
        st.session_state.universe             = load_universe_with_customs(_puk, _prefs)
        st.session_state.active_universe_key  = _puk
        _prefs.active_universe                = _puk
        _prefs.save()
        st.cache_data.clear()

_current_key = st.session_state.get("active_universe_key", getattr(_prefs, "active_universe", "default") or "default")
if _current_key not in _universe_keys:
    _current_key = "default"

_selected_label = st.sidebar.selectbox(
    "Universo",
    options=list(_universe_labels.values()),
    index=_universe_keys.index(_current_key),
    help="Cambiá el universo de análisis. El cambio se aplica inmediatamente a todas las páginas.",
)
_selected_key = _universe_keys[list(_universe_labels.values()).index(_selected_label)]

if _selected_key != _current_key:
    from dashboard.shared import load_universe_with_customs
    st.session_state.universe = load_universe_with_customs(_selected_key, _prefs)
    st.session_state.active_universe_key = _selected_key
    _prefs.active_universe = _selected_key
    _prefs.last_used_universe = list(st.session_state.universe)
    _prefs.save()
    st.cache_data.clear()
    st.rerun()

_meta = UNIVERSE_META.get(_selected_key, {})
if _meta.get("description"):
    st.sidebar.caption(_meta["description"])

st.sidebar.divider()

# --- Config warnings --------------------------------------------------
config_issues = st.session_state.get("config_issues", [])
warnings_msgs = [msg for lvl, msg in config_issues if lvl == "warning"]
error_msgs    = [msg for lvl, msg in config_issues if lvl == "error"]
if error_msgs or warnings_msgs:
    with st.sidebar.expander("⚠️ Configuración", expanded=bool(error_msgs)):
        for msg in error_msgs:
            st.error(msg, icon="🔴")
        for msg in warnings_msgs:
            st.warning(msg, icon="🟡")

if st.session_state.get("prefs_loaded_toast_shown") is None:
    if _PREFS_PATH.exists():
        st.sidebar.caption("✔ Preferencias cargadas")
    st.session_state.prefs_loaded_toast_shown = True

# Watchlist badge — count + triggered alert indicator
_wl = _prefs.watched_tickers
_alerts_triggered = sum(1 for a in _prefs.price_alerts if a.get("triggered"))
if _wl:
    _badge = f"📋 Watchlist: {len(_wl)} ticker{'s' if len(_wl) != 1 else ''}"
    if _alerts_triggered:
        _badge += f" · 🔔 {_alerts_triggered} alerta{'s' if _alerts_triggered != 1 else ''}"
    st.sidebar.caption(_badge)

# Alert badge (Phase 6) — unread alert count, clickeable via link
try:
    from alerts.store import alert_store as _alert_store

    @st.cache_data(ttl=300)
    def _get_unread_count() -> int:
        return _alert_store.get_unread_count()

    _unread = _get_unread_count()
    if _unread > 0:
        st.sidebar.markdown(
            f"[🔴 **{_unread} alerta{'s' if _unread != 1 else ''} sin leer** →](#alertas)",
            unsafe_allow_html=False,
        )
        if st.sidebar.button(
            f"🔔 Ver {_unread} alerta{'s' if _unread != 1 else ''} sin leer",
            key="_sidebar_alert_badge",
            type="primary",
            width="stretch",
        ):
            st.switch_page(str(Path(__file__).parent / "pages" / "8_Alertas.py"))
    else:
        st.sidebar.caption("🔔 Sin alertas pendientes")
except Exception:
    pass

# ------------------------------------------------------------------ #
#  Run selected page                                                   #
# ------------------------------------------------------------------ #

pg.run()
