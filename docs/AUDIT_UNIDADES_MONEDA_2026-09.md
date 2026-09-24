# Auditoría de unidades y moneda del feed — 2026-09

> Fecha: 2026-09-24 · Base: `origin/main` `f8a9163` · Rol: `historical-audit`
> Alcance: cada campo del feed (yfinance `info` y estados) que entra a un `_score_*`, a un
> bloqueo de seguridad, a Graham o a un prompt. **Solo medición: cero cambios de código.**
> Datos: copia de la base del usuario (caché `info` del 22–23/09, 186 tickers, 90 cotizan
> fuera de USD). La base real no se tocó (SHA-256 idéntico antes y después).

---

## Resumen

La pregunta era si los ratios que el feed entrega precalculados se pueden usar cuando la
empresa cotiza en una moneda y reporta en otra — la clase de defecto que la serie
`fcf_yield`/`p_ffo` (`FIX_FCF_YIELD_MONEDA.md`) cerró para dos métricas y dejó abierta para
el resto (§4 de ese doc, fila PB-CURRENCY del backlog).

La respuesta es más angosta de lo que sugería el conteo inicial, y más rara:

1. **El feed convierte bien en la mayoría de los listados locales.** De 28 equities con
   `financialCurrency ≠ currency` (unidad mayor), 21 tienen P/B dentro de la banda del grupo
   control. Una Nestlé en CHF que reporta en USD no está rota.
2. **Lo que se rompe son unidades por acción**: ADRs de empresas que reportan en otra moneda
   (TSM, HDB, KB), una acción chilena (SQM-B.SN) y una clase de acción (BRK-B, que **no es un
   problema de moneda**: el valor libro es por acción clase A). P/B y EV/EBITDA salen de 4× a
   854× de su valor.
3. **La etiqueta de moneda miente** en PETR4.SA y VALE3.SA: dicen `financialCurrency = BRL`
   y los estados vienen en USD. La guarda de `fcf_yield` confía en la etiqueta, así que no
   dispara y el yield sale **5,1× más bajo** (PETR4: 2,44 % publicado, 12,44 % real).
4. **Impacto medido: 1 señal cambia de 186** (EQNR.OL HOLD→BUY al corregir), 8 scores se
   mueven entre −2 y +5 (TSM ya estaba en el tope de 100). Es un defecto real y silencioso, pero **no** "señales falsas en ~17 %
   del universo global" como anticipó la investigación que motivó esta auditoría — esa
   estimación contaba desajustes de etiqueta, no errores medidos.
5. Dos hallazgos laterales: el bloqueo de seguridad `P/B < 0` es **inalcanzable**, y los
   montos en moneda local se imprimen con `$` en la ficha **y en el prompt de la IA**
   (Toyota llega al LLM como `MARKET CAP: $35821.5B`).

---

## Método

**Oráculo de patas, independiente del feed** (`.context/audit_moneda/oracle.py`, fuera del
repo): para cada equity con `info` + estados cacheados (179), recomputar el ratio desde sus
componentes, en la moneda de los estados:

| Ratio | Recomputado |
|---|---|
| P/B | `marketCap × FX(cotización→estados) / Stockholders Equity` |
| EV/EBITDA | `(marketCap × FX + Total Debt − Cash) / EBITDA` |
| P/E | `marketCap × FX / Net Income Common Stockholders` |

Usa `marketCap` total en vez de valores por acción, así que es inmune al ratio de ADR y a la
clase de acción — justo lo que el feed no es. FX: cierre del 2026-09-23 de 15 pares `XXXYYY=X`
bajados con yfinance directo (sin `data.fetcher`, sin escribir caché).

**Criterio de "roto":** `feed / oráculo` fuera de **[0,5 ; 2]**. El grupo control (sin
desajuste de etiqueta, 145 equities) da mediana 0,987 / p10 0,79 / p90 1,10 en P/B; la banda
absorbe diferencias TTM-vs-FY y de definición sin absorber errores de unidad (el más chico
encontrado es 4,3×). Cada outlier se inspeccionó a mano para atribuir la causa; los que no se
explican por unidad quedan **indeterminados**, no rotos.

**Impacto:** `.context/audit_moneda/impact.py` reusa `scripts/measure_score_impact.py`
(offline: TTL alto en memoria, `attach_in_pipeline=False`, IA solo caché) y corre
`full_analysis` sobre los 186 tickers en tres piernas: feed tal cual / campos rotos
reemplazados por el oráculo / campos rotos → `None` (la política que ya usa `fcf_yield`).
El parche es sobre `analysis.fundamental.get_info` en memoria; ningún otro ticker se movió
(verificado).

---

## Hallazgos

