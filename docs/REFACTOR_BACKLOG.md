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
| S1 | simplicidad | S | medio | interno | `ARGENTINA_ADRS` declarada dos veces |
| S2 | simplicidad | S | alto | interno | Code-fence stripping: 3 copias, IndexError latente |
| S7 | simplicidad | S | bajo | interno | Re-import `THRESHOLDS` local en `analyze()` |
| S13 | simplicidad | S | bajo | interno | `_fmt_idx` duplicada en dos páginas |
| S20 | performance | S | bajo | interno | `measure_all` llamado 3 veces donde corresponden 2 |
| S21 | simplicidad | S | bajo | interno | Boilerplate sys.path duplicado en todos los scripts |
| S4 | simplicidad | M | alto | observable | 5 dims del moat cuantitativo: thresholds hardcodeados |
| S5 | simplicidad | S | alto | observable | Fallback de ROIC absoluto hardcodeado |
| S6 | simplicidad | S | alto | observable | CV de EPS y banda `roe_std*2` no están en config |
| S9 | simplicidad | S | medio | observable | `div / 15.0` en optimizer sin nombre ni config |
| S10 | simplicidad | M | alto | observable | 5 glide-path overrides hardcodeados en optimizer |
| S11 | simplicidad | S | medio | observable | Tasa de recovery en stress test: contradicción y sin config |
| P1 | performance | S | alto | observable | `max_tokens=800` hardcodeado en moat AI — trunca JSON |
| S3 | simplicidad | M | medio | interno | `_call_nous` / `_call_xai` ~35 líneas duplicadas |
| S8 | simplicidad | S | medio | interno | `quickRatio` ignora patrón `reported_metric()` |
| S14 | simplicidad | S | medio | interno | Dict comprehension scored-ticker duplicado en 5_Optimizer |
| S15 | simplicidad | S | bajo | observable | Defaults de sesión hardcodeados; imports mid-file |
| S18 | simplicidad | M | medio | interno | Guard de sesión duplicado en ≥3 páginas |
| S19 | simplicidad | S | medio | interno | `_price_lookup` en scheduler duplica lógica de shared.py |
| S22 | simplicidad | M | medio | interno | `_analyse_one` mezcla extracción de datos con UI strings |
| P2 | performance | S | bajo | interno | Unread-alert count consultado 2 veces por rerun |
| O3 | ordenamiento | S | medio | interno | `cached_stress_test` acepta `dict` crudo como param de caché |
| O6 | ordenamiento | S | bajo | interno | Sidebar importa `alert_store` directamente |
| O7 | ordenamiento | S | bajo | interno | Stock Analysis importa `data.data_sources` directamente |
| O8 | ordenamiento | S | bajo | interno | Migraciones one-shot mezcladas con scripts operacionales |
| O2 | ordenamiento | M | alto | interno | Dispatch de provider AI duplicado en moat.py y ai_analyzer.py |
| O4 | ordenamiento | M | medio | interno | `run_holdings_committee` (negocio) en módulo de UI |
| O5 | ordenamiento | M | bajo | interno | Página de alertas importa `AlertEngine` directamente |
| S16 | simplicidad | M | medio | interno | `_home_page()` 208 líneas monolíticas |
| S17 | simplicidad | M | medio | interno | `render_*_controls` mutan session_state dentro del render |
| O1 | ordenamiento | L | alto | interno | `FundamentalAnalyzer.analyze()` 215 líneas: God method |
| S12 | simplicidad | L | alto | interno | `7_Simulaciones.py` 2.420 líneas sin helpers |
| T1 | cobertura | M | alto | interno | Cero tests para `dashboard/shared.py` (1.891 líneas) |

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

**Verificación:** `make check`.

---

### S13 — `_fmt_idx` duplicada en dos páginas `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/pages/7_Simulaciones.py:76` — `def _fmt_idx(v): ...`
- `dashboard/pages/5_Optimizer.py:37` — cuerpo idéntico: `proxy_attractiveness_index(v)` → `"—"` o `f"{v:.0f}"`

