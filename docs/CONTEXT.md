# Project Context — Retirement Advisor

> **Obligatorio:** Este archivo debe leerse completo antes de planear o codificar cualquier cambio.
> Última actualización: 2026-06-23 (Comité de Inversión sobre el PORTFOLIO ACTUAL — "Dictamen del comité sobre tu portfolio", en la página Portfolio)

---

## 1. Resumen Ejecutivo

**Retirement Advisor** es un sistema de análisis de portafolios de inversión a largo plazo orientado a particulares. Combina análisis fundamental cuantitativo, scoring de Moat económico (cuantitativo + IA), optimización de portafolio Mean-Variance y simulaciones Monte Carlo para ayudar al usuario a planificar metas de inversión a 5–30 años.

**Filosofía del proyecto:**
- No es un broker ni da órdenes de compra/venta automáticas — da recomendaciones accionables
- Conservador por defecto: ajuste de volatilidad +10%, haircut de retorno esperado −20% en MC
- Multi-proveedor AI (Claude / Grok / OpenAI / Nous): el usuario elige desde el dashboard
- Todo configurable sin tocar código: thresholds, perfiles, universo de tickers → `config.py`
- UI en Streamlit; no hay backend web, no hay base de datos externa (solo SQLite local)

---

## 2. Stack Técnico

| Componente | Tecnología |
|------------|------------|
| Lenguaje | Python 3.11–3.13 (CI: matrix 3.11/3.12; Docker: 3.12-slim; mínimo soportado 3.10) |
| UI | Streamlit + Plotly |
| Análisis numérico | NumPy, Pandas, pandas_ta, SciPy (SLSQP) |
| Datos de mercado | yfinance (Yahoo Finance) |
| AI / LLM | anthropic, openai (xAI Grok via API compatible) |
| Persistencia | SQLite via SQLAlchemy |
| Alertas | Email (smtplib) + Telegram Bot API |
| Reportes | reportlab (PDF) |
| Logging | loguru |
| Scheduler | schedule |
| Virtualenv | `./venv/` (ejecutar con `./venv/bin/python3`) |

---

## 3. Arquitectura — Capas del Sistema

```
Yahoo Finance (yfinance)
        │
        ▼
  data/fetcher.py  ←→  data/cache.py (SQLite, TTL)
        │
        ├──────────────────────────────────────┐
        ▼                                      ▼
analysis/fundamental.py            portfolio/optimizer.py
analysis/scoring.py                portfolio/monte_carlo.py
analysis/moat.py                   portfolio/stress_test.py
analysis/technical.py              portfolio/tracker.py
        │                          portfolio/goals.py
        ▼
analysis/strategy.py  (full_analysis — orquestador)
analysis/ai_analyzer.py  (decisión AI opcional)
        │
        ├──────────────────────────────────────┐
        ▼                                      ▼
dashboard/app.py (Streamlit, 7 páginas)   alerts/engine.py
dashboard/shared.py (cached_*)            alerts/store.py (SQLite)
                                          alerts/notifier.py (email/Telegram)
                                          alerts/reporter.py (PDF/reportlab)
                                          scripts/run_scheduler.py
```

**Flujo de datos principal:**
1. Screener → `strategy.full_analysis()` × N tickers → cacheado en `session_state["screener_cache"]`
2. Optimizer → lee `screener_cache` (sin re-análisis) → SLSQP → `session_state["optimizer_prev_result"]`
3. Simulaciones → lee `optimizer_prev_result.tickers` → MonteCarloSimulator + StressTester + GoalPlanner
4. Alertas → `AlertEngine.run(scored_tickers)` → dispatch por email/Telegram cuando hay cambios

---

## 4. Mapa de Archivos Críticos

