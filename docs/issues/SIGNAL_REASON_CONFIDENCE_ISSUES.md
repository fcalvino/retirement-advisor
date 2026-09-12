# Hallazgos — cadena Signal → Motivo → Confidence (2026-09-12)

**Estado (2026-09-12): los cinco cerrados.** Ningún test de la serie lleva ya
`xfail`, y la suite no tiene ningún `xfail(strict=True)` vivo de estos hallazgos.
Commits: `f6c36ff` (SIGNAL-1/4/5), `e1b69ce` (SIGNAL-3), `f157c6d` (SIGNAL-2),
`b39015f` (el motivo del caso no medible). El plan de la serie está en
`docs/plans/SIGNAL_REASON_CONFIDENCE_PLAN.md`.

Cinco defectos reales en la cadena que produce una recomendación de compra, todos
reproducidos por test. Los tests quedan en la suite como `xfail(strict=True)` con
el ID del hallazgo en el `reason`, así que **la suite queda verde y se vuelve roja
sola el día que alguien arregle el motor** (el `strict` obliga a sacar la marca).

El mapa completo de escenarios (66 mapeados, 37 ya cubiertos) está en
`.context/signal_reason_confidence_scenarios.md`.

No se tocó código de producción. Cada bloque es un Issue listo para copiar.

Escala de severidad = impacto sobre la decisión de compra:

| Severidad | Significado |
|-----------|-------------|
| **Crítica** | El motor puede recomendar comprar algo que sus propias reglas rechazan |
| **Alta** | La recomendación es defendible pero su confianza o su motivo engañan |
| **Media** | Requiere una configuración no-default o una forma de datos poco frecuente |

---

## SIGNAL-1 — El camino AI puede emitir BUY/STRONG BUY por debajo de la banda de score que esa acción afirma

> ✅ **Cerrado (2026-09-12).** `apply_safety_overlay` capa la acción al peldaño que el
> score efectivo alcanza (`_cap_action_to_matrix` + `max_action_for_score`) y re-aplica
> los dos vetos técnicos de la matriz: BEARISH y `require_technical_uptrend`. Sólo baja,
> nunca sube — el LLM puede ser más prudente que la escalera, nunca menos — así que la
> función es monótona y el overlay sigue siendo idempotente. Se descartó forzar `decide()`
> sobre el camino AI: volvía decorativo al LLM. Los seis tests salieron de `xfail`.

**Severidad: Crítica** — es un falso BUY completo: acción, confianza y motivo, los tres
apuntando a comprar un nombre que el motor rule-based manda vender.

**Tests que lo reproducen**
- `tests/test_decision_coherence_oracle.py::TestNingunaCompraPorDebajoDeSuBanda::test_el_overlay_no_deja_una_compra_sin_banda`
- `…::test_strong_buy_del_llm_se_capa_a_la_banda_que_el_score_alcanza`
- `…::test_bearish_no_puede_quedar_como_compra_en_el_camino_ai`
- `…::test_el_motivo_no_puede_afirmar_zona_de_compra_sin_banda`
- `…::test_una_compra_sin_banda_llega_al_shortlist`
- `tests/test_decision_coherence_oracle.py::TestConfianzaCoherenteConLaAccion::test_el_overlay_no_emite_high_sobre_una_compra_sin_banda`

**Input exacto**

```python
fund.adjusted_score = 35.0          # STRATEGY.reduce_score - 10 → banda SELL
tech.signal = "BEARISH"
decision = Decision(action="BUY", fundamental_score=35.0)   # lo que devolvió el LLM
apply_safety_overlay(decision, fund, tech)
```

**Output obtenido**

```
action      = BUY
confidence  = HIGH
Motivo      = "Score 35/100 en zona de compra, el técnico no lo contradice"
shortlist   = la fila entra al embudo del Screener (ranking._is_buy → True)
```

Con `score = 69.0` (banda BUY) y un `STRONG BUY` del LLM el resultado es
`STRONG BUY / HIGH`: tampoco se capa al rung que el score alcanza.

