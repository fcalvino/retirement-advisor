# Evaluación: "System One models" y Jev (TypeSafe AI) — ¿aplica a este repo?

**Fecha:** 2026-09-21 · **Rol:** ideation (decisión, no spec de implementación)
**Artículo evaluado:** `https://typesafe.ai/blog/introducing-system-one-models-and-jev`
**Veredicto:** **descartar para el motor de decisión**; adoptar gratis una lección de
diseño que ya tenemos implementada; piloto opcional y acotado sólo en triage de texto.

---

## 0. Nota de método y limitaciones de la lectura

El artículo y la documentación se leyeron con `WebFetch`, que devuelve la página
procesada y respondida por un modelo intermedio: **no obtuve el texto literal
completo del post**, sino respuestas sobre él más fragmentos entrecomillados. Lo
declaro porque afecta la fuerza de las citas: las frases entre comillas de abajo
son los fragmentos que la herramienta devolvió, no una transcripción verificada
carácter a carácter. Para compensar fui a las fuentes primarias que el post cita:

- `https://docs.typesafe.ai/llms.txt` — índice completo de la documentación
- `https://docs.typesafe.ai/api.md` — referencia HTTP
- `https://docs.typesafe.ai/model-jaggedness/jev-1.13.md` — limitaciones declaradas
- `https://evals.typesafe.ai/` — los benchmarks que el post invoca
- `https://github.com/typesafe-ai/system-one-adapter-python` — el adapter con que
  midieron a los LLMs contra los que se comparan

**No existe paper.** No hay arXiv, ni publicación, ni validación externa de "RLCD"
(*Reinforcement Learning for Calibrated Decisions*) en ninguna de esas fuentes.
Es un lanzamiento de producto en early access, no un resultado de investigación.

Los precios y IDs de modelos Claude citados acá se verificaron contra la referencia
de la API de Anthropic (Opus 5 `claude-opus-5` $5/$25 por MTok; Sonnet 5
`claude-sonnet-5` $2/$10; Haiku 4.5 `claude-haiku-4-5` $1/$5; Fable 5.1
`claude-fable-5-1` $10/$50), no de memoria.

Del repo leí `config.py`, `analysis/ai_analyzer.py`, `analysis/committee.py`,
`analysis/committee_prompts.py`, y las secciones §5 (estándares), §8 (limitaciones)
y el catálogo de `docs/INDEX.md` de `docs/CONTEXT.md` — no el archivo entero (195 KB).

---

## 1. Qué es realmente

### 1.1 El mecanismo, desde primeros principios

Un LLM de chat resuelve *todas* las tareas con la misma maquinaria: generar tokens
uno tras otro y esperar que el string resultante sea parseable. Cuando lo único que
necesitás es "¿cuál de estas 5 opciones?" esa maquinaria es absurdamente cara: pagás
generación autorregresiva, latencia secuencial, y el riesgo de que el JSON salga mal.

La propuesta de TypeSafe es amputar la generación. El API es un solo endpoint
(`POST https://api.typesafe.ai/v1/systemone`, `docs.typesafe.ai/api.md`) que recibe:

- `state` — el contexto, string o dato estructurado
- `questions` — un mapa de preguntas **tipadas**, de tres formas y sólo tres:
  - **Noul** — sí/no, devuelve la probabilidad de "sí" (0–1)
  - **Choice** — una opción de un conjunto cerrado (máx. 255), devuelve la elegida,
    la probabilidad de cada opción y una `confidence`
  - **Score** — un nivel de una escala ordenada y descripta, mismos campos

y devuelve `answers` (un valor por pregunta) más `usage`. Todas las preguntas se
responden **en paralelo en una sola llamada** — el patrón que documentan como
*speculative fan-out* (`docs.typesafe.ai/patterns/fan-out.md`).

La tesis de diseño es explícita y es la parte buena: *el código manda, el modelo
sólo contesta preguntas angostas* (`docs.typesafe.ai/concepts/how-to-build-with-system-one.md`).
Los pesos, los umbrales y la combinación viven en tu código, no en el prompt
(*composite scoring*, `docs.typesafe.ai/patterns/composite-scoring.md`).

### 1.2 Supuestos que la cosa necesita para funcionar

