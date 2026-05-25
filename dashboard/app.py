"""
Retirement Advisor — Streamlit entry point.

This file is intentionally minimal: it only handles page config,
one-time startup validation, and shared session_state initialization.
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
    st.session_state.universe = (
        _prefs.last_used_universe if _prefs.last_used_universe else DEFAULT_TICKERS.copy()
    )

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
#  Sidebar branding + config warnings                                  #
# ------------------------------------------------------------------ #

st.sidebar.title("📈 Retirement Advisor")
st.sidebar.caption("Long-term investment decisions for retirement")

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

# ------------------------------------------------------------------ #
#  Home page content                                                   #
# ------------------------------------------------------------------ #

st.title("📈 Retirement Advisor")

col1, col2, col3 = st.columns(3)
col1.metric("Tickers en universo", len(st.session_state.universe))
col2.metric("Perfil guardado",     st.session_state.user_prefs.default_profile)
col3.metric("Tests",               "133 passing")

st.divider()

st.markdown("""
### ¿Por dónde empezar?

| Página | ¿Cuándo usarla? |
|---|---|
| **🏠 Screener** | Ver el ranking completo del universo — empezá aquí |
| **🔍 Stock Analysis** | Análisis profundo de un ticker específico |
| **💼 Portfolio** | Ver y gestionar tus posiciones actuales |
| **📈 Optimizer** | Construir una cartera óptima por perfil de riesgo |
| **📊 Backtesting** | Simular performance histórica de la estrategia |
| **🎲 Simulaciones** | Monte Carlo + Stress Test para proyecciones |
| **🔔 Alertas** | Monitoreo automático y reportes PDF |
| **⚙️ Settings** | Configurar universo, AI y preferencias |
""")

st.info(
    "💡 **Flujo recomendado:** Screener → Stock Analysis → Optimizer → Portfolio",
    icon="💡",
)