**Output esperado y por qué.** `RetirementStrategy.decide` sobre el mismo input emite
`SELL`. `apply_safety_overlay` existe precisamente para que "el LLM nunca mejore el
veredicto del motor" (P0 D1, docstring de `strategy.py:102-109`), pero sólo re-aplica
los *blocks duros* y las dos políticas blandas: **nada compara la acción contra
`STRATEGY.strong_buy_score` / `buy_score`, y nada re-aplica el veto de técnico
BEARISH** (`strategy.py:382`) ni el gate `require_technical_uptrend`
(`strategy.py:402-413`). Lo mínimo sería capar la acción del LLM al rung que el
score efectivo alcanza — el LLM puede ser *más* prudente que la escalera, nunca
menos.

**Código responsable**
- `analysis/strategy.py:97-156` — `apply_safety_overlay` (no re-aplica la matriz)
- `analysis/ai_analyzer.py:464-502` — `_parse_response` acepta cualquier acción válida
- Consecuencia aguas abajo: `analysis/ranking.py:143` (`_is_buy`) y
  `data/product_ux.py:1623-1630` (la celda «Motivo») propagan fielmente el error

---

## SIGNAL-2 — La rama crypto del overlay no aplica las políticas de data quality ni de patrimonio negativo

> ✅ **Cerrado (2026-09-12, `f157c6d`).** `apply_negative_equity_policy` y
> `apply_data_quality_policy` salieron del `else` de equity: corren para las dos clases
> de activo cuando la decisión no está bloqueada, igual que en `decide()`. El `if
> _is_crypto` queda conteniendo sólo el block parabólico. Un activo ya bloqueado no las
> atraviesa — AVOID es más severo que cualquier degradación y su motivo es el que hay que
> mostrar. Se agregó idempotencia sobre crypto (el overlay corre dos veces en el pipeline
> real y `partial` no puede capar dos rungs) y el par (acción, confianza) esperado, para
> que «no se contradicen» no se pueda satisfacer dejando subir la confianza.

**Severidad: Crítica** — un STRONG BUY de IA sobre un crypto sin datos sobrevive
intacto, y lo hace con confianza `LOW`: la fila se contradice a sí misma.

**Tests que lo reproducen**
- `tests/test_ai_path_equivalence_oracle.py::TestElOverlayCryptoAplicaLasMismasPoliticas::test_data_quality_degrada_igual_que_en_el_camino_rule_based`
- `…::test_patrimonio_negativo_capa_igual_que_en_el_camino_rule_based`
- `…::test_no_puede_quedar_una_compra_con_confianza_low`

**Input exacto**

```python
fund.is_crypto = True
fund.adjusted_score = 87.0
fund.data_quality = {"level": "poor", "missing_fields": ["roe"]}
apply_safety_overlay(Decision(action="STRONG BUY", fundamental_score=87.0), fund, tech)
```

**Output obtenido**

```
camino AI    : action = STRONG BUY , confidence = LOW
camino rule  : action = HOLD
```

Idéntico con `negative_equity=True` y `level="good"`: AI `STRONG BUY`, rule `HOLD`.

**Output esperado y por qué.** `decide()` aplica las dos políticas blandas para
crypto también (`strategy.py:434-435`, sin condicional por clase de activo), así que
la rama crypto del overlay tendría que llamarlas igual que la rama equity
(`strategy.py:143-145`). Hoy el `if _is_crypto` sólo re-aplica el block parabólico y
sale; el `apply_negative_equity_policy` / `apply_data_quality_policy` viven en el
`else`. El síntoma más visible es la incoherencia interna: `confidence_for` **sí** lee
la data quality (de ahí el `LOW`), la acción no.

**Código responsable**
- `analysis/strategy.py:113-130` — rama crypto de `apply_safety_overlay`
- contraste: `analysis/strategy.py:143-145` (equity) y `analysis/strategy.py:434-435` (`decide`)

