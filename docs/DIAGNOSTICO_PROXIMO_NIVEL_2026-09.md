# Diagnóstico y brainstorming — Próximo nivel (2026-09-04)

> Documento de ideación, no de implementación. Generado analizando el código real
> (`config.py`, `docs/CONTEXT.md`, `docs/ROADMAP.md`, `docs/BACKLOG.md`,
> `docs/REFACTOR_BACKLOG.md`, `docs/brainstorm/`, `analysis/`, `dashboard/`) el
> 2026-09-04. No reemplaza a `docs/brainstorm/99_PRIORIZACION.md` (2026-06-20,
> generado navegando pantalla por pantalla) — lo complementa con una lectura
> centrada en el código y el estado de ejecución dos meses y medio después.

## 1. Diagnóstico breve

**Fortalezas reales (no marketing):**
- El motor cuantitativo es inusualmente honesto consigo mismo: `config.py` documenta en el propio código *por qué* cada threshold es lo que es, qué evidencia falta para calibrarlo mejor, y qué se decidió no arreglar y por qué (ver docstrings de `StrategyConfig`, `PiotroskiConfig`). Es raro ver esto en un codebase de este tamaño.
- `REFACTOR_BACKLOG.md` está prácticamente en cero — 40+ de 42 ítems de deuda técnica estructural ya cerrados (God methods, thresholds hardcodeados, cobertura de `shared.py`). El "próximo nivel" **no** es limpieza de código.
- La cultura de testing es sólida: oráculos independientes (no auto-consistencia), aislamiento de tests contra la DB del usuario (lección de N6), mutation testing en los fixes financieros más delicados.
- El diseño anti-alucinación de la capa IA (Chat con tool-calling estructurado, narrativa que solo puede citar datos que un tool determinístico ya calculó) es un patrón correcto y ya está implementado, no es aspiracional.

**El hueco real, y lo dice el propio código:** el track record tiene **n=11** outcomes evaluados a 30 días. Media docena de docstrings en `config.py` (`StrategyConfig`, `PiotroskiConfig`, bandas REIT) dicen textualmente "esto es anclaje por percentil, no calibración — falta evidencia empírica". `U5-1b` está formalmente bloqueado por esto. Es el cuello de botella epistémico de todo el motor, no un detalle.

**Contradicción entre docs encontrada:**
- `docs/BACKLOG.md` sigue marcando "Módulo Doble Moneda" como 🟡 Parcial, pero conversión (U2-5) y cotización oficial+paralelo (N1, 2026-09-01) ya están shipeadas — es un dato stale, no un gap real.
- `docs/brainstorm/99_PRIORIZACION.md` (2026-06-20) identificó 3 "apuestas grandes" como lo que más mueve la aguja: reorganizar el menú (19→~10 pantallas), separar motor de interfaz, y chat como puerta de entrada. Dos meses y medio después, los *quick wins* de ese mismo documento se ejecutaron casi todos (modo oscuro → N3; resultados cacheados al entrar → `screener_store`; Chat con preguntas sugeridas → ya está en `18_Chat.py`), pero **las tres apuestas grandes siguen en cero**. El patrón de trabajo reciente (refactors S12, O1, T1, S17, S16) es 100% motor/deuda técnica, 0% las apuestas de producto que la propia ideación marcó como las que más importan.

## 2-3. Ideas por área (impacto / esfuerzo / origen)

### A. UX / Producto

| Idea | Impacto | Esfuerzo | Origen |
|---|---|---|---|
| **Reorganizar menú 19→~10 pantallas por intención** | Alto | Medio (reestructurar navegación + fusionar, no lógica nueva) | Ya en `99_PRIORIZACION.md` como apuesta grande — no nueva, pero atrasada 2.5 meses |
| **Asistente "¿qué cambio para llegar?"** en Simulaciones | Alto | **Bajo** — el motor (`monthly_savings_for_probability`, bisección sobre prob. real) ya existe, falta solo la superficie de UI | Ya en `BACKLOG.md` — el único ítem funcional abierto además de U5-1b. La fruta más baja del árbol entero del proyecto |
| **Chat como acceso contextual** (no como puerta de entrada total): botón "preguntale al asesor" embebido en Plan/Simulaciones que precarga el contexto de esa pantalla en el chat | Medio-alto | Bajo-medio — paso intermedio antes de la apuesta grande de "chat como home" | Nueva variante incremental de una idea ya en ideación |
| Poner "cómo viene tu plan" en el home en vez del menú | Alto | Medio | Ya en ideación (`01_inicio_home.md`) |

