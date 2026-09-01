# Arquitectura — Retirement Advisor

## Visión general

El sistema está organizado en capas horizontales que fluyen de izquierda a derecha: **datos → análisis → decisión → UI / alertas**.

```
Yahoo Finance (yfinance)
        │
        ▼
  data/fetcher.py  ←→  data/cache.py (SQLite, TTL)
        │
        ├─────────────────────────────────────┐
        ▼                                     ▼
analysis/fundamental.py            portfolio/optimizer.py
analysis/scoring.py                portfolio/monte_carlo.py
analysis/moat.py                   portfolio/stress_test.py
analysis/technical.py              portfolio/tracker.py
        │                          portfolio/allocation.py
        ▼
analysis/strategy.py  (full_analysis)
analysis/ai_analyzer.py  (decisión AI opcional)
        │
        ├──────────────────────────────────────┐
        ▼                                      ▼
dashboard/app.py (Streamlit)         alerts/engine.py
                                     alerts/store.py  (SQLite)
                                     alerts/notifier.py  (email/Telegram)
                                     alerts/reporter.py  (PDF/reportlab)
                                     scripts/run_scheduler.py
```

---

## Módulos principales

### `config.py`

Punto central de configuración. Todos los umbrales, perfiles y parámetros son dataclasses modificables sin tocar el código de análisis.

| Clase | Propósito |
|-------|-----------|
| `FundamentalThresholds` | Umbrales de scoring (ROE, márgenes, ratios) |
| `StrategyConfig` | Score mínimos para cada señal |
| `AlertConfig` | Email/Telegram + umbrales de disparo |
| `ReportConfig` | PDF output, frecuencia del scheduler |
| `AIConfig` | Proveedor AI, modelo, API key |
| `ConsistencyThresholds` | Std máxima de ROE y márgenes |
| `PiotroskiConfig` | Umbral strong/bonus |
| `BacktestConfig` | Período, benchmark, risk-free rate |
| `MoatConfig` | Umbrales Wide/Narrow/Minimal, TTL caché AI |
| `ProfileConfig` | Constraints del optimizer por perfil |
| `OptimizerConfig` | Parámetros globales del optimizer |
| `MonteCarloConfig` | vol_adjustment, mean_haircut, n_sims |

Singletons module-level: `THRESHOLDS`, `STRATEGY`, `ALERTS`, `AI_CONFIG`, etc.

---

### `data/`

#### `fetcher.py`
Wrapper sobre `yfinance`. Función principal: `get_history(symbol, period, interval)`.

Todas las llamadas a yfinance pasan por aquí para:
1. Verificar el caché SQLite primero
2. Si expirado o ausente, hacer fetch real y guardar
3. Retornar un DataFrame normalizado

#### `cache.py`
SQLite cache con TTL. Tabla `price_cache` (symbol + interval + period → JSON blob + timestamp).

---

### `analysis/`

#### `fundamental.py`
Núcleo del scoring. Calcula las 5 dimensiones (Profitability, Health, Valuation, Growth, Dividends) y llama a `scoring.py` y `moat.py` para construir el `FundamentalResult` completo.

`FundamentalResult` contiene:
- `total_score` (0–100): score base
- `consistency_score`, `piotroski_score`, `piotroski_bonus`
- `moat_score`, `moat_bonus`, `moat_classification`
- `adjusted_score = min(total + consistency + piotroski_bonus + moat_bonus, 100)`
- Todos los campos de métricas financieras

#### `scoring.py`
Dos componentes independientes:

**Consistency Score (0–15)**:
- ROE stability: std de ROE real (NI/Equity) sobre los años disponibles
- EPS stability: CV de tasas de crecimiento de NI
- Margin stability: std de margen neto

**Piotroski F-Score (0–9)**: 9 checks YoY estrictos sobre estados financieros reales. Cada check es True/False; la suma es el score.

#### `moat.py`
`MoatAnalyzer` en dos fases:
1. **Cuantitativo (0–12)**: Calcula 6 dimensiones de 0–2 pts (nivel y estabilidad del margen bruto, ROIC sostenido vs **costo de equity proxy**, defensividad de ingresos, FCF conversion, FCF margin)
2. **AI cualitativo (0–8)**: Llama al LLM con contexto financiero, pide evaluación de 4 dimensiones, parsea JSON. Resultado cacheado 7 días en SQLite.

