# Sistema de Alertas y Reportes

## Visión general

El sistema de alertas detecta cambios significativos en el análisis de cada ticker comparando contra el último snapshot guardado. Está diseñado para ser **no-spammy**: cada tipo de alerta tiene un cooldown específico, y la primera ejecución siempre guarda baseline silenciosamente.

---

## Componentes

```
AlertEngine.run(scored_tickers)
        │
        ├── AlertStore.get_snapshot(symbol)   ← SQLite
        │       │
        │       ├─ None (primera vez) → save_baseline(), return   ← cold start
        │       └─ Snapshot exists → comparar con estado actual
        │
        ├── 5 check methods (signal_change, score_drop, score_surge, opportunity, moat_change)
        │       │
        │       └─ AlertStore.is_on_cooldown() → si True, skip
        │
        ├── AlertStore.record() + set_cooldown()
        ├── AlertStore.save_snapshot()   ← actualizar baseline
        │
        └── Notifier._dispatch(fired)   → email + Telegram digest
```

---

## Tipos de alerta

| Tipo | Condición de disparo | Cooldown | Severidad |
|------|---------------------|---------|-----------|
| `SIGNAL_CHANGE` | Señal cambió (e.g. HOLD → BUY, BUY → SELL) | 24h | WARNING / CRITICAL si SELL |
| `SCORE_DROP` | Score bajó ≥ 8 pts vs. baseline | 168h (7 días) | WARNING / CRITICAL si ≥ 15 pts |
| `SCORE_SURGE` | Score subió ≥ 8 pts Y señal actual es BUY/STRONG_BUY | 168h | INFO |
| `OPPORTUNITY` | Ticker entró en BUY/STRONG_BUY (venía de HOLD/SELL) | 72h | INFO |
| `MOAT_CHANGE` | Moat degradado (Wide→Narrow, Narrow→Minimal, Minimal→None) | 336h (14 días) | WARNING |
| `MARKET_DROP_COACH` | Cartera ≥ 8 % por debajo del costo promedio (o de los precios con que se guardó el plan): resultado acumulado, no una caída reciente | 72h (`AlertConfig.coach_cooldown_hours`) | INFO / WARNING si la prob. de meta está bajo el piso |

El coach avisa **una vez por episodio** (mientras la cartera siga bajo el umbral): vuelve a avisar solo si el retorno empeora `AlertConfig.coach_refire_extra_drop_pp` (2 puntos) más allá del último nivel avisado o si sube la severidad. Mientras el retorno se recupera, el nivel de referencia sube con él (una caída que parte de lo recuperado vuelve a avisar), y cada base (costo / precios del plan) lleva su propio episodio, que vence si deja de medirse `AlertConfig.coach_episode_max_gap_days` (30) días. El nivel avisado se guarda en `alert_snapshots` bajo `COACH:<plan>:<base>`.

El umbral de score change (8 pts) es configurable en `AlertConfig.score_change_threshold`.

---

## Cold start

La primera vez que `AlertEngine.run()` ve un ticker, guarda el estado actual como baseline y **no dispara ninguna alerta**. Esto previene el diluvio de alertas falsas al iniciar el sistema por primera vez con un universo de 38 tickers.

---

## Persistencia (SQLite)

Tres tablas en `data/db/retirement_advisor.db`:

### `alert_snapshots`

Último estado conocido por ticker. Actualizado al final de cada `run()`. También guarda estado de planes: `GOAL:<plan>` (probabilidad de meta previa) y `COACH:<plan>:<base>` (último retorno que avisó el coach; `score` = retorno, `signal` = `COACH`, `moat_class` = severidad).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `symbol` | TEXT (PK) | Ticker |
| `score` | REAL | Score ajustado en la última ejecución |
| `signal` | TEXT | Señal en la última ejecución |
| `moat_class` | TEXT | Clasificación de moat en la última ejecución |
| `updated_at` | DATETIME | Timestamp del último update |

### `alert_history`

Historial de alertas disparadas. Máximo 500 entradas (FIFO, se eliminan las más antiguas).

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | INTEGER (PK) | Autoincrement |
| `alert_type` | TEXT | Tipo de alerta |
| `symbol` | TEXT | Ticker |
| `message` | TEXT | Mensaje completo |
| `severity` | TEXT | INFO / WARNING / CRITICAL |
| `fired_at` | DATETIME | Timestamp de disparo |

### `alert_cooldowns`

