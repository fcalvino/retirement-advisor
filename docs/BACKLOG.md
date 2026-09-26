# Backlog — Retirement Advisor

> **Rol:** `living-guide`. Esto es lo que **falta hacer**. Última repriorización: 2026-09-26 (orden acordado: TEST-NET → PIT-1).
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
| 7 — UX del dashboard | 2 | 2 | 0 | U7-3 nació y cerró después |
| **Total origen 3–7** | **39** | **37** | **0** | leftovers aparte |

**Abiertas hoy**, verificadas contra el código — un agente que lea solo este
archivo tiene que nombrar estas y ninguna cerrada:

| id | banda | qué |
|---|---|---|
| **TEST-NET** | 3 | Un oráculo de la suite depende del mercado del día: `test_longevity_horizon_oracle.py` baja SPY/BND/KO/JNJ/PG de la red, en el CI siempre. Ver bloque 4 |
| **U5-1b** | 3 | Recalibrar Piotroski vs moat. Bloqueado: n=11 orgánico a 30 días, o hasta PIT-1/PIT-2 (evidencia sintética a 1 año) |
| **PIT-1** | 2 | Medir los outcomes del backtesting point-in-time vía yfinance y escribir las 8 columnas de `synthetic_recommendation`. Bloquea a U5-1b. Alcance decidido el 2026-09-26 (ver bloque 3); va después de TEST-NET |
| **PIT-2** | 3 | Correr el volumen amplio y exponer la evidencia (F-Score vs retorno forward) en una lectura — hoy no la lee nadie |
| **LLM-4** | 3 | El banco de eval tiene 6 casos de 2026-07-11, corre sólo en replay y no cubre el moat con IA, que mueve el score. Ver bloque 4 |
| **LLM-3** | 4 | Los titulares del feed entran al prompt del Abogado del Diablo como hechos, sin delimitar. Ver bloque 4 |
| **LLM-5** / **LLM-6** | 5 | HTML de la narrativa del plan sin escapar; ninguna llamada registra tokens ni costo. Ver bloque 4 |
| **TR-DEDUP-SOURCE** | 3 | El dedup del track record usa (símbolo, acción, día local) sin `source` (`same_local_day_key`, `_exists_today`, `collapse_same_local_day`): un dictamen del comité que coincide con lo que el Screener ya registró ese día no se escribe, así que `hit_rate_by_source` sólo ve al comité cuando disiente. Pasó en producción: INTU HOLD `complete=True` el 2026-09-22 19:58 UTC sin fila `committee` (la tapó la 1364 `screener`). Decisión abierta: clave por fuente sin reintroducir doble conteo en `summary_stats`/`equity_curve`. **Medido 2026-09-26: 1 de 28 dictámenes completos del comité en el log vigente no dejó fila** — el sesgo existe pero es chico. Visto en la QA de LLM-2. Ver bloque 4 |
| **SA-TR-CAPTION** | 5 | Stock Analysis registra en el track record sin decirlo: un no-USD (7203.T, AIR.PA) se muestra como BUY y no se registra (`admission_skip_reason`), y un dedup tampoco se avisa. El Comité sí lo dice desde LLM-2. Reusar `admission_skip_reason` y el `id` devuelto. Visto en la QA de LLM-2. Ver bloque 4 |
| **UM-GDR** | ? | SMSN.IL (GDR en USD, `financialCurrency=KRW`) muestra «Market Cap: $0.0B» (`marketCap=None`) y el feed trae `priceToBook=0.0039`, el patrón de PB-CURRENCY. Se registró en el track record (fila 1590 en la copia, score 62.2) porque cotiza en USD. Medir si la guarda de UM-1 cubre GDRs antes de fijar banda. Visto en la QA de LLM-2. Ver bloque 4 |

