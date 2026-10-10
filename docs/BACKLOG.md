# Backlog — Retirement Advisor

> **Rol:** `living-guide`. Esto es lo que **falta hacer**. Qué sigue: [Orden actual](#orden-actual).
> Las filas abiertas: la tabla de «Estado verificado». Lo cerrado y la historia de las
> repriorizaciones: [`ROADMAP.md`](ROADMAP.md).
>
> No confundir con [`ROADMAP.md`](ROADMAP.md), que es el diario de fases **ya
> shipeadas**, ni con [`brainstorm/`](brainstorm/00_INDICE.md), que es ideación sin
> verificar contra el código. El CSV de la auditoría unificada **no** vive en el
> repo: el estado versionado es este archivo (N4).

---

## Orden actual

Decimoctava repriorización (2026-10-10, sobre `a7fe27a`): CACHE-RACE (#251) cerró y su QA en
vivo mostró que el choque, con el código viejo, sacaba un ticker de la cartera. Antes de
cualquier idea nueva, dos PRs chicos. (Decimoséptima, 2026-10-08: cerró el bloque 6 salvo
SCORE-CONTRACCION; tanda de higiene.)

1. ~~**CACHE-RACE-IT**: banda 5. Test de integración: hilos sobre `get_fx_history` con la misma clave vencida y yfinance stubeado; ninguno recibe `None`. Un PR, solo tests.~~
2. ~~**GOAL-PRIORITY-TEXT**: banda 5. Una prioridad en texto se convierte con el mapeo que ratificó el usuario el 2026-10-02. Un PR.~~
3. Repriorización: PORTFOLIO-FX, IDEA-4 o IDEA-5, que decide el usuario.

Esperan disparador: U5-1b, COM-* y TR-RACE. Sin orden: PIT-TOOLS. Espera Fuente:
SCORE-CONTRACCION.

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

## Estado verificado (oleadas 3–7: 2026-09-01; abiertas: 2026-10-02)

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
| 4 — flujos del motor | 4 | 4 | 0 | N8 cerró (rótulo); el signo invertido del flujo queda como **N8b** |
| 5 — scoring y config | 20 | 20 | 0 | **U5-1b** (se partió de U5-1; decidida 2026-09-27: mantener, espera disparador) y **U1-9b** (la fórmula del ratio bajista, que U1-9 dejó «para la oleada 5» sin fila) |
| 6 — dos motores de retorno | 2 | 1 (U6-1) | 0 de defecto | U6-2 es ritual (`ENGINE_VERSION`), no una fila |
| 7 — UX del dashboard | 2 | 2 | 0 | U7-3 nació y cerró después |
| **Total origen 3–7** | **39** | **37** | **0** | leftovers aparte |

**Abiertas hoy**, verificadas contra el código — un agente que lea solo este
archivo tiene que nombrar estas y ninguna cerrada:

| id | banda | qué |
|---|---|---|
| **U5-1b** | 3 | Recalibrar Piotroski vs moat. **Decidida 2026-09-27 (usuario): `bonus_strong` se queda en 12; la fila sigue abierta esperando su disparador.** Medido sobre una copia de la base con `scripts/measure_score_impact.py` en `0d4e764`, 194 tickers cacheados: 12→10 cambia **6** señales, 12→6 cambia **27**, bonus en 0 (también el aceptable) cambia **74**, todas a la baja. La evidencia no alcanza para mover el número: PIT-2 (`docs/PIT2_EVIDENCIA_2026-09.md`) da fuerte − débil +2,89 ± 8,08 pp, inconcluso, y cubre como mucho 33 de los 73 tickers que cobran el bonus (sólo filers 10-K). **Reabrir** si la banda de fuerte − débil de PIT-2 excluye el 0 o si el track record orgánico tiene outcomes a 1 año |
| **PORTFOLIO-FX** | 5 | El Portfolio (`portfolio/tracker.py`) sigue admitiendo sólo `PORTFOLIO.base_currency` (PORTFOLIO-CCY): una posición en yenes no se puede cargar. #154 cerró la conversión en Backtesting, Optimizer, Monte Carlo y Track Record, pero sumar costo y valor de posiciones en otra moneda es otro trabajo (costo en la moneda de compra, valor al tipo de cambio de hoy, P&L separado del cambiario). Anotado el 2026-09-29, **no priorizado** |
| **COM-VOTO-VACÍO** / **COM-QUORUM-MEDICION** | 5 | Mediciones bloqueadas por volumen (18 corridas orgánicas al 2026-09-29, todas con quórum 100 %; 69 líneas `committee[` únicas al 2026-10-02, en buena parte de la suite (ver COM-LOG-TESTS); umbral 200, no cumplido). **Medido el 2026-10-08**: de las 131 líneas `committee[` del log del clon real, 126 son de la suite —todas del 2026-10-03: MSFT 70, ACME, AIR.PA y BTC-USD 7 cada una, `portfolio:t/h/15ee…` 35— y sólo 5 son de una corrida real (BRK-B, CMCSA, MCO, GOOGL, PG): contar desde el 2026-10-08 o excluir esos símbolos; COM-LOG-TESTS (cerrada) evita que vuelva. Ver bloque 4 |
| **IDEA-4 CHAT-CONTEXTUAL** | 5 | Botón «preguntale al asesor» en Plan/Simulaciones que abre el Chat con el contexto de esa pantalla (idea 4 de `DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md`). Sin alcance ni orden. Ver bloque 4 |
| **IDEA-5 IMPUESTOS** | 5 | Módulo de impuestos personales —bienes personales, retención de dividendos, ganancia de capital— (idea 5 de `DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md`; `TaxConfig` sólo modela el impuesto corporativo). Sin alcance ni orden. Ver bloque 4 |
| **PIT-TOOLS** | 5 | Prerrequisito de ReAct (descartado hoy): `get_news` no acepta fecha y un doc macro posterior a `now` cuenta como fresco. Ver bloque 4 |
| **TR-RACE** | 5 | `analysis/track_record.py` (deduplicación por día, upsert de outcomes) y `analysis/macro_rag.py:129` hacen «leer y después insertar», como `DataCache` antes de CACHE-RACE. Sin daño medido el 2026-10-10: 0 duplicados a menos de 5 s en `recommendation_log`; los 74 del 2026-08-28 son anteriores a la deduplicación. **Reabrir** si aparece un duplicado a menos de 5 s o si un escritor del track record pasa a correr en hilos o en dos procesos a la vez. |
| **SCORE-CONTRACCION** | ? | La contracción de la Estimación de cada activo hacia la de su Clase según el score, que el ADR 0001 prevé y EO-4b no hizo (decisión del usuario, 2026-10-06): U6-1 midió que el score ordena el rendimiento (p<0,0001) pero no lo cotiza, así que hoy un peso sería un número sin Fuente. Con la contracción en 0, dos acciones de la misma Clase tienen el mismo μ y el score sólo elige los candidatos. **Reabrir** con una medición point-in-time que dé un peso con su banda (no recalibrar sobre la misma historia que U6-1). Anotado el 2026-10-06, **sin banda** |

Las filas cerradas están en [`ROADMAP.md`](ROADMAP.md): una entrada por fila, con su commit.

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
| **U5-1b** | P2 | El bonus de Piotroski (0–12) pesa **más que el del moat (0–10)** en un producto de retiro: paga más por «mejoró contra el año pasado» que por «tiene una ventaja durable». Medido sobre 150 equities: 31 % cobra `bonus_strong` y **24 cruzan el umbral de BUY sólo por ese bonus**. U5-1 arregló la etiqueta; recalibrar necesita outcomes a 1 año que no existen. Cuando se escribió la fila eran 22 puntuadas y 11 las había escrito la suite (U5-18d), así que la muestra real era **11**, todas a 30 días. Desde SCHED-ONCE el scheduler puntúa, y el 2026-09-28 (copia de la base, clon en `45e06b6`) hay **270** outcomes orgánicos a 30 días (screener 244, ai 15, comité 11), **10** a 90 y **0** a 365; la fila orgánica más vieja es del 2026-06-16, así que el primer outcome a 1 año no llega antes del ~2027-06-16. Una señal a 1 año no se juzga en 30. PIT-1/PIT-2 produjeron la evidencia sintética a 1 año y salió inconclusa, así que **se decidió no mover el número (2026-09-27)**: bajar `bonus_strong` a 10 cambia 6 señales y a 6 cambia 27, todas a la baja, sobre una evidencia que cubre menos de la mitad de los tickers afectados. Reabrir si la banda de fuerte − débil de PIT-2 excluye el 0 o si el track record orgánico tiene horizontes a 1 año. La recalibración en sí (tocar `PiotroskiConfig.strong_threshold` / `bonus_strong`) es una decisión humana explícita — nunca la hace un loop ni un script. | `config.py` `PiotroskiConfig` |
| ~~**PIT-1**~~ | — | *Cerrada (2026-09-26)*, ver `ROADMAP.md`. `analysis/synthetic_outcome.score_due_outcomes` mide el outcome a 1 año con el alcance decidido: deslistado → NULL y `outcome_status='delisted_before_horizon'`; benchmark `TRACK_RECORD.benchmark` sobre el cierre ajustado (total return); un corte cuyo horizonte no pasó queda pendiente. | `analysis/synthetic_outcome.py`, `tests/test_synthetic_outcome_oracle.py` |
| ~~**PIT-2**~~ | — | *Cerrada (2026-09-26)*, ver `ROADMAP.md`. Volumen `default` + `global_quality` × grilla semestral 2012–2025 y lectura en `docs/PIT2_EVIDENCIA_2026-09.md` (inconclusa, sesgo de supervivencia declarado). | `scripts/point_in_time_backtest.py`, `analysis/synthetic_evidence.py`, `scripts/pit_evidence_report.py` |

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
  orgánicos registrados (al 2026-09-25: 15; re-contado el 2026-09-28 sobre
  `~/retirement_advisor/logs/`: **18** —17 por ticker y 1 de cartera—, todos
  `quorum=100% failures=[]` y ningún warning de Abogado del Diablo sin fundamentar;
  ver `AUDIT_LLM_2026-09.md`); ahí, si la tasa de `failures=` no vacío supera ~5 % o
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
- ~~**LLM-3**~~ — *cerrada (2026-09-28)*, ver `ROADMAP.md`. El hallazgo (2026-09-25): `_headlines_lines` (`analysis/committee_prompts.py:297-307`) mete título y resumen del feed bajo «usalos como hechos» y sin delimitador. Un titular con una instrucción llega textual al prompt del Abogado del Diablo (OWASP LLM01, inyección indirecta). **No medido**: si un modelo la obedece — eso es un eval en vivo, con presupuesto aparte.
- ~~**LLM-4**~~ — *cerrada (2026-09-27)*, ver `ROADMAP.md`. La fila decía que no había caso cripto: sí lo había (`crypto_conservative_cap`), y `LiveProvider` existía (página Eval IA y `scripts/run_eval.py`); lo que faltaba era guardar las corridas.
- ~~**EVAL-GROQ-1**~~ — *cerrada (2026-09-29)*, ver `ROADMAP.md`. (2026-09-27, dos corridas en vivo del banco; desde 2026-09-28 en `~/retirement_advisor/data/eval_runs/`, rescatadas de los worktrees): `high_leverage_caution` → SELL con `recommended_max_allocation_conservative` 4 % (`allocation_sane` pide ~0 para un SELL) y `argentina_adr_macro` → REDUCE sin «Argentina» en `macro_factors`, **las dos veces**; `non_usd_quote` no nombró el riesgo cambiario en **una de dos**. Las dos primeras son estables y son del prompt de decisión (`analysis/prompts.py`): el SELL con tope > 0 es una contradicción que la UI muestra; el riesgo país sin `macro_factors` deja al ADR sin su factor estructurado. Ese prompt también es el del Analista Fundamental del comité (`equity_decision_prompt`), así que tocarlo exige subir `COMMITTEE.prompt_version` y volver a correr el banco. **Decisión (usuario, 2026-09-28):** la contradicción SELL con tope > 0 no se arregla en el prompt sino con una guarda determinista en el overlay —un SELL recomienda asignación 0—, que no cambia el prompt y vale para cualquier modelo. El riesgo país sin `macro_factors` y el cambiario de `non_usd_quote` quedan abiertos. **Guarda cerrada 2026-09-28** (SELL y AVOID, ver `ROADMAP.md`); la corrida en vivo de ese día volvió a fallar las dos sub-filas abiertas (sobre las 6 corridas guardadas: 6/6 y 5/6; el conteo anterior, 3/3 y 2/3, sólo miraba las más recientes).
- ~~**MACRO-SEED**~~ — *cerrada (2026-09-27)*, ver `ROADMAP.md`. El hallazgo (2026-09-27, visto midiendo la decisión de #130): la tabla `macro_docs` de la base real tiene sólo los 5 docs de `example_macro_docs` (`analysis/macro_rag.py`, cuyo docstring decía entonces «demo/test… in production these are replaced by real FRED/Fed ingests»), todos con `as_of` 2026-06-16, la fecha en que se sembraron. Nunca se reemplazaron: en `~/retirement_advisor/.env` no había ninguna clave `FRED*`, así que la ingesta real no traía nada (la clave se agregó el 2026-09-27 a las 12:29, y la primera ingesta real, 4/4, fue ese día a las 13:25). `macro_strategist_prompt` (`analysis/committee_prompts.py:233-237`) le dice al Macro «Usá EXCLUSIVAMENTE estos hechos macro fechados», y los 5 dictámenes del comité que había en la caché (Groq `gpt-oss-120b`, 24/09) citan «Fed 4.25‑4.50%», el texto del seed; dos votaron REDUCE (TSM, AIR.PA). El 2026-10-14 el seed cumple `MACRO_RAG.max_age_days = 120` y sale por frescura: desde ahí el RAG queda vacío de verdad y el Macro opina de memoria. **Medido** recalculando esos 5 dictámenes con `aggregate` y el Macro fuera del quórum (el recálculo reproduce primero la caché): **0 de 5 acciones cambian**, el lean se mueve como mucho 0,25 y el quórum queda en 81,8 %. **Decisión (usuario, 2026-09-27): el Macro se abstiene** cuando no hay docs frescos que no sean seed — el seed cuenta como vacío. Cambia el prompt del comité, así que exige subir `COMMITTEE.prompt_version`, más `TZ=UTC make test` (frescura) y `probar-en-vivo`. Se implementó como **abstención**, no como voto fallido (un voto fallido deja el dictamen incompleto, y un dictamen incompleto no se cachea ni se registra): oráculo `tests/test_macro_seed_abstention_oracle.py`. Cierra #130.
- ~~**RAG-TOKENS**~~ — *cerrada (2026-09-27)*, ver `ROADMAP.md`. El hallazgo (visto en la QA de FRED-CPI-NIVEL): `MacroRagStore.retrieve` (`analysis/macro_rag.py`) tokeniza con `_tokens` y puntúa por coincidencia exacta de término, sin stemming ni sinónimos. Reproducido sobre un store en memoria con las 4 series de `MACRO_RAG.fred_series` y el body que escribe `ingest_from_fred`: «tecnología tasas valuación» (la consulta de ejemplo de la página Macro RAG) → **0 docs**; «tasas de interés» → 0; «tasa tecnología» → sólo la Fed; la consulta del comité por ticker (`macro_query_for`: «… tasas inflación macro») → **4 de 4**, porque «macro» aparece en todo body de FRED; la del comité de cartera (hoy `analysis/macro_rag.portfolio_macro_query`, «cartera de retiro {sectores} tasas inflación riesgo país») → **1 de 4**, sólo la inflación. Efecto: el Estratega Macro del dictamen sobre tu cartera razona sin la tasa de la Fed, el bono a 10 años ni el PBI, aunque estén en el RAG y frescos (ese dictamen no se registra en el track record, por eso banda 4 y no 3). No medido: cuánto cambia su voto. Opciones: normalizar tokens (singular/plural, acentos), agregar tags de FRED al texto indexado (`tags` hoy no entra a `MacroDoc.text`), o que los docs de FRED entren siempre —son 4 y `top_k` es 4—. **Decidido (usuario, 2026-09-27): que los docs de FRED frescos y no-seed entren siempre**; se descartan normalizar tokens e indexar `tags`. Exige subir `COMMITTEE.prompt_version`. Hasta el 2026-09-27 la base real no tenía ningún doc de FRED (la clave se agregó después del launchd de ese día, `ingested 0/4`); la ingesta manual de las 13:25 trajo 4/4, así que el defecto ya está en producción. Cierre: `build_context` pone primero los docs fijos (`MACRO_RAG.pinned_doc_key_prefixes = ("fred:",)`) y después hasta `top_k` recuperados entre el resto; los fijos van antes del recorte de `max_context_chars`. Oráculo `tests/test_rag_tokens_oracle.py`.
- ~~**LLM-5**~~ — *cerrada (2026-09-28)*, ver `ROADMAP.md`. `_render_macro_risks` (`dashboard/views/12_Plan.py`) interpolaba `factor`/`why`/`severity` en HTML sin escapar, escritos por el modelo **o por un plan importado**; mismo patrón en los tailwinds del plan, el nombre de meta de Simulaciones y el `company_name` de Stock Analysis.
- ~~**LLM-6**~~ — *cerrada (2026-09-28)*, ver `ROADMAP.md`. Ninguna llamada registraba tokens ni costo (OWASP LLM10); el comité hace 5–6 llamadas por ticker.
- ~~**TR-DEDUP-SOURCE**~~ — *cerrada (2026-09-28)*, ver `ROADMAP.md`. El hallazgo (2026-09-25, QA de LLM-2): `same_local_day_key` no incluía `source` y la usaban la escritura, el pendiente y la lectura; el comité de INTU HOLD (2026-09-22 19:58 UTC, completo) no dejó fila porque el Screener había registrado INTU HOLD a las 19:55 (id 1364), así que las filas `committee` sólo existían cuando el comité disentía. Medido 2026-09-26: 1 de 28 dictámenes sin fila. Se cerró con el diseño provisional que esta fila proponía (decisión del usuario, 2026-09-28): `source` en la clave de la escritura, del pendiente y de la lectura por fuente; sin `source` en `summary_stats`/`equity_curve`/calibración/por acción.
- ~~**SA-TR-CAPTION**~~ — *cerrada (2026-09-28)* en el mismo PR que TR-DEDUP-SOURCE, ver `ROADMAP.md`. Stock Analysis registraba sin decir qué pasó (7203.T y AIR.PA salían BUY y no se registraban); ahora comparte con el Comité `dashboard.shared.track_record_log_caption`.
- ~~**UM-GDR**~~ — *cerrada (2026-09-28)*, ver `ROADMAP.md`. El hallazgo (2026-09-25, QA de LLM-2): SMSN.IL cotiza en USD (GDR) con estados en KRW. `get_info` trae `marketCap=None` —la ficha lo muestra como «$0.0B», un cero que no es dato— y `priceToBook=0.0039`, el mismo patrón de unidades cruzadas que PB-CURRENCY. Pasa la compuerta de LLM-2 (la moneda de cotización es la del benchmark) y quedó registrado con score 62.2. **No medido**: si la guarda de UM-1 (`financial_currency_mismatch`) neutraliza esos campos en el score; medir sobre los GDR del feed antes de fijar la banda. **Medido 2026-09-27 sobre el caché** (194 `info`, copia de la base; SMSN.IL no está, venció): la guarda de P/B es `check_price_to_book` (`analysis/unit_consistency.py`) y deja puntuar el P/B del feed cuando no hay referencia `P/E × ROE` (`UNVERIFIABLE`), **también con monedas distintas**. De 33 tickers con monedas distintas: 28 `ok`, 4 `not_measurable` (no puntúan) y 1 `unverifiable` que puntúa sin verificar —CSL.AX, estados en USD, cotiza en AUD, ROE −15,8 %, P/B 4,13: no es el ×1000 de un GDR—. Ninguno puntúa un P/B absurdo hoy, así que no sube a banda 2. Un GDR con pérdidas o sin `trailingPE` sí lo haría. Pendiente: bajar SMSN.IL (red) y decidir si monedas distintas + sin referencia debe dar `None` (le cambia el score a CSL.AX: medir con `measure_score_impact.py`). Aparte, «Market Cap: $0.0B» con `marketCap=None` es cosmético. **Cierre:** SMSN.IL ya estaba cubierto; se cerró el agujero del caso sin referencia en P/B y en EV/EBITDA, y el «$0.0B» pasó a «n/d».
- ~~**PORTFOLIO-CCY**~~ — *cerrada (2026-09-26)*, ver `ROADMAP.md`. «➕ Agregar al
  Portfolio» guardaba el precio local de 7203.T como «Costo promedio (USD)», y el tracker
  suma costo **y valor de mercado** de cada posición como USD. Se cerró con una compuerta, no
  con conversión: admitir no-USD sigue siendo el trabajo de #154.
- ~~**TEST-CACHE**~~ — *cerrada (2026-09-24)*: los tests aislaban el track record
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
- ~~**TEST-NET**~~ — *cerrada (2026-09-26)*, ver `ROADMAP.md`. La fila
  decía 8 tests y eran 112; la inferencia sobre `pytest-socket` se confirmó
  (`curl_cffi` abre sus sockets en C), por eso el guard parchea su clase además
  del audit hook.
- **PIT-TOOLS (prerrequisito para reabrir ReAct en el comité)**: `get_news`
  (`data/fetcher.py`) no acepta fecha y lee el feed de hoy; `MacroRagStore.retrieve`
  **sí** acepta `now=`, pero sólo lo usa para descartar lo viejo: `_days_old` hace
  `max(0, …)` (`analysis/macro_rag.py`), así que un doc **posterior** a `now` cuenta
  como fresco (re-verificado 2026-09-28; la fila decía «no aceptan `as_of`»). Una
  tool que los exponga filtraría datos posteriores a la fecha de análisis y
  haría irreproducibles los casos dorados de `eval_harness`. Sin eso, ReAct
  queda descartado (se eligió inyección determinista, 2026-09-19).
- ~~**U1-9b**~~ — *cerrada (2026-09-30)*, ver `ROADMAP.md`. El «ratio retorno/vol bajista» de U1-9 dividía por el desvío de las semanas perdedoras alrededor de su propia media (`returns[returns < 0].std()`), que baja cuando la cartera pierde parejo; ahora es un Sortino con MAR = tasa libre de riesgo.
- ~~**N8b**~~ — *cerrada (2026-09-30)*, ver `ROADMAP.md`. La tasa que indexa el gasto también hacía crecer los aportes: Simulaciones proyectaba un ahorro creciente con la inflación y Metas uno fijo, y el tornado mostraba el signo invertido en acumulación.
- ~~**WD-STRATEGY-CONTRIB**~~ — *cerrada (2026-09-30)*, ver `ROADMAP.md`. Con una estrategia de retiro activa el motor proyectaba sin el ahorro y la pantalla no lo decía; ahora lo dice (decisión del usuario: no se suma).
- ~~**WD-PLAN-PDF**~~ — *cerrada (2026-09-30)*, ver `ROADMAP.md`. Simulaciones decía que con estrategia de retiro el ahorro no entra, pero Mi Plan, el PDF, un plan guardado y la narrativa del plan mostraban la misma cifra sin decirlo.
- ~~**WD-PHASED**~~ — *cerrada (2026-10-03)*, ver `ROADMAP.md`. Motor por fases en #219 (`2664c10`) y superficies en el PR 2: un plan cargado corre con su R, longevidad y agotamiento se dicen como edad en Simulaciones, Mi Plan, el PDF y la narrativa, y los planes de ejemplo traen su R. Fila original: «**WD-PHASED — ahorrar hasta el retiro y gastar después** (2026-09-30, sin fila previa; la opción que WD-STRATEGY-CONTRIB dejó afuera). Hoy una estrategia de retiro significa «ya estás retirado»: `apply_withdrawal_strategy` (`portfolio/decumulation.py`) no recibe aportes, y un plan con ahorro y estrategia proyecta sin el ahorro, con aviso en toda superficie (WD-STRATEGY-CONTRIB, WD-PLAN-PDF). El modelo por fases —aportes hasta la edad de retiro del perfil, estrategia desde ahí— es lo que arreglaría el caso en lugar de avisarlo; cambia números del motor, así que exige oráculo y bump de `ENGINE_VERSION`. **Banda 4** (duodécima repriorización, 2026-10-02, decisión del usuario). **Alcance acordado** en la decimotercera (2026-10-02, decisiones del usuario sobre las seis preguntas, verificadas en `2ef25c0` y `c0d959b`): (1) la fase cambia en `UserPreferences.retirement_age` (`data/preferences.py`), que ya da `primary_horizon_years`, sin control nuevo en Simulaciones; (2) se ahorra durante los años hasta el retiro y la estrategia corre después durante la longevidad, **contada desde el retiro** —hoy se cuenta desde hoy y se simulan `max(horizon, longevity)` años (`portfolio/monte_carlo.py`), así que cambian su sentido y su rótulo—; (3) el retiro se calcula sobre el pozo de **cada camino** al retirarse —`apply_withdrawal_strategy` (`portfolio/decumulation.py`) recibe hoy caminos relativos y un `initial_value` fijo, así que cambia su firma—; (4) una edad de retiro menor o igual a la actual es el «ya retirado» de hoy; (5) cambian Simulaciones, Metas, Mi Plan, el PDF y la narrativa, y los avisos de WD-STRATEGY-CONTRIB y WD-PLAN-PDF quedan sólo para el caso sin edad; (6) dos PRs: el motor con oráculo y `ENGINE_VERSION`, después las superficies. Segundo paso del orden, después de SIM-REENTRY-WIDGETS. **PR 1 hecho (2026-10-02, `2026.10-tier17`)**: `run(years_to_retirement=)`, `phased_strategy_events`, `decumulation_metrics(start_week=)` y oráculo en `tests/test_wd_phased_oracle.py`; R ≤ 0 o sin edad es la rama de antes, bit a bit. Dos decisiones del usuario al planearlo: (a) el PR 1 cablea Simulaciones —corrida principal, perfiles y laboratorio, `_saving_years` desde `primary_horizon_years`— y sus dos avisos de ahorro ignorado, porque es la única superficie que corre el motor con estrategia y subir `ENGINE_VERSION` sin cambiar ningún plan guardado mostraría un aviso falso; (b) `fixed_real` está en dólares de hoy, así que el primer retiro trae R años de inflación. El año de agotamiento se sigue contando desde hoy, así que «año X» no miente en ninguna superficie. **Queda para el PR 2**: Mi Plan, Metas, el PDF y la narrativa —que hoy muestran lo que guardó Simulaciones—; los rótulos de longevidad y agotamiento (por ejemplo, como edad); la ayuda de «Retiro anual», que dice «el primer año» y ahora es en dólares de hoy, y su default, que es el 4 % del capital de hoy y no del pozo al retirarse; y si un plan cargado debe correr con su R guardado (`mc_summary.retirement_years`) o con el del perfil actual.»
- ~~**PDF-ZERO-SAVINGS**~~ — *cerrada (2026-10-02)*, ver `ROADMAP.md`. Una corrida con ahorro 0 se describía en el PDF —y en el checklist del plan activo— con el ahorro del perfil. Fila original: «**PDF-ZERO-SAVINGS — el PDF describe el ahorro del perfil en una corrida sin ahorro** (2026-10-02, sin fila previa; duodécima `/decidir-proyecto`, banda 4 por decisión del usuario, segundo paso del orden). Era el «límite conocido» de PLAN-SAVE-PARAMS. `enrich_pdf_mc_params` (`data/product_ux.py`) toma un ahorro ≤ 0 como «sin dato» (`_pos`) y lo completa con el del perfil o el de `UserPreferences`; `assemble_plan_pdf_mc_params` le pasa el 0 de la corrida y `InvestmentPlanReport` (`reports/investment_plan.py`) vuelve a llamar a `enrich_pdf_mc_params` antes de armar «Para compartir», donde `build_annual_action_list` escribe «Meta de aporte anual: $X (según tu perfil/plan)». La probabilidad y la mediana salen de `mc_result` y no se mueven: lo que no cierra es el texto contra la corrida. El plan guardado no tiene el defecto, porque PLAN-LOAD-SAVINGS guarda el ahorro de la corrida cruda. Los tres llamadores del PDF (Mi Plan, Optimizer y Simulaciones) pasan por `enrich_pdf_mc_params`. **Verificado leyendo el código en `2ef25c0`, no en vivo**: el primer paso es reproducirlo con `probar-en-vivo` —perfil con ahorro, corrida con 0, PDF de Mi Plan— y medir si la fila sigue siendo cierta.»
- ~~**REALISTIC-TAIL-CLIP**~~ — *cerrada (2026-10-03)*, ver `ROADMAP.md`. La pasada realista cubre ahora los años que tiene su mercado: con longevidad mayor que el horizonte ya no cobra en la semana del terminal los retiros que no simula. Fila original: «**REALISTIC-TAIL-CLIP — la referencia realista apila los retiros que no simula** (2026-10-02, sin fila previa; visto al implementar WD-PHASED, igual en `origin/main`). `run` sortea la referencia realista sólo para el horizonte (`_simulate_paths(port_hist, n_sims, n_horizon_weeks)`), pero `_wealth_usd` le aplica la estrategia para `n_sim_weeks`, que desde U4-4 llega a la longevidad. `_annual_review_schedule` recorta cada semana a `n_cols - 1`, así que los retiros de los años que ese mercado no tiene caen todos en su última semana, que es la del terminal. Medido sobre una historia sintética (fixed_real 40.000 sobre 1.000.000, horizonte 20): con longevidad 15 y 20 la realista da 438.262 contra 261.947 conservadora; con 30 y 45, **0**. Lo leen «Dos escenarios» de Simulaciones (`7_Simulaciones.py:546`, que lo esconde si es 0 pero muestra uno menor que el conservador) y Mi Plan (`12_Plan.py:291`, sin piso). El PR 1 de WD-PHASED no lo arregla porque el «ya retirado» tenía que quedar bit a bit; el camino por fases descarta los eventos posteriores al final del mercado y no lo tiene. **Banda 1** (decisión del usuario, 2026-10-02: es una cifra falsa visible sin aviso con los defaults), **antes del PR 2** de WD-PHASED, en su propio PR y con su tier.»
- ~~**SIM-REENTRY-WIDGETS**~~ — *cerrada (2026-10-02)*, ver `ROADMAP.md`. Volver a Simulaciones mostraba los defaults de cada widget bajo el caption del perfil, y lo editado se perdía en las ocho claves del sidebar. Fila original: «**SIM-REENTRY-WIDGETS — volver a Simulaciones muestra los defaults bajo el caption del perfil** (2026-10-02, sin fila previa; QA en vivo de PDF-ZERO-SAVINGS, igual en `origin/main`). Con un perfil de 40 años, retiro a los 65 y 150.000: la primera visita a Simulaciones muestra 25 años y 150.000 (PROFILE-SEED-WIDGETS); después de ir a Mi Plan y volver, el caption sigue diciendo «Defaults tomados de Mi Perfil: horizonte ~25 años · capital $150,000» y los widgets muestran 20 años y 100.000, que es lo que corre «Ejecutar». El ahorro sí vuelve al del perfil, porque su `value=` sale de `contribution_inputs(prefs)`. La siembra de PROFILE-SEED-WIDGETS se aplica una vez por diseño (`apply_pending_profile_seed` saca la espera de la sesión), y los dos widgets traen el default escrito a mano —`index=3` del horizonte y `value=100_000` del capital, `7_Simulaciones.py:227` y `:236` en `c0d959b`—: al cambiar de página Streamlit borra las claves de los widgets (ver PLAN-SAVE-PARAMS) y la vuelta las dibuja con esos defaults. **Banda 1** (decimotercera repriorización, 2026-10-02, decisión del usuario), primer paso del orden. Diseño decidido: **conservar lo editado** —claves espejo leídas con `value=`, el patrón de los widgets de estrategia y drags—, así que al volver aparece lo último de la sesión y, si no se tocó, el perfil; un plan cargado sigue ganando. **Sin verificar en vivo**: el mismo borrado alcanzaría a las ocho claves del sidebar (horizonte, capital, ahorro, retiro, suba del ahorro, meta, inflación y simulaciones), no sólo a las dos que nombra el caption; el primer paso es reproducirlo con `probar-en-vivo` y medir cuáles se pierden. Los dos defaults escritos a mano van contra CONTEXT §5 (`MONTE_CARLO.default_horizon_years` existe).»
- ~~**SIM-GAP-PCT**~~ — *cerrada (2026-10-03)*, ver `ROADMAP.md`. «Dos escenarios» rotula `1 − conservadora / realista` (~61 %, no ~158 %); el resto del bloque lo reemplaza EO-4.
- ~~**KATEX-DOLLAR-PLAN**~~ — *cerrada (2026-10-03)*, ver `ROADMAP.md`. `escape_dollars` en cuatro sinks (Simulaciones ×2, el checklist de Mi Plan y el caption de acciones sugeridas de Análisis); sin test estático contra un sink nuevo.
- ~~**GOAL-PRIORITY-TEXT**~~ — *cerrada (2026-10-10)*, ver `ROADMAP.md`. Una meta importada a mano con la prioridad en texto («esencial») llegaba a `goals_list` sin convertir y «Simular» la pasaba por `int()`; ahora `goal_dict_with_defaults` (`portfolio/goals.py`) la convierte con el mapeo que ratificó el usuario el 2026-10-02.
- ~~**PLAN-HORIZON-NONE**~~ → **PLAN-SAVE-PARAMS** — *cerrada (2026-10-01)*, ver `ROADMAP.md`. La fila culpaba a la clave del widget del horizonte; el defecto era que Mi Plan guardaba y exportaba los widgets de Simulaciones y no la corrida: la suba del ahorro, el horizonte, la inflación y la meta del plan guardado no eran los que produjeron sus números, y el PDF perdía el fan chart.
- ~~**PLAN-LOAD-WIDGETS**~~ — *cerrada (2026-10-01)*, ver `ROADMAP.md`. «Cargar plan» llegaba a la sesión pero no al navegador: los widgets de Simulaciones mostraban los defaults y «Ejecutar» los mandaba de vuelta.
- ~~**PROFILE-SEED-WIDGETS**~~ — *cerrada (2026-10-01)*, ver `ROADMAP.md`. La siembra del perfil escribía los widgets de Simulaciones en otra página: el caption decía «Defaults tomados de Mi Perfil» y la pantalla mostraba y corría 20 años y 100.000.
- ~~**PLAN-LOAD-SAVINGS**~~ — *cerrada (2026-10-01)*, ver `ROADMAP.md`. «Cargar plan» corría con el ahorro, el retiro, la estrategia y los drags de la sesión, no con los del plan. Fila original: «**«Cargar plan» no devuelve el ahorro de la corrida** (2026-10-01, sin fila previa; QA en vivo de PLAN-LOAD-WIDGETS). `PlanSnapshot.from_session` guarda en `mc_summary` el horizonte, el capital, la inflación, la suba del ahorro y la meta, pero no `monthly_savings` ni `annual_withdrawal` de la corrida —PLAN-SAVE-PARAMS los agregó a `mc_params` para el PDF, no al plan—; `personal.monthly_savings` es el del perfil al guardar. Así que un plan cargado corre con el ahorro que tenga la sesión: en la QA, 2.000/mes del perfil. Arreglo probable: guardar los dos en `mc_summary` y sembrarlos al cargar con la misma regla de omisión (un plan viejo sin la clave no pisa nada). Banda 1 por decisión del usuario (undécima repriorización, 2026-10-01).»
- ~~**PDF-FAN-PATHS**~~ — *cerrada (2026-10-01)*, ver `ROADMAP.md`. El fan chart del PDF leía `fan_paths` como `{percentil: {año}}` y el motor lo guarda como `{año: {percentil}}`: salía una línea P10 en 0 salvo en los años 5 y 10, sin bandas ni mediana.
- ~~**PLAN-GOALS-KEYS**~~ — *cerrada (2026-10-01)*, ver `ROADMAP.md`. Un plan de ejemplo cargado tiraba «Mis Metas» y, arreglada la página, también «Simular»: faltaban tres claves y la prioridad era texto. Fila original: «**PLAN-GOALS-KEYS — un plan de ejemplo cargado tira la pestaña de metas** (2026-10-01, sin fila previa; QA en vivo de PLAN-SAVE-PARAMS). «Cargar plan» copia `snap.goals` a `goals_list`, y las metas de los tres planes de `data/sample_plans/` sólo tienen `name`, `priority`, `target_amount_today` y `horizon_years`. `_tab_goals_content` (`7_Simulaciones.py:~1658`) lee `g["expected_inflation"]` sin default, así que la pestaña «Mis Metas» se cae con `KeyError` —3 veces en el log de la app sobre `origin/main`, 1 en la rama—. Decisión del usuario (décima repriorización, 2026-10-01): las dos cosas —la página toma el default de `Goal` (`expected_inflation` 3 %) cuando falta la clave y se completan los tres JSON—. Banda 5, siguiente en el orden.»
- ~~**COMPARE-NO-SAVINGS**~~ — *cerrada (2026-09-30)*, ver `ROADMAP.md`. «Comparar Perfiles» corría los perfiles sin el ahorro, los drags ni la estrategia de la pestaña principal: comparaba otro plan.
- ~~**IDEA-3 MENÚ**~~ — *cerrada (2026-09-30)*, ver `ROADMAP.md`. El menú normal tenía 16 entradas; queda en 11 con la agrupación intermedia que eligió el usuario.
- ~~**TEST-ENV-KEY**~~ — *cerrada (2026-09-30)*, ver `ROADMAP.md`. Con el `.env` real, 13 tests de `tests/test_alert_engine.py` pedían la explicación a la IA y el guard de red los cortaba; el CI, sin `.env`, quedaba verde.
- ~~**CONTEXT-DIR-IGNORE**~~ — *cerrada (2026-09-30)*, ver `ROADMAP.md`. `.context/` no estaba en `.gitignore`: las skills `decidir-proyecto` y `probar-en-vivo` ensuciaban `git status` y ruff escaneaba sus scripts.
- **IDEA-4 CHAT-CONTEXTUAL — el Chat abierto desde la pantalla donde surge la pregunta** (2026-09-30, sin fila previa; idea 4 de `DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md`, marcada `[ ]` ahí). Un botón en Plan y Simulaciones que abre el Chat con el contexto de esa pantalla precargado, paso intermedio antes de «chat como puerta de entrada» (❌ en la tabla de ideación). Reusa `ChatAgent` y sus tools deterministas. Sin alcance: antes de implementar, acordar con el usuario qué contexto viaja y desde qué pantallas.
- **IDEA-5 IMPUESTOS — impuestos personales del inversor** (2026-09-30, sin fila previa; idea 5 de `DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md`, marcada `[ ]` ahí; «Módulo de Impuestos» ❌ en la tabla de ideación). `TaxConfig` sólo modela el impuesto corporativo para NOPAT; falta el del usuario: bienes personales, retención de dividendos, ganancia de capital al vender. Sin alcance: es una decisión de producto, y el primer paso es acordar qué impuesto y de qué país.
- ~~**MSI-NET**~~ — *cerrada (2026-09-29)*, ver `ROADMAP.md`. El harness de impacto prometía no salir a la red y salía: `get_financials`/`get_dividends` no cachean una respuesta vacía, así que cada corrida volvía a pedir los estados de los ETFs y cripto.
- ~~**SCR-DIVYIELD-NONE**~~ — *cerrada sin cambio de código (2026-09-29)*, ver `ROADMAP.md`. BTC mostraba `Div Yield %` = «None» en la tabla de fondos; la fila suponía un dtype `object` y medido no lo era: es cómo Streamlit dibuja cualquier nulo.

---

## Bloque 5 — Oleadas nuevas

Trabajo que ninguna de las tres fuentes cubre, o que cambió de costo desde que se
escribió.

**Vacío.** N2b y N3 cerraron: el adapter de yfinance lee la caché, y el tema
Streamlit está declarado. Ver `ROADMAP.md`.

---

## Bloque 6 — Estimación objetiva (ADR 0001)

Sesión de diseño del 2026-10-03 (decisiones del usuario, una por una): la app deja de
ser «conservadora por defecto». La **Estimación** es Objetiva y la prudencia pasa a
ser **Postura** del Perfil. El porqué y lo descartado están en
[`adr/0001-estimacion-objetiva.md`](adr/0001-estimacion-objetiva.md); los términos, en
[`GLOSARIO.md`](GLOSARIO.md). Banda «dec.»: el orden lo fijó el usuario, no las bandas.
Toda etapa que mueva μ o el Monte Carlo sube `ENGINE_VERSION`.

- ~~**EO-0 — Arranque.**~~ *cerrada (2026-10-04)*, ver `ROADMAP.md`. La pestaña de metas
  de Simulaciones deja de escalar la simulación por perfil (`_PLAN_MC_SCALES`, ×0,56 al
  rendimiento con Conservador); el selector se queda para el optimizador por metas y el
  PDF. Salieron de EO-0, verificado en `a175ca8`: la versión en `data/plan_health.py`
  —la alerta de deterioro compara sólo la deriva de precios (`data/plan_context.py`)
  y la P50 de cada registro es la del plan al guardarse— y la del track record, que
  pasa a EO-6. `ENGINE_VERSION` no se sube: ningún plan guardado sale de esa pestaña.
- **EO-1 — El Perfil fuera de la Estimación**, partido en tres PRs (decisión del
  usuario, 2026-10-04):
  - ~~**EO-1a — la Estimación del optimizador.**~~ *cerrada (2026-10-04)*, ver
    `ROADMAP.md`. `ars_risk_discount` rige para todos
    los perfiles (`optimizer.py` lo salteaba en Agresivo) con el 0,85 actual rotulado
    «pendiente de Fuente» —el valor del riesgo país llega en EO-2; el EMBI no está en
    FRED—. El δ de Black-Litterman queda fijo en el del mercado (con Π = δ·Σ·w,
    Conservador era el más optimista) y `ProfileConfig.risk_aversion` se borra.
  - ~~**EO-1b — sin Perfil no hay Postura.**~~ *cerrada (2026-10-04)*, ver
    `ROADMAP.md`. `UserPreferences.profile_chosen` (D1 a): la ponen el onboarding,
    el radio y los presets del Optimizer; un archivo que ya hizo el onboarding
    cuenta como elegido. Sin Perfil (D2 a) el Optimizer, «Optimizar para mis metas»
    y la Asignación piden elegir; las simulaciones corren. El onboarding ya no
    preselecciona la tolerancia, el reset de Settings deja «sin elegir» y
    `OPTIMIZER.default_profile` se borró (no tenía lectores). Sumó un sitio que la
    fila no tenía: «Mis Metas» de `7_Simulaciones.py` arrancaba en Conservador sin
    leer las preferencias —un usuario con Agresivo optimizaba por metas como
    Conservador— y, en vivo, el valor sembrado no llegaba al navegador hasta que
    el selector existiera (el mecanismo de PLAN-LOAD-WIDGETS).
  - ~~**EO-1c — la Exigencia en el Perfil.**~~ *cerrada (2026-10-04)*, ver
    `ROADMAP.md`. `ProfileConfig.exigencia_pct` (90/80/70) y `margin_of_safety_pct`
    (20/10/5), editables en Settings («Tu Postura»). «Mis Metas» juzga y calcula el
    ahorro contra la Exigencia del perfil de su selector; sin perfil, muestra la
    probabilidad sin juicio. `GOAL_CARD.success_target_pct` se borró. La ficha de
    Análisis dice si el margen del activo alcanza para tu perfil. La Señal conserva
    `STRATEGY.min_margin_of_safety_pct` (10 %); su rótulo de «regla del ranking» va
    con EO-6, junto al de «no calibrado».
  - El **Escenario de planificación** pasa a EO-4: necesita los Escenarios.
- **EO-2 — Fuentes**, partido en tres PRs (decisiones del usuario, 2026-10-04): seis
  Clases —acciones EE.UU., desarrolladas ex-EE.UU., emergentes (incluye Argentina),
  bonos EE.UU., REITs y cripto (Fuente declarada ausente)—; la tabla de gestoras la
  investiga la tarea y la valida el usuario antes del merge.
  - ~~**EO-2a — el modelo y las gestoras.**~~ *cerrada (2026-10-04)*, ver `ROADMAP.md`. `analysis/fuentes.py` (Fuente, mediana y
    rango por Clase, antigüedad: aviso a los 12 meses, fuera del central a los 24,
    umbrales en `config.FUENTES`), el mapeo ticker → Clase, el archivo citado
    `data/fuentes/proyecciones.json` y la vista «Supuestos». No alimenta ningún motor.
  - ~~**EO-2b — valuación e historia.**~~ *cerrada (2026-10-05)*, ver `ROADMAP.md`.
    CAPE de Shiller como 1/CAPE + inflación implícita, el Tesoro a 10 años de FRED y la
    Historia más larga por Clase (S&P de Shiller desde 1871; VTMGX, VEIEX, VBMFX, VGSIX),
    con `scripts/refresh_fuentes.py`. Shiller no trae licencia y el repo es público: se
    versionan sólo números derivados. Todas las Fuentes entran al central (decisiones del
    usuario, 2026-10-05).
  - ~~**EO-2c — riesgo país.**~~ *cerrada (2026-10-05)*, ver `ROADMAP.md`. El riesgo país
    de Argentina (EMBI de J.P. Morgan que publica Ámbito, vía ArgentinaDatos) es un dato
    fechado en pb, aparte de las Fuentes, visible en «Supuestos»; no entra al central de
    emergentes. El 0,85 sigue rotulado «pendiente de Fuente»: convertir un spread en un
    multiplicador de score no tiene Fuente (decisiones del usuario, 2026-10-05).
- ~~**EO-3 — Backtest del método.**~~ *cerrada (2026-10-05)*, ver `ROADMAP.md` y la nota
  EO-3 del ADR. ¿El p10–p90 de la Estimación central contiene el rendimiento real a
  10 años el 80 % de las veces? Point-in-time sobre Shiller, 1881–2016, con
  `analysis/backtest_metodo.py` y el informe `data/fuentes/backtest_metodo.json`.
  **Acciones EE.UU. pasa** (9/14 ventanas sin superposición, 64 %, Clopper-Pearson al
  90 % [39 %, 85 %]; superpuestas 73 %); **bonos EE.UU. no pasa** (6/14, 43 %,
  [21 %, 68 %]; superpuestas 41 %): la banda es angosta (4,3 pp de ancho medio) y el
  central queda alto (sesgo −1,05 pp; los fallos caen abajo 3 a 1). Ex-EE.UU.,
  emergentes y REITs: no calibrables (unas 2–3 ventanas independientes).
- **EO-4 — Una Estimación, dos motores**, partido en cuatro PRs (decisión del usuario,
  2026-10-05): EO-4a el Monte Carlo, EO-4b el Optimizer (y la contracción por score),
  EO-4c la UI de Escenarios, EO-4d el riesgo país argentino. Bonos EE.UU. conservan el
  haircut rotulado «no calibrado»; ex-EE.UU., emergentes y REITs, la Estimación rotulada
  «no calibrable»; cripto proyecta 0 % real (el pesimista); un ticker sin Clase conserva
  el haircut y se lo nombra (decisiones del usuario, 2026-10-05).
  - ~~**EO-4a — el Monte Carlo.**~~ *cerrada (2026-10-06)*, ver `ROADMAP.md`. El recentrado
    compuesto va a nivel cartera —el promedio ponderado de las Estimaciones, con la
    volatilidad propia de los activos—: recentrar cada acción en el central del índice
    con su propia volatilidad la proyectaba arriba de la Estimación (QA en vivo: 8,3 %
    sobre 6,7 %).
  - ~~**EO-4b — el Optimizer.**~~ *cerrada (2026-10-06)*, ver `ROADMAP.md`. μ = la
    Estimación de la Clase (bonos y sin Clase, su historia ×0,80), sin contracción por
    score (pasa a SCORE-CONTRACCION) y sin Black-Litterman en ese camino; el número se
    rotula por `return_basis`.
  - **EO-4c en dos PRs** (decisión del usuario, 2026-10-06): EO-4c-1 el motor y el
    Escenario de planificación; EO-4c-2 la UI. Escenarios: cada Clase en su Fuente
    vigente más baja / mediana / más alta; haircut y cripto (0 % real) iguales en los
    tres. Planificación por defecto: Conservador pesimista, Moderado y Agresivo central,
    editable en Settings. La historia reciente deja de ser una proyección.
    ~~EO-4c-1~~ *cerrada (2026-10-06)* y ~~EO-4c-2~~ *cerrada (2026-10-07)*, ver `ROADMAP.md`.
  - ~~**EO-4d — el riesgo país argentino.**~~ *cerrada (2026-10-07)*, ver `ROADMAP.md`. El
    spread completo en pp se resta de la Estimación de la Clase del ADR, con piso en la
    inflación implícita (decisión del usuario, 2026-10-07).

  El diseño original, que las cuatro partes implementan: la Estimación de cada activo se contrae
  hacia la de su Clase según su evidencia (el score, con el peso que respalde U6-1);
  la usan el optimizador y el Monte Carlo, que sigue sorteando de la historia
  recentrada en ella. Cierra la opción B de D3. Se borra `vol_adjustment` /
  `mean_haircut`. La UI muestra Escenarios (pesimista/central/optimista, cada uno con
  su p10–p90) y retira «Realista» y «Conservador»; la historia cruda queda como la
  Fuente «Historia» en el desglose. Planes, semáforo, ahorro y salud usan el
  Escenario de planificación del Perfil; cripto, siempre el pesimista. Reemplaza
  también la pestaña «Comparar perfiles», que hasta acá conserva `_PROFILE_MC_SCALES`
  con su rótulo (decisión del usuario, 2026-10-04). Acá entra también el riesgo país
  de EO-2c a la Estimación de los ADRs argentinos, en términos de rendimiento, y con
  eso se va `OPTIMIZER.ars_risk_discount` del score (decisión del usuario, 2026-10-05).
  Lo que deja EO-3 (2026-10-05): (1) el recentrado del Monte Carlo pasa a ser
  **compuesto** —se fija el promedio de los log-rendimientos, así la mediana rinde la
  Estimación—, el mismo que pasó el backtest; (2) con la evidencia de EO-3 el haircut
  sólo se puede borrar para acciones EE.UU.; para bonos el método no pasó y las
  correcciones medidas tampoco (bloques de 12/24/60 meses: 5, 4 y 2 de 14; toda la
  historia previa como Azar: 6 de 14). **Decide el usuario** qué hacer con bonos antes
  de EO-4 (corregir el método con otro mecanismo de Azar, o dejarlos fuera de la
  Estimación objetiva con el haircut rotulado); probar variantes hasta que una pase
  sobre las mismas 14 ventanas sería ajustar al test.
- **EO-5 — IA calibrada**, en dos PRs (decisión del usuario, 2026-10-08): **EO-5a** el renombre mecánico y `resolve_optimizer_profile` (cerrada 2026-10-08) y **EO-5b** la redacción, el PM con Postura, la clave de caché y el banco en vivo (cerrada 2026-10-08). Fuera «filosofía conservadora» (`committee_prompts.py`),
  «extremadamente… conservador» y «nunca digas esto es genial» (`prompts.py`),
  «asesor… conservador» (`chat_agent.py:138`); la instrucción es decir lo que la
  evidencia sostiene, con su incertidumbre. El Abogado del Diablo se queda (método,
  no sesgo) si la agregación es simétrica. `recommended_max_allocation_conservative`
  → `recommended_max_allocation` en prompts, parser, `STRATEGY` y el banco de eval;
  el PM recibe la Postura y el Perfil entra a la clave de caché del comité. Un
  oráculo barre los prompts como hoy barre los nombres de proveedor. Incluye
  `resolve_optimizer_profile` (`ai_analyzer.py`), que sin nombre de perfil sigue
  cayendo en Conservador: EO-1b lo dejó para acá (desde EO-1b el Optimizer no
  produce un resultado sin perfil, así que el fallback ya no se alcanza desde ahí).
- **EO-6 — Señales**, en dos PRs (decisión del usuario, 2026-10-07): **EO-6a** el sello de versión del método de señales en el track record (sin mover ninguna señal) y **EO-6b** los cambios de señales, partido a su vez en **EO-6b-1** (tope y atenuación simétricos, rótulo; cerrada 2026-10-07) y **EO-6b-2** (imputación por la mediana del sector; cerrada 2026-10-08). `ai_action_capped_by_score_ladder` (`config.py:472`) pasa a
  simétrico, un escalón; la asimetría vuelve sólo si el track record muestra que las
  subas de la IA aciertan menos que sus bajas. `missing_data_score` deja el 0 por la
  mediana del sector. Con datos parciales la señal se atenúa hacia HOLD en las dos
  direcciones; el tope de confianza se queda. Los umbrales 82/68/55/45 se rotulan
  «ranking relativo, no calibrado» en la ficha; recalibrar cuando haya outcomes a
  365 días. Antes de mover la primera señal, el track record guarda la versión del método
  de señales —no `ENGINE_VERSION`, que es el contrato del motor del Monte Carlo—, para
  separar los outcomes de una escalera de los de la otra.

---

## Qué de la ideación ya no aplica

`brainstorm/99_PRIORIZACION.md` es del 2026-06-20. Verificado contra el código de
hoy, **la mayoría ya se shipeó** y conviene dejarlo dicho para no volver a
priorizarlo:

| Idea del brainstorm | Estado real |
|---|---|
| Reorganizar menú + fusionar pantallas (era la apuesta #1) | ✅ **IDEA-3 MENÚ** (2026-09-30) — `dashboard/app.py`: 11 entradas en modo normal; Watchlist como pestaña del Screener, Alertas + Track Record en una página, About desde Settings, Allocation y Comité fuera del menú (siguen registradas, ocultas) |
| Sacar herramientas de dev del menú | ✅ `dashboard/app.py` — `is_dev_mode()` esconde Eval IA, Calidad de Datos y Macro RAG |
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
| Módulo Doble Moneda | 🟡 Conversión ✅ (U2-5), cotización ✅ (N1, oficial de `ARS=X`, paralelo lo carga el usuario); Optimizer, Monte Carlo, Backtesting y Track Record convierten a USD desde #154 (2026-09-29); lo que lo deja en 🟡 es el Portfolio (fila **PORTFOLIO-FX**) |
| Modo oscuro y accesibilidad | ✅ `.streamlit/config.toml` (N3) — tema dark, contraste AA, telemetry off. Sin toggle en runtime |
| Separar el motor de la interfaz (API interna) | ❌ Sigue siendo la apuesta grande sin empezar |
| Unificar ficha + comité + chat | ❌ |
| Chat como puerta de entrada principal | ❌ (paso intermedio: fila **IDEA-4 CHAT-CONTEXTUAL**) |
| Módulo de Impuestos | ❌ (fila **IDEA-5 IMPUESTOS**) |
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
**`X-07` (haircut MC −20 %/+10 % vol) sale de esta lista** — lo reemplaza la Estimación
objetiva, bloque 6 (ADR 0001).

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
- Al cerrar una fila, moverla a [`ROADMAP.md`](ROADMAP.md) con su commit y sacarla de
  la tabla de abiertas: lo hace `scripts/close_row.py` (`docs/MAINTENANCE.md` §1). El
  BACKLOG no lleva lista de cerradas.
- **`## Orden actual` se reescribe, no se le agrega.** Lleva la repriorización vigente
  (número, fecha, SHA base), sus pasos en orden y, por id, lo que espera disparador o
  no tiene orden. Cuando un paso cierra, se tacha de la lista; cuando hay una
  repriorización nueva, su texto completo va como viñeta a «Archivo del backlog» al
  final de `ROADMAP.md` y el bloque se reescribe. `tests/test_doc_shape.py` exige que
  esté en las primeras 15 líneas y no pase de 15 líneas.
- Si un cambio mueve μ o el Monte Carlo, bumpear `ENGINE_VERSION` (U6-2).
- Este archivo está en la tabla canónica de [`INDEX.md`](INDEX.md); si se renombra,
  correr `scripts/check_doc_catalog.py`.
