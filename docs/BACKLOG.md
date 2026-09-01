# Backlog — Retirement Advisor

> **Rol:** `living-guide`. Esto es lo que **falta hacer**. Última repriorización: 2026-09-01.
>
> No confundir con [`ROADMAP.md`](ROADMAP.md), que es el diario de fases **ya
> shipeadas**, ni con [`brainstorm/`](brainstorm/00_INDICE.md), que es ideación sin
> verificar contra el código. El CSV de la auditoría unificada **no** vive en el
> repo: el estado versionado es este archivo (N4).

---

## Por qué existe este archivo

Hasta hoy el trabajo abierto vivía en tres lugares y ninguno era el repo:

| Fuente | Qué tenía | Problema |
|---|---|---|
| `auditoria_remediacion_unificada.csv` | 69 filas, oleadas 0–7 + 8 fuera de alcance | Vivía en `~/Downloads`, fuera de git, sin estado de cierre |
| [`brainstorm/99_PRIORIZACION.md`](brainstorm/99_PRIORIZACION.md) | Quick wins + apuestas de producto | Escrito el 2026-06-20; la mayoría ya se shipeó y nadie lo tachó |
| [`prefilter_contract.md`](prefilter_contract.md) | Contrato del portero | Spec sin código y sin dueño |

Las tres corrientes nunca se cruzaron entre sí, así que no había forma de responder
"¿qué hago ahora?" sin releer las tres. Este archivo es esa respuesta. N4 cerró
eligiendo no importar el CSV: 69 filas de un momento, sin oráculo, no son el
estado. El estado versionado es la tabla de abiertas de abajo.

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

## Estado verificado (2026-09-01)

Las 39 filas de oleadas 3–7 se verificaron contra `main` una por una. La foto del
2026-08-28 decía 30 cerradas / 9 abiertas y **ya no vale**: desde entonces
cerraron U4-3, U4-4, U4-5, U4-1c, U5-7, U5-8, U5-9+10+11, U5-18/b/c/d, U6-1,
U7-3, U3-2, U3-7b, N1, N2 (retry), N5, N6, N6c y N9 — ver [`ROADMAP.md`](ROADMAP.md).
U0-3 y N4 cerraron en docs; N8 cierra el rótulo de la palanca.

Oleadas de origen, reconstruidas desde las filas que siguen acá y las que
ya están en el diario:

| Oleada | Total origen | Cerradas | Abiertas de origen | Leftover vivo |
|---|---|---|---|---|
| 3 — fórmulas con blast radius | 11 | 11 | 0 | U3-1b cerró (pendiente desconocida es None) |
| 4 — flujos del motor | 4 | 4 | 0 | N8 cerró (rótulo; el signo invertido del flujo queda) |
| 5 — scoring y config | 20 | 20 | 0 | **U5-1b** (se partió de U5-1; bloqueado) |
| 6 — dos motores de retorno | 2 | 1 (U6-1) | 0 de defecto | U6-2 es ritual (`ENGINE_VERSION`), no una fila |
| 7 — UX del dashboard | 2 | 1 (U7-1) | 1 (**U7-2**) | U7-3 nació y cerró después |
| **Total origen 3–7** | **39** | **35** | **3** | leftovers aparte |

**Abiertas hoy**, verificadas contra el código — un agente que lea solo este
archivo tiene que nombrar estas y ninguna cerrada:

