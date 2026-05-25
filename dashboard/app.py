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

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from loguru import logger

from config import DEFAULT_TICKERS
from config_validator import log_config_issues, validate_config
from dashboard.shared import _load_env_vars
from data.preferences import _PREFS_PATH, UserPreferences
from data.universe_loader import UNIVERSE_META, list_universes, load_universe
from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Production logging                                                  #
# ------------------------------------------------------------------ #

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
logger.add(
    _LOG_DIR / "retirement_advisor.log",
    rotation="10 MB",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
    enqueue=True,
)

# ------------------------------------------------------------------ #
#  Page config  (must be first Streamlit call)                         #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="Retirement Advisor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

if "user_prefs" not in st.session_state:
    st.session_state.user_prefs = UserPreferences.load()

_prefs: UserPreferences = st.session_state.user_prefs

if "universe" not in st.session_state:
    _saved_key = _prefs.active_universe or "default"
    st.session_state.universe = load_universe(_saved_key)
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

# ------------------------------------------------------------------ #
#  Navigation — must be defined before any sidebar content             #
# ------------------------------------------------------------------ #

def _home_page() -> None:
    st.title("📈 Retirement Advisor")

    _u_key  = st.session_state.get("active_universe_key", "default")
    _u_meta = UNIVERSE_META.get(_u_key, {})
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Universo activo", _u_meta.get("name", _u_key))
    col2.metric("Tickers en universo", len(st.session_state.universe))
    col3.metric("Perfil guardado", st.session_state.user_prefs.default_profile)
    col4.metric("Tests", "133 passing")

    st.divider()

    st.markdown("""
### ¿Por dónde empezar?

| Página | ¿Cuándo usarla? |
|---|---|
| **🏠 Screener** | Ver el ranking completo del universo — empezá aquí |
| **🔍 Stock Analysis** | Análisis profundo de un ticker específico |
| **💼 Portfolio** | Ver y gestionar tus posiciones actuales |
| **📊 Allocation** | Recomendación de acciones/bonos/cash según tu edad |
| **📈 Optimizer** | Construir una cartera óptima por perfil de riesgo |
| **📉 Backtesting** | Simular performance histórica de la estrategia |
| **🎲 Simulaciones** | Monte Carlo + Stress Test para proyecciones |
| **🔔 Alertas** | Monitoreo automático y reportes PDF |
| **📋 Watchlist** | Tickers favoritos con alertas de precio en tiempo real |
| **⚙️ Settings** | Configurar universo, AI y preferencias |
""")

    st.info(
        "💡 **Flujo recomendado:** Screener → Stock Analysis → Optimizer → Portfolio",
        icon="💡",
    )


_pages_dir = Path(__file__).parent / "pages"

pg = st.navigation(
    {
        "": [
            st.Page(_home_page, title="Inicio", icon="📈", default=True),
        ],
        "Análisis": [
            st.Page(str(_pages_dir / "1_Screener.py"),       title="Screener",       icon="🏠"),
            st.Page(str(_pages_dir / "2_Stock_Analysis.py"), title="Stock Analysis", icon="🔍"),
        ],
        "Portfolio": [
            st.Page(str(_pages_dir / "3_Portfolio.py"),  title="Portfolio",  icon="💼"),
            st.Page(str(_pages_dir / "4_Allocation.py"), title="Allocation", icon="📊"),
            st.Page(str(_pages_dir / "5_Optimizer.py"),  title="Optimizer",  icon="📈"),
        ],
        "Simulaciones": [
            st.Page(str(_pages_dir / "6_Backtesting.py"),  title="Backtesting",  icon="📉"),
            st.Page(str(_pages_dir / "7_Simulaciones.py"), title="Simulaciones", icon="🎲"),
        ],
        "Alertas": [
            st.Page(str(_pages_dir / "8_Alertas.py"),   title="Alertas",   icon="🔔"),
            st.Page(str(_pages_dir / "11_Watchlist.py"), title="Watchlist", icon="📋"),
        ],
        "Info": [
            st.Page(str(_pages_dir / "9_Settings.py"), title="Settings", icon="⚙️"),
            st.Page(str(_pages_dir / "10_About.py"),   title="About",    icon="ℹ️"),
        ],
    }
)

# ------------------------------------------------------------------ #
#  Sidebar branding + universe selector + config warnings              #
# ------------------------------------------------------------------ #

st.sidebar.title("📈 Retirement Advisor")
st.sidebar.caption("Long-term investment decisions for retirement")

# --- Universe selector ------------------------------------------------
_universe_keys   = list_universes()
_universe_labels = {k: f"{UNIVERSE_META[k]['name']} ({UNIVERSE_META[k]['count']})" for k in _universe_keys}

_current_key = st.session_state.get("active_universe_key", _prefs.active_universe or "default")
if _current_key not in _universe_keys:
    _current_key = "default"

_selected_label = st.sidebar.selectbox(
    "Universo",
    options=list(_universe_labels.values()),
    index=_universe_keys.index(_current_key),
    help="Cambiá el universo de análisis. El cambio se aplica inmediatamente a todas las páginas.",
    key="sidebar_universe_selector",
)
_selected_key = _universe_keys[list(_universe_labels.values()).index(_selected_label)]

if _selected_key != _current_key:
    st.session_state.universe = load_universe(_selected_key)
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

# ------------------------------------------------------------------ #
#  Run selected page                                                   #
# ------------------------------------------------------------------ #

pg.run()
