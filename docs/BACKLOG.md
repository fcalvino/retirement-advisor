# Backlog — Retirement Advisor

> **Rol:** `living-guide`. Esto es lo que **falta hacer**. Última repriorización: 2026-08-28.
>
> No confundir con [`ROADMAP.md`](ROADMAP.md), que es el diario de fases **ya
> shipeadas**, ni con [`brainstorm/`](brainstorm/00_INDICE.md), que es ideación sin
> verificar contra el código.

---

## Por qué existe este archivo

Hasta hoy el trabajo abierto vivía en tres lugares y ninguno era el repo:

| Fuente | Qué tenía | Problema |
|---|---|---|
| `auditoria_remediacion_unificada.csv` | 69 filas, oleadas 0–7 + 8 fuera de alcance | Vivía en `~/Downloads`, fuera de git, sin estado de cierre |
| [`brainstorm/99_PRIORIZACION.md`](brainstorm/99_PRIORIZACION.md) | Quick wins + apuestas de producto | Escrito el 2026-06-20; la mayoría ya se shipeó y nadie lo tachó |
| [`prefilter_contract.md`](prefilter_contract.md) | Contrato del portero | Spec sin código y sin dueño |

Las tres corrientes nunca se cruzaron entre sí, así que no había forma de responder
"¿qué hago ahora?" sin releer las tres. Este archivo es esa respuesta.

---

## El criterio de orden

No todo defecto pesa igual. El orden de abajo sale de aplicar estas cinco bandas,
en este orden, y dentro de cada banda ordenar por **cuántas superficies leen el
número**:

1. **Rompe una decisión.** El motor produce una cifra falsa que cambia qué compra,
   vende o ahorra el usuario — y no lo avisa. Un cero silencioso es peor que un
   error ruidoso.
2. **Bloquea a otro.** Precondición declarada de algo de la banda 1.
3. **Corrompe la evidencia.** No cambia una decisión de hoy, pero ensucia el
   track record, que es el único juez que tiene el motor sobre sí mismo.
4. **Promete lo que no calcula.** La etiqueta dice más que la fórmula. Casi todo
   cerrado en la oleada 1; lo que queda es residual.
5. **Higiene y fricción.** Config duplicada, literales, UX incómoda. No mueve un
   número hoy; cada uno es un bug futuro barato de prevenir.

**La regla que resuelve los empates:** un número que el usuario ve y usa para
decidir, y que está mal, pesa más que una pantalla incómoda. Siempre.

---

## Estado verificado (2026-08-28)

Las 39 filas de oleadas 3–7 de la auditoría se verificaron contra `main` una por
una, con oráculos empíricos donde el hallazgo lo permitía.

| Oleada | Total | Cerradas | Abiertas |
|---|---|---|---|
| 3 — fórmulas con blast radius | 11 | 10 | 1 |
| 4 — flujos del motor | 4 | 2 | 2 |
| 5 — scoring y config | 20 | 13 | 7 |
| 6 — dos motores de retorno | 2 | 0 | 2 |
| 7 — UX del dashboard | 2 | 0 | 2 |
| **Total** | **39** | **25** | **14** |

Cerradas: **U3-6** (`a5a63d9`), **U3-11** (`00fb551`, oráculo: sin `payoutRatio` ni
FFO el score es 4.0 exacto), **U5-20** (`d86f8e9`), **U4-2** y **U4-1** (`9f05443`,
un PR por la nota U4-1b; oráculos en `tests/test_cash_flow_oracle.py`), **U3-7**
(escala del moat por modo; oráculo empírico sobre los 164 tickers), **U5-6**
(`4395455`, el foso deja de pagarse dos veces en μ), **U3-1** (historial corto es
`None`, no "debajo de la tendencia"), **U3-3 + U3-4 + U3-5** (`c68769d`, la cadena
de Graham: `g` por acción, V con `g = 0`, y la tasa `Y` nombrada como proxy),
**U3-8** (`28bab01`, un solo ROIC, con la tasa del país que grava),
**U3-9 + U3-10** (`c2e7f6b`, cada ratio anclado en un solo año fiscal),
**U5-15** (`070d2a8`, el horizonte anual dura un año y su banda escala con él),
**U5-13** (`ca72aa6`, el gap de capital en dólares de un solo año),
**U5-5** (`ae13e50`, un ratio que un banco no puede tener no le falta),
**U5-4** (`ecb704c`, un REIT juzgado con bandas de REIT),
**U5-12** (`41ab106`, la curva del tracker cubre lo que se tuvo y el retorno dice
qué es), **U5-14** (`4dc8fc9`, la deriva es desconocida si el plan no se pudo
cotizar entero), **U5-16** (`e7bf84e`, el descuento ARS se aplica por país, no
por lista), **U5-1** (el F-Score dice que mide cambio interanual; el bonus queda
como fila de calibración, ver abajo), **U5-17** (`3472dc4`, el bootstrap alcanza la
observación más reciente), **U5-2 + U5-3** (`d1aba8f`, dos señales del Piotroski
que respondían otra pregunta).
Fuera de las oleadas 3–7,
**U0-2** también cerró — ver `ROADMAP.md`.

