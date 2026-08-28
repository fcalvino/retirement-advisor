# Auditoría de calidad de datos — Retirement Advisor

**Fecha inicial:** 2026-08-10  
**Actualización P0:** 2026-08-11 — cableado multi-fuente, política `partial`, overlap raw facts  
**Tipo:** análisis + estado de implementación de P0  
**Alcance:** fuentes reales del pipeline, controles existentes, gaps y mejoras priorizadas  
**Anclado en código:** `data/*`, `analysis/fundamental.py`, `analysis/data_reconciliation.py`, `analysis/strategy.py`, `portfolio/*`, `config.py`, `dashboard/pages/16_Calidad_Datos.py`, tests de calidad/reconciliación  

> No es consejo de inversión. El foco es **confiabilidad de los números** que alimentan scores, decisiones, optimizer, Monte Carlo y el plan vivo.

---

## 0. Resumen ejecutivo

| Hallazgo | Severidad / estado |
|----------|-------------------|
| **Casi todo el scoring entra por yfinance** (info + financials + history). Un número incompleto o stale se propaga a score, moat proxy, expected returns del optimizer y paths de MC. | Estructural (sigue) |
| **Controles de calidad ya existen y son buenos en transparencia** (`compute_data_quality`, badges, gate BUY→HOLD si `poor`, personal_sizer, página de reconciliación). | Fortaleza |
| **Reconciliación multi-fuente en el pipeline** — `FundamentalAnalyzer.analyze` llama `attach_cross_source_quality` si `MULTI_SOURCE.enabled` y `attach_in_pipeline` (kill-switch). No reescribe scores. | **P0.1 ✅ cerrado** |
| **Política `partial` / `poor`** — `partial`: STRONG BUY→BUY + cap confidence; `poor`: BUY→HOLD; optimizer excluye `poor` y haircut a `partial` (`DATA_QUALITY`). | **P0.2 ✅ cerrado** |
| **Overlap raw facts** — `YFinanceSource` mapea `total_equity`/`total_assets`; badge con `cross_check_scope=raw_facts` (no certifica ROE/PE). | **P0.3 ✅ mitigado** |
| **Stale no degrada el nivel** (`stale=True` con `level=good` es válido). Solo badge ⏳ y warning. | Gap P1 |
| **Missing vs zero se confunden** en varios campos (`roe if roe != 0 else None` y análogos). | Gap P1 |
| **Datos curados (universos, tailwinds) y usuario/plan** — poca frescura automática. | Gap P2 |

**Conclusión de producto (post-P0):** la calidad **ya gobierna** decisión (partial/poor) y elegibilidad del optimizer (poor out / partial haircut), y el badge puede llevar metadata multi-fuente en el análisis batch. Siguen abiertos P1+ (stale→level, zero-vs-missing, MC, plan_health rename).

---

## 1. Fuentes de datos reales del pipeline

### 1.1 Mapa de fuentes → consumidores → falla si incompleto / stale / incorrecto

