# Auditoría técnica — Retirement Advisor

> Fecha: 2026-08-11 · Alcance: motor de cálculo, capa de datos, tests, arquitectura, mantenibilidad
> Método: lectura de código + verificación numérica ejecutable (no revisión de documentación)
> Estado de partida verificado: **610 tests pasando en 9.5s**, CI con ruff + matrix 3.11/3.12

---

## ✅ Estado: Tier 0 CERRADO (2026-08-12)

**D1, D2 y D3 están corregidos.** Motor `2026.08-tier0` (`config.ENGINE_VERSION`).
Suite: **717 pasando** (610 de base + 98 del oráculo nuevo + 9 de regresión).

| # | Defecto | Estado | Evidencia |
|---|---|---|---|
| D1 | Retiros restaban un nivel nominal | ✅ Corregido | `decumulation.withdraw_at_week()` — kernel único; `monte_carlo._apply_withdrawals` delega |
| D2 | Ruina no absorbente | ✅ Corregido | absorbente por construcción (factor 0); `prob_ruin_pct` sobre mínimo intra-horizonte |
| D3 | μ dependía del perfil | ✅ Corregido | `VIEW_WEIGHTS` globales; el perfil actúa vía `ProfileConfig.risk_aversion` (δ del prior BL) |

**Validación:** `tests/test_withdrawal_oracle.py` — 98 casos contra un oráculo secuencial
escrito de forma independiente (no contra el motor previo). Se escribió **antes** del fix y
falló en 64 casos; tras el fix pasa en 98/98.

**Impacto medido** sobre un plan realista (retiro $40k/año = 4%, inflación 3%, 30 años,
6.000 simulaciones, mercado sintético +9,1%/año geométrico, vol 14,9%):

| Métrica | Motor viejo | Motor corregido | Δ |
|---|---:|---:|---|
| Mediana del patrimonio final | $5.299.507 | $1.892.217 | **−64,3%** |
| p10 (escenario pesimista) | $477.083 | $0 | — |
| Probabilidad de ruina reportada | 6,3% | **24,1%** | ~4× |
| Ruinas intra-horizonte ocultas | 6,3 pp | 0 | — |

El error real en producción resultó **mayor** que el +60,2% del caso testigo de esta auditoría:
con retiros que crecen por inflación a 30 años, la distorsión compone más fuerte.

**Hallazgo secundario, contraintuitivo:** el bug **no era uniformemente optimista**. En mercados
bajistas, restar un monto fijo de un saldo que cae castigaba de más — el caso testigo de D2 se
agotaba en la semana 185 con el motor viejo y en la 208 con el corregido. El signo del error
dependía del escenario, y por eso ningún promedio agregado lo hacía visible.

**Sin cambios para acumulación pura:** el kernel de retiro no se invoca cuando no hay retiros.

**Pendiente (no era Tier 0):** el Optimizer y el Monte Carlo siguen sin compartir modelo de
retorno. D3 se resolvió en su alcance quirúrgico (μ dejó de depender del perfil); anclar μ a la
historia de precios para reconciliar ambos motores es la opción B de D3, aún abierta. Mientras
tanto la UI llama a ese número **"atractivo estimado"**, no "retorno esperado".

---

## Resumen

El proyecto tiene una arquitectura mejor de lo que su documentación sugiere: **cero imports de
Streamlit fuera de `dashboard/`**, motor puro en NumPy, config centralizada, 610 tests. Esa
separación es real y es lo que hace que los arreglos de abajo sean baratos.

El problema no es la arquitectura. Es que **el motor de decumulación —el corazón de una herramienta
de retiro— tiene un error matemático que sobrestima el patrimonio final hasta un 60%**, y el
sistema de tests no puede detectarlo porque está diseñado para verificar consistencia con sí mismo,
no corrección financiera.

Se han entregado ~14 fases de features (A–J, Olas UX, Comité, Libro Personal) sobre una base cuyo
cálculo central nunca fue validado contra una verdad externa.

