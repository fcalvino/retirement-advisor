# Estado del Proyecto — Retirement Advisor

## ✅ Todo implementado y en producción (GitHub main)

Este plan describe trabajo **ya completado**. El plan original (AI integration) fue implementado junto con las Fases 1.5, 2 y 3.

---

## Fase H — Plan de Retiro como SO Personal: decumulación, historia, sensibilidad y adopción (2026-06)

Evolución de "construir el plan" a "maximizar su valor como sistema operativo de retiro", reutilizando >80% de la infraestructura existente (Monte Carlo con drags, PlanSnapshot extensible, shared helpers, journey, alertas, config-driven). Todo opt-in y conservador por defecto: con la capa nueva desactivada los números base son **byte-idénticos**. Suite completa: **419 pasando** (+68 sobre las 351 de Fase G), sin regresiones.

**H.1 — Motor de decumulación y withdrawal strategies (core retirement feature):**
- Nuevo `WithdrawalConfig` + singleton `WITHDRAWAL` en `config.py` (estrategia default, tasa base, bandas/pasos de guardrails, longevidad).
- Nuevo `portfolio/decumulation.py` (puro NumPy): `WithdrawalStrategy` (+ `fixed_real`/`constant_pct`/`guardrails`, `coerce`), `apply_withdrawal_strategy` y `decumulation_metrics`. `fixed_real` es byte-idéntico al `_apply_withdrawals` legacy (verificado por test).
- `portfolio/monte_carlo.py`: `run(..., withdrawal_strategy=, longevity_years=)` + métricas de decumulación en `MonteCarloResult` (`prob_sustain_real_pct`, `prob_legacy_pct`, `median_legacy`, `expected_depletion_year`, `longevity_years`). Sin estrategia → números base intactos.
- Persistencia: `PlanSnapshot.withdrawal_strategy` + métricas en `mc_summary` (backward-compat).
- UI: `render_withdrawal_controls`/`get_withdrawal_strategy`/`format_withdrawal_badge` en `shared.py`; sección "¿Cuánto dura tu ingreso?" en `7_Simulaciones.py`; estrategia + resultados en la tarjeta de `12_Plan.py`.
- Narrativa IA: `plan_level_narrative_prompt` describe la estrategia + riesgo de secuencia/longevidad (el LLM solo describe, no inventa reglas).

**H.2 — Historial longitudinal de salud del plan (confianza + detección temprana):**
- Nuevo `PlanHealthConfig` + singleton `HEALTH`. Nuevo `data/plan_health.py`: `PlanHealthRecord` + `PlanHealthStore` (JSON, dedup por día, cap de registros).
- `data/plan_context.py`: `record_plan_health`, `get_plan_health_history`, `compute_longitudinal_drift` (flag `degraded` por deriva sostenida ≥ umbral).
- Alertas: nuevo `AlertType.PLAN_HEALTH_DEGRADATION` + `AlertEngine.check_plan_health_degradation`. `scripts/run_scheduler.py` auto-registra salud (detrás de `HEALTH.auto_record`) y dispara la alerta de "plan envejecido".
- UI: sección "📊 Evolución de tu plan" en `12_Plan.py` (botón registrar, KPIs de tendencia, gráfico deriva/calidad, aviso de degradación, tabla de registros).

**H.3 — Laboratorio de sensibilidad y escenarios (what-if poderoso):**
- Nuevo `SensitivityConfig` + singleton `SENSITIVITY`. Nuevo `portfolio/sensitivity.py` (puro, `run_fn` inyectado): `run_sensitivity` (tornado de 4 factores: inflación, fricciones, retorno, volatilidad) + escenarios predefinidos ("inflación +1pp", "fricciones full", "mercado adverso", "vivir 5 años más") con deltas vs base; `tornado_rows` ordenado por impacto.
- UI: `run_plan_sensitivity` en `shared.py` (sobre `cached_monte_carlo`); sección "🔬 Sensibilidad del plan" en `7_Simulaciones.py` (tornado Plotly + tabla de escenarios, selector de métrica P10/mediana/ruina). El caso base es siempre la corrida actual.