| Archivo | Responsabilidad | Cuándo tocarlo |
|---------|-----------------|----------------|
| `config.py` | **Fuente de verdad**: todos los thresholds, perfiles, parámetros | Cambiar umbrales, agregar perfil, ajustar MC |
| `analysis/fundamental.py` | Score 0–100, llama a scoring y moat | Cambiar dimensiones del scoring |
| `analysis/scoring.py` | Consistency Score (0–15) + Piotroski F-Score (0–9) | Ajustar lógica de consistencia |
| `analysis/moat.py` | Economic Moat cuantitativo (0–12) + AI (0–8). `MoatDetail` expone `macro_factors` y `macro_impact_on_moat_durability` cuando se usa LLM. | Cambiar metodología de moat |
| `analysis/tailwind.py` | **Fase F**: colas de viento estructurales sector-país (Idea 2). `TailwindAnalyzer.analyze()` (curado, siempre, sin API; matching ticker > industria+país > sector+país) + `analyze_with_ai()` (enriquecimiento cacheado 30d; el LLM nunca cambia el score). `TailwindDetail` + funciones puras de clasificación/bonus. | Cambiar matching o metodología de tailwinds |
| `data/tailwinds/sector_country.json` | Datos curados de tailwinds (fuente de verdad, editable a mano; campo `last_reviewed` por entrada). Ej: Energy+Argentina (Vaca Muerta +8), headwind Utilities reguladas AR (−3). | Agregar/revisar outlooks sector-país |
| `analysis/ai_analyzer.py` | Capa AI: 4 proveedores, parseo de respuesta estructurada (incluye `macro_factors`). Narrativas: `generate_long_term_narrative`, `generate_optimizer_advice`, y **`generate_plan_narrative`** (Fase D: narrativa + `macro_risks` de un plan guardado) | Agregar proveedor, cambiar formato de respuesta o narrativa |
| `analysis/prompts.py` | Todos los prompts de IA (persona Grok, narrativa, moat) + helpers centralizados de contexto macro y contrato de salida estructurado (`macro_factors`). Incluye **`plan_level_narrative_prompt`** (Fase D) | Editar cualquier prompt o la lógica de contexto macro |
| `analysis/strategy.py` | `full_analysis()` — orquestador del pipeline. Expone `Decision` con `macro_factors` (estructurado) cuando se usa AI. | Cambiar el flujo de análisis |
| `analysis/committee.py` + `analysis/committee_prompts.py` | Comité multi-agente con disenso explícito. **Por ticker:** `CommitteeAnalyzer.analyze(fund, tech)`. **Por portfolio actual:** `analyze_portfolio(ctx, plan_key)` + `build_holdings_committee_context()` (real holdings) + `portfolio_concentration()`; `build_portfolio_committee_context()` es un helper genérico. `aggregate(weights=…)` es genérico. Pesos/etiquetas en `CommitteeConfig` (`COMMITTEE`). El rol `"Abogado del Diablo"` ancla el disenso siempre-presente. UI del dictamen de portfolio: `dashboard/pages/3_Portfolio.py` (`run_holdings_committee`/`render_committee_verdict` en shared). | Cambiar agentes, prompts o agregación del comité (ticker o portfolio) |
| `portfolio/optimizer.py` | Mean-Variance SLSQP + 3 perfiles + fallback | Cambiar optimizador o perfiles |
| `portfolio/monte_carlo.py` | Simulación block-bootstrap + SORR metrics + drags (Fase G). **Fase H.1:** `run(withdrawal_strategy=, longevity_years=)` + métricas de decumulación en `MonteCarloResult`. Sin estrategia → byte-idéntico | Cambiar modelo estocástico |
| `portfolio/decumulation.py` | **Fase H.1** (puro NumPy): `WithdrawalStrategy` (fixed_real/constant_pct/guardrails), `apply_withdrawal_strategy`, `decumulation_metrics`. Inyectado en el MC | Cambiar estrategias de retiro / métricas de "cuánto dura el ingreso" |
| `portfolio/sensitivity.py` | **Fase H.3** (puro, `run_fn` inyectado): `run_sensitivity` (tornado 4 factores + escenarios) + `tornado_rows`. Reusa el MC vía un runner | Cambiar factores/escenarios del what-if |
| `portfolio/goals.py` | Multi-Goal Planner: `Goal`, `GoalPlan`, `GoalPlanner` | Funcionalidad de metas |
| `dashboard/shared.py` + `dashboard/app.py` + `pages/*.py` | Entry multipage (`st.navigation`/`st.Page` en app.py); helpers cacheados + visuales + AI config en shared (cached_*, _get_ai_config, _analyse_universe_parallel, etc.). Monolith legacy removido (era dupe completo de ~2540 LOC). | Agregar página, helper cacheado o patrón de shared (ver app.py para init y navegación) |
| `dashboard/onboarding.py` | Wizard de perfil personal (Fase A): `render_onboarding_wizard()`, `render_profile_summary()`. Consumido en Inicio + Settings. | Cambiar las preguntas del perfil o su persistencia |
| `dashboard/pages/12_Plan.py` | Página "🗺️ Mi Plan" (Fase B/C/D): consolida cartera+núcleo+metas+MC+narrativa de la sesión, guarda/carga/compara/borra planes, lista de compra del núcleo y PDF. **Fase C:** activar/desactivar plan objetivo + "Salud vs mercado actual" (refresh de precios + delta). **Fase D:** generar/regenerar narrativa IA del snapshot (persistida) + factores macro + "Cargar plan en Optimizer/Simulaciones". | UI de orquestación / persistencia / activación / narrativa de planes |
| `data/plan_store.py` | Persistencia de escenarios (Fase B/C): `PlanSnapshot` (resumen JSON-serializable: allocation, core, metrics, goals, mc_summary, narrative, personal; **Fase C:** `last_refreshed_at`, `refreshed_metrics`, `macro_risks`, `price_at_save` por ticker, helper `target_weights()`) + `PlanStore`/`plan_store` (`upsert`/`get`/`list`/`delete`). JSON en `data/retirement_plans.json`. | Cambiar qué se persiste de un plan |
| `data/plan_context.py` | **Fase C** (Streamlit-free): resolver/activar/desactivar el plan activo (`get_active_plan`, `activate_plan`, `deactivate_plan`, `is_active`) + `compute_plan_vs_reality()` (delta de precio hoy vs guardado, con `price_lookup` inyectable). **Fase E:** `compute_alignment_trades()` — trades priorizados (núcleo primero) para alinear el tracker con los `target_weights()` del plan. **Fase H.2:** `record_plan_health`/`get_plan_health_history`/`compute_longitudinal_drift`. **Fase H.4:** `list_sample_plans`/`load_sample_plan` (demo mode, reusa `import_plan_from_dict`). Reusado por dashboard y scheduler. | Lógica de "plan vivo" / deltas / trades / salud / ejemplos |
| `data/plan_health.py` | **Fase H.2** (Streamlit-free): `PlanHealthRecord` + `PlanHealthStore`/`plan_health_store` (JSON `data/plan_health_history.json`, dedup por día, cap de registros). Historial longitudinal de salud del plan | Cambiar qué se registra del historial de salud |
| `data/sample_plans/*.json` | **Fase H.4**: 3 planes de ejemplo (conservador 30y / FIRE moderado / retiro AR con ADRs) que muestran las 3 estrategias de decumulación. Cargados vía `list_sample_plans`/`load_sample_plan` | Agregar/editar planes de ejemplo (demo mode) |
| `data/preferences.py` | `UserPreferences` (JSON): prefs de optimizer/universo/watchlist + **perfil personal** (edad, capital, ahorro, tolerancia, meta) + **`active_plan_id`** (Fase C, con `set_active_plan`/`clear_active_plan`) con helpers derivados | Agregar campo de preferencia o de perfil personal |
| `dashboard/pages/7_Simulaciones.py` | Página principal de simulaciones (MC, Stress, Custom, Comparar, Metas) | UI de simulaciones |
| `dashboard/pages/5_Optimizer.py` | Página del Optimizer con Goal-Aware + Glide Path | UI del optimizer |
| `alerts/engine.py` | Checks de alerta, cooldowns, dispatch. Incluye `check_plan_health_degradation` (Fase H.2, `AlertType.PLAN_HEALTH_DEGRADATION`) | Agregar nuevo tipo de alerta |
| `data/db/retirement_advisor.db` | SQLite: price cache + posiciones + moat AI cache + alert state | Solo via SQLAlchemy |

---

## 5. Estándares de Código

- **Cache en dashboard**: todas las funciones del dashboard usan `@st.cache_data`
- **Hashability del cache**: parámetros de simulación se pasan como **tuplas** (no listas) para que Streamlit pueda hashear
- **Config AI en dashboard**: usar `_get_ai_config()` de `dashboard/shared.py` para resolver config desde `session_state`
- **Venv**: ejecutar con `./venv/bin/python3` (no `python3` del sistema)
- **Logging**: usar `loguru` (`from loguru import logger`), no `print()` ni `logging` estándar
- **SQLite**: solo via SQLAlchemy — no consultas SQL raw directas
- **Thresholds**: nunca hardcodear números en el código de análisis — usar las constantes de `config.py`
- **Tests**: `./venv/bin/python3 -m pytest tests/` — deben pasar sin regresiones antes de cualquier merge
- **Sin async**: el proyecto es síncrono; no introducir `asyncio` sin discutir primero

---

## 6. Estado Actual de Features