| Fuente | Artefacto | Qué entrega | Consumidores principales | Si incompleta / stale / incorrecta |
|--------|-----------|-------------|--------------------------|-------------------------------------|
| **yfinance — info** | `data/fetcher.py` `get_info` → cache `info:{sym}` | Precio, ratios (ROE, PE, D/E…), sector, country, market cap | `FundamentalAnalyzer`, crypto, chat tools, snapshots | Score con dimensiones en 0 / neutrales; DQ `partial`/`poor`; decisiones con risks; optimizer usa `adjusted_score` sesgado |
| **yfinance — financials** | `get_financials` → `financials:{sym}` | Income / BS / CF anuales | ROIC proxy, interest coverage, growth CAGRs, Piotroski/consistency | Sin statements → `has_financials=False` → **level poor**; scores de salud/crecimiento “neutrales” (`compute_data_quality`) |
| **yfinance — history** | `get_history` → `history:{sym}:{period}:{interval}` | OHLCV semanal/diario | Technical, MC, optimizer cov/mu empíricos, backtest, track record, crypto vol | Serie vacía → tech débil; MC rebalancea o cae a SPY; optimizer score-weighted fallback |
| **yfinance — dividends** | `get_dividends` | Serie de dividendos | Dividend score / payout context | DY mal o 0; optimizer **capa** DY sospechoso >15% (`_clean_div_yield`) |
| **Cache SQLite** | `data/cache.py` `DataCache`, TTL `CACHE_TTL_HOURS` (default **24h**, env) | Persistencia JSON de respuestas API | Todo lo anterior vía fetcher | `get` expira y borra; `get_age_hours` **no borra** (solo metadata DQ). Stale flag si age ≥ `DATA_QUALITY.stale_warning_hours` (**48h**) |
| **Multi-fuente: yfinance adapter** | `data/data_sources.py` `YFinanceSource` | Canonical: revenue, NI, shares, price, mcap | Reconciliación / UI | Misma dependencia yfinance; sin equity/assets |
| **Multi-fuente: SEC EDGAR** | `SecEdgarSource` (companyfacts) | revenue, NI, equity, assets (US 10-K) | Reconciliación / UI | `{}` en no-US, sin red, rate limit; no pisa scores del pipeline principal |
| **Multi-fuente: FMP** (opt-in) | `FmpSource` si `FMP_API_KEY` | price, mcap, revenue, NI | Tercer cross-check | Sin key → omitido de `default_fundamental_sources()` |
| **Multi-fuente: FRED** | `FredSource` | Series macro (no per-ticker fundamentals) | Macro / RAG (no scoring equity) | Sin `FRED_API_KEY` → skip |
| **Alpha Vantage** | Solo en `MULTI_SOURCE.source_priority` | — | **Sin adapter implementado** | Prioridad “fantasma”; no aporta datos |
| **Universos curados** | `data/universes/*.json` + `universe_loader.py` | Listas de tickers | Screener, Settings, customs | Ticker inválido se dropea; >20% drop → warning; customs se badgean |
| **Tailwinds curados** | `data/tailwinds/sector_country.json` + `analysis/tailwind.py` | Score sector-país, bonus ±8 | Fundamental adjusted_score, strategy rationale, optimizer ER tilt | Match erróneo o `last_reviewed` viejo → bonus sesgado; sin match → Neutral (byte-idéntico pre-feature) |
| **Preferencias / customs / perfil** | `data/preferences.py`, `user_preferences.json` | Universo activo, customs, perfil, plan activo | Dashboard, journey, filters | Customs con peor cobertura yfinance → más `partial`/`poor` |
| **Planes de retiro** | `plan_store.py`, `retirement_plans.json`, sample plans | Snapshot allocation/scores/MC al guardar | Mi Plan, alerts, health | Precios al guardar desactualizados → drift engañoso si no se refresca |
| **Plan health history** | `plan_health.py` / `plan_health_history.json` | Drift, `data_quality_pct` = % tickers con precio | Plan UI, alertas degradación | `data_quality_pct` **solo es cobertura de precio**, no completeness fundamental |
| **Portfolio tracker** | SQLite posiciones (`portfolio/tracker.py` / DB) | Holdings reales del usuario | Portfolio, sizer, alignment trades | Precio de mercado falla → posiciones sin mark-to-market |
| **Convicciones libro personal** | `personal_book_convictions` | HIGH/MED/LOW usuario | `personal_sizer` | Input subjetivo; sizer combina con DQ del análisis |
| **Snapshot offline** | `data/snapshot.py` | Export JSON de info/precio | Resiliencia (Fase G.3) | Copia point-in-time; no alimenta scoring en caliente |
| **Crypto** | `crypto_fetcher` + yfinance history | Precio, vol, halvings | CryptoAnalyzer, strategy vol cap | Sin precio → DQ poor; vol extrema → BUY cap a HOLD |

### 1.2 Flujo principal (dónde se “confía” en los datos)

```
yfinance
   │
   ▼
data/fetcher.py  ←→  data/cache.py (TTL 24h; age probe para DQ)
   │
   ├─ FundamentalAnalyzer.analyze
   │         → compute_data_quality
   │         → attach_cross_source_quality  (si MULTI_SOURCE.enabled + attach_in_pipeline)
   │         → FundamentalResult.data_quality  (+ sources_used / conflicts / scope)
   ├─ TechnicalAnalyzer / MC / Optimizer history
   │
   ▼
strategy.full_analysis → Decision
   │  apply_data_quality_policy:
   │    poor → BUY/STRONG BUY → HOLD
   │    partial → STRONG BUY → BUY + cap confidence
   │  risks si partial|poor
   ▼
Screener cache → Optimizer (score≥threshold; excluye poor; haircut partial)
              → Monte Carlo (min history weeks; SIN DQ de fundamentales)
              → Personal sizer (poor bloquea core concentration)
              → Plan health (solo % priced)
```