#### `technical.py`
Descarga barras semanales de 10 años y calcula los indicadores **a mano con NumPy/Pandas** (SMA de **200 semanas** ~3,8 años —no la clásica de 200 días— + su pendiente, golden/death cross de 50 vs 200 semanas, RSI 14, MACD 12/26/9). Retorna un `TechnicalResult` con todos los indicadores y una señal técnica (BULLISH/NEUTRAL/BEARISH). No usa librería de análisis técnico: `pandas_ta` se eliminó como código muerto (ver `docs/DEAD_CODE_AUDIT.md`).

#### `strategy.py`
`full_analysis(symbol, ai_config=None)` — orquestador:
1. Fetches data → fundamental → technical → decision
2. Si `ai_config.enabled`: llama a `AIAnalyzer.analyze()` para la decisión
3. Si no: usa el motor rule-based (tabla score × técnico)
4. Retorna un dict con todos los campos para el screener y dashboard

#### `ai_analyzer.py`
`AIAnalyzer` maneja los 4 proveedores (Claude/OpenAI/Grok/Nous). Construye el prompt con todos los datos financieros + técnicos y parsea la respuesta estructurada (decision, confidence, rationale, key_risks, key_strengths). Desde la mejora de contexto macro, también parsea `macro_factors` (lista estructurada de 0-2 factores con impacto explícito en asignación/convicción). El texto libre de razonamiento (`ai_reasoning`) se mantiene para la voz de Grok.

---

### `portfolio/`

#### `optimizer.py`
Pipeline de 9 pasos:
1. Filtrar elegibles (excluir ETFs, score < mínimo)
2. Aplicar ARS risk discount (0.85× en conservador/moderado)
3. Construir price matrix (2 años semanales)
4. Calcular atractivo estimado (proxy: score + dividendo + moat)
5. Calcular covariance matrix (anualizada, regularización 1e-6)
6. SLSQP Mean-Variance (minimizar el ratio atractivo/vol negativo)
7. Fallback score-weighted si SLSQP infeasible
8. Efficient Frontier (300 Monte Carlo portfolios)
9. Rebalancing suggestions (target vs. current)
10. Rebalancing frequency recommendation (perfil + volatilidad)

#### `monte_carlo.py`
Block-bootstrap vectorizado:
1. Fetch weekly prices para todos los símbolos (10 años)
2. Calcular retornos semanales del portafolio (ponderados)
3. Ajuste conservador: +10% vol, -20% mean
4. Simular `n_sims × n_weeks` con indices de bloques de 4 semanas
5. Acumular `cumprod(1 + returns)` → fan chart percentilado

#### `stress_test.py`
6 escenarios definidos como dataclasses con shocks por sector (%). `StressTester.run()` aplica el drawdown ponderado por los pesos sectoriales del portafolio optimizado.

#### `tracker.py`
CRUD de posiciones (SQLite). Calcula P&L, peso actual por posición, métricas de riesgo simples.

#### `allocation.py`
Regla por edad para el tramo **defensivo (bonos + efectivo)**, inclinada por el perfil de riesgo (U5-7): `recommended_bond_pct(age, profile)` es `min(max(age + bond_age_offset_pp, 0), 80)`, con offset `0 / −5 / −10` para Conservador / Moderado / Agresivo.

Lo que ese número gobierna es el tramo **defensivo — bonos + efectivo**, no el de bonos solo (N9). `AllocationAdvisor` mantiene `config.CASH_BUFFER_PCT` líquido como buffer de rebalanceo y el resto va a bonos, así que la pantalla parte la regla en dos filas y ninguna es la regla por separado: a los 30 un Conservador lee 25 % en bonos + 5 % en efectivo, y la regla dice 30. El contrato — exacto para todo perfil y edad — es `bonds_pct + cash_pct == max(recommended_bond_pct(age, profile), CASH_BUFFER_PCT)`, fijado por `tests/test_defensive_sleeve_contract.py`.

Incluye además las verificaciones de concentración por sector y por posición, que califican contra los topes del perfil (`max_sector_pct` / `max_position_pct`), no contra los globales de `STRATEGY`.

---

### `alerts/`

#### `store.py`
Tres tablas SQLite:
- `alert_snapshots`: último estado conocido por ticker (score, signal, moat_class)
- `alert_history`: historial de alertas disparadas (MAX 500 entradas)
- `alert_cooldowns`: cooldowns activos por tipo+ticker para evitar spam

#### `engine.py`
`AlertEngine.run(scored_tickers)`:
- Cold start: si no hay snapshot → guarda baseline, no dispara
- 5 checks: signal change, score drop ≥8pts, score surge ≥8pts+BUY, nueva oportunidad BUY, moat downgrade
- Cada check verifica cooldown antes de disparar
- Al final: despacha digest agrupado por severidad