| Feature | Estado | Módulos clave |
|---------|--------|---------------|
| Análisis Fundamental (5 dimensiones) | ✅ Completo | `analysis/fundamental.py`, `analysis/scoring.py` |
| Consistency Score + Piotroski | ✅ Completo | `analysis/scoring.py` |
| Economic Moat (cuantitativo + AI) | ✅ Completo | `analysis/moat.py` |
| Análisis Técnico | ✅ Completo | `analysis/technical.py` |
| AI Decision Layer (4 proveedores) | ✅ Completo | `analysis/ai_analyzer.py`, `analysis/prompts.py`. Incluye salida estructurada `macro_factors` (0-2 factores) + voz libre en `reasoning`. Decision/MoatDetail/CryptoMoatDetail exponen los campos. |
| Backtesting Engine | ✅ Completo | `analysis/backtesting.py` |
| Portfolio Optimizer (SLSQP + 3 perfiles) | ✅ Completo | `portfolio/optimizer.py` |
| Goal-Aware Optimizer + Glide Path | ✅ Completo (Fase 2) | `portfolio/optimizer.py`, `dashboard/pages/5_Optimizer.py` |
| Monte Carlo (block-bootstrap + SORR) | ✅ Completo | `portfolio/monte_carlo.py` |
| Multi-Goal Planner ("Mis Metas") | ✅ Completo (Fase 1) | `portfolio/goals.py`, `dashboard/pages/7_Simulaciones.py` |
| Presets de escenario (FIRE, Casa, etc.) | ✅ Completo (Fase 0) | `dashboard/pages/7_Simulaciones.py` |
| Narrativa AI "Explicame este plan" | ✅ Completo (Fase 0) | `analysis/ai_analyzer.py`, `analysis/prompts.py` |
| Sistema de Alertas (email + Telegram) | ✅ Completo | `alerts/` |
| PDF Reports | ✅ Completo | `alerts/reporter.py` |
| Crypto Analysis (BTC, ETH) | ✅ Completo | `analysis/crypto_analyzer.py` (incluye `CryptoMoatDetail` con `macro_factors` estructurados) + `analysis/moat.py` (`CryptoMoatConfig`) |
| Recomendación de asignación (Grok Fase 1) + macro estructurado | ✅ Completo | `analysis/ai_analyzer.py`, `analysis/prompts.py` (ahora con `macro_factors` explícitos que influyen en la asignación recomendada) |
| Onboarding Wizard (perfil personal) | ✅ Completo (Fase A) | `dashboard/onboarding.py`, `data/preferences.py`, `dashboard/shared.py` (`get_user_prefs`, `seed_session_defaults_from_profile`) |
| Mi Plan de Retiro (orquestación + persistencia de escenarios) | ✅ Completo (Fase B) | `dashboard/pages/12_Plan.py`, `data/plan_store.py` (`PlanSnapshot`, `plan_store`) |
| Plan como objetivo vivo (activar + delta de mercado + drift atado al plan) | ✅ Completo (Fase C) | `data/plan_context.py`, `data/preferences.py` (`active_plan_id`), `alerts/portfolio_alerts.py` + `alerts/engine.py` (`target_weights`), `scripts/run_scheduler.py`, `dashboard/pages/12_Plan.py` + `3_Portfolio.py` |
| AI Narrativa del plan guardado + `macro_risks` a nivel cartera + cargar plan (what-if) | ✅ Completo (Fase D) | `analysis/prompts.py` (`plan_level_narrative_prompt`), `analysis/ai_analyzer.py` (`generate_plan_narrative`), `dashboard/pages/12_Plan.py` |
| Flujo guiado Onboarding → Plan Activado (journey 4 pasos + CTAs) | ✅ Completo (Fase E) | `dashboard/shared.py` (`plan_journey_status`), `dashboard/app.py` (home), `dashboard/pages/12_Plan.py` (empty state), CTAs en `5_Optimizer.py` + `7_Simulaciones.py` |
| Trades sugeridos de alineación plan vs tracker | ✅ Completo (Fase E) | `data/plan_context.py` (`compute_alignment_trades`), `dashboard/pages/3_Portfolio.py` + `12_Plan.py`, `config.py` (`ALERTS.alignment_*`) |
| Data quality por ticker (completitud + frescura de cache) | ✅ Completo (Fase E) | `analysis/fundamental.py` (`compute_data_quality`, `FundamentalResult.data_quality`), `data/cache.py` (`get_age_hours`), `data/fetcher.py` (`get_info_age_hours`), `config.py` (`DATA_QUALITY`), badges en Screener + salud del plan |
| Colas de viento sector-país (tailwinds curados + AI opcional) | ✅ Completo (Fase F) | `analysis/tailwind.py`, `data/tailwinds/sector_country.json`, `config.py` (`TAILWINDS`), integrado en `fundamental.py` (adjusted_score), `strategy.py`, `optimizer.py` (campos + ER tilt), `plan_store.py`, prompts (decision/optimizer/plan + `sector_country_tailwind_prompt`), UI (Screener "Viento", Stock Analysis, Optimizer, Mi Plan) |
| Transparencia de supuestos + drags económicos (fee/tax/rebal/buffer AR) | ✅ Completo (Fase G — Item 1) | `config.py` (`EconomicDragConfig`, `DRAGS`), `portfolio/monte_carlo.py` (`run(drags=...)`, base vs con-drags), `dashboard/shared.py` (`get_economic_drags`, `render_drags_controls`, `render_assumptions_disclaimer`, `ASSUMPTIONS_TEXT`), UI en `7_Simulaciones.py` + `12_Plan.py`, captura en `plan_store.py` (`drags_at_save`), PDF (`reports/investment_plan.py`), narrativa (`analysis/prompts.py`), disclaimers en `app.py` + `10_About.py`. Opt-in a nivel motor → cero regresiones |
| Plan portable (export/import JSON versionado) + journey de backup | ✅ Completo (Fase G — Item 2) | `data/plan_context.py` (`import_plan_from_dict`), `dashboard/shared.py` (`export_plan_bundle`, paso "Respaldá tu plan" en `plan_journey_status`), `12_Plan.py` (download + uploader), `plan_store.py` (`export_version`/`export_notes`), nudge en `app.py` |
| Resiliencia de datos + custom tickers seguros | ✅ Completo (Fase G — Item 3) | `data/preferences.py` (`custom_tickers` + `add/remove/custom_symbols`), `data/universe_loader.py` (`get_effective_universe`), `data/snapshot.py` (export snapshot offline), `dashboard/shared.py` (`load_universe_with_customs`, `custom_source_badge`), UI en `9_Settings.py` + columna Fuente/warnings en `1_Screener.py` + `5_Optimizer.py` |
| Motor de decumulación + withdrawal strategies (fixed_real/constant_pct/guardrails) | ✅ Completo (Fase H.1) | `config.py` (`WithdrawalConfig`, `WITHDRAWAL`), `portfolio/decumulation.py`, `portfolio/monte_carlo.py` (`run(withdrawal_strategy=, longevity_years=)` + métricas), `plan_store.py` (`withdrawal_strategy`), `dashboard/shared.py` (`render_withdrawal_controls`, etc.), UI en `7_Simulaciones.py` + `12_Plan.py`, narrativa en `prompts.py`. Opt-in → base byte-idéntico |
| Historial longitudinal de salud del plan + alerta de degradación | ✅ Completo (Fase H.2) | `config.py` (`PlanHealthConfig`, `HEALTH`), `data/plan_health.py`, `data/plan_context.py` (`record_plan_health`/`get_plan_health_history`/`compute_longitudinal_drift`), `alerts/engine.py` + `alerts/store.py` (`PLAN_HEALTH_DEGRADATION`), `scripts/run_scheduler.py` (auto-record opt-in), UI "📊 Evolución" en `12_Plan.py` |
| Laboratorio de sensibilidad + escenarios (what-if) | ✅ Completo (Fase H.3) | `config.py` (`SensitivityConfig`, `SENSITIVITY`), `portfolio/sensitivity.py` (`run_sensitivity`/`tornado_rows`), `dashboard/shared.py` (`run_plan_sensitivity`), sección "🔬 Sensibilidad" en `7_Simulaciones.py` (tornado Plotly + escenarios) |
| Adopción: planes de ejemplo + packaging + PDF de retiro | ✅ Completo (Fase H.4) | `data/sample_plans/*.json` + `list_sample_plans`/`load_sample_plan`, recuadro demo en `12_Plan.py`, `run.sh` + `Makefile` + README ("Probar en 5 min"), CI matrix 3.11/3.12 + `Dockerfile` 3.12, sección de decumulación en `reports/investment_plan.py` |
| Escenario realista vs conservador en Monte Carlo (transparencia del haircut) | ✅ Completo (Fase J) | `portfolio/monte_carlo.py` (`run(include_realistic_reference=...)` + campos `realistic_*` en `MonteCarloResult`: re-corre el bootstrap sobre los retornos **crudos** sin el haircut conservador, re-seedeando para usar las **mismas tiradas** → comparación apples-to-apples; opt-in → base byte-idéntico), `dashboard/shared.py` (`cached_monte_carlo(include_realistic_reference=True)` por defecto), UI en `7_Simulaciones.py` (caja "Realista vs Conservador": mediana + pesimista p10) y `12_Plan.py` (línea de referencia). **Fix D (doble penalización AR):** advertencia en el control de buffer AR (`render_drags_controls`) + nota en `EconomicDragConfig.ar_buffer_pct` para no contar el riesgo argentino dos veces (ya descontado vía `ars_risk_discount` en el optimizer). +4 tests (`TestRealisticReference` en `test_monte_carlo.py`). Suite: **512 pasando** |
| Ola 1 UX (menú por intención + modo dev, anti pantallas-en-blanco, "Hoy hacé esto", procedencia 📊/🤖, resultado accionable) | ✅ Completo (Ola 1) | `dashboard/app.py`, `dashboard/shared.py` (`is_dev_mode`, `next_priority_action`, `render_calc_badge`/`render_ai_badge`), `pages/{1_Screener,2_Stock_Analysis,5_Optimizer,7_Simulaciones,9_Settings,12_Plan,13_Track_Record,15_Comite,18_Chat}.py`. **Solo UI — sin cambios al motor.** |
| Comité de Inversión por ticker (panel multi-agente con disenso) | ✅ Completo | `analysis/committee.py`, `analysis/committee_prompts.py`, `dashboard/pages/15_Comite.py`, `config.py` (`CommitteeConfig`/`COMMITTEE`) |
| Comité de Inversión sobre el PORTFOLIO ACTUAL ("Dictamen del comité sobre tu portfolio") | ✅ Completo | `analysis/committee.py` (`analyze_portfolio`, `build_holdings_committee_context`, `portfolio_concentration`; `aggregate(weights=…)`; `build_portfolio_committee_context` queda como helper genérico), `analysis/committee_prompts.py` (4 prompts a nivel cartera + `portfolio_committee_context_block` con secciones condicionales), `config.py` (`portfolio_vote_weights`/`portfolio_action_labels`), `dashboard/shared.py` (`run_holdings_committee`, `render_committee_verdict`), sección en **`dashboard/pages/3_Portfolio.py`**. Evalúa las **posiciones reales**: riesgo realizado (Sharpe/beta/maxDD), concentración, crisis (stress test) y **desvío vs el plan activo**. **Interpreta, no recalcula; opt-in con IA. +12 tests** |
| Análisis de sizing del Libro Personal (concentración como ventaja) | ✅ Completo (Fase I) | `config.py` (`PersonalBookConfig`, `PERSONAL_BOOK`), `portfolio/personal_sizer.py` (motor rule-based puro, `analyze_personal_book` con `enrich_fn` inyectable + dataclasses `SizingRecommendation`/`PersonalBookAnalysis`), `data/personal_book_convictions.py` (store JSON de convicciones HIGH/MED/LOW), `dashboard/shared.py` (`cached_personal_book_analysis`), sección integrada en `dashboard/pages/3_Portfolio.py` (form de convicciones + KPIs de concentración + cards con tesis + export JSON), `tests/test_personal_sizer.py` (15 casos). **Vive en paralelo al optimizer de retiro — cero regresiones; modela explícitamente la libertad de concentración del individuo vs fondos.** |

