# Auditoría cerrada documentalmente — `fcf_yield` mezcla dos monedas

> **Rol:** `historical-audit`. Cierre documental: **2026-09-11**.
> PRs 0–3 mergeados (#115, #113, #114, #116); PR 4 implementado en esta
> rama y verificado localmente; merge pendiente (ver §5). La regla vigente y sus
> límites quedan en `docs/CONTEXT.md` §8; este archivo conserva la evidencia.
>
> **Módulos:** `analysis/fundamental.py`, `config.py`, `data/snapshot.py`,
> `analysis/prompts.py`, `analysis/strategy.py`,
> `dashboard/pages/2_Stock_Analysis.py`, `scripts/measure_score_impact.py`.

---

## 1. El defecto

`analysis/fundamental.py` (`_score_growth`, antes de #114):

```python
fcf_latest = fcf_series.iloc[0]      # moneda de los estados (financialCurrency)
fcf_yield  = fcf_latest / market_cap * 100   # market_cap: moneda de cotización (USD)
```

Las dos patas de la división vienen en monedas distintas. Para un ADR
latinoamericano el numerador está en pesos/reales/pesos colombianos y el
denominador en dólares, así que el cociente es dimensionalmente incoherente y
numéricamente absurdo. **Antes de #113 el repo no leía `financialCurrency` en
ningún archivo** (verificado 2026-09-10: cero ocurrencias en `.py`, `.md` y `.json`).

Es el mismo mecanismo que N5 arregló **sólo** para el yield de dividendos
(`normalize_dividend_yield_pct` + `THRESHOLDS.dividend_yield_crosscheck_ratio`),
documentado en `CONTEXT.md` §8 — *«Un yield derivado no es inmune a la moneda, y
un None no es un cero»*. Antes de #114, acá **no había techo de
plausibilidad ni campo independiente contra el cual contrastar** (ver §3);
el campo independiente sigue sin existir.

### Consumidores del número

| Sitio | Qué hace con él |
|---|---|
| `analysis/fundamental.py` (`_score_growth`) | **3 de los 20 puntos** de la dimensión Crecimiento |
| `analysis/prompts.py` (`FCF Yield=`) | Va al prompt del LLM como `FCF Yield=…%` |
| `analysis/strategy.py` (rationale) | Rationale de la decisión: *«Attractive FCF yield: 41094.6%»* |
| `dashboard/pages/2_Stock_Analysis.py` | Métrica de la ficha |
| `analysis/track_record.py` (vía `metrics_json`) | Se persiste como evidencia de calibración |

---

## 2. Medición (2026-09-10, yfinance en vivo, `data/universes/latam_adrs.json`)

`raw` es lo que el motor reportaba antes de #114. `conv` es el mismo cociente con
el market cap pasado a la moneda de los estados al spot del día — **no es la
propuesta**, está sólo para mostrar el orden de magnitud del error.

| Ticker | fin_ccy | `fcf_yield` antes | conv. aprox. | pts antes | pts si se convierte | pts con la opción elegida |
|---|---|---|---|---|---|---|
| CIB  | COP | 41 122,51 % | 13,35 % | 3 | 3 | 0 |
| CEPU | ARS | 5 331,86 % | 3,53 % | 3 | 2 | 0 |
| AMX  | MXN | 207,38 % | 12,21 % | 3 | 3 | 0 |
| ABEV | BRL | 42,37 % | 8,29 % | 3 | 3 | 0 |
| ITUB | BRL | 29,90 % | 5,85 % | 3 | 3 | 0 |
| BAP  | PEN | 24,35 % | 7,27 % | 3 | 3 | 0 |
| PBR  | BRL | 11,99 % | 2,35 % | 3 | 2 | 0 |
| VALE | BRL | 4,30 % | 0,84 % | 3 | 1 | 0 |
| BSBR | BRL | 3,04 % | 0,59 % | 2 | 1 | 0 |
| LOMA | ARS | −331,17 % | −0,22 % | 0 | 0 | 0 |
| BSAC | CLP | −494,22 % | −0,53 % | 0 | 0 | 0 |
| SBS  | BRL | −28,75 % | −5,63 % | 0 | 0 | 0 |
| YPF  | ARS | −0,54 % | −0,00 % | 0 | 0 | 0 |
| **KO (control)** | **USD** | **1,40 %** | **1,40 %** | **1** | **1** | **1 (sin cambio)** |

Reproduce la medición del reporte original (CIB 41 094 / CEPU 5 319 / AMX 207,57
/ ABEV 42,23 / ITUB 29,93); las diferencias son el market cap de otro día.

**Precisión sobre el alcance del «≥8 tickers».** Esos 8–9 se mueven en
`latam_adrs.json`. Sobre `config.DEFAULT_TICKERS` (38 símbolos) el único que
puntuaba con un número corrupto es **CEPU**: TEO y EDN traen `marketCap=None`
y el guard `market_cap > 0` ya los excluye, y YPF/LOMA dan negativo, que puntúa
0 en las dos versiones. El bump de `ENGINE_VERSION` se justifica igual —la regla
del repo es *bumpear si y sólo si algún score se mueve* (U3-2 no bumpeó por 0
scores; U4-1/U4-2 y U5-9/10/11 sí)— pero la frase honesta es «1 ticker del
universo por defecto, 9 del universo LATAM ADRs».

**El signo se conserva.** La corrupción es un factor de escala positivo, así que
un FCF negativo sigue dando yield negativo. Por eso los 4 tickers negativos de
la tabla no aportan puntos ni antes ni después: **todo el impacto en el score
está en los 9 positivos**.

---

## 3. Decisión de diseño

### Elegida: **negarse a medir cuando las monedas difieren** (opción 1)

Cuando `info["financialCurrency"]` y `info["currency"]` están ambos presentes y
difieren, `fcf_yield` queda en `None`, la sub-banda suma 0, y el motor deja
constancia del porqué (`logger.warning` + `result.warnings` +
`result.notes["fcf_yield_currency"]`). Es exactamente lo que hace el cross-check
de N5 cuando el yield derivado pierde.

**Por qué, y no las otras dos:**

1. **Precedente directo.** N5 es el mismo mecanismo, sobre los mismos ADRs, y se
   resolvió descartando el número, no convirtiéndolo. El repo repite el mismo
   principio en cuatro lugares distintos de §8: *un dato ausente no es un dato
   bueno*, *un None no es un cero*, *una posición sin precio usable es
   desconocida, no 0 %*, *un benchmark que no se pudo cotizar no es 0 %*.

2. **El techo solo (opción 3) no discrimina — medido.** N5 pudo contrastar
   contra `dividendYield`, el único campo que yfinance calcula por su cuenta. Acá
   **ese campo independiente no existe**: `info["freeCashflow"]` viene en la
   misma moneda de los estados y arrastra idéntica corrupción (AMX: 153 238 798 336
   MXN → 224,46 %; ABEV: 19 859 091 456 BRL → 42,36 %). Sin un contraste, un techo
   es lo único que queda, y cualquier techo que no borre valores legítimos deja
   pasar **ITUB (29,90 %), BAP (24,35 %), PBR (11,99 %), VALE (4,30 %) y BSBR
   (3,04 %)** todavía fabricados. Arregla 4 de 9 y no avisa de los otros 5.

3. **Convertir (opción 2) exige una cotización que el repo decidió no fabricar.**
   El FCF es un **flujo del ejercicio** (`as_of = 2025-12-31` en los 20 tickers
   medidos) y el market cap es de **hoy**: hacerlo bien no es aplicar el spot,
   es traer la FX de la fecha del estado. Se puede (`get_history("BRL=X", …)`,
   reusando el precedente de `data/fetcher.py:usd_ars_quote`), pero:
   - **No hay oráculo posible.** `CONTEXT.md` §5 exige una implementación de
     referencia *derivada de la definición*. «Yield» tiene definición; «a qué
     cotización, de qué fecha, sobre cuál de las dos patas» no la tiene, y el
     repo no tiene fuente independiente contra la cual validar el resultado.
   - **5 de los 14 afectados son argentinos.** `ARS=X` es el oficial, y §8 ya
     fija la posición del proyecto sobre eso (*«Una tasa por defecto no es una
     cotización»*, `ArFxConfig.rate_source`, `brecha_omitted_reason`). Un flujo
     nominal en ARS acumulado durante un año de inflación de tres dígitos no
     tiene *una* cotización correcta; convertirlo al spot afirma que sí.
   - **Es un superconjunto de la opción 1.** Si la FX falla, el fallback es
     devolver `None` — o sea, hay que construir la opción 1 igual. Elegirla
     ahora no cierra ninguna puerta.

**Costo aceptado, dicho de frente:** 5 tickers (ITUB, ABEV, AMX, CIB, BAP)
tienen un FCF yield convertido que superaría `fcf_yield_excellent = 4,0` y
cobrarían sus 3 puntos con derecho. La opción 1 se los saca. Se prefiere no
medir a medir con una regla que el proyecto no puede validar; si más adelante
aparece una serie FX período-matcheada **y** una fuente contra la cual
contrastar el resultado, la opción 2 se construye encima de esta sin deshacer
nada.

### Segunda línea: techo de plausibilidad para el feed que no dice la moneda

`financialCurrency` puede faltar (info cacheada vieja, `data/snapshot.py`). En
ese caso el guard no puede disparar, así que se agrega
`FundamentalThresholds.max_plausible_fcf_yield_pct = 50.0` como backstop de
error grueso. **No es una calibración y no discrimina**: caza CIB, CEPU y AMX y
deja pasar ITUB y BAP. Existe sólo para que un 41 000 % no llegue nunca a una
pantalla, no para decidir qué es correcto.

### `p_ffo`: **entra en alcance** (PR 3)

`analysis/fundamental.py` (`_populate_prescoring_metrics`) — `market_cap / ffo`,
con `ffo` de `compute_ffo(income_stmt, cashflow)`: misma familia exacta (una pata
de mercado, una de estados).

- **Exposición medida hoy: cero.** Todos los REITs de los universos versionados
  son estadounidenses (`O`: `financialCurrency=USD`). El único nombre LatAm de
  Real Estate alcanzable, `IRS`, tiene `industry="Real Estate Services"`, así que
  `classify_company` devuelve `OPERATING` y nunca recibe `p_ffo`. La medición inicial no obtuvo `info` de `IRCP` y lo describió como
  deslistado; la corrida de PR 3 del 2026-09-11 sí respondió para ese símbolo.
  Esa respuesta no prueba que sea un REIT extranjero puntuable: se conserva
  como corrección del antecedente, no como validación de su clasificación.
- **Entra igual**, por tres razones: la dirección es la peligrosa —las bandas de
  `p_ffo` son **cotas superiores**, así que un REIT extranjero se ve *barato* y
  cobra los **8 de 25** puntos de Valuación, que es la banda más grande del
  módulo—; `UserPreferences.custom_tickers` deja al usuario agregar cualquier
  símbolo; y una vez que existe el helper, cablearlo cuesta cinco líneas y un
  test. Dejarlo afuera sería repetir lo que hizo N5 al arreglar sólo el
  dividendo, que es la razón por la que existe este documento.
- **Sin backstop numérico.** Acá la corrupción *achica* el múltiplo; un piso de
  plausibilidad borraría REITs legítimamente baratos. Si falta
  `financialCurrency`, `p_ffo` no tiene defensa — límite aceptado, igual que §6.2.

---

## 4. Fuera de alcance (hallazgo nuevo, item aparte)

**`priceToBook` también cruza monedas, por un mecanismo distinto.** yfinance
publica `bookValue` en `financialCurrency` para algunos tickers y en USD para
otros, y calcula su propio `priceToBook` sin corregirlo. Medido sobre 20 ADRs
LatAm:

| Ticker | precio | `bookValue` | `priceToBook` del feed |
|---|---|---|---|
| CIB  | 103,12 USD | 44 394,48 (COP) | **0,0023** |
| BSBR | 5,88 USD | 13,34 (BRL) | **0,4407** |

Los otros 18 son coherentes. Ambos caen en `pb <= T.pb_excellent (1.5)` →
**+5 puntos gratis** en Valuación. `trailingEps` y `trailingPE` **sí** están
bien (CIB: 10,04 / 10,27×), así que el valor de Graham y el margen de seguridad
no están afectados.

No se arregla acá: el mecanismo es otro (el campo derivado del feed, no nuestra
división), el gate de `financialCurrency` no sirve porque la conversión es
inconsistente ticker a ticker, y necesita investigación y un oráculo independientes. Comparar `precio /
bookValue` contra el `priceToBook` publicado no valida por sí solo la moneda
si ambos comparten el dato contaminado. **Queda como item separado
`PB-CURRENCY` de `docs/BACKLOG.md`, sin solución validada.**

---

## 5. Secuencia de PRs

Todos contra `origin/main`, chicos, cada uno mergeable y verde por su cuenta.
Aceptación común: **`make check`** (ruff corre antes que pytest; `pytest` solo
no alcanza). `TZ=UTC make test` **no** aplica: ningún PR de esta serie toca
fechas, horas ni «por día».

| PR | Alcance | Mueve scores | Criterio de aceptación | Estado |
|----|---------|---|---|---|
| **0** | **Instrumentación.** `measure_symbol()` en `scripts/measure_score_impact.py` agrega `fcf_yield`, `p_ffo`, `financial_currency` y `currency` a la fila; `render_comparison` lista las métricas que cambian aunque el score no se mueva. Retroactivo: #114 se mergeó sin él. | No | `--baseline` y `--compare` sobre el mismo árbol reportan 0 movidos; `make check` verde | ✅ #115 |
| **1** | **Helper puro + su oráculo, sin cablear.** `financial_currency_mismatch(info)` junto a `normalize_dividend_yield_pct`. `tests/test_fcf_yield_currency_oracle.py`. | No | El oráculo pasa; 0 scores se mueven; `make check` verde | ✅ #113 |
| **2** | **El fix de `fcf_yield`.** Gate en `_score_growth`, `FundamentalResult.financial_currency`, `notes["fcf_yield_currency"]`, `THRESHOLDS.max_plausible_fcf_yield_pct`, `financialCurrency` en `data/snapshot._INFO_KEYS`, `ENGINE_VERSION` → `2026.09-tier9`. Test de la mitad CAGR en `tests/test_fcf_yield_currency_scoring.py`. | **Sí** | `--compare` muestra **exactamente** los 9 tickers de §2 y ninguno más | ✅ #114 (`--compare` 2026-09-11 contra `051c0b5`, 55 tickers: movidos exactamente los 9, growth −3, BSBR −2; 0 señales cambiadas) |
| **3** | **`p_ffo`.** Mismo helper en `_populate_prescoring_metrics` (ahora recibe `info`), `notes["p_ffo_currency"]`, sin backstop numérico. `financial_currency` pasa a asignarse en `_populate_identity`, no sólo en la rama FCF. Fixture sintética de REIT extranjero en `tests/test_p_ffo_currency.py`. | No (0 en los universos versionados) | `--compare` muestra 0 movidos; la fixture falla sin el guard; `make check` verde | ✅ #116, mergeado 2026-09-11 con CI verde (`--compare` 2026-09-11: 0 movidos y 0 métricas cambiadas sobre 55 tickers → sin bump) |
| **4** | **Superficies + documentación.** Prompt, rationale y ficha dicen *por qué* falta el número en vez de `N/A`. Viñeta en `CONTEXT.md` §8 + fila en §6. Cierre de este documento y cambio de rol en `docs/INDEX.md`. | No | `make check` verde (o alternativa offline autorizada: ruff antes de pytest); catálogo y contrato de etiquetas verdes; UI offline verificada | ✅ Implementado y verificado 2026-09-11; merge pendiente (ruff verde; 3332 tests pasan, 2 skipped; catálogo y contrato verdes; ficha AMX con tooltip comprobada offline) |

### Verificación local de PR 4 (2026-09-11)

Se usó la alternativa offline autorizada a `make check`: Vienna no tenía
`venv` y `setup` instalaría dependencias con red. Con el entorno de yangon
(Python 3.14), `ruff check .` pasó antes de `pytest tests/ -q`: **3332 passed,
2 skipped**, con 12 warnings. El catálogo dio `ok` y el contrato de etiquetas,
**12 passed**. Esto no sustituye la matriz CI 3.11/3.12 pendiente del PR.

Tests nuevos antes del cambio: prompt/rationale **12 failed, 2 passed**;
ficha **2 failed, 2 passed** tras completar las fixtures. Con los cambios,
**18 tests nuevos pasan**; junto con los oráculos FCF/P/FFO, **43 passed**.
La primera suite completa detectó interferencia de un mock del test de UI
con el espía del track record; se corrigió el mock a nivel de clase y la
segunda corrida completa pasó. No se modificó el track record ni el motor.

Se levantó la ficha real de **AMX** con copia aislada de la caché de kyoto,
IA y fuentes secundarias desactivadas y solicitudes externas bloqueadas:
«no medible» y tooltip completo **MXN/USD**, verificados en navegador.
No se consultó yfinance ni se ejecutó `--compare`.

### Precondición histórica de la medición

Al planificar la serie no había caché caliente disponible. El caché vive por
worktree (`config.DB_PATH` cuelga de `BASE_DIR`), y el harness sólo puntúa
símbolos cuyo `info` y cuyo historial 10y/1wk ya están cacheados: sin ambos,
una salida de 0 símbolos no constituye una comparación.

La precondición se resolvió en PR 3 el **2026-09-11**: `full_analysis` sobre
`latam_adrs` ∪ `default` respondió para 58 símbolos y pobló la DB de kyoto;
el harness midió los 55 con ambas entradas necesarias. Esa DB permitió la
comparación contra `051c0b5` (harness PR 0 superpuesto) para PR 2 y la de PR 3,
con los resultados de la tabla. No es una instrucción para consultar la red
otra vez: PR 4 sólo cambia presentación y usa caché aislada para verificar UI.

---

## 6. Riesgos

1. **La mitad CAGR se cae con la del yield.** Las dos viven dentro del mismo
   `if not fcf_series.empty and market_cap > 0`. `fcf_cagr` es un cociente de
   dos flujos de la **misma** moneda: es inmune y tiene que seguir puntuando.
   Cubierto por `test_la_mitad_cagr_sigue_puntuando_pese_al_mismatch`.
2. **`financialCurrency` ausente.** Info cacheada antes de este cambio no cambia
   de forma (se cachea el dict completo de yfinance, así que las entradas nuevas
   ya lo traen sin fetch extra), pero una entrada vieja sin la clave sigue
   puntuando mal hasta que venza el TTL de 24 h. Acotado, y el backstop de §3
   cubre el caso grueso.
3. **El bump de `ENGINE_VERSION` marca stale todos los planes guardados**
   (`dashboard/pages/12_Plan.py`). Es el efecto buscado, pero el usuario lo
   ve como un banner en Mi Plan sin haber tocado nada.
4. **El ranking relativo del Screener se mueve.** Los umbrales absolutos de
   `STRATEGY` no cambian, pero `analysis/ranking.py` calcula percentiles
   **dentro de la corrida**: bajar 9 tickers de `latam_adrs` reordena la tabla y
   puede cambiar la composición de `build_shortlist`. Medirlo con el harness, no
   asumirlo.
5. **Un `None` no degrada la calidad de datos** — verificado: `fcf_yield` no
   está en `_QUALITY_KEY_FIELDS` (`analysis/fundamental.py`), así que no
   dispara `partial`/`poor` ni la política que capea STRONG BUY. Si alguien lo
   agrega a esa tupla después, este fix pasa a tener un segundo efecto.
6. **Durante la serie este archivo entraba en el barrido de
   `tests/test_return_label_contract.py`** por su rol `living-guide` (`LIVING_DOC_ROLES` incluye ese rol y el test deriva
   su lista del catálogo, así que un doc se suma al barrido por estar
   catalogado). El vocabulario de retorno de U1-1/U1-2 aplica acá: los dos
   nombres que el contrato vigila no pueden aparecer sin su calificador. La
   primera redacción de esta misma viñeta los citaba para advertir sobre ellos
   y **rompió el test que estaba describiendo** — si hay que nombrarlos al
   editar un documento vivo, la referencia va por `CONTEXT.md` §8, no en línea.
   El cierre cambia este registro a `historical-audit`; las guías vivas siguen
   sujetas al contrato.