**Cambio propuesto:** mover `_fmt_idx` a `data/product_ux.py` o `dashboard/shared.py` (junto a `proxy_attractiveness_index` que ya está ahí). Reemplazar las dos definiciones por un import.

**Contrato estable:** función privada; ningún contrato externo.

**Verificación:** `make check`.

---

### S20 — `measure_all` llamado 3 veces con `--matrix` + `--baseline` `[interno]`

**Eje:** performance · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `scripts/measure_score_impact.py:379–393`

Con `--matrix`, el script corre `off = measure_all(symbols)` (AI off) y `on = measure_all(symbols, ai_config=...)` (AI on). Si además se pasa `--baseline` o `--compare`, una línea más abajo corre `current = measure_all(symbols)` sin config de AI — idéntico a `off`. Sobre un universo de 164 tickers, cada corrida tarda varios minutos.

**Cambio propuesto:** `current = off if args.matrix else measure_all(symbols)`

**Contrato estable:** salida idéntica; ninguna interfaz externa cambia.

**Verificación:** `make check`. Correr `scripts/measure_score_impact.py --matrix --compare` y verificar que produce el mismo resultado en menos tiempo.

---

### S21 — Boilerplate sys.path duplicado en todos los scripts `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `scripts/run_eval.py:17–22`, `score_track_record.py:17–22`, `run_scheduler.py:29–34`, `measure_score_impact.py:62`, `test_telegram.py`, `check_doc_catalog.py` — cada uno replica el mismo bloque de 4–5 líneas de `sys.path.insert` + `ensure_project_root`.

**Cambio propuesto:** crear `scripts/_bootstrap.py` con la lógica compartida. Cada script lo importa con una sola línea. Los scripts one-shot de migraciones (O8) también se benefician.

**Contrato estable:** sin cambio de comportamiento.

**Riesgos:** importar `_bootstrap` antes de que el path esté configurado es trivial si el módulo es autocontenido. El nombre con `_` señala que es interno.

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

**Verificación:** `scripts/measure_score_impact.py --compare` debe reportar 0 scores movidos, 0 acciones. `make check`.

---

### S5 — Fallback de ROIC absoluto hardcodeado `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** alto

**Evidencia:**
- `analysis/moat.py:651–657` — bandas `>= 20`, `>= 12`, `>= 8` para el fallback cuando no se puede calcular el spread

**Cambio propuesto:** agregar `roic_absolute_excellent`, `roic_absolute_good`, `roic_absolute_min` a `MoatConfig`. Reemplazar literales.

**Contrato estable:** mismo que S4.

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

**Verificación:** `scripts/measure_score_impact.py --compare` → 0 diferencias. `make check`.

---

### S9 — `div / 15.0` en optimizer sin nombre ni config `[observable]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `portfolio/optimizer.py:532` — `div = self._clean_div_yield(...) / 15.0`

El denominador `15.0` es la escala de normalización del yield en `_rank_score`. No coincide con ningún valor existente: `max_plausible_dividend_yield_pct = 30.0`, `div_yield_sweet_spot_high = 4.0`. Afecta directamente qué tickers entran con ventaja en SLSQP.

**Cambio propuesto:** agregar `div_yield_normalization_pct: float = 15.0` a `OptimizerConfig`. El valor default reproduce el comportamiento actual exactamente.

**Contrato estable:** `PortfolioOptimizer.optimize()` — misma firma. Pesos: idénticos con el mismo default.

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

**Verificación:** `make check`. Correr `measure_score_impact.py` con AI encendida sobre un ticker conocido y verificar que el JSON se parsea completo.

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

**Verificación:** `make check`.

---

### S18 — Guard de sesión duplicado en ≥3 páginas `[interno]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `dashboard/pages/2_Stock_Analysis.py:70–77`
- `dashboard/pages/5_Optimizer.py:127–135`
- Parcialmente en `7_Simulaciones.py`