**La mejora determinante nº1 no es una feature: es parar de agregar fases hasta que el motor esté
validado.**

---

## Tier 0 — Los números que ve el usuario están mal  ·  ✅ CERRADO 2026-08-12

### D1. El motor de retiros no descuenta capital: resta un nivel constante ✅ CORREGIDO

`portfolio/monte_carlo.py:594` y `portfolio/decumulation.py:163,173,195`

```python
p[:, week_idx:] -= grown          # resta un valor FIJO a todas las semanas futuras
p = np.maximum(p, 0)
```

Un retiro saca **capital**: el dinero retirado deja de componer con el mercado. El motor en cambio
resta un monto nominal constante a todo el path futuro, con lo cual el dinero retirado *sigue
participando implícitamente del crecimiento*. El error compone con el horizonte.

**Verificación** (`scripts` de repro al final):

| Escenario determinista, 30 años, retiro 4%/año | Correcto | Motor actual | Error |
|---|---:|---:|---:|
| Alcista +8%/año | $553.133 | **$886.266** | **+60,2%** |

Afecta a las tres estrategias (`fixed_real`, `constant_pct`, `guardrails`) y por lo tanto a
`prob_sustain_real_pct`, `prob_legacy_pct`, `expected_depletion_year`, `median_legacy` y al fan chart.

**El sesgo va en dirección contraria al haircut conservador del que el proyecto se enorgullece.**
`mean_haircut=0.80` recorta ~20%; este bug agrega +60%. El neto es una proyección *optimista*
presentada como conservadora.

**Fix:** aplicar el retiro como reducción proporcional de unidades desde el punto de retiro:

```python
# en el año yr, semana w0:
factor = np.where(p[:, w0] > 0, 1.0 - w / np.maximum(p[:, w0], eps), 0.0)
p[:, w0:] *= factor[:, None]
```

Costo: ~20 líneas en 2 archivos. **Rompe la identidad byte-a-byte con el motor legacy — que es
exactamente lo que hay que romper.**

---

### D2. La ruina no es absorbente: paths quebrados "resucitan" ✅ CORREGIDO

Mismo bloque. Tras `np.maximum(p, 0)`, las semanas posteriores conservan el crecimiento
multiplicativo ya calculado, así que un path que llegó a $0 vuelve a mostrar valor positivo.

**Verificación:** path que cae 25%/año 4 años y luego se recupera, retiro $12.000/año:

```
correcto (secuencial) = $0
motor: mínimo intra-horizonte = $0  |  terminal = $32.723
  -> tocó $0 en semana 185 (año 3.6) y RESUCITÓ a $32.723
```

Consecuencia directa: **dos métricas que la UI muestra juntas se contradicen.**

| Métrica | Dónde | Qué mide | Veredicto del path de arriba |
|---|---|---|---|
| `prob_sustain_real_pct` | `decumulation.py:239` — `min` sobre la ventana | correcto | quebró ❌ |
| `prob_legacy_pct` | `decumulation.py:244` — solo terminal | incorrecto | dejó $32.723 de herencia ✅ |
| `prob_ruin_pct` | `monte_carlo.py:355` — solo terminal | incorrecto | no quebró |

**Fix:** una vez que el path toca 0, forzarlo a 0 hacia adelante (`np.minimum.accumulate` sobre una
máscara de vivo/muerto), y derivar `prob_ruin_pct` del mínimo intra-horizonte, no del terminal.

---

### D3. Dos motores con modelos de retorno incompatibles, sin reconciliación ✅ CORREGIDO (alcance quirúrgico)

El Optimizer y el Monte Carlo —las dos mitades de "Mi Plan"— no comparten supuesto de retorno:

- **Optimizer** (`optimizer.py:587`): μ es un *proxy heurístico del score*
  `score_ret = (score/100) * 0.18`, mezclado con los pesos del perfil.