**H.4 — Adopción y distribución (llegar a "plan activo" más fácil):**
- Demo mode: `data/sample_plans/*.json` (3 ejemplos que muestran las 3 estrategias) + `list_sample_plans`/`load_sample_plan` en `plan_context.py` (reutilizan `import_plan_from_dict`) + recuadro "🎁 plan de ejemplo" en el empty-state de `12_Plan.py` (cargar / cargar y activar).
- Packaging: `run.sh` (launcher idempotente), `Makefile` (setup/run/test/lint/check/clean), sección "⚡ Probar en 5 minutos" + Docker mejorado (build + montaje de `data/`) en `README.md`.
- CI/runtime: CI matrix Python 3.11/3.12; `Dockerfile` a `python:3.12-slim`.
- PDF: sección compacta "Estrategia de retiro (decumulación)" en `reports/investment_plan.py` cuando la simulación usó estrategia (acumulación pura → reporte byte-idéntico).

**Tests:** nuevos `test_decumulation.py`, `test_sensitivity.py`, `test_plan_health.py` + extensiones en `test_monte_carlo.py`, `test_plan_store.py`, `test_prompts.py`, `test_plan_context.py`.

**Pendiente (backlog H+):** deep plan compare (diff de supuestos + outcomes entre 2 planes guardados), historial de salud en el PDF, multi-source data, local LLM.

---

## Fase G — Remediaciones P0 post-Fase F (2026-06)

Tres debilidades P0 priorizadas del diagnóstico, atacadas reutilizando >80% de la infraestructura existente (plan vivo, journey, data quality, shared helpers, patrón Tailwind, config-driven). Todo configurable, conservador por defecto, sin romper el path determinístico.

**Item 1 — Transparencia radical de supuestos + capa de drags económicos:**
- Nuevo `EconomicDragConfig` + singleton `DRAGS` en `config.py` (fee anual, tax de dividendos, costo de rebalanceo, buffer AR; opt-in a nivel motor → cero regresiones).
- `portfolio/monte_carlo.py`: `run(drags=...)` aplica un drag anual efectivo compuesto semanalmente (exacto, O(semanas)) y expone métricas **base vs con-drags** en `MonteCarloResult`.
- Helpers en `dashboard/shared.py` (`get_economic_drags`, `format_drags_badge`, `render_drags_controls`, `render_assumptions_disclaimer`, `ASSUMPTIONS_TEXT`) + UI en `7_Simulaciones.py` y `12_Plan.py`.
- Captura de drags en `PlanSnapshot` (`drags_at_save`, base_* en `mc_summary`), sección de supuestos en el PDF (`reports/investment_plan.py`), bloque honesto en la narrativa IA (`analysis/prompts.py`), disclaimers centralizados en Home (`app.py`) y `10_About.py`.

**Item 2 — "Mi Plan" portable + journey de backup:**
- `data/plan_context.py:import_plan_from_dict` (puro, defensivo) + `dashboard/shared.py:export_plan_bundle` (JSON versionado + instrucciones de restauración).
- Export/Import en `12_Plan.py` (download por plan + file_uploader con activar opcional). Campos `export_version`/`export_notes` en `PlanSnapshot`.
- `plan_journey_status` extendido con paso "Respaldá tu plan" + nudge en Home.

**Item 3 — Resiliencia de datos + custom tickers seguros:**
- `custom_tickers` en `UserPreferences` (+ `add/remove/custom_symbols`). `data/universe_loader.py:get_effective_universe` mergea universo curado + customs (dedup, validación).
- UI en `9_Settings.py` (agregar/quitar con advertencias) + columna **Fuente** y warnings en `1_Screener.py` y `5_Optimizer.py` (badge ⚠️ Custom, calidad de datos parcial).
- `data/snapshot.py`: export de snapshot de datos del universo (precio + fundamentals clave) para backup/offline, con inyección de dependencias (testeable offline).

**Tests:** +nuevos tests en `test_monte_carlo.py`, `test_plan_store.py`, `test_plan_context.py`, `test_preferences.py` y `test_snapshot.py`. Suite completa: **351 pasando, sin regresiones**.

---

## Fase 0 — Quick Wins de Largo Plazo & UX (iniciada 2026)

Trabajo iniciado a partir del brainstorming de mejoras (ver plan en `.grok/sessions/.../plan.md`).

**Entregado en Fase 0:**