De la propia página de *jaggedness* de `jev-1.13`, nueve bordes filosos declarados.
Los cuatro que importan acá:

- **"Jev is not a calculator"** y **"does not count reliably"**.
- **"reads dates as text, not as ordered quantities"**.
- **"Accuracy falls as the state grows with content unrelated to the decision"**.
- **"is not trained to generate text"** — y rinde mal si lo forzás.

Es decir: sirve cuando la decisión (a) es un conjunto cerrado, (b) se apoya en texto
corto y pertinente, (c) no requiere aritmética ni orden temporal, y (d) no necesita
producir una justificación en prosa.

### 1.3 Lo que demuestra vs. lo que sólo afirma

**Demuestra (estructuralmente, sin necesidad de creerles):**

- *Type safety*. "The model never makes type errors" es verdad por construcción: si
  el espacio de salida es un enum o un escalar, no hay forma de devolver otra cosa.
  Pero es una garantía sobre **el tipo**, no sobre **el valor** — un Choice siempre
  devuelve una opción válida, y puede ser la equivocada. "Cannot hallucinate" usa la
  palabra en un sentido distinto del habitual.
- *Velocidad y precio*, verificables por cualquiera con una API key: 70–500 ms y
  "$0.042 / MTok" de input con output gratis.

**Sólo afirma:**

- **"Jev achieves similar levels of intelligence on System One tasks compared to
  existing LLMs"** — la afirmación central, y la que no está demostrada. El post no
  da un solo porcentaje de accuracy.
- Los benchmarks de `evals.typesafe.ai` **no tienen ground truth**: las etiquetas de
  referencia son "an average of the responses of GPT-6 Astra and Claude Fable 5.1,
  both at high thinking". Eso no mide si una respuesta es correcta; mide **cuánto se
  parece al consenso de dos LLMs**. Un modelo no puede superar a su propio juez bajo
  esa métrica, y un error compartido por los dos jueces cuenta como acierto.
- Son evals **propias y auto-declaradas**: el post admite que los workflows fueron
  "made by individuals on our model capabilities team, so some bias could exist", y
  que las queries de demo eran "highly simplified" y que "relatively shorter input
  paints our model in an advantageous light".
- El baseline LLM corre a través de **su propio adapter**
  (`github.com/typesafe-ai/system-one-adapter-python`), del que dicen que "tends to
  be slower and more expensive". El competidor lo instrumenta el vendedor.
- El "193.6x faster, 444.6x cheaper" es, por admisión propia, "the higher end of real
  world gains".

**El hallazgo más útil del sitio de evals es, irónicamente, gratis.** En los cuatro
workflows, la misma familia de modelos rinde muchísimo mejor descompuesta que en un
prompt suelto: `"Haiku 4.5 · workflow · 53.6% · $0.0195 · 12.5 s"` contra
`"haiku 4.5 · prompt · 18.1% · $0.0363 · 21.2 s"`. Ese salto es **de la arquitectura,
no del modelo**: partir la decisión en preguntas atómicas y combinarlas en código. No
hace falta comprar nada para aplicarlo — y como se ve en §2, acá ya está aplicado.

---

## 2. Mapeo al repo

### 2.1 Lo que ya cubrimos por otra vía: el comité *es* composite scoring

`analysis/committee.py:845-857` arma 5–6 jobs (Analista Fundamental, Estratega Macro,
Abogado del Diablo, Portfolio Manager, Behavioral Coach, y Analista de Dividendo
condicional), los corre en paralelo (`_run_agents`, `analysis/committee.py:903`, con
`COMMITTEE.max_workers` en `config.py`), y **la agregación es determinística y vive en
código**: `aggregate()` (`analysis/committee.py:311-416`) hace el promedio ponderado,
y `_lean_to_action()` (`analysis/committee.py:298-308`) mapea el lean a la acción con
los umbrales de `CommitteeConfig` (`strong_buy_lean: 1.5`, `buy_lean: 0.5`,
`reduce_lean: -0.5`, `sell_lean: -1.5` en `config.py`).