- **Monte Carlo**: bootstrap de retornos históricos reales × `mean_haircut`.

El MC **nunca lee** el μ del optimizer. Un plan combina una asignación optimizada bajo un supuesto
de retorno con una proyección construida sobre otro distinto.

Peor: **el retorno esperado del mismo activo cambia según el perfil de quien lo mira**, porque
`score_weight`/`dividend_weight`/`moat_weight` funcionan a la vez como preferencias y como
estimadores:

| Activo (score=60, moat=8) | μ implícito |
|---|---:|
| perfil conservative | 5,08%/año |
| perfil moderate | 6,40%/año |
| perfil aggressive | **7,72%/año** |

Un activo no rinde más porque el inversor sea agresivo. La frontera eficiente y el
`expected_return_pct` que se muestran son, en rigor, artefactos del perfil.

**Fix (mínimo honesto, sin reescribir el optimizer):** separar *preferencia* de *estimación* —
μ base único por activo (histórico con shrinkage, o CAPM/BL, que ya está parcialmente ahí en
`black_litterman.py`), y que el perfil actúe solo sobre las **restricciones y la aversión al
riesgo**, no sobre μ. Y renombrar en UI `expected_return_pct` a "score de atractivo" mientras no
sea un retorno estimado de verdad.

---

## ✅ Estado: Tier 1 CERRADO (2026-08-14)

**D4, D5 y D6 están corregidos.** Suite: **982 pasando en 3,2 s** (761 de base + 221 nuevos).

| # | Defecto | Estado | Evidencia |
|---|---|---|---|
| D4 | Tests validaban consistencia consigo mismos | ✅ Corregido | `tests/test_engine_oracles.py` (64 casos contra oráculos independientes) + 106 tests en los 5 módulos que no tenían ninguno |
| D5 | Dependencias sin pinear | ✅ Corregido | `requirements.lock` con hashes (`make lock`); Docker instala con `--require-hashes`; `PlanSnapshot.lib_versions` sella el entorno numérico. Destapó 2 dependencias muertas (`pandas-ta`, `pyyaml`) |
| D6 | PII versionada en git | ✅ Corregido · **hallazgo sobredimensionado** | Destrackeado + en `.gitignore` + plantilla. Auditado el historial: **no contenía el perfil financiero** — ver la corrección en D6 |

### Lo que encontraron los oráculos (que 761 tests verdes no veían)

**1. CAGR con off-by-one en el backtest** — `analysis/backtesting.py:_metrics`

El denominador era el **número de barras**, no el tiempo transcurrido: N barras semanales cubren
N−1 semanas. La cartera que duplicaba en exactamente un año se reportaba creciendo **97,4 %/año**
en vez de 100 %.

| Horizonte | Reportado (viejo) | Correcto | Error |
|---|---:|---:|---:|
| 1 año | 7,843 % | 8,000 % | −0,157 pp |
| 3 años | 7,947 % | 8,000 % | −0,053 pp |
| 5 años | 7,968 % | 8,000 % | −0,032 pp |
| 10 años | 7,984 % | 8,000 % | −0,016 pp |

El sesgo es **sistemático y siempre a la baja**, y contamina `alpha_pct` (CAGR cartera − CAGR
benchmark) y `calmar_ratio`. La magnitud es chica comparada con D1, pero el punto es *cómo* apareció:
el oráculo se escribió desde la definición financiera ("crecimiento compuesto por año transcurrido")
y el motor discrepó. Ningún test de consistencia interna podía verlo.

**2. La suite no era reproducible** — `test_optimizer.py`, `test_optimizer_crypto.py`, `test_tailwind.py`

Tres archivos generaban sus precios sintéticos con `np.random.default_rng(hash(sym) % 2**31)`.
El hash de strings en Python está **aleatorizado por proceso** (`PYTHONHASHSEED`), así que *los datos
de entrada de esos tests cambiaban en cada corrida*. `test_full_optimize_populates_tailwind_fields`
falló una vez durante esta auditoría y pasó en las 4 corridas siguientes con el mismo código.