---

## 7. config.py — Fuente de Verdad

`config.py` es el único lugar donde se definen parámetros. **Nunca hardcodear valores en el código de análisis.**

### Dataclasses principales

| Clase | Descripción |
|-------|-------------|
| `FundamentalThresholds` | 25+ umbrales de scoring (ROE, ROIC, márgenes, ratios de deuda, valuación, crecimiento, dividendos) |
| `StrategyConfig` | Score mínimos por señal: `strong_buy=75`, `buy=60`, `hold=45`, `margin_of_safety=10%` |
| `AIConfig` | Proveedor (claude/grok/openai), modelo, API key, flags `enabled` y `use_in_screener` |
| `ConsistencyThresholds` | Std máxima de ROE y márgenes para Consistency Score |
| `PiotroskiConfig` | Umbral F-Score para bonus (strong ≥ 7) |
| `BacktestConfig` | Período default (5y), benchmark, risk-free rate (4.5%), mínimo historial (52 semanas) |
| `MoatConfig` | Umbrales Wide ≥14 / Narrow ≥8 / Minimal ≥4, TTL caché AI (7 días) |
| `CryptoMoatConfig` | Umbrales moat AI para crypto: Wide ≥6.0, Narrow ≥4.0 |
| `ProfileConfig` | Constraints del optimizer por perfil (max_position%, vol, dividend yield, etc.) |
| `OptimizerConfig` | risk_free_rate=4.5%, price_history=2y, default_profile |
| `MonteCarloConfig` | `vol_adjustment=+10%`, `mean_haircut=-20%`, `n_sims=10000` default |
| `AlertConfig` | Email/Telegram config, frecuencia, umbrales de severidad |
| `ReportConfig` | Directorio PDF, inclusión de charts, cadencia de reportes |
| `DataQualityConfig` | Fase E: `stale_warning_hours=48`, `partial_missing_fields=3`, `poor_missing_fields=6` |
| `TailwindConfig` | Fase F: thresholds Strong ≥6 / Moderate ≥3 / Headwind ≤−2, `bonus = clamp(score×0.8, ±8)`, `optimizer_er_tilt=0.05`, TTL cache AI 720h, `enabled` master switch, `data_file` |
| `EconomicDragConfig` | Fase G: drags anuales `annual_fee_pct=0.20`, `dividend_tax_drag_pct=0.0`, `rebalance_cost_annual_pct=0.05`, `ar_buffer_pct=0.0`, `enabled`. Métodos `total_annual_drag_pct()`/`as_dict()`. Opt-in en el motor MC |
| `WithdrawalConfig` | Fase H.1: estrategia de decumulación `default_strategy`, `base_withdrawal_pct=4.0`, `constant_pct=4.0`, bandas/pasos de guardrails (`guardrail_ceiling_band/floor_band/cut_pct/raise_pct`), `default_longevity_years=30` |
| `PlanHealthConfig` | Fase H.2: `enabled`, `auto_record=False`, `max_records=60`, `min_days_between_records=1`, `degradation_drift_pct=15.0`, `degradation_min_records=2` |
| `SensitivityConfig` | Fase H.3: deltas de factores (`inflation_delta_pct=1.0`, `fee_drag_delta_pct=0.30`, `real_return_delta=0.10`, `vol_delta=0.10`, `longevity_delta_years=5`), `full_drag_pct=1.0`, `n_sims=2000` (lab liviano) |
| `PersonalBookConfig` | Fase I: thresholds de sizing del **libro personal** (NO retiro). `core_high_conviction_max_pct=30`, `trim_concentration_threshold_pct=25`, `max_practical_concentration_single_name=40`, `min_score_for_core_concentration=72`, `aggressive/moderate_accumulate_weight_pct`, `sell_all_score=40`, `drawdown_shock_pct=35`, ponderación de los 4 ejes (45/20/20/15). Modela la **libertad de concentración** del individuo vs fondos. Opt-in (`enabled`) |

