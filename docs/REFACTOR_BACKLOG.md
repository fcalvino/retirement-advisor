# Backlog de Refactorización — Retirement Advisor

> **Rol:** `refactor-backlog` — inventario de deuda técnica estructural, independiente del roadmap de features.
> Creado: 2026-09-02. Metodología: inspección directa del código (archivo:línea verificada).
> Lo que falta hacer en features vive en [`BACKLOG.md`](BACKLOG.md).

---

## Cómo leer este documento

Cada ítem tiene:
- **ID** y **eje** (`ordenamiento` / `simplicidad` / `performance` / `cobertura`)
- **Evidencia** — archivo:línea y síntoma concreto
- **Cambio propuesto** y **contratos públicos que deben permanecer estables**
- **Impacto / Esfuerzo** (`S`=horas / `M`=1–2 días / `L`=3+ días) y **riesgos**
- **Marcador de visibilidad**: `[interno]` el usuario no lo nota · `[observable]` puede cambiar lo que se ve (ej.: un threshold que ahora se puede tunear sin tocar código)
- **Verificación**

Los ítems están agrupados en fases coherentes con el criterio de ratio impacto/esfuerzo. Las dependencias entre ítems están listadas al final.

---

## Resumen — tabla de prioridad

| ID | Eje | Esfuerzo | Impacto | Marcador | Título corto |
|----|-----|----------|---------|----------|-------------|
| S1 ✅ | simplicidad | S | medio | interno | `ARGENTINA_ADRS` declarada dos veces |
| S2 ✅ | simplicidad | S | alto | interno | Code-fence stripping: 3 copias, IndexError latente |
| S7 ✅ | simplicidad | S | bajo | interno | Re-import `THRESHOLDS` local en `analyze()` |
| S13 ✅ | simplicidad | S | bajo | interno | `_fmt_idx` duplicada en dos páginas |
| S20 ✅ | performance | S | bajo | interno | `measure_all` llamado 3 veces donde corresponden 2 |
| S21 ✅ | simplicidad | S | bajo | interno | Boilerplate sys.path duplicado en todos los scripts |
| S4 ✅ | simplicidad | M | alto | observable | 5 dims del moat cuantitativo: thresholds hardcodeados |
| S5 ✅ | simplicidad | S | alto | observable | Fallback de ROIC absoluto hardcodeado |
| S6 ✅ | simplicidad | S | alto | observable | CV de EPS y banda `roe_std*2` no están en config |
| S9 ✅ | simplicidad | S | medio | observable | `div / 15.0` en optimizer sin nombre ni config |
| S10 ✅ | simplicidad | M | alto | observable | 5 glide-path overrides hardcodeados en optimizer |
| S11 ✅ | simplicidad | S | medio | observable | Tasa de recovery en stress test: contradicción y sin config |
| P1 ✅ | performance | S | alto | observable | `max_tokens=800` hardcodeado en moat AI — trunca JSON |
| S3 ✅ | simplicidad | M | medio | interno | `_call_nous` / `_call_xai` ~35 líneas duplicadas |
| S8 ✅ | simplicidad | S | medio | interno | `quickRatio` ignora patrón `reported_metric()` |
| S14 ✅ | simplicidad | S | medio | interno | Dict comprehension scored-ticker duplicado en 5_Optimizer |
| S15 ✅ | simplicidad | S | bajo | observable | Defaults de sesión hardcodeados; imports mid-file |
| S18 ✅ | simplicidad | M | medio | interno | Guard de sesión duplicado en ≥3 páginas |
| S19 ✅ | simplicidad | S | medio | interno | `_price_lookup` en scheduler duplica lógica de shared.py |
| S22 ✅ | simplicidad | M | medio | interno | `_analyse_one` mezcla extracción de datos con UI strings |
| S23 ✅ | simplicidad | S | bajo | interno | `rf = 0.045` literal en `tracker.py` — no usa `RISK_FREE` |
| S24 ✅ | simplicidad | S | medio | observable | Umbrales de drawdown severo/SORR hardcodeados en MC |
| S25 ✅ | simplicidad | M | medio | observable | Pesos de señal técnica hardcodeados en `technical.py` |
| S26 ✅ | simplicidad | S | bajo | interno | `_extract_annual_series` triplicada en 3 módulos de análisis |
| S27 ✅ | simplicidad | M | medio | observable | SCENARIOS de stress test: ~85 shocks hardcodeados en módulo |
| S28 ✅ | simplicidad | S | bajo | observable | `expected_annual_return=0.07` hardcodeado en `goals.py` |
| P2 ✅ | performance | S | bajo | interno | Unread-alert count consultado 2 veces por rerun |
| P3 ✅ | performance | S | bajo | interno | `print()` en `personal_sizer.py` — no usa loguru (evidencia incorrecta: era un docstring) |
| O3 ✅ | ordenamiento | S | medio | interno | `cached_stress_test` acepta `dict` crudo como param de caché |
| O6 ✅ | ordenamiento | S | bajo | interno | Sidebar importa `alert_store` directamente |
| O7 ✅ | ordenamiento | S | bajo | interno | Stock Analysis importa `data.data_sources` y `data.fetcher` |
| O8 ✅ | ordenamiento | S | bajo | interno | Migraciones one-shot mezcladas con scripts operacionales |
| O9 ✅ | ordenamiento | S | bajo | interno | Settings importa `data.cache` y `data.fetcher` directamente |
| O2 ✅ | ordenamiento | M | alto | interno | Dispatch de provider AI duplicado en moat.py y ai_analyzer.py |
| O4 ✅ | ordenamiento | M | medio | interno | `run_holdings_committee` (negocio) en módulo de UI |
| O5 ✅ | ordenamiento | M | bajo | interno | Página de alertas importa `AlertEngine` directamente |
| S16 ✅ | simplicidad | M | medio | interno | `_home_page()` 208 líneas monolíticas |
| S17 ✅ | simplicidad | M | medio | interno | `render_*_controls` mutan session_state dentro del render |
| O1 ✅ | ordenamiento | L | alto | interno | `FundamentalAnalyzer.analyze()` 215 líneas: God method |
| S12 ✅ | simplicidad | L | alto | interno | `7_Simulaciones.py` 2.420 líneas sin helpers |
| T1 ✅ | cobertura | M | alto | interno | Cero tests para `dashboard/shared.py` (1.891 líneas) |
| T2 ✅ | cobertura | M | alto | interno | Sin test de integración para `FundamentalAnalyzer.analyze()` |

---

## Fase R0 — Quick wins (Esfuerzo S, riesgo mínimo)

Cambios triviales o de una sola línea. Sin riesgo de regresión; verificables solo con `make check`.

---

### S1 — `ARGENTINA_ADRS` declarada dos veces `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `analysis/ai_analyzer.py:27` — `ARGENTINA_ADRS = {"YPF", "PAM", "CEPU", ...}` (13 tickers)
- `analysis/prompts.py:41` — declaración idéntica del mismo set

`ai_analyzer.py` ya importa de `analysis.prompts` (`from analysis.prompts import equity_decision_prompt`, línea 80). Re-declara la constante en vez de importarla. Una adición futura de ticker requiere dos edits y puede divergir silenciosamente.

**Cambio propuesto:** eliminar la declaración en `ai_analyzer.py:27`; agregar `ARGENTINA_ADRS` al import existente desde `prompts.py`.

**Contrato estable:** el set de tickers no cambia; ninguna firma pública cambia.

**Riesgos:** ninguno. Es un alias del mismo objeto.

**Estado:** ✅ Mergeado — PR #74 (2026-09-02)

**Verificación:** `make check`.

---

### S2 — Code-fence stripping: 3 copias con IndexError latente `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** alto

**Evidencia:**
- `analysis/ai_analyzer.py:119` — `text = text.split("```")[1].strip()` (IndexError si la respuesta es ` ``` ` sin contenido)
- `analysis/ai_analyzer.py:162–170` — variante segura con guard `len(parts) > 1`
- `analysis/ai_analyzer.py:312–319` — misma variante segura, con strip de `"json"` prefix

