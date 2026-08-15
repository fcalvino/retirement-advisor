# Plan de Implementación — El Gran Salto

> **Estado: HISTÓRICO (2026-06).** Las 5 fases de este plan ya están implementadas
> (track record, comité + eval, RAG macro + multi-source, chat, Black-Litterman).
> **No es el próximo sprint.** Estado actual: [`CONTEXT.md` §6](CONTEXT.md).
> Diario de fases: [`ROADMAP.md`](ROADMAP.md). Visión original: [`VISION_GRAN_SALTO.md`](VISION_GRAN_SALTO.md).
>
> Plan operativo derivado de `VISION_GRAN_SALTO.md`. Se conserva como registro de
> cómo se ejecutó el salto, no como backlog. Fecha original: 2026-06.

---

## Principio rector

Todo reutiliza la infraestructura existente. El motor ya está separado de la UI
(`analysis/`, `portfolio/`, `data/` son librerías puras; `dashboard/pages/` solo presenta).
Cada fase agrega un módulo nuevo + una página + tests, sin reescribir el motor.

Orden (de la matriz de priorización del documento, principio de menor esfuerzo / mayor
confianza primero):

```
Fase 1  Track record / calibración              ✅ implementada
Fase 2  Comité multi-agente + eval harness      ✅ implementada
Fase 3  RAG macro + multi-source data           ✅ implementada
Fase 4  Interfaz conversacional                 ✅ implementada
Fase 5  Black-Litterman + módulos de planificación ✅ implementada
```

Riesgo transversal que es un *gate*, no un detalle: **compliance**. Cuanto más el producto
"actúe", más cerca del asesoramiento regulado. Se trata como criterio de salida antes de
cualquier salto B2B2C/SaaS (ver sección final).

---

# FASE 1 — Track record y calibración (detallada)

**Objetivo.** Persistir cada recomendación que emite el motor y medir su acierto histórico,
de forma auditable. Convertir "creeme" en "acá está mi historial".

**Por qué primero.** Esfuerzo bajo-medio, sin dependencias duras, reutiliza la
infraestructura de persistencia que ya existe, y es lo único de alto impacto que el producto
**no tiene hoy**. Además es el insumo honesto para mejorar el modelo: sin medir aciertos no
sabés si una mejora mejora algo.

**Infra que reutiliza (verificada en el repo):**
- Patrón de persistencia SQLAlchemy + SQLite de `alerts/store.py` (tablas `alert_snapshots`,
  `alert_history`, etc., todas en `DB_PATH` = `data/db/retirement_advisor.db`, definido en
  `config.py:15`).
- `analysis/strategy.py:full_analysis(symbol, ai_config)` que devuelve
  `(FundamentalResult, TechnicalResult, Decision)`. El `Decision` (definido en
  `analysis/strategy.py`) ya trae `symbol`, `action`, `confidence`, `fundamental_score`,
  `technical_signal`, `has_margin_of_safety`.
- El patrón `_price_at_save` de `data/plan_store.py` (≈línea 161) para capturar el precio en
  el momento de la recomendación.
- `data/fetcher.py` para traer precios históricos al momento de scoring.

## 1.1 — Esquema de persistencia

Nuevo módulo `analysis/track_record.py` (espejo estructural de `alerts/store.py`: mismo
`DeclarativeBase`, mismo `create_engine(f"sqlite:///{DB_PATH}")`, mismo `sessionmaker`).

Dos tablas nuevas en la DB existente:

**`recommendation_log`** — una fila por recomendación emitida:

| Columna | Tipo | Nota |
|---------|------|------|
| `id` | Integer PK autoincrement | |
| `symbol` | String, not null | |
| `action` | String | STRONG BUY / BUY / HOLD / REDUCE / SELL |
| `confidence` | String | HIGH / MEDIUM / LOW |
| `fundamental_score` | Float | de `Decision.fundamental_score` |
| `technical_signal` | String | |
| `source` | String | `"rule_based"` \| `"ai"` \| `"committee"` (forward-compat Fase 2) |
| `price_at_rec` | Float | capturado al emitir, vía patrón `_price_at_save` |
| `rationale` | Text | JSON serializado de `Decision.rationale` |
| `created_at` | DateTime UTC | índice |
| `plan_id` | String, nullable | liga a `PlanSnapshot` si aplica |

**`recommendation_outcome`** — scoring diferido (se llena después, no al emitir):

