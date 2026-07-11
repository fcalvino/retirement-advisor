"""Alert engine — monitoring, history, configuration and mute management."""

from __future__ import annotations

import datetime
from pathlib import Path

import streamlit as st
from loguru import logger

from alerts.engine import AlertEngine
from alerts.reporter import ReportGenerator
from alerts.store import AlertSeverity, AlertType, alert_store
from config import ALERTS
from dashboard.shared import _fetch_universe_parallel, _get_ai_config

# ------------------------------------------------------------------ #
#  Mark alerts as read when user visits this page                      #
# ------------------------------------------------------------------ #

alert_store.mark_all_read()
try:
    st.cache_data.clear()
except Exception:
    pass

# ------------------------------------------------------------------ #
#  Page header + quick stats                                           #
# ------------------------------------------------------------------ #

st.title("🔔 Alertas Inteligentes")
st.caption(
    "Monitoreo proactivo de tu universo y portafolio. "
    "Detecta cambios de señal, caídas de score, riesgos de portafolio y nuevas oportunidades."
)

history        = alert_store.get_history(limit=500)
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
#  Tabs                                                                #
# ------------------------------------------------------------------ #

tab_run, tab_history, tab_config, tab_mutes = st.tabs([
    "▶ Ejecutar análisis", "📋 Historial", "⚙️ Configuración", "🔇 Silenciados"
])

# ================================================================== #
#  TAB 1 — Run analysis + PDF report                                  #
# ================================================================== #

with tab_run:
    col_run, col_report = st.columns([3, 2])

    with col_run:
        st.subheader("🔍 Análisis de alertas")
        st.caption(
            "Analiza el universo completo contra el estado guardado y dispara "
            "alertas si se detectan cambios significativos. "
            "Primera ejecución: solo guarda baseline (no dispara alertas)."
        )

        # Profile selection for severity filtering
        _profile = st.selectbox(
            "Perfil de alertas",
            options=["Conservador", "Moderado", "Agresivo"],
            index=1,
            help=(
                "Conservador: solo recibe alertas WARNING y CRITICAL. "
                "Moderado/Agresivo: recibe todas las alertas."
            ),
        )

        _include_portfolio = st.checkbox(
            "Incluir alertas de portafolio",
            value=True,
            help="Analiza posiciones abiertas: pérdidas, drift del optimizer y rebalanceo.",
        )

        if st.button("▶ Ejecutar análisis ahora", type="primary", width="stretch"):
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

            engine = AlertEngine(active_profile=_profile)

            if _include_portfolio:
                portfolio = st.session_state.get("portfolio")
                optimizer_result = st.session_state.get("optimizer_result")
                positions = {}
                current_prices = {}
                optimizer_weights = None

                if portfolio:
                    try:
                        price_data = portfolio.get_current_values()
                        for sym, vals in price_data.items():
                            pos = portfolio.positions.get(sym)
                            if pos:
                                positions[sym] = {
                                    "shares": pos.shares,
                                    "avg_cost": pos.avg_cost,
                                    "sector": pos.sector,
                                }
                                current_prices[sym] = vals.get("current_price", pos.avg_cost)
                    except Exception as e:
                        logger.warning(f"Portfolio data unavailable: {e}")

                if optimizer_result:
                    try:
                        optimizer_weights = {
                            t.symbol: t.weight_pct
                            for t in optimizer_result.tickers
                        }
                    except Exception:
                        pass

                fired = engine.run_with_portfolio(
                    scored_for_alerts, positions, current_prices, optimizer_weights
                )
            else:
                fired = engine.run(scored_for_alerts)

            if fired:
                st.success(f"✅ {len(fired)} alertas detectadas y registradas.")
                for a in fired[:10]:
                    icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(a.severity, "•")
                    st.write(f"{icon} {a.message}")
                    if a.explanation:
                        st.caption(f"   💬 {a.explanation}")
                if len(fired) > 10:
                    st.caption(f"… y {len(fired) - 10} más. Ver historial en la pestaña Historial.")
            else:
                st.info("Sin cambios significativos detectados en esta ejecución.")
            st.rerun()

    with col_report:
        st.subheader("📄 Reporte PDF")
        st.caption(
            "Genera un reporte PDF con el scorecard completo, oportunidades, "
            "señales de riesgo y tabla del universo."
        )
        period_label = st.text_input(
            "Período del reporte",
            value=datetime.datetime.now().strftime("%B %Y").capitalize(),
            help="Ej: 'Mayo 2026', 'Q2 2026'",
        )
        if st.button("📄 Generar reporte PDF", width="stretch"):
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
                            width="stretch",
                        )
                        st.success(f"Reporte generado: `{path}`")
                    except Exception as exc:
                        st.error(f"Error generando reporte: {exc}")

        st.divider()
        st.subheader("🗑️ Limpiar historial")
        st.caption("Elimina el historial de alertas registradas.")
        if st.button("Limpiar historial", width="stretch"):
            alert_store.clear_history()
            st.rerun()