Tres copias de la misma lógica de limpieza de respuesta LLM. La versión de línea 119 lanza `IndexError` si el modelo devuelve un bloque de código vacío (e.g., ` ``` ` sin nada después). Las otras dos son más robustas pero tampoco están unificadas.

**Cambio propuesto:** extraer función privada `_strip_code_fence(text: str) -> str` que use la variante segura (con guard y strip de `"json"`). Reemplazar las tres llamadas.

**Contrato estable:** misma firma de entrada/salida; ningún método público cambia.

**Riesgos:** bajo. El cambio elimina un bug latente.

**Estado:** ✅ Mergeado — PR #74 (2026-09-02)

**Verificación:** `make check`. Si hay tests que mockeaban respuestas con fences, deben seguir pasando.

---

### S7 — Re-import `THRESHOLDS` local dentro de `analyze()` `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `analysis/fundamental.py:28` — `from config import THRESHOLDS as T`
- `analysis/fundamental.py:853` — `from config import THRESHOLDS as _TH` (dentro del cuerpo de `analyze()`)

El bloque Graham fue añadido independientemente y usa `_TH.graham_max_growth_pct` y `_TH.graham_aaa_yield_pct`, ambos accesibles vía `T` ya importado.

**Cambio propuesto:** eliminar la línea 853 y reemplazar `_TH` por `T` en el bloque de Graham.

**Contrato estable:** sin cambio.

**Estado:** ✅ Mergeado — PR #74 (2026-09-02)

**Verificación:** `make check`.

---

### S13 — `_fmt_idx` duplicada en dos páginas `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/pages/7_Simulaciones.py:76` — `def _fmt_idx(v): ...`
- `dashboard/pages/5_Optimizer.py:37` — cuerpo idéntico: `proxy_attractiveness_index(v)` → `"—"` o `f"{v:.0f}"`

**Cambio propuesto:** mover `_fmt_idx` a `data/product_ux.py` o `dashboard/shared.py` (junto a `proxy_attractiveness_index` que ya está ahí). Reemplazar las dos definiciones por un import.

**Contrato estable:** función privada; ningún contrato externo.

**Estado:** ✅ Mergeado — PR #74 (2026-09-02)

**Verificación:** `make check`.

---

### S20 — `measure_all` llamado 3 veces con `--matrix` + `--baseline` `[interno]`

**Eje:** performance · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `scripts/measure_score_impact.py:379–393`

Con `--matrix`, el script corre `off = measure_all(symbols)` (AI off) y `on = measure_all(symbols, ai_config=...)` (AI on). Si además se pasa `--baseline` o `--compare`, una línea más abajo corre `current = measure_all(symbols)` sin config de AI — idéntico a `off`. Sobre un universo de 164 tickers, cada corrida tarda varios minutos.

**Cambio propuesto:** `current = off if args.matrix else measure_all(symbols)`

**Contrato estable:** salida idéntica; ninguna interfaz externa cambia.

**Estado:** ✅ Mergeado — PR #74 (2026-09-02)

**Verificación:** `make check`. Correr `scripts/measure_score_impact.py --matrix --compare` y verificar que produce el mismo resultado en menos tiempo.

---

### S21 — Boilerplate sys.path duplicado en todos los scripts `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `scripts/run_eval.py:17–22`, `score_track_record.py:17–22`, `run_scheduler.py:29–34`, `measure_score_impact.py:62`, `test_telegram.py`, `check_doc_catalog.py` — cada uno replica el mismo bloque de 4–5 líneas de `sys.path.insert` + `ensure_project_root`.

**Cambio propuesto:** crear `scripts/_bootstrap.py` con la lógica compartida. Cada script lo importa con una sola línea. Los scripts one-shot de migraciones (O8) también se benefician.

**Contrato estable:** sin cambio de comportamiento.

**Riesgos:** importar `_bootstrap` antes de que el path esté configurado es trivial si el módulo es autocontenido. El nombre con `_` señala que es interno.

**Estado:** ✅ Mergeado — PR #74 (2026-09-02)

**Verificación:** `make check` + correr un script de ejemplo.

---

## Fase R1 — Centralización en config.py (Esfuerzo S–M)

Mover números hardcodeados a `config.py` sin cambiar la matemática. Los scores finales no deben moverse; verificable con `scripts/measure_score_impact.py --compare`.

---

### S4 — 5 de 6 dimensiones del moat cuantitativo: thresholds hardcodeados `[observable]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** alto

**Evidencia (`analysis/moat.py`):**
- Gross Margin Level (líneas 419, 421, 423): `>= 50`, `>= 35`, `>= 20`
- Gross Margin Stability (431, 433, 435): `<= 3`, `<= 8`, `<= 15`
- FCF Conversion (468, 470, 472): `>= 1.2`, `>= 0.9`, `>= 0.6`
- FCF Margin (479, 481, 483): `>= 20`, `>= 10`, `>= 5`
- Revenue Defensiveness (457, 459, 461): `== 0`, `== 1`, `<= 2`

Solo `roic_sustained` lee sus umbrales de `MoatConfig` (vía `self.cfg.roic_spread_*`). Las otras cinco dimensiones son calibración invisible. `config.py` ya tiene el precedente de `MoatConfig.roic_spread_excellent/good/min`.

**Cambio propuesto:** extender `MoatConfig` con campos para cada dimensión (`gross_margin_excellent`, `gross_margin_good`, `gross_margin_min`, etc.). Reemplazar los literales por `self.cfg.*`. Los valores default deben ser los literales actuales para que `measure_score_impact.py --compare` dé diferencia cero.

**Contrato estable:** `MoatAnalyzer.score_quantitative()` — misma firma. `MoatDetail` — sin cambio. Scores: idénticos con los mismos valores default.

**Riesgos:** bajo si los defaults son exactamente los valores actuales. Riesgo de drift si se olvida algún literal. Solución: oráculo que compare la corrida antes/después del refactor.

**Dependencias:** hacerlo antes de O1 (refactor de `analyze()`) para no enterrar más literales.

**Estado:** ✅ Mergeado — PR R1 (2026-09-02)

**Verificación:** `scripts/measure_score_impact.py --compare` debe reportar 0 scores movidos, 0 acciones. `make check`.

---

### S5 — Fallback de ROIC absoluto hardcodeado `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** alto

**Evidencia:**
- `analysis/moat.py:651–657` — bandas `>= 20`, `>= 12`, `>= 8` para el fallback cuando no se puede calcular el spread

**Cambio propuesto:** agregar `roic_absolute_excellent`, `roic_absolute_good`, `roic_absolute_min` a `MoatConfig`. Reemplazar literales.

**Contrato estable:** mismo que S4.

**Estado:** ✅ Mergeado — PR R1 (2026-09-02)

**Verificación:** `scripts/measure_score_impact.py --compare` → 0 diferencias. `make check`.

---

### S6 — CV de EPS y banda `roe_std * 2` no están en `ConsistencyThresholds` `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** alto

**Evidencia:**
- `analysis/scoring.py:217–225` — CV thresholds hardcodeados: `<= 0.3`, `<= 0.6`, `<= 1.0`, `<= 2.0`
- `analysis/scoring.py:196` — `std <= self.ct.roe_std_max_acceptable * 2` — umbral derivado inline; si `roe_std_max_acceptable` cambia, este límite implícito cambia con él sin documentación

`ConsistencyThresholds` en `config.py` ya tiene `roe_std_max_excellent`, `roe_std_max_acceptable`, `margin_volatility_max` y `missing_data_score`. Los CV de EPS son el siguiente candidato natural.

**Cambio propuesto:** agregar `eps_cv_excellent`, `eps_cv_good`, `eps_cv_acceptable`, `eps_cv_poor` a `ConsistencyThresholds`. Nombrar el múltiplo implícito como `roe_std_moderate_multiplier = 2.0`.

**Contrato estable:** `EnhancedScoring` — misma firma. Scores: idénticos con los mismos valores default.

**Estado:** ✅ Mergeado — PR R1 (2026-09-02)

**Verificación:** `scripts/measure_score_impact.py --compare` → 0 diferencias. `make check`.

---

### S9 — `div / 15.0` en optimizer sin nombre ni config `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `portfolio/optimizer.py:532` — `div = self._clean_div_yield(...) / 15.0`

El denominador `15.0` es la escala de normalización del yield en `_rank_score`. No coincide con ningún valor existente: `max_plausible_dividend_yield_pct = 30.0`, `div_yield_sweet_spot_high = 4.0`. Afecta directamente qué tickers entran con ventaja en SLSQP.

**Cambio propuesto:** agregar `div_yield_normalization_pct: float = 15.0` a `OptimizerConfig`. El valor default reproduce el comportamiento actual exactamente.

**Contrato estable:** `PortfolioOptimizer.optimize()` — misma firma. Pesos: idénticos con el mismo default.

**Estado:** ✅ Mergeado — PR R1 (2026-09-02)

**Verificación:** `make check`. Correr el optimizer sobre la caché y comparar pesos antes/después.

---

### S10 — 5 glide-path overrides hardcodeados en optimizer `[observable]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** alto

**Evidencia (`portfolio/optimizer.py:157–186`):**
- Vol caps por horizonte: `8.0` (≤2yr, línea 158), `11.0` (≤5yr, línea 163), `15.0` (≤10yr, línea 168)
- Crypto caps: `2.0` (≤4yr, línea 174), `3.0` (≤7yr, línea 178)
- Dividend floor: `3.5` (≤3yr, línea 186)

Son las reglas del "glide path" del Goal-Aware Optimizer. Ninguna tiene nombre ni config entry. Cambiar una política de retiro requiere leer el código en vez de editar `config.py`.

**Cambio propuesto:** crear `GlidePathConfig` (o extender `OptimizerConfig`) con los seis valores. Default = valores actuales.

**Contrato estable:** `PortfolioOptimizer.optimize()` — misma firma. Pesos: idénticos con los mismos defaults.

**Riesgos:** bajo si los defaults son exactos. Verificar que `_derive_constraints_from_goals` no tiene más literales fuera de este bloque.

**Estado:** ✅ Mergeado — PR R1 (2026-09-02)

**Verificación:** `make check`. Correr optimizer con metas de horizonte corto/largo y comparar constraints.

---

### S11 — Tasa de recovery en stress test: contradicción y sin config `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `portfolio/stress_test.py:291` — comentario: `"Rough recovery estimate: assume SPY-like recovery rate (~15% p.a. from trough)"`
- `portfolio/stress_test.py:295` — código: `recovery_1yr = trough_value * 1.08`

El comentario dice 15%; el código usa 8%. Ninguno viene de config. `recovery_value_at_year1` se muestra en la UI.

**Cambio propuesto:** agregar `recovery_annual_rate: float = 0.08` a la config de stress test (o `THRESHOLDS`). Corregir el comentario para que refleje el valor en config. La decisión de si el valor correcto es 8% o 15% la toma el proyecto — el refactor solo elimina la contradicción y la hace configurable.

**Contrato estable:** `StressResult.recovery_value_at_year1` — mismo campo. Con el mismo rate, mismo valor.

**Estado:** ✅ Mergeado — PR R1 (2026-09-02)

**Verificación:** `make check`. Test unitario que corra un escenario y verifique que `recovery_1yr == trough * (1 + config_rate)`.

---

### P1 — `max_tokens=800` hardcodeado en moat AI — trunca JSON `[observable]`

**Eje:** performance · **Esfuerzo:** S · **Impacto:** alto

**Evidencia:**
- `analysis/moat.py:797–799` — `max_tokens=800` para todos los providers en `call_ai_api()`
- `analysis/ai_analyzer.py:390` — default `max_tokens or 1024`

El prompt de moat es el más largo del sistema (6 dimensiones cuantitativas + 4 rubros cualitativos + esquema JSON de salida). Respuestas truncadas en 800 tokens generan JSON incompleto que cae a `MoatParseError` y degrada el score. `ai_analyzer.py` usa 1024 para todo lo demás.

**Cambio propuesto:** agregar `ai_max_tokens: int = 1024` a `MoatConfig`. Reemplazar el literal `800`. El aumento de 800 → 1024 implica ~28% más de tokens de output por llamada de moat AI, que es un costo real pero menor al costo de un parse error que fuerza un retry.

**Contrato estable:** `MoatAnalyzer.analyze_with_ai()` — misma firma.

**Riesgos:** costo de API marginalmente mayor. Monitorearlo con `rtk gain`.

**Estado:** ✅ Mergeado — PR R1 (2026-09-02)

**Verificación:** `make check`. Correr `measure_score_impact.py` con AI encendida sobre un ticker conocido y verificar que el JSON se parsea completo.

---

---

### S23 — `rf = 0.045` literal en `portfolio/tracker.py` `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `portfolio/tracker.py:229` — `rf = 0.045  # 4.5% risk-free rate`

El proyecto unificó la tasa libre de riesgo en `config.RISK_FREE` (U5-10), pero `tracker.py` la redeclara como literal en vez de leer `RISK_FREE.annual_fraction`. Si la tasa cambia, el Sharpe del tracker diverge de los demás módulos sin advertencia.

**Cambio propuesto:** reemplazar `rf = 0.045` por `from config import RISK_FREE; rf = RISK_FREE.annual_fraction`.

**Contratos estables:** `Portfolio.compute_metrics()` — misma firma. Con el mismo valor (4.5 %), ningún número cambia.

**Riesgos:** ninguno; es una sustitución alias-por-alias.

**Estado:** ✅ Mergeado — PR #82 (2026-09-03). `portfolio/tracker.py:229` → `rf = RISK_FREE.annual_fraction` (import agregado en `:24`). `RISK_FREE.annual_fraction` = 4.5/100 = 0.045 exacto.

**Verificación:** `make check`. `scripts/measure_score_impact.py --compare`.

---

### S24 — Umbrales de drawdown severo y SORR hardcodeados en `monte_carlo.py` `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `portfolio/monte_carlo.py:877` — `pct_severe = float((max_dd_per_path >= 0.50).mean() * 100)` — "caída severa" = 50 %
- `portfolio/monte_carlo.py:889` — `sorr_early = float((early_dd >= 0.30).mean() * 100)` — "riesgo SORR temprano" = 30 %

Son umbrales de negocio que determinan dos KPIs expuestos en el dashboard (`pct_paths_severe_drawdown`, `sorr_early_drawdown_pct`). El `AlertConfig` ya tiene `sorr_high_threshold_pct = 30.0` para el dispatch de alertas, pero el motor de MC define el mismo concepto con un literal independiente. Si se recalibra uno, el otro no se mueve.

**Cambio propuesto:** agregar `severe_drawdown_threshold: float = 0.50` y `sorr_early_threshold: float = 0.30` a `MonteCarloConfig`. El motor los lee de allí. `AlertConfig.sorr_high_threshold_pct` queda como umbral de severidad de alerta (propósito distinto: cuándo disparar la notificación, no cómo medir el path).

**Contratos estables:** `MonteCarloResult.pct_paths_severe_drawdown` y `sorr_early_drawdown_pct` — mismos campos. Con los mismos defaults, números idénticos.

**Riesgos:** bajo. Los defaults reproducen el comportamiento actual exactamente.

**Estado:** ✅ Mergeado — PR #82 (2026-09-03). `MonteCarloConfig.severe_drawdown_threshold = 0.50` / `sorr_early_threshold = 0.30`; `_drawdown_stats` en `portfolio/monte_carlo.py` los lee de `MONTE_CARLO`.

**Verificación:** `make check`. `scripts/measure_score_impact.py --compare`.

---

### S25 — Pesos de señal técnica hardcodeados en `analysis/technical.py` `[observable]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia (`analysis/technical.py`, función `_derive_signal`):**
- Pesos por componente: `score += 25` (SMA alignment), `score += 10` (RSI zona), `score += 5` (MACD), `score += 10` / `+15` (tendencias adicionales)
- Umbrales de clasificación de señal: `score >= 30` → BUY, `score <= -20` → SELL (o similares)
- Umbrales de sobrecompra/sobreventa: `rsi < 30`, `rsi > 75`
- Umbrales ADX: `adx >= 25` (tendencia fuerte), `adx < 15` (mercado lateral)

Ninguno de estos pesos ni umbrales proviene de `config.py`. `analysis/technical.py` no tiene una sección de config asociada, a diferencia de todos los demás módulos del motor. Un ajuste metodológico requiere editar la lógica directamente.

**Cambio propuesto:** crear `TechnicalConfig` en `config.py` con los campos: `sma_score_weight`, `rsi_score_weight`, `macd_score_weight`, `buy_signal_threshold`, `sell_signal_threshold`, `rsi_oversold`, `rsi_overbought`, `adx_strong_trend`, `adx_ranging`. Los defaults deben reproducir los valores actuales. Instanciar `TECHNICAL = TechnicalConfig()`.

**Contratos estables:** `TechnicalResult` — sin cambio. Señales: idénticas con los mismos defaults.

**Riesgos:** bajo si los defaults son exactos. Verificar con `--compare`.

**Dependencias:** independiente; puede hacerse antes de O1.

**Estado:** ✅ Mergeado — PR #86 (2026-09-03). `TechnicalConfig` en `config.py` con **31 campos** (todos los pesos de `_derive_signal` + los umbrales compartidos RSI/ADX/slope/BB/volumen), `TECHNICAL = TechnicalConfig()`. `_derive_signal` + `_compute_trend`/`_compute_momentum`/`_compute_volatility`/`_compute_volume` los leen de `TECHNICAL`. Los *períodos* de indicador (RSI 14, MACD 12/26/9, ADX 14, SMA, BB) quedan hardcodeados a propósito (definen el indicador, no su calibración; el span del MACD tiene nota anti-cheat U3-2). Byte-idéntico: 31/31 defaults == literales shipeados; oráculo de `_derive_signal` con **0 mismatches sobre 20 000 estados aleatorios**.

**Verificación:** `scripts/measure_score_impact.py --compare` → 0/0/0 (caché worktree: 1 ticker). `make check` → 3129 passed.

---

### S26 — `_extract_annual_series` triplicada en 3 módulos de análisis `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `analysis/fundamental.py:1618` — `def _extract_annual_series(self, df, candidates) -> pd.Series`
- `analysis/moat.py:670` — `def _row_series(self, df, candidates) -> pd.Series`
- `analysis/scoring.py:368` — `def _extract(self, df, candidates) -> Optional[pd.Series]`

Los tres métodos resuelven el mismo problema: extraer una fila de un DataFrame de financial statements buscando el índice por nombre (con candidatos alternativos) y devolver una `pd.Series`. Son privados; **no idénticos** — divergieron en 4 ejes (orden del sort, `astype(float)`, qué devuelven en un miss, y si saltan un match all-NaN).

**Cambio propuesto:** mover la función canónica a `analysis/utils.py` como `extract_financial_row(df, candidates) -> Optional[pd.Series]`. Los tres módulos la importan y eliminan su propia copia.

**Contratos estables:** sin cambio; los métodos son privados.

**Estado:** ✅ Mergeado — PR #83 (2026-09-03). `analysis/utils.py::extract_financial_row(df, candidates, *, ascending, as_float, require_nonempty, missing)` — los 4 ejes de divergencia son parámetros. Los tres métodos (`_extract_annual_series`, `_row_series`, `_extract`) quedan como wrappers de 1 línea que pasan su flavour exacto, así que los 25+ call sites no cambian y el comportamiento es byte-idéntico.

**Verificación:** `make check` + `TZ=UTC make test`.

---

### S27 — SCENARIOS de stress test: ~85 shocks hardcodeados a nivel de módulo `[observable]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `portfolio/stress_test.py:40–203` — 6 instancias de `StressScenario` con `sector_shocks` y `default_shock` completamente hardcodeados como literales (GFC 2008, COVID 2020, Dot-com 2000, Bear 2022, Stagflation 1970s, Crypto Winter). Ejemplo: `"Financials": -80.0`, `"Crypto": -75.0`, etc.

Son ~85 valores de negocio (shocks por sector por escenario histórico). Solo `recovery_annual_rate` (S11, ya mergeado) fue sacado a config. Los escenarios son calibración calibrable: un cambio de metodología requiere editar la lógica directamente. Si se agrega un sector al `SECTOR_MAP`, los 6 escenarios no lo capturan automáticamente.

**Cambio propuesto:** definir los 6 `StressScenario` en `config.py` como una lista `STRESS_SCENARIOS: List[StressScenario]` (o como campo de `StressTestConfig`). `stress_test.py` los importa en vez de redeclararlos. Los valores default reproducen el comportamiento actual exactamente.

**Contratos estables:** `StressResult` — sin cambio. `SCENARIOS` en el módulo puede quedar como re-export para compatibilidad con callers existentes.

**Riesgos:** `StressScenario` es un dataclass definido en `stress_test.py`; moverlo implica decidir si va a `config.py` directamente o si se crea un módulo `data/stress_scenarios.py`. La opción más simple es que `config.py` importe `StressScenario` del módulo y los defina ahí.

**Estado:** ✅ Mergeado — PR #87 (2026-09-03). El dataclass `StressScenario` **y** los 6 `StressScenario` (`STRESS_SCENARIOS: List[StressScenario]`, 84 shocks) viven ahora en `config.py` (no hay ciclo: `config.py` no importa de `portfolio/`). `portfolio/stress_test.py` hace `from config import STRESS_SCENARIOS, STRESS_TEST, StressScenario` y `SCENARIOS = STRESS_SCENARIOS` (re-export — `tests/test_stress_test.py` sigue importando `SCENARIOS` de ahí). Oráculo: los 6 escenarios byte-idénticos a `origin/main`.

**Verificación:** `make check` + `TZ=UTC make test` → 3129 passed. `tests/test_stress_test.py` verde.

---

### S28 — `expected_annual_return=0.07` hardcodeado en `portfolio/goals.py` `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `portfolio/goals.py:426` — `def simulate_goal(..., expected_annual_return: float = 0.07, ...)`
- `portfolio/goals.py:511` — `expected_annual_return=0.07` — llamada interna que usa el mismo literal

El 7 % anual es la tasa de retorno esperada por defecto del GoalPlanner. Es un número de negocio (proxy histórico del mercado) que debería estar en `MONTE_CARLO` o en una nueva sección `GOALS` de `config.py` junto a `default_horizon_years`.

**Cambio propuesto:** agregar `default_expected_annual_return: float = 0.07` a `MonteCarloConfig`. Reemplazar los dos literales por `MONTE_CARLO.default_expected_annual_return`.

**Contratos estables:** `simulate_goal()` — misma firma. Con el mismo valor, resultados idénticos.

**Riesgos:** ninguno.

**Estado:** ✅ Mergeado — PR #82 (2026-09-03). `MonteCarloConfig.default_expected_annual_return = 0.07`; los dos literales en `portfolio/goals.py` (`required_monthly_savings` default en `:426` y el seed en `:511`) lo leen de `MONTE_CARLO`. *Nota: la función es `required_monthly_savings`, no `simulate_goal`.*

**Verificación:** `make check`.

---

## Fase R2 — Deduplicación (Esfuerzo S–M)

Eliminar código duplicado que ya tiene un lugar canónico en el codebase.

---

### S3 — `_call_nous` / `_call_xai`: ~35 líneas casi idénticas `[interno]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `analysis/ai_analyzer.py:411–444` (`_call_nous`)
- `analysis/ai_analyzer.py:446–478` (`_call_xai`)

Los dos métodos son idénticos excepto por: `base_url` default (`nousresearch.com` vs `api.x.ai`) y el resolver de credenciales en runtime (`resolve_nous_runtime_credentials` vs `resolve_xai_oauth_runtime_credentials`).

**Dependencia:** O2 (unificar dispatch). Este ítem puede ir solo si O2 se difiere, pero es más limpio hacerlos juntos.

**Cambio propuesto:** extraer `_call_openai_compatible(base_url, credential_resolver, ...)` como método privado. `_call_nous` y `_call_xai` lo llaman con sus parámetros específicos.

**Contrato estable:** `AIAnalyzer._call_api()` — misma firma. Los dos métodos siguen existiendo como delegadores de 2 líneas.

**Estado:** ✅ Mergeado — PR #76 (2026-09-02). `_call_openai_compatible` en `analysis/ai_analyzer.py:407`; `_call_nous` (`:444`) y `_call_xai` (`:452`) son delegadores.

**Verificación:** `make check`.

---

### S8 — `quickRatio` ignora el patrón `reported_metric()` `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `analysis/fundamental.py:1141` — `qr = _safe_float(info.get("quickRatio"))`

Todos los demás ratios en `_score_financial_health` — D/E (línea 1097), Current Ratio (1116) — usan `reported_metric()` o `reported_positive_metric()`. `_safe_float(None)` devuelve `0.0`, que pasa las tres ramas del scoring como "ausente = 0" y no agrega la dimensión a `missing[]`. El diagnóstico "Sin datos de…" nunca se genera para Quick Ratio.

**Cambio propuesto:** reemplazar `_safe_float(info.get("quickRatio"))` por `reported_positive_metric(info, "quickRatio")`, con el handling de `None` correcto (agregar a `missing`, no puntuar).

**Contrato estable:** `FundamentalResult` — sin cambio. Para empresas que reportan `quickRatio`, el score no cambia. Para las que no lo reportan (bancos principalmente), el score puede bajar — verificar con `measure_score_impact.py`.

**Riesgos:** puede mover scores de tickers sin `quickRatio`. Verificar antes de mergear.

**Estado:** ✅ Mergeado — PR #77 (2026-09-02). `analysis/fundamental.py:1141` → `qr = reported_positive_metric(info, "quickRatio")`.

**Verificación:** `scripts/measure_score_impact.py --compare`. `make check`.

---

### S14 — Dict comprehension de scored-ticker duplicado en `5_Optimizer.py` `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `dashboard/pages/5_Optimizer.py:496–517` — primera instancia (main run)
- `dashboard/pages/5_Optimizer.py:1341–1361` — segunda instancia (compare tab), con comentario misalineado en 1352

~20 líneas que convierten `(sym, fund, tech, dec)` en el scored-ticker dict. El segundo bloque tiene un comentario `# U5-16` que pertenece al primero.

**Cambio propuesto:** extraer `_to_scored_dict(sym, fund, tech, dec) -> dict` como función local o moverla a `dashboard/shared.py`.

**Contrato estable:** ningún cambio de firma visible.

**Estado:** ✅ Mergeado — PR #78 (2026-09-02). `_to_scored_dict(...)` usado en `dashboard/pages/5_Optimizer.py:513` y `:1336`.

**Verificación:** `make check`. Testear ambas tabs del optimizer.

---

### S15 — Defaults de sesión hardcodeados; imports mid-file `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/pages/7_Simulaciones.py:157–158` — `st.session_state["horizon_years"] = 20`
- `dashboard/pages/7_Simulaciones.py:178` — `= 30`
- `dashboard/pages/7_Simulaciones.py:210` — `initial_value = 100_000`
- `dashboard/pages/7_Simulaciones.py:400,407,410` — `from pathlib import Path as _P` repetido
- `dashboard/pages/7_Simulaciones.py:1742` — `import pandas as pd` segunda vez

`config.MONTE_CARLO` ya tiene `default_horizon_years` y `WITHDRAWAL.default_longevity_years`.

**Cambio propuesto:** seed de sesión desde `MONTE_CARLO.*` en vez de literales. Mover todos los imports al top del archivo.

**Contrato estable:** sin cambio de comportamiento si los valores en config coinciden con los actuales.

**Estado:** ✅ Mergeado — PR #78 (2026-09-02). `7_Simulaciones.py:152/173` siembran de `MONTE_CARLO.default_horizon_years` / `WITHDRAWAL.default_longevity_years`; imports al top. *Pendiente menor:* los presets de las líneas 159/166 aún usan literales `25` y `8`.

**Verificación:** `make check`.

---

### S18 — Guard de sesión duplicado en ≥3 páginas `[interno]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `dashboard/pages/2_Stock_Analysis.py:70–77` — bloque inline (usaba `load_universe`, sin customs)
- `dashboard/pages/5_Optimizer.py:143–152` — bloque inline (usaba `load_universe_with_customs`)
- `7_Simulaciones.py` — solo la mitad de prefs, vía `get_user_prefs()`; no toca `universe`/`portfolio`

Los bloques re-implementaban la inicialización de `user_prefs`, `universe` y `portfolio` en session state, y **divergían**: Stock Analysis cargaba el universo sin custom tickers, Optimizer con customs (el mismo que `app.py`).

**Cambio propuesto:** `dashboard/shared.py` ya tiene `get_user_prefs()`. Agregar `ensure_session_defaults()` que centralice el guard completo para las tres variables. Las páginas llaman a ese helper.

**Contrato estable:** el estado que produce `app.py` pasa a ser el único. **Cambio de comportamiento acotado:** en el path raro "sesión fresca + navegación directa a `2_Stock_Analysis.py`" (sin pasar por Home, `app.py` no corrió), el selectbox de tickers (`2_Stock_Analysis.py:91` lee `st.session_state.get("universe")`) ahora incluye los custom tickers del usuario, igual que en todo otro camino de entrada. Antes ese path mostraba menos tickers que el resto de la app.

**Estado:** ✅ Mergeado — PR #85 (2026-09-03). `dashboard/shared.py::ensure_session_defaults()` reusa `get_user_prefs()` y replica la init de `app.py` (universe con customs + `Portfolio()`). **`app.py`, `2_Stock_Analysis.py` y `5_Optimizer.py` los tres llaman al helper** — no queda ninguna copia inline (finding de code-review). `app.py` sigue sembrando `ai_provider`/`ai_model`/`ai_api_key` aparte. Imports muertos sacados (`load_universe` en 2_SA, `Portfolio` en `app.py`).

**Verificación:** `make check` → 3129 passed. `ruff` limpio.

---

### S19 — `_price_lookup` en scheduler duplica lógica de shared.py `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `scripts/run_scheduler.py:288–294` — closure `_price_lookup` para `compute_plan_vs_reality`
- `dashboard/shared.py` — `plan_price_lookup` con lógica equivalente

El scheduler no puede importar `dashboard/shared.py` (arrastraría Streamlit). La solución es extraer la función pura a una capa sin Streamlit.

**Cambio propuesto:** mover `plan_price_lookup` (o su núcleo funcional) a `data/fetcher.py` o `data/plan_context.py`. Tanto el scheduler como shared.py la importan desde ahí. Mantener el nombre en shared.py como re-export si hay callers existentes.

**Contrato estable:** `compute_plan_vs_reality(price_lookup=...)` — misma firma inyectable.

**Estado:** ✅ Mergeado — PR #79 (2026-09-02). `plan_price_lookup` vive en `data/plan_context.py`; el scheduler la importa y `dashboard/shared.py` la re-exporta.

**Verificación:** `make check`. Correr `scripts/run_scheduler.py --dry-run` si existe esa flag.

---

### S22 — `_analyse_one` mezcla extracción de datos con UI strings `[interno]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia (verificada 2026-09-03):**
- `dashboard/shared.py:1746–1814` — closure `_analyse_one` dentro del thread pool de `_analyse_universe_parallel` (`shared.py:1712`)

La closure construye un dict con 20+ keys que incluyen strings de UI (emoji-prefixed sector label, `fund.company_name[:25]` truncation, badge formatting). Esta lógica de presentación vive dentro de un worker concurrente y se duplica parcialmente con el row builder del scheduler.

**Cambio propuesto:** separar en dos funciones puras: `_extract_row_data(sym, fund, tech, dec) -> dict` (datos crudos, sin strings de UI) y `_format_row_for_display(row: dict) -> dict` (strings, badges, truncado). El worker llama a la primera; la segunda se aplica en el thread principal o en el display layer.

**Contrato estable:** la tabla del screener muestra los mismos datos.

**Estado:** ✅ Mergeado — PR #92 (2026-09-04), con **revisión visual del screener aprobada** (playwright-cli sobre la app: análisis end-to-end sin errores, `Company` truncada a 25, `Signal` con emoji, badges/columnas completas, chart "Top 15" + histograma poblados). `dashboard/shared.py`: `_extract_row_data(sym, fund, tech, decision) -> dict` (crudo, thread pool) + `_format_row_for_display(d) -> dict` (badges/emoji/truncado, main thread) como funciones de módulo. El worker `_analyse_one` solo llama a la primera; el loop del pool aplica la segunda antes de `rows.append`. Byte-idéntico: oráculo (mismas keys, mismos valores salvo `_measured_at`) + `tests/test_screener_page_contract.py` (drive el `_analyse_universe_parallel` real). Finding de code-review: sacar el formato del `try` del worker rompía "una excepción por ticker no aborta la corrida" → el loop del pool envuelve `_format_row_for_display` en try/except (test nuevo `test_analyse_universe_parallel_isolates_formatting_failures`). `make check` → 3141 passed.

**Verificación:** `make check`. Verificar visualmente la tabla del screener.

---

### P2 — Unread-alert count consultado dos veces por rerun `[interno]`

**Eje:** performance · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/app.py:469–476` — `_get_unread_count()` para el badge del sidebar
- `build_home_hub_for_prefs` (llamada unas líneas antes en `_home_page`) también llama internamente a `alert_store.get_unread_count()`

Dos queries SQLite en el mismo rerun para el mismo valor.

**Cambio propuesto:** calcular el count una sola vez al inicio del rerun y pasarlo como parámetro a `build_home_hub_for_prefs`, o cachearlo en session_state con TTL corto.

**Contrato estable:** el badge del sidebar muestra el mismo número.

**Estado:** ✅ Mergeado — PR #84 (2026-09-03). `dashboard/shared.py::unread_alert_count()` con `@st.cache_data(ttl=300)` es la única fuente: el sidebar (`app.py`), `next_priority_action` y `build_home_hub_for_prefs` la llaman, y el caché colapsa las 3 lecturas de un render de home en 1. Antes: 3 `alert_store.get_unread_count()` por rerun.

**Verificación:** `make check`. Verificar badge en la UI.

---

### O3 — `cached_stress_test` acepta `dict` crudo como param de caché `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `dashboard/shared.py:1501–1510` — `cached_stress_test(sector_weights: dict[str, float], ...)`
- El resto de las funciones `@st.cache_data` de shared.py convierten `dict` a `tuple` antes de usarlos como params (e.g., `drags_tuple` línea 1341, `withdrawal_tuple` 1342, `scored_tickers_tuple` 1485)

`@st.cache_data` hashea dicts por valor en Streamlit moderno, pero el patrón establecido en el proyecto es explícitamente convertir a tuples para garantizar hashability (estándar documentado en `CONTEXT.md §5`). La inconsistencia hace que `cached_stress_test` sea la excepción sin justificación.

**Cambio propuesto:** agregar `sector_weights_tuple: tuple = tuple(sorted(sector_weights.items()))` antes del call y usar eso como param del caché, siguiendo el mismo patrón de `drags_to_tuple`.

**Contrato estable:** misma semántica de caché; mismo resultado.

**Estado:** ✅ Mergeado — PR #78 (2026-09-02). `dashboard/shared.py:1489` `cached_stress_test(sector_weights_tuple: tuple, ...)` → `dict(sector_weights_tuple)`.

**Verificación:** `make check`.

---

---

### P3 — `print()` en `portfolio/personal_sizer.py` — no usa loguru `[interno]`

**Eje:** performance · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `portfolio/personal_sizer.py:37` — `print(analysis.overall_summary)`

**Estado:** ✅ Cerrado por inspección — PR #81 (2026-09-03). La evidencia era incorrecta: la línea 37 está **dentro del docstring del módulo** (bloque "Uso standalone::", cerrado por `"""` en la línea 38), no es código ejecutable. El módulo ya usa `loguru` en todo el output real (`logger.info`/`logger.warning` en las líneas 710/756/761) y ya importa `from loguru import logger` (línea 45). Un `print()` en un ejemplo de uso de docstring es la convención correcta (así se lee en un REPL) — no se toca.

**Verificación:** `rtk proxy grep -n "print(" portfolio/personal_sizer.py` → única coincidencia es la línea 37 del docstring.

---

## Fase R3 — Ordenamiento entre capas (Esfuerzo M–L)

Responsabilidades mal asignadas entre módulos. Mayor riesgo; requiere regresión end-to-end.

---

### O9 — Settings importa `data.cache` y `data.fetcher` directamente `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/pages/9_Settings.py:11` — `from data.cache import cache`
- `dashboard/pages/9_Settings.py:12` — `from data.fetcher import usd_ars_quote`

El estándar del proyecto (CONTEXT.md §5) prohíbe que las páginas del dashboard importen directamente de la capa `data/`. Settings usa `cache.invalidate(...)` para limpiar la caché desde la UI y `usd_ars_quote` para mostrar/refrescar el tipo de cambio. Si cambia la interfaz de `data.cache` o `data.fetcher`, la página rompe.

**Cambio propuesto:** agregar `invalidate_ticker_cache(ticker)` y `get_usd_ars_quote()` (o un wrapper) en `dashboard/shared.py`. La página los importa desde ahí. O6 (sidebar → alert_store) tiene exactamente el mismo patrón y se resuelve junto a P2.

**Contratos estables:** la página de Settings muestra los mismos datos y produce el mismo efecto de invalidación.

**Riesgos:** bajo. Son wrappers de una línea.

**Dependencias:** independiente; puede hacerse junto a O6/P2 para consistencia.

**Estado:** ✅ Mergeado — PR #84 (2026-09-03). `dashboard/shared.py` expone `cache_stats()`, `clear_data_cache()` y `usd_ars_quote()` (wrappers con import lazy). `9_Settings.py` los importa de shared; sacadas las líneas `from data.cache import cache` y `from data.fetcher import usd_ars_quote`. *Gap conocido fuera de scope:* el bloque "snapshot del universo" (`9_Settings.py:~145`) todavía hace `from data.fetcher import get_info` + `from data.snapshot import ...` lazy — feature aparte, no cubierta por la evidencia de O9.

**Verificación:** `make check`. Probar la sección de caché en Settings manualmente.

---

### O2 — Dispatch de provider AI duplicado en dos módulos `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** M · **Impacto:** alto

**Evidencia (verificada 2026-09-03):**
- `analysis/moat.py:502` — `MoatAnalyzer._call_api(prompt, ai_config)` + `analysis/moat.py:781` — módulo-level `call_ai_api(prompt, ai_config, max_tokens: int = 1024)` — maneja `claude`, `openai`, `xai`, `nous`; compartido con `CryptoAnalyzer` y `analysis/tailwind.py:340`
- `analysis/ai_analyzer.py:371` — `AIAnalyzer._call_api()` delega a `_call_claude`, `_call_openai_compatible` (`_call_nous`/`_call_xai`)

Son dos implementaciones paralelas del mismo dispatch de provider. *Nota: el `max_tokens=800` que citaba la evidencia original ya fue corregido a 1024 por P1; lo que persiste es la duplicación del dispatch.* Agregar un proveedor requiere editar los dos archivos.

**Cambio propuesto:** consolidar en `AIAnalyzer._call_api()` como punto único. `MoatAnalyzer` recibe una instancia de `AIAnalyzer` (ya lo hace parcialmente) y delega todos los calls de red ahí. `call_ai_api()` en `moat.py` puede quedar como shim deprecado durante una transición.

**Contrato estable:** `MoatAnalyzer.analyze_with_ai()` — misma firma y resultado. `AIAnalyzer` — sin cambio.

**Riesgos:** requiere que `MoatAnalyzer` pueda construirse con un `AIAnalyzer` inyectado. Revisar que los tests de moat existentes no rompan.

**Dependencias:** S3 ya mergeado (PR #76) — O2 pasa a standalone.

**Estado:** ✅ Mergeado — PR #90 (2026-09-03), **con aprobación explícita del usuario**. `analysis/moat.py::call_ai_api` pasa a ser un shim que delega en `AIAnalyzer(ai_config)._call_api(prompt, max_tokens=…)` (dispatch único). Preserva la firma y el contrato `MoatAPIError` (con el shim dentro del `try` tras code-review). `MoatAnalyzer._call_api` y los callers `CryptoAnalyzer`/`analysis.tailwind` no cambian. `tests/test_call_ai_api_shim.py` (4 tests). **Cambio de comportamiento acotado, aceptado por el usuario:** el path `nous` de `moat.py` usaba (bug) el resolver + base-url de xAI; ahora usa los de nous (`AIAnalyzer._call_nous`); mensajes de error de "sin credenciales" también cambian. Con `claude`/`openai`/`xai` nada cambia. `make check` → 3133 passed. **La verificación AI-on no se pudo correr** (caché de este worktree sin entradas de moat AI, `--matrix` "cache-only miss").

**Verificación:** `make check`. `scripts/measure_score_impact.py` con AI on — los scores de moat no deben cambiar.

---

### O4 — `run_holdings_committee` (orquestación de negocio) en módulo de UI `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `dashboard/shared.py:1513–1584` — 72 líneas que corren stress test, calculan trades de alineación, obtienen contexto macro, construyen la clave MD5 del plan y convocan el comité

Esta función no hace ninguna llamada `st.*`. Es lógica de orquestación pura que accidentalmente vive en el shared del dashboard.

**Cambio propuesto:** mover el núcleo a `analysis/committee.py` como función libre (donde ya vive `analyze_portfolio`). El wrapper en `shared.py` puede quedar como re-export para no romper callers existentes.

**Contrato estable:** `run_holdings_committee(...)` — misma firma desde el punto de vista de las páginas.

**Estado:** ✅ Mergeado — PR #89 (2026-09-03). `analysis/committee.py::run_holdings_committee(*, metrics, sector_weights, position_weights, total_value, ai_config, stress_results=None, active_plan=None)` — función libre, sin `st.*`, junto a `build_holdings_committee_context` y `CommitteeAnalyzer`. El wrapper en `dashboard/shared.py` mantiene su firma para las páginas (`3_Portfolio.py:253` sin cambio) y solo resuelve `ai_config` (`_get_ai_config()`) + `stress_results` (`cached_stress_test`, `@st.cache_data`) del lado Streamlit y delega. `tests/test_portfolio_committee.py` verde (12).

**Verificación:** `make check` → 3129 passed. Probar la sección de comité en `3_Portfolio.py`.

---

### O5 — Página de alertas importa `AlertEngine` y `ReportGenerator` directamente `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** M · **Impacto:** bajo

**Evidencia:**
- `dashboard/pages/8_Alertas.py:11–13` — imports directos de `alerts.engine` y `alerts.reporter`

Si cambia la firma del constructor de `AlertEngine` o `ReportGenerator`, la página rompe. El patrón establecido para el comité es tener un wrapper en `shared.py`.

**Cambio propuesto:** agregar `run_alert_engine(...)` y `generate_alert_report(...)` en `dashboard/shared.py`. La página solo importa de shared.

**Contrato estable:** la página de alertas muestra los mismos resultados.

**Estado:** ✅ Mergeado — PR #88 (2026-09-03). `dashboard/shared.py::run_alert_engine(scored, *, active_profile, positions=None, current_prices=None, optimizer_weights=None)` (dispatch a `run`/`run_with_portfolio` según `positions`) + `generate_alert_report(scored, *, period)`. `8_Alertas.py` sin `from alerts.engine`/`from alerts.reporter` (sigue importando `alerts.store` para los enums `AlertSeverity`/`AlertType` — fuera del scope de O5).

**Verificación:** `make check`. Probar la página manualmente.

---

### O6 — Sidebar importa `alert_store` directamente `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/app.py:471` — `from alerts.store import alert_store`

`build_home_hub_for_prefs` en `shared.py` ya consulta el unread count. El sidebar puede recibir el valor como parámetro desde `_home_page` en vez de importar el store directamente.

**Cambio propuesto:** ver P2 — resolver ambos juntos. El sidebar lee el count de una variable calculada una sola vez.

**Estado:** ✅ Mergeado — PR #84 (2026-09-03). `app.py` importa `unread_alert_count` de `dashboard.shared`; ya no hay `from alerts.store import alert_store` en `app.py`.

**Verificación:** `make check`.

---

### O7 — Stock Analysis importa `data.data_sources` y `data.fetcher` directamente `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/pages/2_Stock_Analysis.py:22` — `from data.fetcher import get_history`
- `dashboard/pages/2_Stock_Analysis.py:61` — `from data.data_sources import default_fundamental_sources`

Dos imports directos de la capa de datos desde la misma página. `get_history` se usa para el chart de precio histórico; `_cross_source_check` (líneas 53–64) usa `default_fundamental_sources`. Ambos podrían vivir en `dashboard/shared.py` con `@st.cache_data`, manteniendo la página libre de imports de la capa de datos.

**Cambio propuesto:** mover `_cross_source_check` y `get_history` (o un wrapper cacheado) a `shared.py`. La página importa solo los helpers cacheados.

**Estado:** ✅ Mergeado — PR #88 (2026-09-03). `dashboard/shared.py::get_price_history(symbol, period, interval)` (`@st.cache_data`) + `cross_source_check(symbol)` (movido verbatim). `2_Stock_Analysis.py` sin `from data.fetcher`/`from data.data_sources`. (`16_Calidad_Datos.py` también importa `default_fundamental_sources` — fuera del scope de O7.)

**Verificación:** `make check`.

---

### O8 — Migraciones one-shot mezcladas con scripts operacionales `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia (estado original, pre-PR #81):**
- `scripts/mark_test_fixture_rows.py:1` — migración one-shot de fixture rows (ejecutada 2026-08-30)
- `scripts/purge_test_alert_rows.py:1` — migración one-shot de alert rows

Ambos vivían junto a `run_scheduler.py` / `run_eval.py`. Tras PR #81 están en `scripts/migrations/`.

Viven junto a `run_scheduler.py`, `run_eval.py` y herramientas operacionales. Un nuevo contribuidor no puede distinguir "herramienta que se corre seguido" de "script que ya cumplió su propósito".

**Cambio propuesto:** mover los dos archivos a `scripts/migrations/`. Agregar un `scripts/migrations/README.md` que explique cuándo se corrieron y que son idempotentes.

**Contrato estable:** los scripts siguen funcionando; solo cambia su ubicación.

**Estado:** ✅ Mergeado — PR #81 (2026-09-03). `scripts/migrations/{mark_test_fixture_rows,purge_test_alert_rows}.py` + `README.md`. `sys.path.insert(... parents[1])` → `parents[2]`. Callers actualizados: `tests/test_track_record_fixture_exclusion_oracle.py`, `tests/test_track_record_dedupe_read_oracle.py`, comentario en `analysis/track_record.py`, `docs/ROADMAP.md`, `docs/CONTEXT.md §8`. `scripts/migrations/` registrado como colección `how-to` en `docs/INDEX.md`.

**Verificación:** `make check` (incluye `tests/test_doc_catalog.py` y los oráculos del track record).

---

### O1 — `FundamentalAnalyzer.analyze()`: God method de 215 líneas `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** L · **Impacto:** alto

**Evidencia (verificada 2026-09-03):**
- `analysis/fundamental.py:733`–~`952` — método único que hace: fetch de datos yfinance, clasificación de activo, 5 dimensiones de scoring, Graham, EnhancedScoring (Consistency + Piotroski), MoatAnalyzer, TailwindAnalyzer, adjusted_score, data quality, cross-source quality, logging.

Ninguna de estas responsabilidades se puede cambiar sin leer el método completo. Las funciones de dimensión ya están extraídas (`_score_profitability`, etc.) pero `analyze()` es el cuello de botella donde todas se acoplan.

**Cambio propuesto:** extraer sub-métodos privados:
- `_run_scoring_pipeline(info, fund_data) -> ScoringResults`
- `_run_moat_pipeline(info, fund_data, scoring) -> MoatDetail`
- `_run_tailwind_pipeline(ticker, fund_data) -> TailwindDetail`
- `_assemble_result(...)` — solo construye el dataclass

`analyze()` se convierte en un orquestador de 30–40 líneas que llama a estos métodos en orden.

**Contrato estable:** `FundamentalResult` — misma estructura. `FundamentalAnalyzer.analyze()` — misma firma y semántica. `full_analysis()` en strategy.py — sin cambio.

**Riesgos:** alto. Es el método más central del motor. Requiere tests de regresión exhaustivos con `measure_score_impact.py --compare` (0 scores deben moverse). Hacer en un PR dedicado.

**Dependencias:** S4/S5 (moat thresholds a config) ya mergeados (PR R1). T2 (test de integración de `analyze()`) debe mergearse **antes** — ver plan P-11 → P-16.

**Verificación:** `scripts/measure_score_impact.py --compare` → 0 scores movidos. `make check`. `TZ=UTC make test`.

**Estado:** ✅ Mergeado — PR #96 (2026-09-04) **con aprobación explícita del usuario**. `analyze()` (215 líneas) → orquestador de ~30 líneas con 8 sub-métodos: `_try_crypto_fast_path`, `_populate_identity`, `_populate_prescoring_metrics`, `_run_scoring_pipeline`, `_run_moat_pipeline`, `_run_tailwind_pipeline`, `_assemble_result`, `_finalize_data_quality`. Desviación documentada del plan original: se mantiene mutación in-place del acumulador `result` (no value objects como `ScoringResults`/`MoatDetail`) — los scorers de dimensión ya leen campos que sus predecesores setean (`total_score` → Enhanced/Moat; `eps_cagr_5y` → Graham), así que un rediseño a value objects sería mucho más invasivo para 0 ganancia sobre el orquestador. `measure_score_impact.py --compare` → 0 scores / 0 señales movidas sobre 25 tickers cacheados. `make check` 3172 + `TZ=UTC make test` 3172 passed/2 skipped. `/code-review` sin findings. Revisión visual con playwright-cli: Screener con análisis fresco de 25 tickers sin errores; Stock Analysis con AAPL completo (BUY, Piotroski 8/9, Moat Narrow 9.0/20, Graham) sin errores de consola.

---

### S16 — `_home_page()` ~200 líneas `[interno]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia (verificada 2026-09-03):**
- `dashboard/app.py:133`–~`360` — función única que renderiza métricas, plan hub, action card, onboarding wizard, guided journey, sample-plan loading (con try/except y `st.switch_page`), y disclaimer; sin helpers `_render_*`

**Cambio propuesto:** extraer `_render_plan_hub()`, `_render_guided_journey()`, `_render_sample_plan_section()`. Cada una con sus imports y su estado local.

**Contrato estable:** la página de inicio muestra los mismos componentes en el mismo orden.

**Estado:** ✅ Mergeado — PR #93 (2026-09-04). Revisión visual OK. `dashboard/app.py`: `_home_page` queda como orquestador de ~20 líneas; extraídos `_render_plan_hub(hub, action, prefs)`, `_render_profile_section(prefs)`, `_render_guided_journey(prefs)`, `_render_getting_started()` + `_load_activate_sample(prefs, key, *, toast_msg)` (dedup de los 2 handlers de "cargar plan de ejemplo"). Mismos `st.*` en el mismo orden, mismas keys de widget (`home_hub_sample`/`home_today_action`/`home_onb`/`home_journey_next`/`home_try_sample`), mismo anidado de contenedores. `make check` → 3141. Revisión visual con playwright-cli: home en sesión fresca y con plan de ejemplo activo — mismos headings en el mismo orden, botones presentes, el botón de plan de ejemplo navega a Mi Plan, hub muestra valores reales (72% / $780k), sin errores.

**Plan (P-13, 2026-09-04) — independiente de P-14 (archivos distintos: `app.py` vs `shared.py`; sin dependencia):**
- **Alcance:** extraer de `_home_page()` (`dashboard/app.py:133`–~360) → `_render_plan_hub(hub, prefs, pages_dir)`, `_render_guided_journey(prefs, pages_dir)`, `_render_sample_plan_section(pages_dir)`. `_home_page` queda como orquestador de ~40 líneas: métricas → divider → hub → wizard/summary → guided journey → disclaimer, en ese orden. Puro estructural: mismos `st.*` en el mismo orden, mismo estado local (pasar `_hub`/`_prefs_home`/`_pages_dir` como params, no re-derivar).
- **Evidencia mínima para aprobar:** `make check` verde · `/code-review` sin findings de correctness · árbol de widgets idéntico (mismos headings/botones/orden) verificado con playwright-cli sobre la **home**, en dos estados: (a) sesión fresca sin plan, (b) con un plan de ejemplo activado. Console sin errores nuevos.
- **Condición de stop/split:** si una sección necesita hilar >3 params o comparte estado mutable con otra → dividir en sub-PR más chico o dejar esa sección sin extraer y anotarlo.

**Verificación:** `make check`. Probar la home en frío y con plan activo.

---

### S17 — `render_*_controls` mutan session_state dentro del render `[interno]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `dashboard/shared.py:1145–1214` — `render_withdrawal_controls` escribe `st.session_state["withdrawal_kind"]`, luego lee con `get_withdrawal_strategy()`
- `dashboard/shared.py:987–1040` — `render_drags_controls` — mismo patrón

El anti-patrón acopla la phase de render con la de lectura de estado y hace difícil testear la función pura.

**Cambio propuesto:** separar en `render_withdrawal_controls() -> WithdrawalStrategy` (solo widgets, devuelve el valor) y mantener la escritura en session_state solo para persistencia cross-rerun. La función no debe leer de session_state lo que ella misma acaba de escribir en el mismo call.

**Contrato estable:** los callers que usan el return value no cambian.

**Estado:** ✅ Mergeado — PR #94 (2026-09-04). Extraídos `_build_withdrawal_strategy(kind, *, amount, pct, base)` y `_build_economic_drags(enabled, component_pcts)` — puros, sin lecturas de `st.session_state`. `get_withdrawal_strategy` / `get_economic_drags` (que las páginas siguen llamando aparte) quedan como thin readers que delegan al builder. `render_withdrawal_controls` / `render_drags_controls` arman el dict con los valores frescos de los widgets (no releen las keys que acaban de escribir); las escrituras a session_state se conservan para persistencia cross-rerun. Byte-idéntico: oráculo 0 mismatches (11 casos) + `_build_* == get_*`. `make check` → 3141. Revisión visual playwright-cli de Simulaciones (nav por sidebar): ambos bloques renderizan; al elegir "Retiro fijo real" aparecen los inputs y el badge refleja el valor fresco ("$4,000/año"); panel de drags con sus 4 inputs + badge correcto; sin errores de página (los errores de consola son de Plotly con chart vacío, pre-existentes).

**Plan (P-14, 2026-09-04) — independiente de P-13 (toca `dashboard/shared.py`, no `app.py`):**
- **Alcance:** `render_withdrawal_controls()` (`shared.py:1243`) y `render_drags_controls()` (`:1085`). Hoy escriben a `session_state` (`withdrawal_kind`, `drag_*`, …) y en el mismo call releen ese estado para armar el valor de retorno. Cambio: computar el valor de retorno **directo de los widgets**; la escritura a `session_state` queda **solo para persistencia cross-rerun**, nunca como fuente de lectura dentro del mismo call. Firmas y valores de retorno sin cambiar.
- **Evidencia mínima para aprobar:** `make check` verde (incl. `tests/test_product_ux.py`, `tests/test_plan_page_runtime.py`) · oráculo: para un set de inputs de widget, `render_*_controls()` devuelve el mismo dict antes/después · `/code-review` sin findings · revisión visual con playwright-cli de **Simulaciones** (tab de decumulación + panel de drags): mismos widgets, mismos defaults, el resultado del MC no cambia al setear cada estrategia.
- **Condición de stop/split:** si algún caller depende del **efecto secundario** en `session_state` (no del return) → mantener la escritura (S17 solo prohíbe *releer* lo recién escrito); si aparece un caller así, documentarlo y no tocar esa rama.

**Verificación:** `make check`. Probar los controles de retiro en la UI.

---

### S12 — `7_Simulaciones.py`: 2.420 líneas sin helpers `[interno]`

**Eje:** simplicidad · **Esfuerzo:** L · **Impacto:** alto

**Evidencia:**
- `dashboard/pages/7_Simulaciones.py:1–2420` — código secuencial plano, sin funciones helper (solo dos formatters de 4 líneas en 76 y 83)

Cubre: MC baseline, 3 tabs de perfiles, goal cards (add/edit/delete/fund forms), stress testing, tornado de sensibilidad, modo ARS dual, generación de PDF, narrativa AI.

**Cambio propuesto:** extraer secciones como funciones con nombres descriptivos:
- `_render_mc_baseline_tab(...)` 
- `_render_profile_comparison_tab(...)`
- `_render_goal_section(...)`
- `_render_stress_tab(...)`
- `_render_sensitivity_lab(...)`
- `_render_pdf_section(...)`

El cuerpo principal del módulo queda como un dispatcher de ~50 líneas.

**Contrato estable:** la página muestra los mismos tabs y resultados.

**Riesgos:** alto. El archivo más largo del repo. Hacer en un PR dedicado con revisión visual de cada sección. No combinar con otros refactors.

**Verificación:** `make check`. Probar todas las tabs manualmente (MC, goals, stress, tornado). `TZ=UTC make test`.

**Estado:** ✅ Mergeado — PR #97 (2026-09-04). Tres de las cinco tabs ya estaban extraídas como funciones (`_tab_mc_content`, `_render_sensitivity_lab`, `_tab_compare_content`); este PR mueve las dos que quedaban inline: `_tab_stress_content()` (bloque `with tab_stress:`, 123 líneas) y `_tab_custom_content()` (bloque `with tab_custom:`, 60 líneas) — ambas movidas a `def` justo donde vivían, con un dispatch `with tab_x: _tab_x_content()` inmediatamente después, sin reordenar nada respecto al resto del módulo. El bloque más grande y riesgoso, `with tab_goals:` (Planificador de Metas, ~954 líneas: goal cards, fan charts Monte Carlo por meta, timeline), se convirtió en `_tab_goals_content()` con el mismo mecanismo. Desviación documentada del plan: no se sub-dividió `tab_goals` en `_render_goal_section`/`_render_pdf_section` como sugería la propuesta original — se optó por el mismo patrón mecánico ya usado en el archivo (una función por tab, sin reestructurar la lógica interna), para minimizar el riesgo en el archivo más largo del repo. El cuerpo del módulo queda como un dispatcher: 5 bloques `with tab_x: _tab_x_content()` en el orden original de ejecución (idéntico antes/después). Byte-idéntico: cero cambios de lógica, solo `with tab_x:` → `def _tab_x_content():` + llamada en el mismo lugar. `make check` 3172 + `TZ=UTC make test` 3172 passed/2 skipped. Revisión visual con playwright-cli de las 5 tabs: Monte Carlo (ejecutar simulación → 95% probabilidad + distribución + sensibilidad), Stress Test (tabla + 2 gráficos + detalle por sector), Escenario personalizado (cálculo de impacto + gráfico de recuperación), Comparar Perfiles, Mis Metas (agregar meta → simular plan completo → resumen + resultados por meta + timeline). Sin errores de consola nuevos (el único error de Plotly con `translate(NaN,...)` es pre-existente, ya documentado en P-14).

---

## Fase R4 — Cobertura de tests

---

### T1 — Cero tests para `dashboard/shared.py` (1.891 líneas) `[interno]`

**Eje:** cobertura · **Esfuerzo:** M · **Impacto:** alto

**Evidencia:**
- `dashboard/shared.py` — módulo más grande del dashboard: `build_home_hub_for_prefs`, `plan_journey_status`, `next_priority_action`, `export_plan_bundle`, `drags_to_tuple`, `withdrawal_to_tuple`, `_sensitivity_run_fn`, `run_holdings_committee`, `log_screener_run`. Ninguna tiene un test.

Las funciones con mayor riesgo son:
1. **`export_plan_bundle`** — genera el backup JSON del usuario. Falla silenciosa = pérdida de datos. Tiene branches en `prefs.is_onboarded`, `drag_note`, y filename sanitization.
2. **`drags_to_tuple` / `withdrawal_to_tuple`** — contratos de cache key. Si excluyen o incluyen una clave incorrectamente, el cache da hits falsos o misses innecesarios.
3. **`plan_journey_status` / `next_priority_action`** — impulsan el CTA de la home. Branches en onboarding status, plan activo, alertas no leídas, y frescura del plan.

**Cambio propuesto:** crear `tests/test_shared_pure.py` que cubra las funciones puras (sin `st.*`). Seguir el patrón de `tests/conftest.py` existente para aislar dependencias de Streamlit.

**Prioridad dentro del ítem:**
1. `drags_to_tuple` / `withdrawal_to_tuple` (contratos de cache — alta prioridad)
2. `export_plan_bundle` (pérdida de datos potencial)
3. `plan_journey_status` / `next_priority_action`

**Contrato estable:** no cambia código de producción.

**Verificación:** `make check`. Los nuevos tests deben pasar sin `st` en el entorno.

**Estado:** ✅ Mergeado — PR #95 (2026-09-04). `tests/test_shared_pure.py` (31 tests): `drags_to_tuple` / `withdrawal_to_tuple` (None/vacío → None, exclusión de `total_annual_drag_pct` / `label`, drop de no-escalares, orden estable independiente del insertion order, hashabilidad, keys iguales para inputs equivalentes); `plan_journey_status` (5 pasos, paso "respaldá" done cuando no hay nada que respaldar y pending al guardar, flags de export por session y por prefs, lectura de cualquiera de las 2 keys de optimizer, `active_plan_id` con espacios ≠ activo); `next_priority_action` (journey incompleto → primer paso pendiente; alertas no leídas > 0; plan activo stale / nunca refrescado → health check; todo en línea; excepción de `get_active_plan` swallowed); `export_plan_bundle` (tupla `(bytes, filename, md)`, snapshot completo sin campos perdidos, bloque `personal` solo si `is_onboarded`, sanitización de `snap.id` inseguro, fallback a `"plan"`, `drag_note` condicional, UTF-8 round-trip). Sin runtime de Streamlit: `shared.st` → stub con `session_state` dict; colaboradores I/O monkeypatched. Cero cambios en producción.

---

---

### T2 — Sin test de integración para `FundamentalAnalyzer.analyze()` `[interno]`

**Eje:** cobertura · **Esfuerzo:** M · **Impacto:** alto

**Evidencia:**
- `analysis/fundamental.py` — 1637 líneas; el método `analyze()` (líneas 733–947) es el corazón del motor de scoring
- `tests/` — existen tests especializados por comportamiento (`test_eps_growth_and_graham.py`, `test_reit_ffo.py`, `test_dividend_yield_units.py`, `test_data_quality.py`, etc.) pero **no existe `tests/test_fundamental.py`** que cubra el flujo completo del pipeline

Los tests especializados prueban casos de borde específicos pero no detectarían una regresión en la orquestación general de `analyze()` — por ejemplo, que el `adjusted_score` no incluya el bonus de moat, que la clasificación de activo no se propague correctamente a los sub-scorers, o que los ramos de fallback (sin estados financieros) no devuelvan el `FundamentalResult` correcto.

**Las funciones de mayor riesgo sin cobertura de integración:**
1. **Flujo completo `analyze(ticker)`** — 14 responsabilidades en secuencia; cualquier regresión en el orden o la propagación pasa inadvertida
2. **Fast-path de crypto** — lógica bifurcada desde la línea 737; solo cubierto indirectamente por `test_crypto_scoring.py`
3. **Cross-source quality check** — llamada a `data.data_sources` que puede degradar silenciosamente el badge si falla

**Cambio propuesto:** crear `tests/test_fundamental.py` con:
- Un test de integración por asset class (equity standard, REIT, crypto) usando fixtures de `conftest.py`
- Test que verifica que `adjusted_score >= total_score` cuando hay moat/consistency (invariante del motor)
- Test de fast-path crypto: `analyze("BTC-USD")` devuelve `FundamentalResult` válido sin iterar por los sub-scorers de equity

**Contratos estables:** no cambia código de producción.

**Riesgos:** los fixtures de `info` para equity son complejos. Reusar el patrón de `test_scoring.py` y `test_strategy.py` que ya mockan `get_info`.

**Dependencias:** más urgente si se hace O1 (refactor de `analyze()`) — tener tests de integración antes del refactor garantiza que no se rompe nada.

**Estado:** ✅ Mergeado — PR #91 (2026-09-03). `tests/test_fundamental.py` (7 tests) con el patrón de `test_reit_ffo.py` (`patch` de `get_info`/`get_financials`/`get_dividends`/`get_info_age_hours`): 1 test por asset class (equity/REIT-vía-FFO/crypto), fast-path crypto que verifica que `get_info`/`get_financials` **nunca** se llaman, la identidad de ensamblado `raw_adjusted_score == total + consistency + piotroski_bonus + moat_bonus + tailwind_bonus` (findings de code-review: `tailwind_bonus` faltaba y **puede ser negativo**, así que `adjusted_score >= total_score` no es invariante — se testea aparte con `tailwind_bonus >= 0`), fallback sin estados financieros (`get_financials` → `{}` → `level == "poor"`), `info` vacío. **Desbloquea P-16 (O1).**

**Verificación:** `make check` → 3140 passed. Los tests corren sin `st`.

---

## Plan de ejecución — PRs pendientes (2026-09-03)

> R0 (PR #74) y R1 (PR R1) completos. S3 (#76), S8 (#77), S14/S15/O3 (#78), S19 (#79) mergeados.
> Quedan **23 ítems** agrupados en 17 PRs (P-0 = esta actualización de docs). Un PR por iteración,
> en orden. La aprobación de cada PR sigue el gate de su fila.

| PR | Ítems | Fase | Esf. | Ola | Gate de verificación | Merge |
|----|-------|------|------|-----|----------------------|-------|
| P-0 | *(docs: este plan)* | — | S | 1 | `make check` | autónomo |
| P-1 | P3, O8 | R2/R3 | S | 1 | `make check` | autónomo |
| P-2 | S23, S24, S28 | R1-bis | S | 1 | `make check` + `measure_score_impact.py --compare` → 0 scores / 0 señales | autónomo si 0 diff |
| P-3 | S26 | R2 | S | 1 | `make check` + `TZ=UTC make test` | autónomo |
| P-4 | P2, O6, O9 | R2/R3 | M | 1 | `make check` | autónomo + revisión visual badge/Settings |
| P-5 | S18 | R2 | M | 1 | `make check` + carga en frío de 3 páginas | autónomo |
| P-6 | S25 | R1-bis | M | 2 | `make check` + `--compare` → 0 señales técnicas | autónomo si 0 diff |
| P-7 | S27 | R1-bis | M | 2 | `make check` + `TZ=UTC make test` (`tests/test_stress_test.py` verde) | autónomo si 0 diff |
| P-8 | O5, O7 | R3 | M | 2 | `make check` | autónomo + revisión visual |
| P-9 | O4 | R3 | M | 2 | `make check` | autónomo + revisión visual comité |
| P-10 | O2 | R3 | M | 2 | `make check` + `measure_score_impact.py` AI on → 0 delta moat | **aprobación usuario** |
| P-11 | T2 | R4 | M | 2 | `make check` | autónomo · **precede a P-16** |
| P-12 | S22 | R2 | M | 3 | `make check` + revisión visual tabla screener | **aprobación usuario** |
| P-13 | S16 | R3 | M | 3 | `make check` + revisión visual home | **aprobación usuario** |
| P-14 | S17 | R3 | M | 3 | `make check` + revisión visual controles retiro | **aprobación usuario** |
| P-15 | T1 | R4 | M | 3 | `make check` (tras P-5) | autónomo |
| P-16 | O1 | R3 | L | 3 | `make check` + `TZ=UTC make test` + `--compare` → 0 scores | **aprobación usuario** · standalone · tras P-11 |
| P-17 | S12 | R3 | L | 3 | `make check` + `TZ=UTC make test` + revisión visual todas las tabs | **aprobación usuario** · standalone · último |

**Olas:** 1 = P-0…P-5 (paralelizables, riesgo mínimo). 2 = P-6…P-11 (tras ola 1; P-4/P-8/P-9/P-10 tocan `shared.py` → coordinar rebase). 3 = P-12…P-17 (serializadas; P-16 tras P-11; P-17 solo y al final).

**Contratos públicos a preservar** (por PR, según cada ítem): `Portfolio.compute_metrics()` (P-2), `MonteCarloResult` / `simulate_goal()` (P-2), `TechnicalResult` (P-6), `StressResult` (P-7), `run_holdings_committee()` (P-9), `MoatAnalyzer.analyze_with_ai()` (P-10), `FundamentalResult` / `FundamentalAnalyzer.analyze()` / `full_analysis()` (P-16), helpers `cached_*` de `shared.py` (P-4/P-8/P-9). Los ítems de config (S23–S28) no cambian la matemática: defaults = literales actuales. Re-exports se mantienen para no romper callers.

**Evidencia para aprobar los `[observable]`:** P-2 (S24/S28) y P-6 (S25) y P-7 (S27) → `--compare` con 0 scores y 0 señales; P-10 → corrida con AI on antes/después, 0 delta de `moat_score`; P-4 (P2/O6) → badge muestra el mismo número; P-12/P-13/P-14/P-16/P-17 → captura antes/después, mismos componentes y orden.

---

## Dependencias entre ítems

```
S4/S5  →  O1         satisfecha (R1 mergeado) — O1 desbloqueado a nivel config
O2     →  S3         satisfecha (S3 mergeado, PR #76) — O2 pasa a standalone (P-10)
P2/O6/O9 → (juntos)  VIGENTE — mismo patrón double-query + import de capa (P-4)
S18    →  T1         VIGENTE — session guard centralizado facilita testear shared.py (P-5 → P-15)
T2     →  O1         VIGENTE — tests de integración ANTES de refactorizar analyze() (P-11 → P-16)
S26    standalone    (S3 ya cerró; deja de ir "junto a S3") (P-3)
S12    standalone    el PR más grande; no combinar (P-17)
O1     standalone    segundo más grande; no combinar (P-16)
R0     completo — PR #74 (2026-09-02)
R1     completo — PR R1 (2026-09-02)
R2/R3  parcial — S3 #76, S8 #77, S14/S15/O3 #78, S19 #79 (2026-09-02)
```

---

## Ítems puramente internos vs. observables

### Solo internos (el usuario no nota nada)
S1, S2, S3, S7, S8, S13, S14, S18, S19, S20, S21, S22, S23, S26, P2, P3, O1, O2, O3, O4, O5, O6, O7, O8, O9, T1, T2, S12, S16, S17

### Pueden cambiar lo que se ve o se puede configurar
- **S4/S5**: los thresholds del moat pasan a ser editables en `config.py` sin tocar código
- **S6**: los CV de EPS pasan a ser editables
- **S8**: tickers sin `quickRatio` pueden mostrar diagnostic note nueva
- **S9/S10/S11**: parámetros de optimizer y stress test ahora configurables
- **P1**: moat AI puede parsear respuestas que antes truncaba → puede cambiar scores con AI on
- **S24**: los umbrales de drawdown severo/SORR pasan a ser configurables en `MonteCarloConfig`
- **S25**: los pesos de señal técnica pasan a ser configurables en `TechnicalConfig`
- **S27**: los shocks de los escenarios de stress test pasan a ser editables en `config.py`
- **S28**: `expected_annual_return` del GoalPlanner pasa a ser configurable

---

## Verificación general por fase

| Fase | Comando |
|------|---------|
| R0 | `make check` |
| R1 | `scripts/measure_score_impact.py --compare` + `make check` |
| R2 | `make check` + revisión visual de la feature afectada |
| R3 (O1, S12) | `TZ=UTC make test` + `scripts/measure_score_impact.py --compare` + revisión visual completa |
| R4 | `make check` (los nuevos tests deben estar en verde) |