Eso es, punto por punto, el patrón *composite scoring* que TypeSafe vende como
novedad. También el *confidence-gated routing*: la confianza baja un escalón por
disenso fuerte o spread ≥ 2.0 (`analysis/committee.py:391-392`), otro escalón por
calidad de dato degradada (`:393-394`), y por debajo de `min_quorum_weight_pct` no hay
veredicto sino `UNAVAILABLE` (`:340-351`). La diferencia real es que nuestra confianza
es una etiqueta `HIGH|MEDIUM|LOW` que el propio modelo se auto-asigna
(`analysis/committee_prompts.py:12`, coercionada en `analysis/committee.py:247-256`),
no una probabilidad calibrada.

**Ahí está el único aporte genuino que Jev traería al comité: reemplazar tres etiquetas
auto-reportadas por una distribución.** Y ahí mismo está el problema.

### 2.2 Dónde no entra, y por qué

**(a) El voto sin argumento es un defecto conocido de este repo, y Jev no puede dar
argumento.** El contrato de cada agente exige `rationale` y `risks`
(`analysis/committee_prompts.py:52`), que se parsean a `key_points` y `concerns`
(`analysis/committee.py:289-290`) y alimentan consenso y disenso en la UI. El repo ya
trató esto como bug dos veces seguidas: `3c39580` "un voto sin argumentos no es un
desacuerdo" y `d88c570` "un voto ilegible es un agente caído, no un HOLD que vota",
con el guard vivo en `analysis/committee.py:406-410`. Un voto de Jev es
**estructuralmente** un voto sin argumentos: el modelo "is not trained to generate
text". No es que a veces no justifique — es que no puede.

**(b) Nuestro state es numérico y con fechas; Jev declara ser malo en las dos cosas.**
Las decisiones del motor se apoyan en P/E, FCF yield, rachas de dividendo, drawdowns
por ventana anclada a la última barra (`CommitteeConfig.drawdown_windows_years`),
Piotroski point-in-time. "Jev is not a calculator" + "reads dates as text" es una
descalificación directa del caso de uso central, no un matiz.

**(c) El seam de proveedor no encaja.** `AIAnalyzer._call_api`
(`analysis/ai_analyzer.py:547-559`) despacha entre claude / openai / nous / xai / groq
y su contrato es `prompt: str -> str`. Jev no es string→string: es
`state + questions -> typed answers`. Un sexto branch ahí sería una mentira de tipos;
el único punto donde entraría limpio es el seam inyectable
`CommitteeAnalyzer(call_fn=...)` (`analysis/ai_analyzer.py` vía
`analysis/committee.py:791-810`), y sólo reescribiendo su firma.

**(d) Todas las superficies de narrativa quedan fuera por definición.**
`generate_long_term_narrative` (`analysis/ai_analyzer.py:282`),
`generate_plan_narrative` (`:330`), `generate_optimizer_advice` (`:398`) y
`analysis/chat_agent.py` producen prosa en español. Jev no genera texto.

---

## 3. Adaptación viable (la variante más chica que aportaría algo)

Descartado el motor, queda un único candidato honesto: **triage de texto antes de que
entre a un prompt**. Concretamente `_ticker_news()` (`analysis/committee.py:743`), que
hoy vuelca noticias al prompt del Abogado del Diablo sin filtro de materialidad.

**Alcance mínimo:**

- Un módulo nuevo `analysis/news_triage.py` con un seam inyectable
  (`ask_fn`), espejo de `CommitteeAnalyzer(call_fn=...)`.
- Una pregunta Noul por titular: *"¿esta noticia es material para la tesis de
  inversión de este ticker?"* → probabilidad → corte en código.
- Bandera de apagado por defecto y fallback a la lista actual sin filtrar.

**Por qué es el único que cierra:** texto corto adentro, booleano afuera, sin
aritmética ni fechas, y el costo de equivocarse es "el DA vio 3 titulares en vez de
otros 3" — no una señal de compra.

**Invariantes que hay que respetar (y que este cambio puede romper si se hace mal):**