| Columna | Tipo | Nota |
|---------|------|------|
| `id` | Integer PK | |
| `rec_id` | Integer FK → recommendation_log.id | |
| `horizon_days` | Integer | 30 / 90 / 252 (12m hábiles) |
| `price_at_horizon` | Float | |
| `return_pct` | Float | retorno del ticker en el horizonte |
| `benchmark_return_pct` | Float | mismo horizonte, SPY (configurable) |
| `excess_return_pct` | Float | `return_pct - benchmark_return_pct` |
| `hit` | Boolean | acierto direccional según `action` (ver 1.3) |
| `scored_at` | DateTime UTC | |

Restricción única `(rec_id, horizon_days)` para idempotencia del re-scoring.

## 1.2 — Captura (registro disciplinado)

Función `log_recommendation(decision, *, source, plan_id=None) -> int` en
`track_record.py`. Captura `price_at_rec` en el momento (reutiliza fetcher).

**Punto de enganche:** envolver el resultado de `full_analysis` en los flujos que producen
recomendaciones para el usuario, sin tocar la firma del motor:
- `dashboard/pages/2_Stock_Analysis.py` (análisis individual).
- `dashboard/pages/1_Screener.py` (cuando promueve un ticker a BUY/STRONG BUY).
- El motor de alertas `alerts/engine.py` cuando dispara `OPPORTUNITY` / `SIGNAL_CHANGE`
  (esos eventos *son* recomendaciones implícitas y ya pasan por código).

Regla anti-ruido: deduplicar por `(symbol, action, día)` para no loguear N veces el mismo
refresco — espejo de la lógica de cooldown de `alerts/store.py`.

## 1.3 — Módulo de scoring de aciertos

`analysis/track_record_scorer.py`. Job idempotente que recorre `recommendation_log`, y para
cada recomendación cuyo horizonte ya venció y no tiene `outcome`:

1. Trae `price_at_horizon` (fetcher) y el benchmark al mismo horizonte.
2. Calcula `return_pct`, `benchmark_return_pct`, `excess_return_pct`.
3. Define `hit` direccionalmente: BUY/STRONG BUY ⇒ hit si `excess_return_pct > 0`;
   SELL/REDUCE ⇒ hit si `excess_return_pct < 0`; HOLD ⇒ hit si `|return_pct|` dentro de banda
   (configurable, p.ej. ±5%). Las reglas exactas viven en `config.py` (sección nueva
   `TRACK_RECORD`), no hardcodeadas.
4. Escribe `recommendation_outcome`.

**Métricas agregadas** (funciones puras, fáciles de testear):
- Retorno medio de señales STRONG BUY vs SPY por horizonte.
- **Calibración:** para cada nivel de `confidence`, % de aciertos reales (¿cuando decimos HIGH
  acertamos más que cuando decimos LOW?). Es el corazón de la promesa de confianza.
- Curva de equity de las señales del modelo vs. benchmark.
- Tasa de acierto por `action` y por `source` (clave para Fase 2: ¿el comité supera al
  single-shot?).

Ejecución: invocable desde `scripts/` (cron diario) y bajo demanda desde la página.

## 1.4 — Página de visualización

`dashboard/pages/13_Track_Record.py` (sigue el patrón de `8_Alertas.py`). Muestra:
calibración por confidence, equity curve modelo vs SPY, tabla de recomendaciones con su
outcome, filtros por horizonte/acción/source. **Framing honesto** (requisito del documento):
horizontes largos, sin cherry-picking de ventanas favorables, mostrar también los errores.

## 1.5 — Tests (criterio de hecho)

Nuevo `tests/test_track_record.py`:
- Round-trip de persistencia (log → read) en DB temporal.
- Idempotencia del scorer (correrlo dos veces no duplica outcomes).
- Cálculo de `hit`/`excess_return` con precios fixture conocidos (sin red).
- Métrica de calibración con dataset sintético de outcomes conocidos.
- Dedupe de `(symbol, action, día)`.

**Definición de hecho de la Fase 1:**
- [x] Toda recomendación de las páginas de análisis y del motor de alertas queda logueada.
- [x] El scorer corre idempotente y llena outcomes a 30/90/252 días.
- [x] La página muestra calibración + equity curve + tabla, con framing honesto.
- [x] `pytest tests/test_track_record.py` en verde (11/11) y `test_alert_engine` sin regresiones (23/23).

**Esfuerzo estimado (en su día):** 1–2 semanas. **Sin dependencias.** (Arranque original; ya cerrado.)