### B. Motor cuantitativo / evidencia empírica

| Idea | Impacto | Esfuerzo | Origen |
|---|---|---|---|
| **Backtesting point-in-time para generar pseudo-track-record histórico** — usar SEC XBRL frames (ya se consume para reconciliación en `data_reconciliation.py`) para reconstruir fundamentales *como se veían* en cada trimestre pasado, correr el scorer/decisión contra eso, y generar cientos de "recomendaciones sintéticas" con outcome conocido en vez de esperar años a que `n=11` crezca orgánicamente | **Muy alto** — desbloquea U5-1b, la calibración de bandas REIT, y saca a `StrategyConfig`/`PiotroskiConfig` del estado "percentile anchoring, no calibración" que el propio código admite | Alto — look-ahead bias es difícil de evitar del todo, es trabajo de ingeniería de datos serio | **Nueva.** No está en BACKLOG ni en ideación — la idea de mayor apalancamiento del análisis, porque ataca la causa raíz que el código señala como su límite epistémico |
| Risk parity como método de asignación alternativo (además de mean-variance SLSQP) | Medio | Medio — Black-Litterman ya implementado (`portfolio/black_litterman.py`), risk parity sería un módulo nuevo paralelo | Mencionado tangencialmente en ideación ("carteras más robustas") sin especificar risk parity — parcialmente nueva |
| Scorer bancario/utilities dedicado | Medio | Alto | **Fuera de alcance explícito** (X-01) — no se repropone, solo se señala como gap conocido y aceptado |

### C. IA / Chat

| Idea | Impacto | Esfuerzo | Origen |
|---|---|---|---|
| **Encadenar 2-3 tools por pregunta** en `ChatAgent` para escenarios "¿y si...?" (ej. "¿si aporto 500 más por mes llego antes?" requiere recalcular MC con params hipotéticos, no solo leer un dato) | Alto | Medio — `_route` hoy elige exactamente **un** tool por pregunta (confirmado en `chat_agent.py`); el patrón anti-alucinación ya está, extenderlo a multi-step es incremental | Nueva — no está mencionada en ningún doc |
| Unificar ficha+comité+chat en una experiencia | Medio-alto | Alto | Ya en ideación como apuesta grande |
| Centralizar la línea "IDIOMA OBLIGATORIO" repetida 9 veces en `prompts.py` | Bajo | Trivial | Nueva, cosmética |

### D. Arquitectura

| Idea | Impacto | Esfuerzo | Origen |
|---|---|---|---|
| Separar motor de interfaz (API interna) | Muy alto **si el objetivo es web/multiusuario**; bajo si el producto sigue siendo local single-user | Alto | Ya en ideación como apuesta grande — condicionarla explícitamente a una decisión de negocio primero |

### E. Negocio / nuevos módulos

| Idea | Impacto | Esfuerzo | Origen |
|---|---|---|---|
| **Módulo de Impuestos personales** (bienes personales, retención de dividendos AR vs USD, ganancia de capital al vender) — el producto ya tiene todo el tilt argentino (universo con ADRs, `ars_risk_discount`, cotización oficial/paralelo) pero `TaxConfig` solo modela impuesto corporativo para NOPAT, no el impuesto del *usuario* | Alto — diferenciación real para el público objetivo (inversor argentino) | Medio-alto | Ya listado como apuesta grande en ideación, sin scope — acá lo concreto es *qué* construir |
| Versión web multiusuario | Alto (cambia el modelo de negocio) | Alto — depende de la separación motor/interfaz de arriba | Ya en ideación |

## 4. Recomendación priorizada (top 5)