Los tres bloques re-implementan la inicialización de `user_prefs`, `universe` y `portfolio` en session state. Si cambia la inicialización, debe cambiarse en tres lugares.

**Cambio propuesto:** `dashboard/shared.py` ya tiene `get_user_prefs()`. Agregar `ensure_session_defaults()` que centralice el guard completo para las tres variables. Las páginas llaman a ese helper.

**Contrato estable:** mismo estado de sesión resultante.

**Riesgos:** el orden de inicialización importa en Streamlit. Probar que las páginas cargan correctamente en frío.

**Verificación:** `make check`. Abrir las tres páginas en un navegador limpio y verificar que no crashean.

---

### S19 — `_price_lookup` en scheduler duplica lógica de shared.py `[interno]`

**Eje:** simplicidad · **Esfuerzo:** S · **Impacto:** medio

**Evidencia:**
- `scripts/run_scheduler.py:288–294` — closure `_price_lookup` para `compute_plan_vs_reality`
- `dashboard/shared.py` — `plan_price_lookup` con lógica equivalente

El scheduler no puede importar `dashboard/shared.py` (arrastraría Streamlit). La solución es extraer la función pura a una capa sin Streamlit.

**Cambio propuesto:** mover `plan_price_lookup` (o su núcleo funcional) a `data/fetcher.py` o `data/plan_context.py`. Tanto el scheduler como shared.py la importan desde ahí. Mantener el nombre en shared.py como re-export si hay callers existentes.

**Contrato estable:** `compute_plan_vs_reality(price_lookup=...)` — misma firma inyectable.

**Verificación:** `make check`. Correr `scripts/run_scheduler.py --dry-run` si existe esa flag.

---

### S22 — `_analyse_one` mezcla extracción de datos con UI strings `[interno]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `dashboard/shared.py:1758–1819` — closure `_analyse_one` dentro del thread pool de `_analyse_universe_parallel`

La closure construye un dict con 20+ keys que incluyen strings de UI (emoji-prefixed sector label, `fund.company_name[:25]` truncation, badge formatting). Esta lógica de presentación vive dentro de un worker concurrente y se duplica parcialmente con el row builder del scheduler.

**Cambio propuesto:** separar en dos funciones puras: `_extract_row_data(sym, fund, tech, dec) -> dict` (datos crudos, sin strings de UI) y `_format_row_for_display(row: dict) -> dict` (strings, badges, truncado). El worker llama a la primera; la segunda se aplica en el thread principal o en el display layer.

**Contrato estable:** la tabla del screener muestra los mismos datos.

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

**Verificación:** `make check`.

---

## Fase R3 — Ordenamiento entre capas (Esfuerzo M–L)

Responsabilidades mal asignadas entre módulos. Mayor riesgo; requiere regresión end-to-end.

---

### O2 — Dispatch de provider AI duplicado en dos módulos `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** M · **Impacto:** alto

**Evidencia:**
- `analysis/moat.py:781–854` — `call_ai_api(prompt, provider, model, api_key, max_tokens)` — maneja `claude`, `openai`, `xai`, `nous`
- `analysis/ai_analyzer.py:375–478` — `AIAnalyzer._call_api()` delega a `_call_claude`, `_call_openai`, `_call_nous`, `_call_xai`

Son dos implementaciones paralelas del mismo dispatch de provider. `moat.py` hardcodea `max_tokens=800`; `ai_analyzer.py` default a 1024. Agregar un proveedor requiere editar los dos archivos.

**Cambio propuesto:** consolidar en `AIAnalyzer._call_api()` como punto único. `MoatAnalyzer` recibe una instancia de `AIAnalyzer` (ya lo hace parcialmente) y delega todos los calls de red ahí. `call_ai_api()` en `moat.py` puede quedar como shim deprecado durante una transición.

**Contrato estable:** `MoatAnalyzer.analyze_with_ai()` — misma firma y resultado. `AIAnalyzer` — sin cambio.