- **Mejores hints y mensajes para inversionistas de largo plazo** en `dashboard/app.py` y `dashboard/pages/7_Simulaciones.py` (flujo recomendado actualizado, mensajes educativos cuando no hay optimizer, mejor onboarding ligero en home).
- **Presets de escenarios comunes** (Acumulación pura, FIRE, Meta casa, Retiro clásico 30y) + **retiros que crecen con inflación** en Monte Carlo (`portfolio/monte_carlo.py`, `dashboard/shared.py`, `7_Simulaciones.py`). Esto es un cambio de modelado importante para planes realistas de 15-30 años.
- **Narrativa IA "Explicame este plan"** (`analysis/prompts.py` + `analysis/ai_analyzer.py` + botón en Simulaciones). Usa los proveedores AI existentes para generar una explicación conservadora y accionable del portafolio + simulación actual.
- Tests: 179 pasando (sin regresiones).
- Actualización de flujo recomendado y documentación inicial.

**Cierre de esta fase:** el leftover de “próximos pasos” de Fase 0 quedó absorbido por las fases A–J y el Gran Salto (todas shipped). No es backlog abierto — ver [`CONTEXT.md` §6](CONTEXT.md) para el estado actual.

---

## Fase A — Onboarding / Perfil de Usuario Personalizado (2026-06)

Cierra el item pendiente #1 del análisis de visión: capturar el contexto personal del
usuario para personalizar toda la app sin tocar código.

**Entregado:**

- **`UserPreferences` extendido** (`data/preferences.py`) con perfil personal: `onboarded`,
  `age`, `retirement_age`, `current_capital`, `monthly_savings`, `risk_tolerance`,
  `primary_goal_type`, `dividend_preference`. Defaults seguros → 100% backward-compatible
  con archivos de prefs viejos. Helpers derivados: `is_onboarded`, `primary_horizon_years`,
  `annual_savings`, `profile_key`, y `apply_personal_profile()` (mantiene `default_profile`
  sincronizado con la tolerancia al riesgo).
- **Wizard de onboarding ligero** (`dashboard/onboarding.py`): un `st.form` corto y opcional,
  con defaults conservadores. Se muestra en **Inicio** (si el usuario no completó el perfil)
  y en **⚙️ Settings → Mi Perfil** (siempre, para editar). Incluye `render_profile_summary()`.
- **Consumo del perfil como defaults inteligentes**:
  - `dashboard/shared.py` → `get_user_prefs()` + `seed_session_defaults_from_profile()`
    (siembra capital/horizonte una vez por sesión; `force=True` tras guardar el wizard).
  - **Optimizer** (`5_Optimizer.py`): perfil + "Capital a invertir" por defecto.
  - **Simulaciones** (`7_Simulaciones.py`): horizonte Monte Carlo + capital inicial + pre-fill
    del formulario de "Mis Metas" (tipo, horizonte, aporte anual, capital asignado).
  - **Allocation** (`4_Allocation.py`): edad + edad de retiro por defecto.
- **Reset** en Settings ahora también limpia el perfil personal.
- Tests: `tests/test_preferences.py` (7 nuevos) — defaults, mapping de perfil, round-trip
  de persistencia y backward-compat con archivos legacy. Suite total: 228 pasando.

**Fix incidental:** `analysis/crypto_analyzer.py` importaba `field` desde `typing` (typo) —
rompía la colección de tests; corregido (`field` viene de `dataclasses`).

---

## Fase B — Mi Plan de Retiro: orquestación + persistencia (2026-06)

Cierra la brecha entre "excelente analizador" y "plan persistente y accionable". Antes el
plan vivía fragmentado en session_state efímero (Optimizer / Simulaciones / Mis Metas).

**Entregado:**

- **`data/plan_store.py`** — `PlanSnapshot` (resumen JSON-serializable de un plan: allocation,
  core holdings, métricas, goals, `mc_summary`, narrativa, snapshot del perfil personal) +
  `PlanStore`/`plan_store` (`upsert`/`get`/`list`/`delete`, JSON en `data/retirement_plans.json`,
  mismo patrón que `UserPreferences`). `PlanSnapshot.from_session()` construye el snapshot desde
  los objetos vivos del Optimizer/MC/goals + prefs. **No** persiste el `OptimizationResult`
  completo (pesado/no portable); guarda los artefactos relevantes para el humano.
- **`dashboard/pages/12_Plan.py`** — página "🗺️ Mi Plan" (grupo Portfolio):
  - **Plan actual (sesión):** perfil + métricas + núcleo (Grok si existe, si no determinístico)
    + metas + resumen Monte Carlo + narrativa.
  - **Guardar plan** nombrado (guardar con nombre existente = actualizar, por `id` slug).
  - **Planes guardados:** ver (read-only), borrar, y **comparar 2 planes** (tabla de métricas).
  - **Lista de compra del núcleo** (USD por ticker, CSV) y **PDF** (reutiliza `InvestmentPlanReport`).