Un verde que no se puede reproducir no es evidencia. Reemplazado por `zlib.crc32(sym.encode())`
(estable entre procesos); verificado con `PYTHONHASHSEED` ∈ {0, 7, 13, 42, 99} → 982/982 en las cinco.
Es el mismo problema que D5 una capa más arriba: si el input no está fijo, el resultado no es prueba.

### D4 — la capa de oráculos

`tests/test_engine_oracles.py` (64 casos). Cada test compara el código vectorizado de producción
contra una **implementación de referencia lenta, escrita desde la definición financiera**, no desde
el fuente de producción:

| Área | Oráculo de referencia |
|---|---|
| Drags económicos | loop semana a semana cobrando la comisión sobre el saldo vigente |
| Aportes (retiros negativos) | contabilidad secuencial: el mercado crece, después entra el ahorro |
| Métricas de decumulación | bookkeeping en Python puro, path por path |
| Estadísticos del optimizer | Σ wᵢμᵢ y la doble suma Σᵢ Σⱼ wᵢwⱼσᵢⱼ escritas a mano |
| Curva equal-weight + rebalanceo | contabilidad de acciones como la haría un broker |
| Métricas del backtest | CAGR / drawdown / retorno total desde la definición |

Además hay tests de **contrato económico** que no dependen de ninguna implementación: un drag anual
del 1 % deja exactamente 99 % después de 52 semanas; rebalancear no crea ni destruye valor;
concentrar el 100 % en un activo reproduce su propia volatilidad.

**Cobertura de los 5 módulos que no tenían ninguna** (+106 tests):

| Módulo | LOC | Tests | Qué cubre |
|---|---:|---:|---|
| `portfolio/tracker.py` | 287 | 27 | contabilidad de posiciones reales (promediado ponderado, P&L, pesos por sector) |
| `alerts/reporter.py` | 437 | 28 | el PDF desatendido se genera y lleva el disclaimer legal |
| `analysis/backtesting.py` | 461 | 27 | ranking, alpha, cadencias de rebalanceo, persistencia, paths de fallo |
| `scripts/run_scheduler.py` | 394 | 26 | decisiones de la automatización (drift vs plan activo, SORR, baseline de GOAL) |
| `data/crypto_fetcher.py` | 235 | 25 | calendario de halving con fechas inyectadas, métricas de precio |

El scheduler era el más urgente: todo lo que hace está envuelto en `except Exception`, así que un bug
ahí no rompe nada — simplemente el usuario deja de recibir las alertas y nadie se entera.

### D5 — reproducibilidad

- `requirements.lock`: 2.132 líneas, todo `==` con hashes SHA-256 (`uv pip compile --generate-hashes`).
  Regenerable con `make lock`. El `Dockerfile` instala con `--require-hashes`.
- `PlanSnapshot.lib_versions` (nuevo `data/env_provenance.py`): sella python/numpy/scipy/pandas al
  guardar. `numeric_env_drift()` compara contra el entorno actual y Mi Plan lo muestra. Es una señal
  **distinta** de `is_engine_stale()`: que cambien nuestras fórmulas y que cambien las librerías abajo
  son dos razones diferentes para volver a simular. Un plan viejo sin sello se reporta como
  *desconocido*, nunca como *igual*.

**Hallazgo lateral — dos dependencias muertas** (resuelto 2026-08-14): el resolver no podía satisfacer
`requirements.txt` en Python 3.11, porque `pandas-ta` ≥0.4.71b0 exige `>=3.12`. Al ir a arreglarlo
apareció que **`pandas-ta` no se usa**: `docs/DEAD_CODE_AUDIT.md` registra que su import se eliminó de
`analysis/technical.py` hace tiempo (los indicadores se calculan a mano con NumPy/Pandas), pero nadie
la sacó de `requirements.txt` — y el `>=` la fue subiendo sola hasta llevarse puesto el soporte de
3.11. El mismo chequeo encontró `pyyaml`, también declarada y nunca importada.