---

## SIGNAL-3 — `confidence_for` ignora el parámetro `action`: el HIGH de la banda SELL se hereda en una compra

> ✅ **Cerrado (2026-09-12, `e1b69ce`).** Una entrada más en el cap-loop: una acción de
> compra cuyo score no alcanza su banda queda en `MEDIUM`. El techo sale de
> `max_action_for_score`, la misma escalera que `decide()`, así que no hay un solo umbral
> escrito a mano en la función. `SELL` en banda SELL conserva su `HIGH` —la certeza es
> sobre salir, y es real— y los caps que ya estaban (`blocked`, `poor`, `partial`,
> `downgraded`, `negative_equity`) no cambiaron de precedencia. Con SIGNAL-1 mergeado el
> overlay ya no puede entregarle a `confidence_for` una compra sin banda, pero
> `STRATEGY.ai_action_capped_by_score_ladder` es apagable y la función es pública: tiene
> que ser correcta por sí misma.

**Severidad: Alta** — es el mecanismo que convierte SIGNAL-1 en un `HIGH`. La etiqueta
de confianza deja de ser legible: el mismo label significa "alta certeza de comprar" o
"alta certeza de salir" según de qué banda venga.

**Tests que lo reproducen**
- `tests/test_decision_coherence_oracle.py::TestConfianzaCoherenteConLaAccion::test_high_de_la_banda_sell_no_se_hereda_en_una_compra`
- `…::test_la_accion_emitida_cambia_la_confianza`

**Input exacto**

```python
confidence_for("BUY",  35.0, "BEARISH", blocked=False, downgraded=False,
               data_quality_level="", negative_equity=False)
confidence_for("SELL", 35.0, "BEARISH", blocked=False, downgraded=False,
               data_quality_level="", negative_equity=False)
```

**Output obtenido**: `"HIGH"` en los dos casos.

**Output esperado y por qué.** La función recibe `action` (y su docstring dice que el
label es "the same for identical (action, score, technical, dq) inputs"), pero el
cuerpo no lo usa: deriva todo de la banda del score. La rama final —
`else: base = "HIGH"  # SELL: high certainty the position should be exited`
(`strategy.py:69-70`) — afirma certeza **sobre vender**. Acompañando un `BUY` dice lo
contrario de lo que la evidencia soporta. Con `action` en la cuenta, un `BUY` cuyo
score no alcanza `buy_score` no puede salir `HIGH`.

**Código responsable**: `analysis/strategy.py:36-82` (`confidence_for`; la firma en
`:37` y la rama en `:69-70`).

---

## SIGNAL-4 — Las decisiones del camino AI nunca llevan `decisive_reason`: no se capa la confianza y el Motivo no nombra la causa

> ✅ **Cerrado (2026-09-12).** El motivo se **deriva**, no se reescribe: cuando el
> `Decision` llega sin `decisive_reason` propio, el overlay se lo pide al rule-based sobre
> el mismo `(fundamental, technical)`. `_parse_response` sigue sin escribirlo a propósito —
> duplicar las reglas de motivo en `analysis/ai_analyzer.py` habría creado una segunda
> fuente de verdad. Un block o una política blanda ya escribieron el suyo, más específico,
> y no se pisa. `tests/test_confidence_deterministic_oracle.py::test_rule_and_ai_paths_same_confidence`
> dejó de copiar el campo a mano: ahora verifica el camino real.

**Severidad: Alta** — misma acción, mismo input, y por el camino AI sale con una
confianza más alta y sin explicación. Es también el motivo por el que el test de
equivalencia existente no lo detecta: le **copia** el campo a mano.

**Tests que lo reproducen**
- `tests/test_ai_path_equivalence_oracle.py::TestElMotivoEnElCaminoAI::test_la_misma_accion_no_puede_salir_con_mas_confianza_por_el_camino_ai`
- `…::test_el_motivo_del_motor_no_viaja_por_el_camino_ai`