| id | banda | qué |
|---|---|---|
| **U5-1b** | 3 | Recalibrar Piotroski vs moat. Bloqueado: n=11, todas a 30 días |
| **U7-2** | 5 | Vaciar «Fuente» en Track Record muestra todas las filas |
| **N2b** | 5 | Fallback de fetch a SEC/FMP (el retry ya cerró) |
| **N3** | 5 | No hay `.streamlit/config.toml` |
| **Asistente de gap** | ideación | `monthly_savings_for_probability` existe; falta la superficie |

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
que respondían otra pregunta),
**U4-1c** (el jubilado gasta todos los meses; el efecto no resultó uniformemente
conservador — ver `ROADMAP.md`),
**U5-18c** (una sola política también al escribir: el pending deja de puntuar
las 74 duplicadas que la lectura descartaba — 0 hoy, 74 desde el 28/09),
**U4-5** (la pantalla que pregunta «¿llego?» ya representa que alguien ahorre;
el consejo de «cuánto te falta» ya usaba el ahorro y la simulación no),
**U4-4** (la longevidad se simula en vez de truncarse; el desfase venía de
fábrica en los defaults y costaba 5,90 pp de probabilidad),
**U3-7b** (el moat se rankea con la regla que lo mide; la fila describía una
penalización relativa y lo que había era una miscalibración del 60 %),
**U7-3** (el titular del track record dejó de afirmar lo que n=11 no sostiene),
**U5-18** (un solo reloj; la edad del dato estaba bien y el defecto era el día del
dedup — **20,7 %** de la muestra del track record eran repeticiones: 80 filas de
las 386 escritas con la regla vieja. El 19,4 % que decía antes salía de mezclar
dos bases; re-derivado el 2026-08-30, ver CONTEXT §8) y **U5-18b** (esas 80 se
deduplican en **lectura**, no borrando: `get_scored_rows(collapse_same_day=True)`)
y **U5-18d** (las 53 filas de fixture salen de las tres lecturas por
`source='test_fixture'`, marcadas por id enumerado; el acierto publicado pasó de
**68,2 % a 45,5 %** y la curva de equity de 2,572 a **0,913** contra 1,031 del
benchmark — ver `ROADMAP.md`),
**U5-9 + U5-10 + U5-11** (un número, una casa — y cinco de los ocho literales de
U5-9 ya no existían al abrirla),
**U5-8** (la fila no era cierta: de 143 pagadores sólo 6 quedan debajo del
techo del no-pagador, y **ninguno es una equity de yield bajo** — ver `ROADMAP.md`),
**U3-2** (ATR y ADX con el suavizado de Wilder; 48 de 164 tickers cruzan el gate
de ADX 25 y la fila se quedaba corta en los dos sentidos — ver `ROADMAP.md`),
**U4-3** (el cero no era de la palanca, era del caso base: el laboratorio corría
el plan del usuario **sin sus ahorros** —490.275 contra 1.234.907, 2,52×— y el
tornado presentaba una barra de ancho cero como si fuera una medición. Con eso,
la oleada 4 queda entera — ver `ROADMAP.md`).
**U5-7** (la asignación por edad lee el perfil que el onboarding ya había
preguntado: la fila lo llamaba un docstring desalineado y era **+10 pp de equity**
para todo Agresivo, a toda edad, en dos superficies — y de paso el mismo `advise()`
calificaba la concentración con los topes globales mientras el Optimizer usaba los
del perfil, así que las dos pantallas se contradecían — ver `ROADMAP.md`).
Fuera de las oleadas 3–7,
**U0-2**, **N6c**, **N9**, **U0-3**, **N4**, **N8**, **N7**, **U3-1b**, **U5-19** y **U7-1** también cerraron — ver `ROADMAP.md`.

---

## Bloque 1 — El motor descarta o falsea plata del usuario

**Vacío otra vez.** Los tres P0 originales se cerraron el 2026-08-28 — U4-2 y
U4-1 en `9f05443`, U3-7 después de que U0-2 diera la matriz que lo desbloqueaba.
Cada uno dejó filas nuevas con lo que deliberadamente **no** hizo: **U4-1c** y
**U4-5** en el bloque 4, **U3-7b** también.

**N5** volvió a llenarlo por un día y se cerró el 2026-08-29: el yield de
dividendo de 8 tickers no era el de la empresa, y a tres pagadores reales el
producto les decía que no pagaban. Apareció mientras se decidía si bajar el
techo de yield que unificó U5-10 — y la respuesta fue que el techo era la perilla
equivocada. Ver `ROADMAP.md`.

## Bloque 2 — Números que cambian una decisión de compra

**Vacío.** **U6-1** cerró el 2026-08-29. La fila llamaba «inventado» al proxy del
optimizer; medido sobre 149 equities, resultó ser lo contrario de inventado y
peor de lo que decía a la vez: el score **sí** predice el CAGR (p < 0,0001, con
intercepto −1,43 %, o sea el cero que el motor asume), pero μ no tiene relación
con el único retorno observable que el motor calcula (correlación **+0,025** con
el drift del Monte Carlo) y su R² de 0,116 no sostiene el «7,2 % anual» que se
mostraba. Se cerró por el rótulo: μ queda intacto y el proxy pasa a presentarse
como índice 0–100. **Recalibrar el `0.18` quedó descartado con evidencia**, no
por criterio — ver `ROADMAP.md`.

Queda anotado lo que deliberadamente **no** hizo: `er_absolute_cap` sigue en 0,14
y nadie lo calibró tampoco. Hoy casi no muerde (1 ticker de 150), así que no es
urgente; si alguna vez se sube el span, el cap pasa a ser la restricción que
manda y hay que mirarlo. `tests/test_proxy_ordinal_oracle.py` falla si eso pasa.

## Bloque 3 — Scoring calibrado sobre supuestos falsos

Nada de acá miente sobre lo que calcula; todo está mal calibrado o mal alcanzado.