| Invariante | Dónde | Cómo se respeta |
|---|---|---|
| Thresholds en `config.py`, nunca inline | `docs/CONTEXT.md §5` | El corte de probabilidad va a un bloque nuevo de config, como `CommitteeConfig` |
| Logging con loguru | `docs/CONTEXT.md §5` | Igual que `analysis/committee.py:860`; y una causa nueva en `AI_FALLBACK` (`config.py:773`) |
| Caché hasheable / versionado de prompt | `CommitteeConfig.prompt_version` | Clave de caché con versión de pregunta, o las respuestas viejas sobreviven al cambio |
| **Determinismo de los tests oráculo** | `tests/*_oracle.py`, `docs/CONTEXT.md §5` | **Este es el riesgo real.** `api.md` no documenta `seed` ni `temperature`: las probabilidades de Jev no son reproducibles por contrato. Ningún test puede assertear sobre una probabilidad de Jev — sólo sobre la lógica de corte, con `ask_fn` stubeado. Si el seam no es inyectable, la suite pasa a depender de la red y el verde deja de ser evidencia |

---

## 4. Veredicto

**Descartar para el motor de decisión. Adoptar (gratis, ya está hecho) la lección de
diseño. Piloto opcional y acotado en triage de texto, no prioritario.**

**El criterio que lo decide no es costo ni latencia — es el producto.** Este repo
produce decisiones sobre números *que vienen con su argumento*, y trata la ausencia de
argumento como un defecto que ya arregló dos veces (`3c39580`, `d88c570`). Jev es, por
construcción, un motor de decisiones sin números y sin argumento. No hay ajuste de
prompt que cierre esa brecha, porque no es una brecha de calidad: es el trade-off que
el producto eligió a propósito.

**Qué evidencia me haría cambiar el veredicto** (las tres, no una):

1. Un benchmark de juicio financiero numérico con **ground truth externo** — resultado
   de mercado o etiqueta humana experta — no etiquetas promediadas de dos LLMs.
2. Una garantía documentada de **determinismo y versionado** (versión de modelo
   pinneable + probabilidades reproducibles), sin la cual los tests oráculo no pueden
   assertear nada.
3. Un camino para obtener **una justificación citable junto a la probabilidad**. Hoy
   la arquitectura lo excluye.

---

## 5. Costo y riesgo de la adaptación mínima

**Costo directo:** 1–2 días para el piloto de triage (módulo + config + tests con stub
+ bandera). Bajo.

**Costo escondido, que es el que importa:** un **sexto proveedor**. Hoy ya cargamos
cinco branches más resolución de credenciales Hermes con su fallback silencioso
(`analysis/ai_analyzer.py:607-647`) — y el repo ya se comió el costo de esa
complejidad: el bug de `temperature=0` que hacía fallar Claude con 400 y lo disfrazaba
de "sin API key" está documentado en el docstring de `_call_claude`
(`analysis/ai_analyzer.py:562-582`). Sumar un proveedor en early access, sin SLA, sin
página de precios verificable más allá del post, y con un contrato de API que **no
encaja** en el seam existente, es deuda estructural a cambio de un filtro de titulares.

**El argumento de costo no aplica acá.** El comité corre 5–6 llamadas sólo en
decisiones pesadas y cachea el veredicto 24 h (`CommitteeConfig.cache_ttl_hours: 24`,
`analysis/committee.py:819-823`). Aun a precios de Opus 5 ($5/$25 por MTok) o de
Haiku 4.5 ($1/$5), el gasto por veredicto son centavos, amortizados por la caché. Un
"444x más barato" sobre una factura de centavos ahorra centavos; un BUY equivocado
cuesta plata de verdad. **La asimetría está al revés de lo que optimiza Jev.**

**Si el enfoque no madura** (startup en early access, producto sin paper, categoría
inventada por el propio vendedor): con la bandera apagada por defecto y el fallback a
la lista sin filtrar, la pérdida se limita a un módulo muerto. **Por eso la bandera no
es opcional** — es la única cosa que hace que el piloto sea reversible.

---

## Fuentes

- `https://typesafe.ai/blog/introducing-system-one-models-and-jev` (el artículo)
- `https://docs.typesafe.ai/llms.txt`, `.../api.md`, `.../model-jaggedness/jev-1.13.md`,
  `.../patterns/composite-scoring.md`, `.../patterns/fan-out.md`,
  `.../concepts/how-to-build-with-system-one.md`
- `https://evals.typesafe.ai/`
- `https://github.com/typesafe-ai/system-one-adapter-python` (MIT, 231 ★ al 2026-09-21)
- Referencia de la API de Anthropic (IDs y precios de Opus 5 / Sonnet 5 / Haiku 4.5 /
  Fable 5.1)