**Input exacto**

```python
fund.adjusted_score = 87.0            # banda STRONG BUY
fund.margin_of_safety_pct = None      # sin margen de seguridad
tech.signal = "BULLISH"
# las dos ramas emiten la MISMA acción (BUY) sobre el MISMO input
```

**Output obtenido**

```
camino rule : BUY  MEDIUM  decisive_reason = "Fundamentales de STRONG BUY, pero todavía
                                             sin margen de seguridad — esperar una baja"
camino AI   : BUY  HIGH    decisive_reason = ""
              Motivo = "Score 87/100 en zona de compra, el técnico no lo contradice"
```

**Output esperado y por qué.** `confidence_for` recibe
`downgraded=bool(decision.decisive_reason)` (`strategy.py:152`), de modo que el cap a
`MEDIUM` depende de un campo que `_parse_response` nunca escribe. El usuario ve
`HIGH` sobre una acción que el motor considera condicionada, y la celda «Motivo»
—cuyo objetivo es exactamente reconciliar score y acción (audit item 04)— cae al
texto genérico de la banda, que no menciona la falta de margen de seguridad.
`tests/test_confidence_deterministic_oracle.py::test_rule_and_ai_paths_same_confidence`
pasa porque construye el `Decision` del LLM con
`decisive_reason=rule_decision.decisive_reason`: fabrica la precondición que el
camino real no tiene.

**Código responsable**
- `analysis/ai_analyzer.py:490-502` — `_parse_response` no deriva `decisive_reason`
- `analysis/strategy.py:147-155` — el overlay calcula `downgraded` desde ese campo

---

## SIGNAL-5 — Una señal técnica *no medible* viaja como el literal `NEUTRAL` y satisface la confirmación técnica de STRONG BUY

> ✅ **Cerrado (2026-09-12).** `TechnicalResult.signal` tiene un cuarto estado explícito
> —`TECHNICAL.signal_not_measurable`, que además es su default— y
> `STRATEGY.strong_buy_technical_signals` (BULLISH/NEUTRAL) define qué *confirma* la banda
> de máxima convicción, sin incluirlo. `BUY` sigue permitido: su regla es `tech != "BEARISH"`,
> una ausencia de veto y no una confirmación, y degradarlo habría cambiado el shortlist de
> listadas recientes sin un defecto que lo respalde. No se modeló como caso del gate
> `require_technical_uptrend` — el defecto se manifiesta justamente con ese flag apagado.
> El estado no se muestra crudo en ninguna superficie: `data.product_ux.technical_signal_label`
> lo traduce para Screener, Watchlist, ficha y prompt del LLM.
>
> **Cierre del motivo (`b39015f`).** La acción quedó bien y el motivo no: un score de banda
> STRONG BUY sin confirmación técnica cae al `elif` de BUY, que no escribía
> `decisive_reason`, así que la celda «Motivo» usaba el texto genérico de la banda — «el
> técnico no lo contradice», lo contrario de lo que pasó. Ahora nombra la causa, y sólo en
> ese caso: un BUY que se sigue de su score sigue saliendo sin motivo, porque no es una
> degradación y marcarlo como tal cambiaría el estilo de la celda.
>
> **Las dos puntas sueltas del literal nuevo, revisadas: no requieren cambio.**
> `analysis/track_record.py:68` declara `technical_signal` como `Column(String, default="")`
> — texto libre, sin enum ni constraint: persistir `"NOT_MEASURABLE"` no necesita migración
> y no rompe nada. La lectura ya lo traduce (`dashboard/shared.py:1917` pasa el valor
> persistido por `technical_signal_label`), y nadie agrupa ni filtra por el literal. Lo que
> sí queda es una ambigüedad histórica: las filas escritas antes de hoy con `NEUTRAL` pueden
> significar «neutral medido» o «no se midió», y sólo el primero es lo que dicen. Es una
> advertencia para `scripts/score_track_record.py` —que según el comentario de `config.py`
> nunca corrió, y `recommendation_outcome` tiene cero filas— no un defecto a migrar:
> reescribir el pasado sería adivinarlo. `analysis/crypto_analyzer.py:206` lo loguea crudo,
> que es correcto: es un log de diagnóstico, y ahí `NOT_MEASURABLE` dice más que `NEUTRAL`.