| id | sev | qué | evidencia |
|---|---|---|---|
| **U5-1b** | P2 | El bonus de Piotroski (0–12) pesa **más que el del moat (0–10)** en un producto de retiro: paga más por «mejoró contra el año pasado» que por «tiene una ventaja durable». Medido sobre 150 equities: 31 % cobra `bonus_strong` y **24 cruzan el umbral de BUY sólo por ese bonus**. U5-1 arregló la etiqueta; recalibrar necesita outcomes que no existen — y son **menos** de los que esta fila creía: de las 22 puntuadas, 11 las escribió la suite (U5-18d), así que la muestra real es **11**, todas a 30 días, y una señal a 1 año no se juzga en 30. Reabrir cuando el track record tenga horizontes largos | `config.py` `PiotroskiConfig` |

---

## Bloque 4 — Higiene, config y fricción

Ninguno mueve un número hoy. Todos son bugs futuros baratos de prevenir, y varios
son el terreno donde ya nacieron los defectos de arriba.

| id | sev | qué | evidencia |
|---|---|---|---|
| **U7-2** | P3 | Vaciar el multiselect "Fuente" muestra **todas** las filas en vez de ninguna | `13_Track_Record.py:86` |

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
| Segunda fuente de datos + reintentos | 🟡 Reconciliación ✅, retry ✅ (N2, `1fa5013`), fallback de fetch ❌ → **N2b** |
| Módulo Doble Moneda | 🟡 Conversión ✅ (U2-5), cotización ✅ (N1, oficial de `ARS=X`, paralelo lo carga el usuario) |
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

- **Verificá la fila antes de creerle.** Una fila es una hipótesis escrita en un
  momento, no un enunciado del defecto: describe lo que alguien vio, con el
  código de ese día. El primer paso de cualquier fila es medir si sigue siendo
  cierta — y en las cinco que se cerraron el 2026-08-29 **ninguna lo era del
  todo**, siempre para el lado que no se esperaba:

  | fila | lo que decía | lo que había |
  |---|---|---|
  | U5-9 | 8 literales sin centralizar | 5 ya estaban cerrados por filas posteriores |
  | U5-18 | 15 `utcnow`, «afecta la edad del dato» | 31 en seis archivos, y la edad **estaba bien calculada** |
  | U6-1 | el proxy es «inventado» | el score sí predice retorno (p<0,0001); el defecto era el formato |
  | U4-1c | el lump de diciembre | también el primer año entero sin gastar, que era la mitad más grande |
  | N5 | *(no existía)* | apareció midiendo si bajar un techo, y el techo era la perilla equivocada |
  | U3-2 | 3 suavizados del ADX, «ATR y ADX más nerviosos» | 4 sitios, uno de ellos **no puede** mover el número; y el ATR no tiene sesgo de signo, sólo el ADX |
  | N6 | 3 filas en un PR, «contaminación futura» | 53 filas en 16 días, y **ya puntuadas**: 11 de los 22 outcomes, +22,7 pp de hit rate inflado |
  | U5-8 | no pagar (+3) puntúa más que un yield bajo (+2) | cierto en la sub-banda, **falso como score**: 0 de 130 equities; los 6 que caen debajo de 3 son 3 de yield alto castigados a propósito y 3 funds sin payout |
  | U4-3 | «sin retiros activos el swing es 0» | la condición no era «sin retiros»: con `constant_pct` **hay** retiros y el swing también da 0, y con aportes la palanca mueve el plan **al revés**. Y el defecto que pesaba no estaba en la fila: el caso base corría sin los ahorros del usuario, 2,52× |
  | N9 | «el buffer se talla del tramo de bonos, la pantalla muestra 5 pp menos que la regla» | la regla se cumple **exacta** — sobre bonos **+ efectivo**: 0 violaciones en 3 perfiles × edades 20–80. El tramo nunca estuvo corto, estaba nombrado por su mitad más grande. Y el `max(…, 0)` que parecía una guarda es un **piso de liquidez** (edad 13 agresivo: regla 3, defensivo 5) |
  | N6c | «escritas cuando algún test usó el `alert_store` real» | ningún test lo hace: los seis sitios usan un doble, y `TEST1` no está en ningún commit de código. Tampoco lo escribió el engine —`alert_snapshots` en 0 lo descarta—, sino `set_cooldown()` directo. Y copiar el bloque de N6 daba **verde falso**: el default de argumento de `alerts/engine.py:137` se queda con el objeto, no con el nombre |

  Empezar a arreglar sin medir produce el arreglo de la fila, no el del defecto.
- Una fila se cierra cuando su **oráculo** pasa, no cuando el código "parece bien".
  Ver CONTEXT §5: *"tests del motor = oráculo, no auto-consistencia"*.
- Al cerrar una fila, moverla a [`ROADMAP.md`](ROADMAP.md) con su commit.
- Si un cambio mueve μ o el Monte Carlo, bumpear `ENGINE_VERSION` (U6-2).
- Este archivo está en la tabla canónica de [`INDEX.md`](INDEX.md); si se renombra,
  correr `scripts/check_doc_catalog.py`.