- Construye sobre Fase A (`get_user_prefs`) y reutiliza `profile_core_holdings`/`grok_core_holdings`
  + narrativa ya presentes en `OptimizationResult`.
- Tests: `tests/test_plan_store.py` (+6) — `from_session`, preferencia de core Grok, round-trip
  `upsert/get/list/delete`, upsert-replace por id. Suite total: **234 pasando**.

**Pendiente / próximos pasos:**
- ~~Delta vs precios de hoy al cargar un plan viejo (requiere fetch de precios actuales).~~ ✅ Entregado en Fase C.
- ~~Cierre del loop con el tracker (target vs posiciones reales, alertas de drift sobre el plan).~~ ✅ Entregado en Fase C.
- Superficie de `macro_factors` (per-asset) como "factores macro que más impactan tu plan" → Fase D.
- Narrativa AI del plan completo (`goal_narrative_prompt`) → Fase D.

---

## Fase C — Plan como Objetivo Vivo: activar + deltas + drift (2026-06)

Convierte "Mi Plan" de generador de snapshots estáticos en el **corazón operativo** del
producto: un plan guardado puede **activarse** como objetivo de retiro, y desde ahí el
tracker y las alertas lo usan como fuente de verdad. Apalanca casi toda la infraestructura
ya existente (`plan_store`, `PortfolioAlertDetector`, tracker, prefs) — es orquestación y
cierre de loop, no una feature nueva grande.

**Entregado:**

- **Plan activo (`data/preferences.py`)** — campo `active_plan_id` + `set_active_plan()` /
  `clear_active_plan()`. Default `""` → 100% backward-compatible.
- **`PlanSnapshot` extendido (`data/plan_store.py`)** — campos opcionales `last_refreshed_at`,
  `refreshed_metrics`, `macro_risks` (livianos), helper `target_weights()` (pesos objetivo
  desde la allocation, con fallback al núcleo), y captura opcional de `price_at_save` por
  ticker vía `price_lookup` inyectable en `from_session()` (best-effort, nunca rompe el guardado).
- **`data/plan_context.py` (nuevo, Streamlit-free)** — `get_active_plan()` (con self-heal si el
  id quedó colgado), `activate_plan()`, `deactivate_plan()`, `is_active()`, y
  `compute_plan_vs_reality(snap, price_lookup)` que calcula el delta de precio (hoy vs guardado),
  el drift ponderado del plan y deltas por ticker. Acceso a red inyectado → testeable offline.
- **`dashboard/shared.py`** — `plan_price_lookup()` (precio cacheado vía `get_info`) +
  `compute_plan_health()` (wrapper detrás del botón "Refrescar", fetch controlado).
- **Detector de drift generalizado (`alerts/portfolio_alerts.py` + `alerts/engine.py`)** —
  `run()` / `run_with_portfolio()` aceptan `target_weights` + `target_label`
  (`optimizer_weights` queda como alias backward-compat). Los mensajes dicen
  "drift vs tu Plan de Retiro «X»" en lugar de "vs el objetivo del optimizer".
- **Scheduler (`scripts/run_scheduler.py`)** — si hay plan activo + posiciones reales, el
  `job_alert_check` mide drift contra los pesos objetivo del plan activado.
- **UI `12_Plan.py`** — botón "🎯 Activar/Desactivar" por plan + badge de plan activo, y sección
  "📈 Salud vs mercado actual" con botón "🔄 Refrescar con datos de hoy" (delta de precio,
  precio guardado vs hoy, score promedio al guardar).
- **UI `3_Portfolio.py`** — sección "🎯 Alineación con tu Plan" (objetivo vs actual por posición,
  deriva total vs umbral de `config.ALERTS`, sugerencia de rebalanceo).
- Tests: `tests/test_plan_context.py` (nuevo, 9), `tests/test_plan_store.py` (+6 Fase C) y
  `tests/test_alert_engine.py` (+4 drift vs plan). Suite total: **252 pasando** (0 regresiones).

**Criterio de éxito cumplido:** el usuario puede guardar un plan, activarlo, ver si se está
desviando (en Portfolio y en alertas), y refrescarlo con el mercado de hoy.

---

## Fase D — Narrativa IA del plan, factores macro y what-if (2026-06)