**Riesgos:** requiere que `MoatAnalyzer` pueda construirse con un `AIAnalyzer` inyectado. Revisar que los tests de moat existentes no rompan.

**Dependencias:** S3 (dedup `_call_nous`/`_call_xai`) se beneficia de hacerse junto.

**Verificación:** `make check`. `scripts/measure_score_impact.py` con AI on — los scores de moat no deben cambiar.

---

### O4 — `run_holdings_committee` (orquestación de negocio) en módulo de UI `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `dashboard/shared.py:1513–1584` — 72 líneas que corren stress test, calculan trades de alineación, obtienen contexto macro, construyen la clave MD5 del plan y convocan el comité

Esta función no hace ninguna llamada `st.*`. Es lógica de orquestación pura que accidentalmente vive en el shared del dashboard.

**Cambio propuesto:** mover el núcleo a `analysis/committee.py` como función libre (donde ya vive `analyze_portfolio`). El wrapper en `shared.py` puede quedar como re-export para no romper callers existentes.

**Contrato estable:** `run_holdings_committee(...)` — misma firma desde el punto de vista de las páginas.

**Verificación:** `make check`. Probar la sección de comité en `3_Portfolio.py`.

---

### O5 — Página de alertas importa `AlertEngine` y `ReportGenerator` directamente `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** M · **Impacto:** bajo

**Evidencia:**
- `dashboard/pages/8_Alertas.py:11–13` — imports directos de `alerts.engine` y `alerts.reporter`

Si cambia la firma del constructor de `AlertEngine` o `ReportGenerator`, la página rompe. El patrón establecido para el comité es tener un wrapper en `shared.py`.

**Cambio propuesto:** agregar `run_alert_engine(...)` y `generate_alert_report(...)` en `dashboard/shared.py`. La página solo importa de shared.

**Contrato estable:** la página de alertas muestra los mismos resultados.

**Verificación:** `make check`. Probar la página manualmente.

---

### O6 — Sidebar importa `alert_store` directamente `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/app.py:471` — `from alerts.store import alert_store`

`build_home_hub_for_prefs` en `shared.py` ya consulta el unread count. El sidebar puede recibir el valor como parámetro desde `_home_page` en vez de importar el store directamente.

**Cambio propuesto:** ver P2 — resolver ambos juntos. El sidebar lee el count de una variable calculada una sola vez.

**Verificación:** `make check`.

---

### O7 — Stock Analysis importa `data.data_sources` directamente `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `dashboard/pages/2_Stock_Analysis.py:61` — `from data.data_sources import default_fundamental_sources`

La función `_cross_source_check` (líneas 53–64) podría vivir en `dashboard/shared.py` con su propio `@st.cache_data`, manteniendo la página libre de imports de la capa de datos.

**Cambio propuesto:** mover `_cross_source_check` y su import a `shared.py`. La página importa solo el helper cacheado.

**Verificación:** `make check`.

---

### O8 — Migraciones one-shot mezcladas con scripts operacionales `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** S · **Impacto:** bajo

**Evidencia:**
- `scripts/mark_test_fixture_rows.py:1` — migración one-shot de fixture rows (ejecutada 2026-08-30)
- `scripts/purge_test_alert_rows.py:1` — migración one-shot de alert rows

Viven junto a `run_scheduler.py`, `run_eval.py` y herramientas operacionales. Un nuevo contribuidor no puede distinguir "herramienta que se corre seguido" de "script que ya cumplió su propósito".

**Cambio propuesto:** mover los dos archivos a `scripts/migrations/`. Agregar un `scripts/migrations/README.md` que explique cuándo se corrieron y que son idempotentes.

**Contrato estable:** los scripts siguen funcionando; solo cambia su ubicación.

**Verificación:** `make check` (el script `check_doc_catalog.py` no debería enumerar scripts).

---

### O1 — `FundamentalAnalyzer.analyze()`: God method de 215 líneas `[interno]`

**Eje:** ordenamiento · **Esfuerzo:** L · **Impacto:** alto