**UI multi-fuente (también en pipeline cuando attach_in_pipeline):**

- `dashboard/pages/16_Calidad_Datos.py` — `reconcile_sources` + `data_quality_agent`
- `dashboard/pages/2_Stock_Analysis.py` — `_cross_source_check` (cache 1h Streamlit) + `second_source_quality_signal` (`data/product_ux.py`)

---

## 2. Controles de calidad existentes vs gaps

### 2.1 Controles que sí están (evidencia)

| Control | Dónde | Comportamiento |
|---------|-------|----------------|
| Completitud de métricas clave | `compute_data_quality` + `_QUALITY_KEY_FIELDS` (10 campos) | `good` / `partial` (≥3 missing) / `poor` (≥6 o sin financials) |
| Frescura de cache info | `get_info_age_hours` + `stale_warning_hours=48` | `stale` booleano **independiente** del level |
| Badge UI | `data_quality_badge` en Screener; warnings agregados | 🟢/🟡/🔴 + ⏳ si stale |
| Soft gate decisión | `strategy.decide` + `apply_safety_overlay` (path AI) | Solo **`poor`** degrada BUY→HOLD + confidence LOW |
| Risks en decisión | strategy | `partial` y `poor` agregan risk text |
| Personal book | `personal_sizer` | `data_quality_level != "poor"` para core concentration; risk si poor |
| Reconciliación multi-fuente | `reconcile` / `data_quality_agent` | **Solo compara valores del mismo período fiscal** (`as_of` a ±15 días). Conflicto si Δ relativa > `discrepancy_pct` (5%) *entre valores comparables*; downgrade 1 nivel si `conflict_downgrades_quality`. Períodos que no coinciden → `comparable=False`: se reportan como "no se pudo verificar", **no** como discrepancia, y no mueven el badge |
| Cap DY basura | optimizer `_clean_div_yield` | DY fuera de [0, 15] → 0 |
| History mínimo MC | `MONTE_CARLO.min_history_weeks` (104) | Bloquea / avisa si historia corta |
| MC missing tickers | `_load_returns` | Rebalancea pesos; o SPY fallback |
| Universe validation | `universe_loader._is_valid_ticker` | Drop de basura + warning >20% |
| Customs badge | product UX / Screener | Customs tratados como calidad inferior potencial |
| Tests offline | `tests/test_data_quality.py` (11), `tests/test_data_reconciliation.py` (11), strategy DQ | Completitud, stale, crypto/ETF, conflictos, attach con fakes |

**Evidencia offline ejecutada (2026-08-10):**

- 24 tests de calidad/reconciliación/strategy DQ: **passed**
- `attach_cross_source in full_analysis: False`
- `attach_cross_source in fundamental.py: False`
- Stale completo: `level=good, stale=True`
- Conflicto 100 vs 140 NI: agent → `level=partial`, chosen=`sec_edgar`
- `optimizer_mentions_data_quality: False`, `monte_carlo_mentions_data_quality: False`
- Captura: scratch `data_quality_audit_notes.txt`

### 2.2 Gaps concretos (qué sigue “entrando mal”)

#### G1 — Reconciliación no gobierna el score (P0) — ✅ cerrado 2026-08-11

- `FundamentalAnalyzer._attach_cross_source_quality` invoca `attach_cross_source_quality` tras `compute_data_quality` cuando `MULTI_SOURCE.enabled` y `attach_in_pipeline`.
- Sigue **sin sobrescribir** métricas del score; solo badge + warnings.
- Kill-switch: `attach_in_pipeline=False` deja la UI de Calidad de Datos operativa sin red en batch.

#### G1.1 — La comparación tiene que ser del mismo período — ✅ cerrado 2026-08-18

El chequeo cruzado degradaba **22 de 25 tickers con cero métricas faltantes** (16 STRONG BUY → BUY). No medía calidad: medía si SEC había contestado. Corrida `default` del 2026-08-17 (solo yfinance respondió) → 22 `good`; corrida `us_quality` del 2026-08-18 (SEC respondió) → 22 `partial`. Tres defectos apilados:

