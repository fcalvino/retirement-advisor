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
1. **Cuantitativo (0–12)**: Calcula 4 dimensiones (ROIC vs WACC, márgenes vs sector, revenue growth, eficiencia de capital)
2. **AI cualitativo (0–8)**: Llama al LLM con contexto financiero, pide evaluación de 4 dimensiones, parsea JSON. Resultado cacheado 7 días en SQLite.

#### `technical.py`
Descarga barras semanales de 10 años y calcula con `pandas_ta`: SMA200, RSI, MACD, ADX, Bollinger Bands. Retorna un `TechnicalResult` con todos los indicadores y una señal técnica (BULLISH/NEUTRAL/BEARISH).

#### `strategy.py`
`full_analysis(symbol, ai_config=None)` — orquestador:
1. Fetches data → fundamental → technical → decision
2. Si `ai_config.enabled`: llama a `AIAnalyzer.analyze()` para la decisión
3. Si no: usa el motor rule-based (tabla score × técnico)
4. Retorna un dict con todos los campos para el screener y dashboard

#### `ai_analyzer.py`
`AIAnalyzer` maneja los 4 proveedores (Claude/OpenAI/Grok/Nous). Construye el prompt con todos los datos financieros + técnicos y parsea la respuesta estructurada (decision, confidence, rationale, key_risks, key_strengths).

---

### `portfolio/`

#### `optimizer.py`
Pipeline de 9 pasos:
1. Filtrar elegibles (excluir ETFs, score < mínimo)
2. Aplicar ARS risk discount (0.85× en conservador/moderado)
3. Construir price matrix (2 años semanales)
4. Calcular expected returns (composite formula)
5. Calcular covariance matrix (anualizada, regularización 1e-6)
6. SLSQP Mean-Variance (minimizar Sharpe negativo)
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
Regla edad-conservadora: `bond_pct = min(age, 80)`. Incluye tablas de referencia para diferentes horizontes y perfiles de riesgo.

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

### `dashboard/app.py`

9 páginas en navegación por radio buttons. Session state clave:
- `screener_cache`: resultados del screener (38 tickers) para reusar sin re-análisis
- `optimizer_prev_result`: resultado del optimizer, compartido con la página de Simulaciones

Cada página se renderiza como función separada llamada desde el switch principal.

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
| `pandas`, `numpy` | Procesamiento de datos |
| `pandas_ta` | Indicadores técnicos |
| `scipy` | SLSQP optimizer |
| `streamlit` | Dashboard UI |
| `plotly` | Gráficos interactivos |
| `sqlalchemy` | ORM para SQLite |
| `anthropic`, `openai` | Clientes AI |
| `reportlab` | Generación de PDFs |
| `loguru` | Logging estructurado |
| `schedule` | Scheduler de alertas/reportes |