# ================================================================== #
#  TAB 2 — Alert history with filters                                  #
# ================================================================== #

with tab_history:
    if not history:
        st.info(
            "No hay alertas registradas aún. "
            "Ejecuta el análisis en la pestaña ▶ Ejecutar análisis para comenzar."
        )
    else:
        _SEVERITY_ICON = {
            AlertSeverity.CRITICAL: "🔴",
            AlertSeverity.WARNING:  "🟡",
            AlertSeverity.INFO:     "🔵",
        }
        _TYPE_LABEL = {
            "signal_change":       "Cambio de señal",
            "score_drop":          "Caída de score",
            "score_surge":         "Suba de score",
            "opportunity":         "Oportunidad",
            "moat_change":         "Cambio de moat",
            "portfolio_loss":      "Pérdida en posición",
            "portfolio_drift":     "Drift de posición",
            "portfolio_rebalance": "Rebalanceo requerido",
            "sorr_high":           "SORR elevado",
            "goal_risk":           "Meta en riesgo",
        }

        # Filters
        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            _all_types = sorted(set(a.alert_type for a in history))
            _type_labels = ["Todos"] + [_TYPE_LABEL.get(t, t) for t in _all_types]
            _sel_type_label = st.selectbox("Tipo", _type_labels, index=0)
            _sel_type = (
                None if _sel_type_label == "Todos"
                else _all_types[_type_labels.index(_sel_type_label) - 1]
            )
        with fcol2:
            _sel_sev = st.selectbox(
                "Severidad", ["Todas", "🔴 Crítica", "🟡 Advertencia", "🔵 Info"], index=0
            )
            _sev_map = {"🔴 Crítica": "critical", "🟡 Advertencia": "warning", "🔵 Info": "info"}
            _sel_sev_val = _sev_map.get(_sel_sev)
        with fcol3:
            _all_tickers = sorted(set(a.symbol for a in history))
            _sel_ticker = st.selectbox("Ticker", ["Todos"] + _all_tickers, index=0)

        # Apply filters
        filtered = history
        if _sel_type:
            filtered = [a for a in filtered if a.alert_type == _sel_type]
        if _sel_sev_val:
            filtered = [a for a in filtered if a.severity == _sel_sev_val]
        if _sel_ticker != "Todos":
            filtered = [a for a in filtered if a.symbol == _sel_ticker]

        st.caption(f"Mostrando {len(filtered)} de {len(history)} alertas")

        for a in filtered[:100]:
            icon = _SEVERITY_ICON.get(a.severity, "•")
            type_label = _TYPE_LABEL.get(a.alert_type, a.alert_type)
            date_str = a.fired_at.strftime("%d/%m/%Y %H:%M") if a.fired_at else ""
            with st.expander(
                f"{icon} [{date_str}] **{a.symbol}** — {type_label}",
                expanded=False,
            ):
                st.write(a.message)
                if a.explanation:
                    st.info(f"💬 **Explicación:** {a.explanation}")

# ================================================================== #
#  TAB 3 — Configuration                                              #
# ================================================================== #

