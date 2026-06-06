# Project Context — Retirement Advisor

> **Obligatorio:** Este archivo debe leerse completo antes de planear o codificar cualquier cambio.
> Última actualización: 2026-06-04

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
| Lenguaje | Python 3.13 |
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
| `analysis/moat.py` | Economic Moat cuantitativo (0–12) + AI (0–8) | Cambiar metodología de moat |
| `analysis/ai_analyzer.py` | Capa AI: 4 proveedores, parseo de respuesta estructurada | Agregar proveedor, cambiar formato de respuesta |
| `analysis/prompts.py` | Todos los prompts de IA (persona Grok, narrativa, moat) | Editar cualquier prompt |
| `analysis/strategy.py` | `full_analysis()` — orquestador del pipeline | Cambiar el flujo de análisis |
| `portfolio/optimizer.py` | Mean-Variance SLSQP + 3 perfiles + fallback | Cambiar optimizador o perfiles |
| `portfolio/monte_carlo.py` | Simulación block-bootstrap + SORR metrics | Cambiar modelo estocástico |
| `portfolio/goals.py` | Multi-Goal Planner: `Goal`, `GoalPlan`, `GoalPlanner` | Funcionalidad de metas |
| `dashboard/shared.py` | Funciones cacheadas (`cached_monte_carlo`, `cached_goal_simulation`, etc.) | Agregar cache de nueva feature |
| `dashboard/pages/7_Simulaciones.py` | Página principal de simulaciones (MC, Stress, Custom, Comparar, Metas) | UI de simulaciones |
| `dashboard/pages/5_Optimizer.py` | Página del Optimizer con Goal-Aware + Glide Path | UI del optimizer |
| `alerts/engine.py` | 5 checks de alerta, cooldowns, dispatch | Agregar nuevo tipo de alerta |
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
| AI Decision Layer (4 proveedores) | ✅ Completo | `analysis/ai_analyzer.py`, `analysis/prompts.py` |
| Backtesting Engine | ✅ Completo | `analysis/backtesting.py` |
| Portfolio Optimizer (SLSQP + 3 perfiles) | ✅ Completo | `portfolio/optimizer.py` |
| Goal-Aware Optimizer + Glide Path | ✅ Completo (Fase 2) | `portfolio/optimizer.py`, `dashboard/pages/5_Optimizer.py` |
| Monte Carlo (block-bootstrap + SORR) | ✅ Completo | `portfolio/monte_carlo.py` |
| Multi-Goal Planner ("Mis Metas") | ✅ Completo (Fase 1) | `portfolio/goals.py`, `dashboard/pages/7_Simulaciones.py` |
| Presets de escenario (FIRE, Casa, etc.) | ✅ Completo (Fase 0) | `dashboard/pages/7_Simulaciones.py` |
| Narrativa AI "Explicame este plan" | ✅ Completo (Fase 0) | `analysis/ai_analyzer.py`, `analysis/prompts.py` |
| Sistema de Alertas (email + Telegram) | ✅ Completo | `alerts/` |
| PDF Reports | ✅ Completo | `alerts/reporter.py` |
| Crypto Analysis (BTC, ETH) | ✅ Completo | `analysis/moat.py` (`CryptoMoatConfig`) |
| Recomendación de asignación (Grok Fase 1) | ✅ Completo | `analysis/ai_analyzer.py` |
| Onboarding Wizard (cuestionario de perfil) | ⏳ Pendiente | — |
| AI Narrativa para plan completo | ⏳ Pendiente | `analysis/prompts.py` (`goal_narrative_prompt`) |

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

### Singletons module-level (usar estos, no instanciar nuevas clases)

```python
THRESHOLDS    # FundamentalThresholds
STRATEGY      # StrategyConfig
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
OPTIMIZER_PROFILES  # Dict[str, ProfileConfig]
```

### Constantes clave

- `DEFAULT_TICKERS` — 38 tickers (US mega-caps, ADRs argentinos, ETFs, crypto)
- `CRYPTO_TICKERS` — {BTC, BTC-USD, BITCOIN, ETH, ETH-USD, ETHEREUM}
- `TICKER_ALIASES` — mapeo de nombres (BTC→BTC-USD, etc.)
- `SECTOR_MAP` — 10 sectores

---

## 8. Limitaciones Conocidas

- **EMFILE**: El screener puede agotar file descriptors con muchos workers simultáneos — `max_workers` controlado, usar `NullPool` en SQLAlchemy
- **yfinance rate limits**: No hay retry automático; si falla un ticker, se loggea y se continúa
- **Moat AI cache**: 7 días de TTL; si el modelo AI cambia, el cache puede estar desactualizado (borrar `data/db/retirement_advisor.db` para reset)
- **ADRs argentinos**: Se aplica `ARS risk discount` (0.85×) automáticamente en perfiles Conservador/Moderado
- **Sin datos intraday**: Toda la simulación MC usa retornos semanales (10 años de historia)
- **Streamlit hot-reload**: Algunas instancias de clases (ej. Portfolio) pueden quedar stale tras hot-reload — hay guards `hasattr` para auto-reparar
- **KaTeX rendering**: Streamlit puede interpretar `$` en markdown como LaTeX — escapar `\$` en strings de montos

---

## 9. Últimos Cambios Importantes

| Commit | Cambio |
|--------|--------|
| `33785c5` | Prompts de decisión AI: justificación explícita de `confidence` (HIGH/MEDIUM/LOW) integrada en el campo `reasoning` — equity y crypto |
| `c7717be` | Goal-Aware Optimizer Fase 2 — Glide Path automático en `portfolio/optimizer.py` |
| `9d2d508` | Capturar y exponer recomendación de asignación de Grok (Fase 1 de integración AI) |
| `62cb6e5` | Pulido UX Fase 1 Simulaciones — cards, SORR badge, fan chart |
| `8741d96` | Fix screener: reducir `max_workers` + NullPool para evitar EMFILE |
| `13d84e7` | Multi-Goal Planner + SORR metrics completo (`portfolio/goals.py`) |
| `fb14aac` | Fase 0: presets, narrativa IA, retiros con inflación en Monte Carlo |

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