1. **Tags us-gaap muertos.** `_CONCEPTS` tomaba el primer tag que existiera en la historia de la empresa. Las empresas retiran tags (ASC 606 sacó revenue de `Revenues`) pero el tag retirado sobrevive en `companyfacts` con su último valor histórico: MSFT resolvía a **FY2010** (62,48 B), CRM a **FY2017** (8,39 B), MA a `NetIncomeLoss` de **FY2013** (3,12 B — hoy reporta bajo `ProfitLoss`, que ni estaba en la lista). Ahora se escanean **todos** los tags candidatos y gana el de `end` más reciente; el orden de la lista es solo desempate.
2. **Fallback a trimestrales.** `_latest_annual` caía a "cualquier row con `val`", que en KLAC devolvió un **10-Q de 2011**. Ahora exige duración de 330–400 días y no hay fallback.
3. **TTM contra FY.** yfinance entregaba TTM sin fecha (`info.totalRevenue`) contra el último 10-K de SEC; con `discrepancy_pct=5%`, toda empresa que creciera más de 5% anual era "discrepancia" por definición. `YFinanceSource` ahora lee los estados anuales (`get_financials`, ya cacheado y ya llamado por `analyze()`) y estampa `as_of`.

Regla nueva en `reconcile()`: **el reconciliador se niega a comparar valores cuyos períodos no coinciden**, en vez de comparar y llamar conflicto a la diferencia. `agreement_pct` solo cuenta campos comparables.

Re-medido sobre las mismas 24 empresas: **0 conflictos (antes 38), 0 degradaciones falsas (antes 22)**.

**Qué compra esto, y qué no.** Con los períodos alineados, cada campo comparable coincide con **Δ = 0,00%**: los estados anuales de yfinance derivan de los mismos filings de SEC. Es un chequeo de **procedencia** (¿el número que usó el score sale del 10-K vigente?), no verificación independiente — no puede detectar un dato mal que esté mal en ambos. Verificación independiente de verdad requiere la tercera fuente: `FMP_API_KEY`. Lo que sí detecta es desactualización real: QCOM y V tienen `total_equity` con el tag de SEC congelado en 2019 y 2011, y salen como "no se pudo verificar".

Costo: ~1,2 s/ticker contra el presupuesto de 3,5 s/ticker del screener. `SecEdgarSource._cik_map` pasó a nivel de clase con lock — `default_fundamental_sources()` crea un adapter por ticker, así que el mapa ticker→CIK (~1 MB) se re-descargaba una vez por ticker con 6 hilos en paralelo. Definir `SEC_USER_AGENT` con un contacto real antes de correr universos grandes.

#### G2 — `partial` no frena el pipeline (P0/P1) — ✅ cerrado (soft) 2026-08-11

- `apply_data_quality_policy` en `strategy.decide` y `apply_safety_overlay`:
  - `partial` → no STRONG BUY (queda BUY) + confidence ≤ `partial_max_confidence`
  - `poor` → BUY/STRONG BUY → HOLD
- Optimizer: `exclude_poor_from_optimizer` + `partial_optimizer_score_haircut` sobre copia local del scored dict.
- Residual P1: MC sigue ciego a DQ fundamental.

#### G3 — Stale no degrada nivel ni bloquea (P1)

- Cache TTL 24h; warning stale a 48h.
- Un `info` de 72h puede ser `good` + `stale`.
- **History/financials** no tienen age en el badge (solo se mide `info:{symbol}`).

#### G4 — Campos canónicos de reconciliación ≠ campos del score (P0.3 mitigado / residual P1)

| Score key fields | En YFinanceSource | En SecEdgarSource |
|------------------|-------------------|-------------------|
| roe, roic, margins, D/E, CR, PE, PB, CAGRs | No (solo raw facts) | No |
| total_revenue, net_income | Sí | Sí |
| shares, price, mcap | Sí | No |
| total_equity, total_assets | **Sí** (info keys) | Sí |

Cross-check solapa **revenue, NI, equity, assets** cuando ambas fuentes responden. Badge marca `cross_check_scope=raw_facts` (no certifica ROE/PE). Residual: no se reconcilian ratios del score (evita falsos conflictos TTM vs FY).