**Estado: IMPLEMENTADO (2026-06).** Archivos entregados:
`analysis/track_record.py` (esquema + captura), `analysis/track_record_scorer.py`
(scoring + métricas puras), `config.py` (sección `TrackRecordConfig` / `TRACK_RECORD`),
enganches en `dashboard/pages/2_Stock_Analysis.py` y `alerts/engine.py`, página
`dashboard/pages/13_Track_Record.py`, script de cron `scripts/score_track_record.py`,
y `tests/test_track_record.py`. Nota: SQLite corre sobre `DB_PATH` igual que `alerts/store.py`;
el scoring de outcomes se ejecuta con `./venv/bin/python3 scripts/score_track_record.py`
(ideal en cron diario).

---

# FASE 2 — Comité multi-agente + eval harness (épica)

**Objetivo.** Reemplazar la llamada IA única por la simulación de un comité que debate y
produce un dictamen con disenso explícito. Mejor ratio impacto/esfuerzo del documento.

**Prerrequisito propio: eval harness.** Sin medir calidad de output, cambiar un prompt es a
ciegas y el comité no se puede mejorar de forma disciplinada. Por eso van juntos.

**Sub-épica 2A — Eval harness (hacer primero dentro de la fase):**
- Set de "casos dorados" (ticker + contexto → propiedades esperadas de la respuesta).
- Scorer de respuestas (estructura + chequeos de coherencia: ¿no inventó cifras?, ¿el bear
  case contradice de verdad?, ¿la allocation respeta los límites conservadores?).
- Reutiliza el patrón de `tests/test_prompts.py` (hoy solo valida estructura) extendiéndolo a
  calidad. Integrar con el `source="ai"` del track record (Fase 1) para medir aciertos reales.

**Estado 2A: IMPLEMENTADO (2026-06).** Archivos entregados:
`analysis/eval_cases.py` (6 casos dorados con respuestas grabadas para replay determinista:
compounder de calidad, alto apalancamiento, sobrecompra, cripto con tope conservador, ADR
argentino con macro, y hold a precio justo); `analysis/eval_harness.py` (9 checks de calidad
—estructura válida, acción esperada/prohibida, **scores deterministas** (la IA nunca pisa las
cifras del motor), riesgos presentes en todo BUY como antídoto a la complacencia, schema y
grounding de `macro_factors`, y tope de asignación conservador— más providers `ReplayProvider`
(sin API/costo) y `LiveProvider` (IA real) y un runner con reporte agregado); `config.py`
(sección `EvalConfig` / `EVAL`); CLI `scripts/run_eval.py` (`--live` para IA real); página
`dashboard/pages/14_Eval_IA.py`; y `tests/test_eval_harness.py` (14/14, cada check con su caso
de fallo). Suite replay en verde 6/6. Queda pendiente la integración fina con `source="ai"`
del track record (requiere persistir las respuestas crudas de la IA), que se hará junto a 2B.

**Sub-épica 2B — Comité.** Orquestación de prompts existentes en `analysis/prompts.py` +
`analysis/ai_analyzer.py`, **no infraestructura nueva**:

| Agente | Reutiliza |
|--------|-----------|
| Analista Fundamental | `equity_decision_prompt` |
| Estratega Macro | bloques `_*_macro_factors` |
| Risk Manager / Abogado del Diablo | prompt nuevo (red-team) |
| Portfolio Manager | `portfolio_optimizer_advice_prompt` |
| Behavioral Coach | `long_term_plan_narrative_prompt` |

Más: un **agregador de consenso** (1 módulo nuevo, p.ej. `analysis/committee.py`). El
multi-proveedor ya soportado (Claude/GPT-4o/Grok/Nous en `ai_analyzer.py`) permite correr
distintos agentes en distintos modelos.

**Riesgos / mitigaciones:** costo de tokens ⇒ cachear el dictamen como ya se cachea el moat
AI, y reservar el comité completo para decisiones de peso (no para refrescar 38 tickers);
latencia ⇒ correr agentes en paralelo. El `source="committee"` del track record permite
comparar comité vs single-shot con datos.

**Done (alto nivel):** comité produce dictamen con disenso auditable; eval harness lo puntúa;
track record distingue `source`; caché y paralelismo operativos.