Cierra los últimos pendientes de Fase B/C: todo plan guardado tiene una explicación humana
**regenerable y persistida**, los **riesgos macro** a nivel cartera son visibles, y un plan
puede recargarse en los flujos de Optimizer/Simulaciones para iterar.

**Entregado:**

- **`plan_level_narrative_prompt()` (`analysis/prompts.py`)** — prompt nuevo que, a partir de un
  `PlanSnapshot` (+ refresco de mercado opcional de Fase C), devuelve un JSON
  `{"narrative", "macro_risks"}`: explicación conservadora en español (estructura de viñetas
  fija) + 0-2 factores macro que más pueden romper el plan (`{factor, why, severity}`).
  Incorpora perfil personal, metas, Monte Carlo, núcleo, cartera, sectores y el delta de mercado.
- **`AIAnalyzer.generate_plan_narrative(snapshot, refreshed=None)` (`analysis/ai_analyzer.py`)** —
  reusa `_call_api` + `extract_json_object` con fallback robusto: error de API → mensaje útil;
  prosa sin JSON → se rescata como narrativa; macro normalizado y capado a 2. El path sin IA
  sigue funcionando (narrativa opcional).
- **UI `12_Plan.py`** — en el visor de cada snapshot: botón "🧠 Generar/Regenerar narrativa IA"
  (persiste `narrative` + `macro_risks` en el JSON del plan), sección "🌍 Factores macro que más
  impactan tu plan" (badges por severidad), y botón "📥 Cargar plan en Optimizer/Simulaciones"
  que siembra `session_state` (perfil vía preset hook, capital, horizonte, target, inflación,
  metas) para what-if inmediato.
- Tests: `tests/test_prompts.py` (+9) — estructura del prompt (campos JSON, voz conservadora,
  perfil/metas, bloque de refresco) y `generate_plan_narrative` (parse, cap de macro a 2,
  normalización, descarte de entradas malformadas, fallback de API, rescate de prosa).
  Suite total: **261 pasando** (0 regresiones).

**Criterio de éxito cumplido:** cada plan guardado es un documento vivo y explicable años
después, con sus riesgos macro a la vista, y recargable para iterar escenarios.

---

## Fase E — Alto Impacto Post-Plan Vivo: adopción, acción y confianza (2026-06)