### Singletons module-level (usar estos, no instanciar nuevas clases)

```python
THRESHOLDS    # FundamentalThresholds
STRATEGY      # StrategyConfig
PERSONAL_BOOK # PersonalBookConfig (Fase I — sizing libro personal, opt-in)
ALERTS        # AlertConfig
AI_CONFIG     # AIConfig
CONSISTENCY   # ConsistencyThresholds
PIOTROSKI     # PiotroskiConfig
BACKTEST      # BacktestConfig
MOAT          # MoatConfig
CRYPTO_MOAT   # CryptoMoatConfig
OPTIMIZER     # OptimizerConfig
REPORT        # ReportConfig
MONTE_CARLO   # MonteCarloConfig
DATA_QUALITY  # DataQualityConfig (Fase E)
TAILWINDS     # TailwindConfig (Fase F)
DRAGS         # EconomicDragConfig (Fase G — drags económicos)
WITHDRAWAL    # WithdrawalConfig (Fase H.1 — decumulación)
HEALTH        # PlanHealthConfig (Fase H.2 — historial de salud)
SENSITIVITY   # SensitivityConfig (Fase H.3 — laboratorio what-if)
OPTIMIZER_PROFILES  # Dict[str, ProfileConfig]
```

### Constantes clave

- `DEFAULT_TICKERS` — 38 tickers (US mega-caps, ADRs argentinos, ETFs, crypto)
- `CRYPTO_TICKERS` — {BTC, BTC-USD, BITCOIN, ETH, ETH-USD, ETHEREUM}
- `TICKER_ALIASES` — mapeo de nombres (BTC→BTC-USD, etc.)
- `SECTOR_MAP` — 10 sectores

---

## 8. Limitaciones Conocidas

- **EMFILE (mitigado)**: El screener puede agotar file descriptors — `max_workers` controlado, `NullPool` en SQLAlchemy. El logger de Streamlit también acumulaba sinks en cada rerun; ya corregido con `_ensure_logger()` (guard en `session_state`) en `dashboard/app.py`
- **Supuestos por defecto (drags)**: Las proyecciones asumen 0% fees/impuestos/rebalanceo salvo que el usuario active la capa de drags (Fase G, `DRAGS` + `render_drags_controls`). Los drags son **opt-in a nivel motor** (`MonteCarloSimulator.run(drags=...)`): sin drags, los números son byte-idénticos al estado previo. El caso base se conserva siempre como referencia (`base_*` en `MonteCarloResult`/`mc_summary`)
- **yfinance única fuente (mitigado parcialmente)**: No hay fallback real; se mitiga con badges de calidad de datos y export de snapshot del universo (`data/snapshot.py`) para backup/offline. No hay retry automático; si falla un ticker, se loggea y se continúa
- **Custom tickers experimentales**: Los tickers agregados por el usuario (`UserPreferences.custom_tickers`) se mergean vía `get_effective_universe`, pero quedan marcados ⚠️ Custom con calidad de datos parcial y el optimizer los trata con cautela
- **Moat AI cache**: 7 días de TTL; si el modelo AI cambia, el cache puede estar desactualizado (borrar `data/db/retirement_advisor.db` para reset)
- **ADRs argentinos**: Se aplica `ARS risk discount` (0.85×) automáticamente en perfiles Conservador/Moderado
- **Sin datos intraday**: Toda la simulación MC usa retornos semanales (10 años de historia)
- **Streamlit hot-reload**: Algunas instancias de clases (ej. Portfolio) pueden quedar stale tras hot-reload — hay guards `hasattr` para auto-reparar
- **KaTeX rendering**: Streamlit puede interpretar `$` en markdown como LaTeX — escapar `\$` en strings de montos
- **Convención de retiros (decumulación, Fase H.1)**: las estrategias restan el retiro de la semana del año en adelante sobre el path ya acumulado (igual que el `_apply_withdrawals` legacy). `prob_sustain_real_pct` mide "nunca tocó 0" y `prob_legacy_pct` "queda capital al final" — pueden diferir. `fixed_real` con el mismo monto + inflación es byte-idéntico al motor previo
- **Historial de salud (Fase H.2)**: `avg_score_then` es el score **al guardar** (constante entre registros del mismo snapshot); la deriva longitudinal se mide sobre `weighted_delta_pct` (precio hoy vs guardado). El auto-registro del scheduler es opt-in (`HEALTH.auto_record=False` por defecto)
- **Mercado adverso en sensibilidad (Fase H.3)**: el escenario aproxima un mercado malo bajando `return_scale` y subiendo `vol_scale` (no modela un cambio estructural de régimen ni "5 años planos" explícitos). Inflación solo impacta si hay retiros activos
- **El sesgo conservador no baja todo parejo (Fase J)**: el haircut conservador (`vol_adjustment=+10%`, `mean_haircut=−20%`) reduce la mediana y, sobre todo, el piso pesimista (p10), pero como **infla la volatilidad** puede *ensanchar* el escenario optimista (p90 conservador a veces > p90 realista). Por eso la comparación "Realista vs Conservador" en la UI muestra **mediana + p10** (no p90, que confundiría). La referencia realista usa retornos crudos = bootstrap del historial 2010-2024 (optimista por construcción): es un techo de referencia, no un pronóstico
- **Doble conteo de riesgo argentino (Fase J — mitigado por doc)**: `OptimizerConfig.ars_risk_discount` (0.85×) ya inclina la asignación lejos de ADRs AR; `EconomicDragConfig.ar_buffer_pct` también penaliza riesgo país a nivel proyección. No se fusionaron en código (siguen midiendo ejes distintos: selección vs proyección) pero el buffer AR queda documentado y con warning en UI para usarse en 0 cuando el descuento de score ya cumple esa función