#### `notifier.py`
`Notifier.send()`: email HTML con template branded + Telegram.
`Notifier.send_report()`: email con PDF adjunto.

#### `reporter.py`
`ReportGenerator.generate()` usando `reportlab`:
- Header/footer con callback de canvas
- KPI cover table
- Leaderboard (top N por score)
- BUY opportunities + SELL risks
- Tabla completa del universo
- Gráfico de distribución de scores (matplotlib → BytesIO → PDF)

---

### `dashboard/app.py` + `dashboard/shared.py` + `dashboard/pages/*.py`

UI multipágina moderna usando `st.navigation` + `st.Page(path)` (carga dinámica de archivos numerados en `pages/`). 

- `app.py`: `st.set_page_config`, logger idempotente (`_ensure_logger` con guard en session_state para evitar sinks duplicados/EMFILE), validación de config al startup, init de session_state (user_prefs, universe desde active_universe, portfolio, ai_provider/model/key), sidebar (selector de universo persistido en prefs + badges de watchlist/alertas + warnings de config), home page informativa + flujo recomendado, y orquestación de la navegación por intención (Inicio / Mi dinero / Investigar / Proyectar / Seguimiento / Ajustes). Hay **18** páginas en `dashboard/pages/` (Eval IA, Calidad de Datos y Macro RAG solo en `DEV_MODE`).
- `shared.py`: fuente canónica de helpers usados por **todas** las páginas (`_load_env_vars` / `_save_ai_config_to_env`, `_get_ai_config` (resuelve desde session_state con override por contexto screener), `score_bar` + helpers HTML de moat, `cached_full_analysis`, `cached_monte_carlo` / `cached_goal_simulation` / `cached_goal_optimization` / `cached_stress_test` (con params como tuplas para hashability), `_analyse_universe_parallel` y `_fetch_universe_parallel` con `max_workers` capped en 6 por límites de FD en macOS + EMFILE mitigation documentada en CONTEXT §8). Lazy imports pesados dentro de las cached funcs.
- `pages/N_*.py`: lógica específica de cada página (delgada). Importan de `shared` + módulos de analysis/portfolio/alerts/data/config. Incluyen guards defensivos para el orden de inicialización de multipage (ej. "volvé a Inicio si session_state no está listo").

Session state clave y patrones de cache: ver `docs/CONTEXT.md` §5. El flujo de datos principal (debajo) permanece válido.

**Nota histórica:** Previamente existía `dashboard/app_monolith.py` (UI legacy con radio + toda la lógica inline). Fue eliminado por ser código duplicado inutilizado tras la migración a multipage + shared (0 referencias en source).

---

## Flujo de datos principal

```
Usuario abre Screener
    → strategy.full_analysis() × 38 tickers
    → fundamental.analyze() + scoring.get_enhanced_score() + moat.analyze()
    → technical.analyze()
    → ai_analyzer.analyze() si AI habilitado
    → Resultado cacheado en session_state["screener_cache"]

Usuario abre Optimizer
    → Lee screener_cache (sin re-análisis)
    → optimizer.optimize(scored_tickers, profile)
    → Descarga precios (caché SQLite)
    → SLSQP o score-weighted fallback
    → Guarda result en session_state["optimizer_prev_result"]

Usuario abre Simulaciones
    → Lee optimizer_prev_result.tickers (símbolos + pesos)
    → MonteCarloSimulator(symbols, weights).run(...)
    → StressTester().run(optimizer_prev_result.sector_weights)
```

---

## Persistencia

| Store | Contenido | Tecnología |
|-------|-----------|------------|
| `data/db/retirement_advisor.db` | price cache + portfolio positions + moat AI cache + alert state | SQLite (SQLAlchemy) |
| `reports/` | PDFs generados mensualmente | Archivos en disco |

No hay base de datos externa ni servicios remotos más allá de Yahoo Finance y los proveedores AI.

---

## Dependencias clave

| Paquete | Uso |
|---------|-----|
| `yfinance` | Datos de mercado |
| `pandas`, `numpy` | Procesamiento de datos + indicadores técnicos (calculados a mano) |
| `scipy` | SLSQP optimizer |
| `streamlit` | Dashboard UI |
| `plotly` | Gráficos interactivos |
| `sqlalchemy` | ORM para SQLite |
| `anthropic`, `openai` | Clientes AI |
| `reportlab` | Generación de PDFs |
| `loguru` | Logging estructurado |
| `schedule` | Scheduler de alertas/reportes |