Cerradas: **PORTFOLIO-CCY** (2026-09-26: sin conversión —#154—, la cartera solo admite `PORTFOLIO.base_currency`; `position_currency_skip_reason` es la regla, `Portfolio.add_position` la aplica en el store y devuelve el motivo sin escribir, y Stock Analysis lo muestra en lugar del formulario; moneda desconocida no bloquea, como en LLM-2. La fila se quedaba corta: el tracker también **valúa** en moneda local y suma esos valores como USD en total, pesos y sectores; oráculo `tests/test_portfolio_currency_gate_oracle.py`), **LLM-2** (2026-09-25: el comité guarda `effective_decision_score` como el resto, y una sola compuerta —`admission_skip_reason`, dentro de `log_recommendation`— rechaza para todo escritor el símbolo sin forma de ticker, la moneda distinta del benchmark y el feed vacío; las 4 filas previas se marcan `inadmissible` por id enumerado; oráculo `tests/test_track_record_admission_oracle.py`; la QA en la app encontró que el caption del Comité decía «quedó registrado» aunque el dedup hubiera descartado la fila — corregido en el mismo PR: el caption sale del `id` que devuelve el store y `logged_today` nombra el dedup), **UX-QA** (2026-09-25, QA manual: la pantalla decía menos que el log en cinco lugares — Stock Analysis ahora muestra `AI_FALLBACK.message` cuando la IA falla; el Chat nombra la causa con `AI_FALLBACK.chat_message` y solo sugiere reintentar si es transitoria; una alerta de precio dispara al *cruzar* el objetivo (`<`/`>`), no al crearla en el precio actual; el banner de la Watchlist escapa `\$` (KaTeX, §8); Alertas avisa si el email está incompleto (SMTP-GUARD lo saltea); oráculo `tests/test_ux_qa_fallbacks_oracle.py`), **SMTP-GUARD** (2026-09-25, QA manual: con `SMTP_PASSWORD` vacío el notifier igual hacía login en Gmail —535— aunque `config_validator` ya lo marcaba incompleto; ahora `ALERTS.email_ready` exige remitente, destinatario y contraseña, y el envío se saltea con un warning; oráculo `tests/test_notifier_smtp_guard_oracle.py`), **EMPTY-FEED-SA** (2026-09-25, QA manual en la app: Stock Analysis y Watchlist publicaban un ticker sin datos —inexistente o sin red— como SELL y Stock Analysis lo registraba en el track record; ahora usan `is_empty_feed` como el Screener, y el símbolo manual se valida antes de descargar; oráculo `tests/test_empty_feed_pages_oracle.py`), **LLM-1** (2026-09-25, decisión híbrida: el comité registra la acción limitada por `apply_safety_overlay` y la UI muestra el voto crudo; oráculo `tests/test_committee_overlay_oracle.py`), **Asistente de gap** (`5eed792`, 2026-08-15 — la fila decía "falta la
superficie" sobre una superficie que ya estaba en producción: el consejo de
ahorro en la card "🎯 Resultados por meta" de `7_Simulaciones.py` ya llama a
`monthly_savings_for_probability`/`cached_goal_savings_target` y muestra "Para
llevar {meta} al 80% de probabilidad: $X/mes"; dato stale, no gap real, ver
`docs/CONTEXT.md §9`), **U3-6** (`a5a63d9`), **U3-11** (`00fb551`, oráculo: sin `payoutRatio` ni
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
**U0-2**, **N6c**, **N9**, **U0-3**, **N4**, **N8**, **N7**, **U3-1b**, **U5-19**, **U7-1**, **U7-2**, **N2b**, **N3**, **UM-4**, **UM-2**, **UM-1** y **UM-3** también cerraron — ver `ROADMAP.md`.

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

**PB-CURRENCY — `priceToBook` entre monedas (abierto 2026-09-11, cerrado 2026-09-24 como UM-1).** La
medición del 2026-09-10 registró CIB: precio 103,12 USD, `bookValue` 44.394,48
COP y `priceToBook` 0,0023; BSBR: 5,88 USD, `bookValue` 13,34 BRL y múltiplo
0,4407. Ambos reciben la banda máxima de P/B del scorer. Es un campo derivado
del feed con unidades inconsistentes entre símbolos, distinto de las divisiones
locales corregidas por la serie FCF/P/FFO. **Pendientes:** revalidar el alcance,
identificar evidencia independiente de moneda y definir un oráculo antes de
elegir una corrección; ni conversión ni contraste entre campos del mismo feed
están validados como solución. Evidencia: [`FIX_FCF_YIELD_MONEDA.md`](FIX_FCF_YIELD_MONEDA.md)
§4; límites de la serie cerrada en `CONTEXT.md` §8.

> **2026-09-24:** PB-CURRENCY quedó absorbida por UM-1, que cerró en tier11 (P/B) y
> tier12 (EV/EBITDA). Ver [`ROADMAP.md`](ROADMAP.md) y
> [`AUDIT_UNIDADES_MONEDA_2026-09.md`](AUDIT_UNIDADES_MONEDA_2026-09.md).

**LLM-1 — el comité no pasa por el overlay de seguridad (abierto y cerrado 2026-09-25).** `CommitteeVerdict.to_decision` (`analysis/committee.py:172-200`) arma la decisión con la acción del voto ponderado y `dashboard/views/15_Comite.py:128-138` la registra; la decisión de una sola llamada, en cambio, pasa por `apply_safety_overlay` (`analysis/ai_analyzer.py:246`, `:261`), que es lo que hace cumplir SIGNAL-1 («el LLM puede ser más prudente que la escalera, nunca menos»). Por construcción, con el caso dorado `quality_compounder_buy` y D/E 4,0: el motor da AVOID y el comité, con todos los votos en BUY, registra BUY. En producción pasó dos veces: ADBE BUY del comité (ids 1022 y 1179, 15 y 16/09) contra HOLD del motor por `require_technical_uptrend`. Es el único caso en 25 pares en que el comité fue más optimista que el motor; los otros 23 son más prudentes. **Cerrado con la opción híbrida**: `to_decision(fund, tech)` aplica `apply_safety_overlay`, así que se registra la acción limitada por el motor (paridad con `source=ai`, que ya es post-overlay, y el contrato de `config.py` se cumple), y la página del Comité muestra el voto crudo con un aviso cuando difieren. Se descartó registrar la opinión cruda: violaba el contrato en el track record y volvía incomparable `hit_rate_by_source`. Sin cambio de esquema; las filas 1022 y 1179 quedan como están. Oráculo: `tests/test_committee_overlay_oracle.py`. Evidencia y oráculo: [`AUDIT_LLM_2026-09.md`](AUDIT_LLM_2026-09.md).

**U6-1** cerró el 2026-08-29. La fila llamaba «inventado» al proxy del
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
| **U5-1b** | P2 | El bonus de Piotroski (0–12) pesa **más que el del moat (0–10)** en un producto de retiro: paga más por «mejoró contra el año pasado» que por «tiene una ventaja durable». Medido sobre 150 equities: 31 % cobra `bonus_strong` y **24 cruzan el umbral de BUY sólo por ese bonus**. U5-1 arregló la etiqueta; recalibrar necesita outcomes que no existen — y son **menos** de los que esta fila creía: de las 22 puntuadas, 11 las escribió la suite (U5-18d), así que la muestra real es **11**, todas a 30 días, y una señal a 1 año no se juzga en 30. Reabrir cuando el track record orgánico tenga horizontes largos **o cuando PIT-1/PIT-2 produzcan la evidencia sintética a 1 año**. La recalibración en sí (tocar `PiotroskiConfig.strong_threshold` / `bonus_strong`) es una decisión humana explícita — nunca la hace un loop ni un script. | `config.py` `PiotroskiConfig` |
| **PIT-1** | P2 | El motor de backtesting point-in-time (Idea 2 del diagnóstico 2026-09; PRs #100/#102/#104/#106/#108) genera F-Scores sintéticos a volumen pero **ninguno tiene outcome medido** — las 8 columnas (`price_at_cutoff`, `price_at_horizon`, `return_pct`, `benchmark_return_pct`, `excess_return_pct`, `benchmark_missing`, `outcome_scored_at`, `horizon_date`) existen y no las escribe nada. Falta: para cada `synthetic_recommendation`, traer precio a `as_of` y a +1 año vía yfinance (point-in-time-safe por construcción: precio histórico, no reconstrucción), computar retorno propio y exceso vs un benchmark, escribir las columnas. **Alcance decidido por el usuario (2026-09-26):** un ticker deslistado antes del horizonte queda con outcome `NULL` y marcado —no se descarta, para no sesgar por supervivencia—; el benchmark es SPY total-return, coherente con `TRACK_RECORD`; un corte a menos de 1 año de hoy queda pendiente, no se estima. Va después de TEST-NET, que es su precondición: sin el guard de red sus tests podrían salir a yfinance sin que se note. El schema y el flag `outcome_columns_verified` ya están; `scripts/point_in_time_backtest.py` ya rehúsa si no verifica. **Bloquea a U5-1b** (le da la muestra a 1 año que hoy no existe). | `analysis/synthetic_backtest.py:138-157` (columnas nullable sin escritor), `scripts/point_in_time_backtest.py:220-240` |
| **PIT-2** | banda 3 | Con PIT-1 hecho: correr `scripts/point_in_time_backtest.py` sobre un universo amplio (no solo `DEFAULT_TICKERS`) × una grilla de cortes históricos, y **agregar una lectura** (report o página) que muestre F-Score vs retorno forward / exceso con bandas honestas (t de Student, como `mean_with_band` — no 1.96). Sin esto, PIT-1 deja evidencia en una tabla que **nada lee hoy** (0 consumidores en producción, verificado por grep). La corrida grande en sí es una decisión operativa (rate-limit de yfinance, tiempo de cómputo). | grep: nada fuera de `scripts/point_in_time_backtest.py` y sus tests consume `synthetic_recommendation` |

---

## Bloque 4 — Higiene, config y fricción

U7-1 y U7-2 cerraron: `preset_gap` compara contra la corrida, y Fuente vacío es
ninguna fila. Ver `ROADMAP.md`. Lo que sigue abierto (o se cerró en este bloque):

- **COM-VOTO-VACÍO** — *presentación resuelta (2026-09-21); la medición sigue
  abierta*. Un voto con `stance` válido pero `key_points` y `concerns` en `[]`
  pasa todas las guardas y vota con su peso completo. **Se decidió que siga
  votando**: la prosa no entra al lean (`analysis/committee.py`, `aggregate` sólo
  usa `_STANCE_SCORE` y el peso), así que excluirlo cambiaría números del motor
  para arreglar un problema de presentación — y si el proveedor es tacaño de
  forma sistemática, `quorum_pct` cae a 0 y *todo* dictamen sale `UNAVAILABLE`.
  Lo que sí se arregló: `CommitteeVerdict.unreasoned_roles` y `devil_silent`
  nombran el caso, `aggregate` loguea un warning cuando el Abogado del Diablo
  vota sin fundamentar, y los captions de las dos vistas
  (`consensus_empty_caption` / `dissent_empty_caption` en `dashboard/shared.py`)
  dejaron de decir «sin consenso» cuando lo que pasó es que nadie argumentó.
  **Queda abierto**: medir la frecuencia por proveedor/modelo. Es el único dato
  que movería la decisión hacia excluir el voto del quórum — ahí dejaría de ser
  un apagón global y pasaría a ser un filtro de calidad legítimo. El log de
  `failures=` no lo ve, porque no es un fallo. Repro: bloque C de
  `.context/repro_silent_hold.py`.
- **COM-QUORUM-MEDICION**: nadie midió la frecuencia real de votos malformados,
  que es el único dato que diría si `COMMITTEE.min_quorum_weight_pct = 50.0` es
  demasiado estricto en la práctica. El log ya expone `quorum=` y `failures=` en
  cada línea de `analyze`, y la retención del sink pasó de 7 a 90 días
  (`dashboard/app.py`) justamente para que la evidencia sobreviva — a 7 días se
  tiraba antes de juntarse. **No escribir el agregador todavía**: el cuello de
  botella es volumen de uso, no herramienta (al 2026-09-21 hay 3 corridas
  orgánicas, todas `quorum=100% failures=[]`). Reactivar con ≥200 `analyze`
  orgánicos registrados (al 2026-09-25: 15, todos `quorum=100% failures=[]`, ver
  `AUDIT_LLM_2026-09.md`); ahí, si la tasa de `failures=` no vacío supera ~5 % o
  aparece algún `quorum<50%` no inyectado, se revisa el 50 %. Ojo: la nota de
  `config.py` avisa que la propiedad del 50 % **no se hereda** si cambian los
  `vote_weights` — tocar uno obliga a re-verificar el otro.
- ~~**COM-CACHE-HOLD**~~ — *descartada (2026-09-21)*. La hipótesis era que
  `_verdict_from_dict` deserializa un `action` ausente como `"HOLD"`
  (`analysis/committee.py`, `d.get("action", "HOLD")`). El caso es **inalcanzable**
  por dos barreras independientes: `data/cache.py` borra y devuelve `None` para
  toda entrada más vieja que el TTL (24 h), así que cualquier payload anterior a
  #137 (2026-09-19) ya está expirado y físicamente borrado; y `_cache_key`
  incluye `v{prompt_version}`, o sea que un payload viejo tiene otra clave y ni
  se consulta. Sumado a que `_verdict_to_dict` **siempre** escribe `action` y
  `_set_cached` está gateado por `complete`, ese default es código defensivo
  muerto. No hacía falta ninguna base con caché vieja para confirmarlo.
- ~~**LLM-2**~~ — *cerrada (2026-09-25)*, ver abajo. El hallazgo: el comité escribe en el track record con otra regla que el resto. Guarda `total_score` (`analysis/committee.py:181`) donde los demás guardan `adjusted_score` (`analysis/strategy.py:176-184`): sobre los 25 pares comité–motor del mismo día la brecha mediana es 25 puntos, en la columna que se usa para calibrar umbrales. Tampoco aplica los filtros del Screener (`dashboard/shared.py:1941-1944` moneda, `:2162` feed vacío): AIR.PA y NOVN.SW (ids 1507, 1509) están registradas, igual que ABVE con score 0 (id 1021) y una fila con símbolo `BTC-USD — BITCOIN` (id 1350). Son 5 de los 11 outcomes reales. `dashboard/views/2_Stock_Analysis.py:160-170` tampoco filtra moneda (0 filas no-USD hoy). **Cierre:** (1) escala — `CommitteeVerdict.to_decision` usa `effective_decision_score(fund)`, el mismo número que `decide()`, y con eso el cap de confianza del overlay también se calcula sobre el score correcto; (2) admisión — se eligió **una compuerta en el store** y no filtros en cada llamador: `admission_skip_reason` corre dentro de `log_recommendation`, así que un escritor nuevo no puede olvidarla, y el Screener dejó su filtro de moneda propio (lo pasa como `currency` al store). Stock Analysis queda cubierto sin tocar la página; las alertas pasan la moneda desde el scheduler. Lo que el escritor no sabe (moneda vacía, `fundamental` sin precio) no bloquea, igual que antes. La página del Comité valida el símbolo, no gasta las 5–6 llamadas sobre un feed vacío y dice «No se registra en el Track Record» con el motivo. (3) filas históricas — **decisión del usuario: marcar las 4**, no borrar ni reescribir: `scripts/migrations/mark_inadmissible_rows.py` (dry-run por default) les pone `source='inadmissible'` y `_visible_rows` las oculta como a las fixtures. Las otras 36 filas del comité conservan `total_score`: el `adjusted_score` de ese día no se puede reconstruir, y la fecha del merge separa las escalas. **Queda afuera, a propósito:** el prompt del comité (`committee_prompts.committee_context_block`) sigue mostrándole a los agentes `total_score` como «Score del motor»; cambiarlo mueve votos y exige bump de `prompt_version` y una corrida del banco (LLM-4). Oráculo: `tests/test_track_record_admission_oracle.py` (33 en rojo contra `origin/main`).
- **LLM-3** (2026-09-25): `_headlines_lines` (`analysis/committee_prompts.py:297-307`) mete título y resumen del feed bajo «usalos como hechos» y sin delimitador. Un titular con una instrucción llega textual al prompt del Abogado del Diablo (OWASP LLM01, inyección indirecta). **No medido**: si un modelo la obedece — eso es un eval en vivo, con presupuesto aparte.
- **LLM-4** (2026-09-25): el banco de eval (`analysis/eval_cases.py`, 6 casos) no se tocó desde `5fb471c` (2026-07-11); 29 commits en prompts y capa de IA desde entonces. Corre sólo en replay (`analysis/eval_harness.py:246-251`), no guarda corridas en vivo y cubre 2 de 11 superficies: sin casos para el moat con IA —la única fuera del banco que mueve el score—, cripto, no-USD, voto vacío ni titular adversarial.
- **LLM-5** (2026-09-25, cosmético/seguridad): `dashboard/views/12_Plan.py:826-839` interpola `factor`/`why`/`severity` del modelo en HTML sin escapar. Si Streamlit ejecuta algo en ese contexto no está verificado.
- **LLM-6** (2026-09-25): ninguna llamada registra tokens ni costo (OWASP LLM10); el comité hace 5–6 llamadas por ticker.
- **TR-DEDUP-SOURCE** (2026-09-25, QA de LLM-2): `same_local_day_key` (`analysis/track_record.py`) no incluye `source`, y la usan la escritura (`_exists_today`), el pending y la lectura (`collapse_same_local_day`). En producción, el comité de INTU (HOLD, `complete=True`, 2026-09-22 19:58 UTC según `logs/retirement_advisor.log`) no dejó fila porque el Screener había registrado INTU HOLD a las 19:55 (id 1364). Efecto: las filas `committee` sólo existen cuando el comité disiente del Screener del día, y `hit_rate_by_source` compara una muestra sesgada. Arreglar sólo la escritura no alcanza —la lectura colapsa con la misma clave, y `tests/test_track_record_dedupe_read_oracle.py:273-274` fija ese conteo—, y separar por fuente reintroduce el doble conteo del mismo movimiento de mercado que `summary_stats`/`equity_curve` evitan. **Decisión de diseño abierta** (`AskUserQuestion` antes de codear). El caption del Comité ya no miente sobre esto (LLM-2). **Medición (2026-09-26):** en el log vigente, el comité completó 28 dictámenes distintos (día, símbolo, acción) y a 27 les quedó fila `committee`; solo faltó INTU del 22/09. El sesgo sobre `hit_rate_by_source` existe pero es chico, así que la fila queda detrás de TEST-NET y PIT-1; reabrir si el comité pasa a correr a diario junto al Screener. Diseño provisional si se encara: la clave incluye `source` al escribir y en la lectura por fuente, y no la incluye en `summary_stats`/`equity_curve` (así no vuelve el doble conteo); SA-TR-CAPTION va en el mismo PR porque `logged_today` cambia de sentido.
- **SA-TR-CAPTION** (2026-09-25, QA de LLM-2, cosmético): `dashboard/views/2_Stock_Analysis.py` llama a `log_recommendation` sin mostrar el resultado. Con 7203.T y AIR.PA la página muestra BUY y el log dice «not logged — cotiza en JPY/EUR»; la pantalla no contradice a la base (nunca afirma registrar), pero calla lo que el Comité sí dice. Arreglo: el mismo caption del Comité, con `admission_skip_reason`, el `id` devuelto y `logged_today`.
- **UM-GDR** (2026-09-25, QA de LLM-2): SMSN.IL cotiza en USD (GDR) con estados en KRW. `get_info` trae `marketCap=None` —la ficha lo muestra como «$0.0B», un cero que no es dato— y `priceToBook=0.0039`, el mismo patrón de unidades cruzadas que PB-CURRENCY. Pasa la compuerta de LLM-2 (la moneda de cotización es la del benchmark) y quedó registrado con score 62.2. **No medido**: si la guarda de UM-1 (`financial_currency_mismatch`) neutraliza esos campos en el score; medir sobre los GDR del feed antes de fijar la banda.
- ~~**PORTFOLIO-CCY**~~ — *cerrada (2026-09-26)*, ver arriba y `ROADMAP.md`. «➕ Agregar al
  Portfolio» guardaba el precio local de 7203.T como «Costo promedio (USD)», y el tracker
  suma costo **y valor de mercado** de cada posición como USD. Se cerró con una compuerta, no
  con conversión: admitir no-USD sigue siendo el trabajo de #154.
- **TEST-CACHE** (abierto y cerrado 2026-09-24): los tests aislaban el track record
  y las alertas pero **no la caché de datos**, que vive en la misma base
  (`config.DB_PATH`, tabla `cache`). Una corrida completa borró 4 filas (AZN.L,
  SHEL.L) y reescribió 7 historiales en la caché del usuario; así «cambió» la señal
  de BND en #160. **Cerrado**: `config.DB_PATH` se lee de
  `RETIREMENT_ADVISOR_DB_PATH` y `tests/conftest.py` la fija a un temporal antes del
  primer import del proyecto. Se midió contra redirigir el singleton al importar
  (estilo N6) y contra una fixture por test, sobre copias idénticas de la base: las
  tres dejan 0 filas tocadas, pero solo la variable alcanza a los 4 subprocesos de
  `test_direct_page_entry`, que heredan el entorno y seguían abriendo la caché y el
  `portfolio.json` reales (la suite lo leía 5 veces). Oráculo en rojo antes del
  cambio: `tests/test_data_cache_isolation_oracle.py`.
- **TEST-NET** (2026-09-24): con la caché aislada, 8 tests siguen saliendo a la red
  (yfinance vía `curl_cffi`, SEC vía `requests`). Cortándola en `Session.request`
  fallan 6, todos de `tests/test_longevity_horizon_oracle.py`: el oráculo corre
  Monte Carlo sobre la historia real de SPY/BND/KO/JNJ/PG, así que su input es el
  mercado del día —en el CI, que arranca con la caché vacía, siempre—. Los otros 7
  pasan sin red: es tráfico de más, no dependencia. Arreglo propuesto: historia
  sintética sembrada en ese oráculo, parchar los 7, y recién después un guard
  autouse a nivel `curl_cffi`/`requests` (**inferencia**: `pytest-socket` no vería
  yfinance, porque `curl_cffi` abre sus sockets en C — la sonda de sockets de
  Python vio 2 tests, la de HTTP 8).
- **PIT-TOOLS (prerrequisito para reabrir ReAct en el comité)**: `get_news` y
  `MacroRagStore.retrieve` no aceptan `as_of` — leen el reloj real, así que una
  tool que los exponga filtraría datos posteriores a la fecha de análisis y
  haría irreproducibles los casos dorados de `eval_harness`. Sin eso, ReAct
  queda descartado (se eligió inyección determinista, 2026-09-19).
- **SCR-DIVYIELD-NONE** (2026-09-22, cosmético): en la tabla «🧺 Fondos, ETFs y
  cripto» del Screener, BTC muestra `Div Yield %` = `None` literal. El valor es
  `None` a propósito (`analysis/crypto_analyzer.py`, `result.dividend_yield =
  None`: un cripto no paga renta) y la columna es numérica
  (`SCREENER_COLUMN_SPECS`, `format: "%.2f %%"`). Hipótesis sin verificar: con
  una sola fila todo-`None` la columna queda con dtype `object` y Streamlit
  imprime el literal en vez de una celda vacía. Visto al verificar PR 1–4; el
  diff de `1_Screener.py` era vacío, así que es previo. No presenta una medición
  falsa, por eso va acá y no en el bloque 2.

---

## Bloque 5 — Oleadas nuevas

Trabajo que ninguna de las tres fuentes cubre, o que cambió de costo desde que se
escribió.

**Vacío.** N2b y N3 cerraron: el adapter de yfinance lee la caché, y el tema
Streamlit está declarado. Ver `ROADMAP.md`.

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
| Asistente "¿qué cambio para llegar?" | ✅ `monthly_savings_for_probability` + `cached_goal_savings_target`, card "🎯 Resultados por meta" en `7_Simulaciones.py` (desde `5eed792`, 2026-08-15) |
| Segunda fuente de datos + reintentos | ✅ Reconciliación, retry (N2), adapter cache-only (N2b). Scoring sigue siendo yfinance; SEC/FMP no puntúan |
| Módulo Doble Moneda | 🟡 Conversión ✅ (U2-5), cotización ✅ (N1, oficial de `ARS=X`, paralelo lo carga el usuario) |
| Modo oscuro y accesibilidad | ✅ `.streamlit/config.toml` (N3) — tema dark, contraste AA, telemetry off. Sin toggle en runtime |
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