**Estado 2B: IMPLEMENTADO (2026-06).** Archivos entregados:
`analysis/committee_prompts.py` (bloque de contexto con números duros + prompts por rol con
schema JSON uniforme; el Abogado del Diablo está estructuralmente obligado a armar el bear
case); `analysis/committee.py` (orquestador `CommitteeAnalyzer` con `call_fn` inyectable —en
producción envuelve el `_call_api` multi-proveedor—, **paralelismo por hilos** (no asyncio,
respeta las guías), **agregador determinista y auditable** (las posturas mapean a un lean
ponderado → acción; el disenso del abogado del diablo **siempre** se muestra; la confianza
baja un escalón ante disenso fuerte = sesgo conservador), caché del veredicto en el SQLite
compartido, y `to_decision()` para encajar en el flujo existente); `config.py` (sección
`CommitteeConfig` / `COMMITTEE` con pesos de voto y umbrales); `CommitteeProvider` en
`analysis/eval_harness.py` (el harness puede puntuar al comité con los mismos casos dorados);
página `dashboard/pages/15_Comite.py` (dictamen + consenso + disenso + opinión por agente, y
loguea a track record con `source="committee"`); y `tests/test_committee.py` (10/10, con LLM
falso inyectado, sin red). Las cifras siguen siendo deterministas (la IA nunca pisa el score
del motor). Regresión total verde: 76 tests entre comité, eval, track record y prompts.

**Dependencias:** Fase 1 (para medir), se beneficia de Fase 3 (macro fresco).

---

# FASE 3 — RAG macro + multi-source data (épica)

**Objetivo.** Atacar la debilidad estructural #1: todo entra por `yfinance` (garbage in,
garbage out) y los prompts piden al LLM que "use su conocimiento macro actual" —training data
potencialmente desactualizada, `macro_factors` en el peor caso inventados.

**Sub-épica 3A — Multi-fuente con reconciliación:** SEC EDGAR (fundamentals reales de
filings), FRED (macro), FMP/Alpha Vantage como cross-check, con un *agente de calidad de
datos* que detecta discrepancias entre fuentes. Extiende el badge ya existente
(`compute_data_quality`). Se inserta detrás de `data/fetcher.py` como capa de fuentes.

**Estado 3A: IMPLEMENTADO (2026-06).** Archivos entregados:
`data/data_sources.py` (abstracción `DataSource` + `SourceValue` sobre campos crudos
cross-comparables —ingresos, utilidad neta, acciones, equity, activos, precio, market cap—;
`YFinanceSource` real, `SecEdgarSource` real best-effort contra el API público de companyfacts
—acciones de EE.UU., sin clave, con User-Agent— y `FredSource` para series macro con clave;
todas degradan a `{}` ante fallo de red, nunca rompen el pipeline); `analysis/data_reconciliation.py`
(el cerebro: `reconcile()` arma por campo los valores de cada fuente, elige por prioridad,
mide el acuerdo (diff relativa) y marca conflicto sobre el umbral; `data_quality_agent()`
funde esto con `compute_data_quality` y **baja el badge un nivel ante discrepancia material**);
`config.py` (sección `MultiSourceConfig` / `MULTI_SOURCE` con prioridad de fuentes y umbral);
página `dashboard/pages/16_Calidad_Datos.py` (reconcilia un ticker y muestra acuerdo,
discrepancias por campo y el badge cruzado); y `tests/test_data_reconciliation.py` (9/9,
fuentes falsas inyectadas, sin red). El cerebro (reconciliación + detección de discrepancias +
agente de calidad) está 100% testeado offline; los adaptadores externos (SEC/FRED) quedan
enchufados y dependen de red/clave del usuario.

**Cierre de 3A (2026-06):** sumado `FmpSource` (tercer cross-check, opt-in por clave
`FMP_API_KEY`) y `attach_cross_source_quality()` que **funde la reconciliación dentro del
flujo de análisis** (la página `2_Stock_Analysis.py` ahora muestra, cacheada, una verificación
entre fuentes con su badge de calidad cruzado). Se surfacean las discrepancias en vez de
corregir números en silencio. Tests 3A: 11/11.

**Sub-épica 3B — RAG macro en tiempo real:** indexar releases de la Fed, datos económicos y
noticias, e inyectarlos como **contexto fresco y fechado** en los prompts, en vez de confiar
en la memoria del modelo. Requiere un vector store (ver Fase de infra). Convierte
`macro_factors` de acto de fe en hechos verificables.