**Evidencia:**
- `analysis/fundamental.py:733–948` — método único que hace: fetch de datos yfinance, clasificación de activo, 5 dimensiones de scoring, Graham, EnhancedScoring (Consistency + Piotroski), MoatAnalyzer, TailwindAnalyzer, adjusted_score, data quality, cross-source quality, logging.

Ninguna de estas responsabilidades se puede cambiar sin leer el método completo. Las funciones de dimensión ya están extraídas (`_score_profitability`, etc.) pero `analyze()` es el cuello de botella donde todas se acoplan.

**Cambio propuesto:** extraer sub-métodos privados:
- `_run_scoring_pipeline(info, fund_data) -> ScoringResults`
- `_run_moat_pipeline(info, fund_data, scoring) -> MoatDetail`
- `_run_tailwind_pipeline(ticker, fund_data) -> TailwindDetail`
- `_assemble_result(...)` — solo construye el dataclass

`analyze()` se convierte en un orquestador de 30–40 líneas que llama a estos métodos en orden.

**Contrato estable:** `FundamentalResult` — misma estructura. `FundamentalAnalyzer.analyze()` — misma firma y semántica. `full_analysis()` en strategy.py — sin cambio.

**Riesgos:** alto. Es el método más central del motor. Requiere tests de regresión exhaustivos con `measure_score_impact.py --compare` (0 scores deben moverse). Hacer en un PR dedicado.

**Dependencias:** S4/S5 (moat thresholds a config) deben estar mergeados primero.

**Verificación:** `scripts/measure_score_impact.py --compare` → 0 scores movidos. `make check`. `TZ=UTC make test`.

---

### S16 — `_home_page()` 208 líneas `[interno]`

**Eje:** simplicidad · **Esfuerzo:** M · **Impacto:** medio

**Evidencia:**
- `dashboard/app.py:133–341` — función única que renderiza métricas, plan hub, action card, onboarding wizard, guided journey, sample-plan loading (con try/except y `st.switch_page`), y disclaimer

**Cambio propuesto:** extraer `_render_plan_hub()`, `_render_guided_journey()`, `_render_sample_plan_section()`. Cada una con sus imports y su estado local.

**Contrato estable:** la página de inicio muestra los mismos componentes en el mismo orden.

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

---

## Dependencias entre ítems

```
S4/S5  →  O1         (mover thresholds a config antes de refactorizar analyze())
O2     →  S3         (unificar dispatch AI antes de dedup _call_nous/_call_xai)
P2/O6  → (juntos)    (resolver double-query y sidebar import en el mismo PR)
S18    →  T1         (extraer session guard facilita testear shared.py)
S12    standalone    (el PR más grande; no combinar con ningún otro)
O1     standalone    (segundo PR más grande; no combinar)
R0     sin dependencias (empezar por aquí)
```

---

## Ítems puramente internos vs. observables

### Solo internos (el usuario no nota nada)
S1, S2, S3, S7, S8, S13, S14, S18, S19, S20, S21, S22, P2, O1, O2, O3, O4, O5, O6, O7, O8, T1, S12, S16, S17

### Pueden cambiar lo que se ve o se puede configurar
- **S4/S5**: los thresholds del moat pasan a ser editables en `config.py` sin tocar código
- **S6**: los CV de EPS pasan a ser editables
- **S8**: tickers sin `quickRatio` pueden mostrar diagnostic note nueva
- **S9/S10/S11**: parámetros de optimizer y stress test ahora configurables
- **P1**: moat AI puede parsear respuestas que antes truncaba → puede cambiar scores con AI on

---

## Verificación general por fase

| Fase | Comando |
|------|---------|
| R0 | `make check` |
| R1 | `scripts/measure_score_impact.py --compare` + `make check` |
| R2 | `make check` + revisión visual de la feature afectada |
| R3 (O1, S12) | `TZ=UTC make test` + `scripts/measure_score_impact.py --compare` + revisión visual completa |
| R4 | `make check` (los nuevos tests deben estar en verde) |