### UM-1 — P/B y EV/EBITDA rotos por unidad por acción (banda 1: cambia una decisión)

| Ticker | Causa | P/B feed → oráculo | EV/EBITDA feed → oráculo | Score base → corregido | Señal |
|---|---|---:|---:|---:|---|
| SQM-B.SN | cotiza CLP, reporta USD | 3.037,6 → 3,56 (854×) | 6.339 → 20,3 (313×) | 73,7 → 74,7 | BUY = |
| TSM | ADR, reporta TWD | 91,4 → 13,7 (6,7×) | 5,16 → 26,1 (0,20×) | 100 → 100 (tope) | STRONG BUY = |
| HDB | ADR, reporta INR | 9,15 → 1,38 (6,6×) | — | 58,0 → 63,0 | HOLD = |
| KB | ADR, reporta KRW | 4,35 → 1,01 (4,3×) | — | 63,8 → 67,8 | HOLD = |
| BRK-B | **clase de acción**: `bookValue` es por acción A | 0,00096 → 1,50 | — | 72,3 → 70,3 | BUY = |
| CEMEXCPO.MX | cotiza MXN, reporta USD | ok | 81,9 → 7,55 (10,8×) | 55,8 → 60,8 | HOLD = |
| EQNR.OL | cotiza NOK, reporta USD | ok | 23,3 → 3,34 (7,0×) | 67,5 → **72,5** | **HOLD → BUY** |
| CIB, BSBR | ADRs, reportan COP/BRL | 0,0023 / 0,44 (medido 2026-09-10) | no cacheados hoy | — | — |

El error va en **las dos direcciones**: BRK-B y CIB cobran la banda máxima de P/B por un
número ~0; SQM, TSM, HDB, KB y EQNR pierden puntos que les corresponden. Con la política
`None`, BRK-B pasa de BUY a HOLD (pierde los 5 puntos regalados sin recuperar los 3 reales).

`bookValue` es el campo culpable de P/B: TSM `bookValue = 4,89` contra un precio de 446,58 USD
por ADR. El `marketCap` total del mismo feed es correcto — por eso el oráculo lo usa.

Evidencia de código: bandas sin guarda en `analysis/fundamental.py:1462-1483`
(`enterpriseToEbitda`, `priceToBook`); la guarda `financial_currency_mismatch`
(`fundamental.py:322`) solo se invoca en `:914` (P/FFO) y `:1602` (FCF yield).

### UM-2 — `financialCurrency` no es confiable como etiqueta (banda 1 candidata)

PETR4.SA y VALE3.SA declaran `financialCurrency = BRL`, pero sus estados vienen en USD
(Petrobras: patrimonio 75,6 B, que es la cifra en dólares). El P/B del feed es correcto; lo
que se rompe es la **métrica que calculamos nosotros**:

| Ticker | FCF (USD) | `marketCap` (BRL) | `fcf_yield` publicado | con FX (BRLUSD 0,196) |
|---|---:|---:|---:|---:|
| PETR4.SA | 16,5 B | 677,6 B | 2,44 % | **12,44 %** |
| VALE3.SA | 2,80 B | 304,8 B | 0,92 % | **4,68 %** |

La guarda no dispara porque compara etiquetas y las etiquetas coinciden. Con la banda
correcta PETR4 sumaría +1 y VALE3 +2; ninguna señal cambia hoy. Lo que importa es la
premisa: **cualquier guarda basada en `financialCurrency` hereda este agujero**, incluida la
que se escriba para UM-1. Detectado solo para estos dos en 179; el oráculo de patas es lo que
lo encuentra (en el grupo control salen con P/B 0,15–0,17 = el FX BRL→USD).

### UM-3 — Montos en moneda local impresos como dólares, también para la IA (banda 4)

90 de 186 tickers cacheados cotizan fuera de USD. Estas superficies anteponen `$` a montos en
la moneda de cotización (o de estados):

- `analysis/prompts.py:516` — `PRECIO: $… | MARKET CAP: $…B` en el prompt de decisión:
  Toyota (7203.T) llega como `$35821.5B`, Fast Retailing con precio `$67680`.
- `analysis/prompts.py:534` — `Graham Value: $…`.
- `dashboard/views/2_Stock_Analysis.py:221` (caption de market cap), `:672` y `:680`
  (valor de Graham y precio).
- `analysis/fundamental.py:1350` (warning de patrimonio negativo, que además está en moneda
  de **estados**) y `analysis/strategy.py:668` (rationale de Graham).

El score no se mueve, pero el LLM razona sobre una capitalización ~150× inflada en yenes
rotulados como dólares. El row builder del Screener (`dashboard/shared.py`) está bien: precio
sin símbolo y columna Moneda.

