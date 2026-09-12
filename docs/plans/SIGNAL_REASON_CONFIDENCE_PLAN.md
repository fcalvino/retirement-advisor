# Plan — cadena Signal → Motivo → Confidence (SIGNAL-1..SIGNAL-5)

✅ He leído CONTEXT.md actualizado (vía `docs/PROMPT_INSTRUCTIONS.md`, `config.py`,
`analysis/strategy.py`, `analysis/technical.py`, `analysis/ai_analyzer.py`,
`analysis/ranking.py`, `data/product_ux.py`).

## Context

`docs/issues/SIGNAL_REASON_CONFIDENCE_ISSUES.md` (2026-09-12) documenta cinco
defectos en la cadena que produce una recomendación de compra, todos reproducidos
por tests `xfail(strict=True)` ya mergeados en `main` (#118). El `strict` es un
contrato: **el PR que arregla el motor tiene que sacar la marca en el mismo commit**,
o el CI se pone rojo por XPASS.

El defecto raíz es que `apply_safety_overlay` —la única barrera entre el LLM y el
usuario— re-aplica *blocks duros* y dos políticas blandas, pero no la escalera de
score ni los vetos técnicos. Resultado: un BUY/STRONG BUY de IA sobre un score de
banda SELL llega a la celda «Motivo» y al shortlist del Screener con confianza HIGH.

Este documento es el plan; **no hay código de producción en esta tarea**.

### Verificación de las líneas citadas (sobre el código actual)

Corridas contra el worktree en `100bda4`:

| Doc dice | Real hoy | Estado |
|---|---|---|
| `strategy.py:97-156` `apply_safety_overlay` | `def` en `:97`; rama crypto `:113-141`; políticas blandas equity `:144-145`; `confidence_for(...)` `:147-155` | ✅ (doc dice `:143-145`, son `:144-145`) |
| `strategy.py:36-82` `confidence_for`, firma `:37`, rama SELL `:69-70` | firma en `:36`; rama `else: base = "HIGH"` en `:69-70` | ✅ (firma `:36`, no `:37`) |
| `strategy.py:371` matriz STRONG BUY | `if score >= CFG.strong_buy_score and tech in ("BULLISH","NEUTRAL")` en `:371` | ✅ |
| `strategy.py:402-413` gate `require_technical_uptrend` | `:402` | ✅ |
| `strategy.py:434-435` políticas blandas en `decide()` | `:434-435` | ✅ |
| `ai_analyzer.py:470-502` `_parse_response` | `def` en `:464`; construcción del `Decision` `:488-502`; **no escribe `decisive_reason`** | ⚠️ corregir a `:464-502` |
| `ranking.py:143` `_is_buy` | `:143-145`, consumido en `:190` | ✅ |
| `product_ux.py:1623-1630` celda «Motivo» | `decision_explanation` en `:1599`; mapa de headlines `:1622-1630` | ✅ |
| `technical.py:29` default `signal="NEUTRAL"`, `:79-81` retorno temprano | `:29` y `:79-81` (`len(df) < 50`, con el **50 inline**) | ✅ |

**Los cinco defectos siguen vivos.**

Nota: el mapa de escenarios `.context/signal_reason_confidence_scenarios.md` **no
existe en este worktree** (`.context/` sólo tiene `todos.md`) — `.context/` es
gitignored y por-workspace. Quien ejecute el plan debe recuperarlo del workspace
donde se escribió o trabajar sólo con los tests, que son la fuente de verdad viva.

## Decisiones de producto (confirmadas con el usuario)

1. **SIGNAL-1** → el overlay **capa la acción del LLM al rung que el score alcanza
   Y re-aplica los vetos técnicos** (veto BEARISH de la matriz + gate
   `require_technical_uptrend`). El LLM puede ser más prudente que la escalera,
   nunca menos.
2. **SIGNAL-5** → «no medible» deja de habilitar **sólo STRONG BUY**. `BUY` sigue
   permitido (su regla es `tech != "BEARISH"`), así el cambio no saca del shortlist
   a las empresas listadas hace poco.
3. **SIGNAL-4** → el `decisive_reason` del camino AI se **deriva del rule-based**
   (una sola implementación de las reglas), no se reimplementa en `_parse_response`.

## Decisión de diseño — SIGNAL-5, cómo representar «señal no medible»

Tres alternativas y sus consecuencias aguas abajo:

**(a) Tercer literal en `signal` (`"UNMEASURED"`).** Rechazada. `signal` es un
literal que escapa del motor: `analysis/track_record.py:68/440-457` lo persiste en
SQL, `analysis/prompts.py:472/710` lo mete en el prompt del LLM,
`analysis/chat_tools.py:88`, `analysis/crypto_analyzer.py:206` y
`scripts/measure_score_impact.py:147/237` lo leen. Un cuarto valor obliga a auditar
cada consumidor y rompe el test que ya fija el estado actual
(`test_historia_insuficiente_devuelve_el_default_neutral`, que afirma `signal == "NEUTRAL"`).

**(b) Inferirlo en `strategy.py` desde `warnings` / `signal_strength is None`.**
Rechazada. Matchear el string `"Insufficient price history…"` desde la capa de
decisión es acoplamiento frágil; y `signal_strength` hoy es `int = 0` no-opcional,
volverlo `Optional[int]` tiene el mismo blast radius que (a).

**(c) Campo booleano nuevo en `TechnicalResult` — RECOMENDADA.** Es exactamente el
precedente de U3-1: ahí la distinción "no medido" vs "medido y falso" se resolvió
**agregando estados a un campo propio** (`above_sma200: Optional[bool]`), sin tocar
el literal de salida, y la convención de lectura (`is True` / `is False`) quedó
documentada en `technical.py:31-36`. Acá:

```python
# analysis/technical.py, dentro de TechnicalResult
signal_measurable: bool = True   # False = serie más corta que TECHNICAL.min_bars_for_signal;
                                 # `signal` conserva el default NEUTRAL por compatibilidad,
                                 # pero NO cuenta como confirmación técnica (U3-1, SIGNAL-5)
```

Consecuencias: `strategy.py:371` pasa a exigir
`technical.signal_measurable is not False` además de la banda; `ranking.py` y
`data/product_ux.py` **no cambian** (siguen viendo acciones y motivos, no el flag);
`track_record`/prompts/chat_tools siguen recibiendo el literal `NEUTRAL` de hoy.
El default `True` mantiene compatible todo fixture o `SimpleNamespace` existente
que no conozca el campo — importante porque los oráculos construyen `_tech()` a
mano; aun así se lee con `getattr(technical, "signal_measurable", True)`.

El `50` inline de `technical.py:81` se mueve a `TECHNICAL.min_bars_for_signal` en
`config.py` (estándar CONTEXT §5) y se usa en los dos lugares.

> **Lo que finalmente se implementó fue la alternativa (a), no la (c).**
> `TECHNICAL.signal_not_measurable = "NOT_MEASURABLE"` es un cuarto literal de
> `TechnicalResult.signal`, y el blast radius que motivaba rechazarla se contuvo con
> una sola función de presentación, `data/product_ux.py::technical_signal_label`,
> aplicada en `analysis/prompts.py:472/710` y en las tres páginas del dashboard que
> muestran la señal. Es una solución más completa que la que este plan recomendaba:
> resuelve además *cómo se lee* el estado, no sólo cómo se decide con él.
> **Punta suelta a verificar antes de mergear**: `analysis/track_record.py:68/440-457`
> va a persistir `"NOT_MEASURABLE"` en SQL conviviendo con los `NEUTRAL` históricos,
> y `analysis/crypto_analyzer.py:206` lo loguea crudo.

---

## Serie de PRs

Convención de la serie `fcf_yield` (#115-#118): PR 0 documental/instrumentación,
después un defecto por PR, cada uno mergeable solo y verde por sí mismo.

### PR 0 — `docs(signal): plan de la serie signal_reason_confidence`
- **Cambia**: crea `docs/plans/SIGNAL_REASON_CONFIDENCE_PLAN.md` (este documento) y
  agrega su fila a la tabla canónica de `docs/INDEX.md`, que
  `scripts/check_doc_catalog.py` valida.
- **Rol en el catálogo: `living-guide`** (resuelto). `historical-plan` está reservado
  para planes ya shipped, y `VALID_ROLES` en `scripts/check_doc_catalog.py:52-65` no
  tiene un rol de plan abierto: agregar uno obligaría a tocar el checker en un PR
  documental. `docs/BACKLOG.md` («lo que falta hacer») ya usa `living-guide` con esa
  misma semántica. Al cerrar la serie, la fila pasa a `historical-plan`.
- **Sin código de producción, sin cambios de test.**
- **Verificación**: `./venv/bin/python3 scripts/check_doc_catalog.py` y `make check`.

### PR 1 — `fix(confidence): confidence_for usa la acción emitida (SIGNAL-3)`
Primero de todos: es el **mecanismo** que convierte SIGNAL-1 en `HIGH`, y es el
cambio más chico y mejor aislado. Arreglarlo antes hace que el PR de SIGNAL-1 se
lea sólo como "la acción", sin mezclar confianza.

- **Archivo**: `analysis/strategy.py` (`confidence_for`, `:36-82`).
- **Qué cambia**: el cuerpo usa el parámetro `action`, hoy ignorado. Regla mínima y
  defendible: la rama `else: base = "HIGH"` (certeza de **salir**) sólo puede
  producir `HIGH` cuando la acción **no** es de compra; sobre `STRONG BUY`/`BUY`
  cuyo score no alcanza `oracle_min_score_for(action)`, el resultado se capa a
  `MEDIUM` (se reusa el mismo cap-loop que ya existe en `:72-80`). Los umbrales
  salen de `CFG.strong_buy_score` / `CFG.buy_score`; **ningún número nuevo**.
  Actualizar el docstring, que hoy promete que el label depende de `action`.
- **xfails que hay que sacar en este mismo PR** (`tests/test_decision_coherence_oracle.py`):
  - `TestConfianzaCoherenteConLaAccion::test_high_de_la_banda_sell_no_se_hereda_en_una_compra`
  - `TestConfianzaCoherenteConLaAccion::test_la_accion_emitida_cambia_la_confianza`
  - `TestConfianzaCoherenteConLaAccion::test_el_overlay_no_emite_high_sobre_una_compra_sin_banda`
    ⚠️ marcado "SIGNAL-1 + SIGNAL-3" pero **empieza a pasar acá**: el BUY sin banda
    sigue siendo BUY, pero ya no sale HIGH. Si no se saca la marca, XPASS ⇒ CI rojo.
- **Tests nuevos**: en `tests/test_confidence_deterministic_oracle.py`, tabla
  paramétrica (acción × banda) que fije que (i) `SELL` en banda SELL sigue `HIGH`,
  (ii) ninguna acción de compra por debajo de su banda puede salir `HIGH`,
  (iii) los caps existentes (`blocked`, `poor`, `partial`, `downgraded`,
  `negative_equity`) no cambiaron de precedencia.
- **Salida visible**: la **confianza mostrada** baja de HIGH a MEDIUM en filas del
  camino AI incoherentes. Sin cambios de acción ni de shortlist.

### PR 2 — `fix(overlay): la rama crypto aplica las mismas políticas blandas (SIGNAL-2)`
Independiente de PR 1 y PR 3; va segundo porque es el fix más mecánico y cierra una
severidad Crítica con superficie mínima.

- **Archivo**: `analysis/strategy.py:113-145`.
- **Qué cambia**: sacar `apply_negative_equity_policy` / `apply_data_quality_policy`
  del `else` y ejecutarlas para **ambas** clases de activo cuando
  `not decision.blocked`, igual que hace `decide()` en `:434-435` (que no tiene
  condicional por clase de activo). El `if _is_crypto` queda conteniendo sólo el
  block parabólico. Sin config nueva.
- **xfails a sacar** (`tests/test_ai_path_equivalence_oracle.py::TestElOverlayCryptoAplicaLasMismasPoliticas`):
  `test_data_quality_degrada_igual_que_en_el_camino_rule_based`,
  `test_patrimonio_negativo_capa_igual_que_en_el_camino_rule_based`,
  `test_no_puede_quedar_una_compra_con_confianza_low`.
- **Tests nuevos**: idempotencia sobre crypto (`TestIdempotencia` ya cubre equity):
  correr el overlay dos veces sobre un crypto con dq `partial` no debe capar dos
  rungs. Y un caso crypto `poor` + `STRONG BUY` que verifique acción `HOLD` y
  confianza `LOW` juntas.
- **Salida visible**: acciones de crypto en el camino AI bajan (STRONG BUY → HOLD
  con dq poor). **Sale gente del shortlist del Screener** (`ranking._is_buy`).
  Revisar fixtures de crypto en `tests/` y cualquier snapshot de Screener.

### PR 3 — `fix(overlay): el camino AI no puede superar la escalera ni los vetos técnicos (SIGNAL-1)`
Después de PR 1 (la confianza ya es coherente) y de PR 2 (el overlay ya tiene una
sola forma para ambas clases de activo), así este PR toca un `apply_safety_overlay`
simétrico.

- **Archivos**: `analysis/strategy.py` (`apply_safety_overlay`).
- **Qué cambia**, en este orden, después de los blocks y antes de `confidence_for`:
  1. **Cap por banda**: `max_action_for_score(effective_decision_score(fundamental))`
     — helper nuevo en `strategy.py`, construido desde `CFG.strong_buy_score /
     buy_score / hold_score / reduce_score`; si la acción del LLM está por encima
     del rung alcanzado, se baja al rung y se escribe `decisive_reason`
     ("El score no alcanza la banda de {acción pedida} — {acción efectiva}").
     Sólo hacia abajo: un HOLD del LLM sobre un score de STRONG BUY se respeta.
  2. **Veto técnico BEARISH**: si la acción resultante es `BUY`/`STRONG BUY` y
     `technical.signal == "BEARISH"`, misma degradación a `HOLD` con el mismo
     texto que la matriz usa en `:388-390`.
  3. **Gate `require_technical_uptrend`**: reusar exactamente la condición de
     `:402-413` (`tech == "BULLISH" or above_sma200 is True`).
  Para no duplicar reglas, extraer de `decide()` un helper puro
  `enforce_technical_gates(decision, technical)` y llamarlo desde los dos lados
  (refactor sin cambio de comportamiento en el camino rule-based).
- **xfails a sacar** (`tests/test_decision_coherence_oracle.py::TestNingunaCompraPorDebajoDeSuBanda`):
  `test_el_overlay_no_deja_una_compra_sin_banda`,
  `test_strong_buy_del_llm_se_capa_a_la_banda_que_el_score_alcanza`,
  `test_bearish_no_puede_quedar_como_compra_en_el_camino_ai`,
  `test_el_motivo_no_puede_afirmar_zona_de_compra_sin_banda`,
  `test_una_compra_sin_banda_llega_al_shortlist`.
- **Tests nuevos**: (i) property test — para toda acción del LLM y todo score, la
  acción final ≤ la de `decide()` sobre el mismo input (hoy
  `test_el_camino_ai_nunca_mejora_la_accion_del_rule_based_en_equity` sólo prueba
  con `rule.action` como entrada); (ii) el LLM *más* prudente se respeta
  (HOLD del LLM en banda STRONG BUY sigue HOLD); (iii) idempotencia: el overlay
  corre dos veces (`ai_analyzer.py:80` y `strategy.py:578`) y el cap no debe bajar
  dos rungs.
- **Salida visible**: **acción**, **celda «Motivo»** (ahora nombra la causa en vez
  del texto genérico de banda) y **composición del shortlist**. Es el cambio de
  producto más grande de la serie.

### PR 4 — `fix(ai): el motivo del motor viaja por el camino AI (SIGNAL-4)`
Depende de PR 3: ahí se extrajeron los helpers que producen `decisive_reason`.

- **Archivos**: `analysis/strategy.py` (overlay) y/o `analysis/ai_analyzer.py:464-502`.
- **Qué cambia**: cuando la decisión del camino AI llega sin `decisive_reason`, el
  overlay deriva el del rule-based corriendo `RetirementStrategy().decide(fund, tech)`
  sobre el mismo input y adoptando su `decisive_reason` **si la acción coincide**
  (si el LLM eligió una acción distinta y más prudente, el motivo del rule-based no
  la explica — en ese caso escribir uno propio del cap, que ya existe desde PR 3).
  `_parse_response` queda sin lógica de reglas. Ojo con el costo: `decide()` es puro
  y barato, pero conviene que el overlay reciba la decisión rule-based ya calculada
  cuando el llamador la tiene.
- **xfails a sacar** (`tests/test_ai_path_equivalence_oracle.py::TestElMotivoEnElCaminoAI`):
  `test_la_misma_accion_no_puede_salir_con_mas_confianza_por_el_camino_ai`,
  `test_el_motivo_del_motor_no_viaja_por_el_camino_ai`.
- **Tests nuevos**: arreglar
  `tests/test_confidence_deterministic_oracle.py::test_rule_and_ai_paths_same_confidence`,
  que hoy **fabrica la precondición** copiando `decisive_reason=rule_decision.decisive_reason`:
  sacarle la copia, para que pruebe la equivalencia real. Agregar el caso simétrico
  (LLM que sí trae un motivo propio: no debe pisarse).
- **Salida visible**: baja la **confianza mostrada** (HIGH → MEDIUM) en el camino AI
  sobre acciones condicionadas, y la **celda «Motivo»** pasa de genérica a explicativa
  (`is_downgrade` pasa a `True`, lo que cambia el estilo de la celda en el Screener).

### PR 5 — `fix(technical): una señal no medible no confirma STRONG BUY (SIGNAL-5)`
Último: severidad Media, independiente de los anteriores, y el único que toca
`config.py` con un parámetro nuevo.

- **Archivos**: `config.py` (`TECHNICAL`), `analysis/technical.py:29/79-81`,
  `analysis/strategy.py:371`.
- **Qué cambia**: (i) `TECHNICAL.min_bars_for_signal: int = 50` (hoy inline en
  `technical.py:81`); (ii) campo `signal_measurable: bool = True` en
  `TechnicalResult`, puesto en `False` en el retorno temprano, con el comentario que
  cita U3-1 igual que el bloque de `above_sma200`; (iii) `strategy.py:371` exige
  `getattr(technical, "signal_measurable", True)` además de
  `tech in ("BULLISH","NEUTRAL")`; cuando falla, cae al rung `BUY` de la matriz con
  `decisive_reason` ("Sin historia suficiente para confirmar el técnico — no alcanza
  para compra fuerte"). **`BUY` no se toca** (decisión de producto).
- **xfail a sacar**: `tests/test_technical_d15.py::TestSenalNoMedible::test_una_senal_no_medible_no_deberia_habilitar_la_banda_strong_buy`.
  `…::test_historia_insuficiente_devuelve_el_default_neutral` (hoy verde, afirma
  `signal == "NEUTRAL"`) **debe seguir pasando** — es la comprobación de que
  elegimos la alternativa (c) y no la (a); extenderlo con
  `assert r.signal_measurable is False`.
- **Tests nuevos**: (i) mover el umbral en `TECHNICAL` mueve la frontera de
  "medible" (mismo patrón que `test_mover_el_umbral_de_compra_mueve_la_frontera`);
  (ii) con `require_technical_uptrend=False` y score de STRONG BUY, historia corta
  ⇒ `BUY`, no `STRONG BUY`; (iii) un `SimpleNamespace` sin el campo (fixtures viejos)
  se sigue leyendo como medible.
- **Salida visible**: empresas listadas hace poco dejan de aparecer como STRONG BUY.
  Shortlist sin cambios (BUY sigue siendo compra).

---

## Documentación y fixtures a actualizar

- `docs/issues/SIGNAL_REASON_CONFIDENCE_ISSUES.md`: marcar cada hallazgo como cerrado
  con su PR, y corregir la referencia `ai_analyzer.py:470-502` → `:464-502`.
- `docs/CONTEXT.md`: §5 (estándares) si se agrega la convención de lectura de
  `signal_measurable`; §6 (estado de features) con la serie cerrada. Correr
  `./venv/bin/python3 scripts/refresh_context.py`.
- `docs/INDEX.md`: fila del plan (PR 0) y, al cerrar, decidir si el plan pasa a
  `historical-plan`.
- `analysis/strategy.py` docstring de módulo: hoy dice "75 / 60 / 45" y "AI path
  cannot bypass hard safety blocks" — con PR 3 la afirmación se vuelve más fuerte
  ("ni la escalera ni los vetos técnicos").
- Fixtures: cualquier snapshot del Screener o del track record que asuma la
  composición actual del shortlist (PR 2 y PR 3 la cambian).
- `analysis/track_record.py` guarda `action`/`confidence` históricos: las filas
  viejas quedan con la semántica anterior. No migrar; anotarlo.

## Verificación (cada PR)

```bash
make check            # ruff check . && pytest — es exactamente lo que corre el CI
TZ=UTC make check     # obligatorio: el CI corre en UTC
./venv/bin/python3 -m pytest tests/test_decision_coherence_oracle.py \
    tests/test_ai_path_equivalence_oracle.py \
    tests/test_confidence_deterministic_oracle.py \
    tests/test_technical_d15.py tests/test_strategy.py -q
./venv/bin/python3 -m pytest -q -rX   # -rX lista XPASS: con strict=True son fallos
./venv/bin/python3 scripts/check_doc_catalog.py
```

Antes de mergear PR 2/3/5, correr `scripts/measure_score_impact.py` sobre el
universo cacheado para cuantificar cuántos nombres cambian de acción — la serie
`fcf_yield` usó exactamente ese harness (#115) para eso.

## Riesgos

1. **XPASS prematuro** (el riesgo operativo principal). `strict=True` ⇒ un test que
   empieza a pasar antes de su PR pone el CI rojo. El caso concreto ya identificado:
   `test_el_overlay_no_emite_high_sobre_una_compra_sin_banda` está etiquetado
   "SIGNAL-1 + SIGNAL-3" pero **flipea en PR 1**. Correr `pytest -rX` en cada PR.
2. **Doble aplicación del overlay**. `ai_analyzer.py:80` y `strategy.py:578` lo
   encadenan sobre el mismo objeto. El cap de PR 3 y el `decisive_reason` de PR 4
   tienen que ser idempotentes o degradan dos rungs. `TestIdempotencia` existe —
   extenderlo en cada PR.
3. **Cambio de producto visible sin medir**. PR 2 y PR 3 sacan filas del shortlist.
   Es el arreglo correcto, pero conviene el número antes del merge (ver arriba).
4. **Coste del `decide()` extra en PR 4** si el overlay lo recalcula por símbolo en
   caliente; mitigable pasando la decisión rule-based cuando el llamador ya la tiene.
5. **`.context/signal_reason_confidence_scenarios.md` no está en este worktree** —
   los 29 escenarios mapeados y no cubiertos podrían perderse. Recuperarlo antes de
   empezar, o aceptar los tests como única fuente.

## Estado de la serie

| PR | Defecto | Estado |
|----|---------|--------|
| 0 | — (plan) | ✅ este documento |
| 1 | SIGNAL-3 | ✅ implementado |
| 2 | SIGNAL-2 | ⏳ pendiente — 4 `xfail(strict=True)` vivos |
| 3 | SIGNAL-1 | ✅ implementado |
| 4 | SIGNAL-4 | ✅ implementado |
| 5 | SIGNAL-5 | ✅ implementado (alternativa (a), ver arriba) |
| 6 | copy del caso «no medible» | ⏳ pendiente, ver decisión (A) |

El orden de merge real difirió del planeado: SIGNAL-1/4/5 se implementaron juntos y
SIGNAL-3 entró después. El riesgo de XPASS que el plan anticipaba para PR 1 se
resolvió por el otro lado —el cap de SIGNAL-1 hizo pasar
`test_el_overlay_no_emite_high_sobre_una_compra_sin_banda`, que quedó sin marca en
ese commit— así que PR 1 sólo tuvo que sacar dos marcas.

## Decisiones cerradas

**(A) Copy de los `decisive_reason` nuevos → no hizo falta copy nuevo, salvo un caso.**
El cap de SIGNAL-1 (`_cap_action_to_matrix`) deliberadamente **no escribe motivo**: lo
escribe SIGNAL-4, corriendo `decide()` sobre el mismo `(fundamental, technical)` y
adoptando su `decisive_reason`. Es mejor que lo que este plan proponía — el motivo lo
redacta el motor que conoce la causa, y no queda una segunda redacción que mantener
sincronizada con las reglas. Un BUY del LLM capado a SELL cae al texto de banda de
`decision_explanation` ("Score 35/100 en zona de venta"), que es verdadero.

La excepción, que queda como **PR 6**: con `require_technical_uptrend=False`, un score
de STRONG BUY y una señal no medible, `decide()` cae al `elif` de BUY y sale **sin**
`decisive_reason`, así que la celda «Motivo» dice "el técnico no lo contradice" —
justo lo que SIGNAL-5 vino a desmentir. Ahí va una línea, en el tono de `:376-380`
(nombra la causa, no la regla):

> `"Sin historia suficiente para confirmar el técnico — alcanza para comprar, no para compra fuerte"`

**(B) Exponer en la UI que la acción fue capada respecto del LLM → no.**
`ai_confidence` se muestra como explicación porque es una *opinión sobre la misma
decisión*. Un indicador de "el LLM había dicho STRONG BUY" mostraría una
recomendación que el motor ya rechazó, y le daría estatus de alternativa a algo que
por diseño no lo es: el overlay existe precisamente para que el LLM nunca mejore el
veredicto del motor. La celda «Motivo» ya nombra la causa desde SIGNAL-4, que es la
información accionable. Fuera de alcance, ahora por decisión y no por omisión.