Sacando las dos: `requirements.txt` vuelve a resolver en **3.11 y 3.10**, y el lock baja de 85 a 81
paquetes (se van además `numba` y `llvmlite`, que solo entraban por `pandas-ta`). Verificado que
**todas** las dependencias tienen wheel manylinux
(`uv pip compile --python-platform x86_64-manylinux_2_28 --only-binary :all:`), así que el `Dockerfile`
ya no instala `gcc`/`g++`. El lock pasa a apuntar a 3.11 (piso del CI) para que una sola resolución
sirva en todo el rango. **Prueba final: 985 tests pasan en un venv limpio construido solo desde el
lock hasheado.** No hizo falta tocar la matriz de CI ni bajar ninguna versión.

`tests/test_reproducibility.py::TestNoDeadDependencies` ahora falla si se declara una dependencia que
nadie importa. Es el guard que faltaba: una dependencia muerta no es sólo peso muerto — restringe el
intérprete, engorda la imagen y amplía la superficie de supply-chain, todo sin dar nada a cambio.

### D6 — PII fuera del repo

`git rm --cached data/user_preferences.json` + entrada en `.gitignore` (junto a los otros runtime JSON
que ya estaban ignorados). Se versiona `data/user_preferences.example.json`, y `UserPreferences.load()`
siembra desde esa plantilla en un clon nuevo (con `onboarded: false`, así corre el wizard).
`tests/test_reproducibility.py` falla si alguien la vuelve a trackear.

#### ⚠️ Corrección: este hallazgo estaba sobredimensionado

**El texto original de D6 (abajo) es incorrecto** y se corrige acá. Citaba
`"age": 36, "current_capital": 40000.0, "monthly_savings": 4500.0` como datos versionados, pero esa
cita se tomó del **archivo de trabajo local**, no de los commits. Auditado commit por commit
(2026-08-14), lo que el historial contiene es:

| Está en el historial | NO está en el historial |
|---|---|
| `default_profile: "Agresivo"` | `age`, `retirement_age` |
| 3 tickers seguidos (INTU, BTC-USD, GOOGL) | `current_capital`, `monthly_savings` |
| la lista de universo preseleccionada | `risk_tolerance`, `primary_goal_type`, `onboarded` |

Los siete campos del perfil personal dan **cero commits** en toda la historia
(`git log --all -S"<campo>" -- data/user_preferences.json`): llegaron con el onboarding, que todavía
está sin commitear. El archivo estuvo en sólo dos commits (`e5e6ecd`, `fb14aac`).

Revisado además lo que sí sería grave en un repo público: `.env` nunca estuvo trackeado, ninguna base
de datos tampoco, y las coincidencias con `sk-ant-` son todas placeholders de formularios y del README.
**No hay secretos en el historial.** Los `current_capital`/`monthly_savings` que aparecen en la historia
están en `data/sample_plans/*.json` — los tres planes de ejemplo ficticios de Fase H.4, cuyos números
(45/250k, 32/400k, 50/120k) no se parecen al perfil real.

**Decisión (2026-08-14): no se reescribe el historial.** El repo es público
(`github.com/fcalvino/retirement-advisor`) y está todo pusheado, pero reescribir 92 commits rompe
cualquier clon y fork, invalida todos los SHA y obliga a un push forzado — desproporcionado frente a
exponer un perfil de riesgo y tres tickers. Lo que importaba era que el perfil real nunca llegue a un
commit, y eso ya está cubierto por `.gitignore` + el test de regresión.

**Lección de método:** esta auditoría se escribió leyendo el working tree y afirmó sobre el historial
sin verificarlo. Es el mismo error que D4 denuncia en los tests — dar por probado lo que no se midió.
Un documento de auditoría que exagera pierde autoridad igual que uno que omite.