#### G5 — Missing vs zero / escalas yfinance (P1)

- Patrón repetido: `result.roe = roe if roe != 0 else None` (también roic, net_margin, gross_margin, debt_equity, current_ratio).
- `_safe_float(None)=0` → missing y “cero real” colapsan.
- `debtToEquity / 100` asume escala yfinance; si el proveedor cambia o un ticker no usa esa escala, D/E se distorsiona.
- ROIC usa **tax_rate hardcode 0.21** (US) — sesgo para AR ADRs / no-US.

#### G6 — Optimizer / MC / plan health ciegos a DQ fundamental (parcialmente mitigado)

- Optimizer (**P0**): excluye `poor`; haircut `partial` (`DATA_QUALITY`); lee `data_quality_level` o `data_quality.level`.
- MC: quality = longitud de historia de precios, no fundamentals → **P1**.
- `PlanHealthRecord.data_quality_pct` = `n_priced / n_total` — nombre engañoso vs badge fundamental → **P1**.

#### G7 — Cobertura multi-fuente para el universo real (P1)

- Universo default incluye **ADRs AR, ETFs, crypto** (`docs/universe_coverage_analysis.md`).
- SEC no aplica a ADRs no-US / crypto / ETF.
- Sin FMP key, `default_fundamental_sources()` = yfinance + sec_edgar; para mucho del universo → **una sola fuente efectiva** + warning “sin verificación cruzada” solo si se corre la UI de calidad.

#### G8 — Datos curados sin “stale policy” operativa (P2)

- Tailwinds tienen `last_reviewed` (ej. `2026-06`) pero **no hay check** que baje bonus o avise en UI si > N meses.
- Universos JSON no validan existencia en yfinance al cargar (solo formato de ticker).

#### G9 — Página Calidad de Datos en modo dev (P2 producto)

- En navegación actual, herramientas de calidad multi-fuente tienden a vivir en **modo dev** (ver auditoría de producto). El usuario típico no ve el cross-check salvo caption en Stock Analysis.

#### G10 — Tests: cubren motor puro, no wiring de producción (P2)

Cubren bien:

- Umbrales partial/poor, financials, crypto/ETF, stale independiente, dividend_yield excluido.
- Reconcile agreement/conflict/priority, agent downgrade, attach con fakes, skip crypto.

**Cubren (post-P0, 2026-08-11):**

- Wiring: `FundamentalAnalyzer._attach_cross_source_quality` llama attach cuando enabled + `attach_in_pipeline`; no llama si flag off.
- Política partial (STRONG BUY→BUY, cap confidence) + overlay AI.
- Optimizer: exclude poor + haircut partial (sin mutar input).
- YFinanceSource mapea equity/assets; agent marca `cross_check_scope=raw_facts`.

**Aún no cubren:**

- Freshness de `history`/`financials`.
- Integridad de escala debtToEquity / zero-vs-missing.
- Aging de tailwinds `last_reviewed`.
- MC respeta DQ fundamental.

---

## 3. Impacto aguas abajo cuando la calidad es `partial` / `poor` / conflicto

| Capa | `partial` | `poor` | Conflicto multi-fuente |
|------|-----------|--------|------------------------|
| Score fundamental | Dimensiones faltantes ~0 pts → score **subestimado** o sesgado | Igual + flag; sin financials → neutrales | Scores **no** se reescriben; badge puede bajar 1 nivel |
| Decision rule / AI overlay | STRONG BUY→BUY; confidence cap MEDIUM; risks | BUY→HOLD, confidence LOW | Warnings de discrepancia en result si attach corrió |
| Screener | Badge 🟡 (+ ⏳ si stale) | Badge 🔴 | Metadata en `data_quality` del fund (batch) |
| Optimizer | Entra con **haircut** de score (default ×0.95) | **Excluido** del eligible | N/A directo (usa level post-agent) |
| Monte Carlo | Solo precio history | Igual | No |
| Personal sizer | Core OK si resto de gates | **No** core concentration | No |
| Plan health | `data_quality_pct` de precios | Igual | No |
| Alertas / scheduler | Heredan policy partial/poor vía full_analysis | Igual | Attach en analyze si flags on |

