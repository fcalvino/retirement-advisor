# Plan — el camino AI se pisa contra la decisión del motor (SIGNAL-6)

✅ He leído CONTEXT.md actualizado (vía `docs/PROMPT_INSTRUCTIONS.md`, `config.py`,
`analysis/strategy.py`, `analysis/ai_analyzer.py`, `data/product_ux.py`).

**Estado: ejecutado (2026-09-12, `e7ec4f0` + `54779a3`).** Este documento se escribió
como plan y se conserva con el resultado medido; al mergear la serie pasa a
`historical-plan` en `docs/INDEX.md`.

## Context

La serie `signal_reason_confidence` (SIGNAL-1..SIGNAL-5,
`docs/plans/SIGNAL_REASON_CONFIDENCE_PLAN.md`) quedó lista para PR, y la revisión previa
a abrirlo encontró cuatro defectos más en la misma superficie — **dos de ellos
introducidos por la propia serie**. Bloqueaban el merge porque los dos tocan la celda
«Motivo», que existe justamente para reconciliar score y acción (audit item 04): un
motivo que nombra otra acción es el defecto que la celda vino a eliminar, con más texto.

La causa es una sola. `_cap_action_to_matrix` **reimplementaba un subconjunto de la
matriz** —escalera, veto BEARISH, gate `require_technical_uptrend`— y el motivo se
adoptaba del motor sin comparar la acción:

| Síntoma | Input | Antes |
|---|---|---|
| **A** — motivo adoptado sin comparar la acción | LLM `SELL`, score 87 sin margen de seguridad, BULLISH | `SELL` con «…sin margen de seguridad — esperar una baja» |
| **B** — el cap deja obsoleto el motivo de la política blanda | score 35, dq `partial`, LLM `STRONG BUY` | `SELL` con «STRONG BUY capado a BUY por data quality partial» |
| **C** — el margen de seguridad no se re-aplicaba | score 87, sin margen, LLM `STRONG BUY` | AI `STRONG BUY` vs motor `BUY` (config default) |
| **D** — el cap crypto de volatilidad extrema tampoco | crypto score 87 + «Volatilidad extrema», LLM `STRONG BUY` | AI `STRONG BUY` vs motor `HOLD` |

C y D son huecos del contrato que SIGNAL-1 dice cerrar: lo cerraba para tres de las cinco
reglas de la matriz.

### Verificación de las líneas citadas (sobre el código previo a `e7ec4f0`)

| Doc dice | Real entonces | Estado |
|---|---|---|
| `apply_safety_overlay` | `def` en `:155`; blocks `:167-198`; políticas blandas `:205-207`; cap `:211-212`; motivo `:221-222`; `confidence_for` `:224-232` | ✅ |
| `_cap_action_to_matrix` | `:236-273` | ✅ |
| cap crypto de volatilidad extrema en `decide()` | `:549` (`"Volatilidad extrema" in warnings`) | ✅ |
| margen de seguridad en la matriz | `:486-495` (`is_value_stock() or not CFG.require_margin_of_safety`) | ✅ |
| doble aplicación del overlay | `ai_analyzer.py:80` y `strategy.py:719` (`full_analysis`) | ⚠️ el plan viejo decía `:578`; son `:719` |
| `logger.info` de `decide()` | `:566` | ✅ |
| tooltip de la columna «Technical» | `data/product_ux.py:1724` | ✅ |

## Decisión de diseño — el piso, no la enumeración

**El cap pasa a ser un piso contra `decide()`**: `min(acción del LLM, acción de decide())`
sobre el mismo `(fundamental, technical)`.

No es «forzar la acción del rule-based», que la serie descartó porque volvía decorativo al
LLM: `min` preserva la prudencia del LLM, la asignación la borraría. Es la lectura literal
del principio que ya cerró SIGNAL-1 —*el LLM puede ser más prudente que el motor, nunca
menos*— aplicada al veredicto completo en vez de a tres de sus reglas.

Consecuencias:

- Las cinco reglas —escalera, veto BEARISH, gate de tendencia, margen de seguridad y cap
  crypto de volatilidad— se re-aplican **por construcción**. `_cap_action_to_matrix` se
  borra. Una regla nueva en `decide()` ya no hay que acordarse de duplicarla.
- El motivo del motor pasa a ser correcto siempre que las acciones coincidan, que es la
  precondición que A necesitaba y no se comprobaba.
- La única llamada a `decide()` alimenta el piso **y** el motivo, en vez de correrse y
  tirarse. Los llamadores que ya tienen la decisión del motor la pasan por
  `rule_decision=`, así que el camino rule-based no paga nada.

**El motivo se decide comparando acciones**, no por «si está vacío»:

- `acción == rule.action` → el motivo del motor, **sobrescribiendo**. Cierra B: el que
  escribió una política blanda antes del piso se reemplaza por el del motor sobre la misma
  acción — que ya incluye lo que las políticas blandas dicen, porque `decide()` también las
  corre. Puede ser vacío, y entonces `decision_explanation` cae al texto de banda, que en
  ese caso es verdadero.
