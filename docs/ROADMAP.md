# Estado del Proyecto — Retirement Advisor

## ✅ Todo implementado y en producción (GitHub main)

Este plan describe trabajo **ya completado**. El plan original (AI integration) fue implementado junto con las Fases 1.5, 2 y 3.

---

## Fase 0 — Quick Wins de Largo Plazo & UX (iniciada 2026)

Trabajo iniciado a partir del brainstorming de mejoras (ver plan en `.grok/sessions/.../plan.md`).

**Entregado en Fase 0:**

- **Mejores hints y mensajes para inversionistas de largo plazo** en `dashboard/app.py` y `dashboard/pages/7_Simulaciones.py` (flujo recomendado actualizado, mensajes educativos cuando no hay optimizer, mejor onboarding ligero en home).
- **Presets de escenarios comunes** (Acumulación pura, FIRE, Meta casa, Retiro clásico 30y) + **retiros que crecen con inflación** en Monte Carlo (`portfolio/monte_carlo.py`, `dashboard/shared.py`, `7_Simulaciones.py`). Esto es un cambio de modelado importante para planes realistas de 15-30 años.
- **Narrativa IA "Explicame este plan"** (`analysis/prompts.py` + `analysis/ai_analyzer.py` + botón en Simulaciones). Usa los proveedores AI existentes para generar una explicación conservadora y accionable del portafolio + simulación actual.
- Tests: 179 pasando (sin regresiones).
- Actualización de flujo recomendado y documentación inicial.

**Próximos pasos sugeridos (Fase 0 restante o Fase 1):**
- Pulir la experiencia de presets (widget keys + valores por defecto reales).
- Mover más prompts de narrativa al flujo de Optimizer.
- Agregar un wizard de perfil más completo (edad, horizonte principal, otras metas).

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
| `dashboard/app.py` | UI Streamlit: 7 páginas |
| `config.py` | AIConfig, MoatConfig, BacktestConfig, ProfileConfig, OptimizerConfig |
| `docs/moat_methodology.md` | Documentación del moat |
| `docs/ROADMAP.md` | Estado del proyecto y fases completadas |