---

## Tier 1 — No se puede confiar ni reproducir  ·  ✅ CERRADO 2026-08-14

### D4. Los tests validan consistencia consigo mismos, no corrección financiera ✅ CORREGIDO

`tests/test_decumulation.py:64`

```python
def test_matches_legacy_apply_withdrawals(self):
    ...
    np.testing.assert_array_equal(legacy, new)   # ← congela el bug D1
```

El patrón se repite en toda la suite: "byte-idéntico", "sin regresiones" aparece 10 veces en
`CONTEXT.md` como criterio de calidad. Es un buen *guard* de regresión y un mal *criterio de
validación*: 610 tests pasan y el error de D1 es del 60%.

**Fix determinante — tests-oráculo:** una capa de tests que compare el motor contra una
implementación de referencia lenta, escrita de forma independiente (loop secuencial de contabilidad
de capital, ~30 líneas), sobre paths deterministas. Si el vectorizado y el oráculo divergen, falla.
Es el único tipo de test que habría atrapado D1 y D2.

Cobertura ausente en módulos críticos: `portfolio/tracker.py` (posiciones reales),
`scripts/run_scheduler.py` (automatización desatendida), `analysis/backtesting.py`,
`alerts/reporter.py`, `data/crypto_fetcher.py`.

**Resuelto:** `tests/test_engine_oracles.py` (64 casos) + 106 tests en los cinco módulos sin
cobertura. El test citado arriba ya no congela nada: quedó reencuadrado como guard de
*duplicación* (los dos entry points comparten kernel), no como definición de corrección.
Los oráculos encontraron un off-by-one real en el CAGR del backtest y una fuente de
no-reproducibilidad en la propia suite. Ver "Estado: Tier 1 CERRADO" arriba.

---

### D5. Dependencias sin pinear — resultados financieros no reproducibles ✅ CORREGIDO

`requirements.txt` usa solo `>=`, sin lockfile:

```
yfinance>=0.2.40   pandas>=2.0.0   numpy>=1.24.0   scipy>=1.11.0
```

Dos corridas del mismo plan en fechas distintas pueden dar números distintos por un bump de
`scipy` (SLSQP), `numpy` (RNG/percentiles) o `yfinance` (forma de los datos). En una herramienta
que produce cifras sobre las que alguien decide su retiro, eso es inaceptable.

**Fix:** `requirements.lock` con hashes (`pip-compile`/`uv`), y sellar la versión de las libs
numéricas dentro de `PlanSnapshot` para que un plan guardado sea auditable.

**Resuelto:** lock con 2.132 líneas hash-pineadas + `PlanSnapshot.lib_versions` +
`data/env_provenance.py`. Descubrió además que el piso real de Python ya era 3.12, no 3.10.

---

### D6. Datos personales reales versionados en git ✅ CORREGIDO

> ⚠️ **El texto de esta sección es incorrecto en su premisa central** y se conserva sólo como
> registro. El archivo estaba trackeado (eso era cierto y se corrigió), pero **las versiones
> commiteadas no contienen el perfil financiero**: el JSON de abajo se copió del archivo de trabajo
> local, no de git. Ver "Corrección: este hallazgo estaba sobredimensionado" más arriba.

`data/user_preferences.json` está **trackeado** y contiene el perfil financiero real:

```json
"age": 36, "current_capital": 40000.0, "monthly_savings": 4500.0,
"risk_tolerance": "agresiva", "primary_goal_type": "fire"
```

Además aparece modificado en cada sesión, ensuciando el working tree de forma permanente
(está entre los 26 archivos con cambios sin commitear).

**Fix:** `git rm --cached data/user_preferences.json`, agregarlo a `.gitignore` (junto a los otros
runtime JSON que **sí** están ignorados — `retirement_plans.json`, `plan_health_history.json`,
`personal_book_convictions.json`: la excepción es claramente un descuido), y versionar solo un
`user_preferences.example.json`. Si el repo va a ser público, además reescribir historia.