1. **Asistente "¿qué cambio para llegar?"** — el motor ya existe, es literalmente conectar UI a una función ya escrita. La relación impacto/esfuerzo más desbalanceada del análisis y ya está en el backlog formal.
2. **Backtesting point-in-time para evidencia sintética** — la única idea nueva que ataca la limitación que el propio `config.py` repite media docena de veces como su techo actual (calibración sin datos). Desbloquea decisiones hoy "congeladas hasta tener evidencia" (U5-1b, bandas REIT, umbrales Piotroski).
3. **Reorganizar el menú (19→~10)** — identificado desde junio como lo que más baja la barrera de entrada; el trabajo reciente del repo (puros refactors de motor) sugiere que se está postergando sistemáticamente.
4. **Chat contextual embebido** (paso intermedio antes de "chat como home") — aprovecha una pieza ya construida y subutilizada (`ChatAgent` con anti-alucinación estructural) sin pagar el costo completo de rediseñar la navegación.
5. **Módulo de Impuestos personales** — la apuesta de producto con más diferenciación real dado el público (argentino, con ADRs y doble moneda ya resueltos), pero en cuarto lugar porque compite en esfuerzo con las de arriba y no depende de nada previo — se puede planear en paralelo.

Se deja **fuera** por ahora: separar motor/interfaz y versión web multiusuario — apuestas de alto esfuerzo que solo se justifican si ya hay una decisión de negocio de ir a multiusuario; construirlas especulativamente sería el tipo de abstracción prematura que el propio código evita en todos lados.

## Estado de implementación

> Fuente de verdad del loop de implementación (`/loop`). Cada idea se implementa en su propio ciclo: rama → PR → review → merge, en este orden de prioridad.

- [x] 1. Asistente "¿qué cambio para llegar?" (Simulaciones) — **ya estaba implementado**, la fila del diagnóstico partía de `BACKLOG.md` desactualizado. Verificado en `dashboard/pages/7_Simulaciones.py:2142-2191`: `monthly_savings_for_probability`/`cached_goal_savings_target` ya alimentan el mensaje "💡 Para llevar {meta} al 80% de probabilidad: $X/mes" desde `5eed792` (2026-08-15). Docs corregidos, no requirió PR de código — PR: [#99](https://github.com/fcalvino/retirement-advisor/pull/99)
- [ ] 2. Backtesting point-in-time para evidencia sintética — **en curso, PR 2/N mergeado.** Acordado el alcance con el usuario antes de codear en cada PR (varias rondas de investigación conjunta: N6/N6c/U5-18d, `SecEdgarSource`, qué necesita realmente Piotroski vs el scorer completo, y qué hacer con la mitad "moat" de U5-1b). PR 1: [#100](https://github.com/fcalvino/retirement-advisor/pull/100) — `analysis/point_in_time.py`, reconstrucción de fundamentales SEC ancladas a `filed <= cutoff`. PR 2: [#102](https://github.com/fcalvino/retirement-advisor/pull/102) — `analysis/point_in_time_piotroski.py`, Piotroski F-Score point-in-time completo (9 checks) reusando `EnhancedScoring._piotroski_score` sin duplicar lógica; 4 rondas de code review encontraron y corrigieron bugs reales de alineación de fechas entre conceptos, contaminación del eje de períodos por instant facts (portada de 10-K, 10-K de transición de año fiscal) y un fallback `info.get(...) or 0` en `analysis/scoring.py` que afectaba también al path de producción en vivo (no solo backtesting) — corregido ahí para que todo caller lo reciba. Sigue sin persistir nada ni tocar `track_record.py`. **Falta para cerrar la idea:** (a) decidir e implementar dónde viven las recomendaciones sintéticas — recomendación ya documentada en la discusión del PR 1: tablas separadas en el mismo `DB_PATH`, nunca reusar `RecommendationLog`/`track_record_store`, con oráculo de aislamiento propio (mismo patrón que `tests/test_track_record_isolation_oracle.py`), (b) generar volumen (correr `piotroski_as_of` sobre el universo × múltiples cutoffs históricos) y medir outcomes a 1 año vía precio yfinance (point-in-time-safe, no necesita reconstrucción), (c) conectar esa evidencia a la calibración de `PiotroskiConfig.strong_threshold`/`bonus_strong`. La mitad "moat" de U5-1b queda fuera de esta idea (el tramo IA introduciría hindsight bias; el tramo cuantitativo 0-12 es un candidato de PR futuro, no comprometido todavía)
- [ ] 3. Reorganizar el menú (19→~10 pantallas) — PR: _pendiente_
- [ ] 4. Chat contextual embebido — PR: _pendiente_
- [ ] 5. Módulo de Impuestos personales — PR: _pendiente_
