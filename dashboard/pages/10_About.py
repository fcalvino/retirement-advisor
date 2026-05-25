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
st.caption("v8.0 — Fase 8: Producción Ready")

col1, col2, col3 = st.columns(3)
col1.metric("Versión", "8.0")
col2.metric("Tickers en universo", len(st.session_state.get("universe", DEFAULT_TICKERS)))
col3.metric("Tests", "133 passing")

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
| **Screener** | Ranking de 38+ tickers con score ajustado (0–100) y señal |
| **Stock Analysis** | Análisis profundo: Piotroski, Consistency, Economic Moat, AI |
| **Portfolio Tracker** | Posiciones, P&L, pesos por sector |
| **Asset Allocation** | Regla conservadora acciones/bonos/cash por edad |
| **Optimizer** | Mean-Variance SLSQP + 3 perfiles de riesgo |
| **Backtesting** | Curva de equity histórica, Sharpe, Sortino, Calmar |
| **Simulaciones** | Monte Carlo 10k sims + Stress Test 6 crisis históricas |
| **Alertas** | Motor inteligente con debounce + email/Telegram + PDF |
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