Cooldowns activos para prevenir re-disparos.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `key` | TEXT (PK) | `"{alert_type}:{symbol}"` |
| `expires_at` | DATETIME | Momento en que expira el cooldown |

---

## Despacho de notificaciones

`AlertEngine._dispatch()` agrupa todas las alertas de una ejecución en un único mensaje digest, organizado por severidad:

```
🔴 CRÍTICAS
  • T (AT&T): señal cambió BUY → SELL (Score: 38.2/100)

🟡 ADVERTENCIAS
  • JPM: score cayó 12.1 pts (72.0 → 59.9/100). Revisar fundamentals.

🔵 INFORMACIÓN
  • NVDA: score subió 9.3 pts (61.0 → 70.3/100) · señal: STRONG_BUY
```

Si no hay canales configurados (email ni Telegram), el digest se loguea localmente pero no se envía.

---

## Notificaciones

### Email

`Notifier._send_email()` envía HTML con template branded vía SMTP. Requiere `EMAIL_FROM`, `EMAIL_TO`, `SMTP_PASSWORD` en `.env`.

Para Gmail: usar App Password (no la contraseña de cuenta). Activar 2FA y generar en *Cuenta Google → Seguridad → Contraseñas de aplicaciones*.

### Telegram

`Notifier._send_telegram()` llama a `https://api.telegram.org/bot{TOKEN}/sendMessage`. Requiere `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (`TELEGRAM_TOKEN` se acepta como alias; `config.resolve_telegram_token`).

Para obtener el chat_id: enviar cualquier mensaje al bot y consultar `https://api.telegram.org/bot{TOKEN}/getUpdates`.

---

## Reportes PDF mensuales

`ReportGenerator.generate(scored_tickers, portfolio_positions, period)` genera un PDF con:

1. **Cover**: KPIs clave (total tickers, BUY count, SELL count, avg score)
2. **Top oportunidades** (BUY/STRONG_BUY, ordenado por score)
3. **Riesgos** (SELL/REDUCE)
4. **Portafolio actual** (si hay posiciones abiertas)
5. **Universo completo** (tabla con todos los tickers)
6. **Gráfico de distribución** de scores (histograma matplotlib embebido)
7. **Disclaimer** legal

El PDF se guarda en `REPORT_OUTPUT_DIR` (default `reports/`) y se puede adjuntar al email.

---

## Scheduler

`scripts/run_scheduler.py` usa la librería `schedule` para:

- **Alertas**: cada `ALERT_INTERVAL_HOURS` (default 24h), ejecuta el screener completo y corre `AlertEngine.run()`
- **Reporte PDF**: el día `REPORT_DAY` de cada mes a las 08:00 AM, genera PDF y lo envía
- **Scoring de outcomes**: diario a las 07:00 — `job_score_track_record` (track record en vivo) y `job_score_synthetic_outcomes` (backtesting point-in-time)

`--once` corre macro + alertas + los dos scorings y sale: es el camino de `scripts/run_daily_alerts.sh` (cron) y de launchd. Antes de SCHED-ONCE (2026-09) `--once` no puntuaba y el track record pasó un mes sin outcomes.

```bash
python scripts/run_scheduler.py
```

Al iniciar, ejecuta un chequeo de alertas inmediato antes de entrar al loop de schedule.

### Variables de entorno relevantes

| Variable | Default | Descripción |
|----------|---------|-------------|
| `ALERT_INTERVAL_HOURS` | 24 | Frecuencia de chequeo de alertas |
| `REPORT_DAY` | 1 | Día del mes para generar el PDF |
| `REPORT_OUTPUT_DIR` | `reports` | Carpeta de destino de PDFs |

---

## Ejecutar manualmente desde el dashboard

La página **Alertas** del dashboard permite:
- Ver el historial de alertas disparadas
- Ejecutar un análisis manual y correr el motor de alertas
- Descargar el PDF del período actual
- Limpiar el historial

---

## Limitaciones

- El scheduler continuo es un proceso Python simple (no un cron del sistema). Se detiene si el proceso muere o la máquina duerme.
- En macOS, `make launchd-install` agenda `--once` a diario (07:30) con launchd (`deploy/launchd/`, `scripts/install_launchd.sh`); en Linux, cron o `systemd` (README).
- El historial se limita a 500 alertas para evitar crecimiento indefinido del SQLite.
- Los cooldowns persisten entre reinicios del proceso (guardados en SQLite).