---

## Bloque 1 — El motor descarta o falsea plata del usuario

**Vacío.** Los tres P0 se cerraron el 2026-08-28 — U4-2 y U4-1 en `9f05443`,
U3-7 después de que U0-2 diera la matriz que lo desbloqueaba. Ver `ROADMAP.md`.
Cada uno dejó filas nuevas con lo que deliberadamente **no** hizo: **U4-1c** y
**U4-5** en el bloque 4, **U3-7b** también.

## Bloque 2 — Números que cambian una decisión de compra

### U6-1 · El proxy de retorno del optimizer no está anclado a nada `P1`

**U5-6 cerró** (`4395455`): el moat ya no se paga dos veces en μ. Queda la mitad
estructural, que es la que da nombre a la fila: hay **dos motores de retorno** —
el proxy del optimizer (`score/100 × 0.18` más el dividendo, acotado por
`er_absolute_cap`) y el del Monte Carlo (historia semanal + haircut del 20 %) — y
el primero no está atado al segundo ni a nada observable. Que el score de un
ticker sea 80 no dice que su **atractivo estimado (proxy del optimizer)** sea
7,2 %; lo dice la constante `0.18`, que nadie calibró contra nada.

Hoy los dos números conviven en la misma pantalla con nombres distintos (U1-1/U1-2
dejó «Atractivo estimado (proxy)» para uno y «retorno histórico» para el otro), así
que al menos no se confunden. Pero ordenar una cartera con un proxy inventado sigue
siendo ordenarla con un número inventado.

**Hacer:** anclar el proxy a algo verificable — el retorno histórico que ya calcula
el MC, o una calibración explícita de `0.18` contra el universo — o declararlo
ordinal y dejar de expresarlo en puntos porcentuales.
**Cuidado:** blast radius sobre toda la asignación, no sólo sobre el ordenamiento.

---

## Bloque 3 — Scoring calibrado sobre supuestos falsos

Nada de acá miente sobre lo que calcula; todo está mal calibrado o mal alcanzado.

| id | sev | qué | evidencia |
|---|---|---|---|
| **U5-1b** | P2 | El bonus de Piotroski (0–12) pesa **más que el del moat (0–10)** en un producto de retiro: paga más por «mejoró contra el año pasado» que por «tiene una ventaja durable». Medido sobre 150 equities: 31 % cobra `bonus_strong` y **24 cruzan el umbral de BUY sólo por ese bonus**. U5-1 arregló la etiqueta; recalibrar necesita outcomes que no existen (22 filas, todas a 30 días, y una señal a 1 año no se juzga en 30). Reabrir cuando el track record tenga horizontes largos | `config.py` `PiotroskiConfig` |
| **U5-8** | P2 | No pagar dividendo (+3) puntúa más que pagar un yield bajo (+2) | `_score_dividends` |

---

## Bloque 4 — Higiene, config y fricción

Ninguno mueve un número hoy. Todos son bugs futuros baratos de prevenir, y varios
son el terreno donde ya nacieron los defectos de arriba.