**Riesgo residual:** ADRs/`partial` frecuentes aún pueden BUY (a propósito, soft gate); MC y plan health no usan DQ fundamental.

---

## 4. Mejoras priorizadas (problema → riesgo → outcome)

> Solo outcomes; no se implementan en este goal. Cada ítem cita artefacto del repo.

### P0 — Alta confianza / alto impacto — ✅ implementado 2026-08-11

| # | Problema (histórico) | Cómo quedó (outcome real) | Artefactos |
|---|----------------------|---------------------------|------------|
| **P0.1** ✅ | Reconciliación no en batch | `FundamentalAnalyzer.analyze` → `_attach_cross_source_quality` → `attach_cross_source_quality`; flags `MULTI_SOURCE.enabled` + `attach_in_pipeline` | `analysis/fundamental.py`, `config.MultiSourceConfig` |
| **P0.2** ✅ | `partial` no gobernaba | `apply_data_quality_policy`: partial cap STRONG BUY + confidence; poor→HOLD (rule + AI overlay). Optimizer: exclude poor + haircut partial | `strategy.py`, `portfolio/optimizer.py`, `DATA_QUALITY.*` |
| **P0.3** ✅ | Poco solape de campos | YFinance mapea equity/assets; agent setea `cross_check_scope=raw_facts` + warning de scope | `data/data_sources.py`, `data_quality_agent` |

### P1 — Calidad de señal y honestidad numérica

| # | Problema | Riesgo | Outcome | Evidencia |
|---|----------|--------|---------|-----------|
| **P1.1** | Stale no baja level; history/financials sin age | Precios/ratios “viejos” se ven good | Incluir stale material en level o en elegibilidad de decisiones; surface age de history/financials en DQ | `compute_data_quality` stale independent; solo `info:` en `get_info_age_hours` |
| **P1.2** | Zero vs missing colapsados | Penaliza incompleto como “malo” y viceversa | Separar “campo ausente” de “valor 0 legítimo” antes de scoring y de `_QUALITY_KEY_FIELDS` | `fundamental.py` `if x != 0 else None` |
| **P1.3** | ROIC tax 0.21 y D/E /100 fijos | Sesgo sistemático AR/no-US o si yfinance cambia escala | Parametrizar / detectar moneda-país; validar rango D/E sensato | `_compute_roic`, `_score_financial_health` |
| **P1.4** | Optimizer/MC ignoran DQ | Pesos y proyecciones sobre inputs frágiles | Haircut de expected return o exclusión suave de `poor`/`partial`; warning en resultado optimizer/MC | `portfolio/optimizer.py`, `monte_carlo.py` |
| **P1.5** | Plan health “calidad datos %” = solo precios | Falsa sensación de calidad fundamental | Renombrar o combinar con % tickers good/partial/poor del último screener | `PlanHealthRecord.data_quality_pct` |
| **P1.6** | Sin FMP key, ADRs/crypto casi sin 2ª fuente | Multi-source “enabled” pero no efectivo | Fallback documentado + badge “single_source” en screener (ya existe señal en product_ux; **subir a tabla** no solo caption SA) | `default_fundamental_sources`, `second_source_quality_signal` |
| **P1.7** | `alpha_vantage` en priority sin adapter | Config engañosa | Quitar de priority o implementar adapter; alinear config con código | `MultiSourceConfig.source_priority` |

### P2 — Gobernanza de datos curados y tests de wiring

| # | Problema | Riesgo | Outcome | Evidencia |
|---|----------|--------|---------|-----------|
| **P2.1** | Tailwinds sin alarma de `last_reviewed` viejo | Bonus estructural desactualizado | Warning en TailwindDetail/UI si review > N meses (config) | `sector_country.json` `last_reviewed`; `TailwindDetail` |
| **P2.2** | Universos no verifican resolvibilidad yfinance | Ticker muerto en screener | Job/smoke opcional: % del universo con `get_info` no vacío | `universe_loader`, universes JSON |
| **P2.3** | Calidad multi-fuente escondida en dev | Usuario no audita datos | Exponer reconciliación 1-click desde Screener/Stock Analysis en modo normal (o resumen agregado post-screener) | `16_Calidad_Datos.py`, nav app |
| **P2.4** | Tests no fijan wiring de producción | Regresión “feature exists but unwired” otra vez | Test: `full_analysis` (mocked sources) llama attach **o** documenta contract “UI-only” hasta P0.1 | `tests/test_data_reconciliation.py` solo unitario |
| **P2.5** | Snapshot offline no rehidrata análisis | Resiliencia parcial | Permitir análisis “from snapshot” en modo degradado con badge forzado partial | `data/snapshot.py` |