**Estado 3B: IMPLEMENTADO (2026-06).** Archivos entregados:
`analysis/macro_rag.py` (store `MacroRagStore` de documentos macro **fechados** en el SQLite
compartido, con **recuperación TF-IDF pura en Python** —sin sklearn, sin vector DB externa, sin
servicio de embeddings, respetando "proyecto sincrónico y autocontenido"—, una **compuerta de
frescura** que descarta hechos viejos, y `build_context()` que arma el bloque de contexto
fechado; más `example_macro_docs()` (set offline para demo/test sin red), `ingest_from_fred()`
(best-effort con clave) y `macro_context_for(fund)`); `config.py` (sección `MacroRagConfig` /
`MACRO_RAG`); **inyección** del bloque en el prompt del Estratega Macro del comité
(`committee_prompts.py` + `committee.py`), instruyéndolo a usar SOLO esos hechos fechados y no
su memoria; página `dashboard/pages/17_Macro_RAG.py` (cargar set de ejemplo / ingerir de FRED /
probar recuperación / ver el bloque inyectado); y `tests/test_macro_rag.py` (10/10: ranking de
relevancia, upsert idempotente, compuerta de frescura, bloque fechado e inyección al prompt).
Regresión total verde: **97 tests** entre todas las fases del Gran Salto.

**Done (alto nivel):** prompts macro consumen contexto fechado de fuentes externas;
discrepancias entre fuentes se detectan y se muestran en el badge de calidad.

**Dependencias:** habilita que Fases 1–2 sean creíbles. Es prerequisito de escalar la IA.

---

# FASE 4 — Interfaz conversacional "Hablá con tu plan" (épica)

**Objetivo.** Un chat donde el usuario pregunta en lenguaje natural y un agente orquestador
elige y ejecuta las funciones correctas, devuelve respuesta + gráfico + acción propuesta.
Colapsa a cero la barrera de navegación de las ~12 páginas Streamlit.

**Qué reutiliza (casi todo).** Las funciones del motor son directamente "tools" para
function-calling (verificadas en el repo):
- `analysis/strategy.py:full_analysis`
- `portfolio/optimizer.py:optimize`
- `portfolio/monte_carlo.py:MonteCarloSimulator.run`
- `portfolio/stress_test.py:StressTester.run`
- `portfolio/sensitivity.py:run_sensitivity`
- `data/plan_context.py:compute_plan_vs_reality` / `compute_alignment_trades`

**Por qué después del comité.** El orquestador *es* un agente; conviene tener el patrón
multi-agente (Fase 2) y el eval harness maduros antes de exponer el chat al usuario.

**Riesgos / mitigaciones:** que ejecute la tool equivocada o alucine números ⇒ tool-calling
estricto (la IA nunca inventa cifras, solo invoca funciones deterministas) + mostrar siempre
el dato crudo junto a la narrativa (como ya hace el producto). Streamlit pasa de *ser el
producto* a panel de respaldo / power-user.

**Done (alto nivel):** chat resuelve consultas comunes invocando tools reales; respuestas con
gráfico + dato crudo + acción; cobertura medida por el eval harness.

**Estado: IMPLEMENTADO (primer entregable, 2026-06).** Archivos entregados:
`analysis/chat_tools.py` (registro de herramientas con adapters deterministas que envuelven el
motor existente: `analyze_ticker`→`full_analysis`, `plan_status`→`compute_plan_vs_reality`,
`retirement_projection`→`MonteCarloSimulator.run`; todos JSON-serializables y defensivos —si
falta contexto devuelven `{ok: False, error}` en vez de romper); `analysis/chat_agent.py`
(orquestador `ChatAgent` con `call_fn` inyectable: **router** que elige tool+args, ejecución de
la función determinista, y **narrador** que recibe SOLO los datos reales y tiene prohibido
inventar cifras —la garantía anti-alucinación es estructural, no un ruego al prompt);
`config.py` (sección `ChatConfig` / `CHAT`); página `dashboard/pages/18_Chat.py` (chat real con
`st.chat_input`, historial, y el **dato crudo en un expander** junto a cada respuesta);
y `tests/test_chat_agent.py` (8/8 con LLM falso + registro falso: routing, args, narración,
tool desconocida, error de tool, y el invariante de que el narrador solo ve datos deterministas).
Regresión total verde: **105 tests** entre todas las fases del Gran Salto. **Pendiente
(siguientes entregables de Fase 4):** sumar tools de optimizer/stress/sensitivity al registro,
gráficos en las respuestas, y medir la cobertura del chat con el eval harness.

**Dependencias:** Fases 2 y 3.

---

# FASE 5 — Black-Litterman + módulos de planificación (épica continua)