| id | sev | qué | evidencia |
|---|---|---|---|
| **U3-7b** | P2 | El Optimizer sigue normalizando el moat por `/20` para rankear (`:483`, `:509`), así que una fila sin IA —cuyo techo real es 12— queda sistemáticamente peor rankeada por no haber sido enriquecida, no por la empresa. U3-7 arregló las **etiquetas**; esto es el mismo supuesto de escala única en los **pesos**. Se dejó afuera de U3-7 a propósito; `:625`, el tercer `/20`, desapareció con U5-6 al quitarse el término de moat de μ | `optimizer.py:483,509` |
| **U5-9** | P2 | Literales que deberían estar en config, movidos 1:1 y byte-idénticos: `0.18`/`0.05` de μ, `0.21`/`0.79` del tax, FCF 4/2, quick 1.5/1.0, F6 1.02, MaxDD 1.5, payout 80 | `optimizer.py:623,625`, `fundamental.py:882`, `moat.py:626` |
| **U5-10** | P2 | La tasa libre de riesgo vive en tres lugares con dos valores: `config.py:402` (0.045), `:694` (0.045), `:491` (`risk_free_proxy_pct = 4.0`). Más `BLOCK_SIZE` muerto, dos techos de yield y dos caps de sector | |
| **U5-18** | P2 | 15 `utcnow` vivos entre relojes UTC-naive y local-naive: `data/cache.py` (6), `analysis/track_record.py` (8), `track_record_scorer.py` (1). Afecta la edad del dato y el dedup por día | |
| **U3-1b** | P3 | `sma200_slope_pct` tiene la misma forma que tenía `above_sma200` antes de U3-1: es `float = 0.0`, así que "no hay ventana suficiente" y "la media está plana" son el mismo valor. Consecuencia acotada pero real: el gate D15 de `technical.py:266` (`or result.sma200_slope_pct >= 0`) concede el bonus por sobreventa a un ticker cuya pendiente nadie pudo medir. Se dejó afuera de U3-1 para no mezclar dos campos en un PR de tipos | `technical.py:35,266` |
| **U3-2** | P2 | ATR y ADX usan `ewm(span=period)` en vez del suavizado de Wilder `alpha=1/period`. El RSI (`:300`) ya está bien — son los únicos dos que quedaron | `technical.py:329,353-358` |
| **U4-1c** | P2 | U4-1 mensualizó los aportes; los **retiros** siguen anuales a propósito (`guardrails` *es* una revisión anual). Un jubilado gasta todos los meses, así que el lump de diciembre sobrestima el pozo que sobrevive. Decidir anual, pagar en doceavos — `MONTE_CARLO.withdrawal_periods_per_year` ya existe. Mueve `prob_sustain_real_pct` y `expected_depletion_year` de todo plan de retiro guardado → otro bump de `ENGINE_VERSION` | `decumulation.py`, `config.py` |
| **U4-5** | P2 | La pestaña principal de Simulaciones **no puede** simular un aporte: su único widget de flujo es "Retiro anual" con `min_value=0`, así que la pantalla que contesta "¿llego?" no representa que alguien ahorre. El motor acepta `annual_contribution` desde tier2 y `contribution_inputs` ya resuelve el número; falta la palanca | `7_Simulaciones.py:195-204` |
| **U4-3** | P2 | La palanca "Inflación" del tornado bumpea `withdrawal_growth_rate`; sin retiros activos el swing es exactamente 0 y el rótulo queda igual | `sensitivity.py:105-110` |
| **U4-4** | P2 | La longevidad solo trunca: `cap_week = min(longevity*52, n_cols-1)`. Vivir 5 años más no puede alargar la simulación | `decumulation.py:300` |
| **U5-7** | P2 | El docstring promete "Conservative: age / Aggressive: age − 10"; la función no toma perfil y siempre devuelve `min(age, 80)` | `config.py:360-362` |
| **U5-11** | P2 | `weight_quality_moat_tailwind = 45` y sus tres hermanos nunca se leen: solo se interpolan en un f-string | `config.py:1266` → `personal_sizer.py:648` |
| **U5-19** | P3 | Black-Litterman documenta Π como "CAPM equilibrium **excess** returns" mientras las views `q` son retornos totales | `black_litterman.py:83` |
| **U7-1** | P3 | `preset_gap` se evalúa en cada rerun contra los widgets actuales, así que sacar un valor a mano dispara "ese filtro no se aplicó", que es falso | `1_Screener.py:663` |
| **U7-2** | P3 | Vaciar el multiselect "Fuente" muestra **todas** las filas en vez de ninguna | `13_Track_Record.py:86` |
| **U0-3** | P3 | CONTEXT §8 (a)(b) describen como abiertos dos defectos ya cerrados | |

---

## Bloque 5 — Oleadas nuevas

Trabajo que ninguna de las tres fuentes cubre, o que cambió de costo desde que se
escribió.

### N2b · El fallback de fetch a una segunda fuente

**El retry cerró** (`1fa5013`): los cuatro fetchers reintentan y la política vive en
`config.FETCH`. Queda la mitad cara, que es la que `X-08` tenía en mente.

`data/data_sources.py` habla con SEC EDGAR y FMP, pero sólo en el camino de
**verificación** (`attach_cross_source_quality`). Usarlas en el de **fetch** exige
decidir a quién creerle cuando difieren — y difieren, que es exactamente la razón
por la que existe la capa de reconciliación. Pedirle dos veces a la misma fuente y
elegir entre dos fuentes distintas son trabajos distintos.