**Severidad: Media** — con el default `require_technical_uptrend=True` el gate de
`above_sma200` tapa el agujero; el defecto se manifiesta con el flag apagado, que es
configuración soportada.

**Test que lo reproduce**:
`tests/test_technical_d15.py::TestSenalNoMedible::test_una_senal_no_medible_no_deberia_habilitar_la_banda_strong_buy`
(el estado previo, sin xfail, queda fijado en
`…::test_historia_insuficiente_devuelve_el_default_neutral`).

**Input exacto**: una serie semanal de 30 barras (empresa listada hace ~7 meses) →
`TechnicalAnalyzer.analyze` corta en `technical.py:79-81`; `fund.adjusted_score = 87.0`,
`STRATEGY.require_technical_uptrend = False`.

**Output obtenido**: `signal = "NEUTRAL"`, `signal_strength = 0`, warning
"Insufficient price history for technical analysis" → `decide()` emite **STRONG BUY**.

**Output esperado y por qué.** La matriz exige `tech in ("BULLISH", "NEUTRAL")` para
STRONG BUY (`strategy.py:371`): pide una confirmación técnica y acepta como tal la
*ausencia* de datos técnicos. Es la misma clase de defecto que U3-1 cerró para
`above_sma200` — donde `None` ("la ventana es más larga que la serie") se distingue
de `False` ("cotiza por debajo") — aplicada al campo `signal`, que no tiene ese
tercer estado. Lo esperado: un estado explícito de "no medible" (o consultar
`warnings`/`signal_strength is None`) que no cuente como confirmación.

**Código responsable**
- `analysis/technical.py:29` (default `signal = "NEUTRAL"`) y `:79-81` (retorno temprano)
- `analysis/strategy.py:371` (la matriz lo acepta como confirmación)

---

## Verificado como comportamiento esperado (no se reporta)

Escenarios que parecían defectos y no lo son; quedan fijados con tests que pasan, para
que nadie los "arregle" en la dirección equivocada:

| Escenario | Por qué el motor tiene razón | Test |
|-----------|------------------------------|------|
| El guard parabólico no dispara con `rsi_weekly is None`, incluso a +300 % del mínimo | Un RSI que no se midió no es sobrecompra, y la combinación no la produce el motor: `rsi_weekly` sólo es `None` cuando la serie es corta, y entonces `price_vs_52w_low_pct` quedó en 0.0. Lo contrario sería la inversa del defecto de U3-1 | `tests/test_strategy.py::TestGuardParabolico::test_un_rsi_que_no_se_midio_no_es_una_parabola` |
| `data_quality` con un `level` fuera de {good, partial, poor} no aplica tope de confianza | `compute_data_quality` sólo emite esos tres niveles (`fundamental.py:728-739`); un cuarto valor no es alcanzable | `tests/test_strategy.py::TestDataQualityBordes::test_solo_existen_tres_niveles` |
| `RetirementStrategy.decide()` devuelve `confidence` en el default `MEDIUM` | La confianza se finaliza en `apply_safety_overlay`, y los dos llamadores de producción (`strategy.py:575`, `ai_analyzer.py:88`) lo encadenan siempre | `tests/test_strategy.py::TestDataQualityBordes::test_sin_data_quality_no_degrada_ni_explota` |
| Una señal técnica con un string inesperado (`"bullish"`, `""`, `None`) | Las comparaciones son contra literales, así que lo desconocido cae del lado no alcista — conservador | `tests/test_decision_coherence_oracle.py::TestSenalTecnicaEnLaMatriz::test_una_senal_que_el_motor_no_conoce_se_lee_conservadora` |