Profundidad de modelo y producto; conviene después de datos y agentes.

**Modelo (`portfolio/optimizer.py`):**
- **Black-Litterman** en lugar del proxy de expected returns (`score/100*0.18 + …`). El score
  ajustado *es* una view. Resuelve de raíz que el perfil **Conservador es matemáticamente
  infeasible** con el universo default (hoy cae a fallback score-weighted).
- **Shrinkage de covarianza (Ledoit-Wolf)** en vez de covarianza muestral.
- **Análisis de exposición a factores** (value/quality/momentum/size) de la cartera.
- **Monte Carlo con regime-switching** (`portfolio/monte_carlo.py`), no solo block-bootstrap.

**Estado (primer entregable, 2026-06): Black-Litterman + Ledoit-Wolf IMPLEMENTADOS.** Archivos:
`portfolio/black_litterman.py` (módulo puro NumPy: `ledoit_wolf_shrinkage()` —shrink a identidad
escalada, intensidad óptima cerrada, más estable con pocas observaciones → menos pesos extremos—;
`implied_equilibrium_returns()` —Π = δ·Σ·w_market, reverse-optimisation—; `black_litterman_posterior()`
—views absolutas P=I con el proxy de score como Q y Ω = τ·diag(Σ) escalada por la confianza del
score—; y `bl_expected_returns()` wrapper); `config.py` (sección `BlackLittermanConfig` /
`BLACK_LITTERMAN`); **wiring opt-in y guardado** en `portfolio/optimizer.py`: `_covariance_matrix`
usa Ledoit-Wolf cuando `shrinkage_enabled`, y `_apply_black_litterman()` reemplaza el `mu` por el
posterior BL dentro de `optimize()` (el proxy `_expected_returns` se conserva intacto como las
*views*, así los tests directos del proxy siguen valiendo). Ante cualquier desajuste de tamaño o
fallo numérico, vuelve al proxy → el camino determinista nunca se rompe. Tests:
`tests/test_black_litterman.py` 10/10 (PSD/simetría, intensidad↑ con pocas obs, equilibrio,
posterior entre prior y views, confianza, fallbacks) **y la suite del optimizer 62/62 sin
regresiones** con BL+shrinkage activos por defecto. Regresión total verde: **130 tests**.
**Pendiente de Fase 5:** exposición a factores, Monte Carlo regime-switching, y los módulos de
producto (tributaria, buckets, capa Argentina, coach proactivo, escalera de dividendos).

**Módulos de producto (continuo, por impacto):**
- Planificación financiera real: multi-cuenta (taxable vs. tax-advantaged), orden óptimo de
  retiro, tax-loss harvesting (los `EconomicDragConfig` ya existen, falta optimización
  tributaria). — *Alto.*
- Estrategia de buckets para riesgo de secuencia (cash/bonos/equity por tramos). — *Alto.*
- Capa Argentina first-class: dual ARS/USD, brecha, CER/inflación. — *Alto estratégico.*
- Coach proactivo anclado al plan: check-in automático cuando el mercado cae 8% (reutiliza
  scheduler + alertas). — *Alto.*
- Proyector de dividendos / escalera de cashflow para retiro. — *Medio.*

---

# Infra de soporte (transversal, según se necesite)

- **Sacar el cómputo pesado de Streamlit:** job queue + cache de resultados (Streamlit
  re-ejecuta el script entero en cada interacción). — necesario al escalar Fases 2–4.
- **Vector store** para el RAG. — necesario para Fase 3B.
- **Observabilidad:** logging de decisiones IA + costo por token. — útil desde Fase 2.
- **Frontend desacoplado** a mediano plazo, cuando el chat justifique UI propia. — Fase 4+.

---

# Gate de compliance (bloqueante para negocio)

El disclaimer actual alcanza para una herramienta educativa local. Un producto que "actúa" o
sugiere trades se acerca al **asesoramiento financiero regulado**. **Antes** de cualquier
salto B2B2C ("asesor en una caja" para advisors LatAm) o SaaS multi-tenant: revisión legal
seria. No es un detalle, es un gate. Se documenta aquí para que ninguna fase de producto lo
saltee por inercia.

---

# Resumen de arranque (cerrado)

La lista de “esta semana” (crear `track_record.py`, scorer, página 13, tests)
ya se ejecutó. Ver **Estado: IMPLEMENTADO** en cada fase de este mismo archivo.
Para trabajo nuevo, partí de [`CONTEXT.md`](CONTEXT.md), no de este kickoff.