**Hallazgo del PR del retry:** `YFinanceSource` importa `get_financials`
**localmente** y su comentario dice que espera un cache hit porque `analyze` ya lo
trajo. Cuando la caché falla, es una segunda llamada de red redundante — invisible
hasta que el retry la volvió cara (la suite pasó de 23 s a 7m26). Vale arreglarlo
junto con el fallback.

### N3 · Accesibilidad y tema

`99_PRIORIZACION.md` lo lista como quick win y sigue abierto: **no existe
`.streamlit/config.toml`** en el repo, así que no hay tema declarado ni paleta
controlada. Es de los pocos quick wins de la ideación que no se shipeó.

### N4 · El backlog vive en el repo

Este archivo. Falta cerrar el círculo: mover
`auditoria_remediacion_unificada.csv` adentro del repo (o versionar su estado acá),
para que "qué está abierto" no dependa de un archivo en `~/Downloads`. Es lo que
U0-1 pedía a medias.

---

## Qué de la ideación ya no aplica

`brainstorm/99_PRIORIZACION.md` es del 2026-06-20. Verificado contra el código de
hoy, **la mayoría ya se shipeó** y conviene dejarlo dicho para no volver a
priorizarlo:

| Idea del brainstorm | Estado real |
|---|---|
| Reorganizar menú + fusionar pantallas (era la apuesta #1) | ✅ `app.py:361-387` — `st.navigation` por intención, 15 páginas en modo normal, Allocation adentro de Optimizer, Comité bajo Ajustes |
| Sacar herramientas de dev del menú | ✅ `app.py:353-359` — `is_dev_mode()` esconde Eval IA, Calidad de Datos y Macro RAG |
| Mostrar resultados cacheados al entrar (Screener) | ✅ `data/screener_store.py` |
| Filtros y búsqueda arriba de la tabla | ✅ Auditoría Screener item 09 |
| Barra de progreso real | ✅ `1_Screener.py:258` + `format_eta` |
| Acción única destacada ("hoy hacé esto") | ✅ Ola 1, `next_priority_action` |
| Distinguir calculado vs interpretación de IA | ✅ Ola 1, `render_calc_badge`/`render_ai_badge` |
| Preguntas sugeridas clicables en el Chat | ✅ `18_Chat.py:69`, `chat_suggested_questions` |
| Botón "probar con plan de ejemplo" | ✅ Fase H.4 + `app.py:189` |
| Realista vs Conservador visible | ✅ Fase J, `7_Simulaciones.py:416-422` |
| Deriva inteligente cuando cartera y plan no se superponen | ✅ U2-3, `drift_breakdown` sobre la unión |
| Asistente "¿qué cambio para llegar?" | 🟡 El motor existe (`monthly_savings_for_probability`, bisección sobre la probabilidad MC real); falta la superficie que lo presente como asistente |
| Segunda fuente de datos + reintentos | 🟡 Reconciliación ✅, fallback de fetch ❌, retry ❌ → **N2** |
| Módulo Doble Moneda | 🟡 Conversión ✅ (U2-5), cotización ❌ → **N1** |
| Modo oscuro y accesibilidad | ❌ → **N3** |
| Separar el motor de la interfaz (API interna) | ❌ Sigue siendo la apuesta grande sin empezar |
| Unificar ficha + comité + chat | ❌ |
| Chat como puerta de entrada principal | ❌ |
| Módulo de Impuestos | ❌ |
| Versión web multiusuario | ❌ |

---

## Fuera de alcance (sin cambios)

- `X-01` — scorer bancario/utilities completo
- `X-02` — IRR canónico
- `X-03` — completar el método de Guyton-Klinger. Hoy el motor corre una versión
  **simplificada**: dos de las cuatro reglas (preservación de capital y prosperidad).
  No implementa la regla de inflación ni las otras dos — ver CONTEXT §8 (U1-6)
- `X-04` — AAA en vivo
- `X-05` — universo/prefiltro
- `X-06` — reabrir D1/D2/D4/D5/D6
- `X-07` — haircut MC −20 %/+10 % vol (documentado)

**`X-08` (yfinance como fuente única) sale de esta lista** — ver N2.

---

## Cómo mantener este archivo

- Una fila se cierra cuando su **oráculo** pasa, no cuando el código "parece bien".
  Ver CONTEXT §5: *"tests del motor = oráculo, no auto-consistencia"*.
- Al cerrar una fila, moverla a [`ROADMAP.md`](ROADMAP.md) con su commit.
- Si un cambio mueve μ o el Monte Carlo, bumpear `ENGINE_VERSION` (U6-2).
- Este archivo está en la tabla canónica de [`INDEX.md`](INDEX.md); si se renombra,
  correr `scripts/check_doc_catalog.py`.