**Resuelto** salvo la reescritura de historial, que es destructiva y queda a decisión del owner.

---

## Tier 2 — Freno a la velocidad

### D7. La documentación obligatoria está desactualizada y es enorme 🟡

`docs/PROMPT_INSTRUCTIONS.md` obliga a leer `CONTEXT.md` (45,9 KB) antes de cualquier cambio.
Ese archivo afirma cosas que el código contradice:

| CONTEXT.md dice | Realidad en el código |
|---|---|
| "dashboard/app.py (Streamlit, **7 páginas**)" | 18 páginas |
| "No hay retry automático" | `data/fetcher.py:25` `_fetch_with_retry` |
| "yfinance única fuente; no hay fallback real" | `data/data_sources.py`: SEC EDGAR, FRED, FMP |
| "Suite: 512 / 524 pasando" | 610 |

`docs/` pesa **3,8 MB en 17 archivos**, con tres auditorías previas solapadas
(`AUDIT_DATA_QUALITY`, `AUDIT_REASONING_QUALITY`, `auditoria_project_owner`). Documentación que
miente es peor que no tener documentación: cada asistente de IA que la lee arranca con un modelo
mental equivocado — precisamente el fallo que `PROMPT_INSTRUCTIONS.md` intenta prevenir.

**Fix:** recortar `CONTEXT.md` a lo que no se deduce del código (decisiones y por qué), generar el
resto con `scripts/refresh_context.py` en un pre-commit hook, y archivar las auditorías cerradas.

---

### D8. God-files en UI y config 🟡

| Archivo | LOC |
|---|---:|
| `dashboard/pages/7_Simulaciones.py` | 2.116 |
| `dashboard/shared.py` | 1.490 (54 funciones) |
| `dashboard/pages/5_Optimizer.py` | 1.464 |
| `config.py` | 1.287 (56 dataclasses, 33 singletons) |

`dashboard/pages/` suma 8.797 LOC sin un solo test, y 58 números mágicos inline que violan la
regla "nunca hardcodear en config.py". `shared.py` es un módulo-basurero: helpers cacheados,
render, config de IA y orquestación conviven sin frontera.

**Fix:** partir `shared.py` por responsabilidad (`cache.py` / `render.py` / `ai_config.py`) y bajar
`7_Simulaciones.py` extrayendo cada tab a su módulo. No urgente, pero es lo que hace que cada fase
nueva cueste más que la anterior.

---

### D9. 11 `except Exception` que tragan el error en silencio 🟡

163 `except Exception` en el código propio (13 solo en `shared.py`), de los cuales 11 terminan en
`pass`. En un pipeline financiero, un fallo silencioso en enriquecimiento de datos produce un score
calculado sobre datos incompletos, sin señal para el usuario. Al menos loguear con `logger.warning`
y propagar a `warnings` del resultado.

---

## Plan de acción sugerido

| # | Acción | Esfuerzo | Impacto | Estado |
|---|---|---|---|---|
| 1 | **Moratoria de fases nuevas** hasta cerrar Tier 0 | — | 🔴 | ✅ |
| 2 | D4: tests-oráculo del motor de retiros (antes del fix) | 0,5 día | 🔴 | ✅ |
| 3 | D1 + D2: reescribir retiros como reducción de capital + ruina absorbente | 1 día | 🔴 | ✅ |
| 4 | D6: sacar PII del repo | 15 min | 🟠 | ✅ (historial pendiente) |
| 5 | D5: lockfile + versiones selladas en `PlanSnapshot` | 0,5 día | 🟠 | ✅ |
| 6 | D3: separar μ de las preferencias del perfil | 2–3 días | 🔴 | ✅ (alcance quirúrgico; opción B abierta) |
| 7 | D7: podar y regenerar `CONTEXT.md` | 0,5 día | 🟡 | ⏳ |
| 8 | D8/D9: refactor `shared.py`, excepciones ruidosas | continuo | 🟡 | ⏳ |