---

## 9. Últimos Cambios Importantes

| Commit | Cambio |
|--------|--------|
| `(pending)` | **Comité de Inversión sobre el PORTFOLIO ACTUAL ("Dictamen del comité sobre tu portfolio")**: extiende el comité por-ticker a debatir las **posiciones reales del tracker**, reutilizando >90% del motor (orquestación paralela, agregación determinística, caché SQLite, schema JSON). **Principio: interpreta, no calcula** — cita números ya existentes (riesgo realizado, concentración, stress test, desvío vs plan, macro), nunca recalcula; el portfolio real no tiene proyección a futuro. **(1)** `config.py`: `CommitteeConfig` gana `portfolio_vote_weights` (4 roles) y `portfolio_action_labels` (stance→salud de la cartera: STRONG BUY→"Plan muy sólido" … SELL→"Reestructurar"). **(2)** `analysis/committee_prompts.py`: `portfolio_committee_context_block(ctx)` (secciones condicionales: realizado, proyección, concentración, crisis, alineación, macro) + 4 prompts (**Estratega del Plan**, **Gestor de Riesgo**, **Estratega Macro**, **Abogado del Diablo** — nombre exacto preservado para el disenso siempre-presente) reencuadrados a "tu portfolio actual". **(3)** `analysis/committee.py`: `analyze_portfolio(ctx, plan_key)` (reusa `_run_agents` + caché `committee:portfolio:{plan_key}:{prov}:{model}`), `build_holdings_committee_context(...)` (real holdings: realized + concentración + crisis + alineación), `portfolio_concentration(weights)` (máx/top-3/posiciones efectivas 1/HHI), `aggregate(..., weights=…)` (opcional, backward-compat); `build_portfolio_committee_context(...)` queda como helper genérico. **(4)** `dashboard/shared.py`: `run_holdings_committee(metrics, sector_weights, position_weights, total_value, active_plan)` (corre `cached_stress_test` + `compute_alignment_trades` para la deriva + macro; cachea por hash de las tenencias; `None` si IA off) + `render_committee_verdict(...)`. **(5)** UI en **`dashboard/pages/3_Portfolio.py`** (no Mi Plan): botón "🏛️ Convocar al comité" opt-in, banner con etiqueta + acuerdo X/4, consenso/disenso, expander por agente, badges 📊/🤖, pie con Sharpe/beta/maxDD/posición máx. No se loguea al Track Record (es por-ticker). +12 tests (`tests/test_portfolio_committee.py`). Suite: **524 pasando, sin regresiones**. _(Nota: una primera iteración apuntó al plan propuesto en Mi Plan; corregido para evaluar el portfolio real.)_ |
| `(pending)` | **Ola 1 UX — que la potencia existente se encuentre, se entienda y se use** (basada en `docs/brainstorm/99_PRIORIZACION.md`; dirección: producto local/un usuario en Streamlit; **solo UI — no toca el motor de cálculo → cero regresiones, 512 tests**). **(A) Menú por intención + modo dev:** `st.navigation` reagrupado en *(Inicio+Chat)·Mi dinero·Investigar·Proyectar·Seguimiento·Ajustes*; Eval IA / Calidad de Datos / Macro RAG salen del menú diario y aparecen solo con `is_dev_mode()` (env `DEV_MODE` o toggle nuevo en `9_Settings.py`). **(B) Pantallas en blanco:** Screener muestra la última corrida cacheada (`screener_rows*` en session_state) y re-analiza solo con Refresh; barra de progreso en español; Chat con preguntas sugeridas clicables (`_chat_pending`); botón "Probar con un plan de ejemplo" en la portada (reusa `load_sample_plan_into_store` + `activate_plan`); Comité con estado guía en vez de vacío. **(C) Plan en el centro:** "Hoy hacé esto" en la portada (`next_priority_action` en shared — journey → alertas sin leer → plan stale → ok; sin fetch de precios) + resumen del plan activo con métricas guardadas. **(D) Transparencia visible:** etiquetas `📊 Calculado` / `🤖 Interpretación IA` (`render_calc_badge`/`render_ai_badge`/`CALC_BADGE`/`AI_BADGE` en shared) en Chat, Stock Analysis y Mi Plan (Realista-vs-Conservador y badge de calidad en Screener ya existían). **(E) Resultado accionable:** tesis (3 a favor / 3 riesgos) arriba en Stock Analysis; conclusión "En una frase" en Optimizer; frase resumen honesta en Track Record; palancas "hacé esto" en Simulaciones cuando la meta queda <70%. Archivos: `dashboard/app.py`, `dashboard/shared.py`, `pages/{1_Screener,2_Stock_Analysis,5_Optimizer,7_Simulaciones,9_Settings,12_Plan,13_Track_Record,15_Comite,18_Chat}.py`. Roadmap posterior (no en esta ola): fusionar pantallas que se solapan, flujo único meta→cartera→simulación→plan, módulos AR Doble Moneda + Impuestos. |
| `(pending)` | **Fase J — Transparencia del sesgo conservador (escenario realista vs conservador)**: el motor MC siempre aplicaba un haircut conservador (`vol_adjustment=+10%`, `mean_haircut=−20%`) y lo apilaba con drags y descuento ARS, pintando un futuro más pobre que el más probable y empujando a sobre-ahorrar o subestimar la meta. **(B)** Nuevo opt-in `MonteCarloSimulator.run(include_realistic_reference=True)` + campos `realistic_median_terminal/p10/p90/prob_achieve_target_pct` y `realistic_reference_applied` en `MonteCarloResult`: corre una segunda pasada compacta sobre los retornos **crudos** (sin haircut), re-seedeando con el mismo seed para replicar las **mismas tiradas** del bootstrap → la única diferencia es el haircut (apples-to-apples). `cached_monte_carlo` lo pasa con default `True`; UI en `7_Simulaciones.py` (caja "Realista vs Conservador" con mediana + pesimista p10) y `12_Plan.py` (línea de referencia). Opt-in a nivel motor → con la flag apagada el resultado es byte-idéntico. **(D)** Fix doble penalización AR: warning en el control de buffer AR (`render_drags_controls`, importa `OPTIMIZER`) + nota anti-doble-conteo en `EconomicDragConfig.ar_buffer_pct`. Hallazgo documentado (§8): el haircut no baja todo parejo — inflar vol ensancha el p90, por eso la UI compara mediana+p10, no p90. +4 tests (`TestRealisticReference`). Suite: **512 pasando, sin regresiones**. |
| `(pending)` | **Fase H — Plan de Retiro como SO Personal (4 pilares, >80% infra reutilizada, todo opt-in → base byte-idéntico)**: **(H.1) Decumulación** — `WithdrawalConfig`/`WITHDRAWAL`; nuevo `portfolio/decumulation.py` (`WithdrawalStrategy` fixed_real/constant_pct/guardrails + `apply_withdrawal_strategy` + `decumulation_metrics`); `monte_carlo.run(withdrawal_strategy=, longevity_years=)` + métricas (`prob_sustain_real_pct`, `prob_legacy_pct`, `median_legacy`, `expected_depletion_year`); `PlanSnapshot.withdrawal_strategy`; UI en `shared.py`/`7_Simulaciones.py`/`12_Plan.py`; narrativa en `prompts.py`. **(H.2) Historial de salud** — `PlanHealthConfig`/`HEALTH`; nuevo `data/plan_health.py` (`PlanHealthRecord`/`PlanHealthStore`); `plan_context` (`record_plan_health`/`get_plan_health_history`/`compute_longitudinal_drift`); `AlertType.PLAN_HEALTH_DEGRADATION` + `check_plan_health_degradation` + scheduler auto-record opt-in; sección "📊 Evolución" en `12_Plan.py`. **(H.3) Sensibilidad** — `SensitivityConfig`/`SENSITIVITY`; nuevo `portfolio/sensitivity.py` (`run_sensitivity` tornado 4 factores + escenarios, `tornado_rows`); `run_plan_sensitivity` en shared; sección "🔬 Sensibilidad" en `7_Simulaciones.py`. **(H.4) Adopción** — `data/sample_plans/*.json` (3 ejemplos) + `list_sample_plans`/`load_sample_plan` + demo en `12_Plan.py`; `run.sh`/`Makefile`/README "Probar en 5 min"; CI matrix 3.11/3.12 + Dockerfile 3.12; sección de decumulación en el PDF. +nuevos `test_decumulation.py`, `test_sensitivity.py`, `test_plan_health.py` + extensiones. Suite: **419 pasando, sin regresiones**. Ver ROADMAP Fase H. |
| `(pending)` | **Fase G — Remediaciones P0 (3 items, reutilizando >80% de la infra)**: **(1) Transparencia de supuestos + drags económicos** — `EconomicDragConfig`/`DRAGS` en config; `MonteCarloSimulator.run(drags=...)` aplica drag anual compuesto semanalmente (exacto) y expone base vs con-drags; helpers en `shared.py` (`get_economic_drags`, `render_drags_controls`, `render_assumptions_disclaimer`, `ASSUMPTIONS_TEXT`); UI en `7_Simulaciones.py`+`12_Plan.py`; `PlanSnapshot.drags_at_save` + base_* en mc_summary; PDF (`reports/investment_plan.py`); narrativa (`prompts.py`); disclaimers en `app.py`+`10_About.py`. **Opt-in a nivel motor → cero regresiones**. **(2) Plan portable** — `import_plan_from_dict` (puro) + `export_plan_bundle` (JSON versionado + instrucciones); export/import en `12_Plan.py`; `export_version`/`export_notes`; paso "Respaldá tu plan" en journey + nudge en Home. **(3) Resiliencia + custom tickers** — `UserPreferences.custom_tickers` (+helpers), `get_effective_universe`, `data/snapshot.py` (export offline), `load_universe_with_customs`/`custom_source_badge` en shared, UI en `9_Settings.py` + columna Fuente/warnings en Screener+Optimizer. +nuevos tests (`test_monte_carlo`, `test_plan_store`, `test_plan_context`, `test_preferences`, `test_snapshot.py` nuevo). Suite: **351 pasando, sin regresiones**. Ver ROADMAP Fase G. |
| `(pending)` | **Fase F — Colas de Viento Industria-País (Tailwinds, Idea 2)**: contexto estructural sector-país como input first-class, curado y auditable (caso canónico: Vaca Muerta / energía argentina). Nuevo `analysis/tailwind.py` (`TailwindAnalyzer`: curado siempre + AI opcional cacheada 30d que **solo interpreta**, nunca inventa ni cambia el score) + `data/tailwinds/sector_country.json` (fuente de verdad editable) + `TailwindConfig`/`TAILWINDS` en config. `FundamentalResult` gana `tailwind_score/bonus/classification/detail`; `adjusted_score` suma `tailwind_bonus` (clamp [0,100], cap ±8 < moat). Rationale/risks en `Decision` rule-based; `TickerAllocation` extendido + ER tilt chico (≤±0.9%) en optimizer; `PlanSnapshot.from_session` persiste tailwinds solo cuando son materiales (backward compat total). Prompts: `_tailwind_context_block` (equity decision), `tailwind=` en optimizer advice, sección en `plan_level_narrative_prompt`, nuevo `sector_country_tailwind_prompt`. UI: columna "Viento" (Screener + Optimizer, `tailwind_badge` en shared), expander en Stock Analysis, sección 🌬️ en Mi Plan. Guardrail: sin datos curados / todo Neutral ⇒ números idénticos al pre-feature; apagable con `TAILWINDS.enabled=False`. +40 tests (`test_tailwind.py` nuevo). Suite: **320 pasando**. Ver ROADMAP Fase F. |
| `(pending)` | **Fase E — Alto Impacto Post-Plan Vivo (adopción + acción + confianza)**: (A) flujo guiado "de cero a plan activo" — `plan_journey_status()` en `dashboard/shared.py`, bloque de progreso 4 pasos en Home con botón al próximo paso, empty state guiado en `12_Plan.py`, CTAs hacia Mi Plan en Optimizer/Simulaciones. (B) trades sugeridos de alineación — `compute_alignment_trades()` (pura, inyectable) en `data/plan_context.py`, prioriza núcleo, umbrales nuevos `ALERTS.alignment_min_trade_usd`/`alignment_max_trades`; UI en Portfolio (expander en Alineación) y en el visor del plan activo en `12_Plan.py`. (C) data quality — `DataQualityConfig`/`DATA_QUALITY` en config, `DataCache.get_age_hours()` + `get_info_age_hours()`, `compute_data_quality()` + campo `FundamentalResult.data_quality`, badge 🟢/🟡/🔴/⏳ (`data_quality_badge` en shared) con columna "Datos" + warning agregado en Screener y aviso de posiciones sin precio en la salud del plan. +19 tests (`test_data_quality.py` nuevo, `test_plan_context.py` ampliado). Suite: **280 pasando**. Ver ROADMAP Fase E. |
| `(pending)` | **Fase B — Mi Plan de Retiro (orquestación + persistencia)**: nueva página `dashboard/pages/12_Plan.py` que consolida el plan de la sesión (cartera optimizada + núcleo determinístico/Grok + métricas + metas + Monte Carlo + narrativa) y permite **guardar/cargar/comparar/borrar** escenarios nombrados. Nuevo `data/plan_store.py` con `PlanSnapshot` (resumen JSON-serializable, NO guarda el `OptimizationResult` completo) + `PlanStore`/`plan_store` (JSON en `data/retirement_plans.json`, patrón de `UserPreferences`). Acciones: lista de compra accionable del núcleo (CSV) y PDF (`InvestmentPlanReport`). Página registrada en nav (grupo Portfolio). +6 tests (`tests/test_plan_store.py`). Construye sobre Fase A (`get_user_prefs`) y reutiliza core+narrativa del Optimizer. |
| `(pending)` | **Fase A — Onboarding / Perfil de Usuario**: `UserPreferences` extendido con perfil personal (`onboarded`, `age`, `retirement_age`, `current_capital`, `monthly_savings`, `risk_tolerance`, `primary_goal_type`, `dividend_preference`) + helpers derivados (`is_onboarded`, `primary_horizon_years`, `annual_savings`, `profile_key`, `apply_personal_profile`). Wizard ligero `dashboard/onboarding.py` (Inicio + Settings). Helpers en `dashboard/shared.py` (`get_user_prefs`, `seed_session_defaults_from_profile`). Consumo como defaults en Optimizer (perfil+capital), Simulaciones (horizonte+capital+form de metas) y Allocation (edad). Backward-compatible. +7 tests (`tests/test_preferences.py`). Fix incidental: `analysis/crypto_analyzer.py` importaba `field` desde `typing` (typo que rompía la colección de tests). |
| `(pending)` | **Mejora estructural contexto macro AI**: `analysis/prompts.py` ahora usa helpers centralizados (`_equity_*_macro_factors`, `_macro_factors_output_spec`, etc.) y produce `macro_factors` (lista estructurada de 0-2 objetos con factor/why/impact/effect) además del `reasoning` en prosa. Actualizados Decision, MoatDetail y CryptoMoatDetail con los nuevos campos. Parsers en ai_analyzer/moat/crypto_analyzer + render en Stock Analysis. Sigue el proceso de MAINTENANCE.md para documentación. |
| `(pending)` | **Optimizer robustez N grande (plan Grok 019e9dff):** profile down-select (`_select_candidates_for_profile`), core determinístico (`_select_core_holdings`), fetch paralelo de precios, instrumentación (n_input/n_eligible/n_candidates/slsqp_success/build_matrix_ms), AI auto-desactivado en screener para N>40, Grok advice siempre retorna core fallback, +32 tests nuevos |
| `(pending)` | Fix EMFILE: logger idempotente en `dashboard/app.py` (`_ensure_logger` con guard en session_state); migración masiva `use_container_width` → `width` (66 ocurrencias, 12 archivos) |
| `33785c5` | Prompts de decisión AI: justificación explícita de `confidence` (HIGH/MEDIUM/LOW) integrada en el campo `reasoning` — equity y crypto |
| `c7717be` | Goal-Aware Optimizer Fase 2 — Glide Path automático en `portfolio/optimizer.py` |
| `9d2d508` | Capturar y exponer recomendación de asignación de Grok (Fase 1 de integración AI) |
| `62cb6e5` | Pulido UX Fase 1 Simulaciones — cards, SORR badge, fan chart |
| `8741d96` | Fix screener: reducir `max_workers` + NullPool para evitar EMFILE |
| `13d84e7` | Multi-Goal Planner + SORR metrics completo (`portfolio/goals.py`) |
| `fb14aac` | Fase 0: presets, narrativa IA, retiros con inflación en Monte Carlo |

