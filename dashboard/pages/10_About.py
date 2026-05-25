"""About page — version info, config status, score formula and docs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from config import DEFAULT_TICKERS

# ------------------------------------------------------------------ #
#  Page config                                                         #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="About — Retirement Advisor",
    page_icon="ℹ️",
    layout="wide",
)

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("ℹ️ About — Retirement Advisor")
st.caption("v1.0.0 — Motor de análisis de inversiones para el retiro")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Versión", "1.0.0")
col2.metric("Tickers en universo", len(st.session_state.get("universe", DEFAULT_TICKERS)))
col3.metric("Tests", "133 passing")
col4.metric("Páginas", "11")

st.divider()

# Project highlights
st.subheader("Highlights del proyecto")
h1, h2, h3 = st.columns(3)
with h1:
    st.markdown("""
**📊 Análisis cuantitativo**
- Score fundamental 0–100 en 5 dimensiones
- Consistency Score + Piotroski F-Score
- Economic Moat cuantitativo 0–20 pts
- Análisis técnico en barras semanales de 10 años
""")
with h2:
    st.markdown("""
**🤖 Decisión asistida por AI**
- Claude, GPT-4o, Grok o Nous Research
- Moat cualitativo: network effects, switching costs, brand, regulatory
- Razonamiento en lenguaje natural por ticker
- Fallback rule-based si no hay API key
""")
with h3:
    st.markdown("""
**📈 Gestión de portafolio**
- Optimizer Mean-Variance (SLSQP) con 3 perfiles
- Monte Carlo block-bootstrap 10 000 sims
- Stress test en 6 crisis históricas
- Watchlist con alertas de precio en tiempo real
""")

st.divider()

# Config status
st.subheader("Estado de configuración")
issues = st.session_state.get("config_issues", [])
if not issues:
    st.info("Validación de configuración no disponible. Recargá la página.")
else:
    for level, msg in issues:
        if level == "error":
            st.error(msg, icon="🔴")
        elif level == "warning":
            st.warning(msg, icon="🟡")
        elif "Hermes OAuth" in msg:
            st.success(msg, icon="🔐")
        else:
            st.success(msg, icon="✅")

st.divider()

# Feature summary
st.subheader("Módulos activos")
st.markdown("""
| Módulo | Descripción |
|--------|-------------|
| **🏠 Screener** | Ranking de 38+ tickers con score ajustado (0–100) y señal — paralelo con cache 1h |
| **🔍 Stock Analysis** | Análisis profundo: Piotroski, Consistency, Economic Moat, decisión AI |
| **💼 Portfolio** | Posiciones abiertas, P&L, gráficos de pesos por sector |
| **📊 Allocation** | Regla conservadora acciones/bonos/cash según edad |
| **📈 Optimizer** | Mean-Variance SLSQP + 3 perfiles + Efficient Frontier Monte Carlo |
| **📉 Backtesting** | Curva de equity histórica, Sharpe, Sortino, Calmar, scatter Score↔CAGR |
| **🎲 Simulaciones** | Monte Carlo 10k sims (block-bootstrap) + Stress Test 6 crisis históricas |
| **🔔 Alertas** | Motor inteligente con debounce SQLite + email/Telegram + PDF mensual |
| **📋 Watchlist** | Tickers favoritos con alertas de precio en tiempo real |
| **⚙️ Settings** | Editor de universo, configuración AI, limpieza de caché |
""")

st.divider()

# Score formula
st.subheader("Fórmula del Score Ajustado")
st.code(
    "adjusted_score = min(\n"
    "    fundamental_score        (0–100)\n"
    "  + consistency_score        (0–15)   # estabilidad ROE/EPS/márgenes\n"
    "  + piotroski_bonus          (0–12)   # 9 checks YoY de calidad contable\n"
    "  + moat_bonus               (0–10)   # min(moat_score × 0.5, 10)\n"
    ", 100)",
    language="python",
)

st.divider()

# Docs links
st.subheader("Documentación técnica")
st.markdown("""
- `docs/architecture.md` — Mapa de módulos y flujo de datos
- `docs/moat_methodology.md` — Economic Moat: metodología y umbrales
- `docs/portfolio_optimizer.md` — Optimizer: SLSQP, perfiles, ARS discount
- `docs/alert_system.md` — Alertas: tipos, cooldowns, scheduler
- `docs/ROADMAP.md` — Historial de fases (1 → 8)
""")

st.divider()

st.warning(
    "**Aviso legal**: Esta herramienta es educativa. Los resultados no constituyen "
    "asesoramiento financiero. Los datos provienen de Yahoo Finance y pueden contener "
    "errores o estar desactualizados. Consultá con un asesor certificado antes de "
    "tomar decisiones de inversión.",
    icon="⚠️",
)