- `acción < rule.action` (la IA fue más prudente) → `AI_MORE_PRUDENT_REASON`, un literal
  nuevo en `strategy.py`, con los demás motivos del motor. Acá **no** sirve caer al texto
  de banda: `decision_explanation` elige la frase por **acción**, así que un `SELL` sobre
  un score de 87 rendiría «Score 87/100 en zona de venta», que es falso. El literal
  mantiene además `downgraded=True`: una acción que no se sigue del score no debería salir
  con confianza alta.
- `acción > rule.action` → sólo alcanzable con `STRATEGY.ai_action_capped_by_score_ladder`
  apagado; no se adopta ningún motivo, porque ninguno del motor describe esa acción.
- Los bloqueados conservan su `Bloqueado: …`: el paso de blocks ya lo escribió y el piso no
  los toca.

**Idempotencia.** El piso es monótono decreciente y `rule` se recalcula idéntico, así que
la segunda pasada del overlay no mueve ni la acción ni el motivo. Es más fuerte que antes,
donde el motivo dependía de si ya había uno escrito.

## Resultado medido

Grilla de **14.400 combinaciones** (score × señal × data quality × patrimonio negativo ×
clase de activo × acción del LLM × `above_sma200` × margen de seguridad × volatilidad):

| | Antes | Después |
|---|---|---|
| Acciones del camino AI por encima del motor | 92 | **0** |
| Motivos que describen otra acción | 1528 | **0** |
| Divergencias 1ª vs 2ª pasada del overlay | 0 | **0** |

Las 92 acciones que cambian **bajan todas** (12 por margen de seguridad, 80 por volatilidad
extrema crypto) y **80 salen del shortlist** (`ranking._is_buy`). El camino rule-based no
cambia: el piso es un no-op ahí (0 de 7200).

## Cambios

1. **`analysis/strategy.py`** — piso + motivo por comparación de acciones, parámetro
   `rule_decision=`, borrado de `_cap_action_to_matrix`, literal `AI_MORE_PRUDENT_REASON`,
   helper `_rank`. El `logger.info` de `decide()` baja a `debug`: desde el piso esa línea ya
   no describe necesariamente la decisión emitida, y `full_analysis` emite la INFO final.
2. **`analysis/ai_analyzer.py`** — el fallback rule-based pasa su decisión por
   `rule_decision=`.
3. **`data/product_ux.py:1724`** — el help de la columna «Technical» nombra el cuarto
   estado que SIGNAL-5 agregó.
4. **Documentación** — bloque SIGNAL-6 y nota en SIGNAL-3 (el cap de `confidence_for` es
   unidireccional) en `docs/issues/SIGNAL_REASON_CONFIDENCE_ISSUES.md`; este plan y su fila
   en `docs/INDEX.md`; `docs/CONTEXT.md` §pipeline.

## Tests

Todos verdes al entrar, sin `xfail` (la serie quedó sin marcas):

- `tests/test_ai_path_equivalence_oracle.py`
  - `test_ninguna_accion_del_llm_supera_al_motor` — la propiedad completa: la entrada es
    **cualquier** acción del LLM, no `rule.action`, que era lo que el test previo probaba.
  - `TestElMotivoDescribeLaAccionEmitida` — el oráculo que faltaba: motivo contra acción
    emitida (los de idempotencia comparan pasada-1 contra pasada-2, que es otra cosa).
    Incluye B, el caso «IA más prudente» y el flag apagado.
  - `TestElMotivoEnElCaminoAI::test_el_margen_de_seguridad_tambien_capa_el_camino_ai` (C) y
    `::test_la_volatilidad_extrema_crypto_tambien_capa_el_camino_ai` (D).
  - `TestIdempotencia::test_politica_blanda_y_piso_sobre_la_misma_decision` — la
    combinación que ningún test cubría.
- `tests/test_decision_coherence_oracle.py::…::test_el_motivo_no_puede_nombrar_la_accion_que_el_piso_descarto`
  — B desde la celda «Motivo», vía `decision_explanation`.

## Riesgos

1. **El piso puede leerse como «forzar el rule-based»**, que es la alternativa que la serie
   descartó. No lo es —`min` deja pasar la prudencia de la IA— y el docstring del módulo y
   el de `apply_safety_overlay` lo dicen explícitamente.
2. **Cambio de producto sin medir sobre datos reales**: 80 filas salen del shortlist en la
   grilla sintética. El impacto real sigue sin medirse porque
   `scripts/measure_score_impact.py` necesita una caché poblada y la local tiene un solo
   ticker elegible y ningún crypto — la misma punta suelta que la serie ya documenta.
3. **El flag `ai_action_capped_by_score_ladder` apagado** restaura el defecto crítico de
   SIGNAL-1 y ahora también C y D. La rama `>` del motivo existe para que, al menos, no se
   le preste a esa acción un motivo que el motor escribió para otra.
4. **El cap de `confidence_for` sigue siendo unidireccional** (un `SELL` en banda 87 sale
   `HIGH`). Anotado en el bloque de SIGNAL-3, que es donde vive ese defecto.

## Verificación

```bash
make check            # ruff check . && pytest — es exactamente lo que corre el CI
TZ=UTC make check     # el CI corre en UTC
./venv/bin/python3 -m pytest tests/ -q -rX   # -rX: cualquier XPASS es un fallo
./venv/bin/python3 scripts/check_doc_catalog.py
```