### Razonamiento LLM por instancia (documentado en el plan Grok 019e9dff)

- **Screener bulk (N>40):** LLM **NO necesario**. Scoring cuantitativo es suficiente para ranking. Auto-desactivado en dashboard Optimizer cuando `len(selected_universe) > OPTIMIZER.max_ai_screener_tickers`.
- **Price matrix + cov + SLSQP:** LLM completamente innecesario. Math puro.
- **Post-optimización `generate_optimizer_advice`:** LLM SÍ agrega valor para narrativa + síntesis humana. Pero `profile_core_holdings` es siempre calculado determinísticamente (sin LLM) como fallback.
- **Capa de decisión / moat (asset level):** LLM produce tanto el texto libre en `reasoning`/`ai_reasoning` (voz de Grok) como datos estructurados en `macro_factors` (0-2 factores con factor/why_relevant/impact/effect_on_allocation). Los modelos `Decision`, `MoatDetail` y `CryptoMoatDetail` exponen estos campos. El macro ahora es first-class y auditable, no solo texto dentro del reasoning.
- **Principio guía:** LLM = enriquecimiento y usabilidad humana, no motor de cálculo. Path "sin AI" siempre produce portfolio válido + core accionable.

---

## 10. Cómo Actualizar Este Archivo

Este archivo debe actualizarse cuando:
- Se completa una feature grande o una Fase del roadmap
- Cambian thresholds importantes en `config.py`
- Se agrega o elimina un módulo clave
- Cambia la arquitectura del sistema

**Script de ayuda:** `./venv/bin/python3 scripts/refresh_context.py`
Genera bloques de texto para las secciones §7 (config.py) y §9 (últimos cambios) — revisar y pegar manualmente.

Ver `docs/MAINTENANCE.md` para el proceso completo de mantenimiento.