El orden importa: **el test-oráculo va antes del fix**, para que el arreglo se demuestre en vez de
afirmarse.

### Decisiones tomadas (2026-08-14)

1. **Historial de git con PII** (D6) → **no se reescribe.** El historial no contiene el perfil
   financiero (auditado commit por commit); reescribir 92 commits de un repo público es
   desproporcionado frente a lo que realmente expone. Ver la corrección en D6.
2. **Piso de Python** (D5) → **se borró la dependencia muerta.** `pandas-ta` y `pyyaml` no se usaban;
   sin ellas `requirements.txt` resuelve en 3.11 y 3.10, y no hizo falta tocar el CI ni bajar nada.

### Lo que queda abierto

3. **D3 opción B** (de Tier 0). El Optimizer y el Monte Carlo siguen sin compartir modelo de retorno.
   El estado real es mejor de lo que sugiere D3: Black-Litterman **ya está activo**, con prior
   Π = δ·Σ·w donde Σ sale de precios históricos reales y w de capitalizaciones reales — o sea que μ ya
   está anclado a la historia por el lado de la covarianza, y el score entra como *view*, que es
   exactamente su rol. Lo que no se reconcilia es el **nivel**: el optimizer lo saca de la prima de
   riesgo implícita, el MC del promedio histórico × 0,80.

   **Próximo paso recomendado: medir antes de reescribir.** Un chequeo que, sobre planes reales,
   compare el retorno anual implícito del bootstrap del MC contra el μ del optimizer. Si la brecha es
   chica, es un problema de etiquetas en la UI; si es grande, ahí sí hay que unificar el nivel. Abarata
   mucho el trabajo que el price matrix ya esté en memoria (`optimizer.py:294`) 24 líneas antes de que
   se calcule μ (`optimizer.py:318`), y que `portfolio/black_litterman.py` ya tenga la maquinaria.
   Reescribir el motor sin saber el tamaño de la brecha sería justo lo contrario de la disciplina que
   D4 vino a instalar.
4. **Tier 2 completo** (D7 documentación, D8 god-files, D9 excepciones mudas). Nada de eso mueve
   números, pero encarece cada fase nueva.

---

## Anexo — repro de D1 y D2

```python
import numpy as np
from portfolio.monte_carlo import MonteCarloSimulator

INIT = 100_000.0

def correct_sequential(path_rel, initial, annual_w, years):
    """Oráculo: el retiro saca capital; el resto sigue al mercado."""
    val = initial
    for yr in range(1, years + 1):
        val *= path_rel[yr * 52] / path_rel[(yr - 1) * 52]
        val = max(0.0, val - annual_w)
    return val

years, wk = 30, 1.08 ** (1 / 52) - 1
path = np.concatenate([[1.0], np.cumprod(np.full(years * 52, 1 + wk))])

motor = MonteCarloSimulator._apply_withdrawals(
    np.array([path]).copy(), INIT, 4000.0, years * 52)[0, -1] * INIT

print(correct_sequential(path, INIT, 4000.0, years))  # 553_133
print(motor)                                          # 886_266  -> +60,2%
```

---

## Lo que está bien (no tocar)

- Separación motor/UI: **cero imports de Streamlit** fuera de `dashboard/`. Es lo que hace baratos
  los fixes de Tier 0.
- `config.py` como fuente de verdad única, sin números mágicos en el motor.
- CI real: ruff + matrix 3.11/3.12 + dead-code scan informativo.
- Multi-fuente de datos (`SecEdgarSource`, `FredSource`, `FmpSource`) con timeouts y retry — mejor
  de lo que la documentación admite.
- `portfolio/decumulation.py` y `portfolio/sensitivity.py` como módulos puros e inyectables: el
  diseño es correcto, solo la fórmula de retiro está mal.