---

## 5. Cobertura de tests existentes

### `tests/test_data_quality.py`

| Comportamiento | Cubierto |
|----------------|----------|
| Todos los key fields → good | ✅ |
| partial_missing_fields − 1 → good | ✅ |
| Umbral partial / poor | ✅ |
| Sin financials → poor | ✅ |
| dividend_yield None no penaliza | ✅ |
| Fresh / stale / freshness None | ✅ |
| Crypto con precio / ETF sin precio | ✅ |
| Integración en `FundamentalAnalyzer.analyze` real | ❌ |
| Stale de history/financials | ❌ |
| Zero vs missing | ❌ |

### `tests/test_data_reconciliation.py`

| Comportamiento | Cubierto |
|----------------|----------|
| Agreement / conflict / priority / single source | ✅ |
| reconcile_sources + source que falla | ✅ |
| Agent downgrade / keep level / single-source warning | ✅ |
| attach muta result; skip crypto | ✅ |
| attach desde `full_analysis` | ❌ |
| SEC/FMP live | ❌ (by design offline) |
| discrepancy_pct edge / chosen no pisa score | ❌ (filosofía documentada, no test de no-mutación de scores) |

### Strategy / sizer

| Comportamiento | Cubierto |
|----------------|----------|
| poor BUY→HOLD | ✅ `test_poor_data_quality_degrades_buy_to_hold` |
| partial no degrada BUY | ❌ (gap de política) |
| personal_sizer poor bias | ✅ `test_poor_data_quality_biases_conservative` |

---

## 6. Recomendación de secuencia

1. ~~**P0.1–P0.3**~~ **Hecho (2026-08-11).**  
2. **P1.2 + P1.3** Honestidad numérica (missing vs zero, escalas, tax ROIC).  
3. **P1.1** Stale material en level / age de history-financials.  
4. **P1.4 residual** MC warnings/gates por DQ; **P1.5** plan_health rename.  
5. **P1.6–P1.7 + P2.*** Segunda fuente para ADRs, alpha_vantage cleanup, tailwinds aging, UI fuera de dev.

Alineado con `docs/IMPLEMENTATION_PLAN.md` Fase 3A y badge Fase E.

---

## 7. Checklist de verificación de este entregable

| Criterio del plan | ¿Cubierto? |
|-------------------|------------|
| (a) yfinance + cache TTL/edad | §1, §2 (TTL 24h, stale 48h, `get_age_hours`) |
| (b) multi-fuente y reconciliación | §1 adapters, §2 G1/G4, §4 P0.1 |
| (c) badge `compute_data_quality` + umbrales `DATA_QUALITY` | §2.1, evidencia offline |
| (d) curados (universos/tailwinds) y usuario/plan | §1 tabla, G8, P2.1–P2.2, plan health G6 |
| (e) impacto aguas abajo partial/poor/conflicto | §3 |
| Cada gap cita artefacto | Sí, tablas §2–§4 |
| Mejoras priorizadas problema vs outcome | §4 P0/P1/P2 |
| Evidence offline | §2.1 + scratch notes; 24 tests passed |
| Tests cover vs not cover | §5 |

---

### Changelog implementación P0 (2026-08-11)

| Cambio | Detalle |
|--------|---------|
| Config | `MULTI_SOURCE.attach_in_pipeline`; `DATA_QUALITY.partial_caps_strong_buy`, `partial_max_confidence`, `exclude_poor_from_optimizer`, `partial_optimizer_score_haircut` |
| Analyze | Attach multi-fuente best-effort post-DQ |
| Strategy | `apply_data_quality_policy` compartido rule/AI |
| Optimizer | Filter poor + haircut partial; Optimizer UI pasa `data_quality_level` |
| Sources | equity/assets en YFinance; scope raw_facts en agent |
| Tests | Wiring, policy, optimizer DQ, YF mapping — suite targeted en verde |

*Fin del documento de auditoría de calidad de datos (actualizado post-P0).*