Surge del análisis de visión post-Fase D (plan "Análisis de Visión + Áreas de Alto
Impacto"): la madurez técnica estaba completa, pero la **superficie de uso, la
accionabilidad y la confianza en los datos** del plan vivo podían mejorar mucho con
poco código nuevo. Se entregaron los 3 items P0 del análisis:

**E.A — Flujo guiado Onboarding → Primer Plan Activado (adopción/UX):**

- **`dashboard/shared.py` → `plan_journey_status(prefs)`** — los 4 pasos canónicos
  (perfil → optimizar → guardar plan → activar) con flag `done` cada uno, leyendo
  prefs + session_state + `plan_store`.
- **Home (`dashboard/app.py`)** — bloque "🚀 Tu camino a un plan de retiro activo":
  progress bar X/4, checklist con el próximo paso resaltado y botón
  "➡️ Siguiente paso" (`st.switch_page`). Cuando los 4 pasos están completos muestra
  el badge de plan activo. Flujo recomendado actualizado (ahora termina en
  Mi Plan → Portfolio + Alertas).
- **`12_Plan.py` empty state guiado** — en lugar de un warning muerto, muestra la
  checklist del journey + botones directos a Optimizer/Simulaciones + recordatorio
  de que el perfil ya siembra capital/perfil de riesgo.
- **CTAs de continuidad**: Optimizer (post-resultado) y Simulaciones (post-MC) sugieren
  ir a 🗺️ Mi Plan para consolidar.

**E.B — Trades sugeridos para alinear (cierre del loop de acción):**

- **`data/plan_context.py` → `compute_alignment_trades(snap, current_weights,
  total_value, *, price_lookup, drift_threshold_pct, min_trade_usd, max_trades)`** —
  función pura (Streamlit-free, lookup inyectable): compara `target_weights()` del plan
  vs pesos reales del tracker y devuelve trades priorizados (núcleo primero, luego por
  monto) con acción comprar/vender, monto USD y shares estimadas. Umbrales desde
  `config.ALERTS` (nuevos: `alignment_min_trade_usd`, `alignment_max_trades`;
  reusa `portfolio_drift_threshold_pct`). Nunca hardcodea.
- **UI `3_Portfolio.py`** — dentro de "Alineación con tu Plan", expander
  "🛒 Trades sugeridos" (auto-expandido si la deriva supera el umbral de rebalanceo):
  métricas comprar/vender, tabla priorizada (⭐ = núcleo) y disclaimer fuerte.
- **UI `12_Plan.py`** — sección "🛒 Acciones sugeridas para alinear tu portfolio" en el
  visor del plan **activo** (botón "🧮 Calcular", fetch controlado como el de salud).
- Tests: `tests/test_plan_context.py` (+8) — montos buy/sell, umbral, prioridad núcleo,
  filtro de montos chicos, cap de trades, posiciones fuera del plan, errores de price
  lookup tolerados, defaults desde config.

**E.C — Robustez y transparencia de calidad de datos (confianza):**

- **`config.py` → `DataQualityConfig` / `DATA_QUALITY`** — `stale_warning_hours=48`,
  `partial_missing_fields=3`, `poor_missing_fields=6`.
- **`data/cache.py` → `DataCache.get_age_hours(key)`** (probe read-only de frescura) y
  **`data/fetcher.py` → `get_info_age_hours(symbol)`**.
- **`analysis/fundamental.py` → `compute_data_quality(result, freshness_hours,
  has_financials)`** — función pura que clasifica `good/partial/poor` contando métricas
  clave en None (excluye `dividend_yield`: None es legítimo en growth) + flag `stale`
  independiente. Crypto/ETF/Index: solo se chequea precio usable. Nuevo campo
  `FundamentalResult.data_quality` poblado en `analyze()` (también en el fast-path
  crypto y en el early-return sin datos).
- **UI Screener** — columna "Datos" (🟢 OK / 🟡 Parcial / 🔴 Pobre / ⏳ stale) vía
  `data_quality_badge()` en `shared.py` + warning agregado con conteos cuando hay
  tickers degradados.
- **UI `12_Plan.py`** — la "Salud vs mercado actual" ahora advierte qué posiciones
  quedaron sin precio hoy (datos incompletos ⇒ delta/trades parciales).
- Tests: `tests/test_data_quality.py` (nuevo, 11) — thresholds, sin estados financieros,
  exclusión de dividend_yield, staleness independiente, crypto/ETF.

Suite total: **280 pasando** (0 regresiones).

**Criterio de éxito:** un usuario nuevo ve su progreso hacia el plan activo desde Home y
llega guiado en pocos clics; con drift sobre el umbral ve 2-6 trades concretos (núcleo
primero, con montos); y la calidad de los datos detrás de cada score es visible en vez
de silenciosa.

**Pendiente sugerido (P1, ver plan de visión):** D. transparencia de supuestos +
sensitivity de MC en el plan; E. historial longitudinal de salud del plan
(`health_history`); F. freshness/fallback rico de narrativas IA; captura opcional de
un snapshot de data quality al guardar el plan.

---

## Fase F — Colas de Viento Industria-País (Tailwinds, Idea 2) (2026-06)

Motivación (caso canónico): el outlook estructural positivo del oil & gas argentino por
Vaca Muerta (YPF, PAM, CEPU…) no era capturado de forma confiable — el path rule-based
es 100% backward-looking y el path AI dependía del conocimiento del modelo en cada call.
Esta fase hace del contexto sector-país un **input first-class, curado y auditable**.

**Arquitectura (espejo de MoatAnalyzer: base determinística + AI opcional cacheada):**

- **`analysis/tailwind.py` (nuevo)** — `TailwindDetail` + `TailwindAnalyzer`:
  - `analyze(symbol, sector, country, industry)` — siempre rápido, sin API. Matching
    contra datos curados con precedencia ticker > (industria, país) > (sector, país).
    Sin match / sin datos → Neutral, bonus 0 (subset estricto del comportamiento previo).
  - `analyze_with_ai(...)` — enriquecimiento cualitativo opcional (cache SQLite 30 días).
    El LLM **solo interpreta** el dato curado para la empresa concreta — nunca inventa
    colas de viento ni modifica el score. Falla → base curada intacta.
  - Funciones puras `classify_tailwind()` / `compute_tailwind_bonus()`.
- **`data/tailwinds/sector_country.json` (nuevo)** — fuente de verdad curada y editable:
  Energy+Argentina (Vaca Muerta, +8, ~10a, tickers YPF/PAM/CEPU/VIST/TGS),
  Technology+US (AI capex, +4, ~6a) y un headwind de balance
  (Utilities reguladas AR / EDN, −3, ~5a). Campo `last_reviewed` por entrada.
- **`config.py` → `TailwindConfig` / `TAILWINDS`** — thresholds Strong ≥6 / Moderate ≥3 /
  Headwind ≤−2, `bonus = clamp(score × 0.8, ±8)` (cap menor que moat: nunca domina),
  `optimizer_er_tilt=0.05` (≤±0.9% anual), TTL cache AI 720h, master switch `enabled`.

**Integración pipeline (fluye a todo el sistema):**

- `analysis/fundamental.py` — campos `tailwind_score/bonus/classification/detail` en
  `FundamentalResult`; `adjusted_score` ahora suma `tailwind_bonus` (clamp [0,100]).
- `analysis/strategy.py` — rationale (Strong) / risks (Headwind) en `Decision` rule-based.
- `portfolio/optimizer.py` — `TickerAllocation` extendido (defaults backward-compat),
  tilt explícito pequeño en `_expected_returns`, nota 🌬️/🌪️ en el "why" del core.
- `data/plan_store.py` — `from_session` persiste tailwind en allocation **solo cuando es
  material** (snapshots viejos y tickers Neutral quedan byte-idénticos).
- Prompts (`analysis/prompts.py`) — `_tailwind_context_block()` en equity decision,
  línea `tailwind=` en holdings del optimizer advice, sección "COLAS DE VIENTO" en
  `plan_level_narrative_prompt`, y nuevo `sector_country_tailwind_prompt` (enriquecimiento).
  Regla en todos: dato curado = fuente de verdad, el LLM no inventa.

**UI:**

- `shared.py` → `tailwind_badge()` / `_tailwind_badge_html()` (🌬️ fuerte · 🍃 moderada ·
  🌪️ headwind) + columna "Viento" en filas del screener.
- Screener: columna "Viento" + nota al pie. Stock Analysis: expander dedicado
  (badge, rationale curado, durabilidad, efecto en score, match, AI reasoning,
  disclaimer "outlook a fecha de curaduría, no garantía"). Visible también sin AI.
- Optimizer: columna "Viento" en la tabla de asignación + resumen de tailwinds materiales.
- Mi Plan: sección "🌬️ Factores estructurales de sector-país" en el visor del snapshot.

**Guardrails conservadores:** sin datos curados / todo Neutral ⇒ números idénticos al
pre-feature en todos los flujos; bonus estrictamente capped; todo configurable solo via
`config.py` (apagable con `TAILWINDS.enabled=False`); AI nunca es el motor.

- Tests: `tests/test_tailwind.py` (nuevo, **40**) — thresholds y caps, precedencia de
  matching, neutral para pares no cubiertos, archivo ausente/corrupto, config override,
  AI graceful failure + cache + score inmutable, prompts, rationale/risks, tilt del
  optimizer (chico y acotado), dicts legacy sin claves, snapshot capture + roundtrip +
  backward compat.

Suite total: **320 pasando** (0 regresiones).

**Criterio de éxito:** quien analiza u optimiza una cartera con YPF/PAM ve un factor
"Argentina Energy structural tailwind" consistente, explicable y auditable influyendo
en scores, sizing y narrativas — con o sin AI — mientras el path sin tailwinds queda
estrictamente intacto.

---

## Fases completadas (históricas)

---

## Fases completadas (en orden cronológico)

### Fase 1 — Base (commit 68d6a00)
Proyecto inicial: análisis fundamental 0–100, análisis técnico, decision engine rule-based, dashboard Streamlit, portfolio tracker, asset allocation.

### Fase 1.5 — Consistency + Piotroski (commits fa4b29b, 8225b43)
- `analysis/scoring.py`: Consistency Score (0–15) + Piotroski F-Score (0–9, verdadero YoY)
- `analysis/fundamental.py`: campos `consistency_detail`, `piotroski_detail` en `FundamentalResult`
- Dashboard: expanders con sub-scores F1–F9 y detalle de consistency

### AI Integration — capa de decisión (commits a2ac30a → f5c6434)
Refinamiento posterior: salida estructurada `macro_factors` (además del texto libre en reasoning) para contexto macro en prompts de equity/crypto moat y decision. Ver CONTEXT.md §9.
- `analysis/ai_analyzer.py` ✅ — `AIAnalyzer` reemplaza `RetirementStrategy.decide()` cuando AI está habilitado
- `config.py` → `AIConfig` (provider / model / api_key / enabled / use_in_screener)
- `analysis/strategy.py` → `full_analysis(symbol, ai_config=None)` — orquesta rule-based o AI
- `dashboard/app.py` → Settings con selector de proveedor + Decision tab con razonamiento AI
- Proveedores soportados: Claude (Anthropic), GPT-4o (OpenAI), Grok (xAI via Hermes OAuth), Nous Research

### Fase 2 — Backtesting Engine (commits 25d3dab, 4151937, da1a0b4)
- `analysis/backtesting.py` — equity curve, drawdown, Sharpe, Sortino, Calmar
- Rebalanceo configurable: anual / trimestral / mensual / buy-and-hold
- Dashboard página "📊 Backtesting" con charts interactivos, scatter score↔CAGR y descarga CSV

### Fase 3 — Economic Moat (commits 9b2ed74, 626ffed)
- `analysis/moat.py` — `MoatAnalyzer`: cuantitativo (0–12, siempre) + AI cualitativo (0–8, cacheado 7 días)
- Clasificación: Wide ≥14 / Narrow ≥8 / Minimal ≥4 / None
- `FundamentalResult` enriquecido: `moat_score`, `moat_bonus`, `moat_classification`, `moat_detail`
- `adjusted_score` = base + consistency + piotroski_bonus + moat_bonus (cap 100)
- Dashboard: badge HTML con colores, progress bars por dimensión, tooltips
- `docs/moat_methodology.md` — metodología, umbrales, ejemplos reales, limitaciones

### Fase 4 — Portfolio Optimizer (commits 1bc1778, 67d4950, 1de3a63, 050b15c)
- `portfolio/optimizer.py` — Mean-Variance (scipy SLSQP) + 3 perfiles de riesgo
- Perfiles: Conservador (vol≤12%, div≥3.5%), Moderado (vol≤18%, div≥2.5%), Agresivo (vol≤25%, div≥1.5%)
- Expected return proxy: `score_weight*(score/100*0.18) + div_weight*(yield/100) + moat_weight*(moat/20*0.05)`
- Fallback score-weighted cuando SLSQP es infeasible, con warnings específicos por constraint violado
- ARS risk discount: 0.85× en composite score para ADRs argentinos (perfil conservador/moderado)
- Monte Carlo Efficient Frontier: 300 carteras aleatorias coloreadas por Sharpe
- Dashboard página "📈 Optimizer": 4 tabs (Cartera, Frontier, Métricas, Rebalanceo)
  - **Cartera**: bar chart coloreado por Score Ajustado + línea de pos. máx, tabla con ProgressColumn, sector donut + top-10 pie
  - **Frontier**: scatter Monte Carlo + línea roja vol-ceiling del perfil + estrella azul portfolio óptimo
  - **Métricas**: tabla de estadísticas + compliance badges ✅/❌ por constraint + sector bars con colores
  - **Rebalanceo**: waterfall chart Δpeso + tabla buys/sells/holds filtrada por ≥0.5%
- Session-state caching: análisis de 38 tickers cacheado; cambio de perfil es instantáneo sin re-análisis
- Delta banner al cambiar de perfil: muestra Δretorno, Δvol, ΔSharpe, ΔDivYield + top-6 position movers
- `config.py` → `ProfileConfig`, `OPTIMIZER_PROFILES`, `OptimizerConfig`

---

## Archivos principales

| Archivo | Rol |
|---|---|
| `analysis/fundamental.py` | Score 0–100, llama a scoring y moat |
| `analysis/scoring.py` | Consistency Score + Piotroski F-Score |
| `analysis/moat.py` | Economic Moat cuantitativo + AI |
| `analysis/ai_analyzer.py` | AI decision layer (reemplaza rule-based) |
| `analysis/backtesting.py` | Motor de backtesting histórico |
| `analysis/strategy.py` | `full_analysis()` orquestador |
| `portfolio/optimizer.py` | Mean-Variance optimizer + 3 perfiles |
| `dashboard/app.py` | UI Streamlit: 18 páginas (menú por intención; 3 solo en DEV_MODE) |
| `config.py` | AIConfig, MoatConfig, BacktestConfig, ProfileConfig, OptimizerConfig |
| `docs/moat_methodology.md` | Documentación del moat |
| `docs/ROADMAP.md` | Estado del proyecto y fases completadas |