### UM-4 — El bloqueo de seguridad `P/B < 0` no puede disparar (banda 5)

`analysis/strategy.py:632` bloquea si `pb_ratio < 0`, pero `pb_ratio` sale de
`reported_positive_metric` (`fundamental.py:383-384`), que convierte todo valor ≤ 0 en
`None`. El riesgo real (patrimonio negativo) sí está cubierto, por otro camino:
`negative_equity` + `apply_negative_equity_policy` (P1-3, 2026-08-22). Es código muerto que
aparenta una protección; no cambia ningún número.

---

## Lo que está bien (hipótesis refutadas)

- **Graham usa EPS en la moneda de cotización.** `precio / trailingEps == trailingPE` en 28 de
  28 desajustados (tras la corrección de subunidad `QUOTE_MINOR_UNITS`). El valor de Graham y
  el margen de seguridad —lo que habilita STRONG BUY— no están afectados.
- **La guarda que compara `.upper()` (GBp == GBP) es correcta.** En los `.L`, `marketCap` viene
  en libras (`marketCap / (precio × acciones) = 0,01` porque el precio está en peniques), igual
  que los estados; `fcf_yield` de GSK.L, NG.L y REL.L es consistente.
- **P/E y PEG del feed** no mostraron errores atribuibles a unidad (los dos outliers, BP.L y
  SQM, son de ganancia TTM contra FY — indeterminados, no rotos).
- **Listados locales con desajuste de etiqueta:** 21 de 28 dentro de la banda control. El
  feed convierte.
- **El issue #154 tenía razón a medias:** "sus ratios no dependen de la moneda" vale para la
  mayoría, no para ADRs de reportantes extranjeros ni para los casos de UM-1/UM-2.

## Indeterminados (no se atribuyen a unidad)

EV/EBITDA fuera de banda en el grupo control — VALE3.SA, PETR4.SA (UM-2), APD, NFLX, 8058.T,
INFY, RWE.DE — y P/E de MRK, SAN.PA, FEMSAUBD.MX: compatibles con diferencias de definición de
EBITDA o TTM vs FY. INFY tiene P/B 2,0× el oráculo sin desajuste de moneda. No se proponen
filas para estos sin más evidencia.

---

## Oráculos propuestos (para cuando se arregle)

| Fila | Oráculo |
|---|---|
| UM-1 | Test con fixtures de `info` + estados reales de TSM, SQM-B.SN, BRK-B y EQNR.OL: el P/B y EV/EBITDA que puntúa el motor están dentro de [0,5 ; 2] del recomputado desde `marketCap` y los estados. Escrito primero, en rojo. |
| UM-2 | Fixture PETR4.SA: una guarda que no dependa solo de la etiqueta (p. ej. contrastar el patrimonio de estados contra `bookValue × acciones` en ambas monedas) marca el FCF yield como no medible o lo convierte; nunca 2,44 %. |
| UM-3 | El prompt de decisión para un ticker JPY no contiene `$` delante de un monto; nombra la moneda. |
| UM-4 | Borrar la rama muerta o documentar que la cubre `apply_negative_equity_policy`; test de que patrimonio negativo sigue capando a HOLD. |

La corrección en sí (convertir, anular o reconstruir desde `marketCap`) es decisión aparte:
anular a `None` castiga a BRK-B (BUY→HOLD) porque le saca los puntos regalados sin darle los
reales; reconstruir desde `marketCap` + estados + FX es lo que el oráculo ya hace, pero agrega
una dependencia de FX al scoring.

---

## Repro

```bash
# desde la raíz del worktree, con una COPIA de la base en data/db/
sqlite3 "file:$HOME/retirement_advisor/data/db/retirement_advisor.db?mode=ro" \
  ".backup data/db/retirement_advisor.db"
~/retirement_advisor/venv/bin/python3 .context/audit_moneda/oracle.py   # FX + oráculo
~/retirement_advisor/venv/bin/python3 .context/audit_moneda/impact.py   # 3 piernas
```

Los scripts viven en `.context/` (gitignoreado) porque son de medición única; las cifras de
este documento salen de `oracle.json` e `impact.json` de esa corrida.

## Limitaciones

- La caché tiene el universo cacheado el 22–23/09; CIB, BSBR, YPF y los demás ADRs de
  `latam_adrs` no estaban, así que UM-1 los cita de la medición del 2026-09-10.
- Sin `.env` en el worktree, la capa IA del moat corrió sin su caché de proveedor; las tres
  piernas corren igual, así que los deltas son atribuibles solo a los campos parcheados.
- FX de un solo día; los ratios rotos están a 4×–854×, lejos de cualquier ruido cambiario.