with tab_config:
    st.subheader("⚙️ Configuración de alertas")

    st.markdown("**Frecuencia y canales**")
    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        _freq = st.selectbox(
            "Modo de frecuencia",
            ["daily", "weekly", "critical_only"],
            index=["daily", "weekly", "critical_only"].index(ALERTS.frequency_mode),
            help=(
                "daily: chequea cada 24hs.\n"
                "weekly: chequea una vez por semana.\n"
                "critical_only: solo alertas CRÍTICAS."
            ),
        )
        _hours = st.number_input(
            "Intervalo entre chequeos (horas)",
            min_value=1, max_value=168,
            value=ALERTS.check_frequency_hours,
            step=1,
        )
    with col_cfg2:
        _email_ok = st.checkbox("Email habilitado", value=ALERTS.email_enabled, disabled=True)
        _tg_ok = st.checkbox("Telegram habilitado", value=ALERTS.telegram_enabled, disabled=True)
        _ai_exp = st.checkbox(
            "Explicaciones AI",
            value=ALERTS.ai_explanations_enabled,
            help="Grok/Claude genera una explicación natural para cada alerta.",
        )

    st.markdown("**Umbrales de detección**")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        _score_thr = st.slider(
            "Cambio mínimo de score (pts)",
            min_value=3.0, max_value=20.0,
            value=float(ALERTS.score_change_threshold),
            step=1.0,
        )
        _loss_thr = st.slider(
            "Pérdida en posición para alerta (%)",
            min_value=3.0, max_value=25.0,
            value=float(ALERTS.portfolio_loss_threshold_pct),
            step=1.0,
        )
    with col_t2:
        _drift_thr = st.slider(
            "Drift individual por posición (%)",
            min_value=2.0, max_value=15.0,
            value=float(ALERTS.portfolio_drift_threshold_pct),
            step=0.5,
        )
        _rebalance_thr = st.slider(
            "Drift total para rebalanceo (%)",
            min_value=5.0, max_value=20.0,
            value=float(ALERTS.portfolio_rebalance_threshold_pct),
            step=1.0,
        )

    st.info(
        "⚠️ Los cambios de configuración aquí son visuales. "
        "Para cambiarlos de forma permanente, editá las variables en `.env` "
        "o los valores por defecto en `config.py:AlertConfig`.",
        icon="ℹ️",
    )

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
ALERT_INTERVAL_HOURS=24        # cada cuántas horas revisar alertas
ALERT_FREQUENCY_MODE=daily     # daily | weekly | critical_only
ALERT_AI_EXPLANATIONS=true     # habilitar explicaciones con IA
REPORT_DAY=1                   # día del mes para el reporte
EMAIL_FROM=...                 # habilita alertas por email
TELEGRAM_TOKEN=...             # habilita alertas por Telegram
```

Para correr en background (macOS/Linux):
```bash
nohup python scripts/run_scheduler.py &> logs/scheduler.log &
```
        """)

# ================================================================== #
#  TAB 4 — Mutes (silenciados)                                        #
# ================================================================== #

with tab_mutes:
    st.subheader("🔇 Silenciados")
    st.caption("Tickers o tipos de alerta silenciados temporalmente.")

    # Add new mute
    with st.form("add_mute_form"):
        st.markdown("**Agregar silencio**")
        mc1, mc2, mc3, mc4 = st.columns([2, 2, 1, 1])
        with mc1:
            _mute_sym = st.text_input(
                "Ticker (o '*' para todos)",
                placeholder="AAPL",
                help="'*' silencia el tipo de alerta para todos los tickers.",
            )
        with mc2:
            _type_options = {
                "Todos los tipos": "*",
                "Cambio de señal": AlertType.SIGNAL_CHANGE.value,
                "Caída de score": AlertType.SCORE_DROP.value,
                "Suba de score": AlertType.SCORE_SURGE.value,
                "Oportunidad": AlertType.OPPORTUNITY.value,
                "Cambio de moat": AlertType.MOAT_CHANGE.value,
                "Pérdida en posición": AlertType.PORTFOLIO_LOSS.value,
                "Drift de posición": AlertType.PORTFOLIO_DRIFT.value,
                "Rebalanceo": AlertType.PORTFOLIO_REBALANCE.value,
                "SORR elevado": AlertType.SORR_HIGH.value,
                "Meta en riesgo": AlertType.GOAL_RISK.value,
            }
            _mute_type_label = st.selectbox("Tipo de alerta", list(_type_options.keys()))
            _mute_type = _type_options[_mute_type_label]
        with mc3:
            _mute_days = st.number_input(
                "Días (0 = permanente)",
                min_value=0, max_value=365, value=7,
            )
        with mc4:
            st.markdown("<br>", unsafe_allow_html=True)
            _submitted = st.form_submit_button("➕ Agregar", width="stretch")

        if _submitted:
            sym = (_mute_sym or "").strip().upper() or "*"
            days = int(_mute_days) if _mute_days > 0 else None
            alert_store.add_mute(symbol=sym, alert_type=_mute_type, days=days)
            st.success(f"Silenciado: {sym} / {_mute_type_label}" + (f" por {days} días" if days else " (permanente)"))
            st.rerun()

    # List active mutes
    mutes = alert_store.get_mutes()
    if not mutes:
        st.info("No hay silenciados activos.")
    else:
        _TYPE_LABEL_SHORT = {v: k for k, v in {
            "Todos los tipos": "*",
            "Cambio de señal": AlertType.SIGNAL_CHANGE.value,
            "Caída de score": AlertType.SCORE_DROP.value,
            "Suba de score": AlertType.SCORE_SURGE.value,
            "Oportunidad": AlertType.OPPORTUNITY.value,
            "Cambio de moat": AlertType.MOAT_CHANGE.value,
            "Pérdida en posición": AlertType.PORTFOLIO_LOSS.value,
            "Drift de posición": AlertType.PORTFOLIO_DRIFT.value,
            "Rebalanceo": AlertType.PORTFOLIO_REBALANCE.value,
            "SORR elevado": AlertType.SORR_HIGH.value,
            "Meta en riesgo": AlertType.GOAL_RISK.value,
        }.items()}

        for m in mutes:
            col_a, col_b, col_c, col_d = st.columns([2, 3, 3, 1])
            with col_a:
                st.write(f"**{m.symbol}**")
            with col_b:
                st.write(_TYPE_LABEL_SHORT.get(m.alert_type, m.alert_type))
            with col_c:
                if m.expires_at:
                    remaining = m.expires_at - datetime.datetime.utcnow()
                    days_left = max(0, remaining.days)
                    st.write(f"Expira en {days_left}d ({m.expires_at.strftime('%d/%m/%Y')})")
                else:
                    st.write("Permanente")
            with col_d:
                if st.button("❌", key=f"del_mute_{m.id}", help="Eliminar silencio"):
                    alert_store.remove_mute(m.id)
                    st.rerun()
