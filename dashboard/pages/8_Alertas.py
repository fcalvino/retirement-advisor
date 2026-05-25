"""Alert engine — monitoring, PDF reports and alert history."""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st
from loguru import logger

from alerts.engine import AlertEngine
from alerts.reporter import ReportGenerator
from alerts.store import AlertSeverity, alert_store
from dashboard.shared import _fetch_universe_parallel, _get_ai_config

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("🔔 Alertas & Reportes")
st.caption(
    "Monitoreo proactivo del universo de inversión. "
    "Detecta cambios de señal, caídas de score y nuevas oportunidades. "
    "Genera reportes PDF profesionales."
)

# ------------------------------------------------------------------ #
#  Quick stats                                                        #
# ------------------------------------------------------------------ #

history        = alert_store.get_history(limit=200)
critical_count = sum(1 for a in history if a.severity == AlertSeverity.CRITICAL)
warning_count  = sum(1 for a in history if a.severity == AlertSeverity.WARNING)
info_count     = sum(1 for a in history if a.severity == AlertSeverity.INFO)

qs1, qs2, qs3, qs4 = st.columns(4)
qs1.metric("Total alertas",   len(history))
qs2.metric("🔴 Críticas",     critical_count)
qs3.metric("🟡 Advertencias", warning_count)
qs4.metric("🔵 Info",         info_count)

st.divider()

# ------------------------------------------------------------------ #
#  Actions row                                                        #
# ------------------------------------------------------------------ #

col_run, col_report, col_clear = st.columns([2, 2, 1])

with col_run:
    st.subheader("🔍 Análisis de alertas")
    st.caption(
        "Analiza el universo completo contra el estado guardado y dispara "
        "alertas si se detectan cambios significativos. "
        "Primera ejecución: solo guarda baseline (no dispara alertas)."
    )
    if st.button("▶ Ejecutar análisis ahora", type="primary", use_container_width=True):
        ai_cfg   = _get_ai_config(context="screener")
        universe = st.session_state.universe
        n        = len(universe)
        st.info(f"⚡ Analizando {n} tickers en paralelo…")
        prog = st.progress(0)
        stat = st.empty()
        raw  = _fetch_universe_parallel(universe, ai_cfg, prog, stat, label="Alertas")
        prog.empty()
        stat.empty()

        scored_for_alerts: list[dict] = [
            {
                "symbol":              sym,
                "company_name":        fund.company_name,
                "adjusted_score":      fund.adjusted_score,
                "total_score":         fund.total_score,
                "moat_bonus":          getattr(fund, "moat_bonus", 0),
                "signal":              getattr(dec, "action", ""),
                "moat_classification": getattr(fund, "moat_classification", "None"),
                "moat_score":          getattr(fund, "moat_score", 0),
                "dividend_yield":      fund.dividend_yield or 0,
                "sector":              fund.sector or "Unknown",
            }
            for sym, fund, _tech, dec in raw
        ]

        engine = AlertEngine()
        fired  = engine.run(scored_for_alerts)

        if fired:
            st.success(f"✅ {len(fired)} alertas detectadas y registradas.")
            for a in fired[:10]:
                icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.severity, "•")
                st.write(f"{icon} {a.message}")
            if len(fired) > 10:
                st.caption(f"… y {len(fired) - 10} más. Ver historial abajo.")
        else:
            st.info("Sin cambios significativos detectados en esta ejecución.")
        st.rerun()

with col_report:
    st.subheader("📄 Reporte PDF")
    st.caption(
        "Genera un reporte PDF con el scorecard completo, oportunidades, "
        "señales de riesgo y tabla del universo. "
        "Requiere haber ejecutado al menos una vez el screener."
    )
    period_label = st.text_input(
        "Período del reporte",
        value=datetime.datetime.now().strftime("%B %Y").capitalize(),
        help="Ej: 'Mayo 2026', 'Q2 2026'",
    )
    if st.button("📄 Generar reporte PDF", use_container_width=True):
        scored_cache = st.session_state.get("optimizer_scored", [])
        if not scored_cache:
            st.warning(
                "Primero ejecuta el análisis en 🏠 Screener o 📈 Optimizer "
                "para tener datos del universo."
            )
        else:
            with st.spinner("Generando reporte PDF…"):
                try:
                    gen  = ReportGenerator()
                    path = gen.generate(scored_cache, period=period_label)
                    with open(path, "rb") as f:
                        pdf_bytes = f.read()
                    st.download_button(
                        label="⬇️ Descargar PDF",
                        data=pdf_bytes,
                        file_name=Path(path).name,
                        mime="application/pdf",
                        use_container_width=True,
                    )
                    st.success(f"Reporte generado: `{path}`")
                except Exception as exc:
                    st.error(f"Error generando reporte: {exc}")
                    logger.error(f"Report generation error: {exc}")

with col_clear:
    st.subheader("🗑️ Limpiar")
    st.caption("Elimina el historial de alertas registradas.")
    if st.button("Limpiar historial", use_container_width=True):
        alert_store.clear_history()
        st.rerun()

st.divider()

# ------------------------------------------------------------------ #
#  Alert history table                                                #
# ------------------------------------------------------------------ #

st.subheader("📋 Historial de alertas")

if not history:
    st.info(
        "No hay alertas registradas aún. "
        "Ejecuta el análisis de alertas para comenzar a monitorear el universo."
    )
else:
    _SEVERITY_ICON = {
        AlertSeverity.CRITICAL: "🔴",
        AlertSeverity.WARNING:  "🟡",
        AlertSeverity.INFO:     "🔵",
    }
    _TYPE_LABEL = {
        "signal_change": "Cambio de señal",
        "score_drop":    "Caída de score",
        "score_surge":   "Suba de score",
        "opportunity":   "Oportunidad",
        "moat_change":   "Cambio de moat",
    }
    df_hist = pd.DataFrame([
        {
            "Fecha":   a.fired_at.strftime("%d/%m/%Y %H:%M") if a.fired_at else "",
            "Sev.":    _SEVERITY_ICON.get(a.severity, "•"),
            "Tipo":    _TYPE_LABEL.get(a.alert_type, a.alert_type),
            "Ticker":  a.symbol,
            "Mensaje": a.message,
        }
        for a in history[:100]
    ])
    st.dataframe(df_hist, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------ #
#  Scheduler instructions                                             #
# ------------------------------------------------------------------ #

with st.expander("⚙️ Cómo automatizar alertas (scheduler en background)"):
    st.markdown("""
**Para recibir alertas automáticas sin abrir el dashboard:**

```bash
# Desde la raíz del proyecto:
python scripts/run_scheduler.py
```

El scheduler:
- Corre el análisis completo cada `ALERT_INTERVAL_HOURS` horas (default: 24h)
- Genera el reporte PDF el día `REPORT_DAY` de cada mes a las 08:00
- Envía alertas por email y/o Telegram si están configurados en `.env`

**Variables de entorno relevantes:**
```
ALERT_INTERVAL_HOURS=24    # cada cuántas horas revisar alertas
REPORT_DAY=1               # día del mes para el reporte
EMAIL_FROM=...             # habilita alertas por email
TELEGRAM_TOKEN=...         # habilita alertas por Telegram
```

Para correr en background (macOS/Linux):
```bash
nohup python scripts/run_scheduler.py &> logs/scheduler.log &
```
    """)
