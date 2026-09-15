# Adaptación multimodelo de los prompts (`analysis/prompts.py` + `analysis/committee_prompts.py`)

> **Estado:** diagnóstico cerrado 2026-09-14. **PR 0 implementado** (rama
> `fercalvino-cu/prompts-multimodelo-pr0`) y **PR 1 implementado** (rama
> `fercalvino-cu/san-juan`); **PR 3 absorbido por PR 0**. El resto sigue
> abierto — tabla de estado y hallazgos de ejecución en §5.0.
> **Alcance:** los 7 prompts de `analysis/prompts.py`, los 8 de `analysis/committee_prompts.py`,
> y los parámetros de API de `analysis/ai_analyzer.py` que los entregan.
> **Decisiones del owner tomadas antes de fijar el plan (2026-09-14):**
> 1. **Contrato de salida portable puro** — nada de `output_config.format` de Anthropic.
>    El JSON se sigue pidiendo en el texto del prompt y se parsea con `extract_json_object`
>    para los cuatro proveedores. Sin bifurcación del embudo.
> 2. **Persona neutra + renombre total** — se elimina la persona «Eres Grok, construido por
>    xAI» y también los campos persistidos y strings de UI que dicen *Grok*, con migración
>    de los planes guardados en disco.

---

## 0. Qué proveedor hay en juego, empíricamente

No se asumió nada: esto es lo que hace el código hoy.

| Hecho | Evidencia |
|---|---|
| El proveedor por defecto es **Anthropic** | `config.py:526` — `AI_PROVIDER` default `"claude"` |
| El modelo por defecto es **`claude-sonnet-4-6`** | `config.py:527` |
| Hay **cuatro** branches de proveedor vivos | `analysis/ai_analyzer.py:377-385` — `claude`, `openai`, `nous`, `xai` |
| `xai` y `nous` van por endpoint **OpenAI-compatible** | `ai_analyzer.py:413-463` (`api.x.ai/v1`, `inference-api.nousresearch.com/v1`) |
| La UI ofrece los cuatro | `dashboard/pages/9_Settings.py:191-219` |
| El selector ofrece modelos que **rechazan** la llamada actual | `9_Settings.py:192` lista `claude-opus-4-7` |
| CONTEXT lo declara multi-proveedor | `docs/CONTEXT.md` §1 — «Multi-proveedor AI (Claude / Grok / OpenAI / Nous)» |

### 0.1 El fallback silencioso (y por qué invalida cualquier verificación de prompts)

`AIAnalyzer.analyze` envuelve todo en `except Exception` y cae al motor rule-based con un
único `logger.warning` (`ai_analyzer.py:88-94`). En la UI, **un 400 de la API, una API key
ausente y una key inválida se ven exactamente igual**: el usuario recibe un veredicto
rule-based presentado sin señal de que la IA no corrió.

Peor: `AIConfig.api_key` (`config.py:530-534`) resuelve `ANTHROPIC_API_KEY or XAI_API_KEY
or OPENAI_API_KEY` **sin mirar `provider`**. Con `provider="claude"` y sólo `XAI_API_KEY`
seteada, se le manda una key de xAI a Anthropic → 401 → fallback silencioso. `config_validator.py:60-67`
sí mapea proveedor→variable correctamente, o sea que el validador y el runtime discrepan:
el validador dice «falta ANTHROPIC_API_KEY» mientras el runtime manda la de xAI igual.

**Consecuencia para este trabajo:** cualquier medición de «¿el prompt nuevo rinde mejor?»
es inverificable mientras el fallback trague la causa. Por eso el Fase 0 es el fallback,
no los prompts.

### 0.2 El defecto que rompe la IA hoy (no es el prompt, es un parámetro)

`_call_claude` (`ai_analyzer.py:389-400`) manda `temperature=0`. Según la documentación
vigente, los parámetros de sampling (`temperature`, `top_p`, `top_k`) **fueron removidos y
devuelven 400** en Claude Sonnet 5, Opus 5, Opus 4.8 y Opus 4.7; siguen aceptados en Opus
4.6 y Sonnet 4.6 ([Prompting Claude Sonnet 5 § Tone and writing
style](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5),
[migration guide](https://platform.claude.com/docs/en/models/sonnet-5/migration-guide#migrating-from-claude-sonnet-4-6-to-claude-sonnet-5)).

Es decir: con el default actual (`claude-sonnet-4-6`) la llamada pasa, pero **cualquier
modelo del selector más nuevo que 4.6 devuelve 400** → fallback silencioso → «la IA no
anda» sin causa visible. `9_Settings.py:192` ya ofrece `claude-opus-4-7`, así que el
defecto es alcanzable desde la UI sin tocar código.

Colateral del mismo branch:
- `max_tokens` default **1024** (`ai_analyzer.py:392`). Con thinking adaptativo encendido
  por defecto en Sonnet 5 / Opus 5, `max_tokens` es el techo de *thinking + texto*; 1024 es
  candidato a truncarse en `stop_reason: "max_tokens"` y producir JSON incompleto
  (el propio `generate_optimizer_advice` ya tiene un branch de error para «incomplete json»,
  `ai_analyzer.py:352-356`). El tokenizer nuevo de Sonnet 5 produce ~30 % más tokens para el
  mismo texto, así que los techos calibrados para 4.6 truncan output equivalente.
- `message.content[0].text` (`ai_analyzer.py:399`) asume que el **primer** bloque es texto.
  Con thinking encendido el primer bloque es un `thinking` block → `AttributeError` →
  fallback silencioso. Hay que iterar `content` y filtrar `block.type == "text"`.
- Ningún branch chequea `stop_reason` antes de leer el contenido.

---

## 1. Inventario de prompts

Tamaños medidos sobre el template fuente (incluye docstring y código de armado; el
prompt renderizado es del mismo orden). `~tok` es char/4, aproximación.

### 1.1 `analysis/prompts.py` (1370 líneas, 7 prompts públicos + 12 helpers)

| # | Función | Línea | Tamaño | Salida esperada | Consumidor |
|---|---|---|---|---|---|
| 1 | `equity_moat_prompt` | 251 | 8,9 K / ~2,2 K tok | JSON 9 campos + **texto libre permitido después del JSON** | `analysis/moat.py:504` |
| 2 | `equity_decision_prompt` | 390 | 8,3 K / ~2,1 K tok | JSON 7 campos + texto libre después | `ai_analyzer.py:99`, `committee.py:516` |
| 3 | `crypto_moat_prompt` | 510 | 8,6 K / ~2,1 K tok | JSON 12 campos + texto libre después | `crypto_analyzer.py:520` |
| 4 | `crypto_decision_prompt` | 648 | 7,0 K / ~1,7 K tok | JSON 7 campos + texto libre después | `ai_analyzer.py:97`, `committee.py:516` |
| 5 | `alert_explanation_prompt` | 762 | 2,8 K / ~0,7 K tok | JSON 2 campos, **«SOLO con JSON válido»** | `alerts/` |
| 6 | `long_term_plan_narrative_prompt` | 831 | 3,6 K / ~0,9 K tok | **Markdown libre** (viñetas `**bold**`), «Nada de JSON» | `ai_analyzer.py:112` |
| 7 | `portfolio_optimizer_advice_prompt` | 925 | 8,2 K / ~2,1 K tok | JSON 6 campos anidados, **«SOLO el objeto JSON»** | `ai_analyzer.py:230` |
| 8 | `plan_level_narrative_prompt` | 1073 | 12,3 K / ~3,1 K tok | JSON 2 campos, **uno de los cuales contiene Markdown** | `ai_analyzer.py:160` |
| 9 | `sector_country_tailwind_prompt` | 1319 | 2,6 K / ~0,7 K tok | JSON 2 campos | `analysis/tailwind.py:341` |

Helpers de contexto compartido: `_macro_factors_output_spec` (103, 1,7 K),
`_hard_decision_constraints_block` (210, 2,1 K), `_tailwind_context_block` (184, 1,4 K),
`_payout_block` (161), `_tristate` (127), `_slope_pct` (142).

### 1.2 `analysis/committee_prompts.py` (396 líneas, 8 prompts públicos)

Todos comparten un único contrato: `AGENT_JSON_SCHEMA` (línea 36) —
`{stance, confidence, key_points, concerns}`, «EXCLUSIVAMENTE un objeto JSON válido, sin
texto antes ni después».

| # | Función | Línea | Tamaño | Nivel |
|---|---|---|---|---|
| 10 | `macro_strategist_prompt` | 113 | ~0,9 K | ticker |
| 11 | `devils_advocate_prompt` | 130 | ~0,7 K | ticker |
| 12 | `portfolio_manager_prompt` | 144 | ~0,6 K | ticker |
| 13 | `behavioral_coach_prompt` | 156 | ~0,5 K | ticker |
| 14 | `plan_strategist_prompt` | 347 | ~0,6 K | portfolio |
| 15 | `risk_manager_portfolio_prompt` | 359 | ~0,7 K | portfolio |
| 16 | `macro_strategist_portfolio_prompt` | 373 | ~0,6 K | portfolio |
| 17 | `devils_advocate_portfolio_prompt` | 385 | ~0,8 K | portfolio |

Más los bloques de contexto: `committee_context_block` (73, 1,7 K) y
`portfolio_committee_context_block` (188, 6,0 K, el más grande del archivo).

**Observación estructural:** `committee_prompts.py` está **notablemente mejor diseñado**
que `prompts.py`. Un solo esquema de salida, delimitadores consistentes (`=== SECCIÓN ===`),
roles cortos sin persona de marca, un solo bloque de datos duros, sin texto libre permitido
alrededor del JSON. La mayor parte de este plan consiste en llevar `prompts.py` al nivel
que `committee_prompts.py` ya tiene.

---

## 2. Marcas de sesgo a Grok / a un proveedor, con cita

### H1 — Persona de marca ajena inyectada en 7 de 9 prompts *(sesgo a Grok, directo)*

`prompts.py:283`, `:443`, `:554`, `:692`, `:794`, `:986`, `:1347` abren con
«**Eres Grok, construido por xAI.**». El docstring del módulo lo declara doctrina
(`prompts.py:8-11`): *«This ensures Grok receives instructions in its own persona
regardless of which provider (Claude, Grok, GPT-4o) is actually executing the request»*.
Reforzado a lo largo del cuerpo: «tu voz característica de Grok» (`:489`, `:742`),
«**TAREA (con tu voz propia de Grok)**» (`:1027`), «Grok decide el número exacto» (`:1032`),
«tu voz Grok» (`:1044`).

**Por qué es un problema, no sólo cosmética.** El rol en el prompt es una palanca real:
la doctrina de Anthropic lo confirma
([*Give Claude a role*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#give-claude-a-role)).
Pero decirle a Claude que *es otro modelo* pelea con su auto-conocimiento; la doctrina
tiene una sección dedicada a cómo se declara la identidad del modelo
([*Model self-knowledge*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#model-self-knowledge))
y el patrón es afirmar la identidad real, no suplantarla. El contenido que la app
realmente quiere —directo, escéptico, sin corporativismo— es **independiente de la marca**
y sobrevive intacto a la sustitución.

**Adaptación (portable):** rol neutro y descriptivo en una o dos oraciones
(«Sos un analista de inversión senior, riguroso y basado en datos, especializado en X.
Escribís directo y escéptico: nombrás lo que los números contradicen y no usás lenguaje
corporativo ni hype»). Mismo registro, cero marca.
**Riesgo de no hacerlo:** con `provider="claude"` el modelo arranca cada respuesta bajo una
premisa falsa sobre quién es; y los usuarios que ven el `reasoning` leen referencias a un
proveedor que la app no está usando.

### H2 — El bug de proveedor es un parámetro, no un prompt *(dependencia de `temperature`)*

`ai_analyzer.py:395` (`_call_claude`), `:406` (`_call_openai`), `:449` (`_call_openai_compatible`)
mandan `temperature=0` incondicionalmente. Ver §0.2.

**Adaptación (específica de Claude, obligatoria):** en `_call_claude`, omitir `temperature`.
Los branches OpenAI-compatible pueden conservarlo — el parámetro sigue siendo válido ahí,
y ése es justamente el punto: es una divergencia de **transporte**, no de prompt, y por eso
no rompe la portabilidad del prompt.
**Riesgo de no hacerlo:** el plan entero es inverificable. Con cualquier modelo del selector
posterior a 4.6, la IA nunca corre y el A/B de prompts mide el motor rule-based contra
sí mismo.

### H3 — El contrato de salida se contradice entre prompts hermanos *(delimitadores y formato)*

Cuatro prompts permiten explícitamente texto fuera del JSON:

> `prompts.py:371`, `:493`, `:626`, `:746` — «Podés agregar un breve comentario adicional
> **después del JSON** si ayuda a expresar matices»

Cuatro lo prohíben con la misma fuerza:

> `prompts.py:819` — «Respondé **SOLO** con JSON válido»
> `prompts.py:1042` — «Respondé **SOLO** con el objeto JSON válido. No agregues **NADA** de texto antes ni después»
> `prompts.py:1287` — «Devolvé un objeto JSON válido (y **NADA** de texto fuera del JSON)»
> `committee_prompts.py:37` — «Respondé **EXCLUSIVAMENTE** con un objeto JSON válido»

Y uno pide Markdown puro prohibiendo JSON:

> `prompts.py:910` — «Respondé SOLO con el texto en el formato pedido. **Nada de JSON**»

Los cinco caminos desembocan en el **mismo** parser, `analysis/utils.py:67
extract_json_object`, más `_strip_code_fence` (`ai_analyzer.py:56`). O sea: el permiso de
`:371` existe únicamente porque el parser tolera basura alrededor — es una laxitud del
prompt cubriendo una laxitud del parser, y nadie mide cuál de los dos está fallando.

**Adaptación (portable):** un solo contrato para todos los prompts JSON, redactado como
`committee_prompts.py:37`. Borrar el permiso de comentario adicional de `:371`, `:493`,
`:626`, `:746`. Los matices ya tienen campo propio (`reasoning`).
**Riesgo de no hacerlo:** el modelo gasta tokens de `max_tokens` en prosa post-JSON que
nadie lee, y con `max_tokens=1024` esa prosa es exactamente lo que empuja el JSON a
truncarse.

### H4 — Se pide Markdown donde hace falta estructura parseable

`prompts.py:894-901` pide la narrativa como Markdown con encabezados en negrita
(`**Resumen del plan en una frase**`, `**Fortalezas…**`, …). `prompts.py:1289-1296`
repite la misma estructura **dentro** del campo JSON `narrative`, o sea Markdown
serializado dentro de una string JSON — y `:1303` lo ejemplifica así
(`"narrative": "**Resumen del plan en una frase** ..."`).

La consecuencia: la app no puede renderizar ni verificar secciones individuales, y ningún
test puede afirmar «la sección *Riesgos* existe» sin parsear Markdown con regex. Es un
formato de presentación haciendo de estructura de datos.

La doctrina es explícita sobre que el estilo del prompt arrastra el estilo de la respuesta
y sobre preferir decir qué hacer antes que qué no hacer
([*Control the format of responses*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#control-the-format-of-responses)).

**Adaptación (portable):** convertir las secciones en campos del JSON
(`resumen`, `fortalezas: list[str]`, `riesgos: list[str]`, `p10_lectura`,
`duracion_ingreso`, `recomendaciones: list[str]`, `cierre`), y que el Markdown lo arme la
UI. Es lo mismo que `macro_factors` ya hace bien: el paso de texto libre a objeto
estructurado está documentado en `prompts.py:16-17` como una mejora deliberada; esto la
termina de aplicar.
**Riesgo de no hacerlo:** la narrativa persistida en `PlanSnapshot` queda como un blob
opaco — no se puede re-renderizar, ni diffear entre dos guardados, ni testear.

### H5 — Negaciones acumuladas y jerga anti-alucinación repetida *(sesgo a modelos viejos)*

La instrucción «no inventes» aparece al menos **nueve** veces, en variantes:

| Cita | Texto |
|---|---|
| `prompts.py:122` | «**No fuerces** factores de relleno ni narrativas genéricas» |
| `prompts.py:205` | «**NO inventes** colas de viento adicionales» |
| `prompts.py:1019` | «**NO inventes** colas de viento adicionales» |
| `prompts.py:1129` | «**NO inventes** colas de viento adicionales» |
| `prompts.py:1176` | «mencioná que reflejan supuestos realistas» (+ `:1187-1188` «el LLM **nunca inventa**») |
| `prompts.py:1297` | «**NO inventes** números de decumulación» |
| `prompts.py:1362` | «**NO inventes** colas de viento adicionales ni cambies el score curado» |
| `committee_prompts.py:106` | «anclá tus argumentos a estos números, **no inventes otros**» |
| `committee_prompts.py:125` | «**no inventes** datos macro ni uses tu memoria de entrenamiento» |
| `committee_prompts.py:328` | «usalo, **no inventes**» |
| `committee_prompts.py:339` | «anclá tus argumentos a estos números, **no inventes otros**» |

Además el énfasis apilado: `prompts.py:121` — «**REGLA CRÍTICA OBLIGATORIA**»;
`:306`, `:483`, `:578`, `:723`, `:1021` — «Instrucción estructural (**obligatoria**)»
seguida de «Usá **EXACTAMENTE** el formato»; `:285`, `:445`, `:556`, `:694`, `:796`,
`:868`, `:988`, `:1251`, `:1349` — «**IDIOMA OBLIGATORIO**: Responde **SIEMPRE** en español
… **Nunca** uses inglés», repetida nueve veces, y en varias enumerando campos que ese
prompt **no tiene** (`:445` menciona `key_strengths`/`key_risks`, que no existen en el
contrato de `equity_decision_prompt`; `:556`, `:694`, `:796` copian la misma lista muerta).

La doctrina vigente tiene dos cosas que decir acá. Primero: la instrucción rinde más si se
da en positivo con su motivo, no como prohibición apilada — el ejemplo canónico es
literalmente «en vez de *NEVER use ellipses*, explicá por qué»
([*Add context to improve performance*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#add-context-to-improve-performance)).
Segundo, y más importante: *«si tus prompts antes empujaban al modelo a ser más exhaustivo
o a usar herramientas más agresivamente, **bajá esa guía**; los modelos 4.6+ son más
proactivos y pueden sobre-disparar con instrucciones que los modelos previos necesitaban»*
([Migration considerations §6](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#migration-considerations)).
Sonnet 5 además sigue las instrucciones **más literalmente** y no generaliza de un ítem a
otro ([*More literal instruction following*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5#more-literal-instruction-following))
— lo que convierte la lista de campos inexistentes de `:445` en ruido activo, no inocuo.

**Adaptación (portable):** una sola declaración de idioma por prompt, sin enumerar campos;
un solo enunciado de anclaje a datos, con su motivo, en el bloque de datos duros; borrar
la repetición triple del «no inventes tailwinds» (`:205`/`:1019`/`:1129` dicen lo mismo
tres veces en tres capas del mismo pipeline).
**Riesgo de no hacerlo:** sobre-disparo — el modelo prioriza la defensa sobre el análisis y
devuelve `macro_factors: []` y `reasoning` genéricos por cautela, que es exactamente el
fracaso que la repetición quería evitar. Y ~400 tokens por llamada de instrucción muerta.

### H6 — Few-shot desbalanceado: un solo ejemplo, y es negativo

`prompts.py:240-242`:

> **FEW-SHOT DE RIGOR (estilo, no copiar números):**
> Empresa con ROE 22%, moat Wide, pero D/E 3.5 y valuación en percentil alto → action HOLD o
> REDUCE, confidence MEDIUM/LOW, allocation ≤ 3%. Nunca STRONG BUY por narrativa de marca si
> el leverage viola constraints.

Es **un** ejemplo, **de un solo lado** (el caso que degrada), sin delimitadores, y no muestra
el formato de salida sino una conclusión en prosa. No hay ningún ejemplo de una compra
legítima. La doctrina pide ejemplos **relevantes, diversos y envueltos en `<example>` /
`<examples>`**, y recomienda 3–5
([*Use examples effectively*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#use-examples-effectively)).
Los prompts de Sonnet 5 además funcionan mejor con ejemplos **positivos** que con
instrucciones de qué no hacer
([*Response length and verbosity*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5#response-length-and-verbosity)).

Nota de interacción con el motor: desde SIGNAL-1/6 (`analysis/strategy.py`,
`apply_safety_overlay`) el veredicto del LLM se **pisa** contra `decide()` y sólo puede ir
hacia abajo. Un few-shot que sólo enseña a degradar refuerza una asimetría que el overlay
ya garantiza por construcción; lo que el prompt tendría que enseñar es el caso donde el
LLM **coincide** con el motor, que es la mayoría del tráfico.

**Adaptación (portable):** 2–3 ejemplos, uno por cuadrante (constraint violado → degrada;
fundamentals sólidos + técnico confirmando → BUY con confidence justificada; datos
faltantes → HOLD con `macro_factors: []`), envueltos en `<examples><example>…</example></examples>`.
**Riesgo de no hacerlo:** sesgo sistemático a HOLD/REDUCE mal atribuido al modelo cuando
en realidad lo instaló el prompt; y las alertas `score_drop` se explican con el mismo sesgo
heredado.

### H7 — Delimitadores inconsistentes entre archivos y dentro de cada uno

En `prompts.py` conviven cuatro convenciones simultáneas:

| Convención | Ejemplo |
|---|---|
| `--- SECCIÓN ---` | `:451` `--- ANÁLISIS FUNDAMENTAL ---`, `:472`, `:479`, `:487` |
| `**Sección**` Markdown | `:560` `**Datos actuales del mercado:**`, `:990`, `:1003`, `:1255` |
| `SECCIÓN:` a secas | `:287` `EMPRESA:`, `:288` `SECTOR:` |
| `━━━━━` (U+2501) | `:320`, `:332`, `:344`, `:355`, `:365` — separadores de rúbrica |

`committee_prompts.py` usa `=== SECCIÓN ===` de forma consistente (`:106`, `:108`, `:109`,
`:339`, `:342`, `:343`), lo que lo vuelve el modelo a seguir.

La doctrina recomienda **XML tags** para separar instrucciones, contexto, ejemplos e input
variable, con nombres consistentes entre prompts
([*Structure prompts with XML tags*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#structure-prompts-with-xml-tags)).

**Clasificación honesta:** los XML tags son **doctrina de Anthropic**, no un estándar
neutral — pero son *portables de hecho*: son texto plano, no una feature de API, y no
degradan en un endpoint OpenAI-compatible. Los clasifico como «Claude-first, sin costo
de portabilidad», distinto de `output_config.format`, que sí es Claude-only y quedó
**fuera de alcance** por la decisión del owner.
**Adaptación:** una convención única por archivo. Mínimo viable y portable: adoptar
`=== SECCIÓN ===` de `committee_prompts.py` en todo `prompts.py`. Si se decide subir a XML
(`<datos_duros>`, `<instrucciones>`, `<formato_salida>`, `<examples>`), hacerlo en los dos
archivos a la vez.
**Riesgo de no hacerlo:** con cuatro convenciones el modelo no distingue un encabezado de
sección de un dato; `:560` «**Datos actuales del mercado:**» se lee igual que un
`**bold**` de énfasis dentro de una instrucción.

### H8 — El orden del prompt contradice la guía de contexto largo

Los prompts grandes (`plan_level_narrative_prompt`, ~3 K tok;
`portfolio_optimizer_advice_prompt`, ~2 K tok) ponen persona e instrucciones **arriba** y la
tarea al final, con los datos en el medio. La doctrina de contexto largo dice lo contrario:
**datos arriba, query e instrucciones abajo**, con una mejora medida de hasta 30 % en
inputs multi-documento
([*Long context prompting*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#long-context-prompting)).

Hoy el orden real de `equity_decision_prompt` es: persona (`:443`) → idioma (`:445`) →
datos (`:447-477`) → macro (`:479-485`) → constraints (`:486`) → instrucción (`:487-491`)
→ formato (`:493-502`). Está a mitad de camino: los datos ya están antes de la instrucción,
pero la persona y el bloque de idioma cortan el arranque. `plan_level_narrative_prompt`
está mejor ordenado (`:1249` persona, `:1255-1282` datos, `:1286-1306` tarea y formato).

**Adaptación (portable):** rol corto arriba (una oración; la doctrina dice que una alcanza),
datos inmediatamente después, instrucciones y contrato de salida al final. Mover el bloque
de idioma al final, junto al contrato de salida, donde pertenece.
**Nota de caching:** es además lo que habilita prompt caching si algún día se activa —
el prefijo estable (rol + rúbrica) queda primero y lo volátil (datos del ticker) después.
Hoy no hay `cache_control` en ninguna llamada, así que es beneficio futuro, no actual.
**Riesgo de no hacerlo:** menor, pero acumulativo en los dos prompts grandes.

### H9 — Instrucciones de estilo que pelean con los defaults de los modelos actuales

`prompts.py:369` («Escribilo como prosa fluida y analítica (no como lista seca)»),
`:489`, `:742` («prosa natural, analítica, directa … Usá oraciones completas») conviven con
`:894` («usá viñetas») y `:1289` («estructurada exactamente así con viñetas»). O sea: el
mismo archivo pide prosa y viñetas según el prompt, y en `plan_level_narrative_prompt`
pide viñetas *dentro* de un campo que otro prompt pediría en prosa.

Sonnet 5 calibra la longitud según la complejidad de la tarea y no según una verbosidad
fija; si el producto depende de un estilo concreto hay que tunearlo explícitamente y con
ejemplos positivos
([*Response length and verbosity*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5#response-length-and-verbosity)).
Opus 5 es la excepción de verbosidad —responde más largo por defecto y el `effort` no lo
cambia de forma confiable— y hay que pedir concisión explícitamente
([*Communication style and verbosity*](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#communication-style-and-verbosity)).

Los límites de longitud existen pero están sólo en dos prompts (`:908` «180-280 palabras»,
`:1289` idem). Los demás no tienen techo — y son los que van con `max_tokens=1024`.

**Adaptación (portable):** techo de longitud explícito y por campo en todos los prompts
con texto libre; una sola política de formato por campo (prosa **o** viñetas, no ambas);
si H4 se aplica, las viñetas dejan de ser un problema porque pasan a ser listas JSON.
**Riesgo de no hacerlo:** con Opus 5 en el selector, los campos sin techo se estiran hasta
`max_tokens` y truncan el JSON.

### H10 — Restos de Grok fuera de los prompts *(alcance del renombre)*

El nombre está también donde no es prompt:

| Ubicación | Qué |
|---|---|
| `ai_analyzer.py:219` | docstring «Generate Grok voice + human-manageable…» |
| `ai_analyzer.py:262` | **string de UI**: «sin necesidad de Grok» |
| `ai_analyzer.py:343` | log «Optimizer Grok advice generation failed» |
| `ai_analyzer.py:348-349` | **string de UI**: «Grok/xAI está con rate limit» — se muestra cuando cualquier proveedor devuelve 429 |
| `ai_analyzer.py:374` | **string de UI**: «Núcleo generado por reglas del perfil (Grok no disponible)» |
| `analysis/strategy.py:396` | comentario «Grok allocation recommendation» |
| `analysis/moat.py:139` | comentario «from Grok prompt» |
| `analysis/crypto_analyzer.py:18`, `:88`, `:91` | comentarios «Grok-approved», «Grok-recommended» |
| `data/plan_store.py` (via tests) | **campos persistidos** `grok_core_holdings`, `ai_grok_narrative` |
| `tests/test_prompts.py:6`, `:177`, `:221`, `:298`, `:346`, `:435`, `:682` | aserciones de la persona |
| `tests/test_prompts.py:495` | assert sobre un string de UI con «grok» |
| `tests/test_plan_store.py:32-33`, `:70-72`; `tests/test_tailwind.py:452`, `:471-472` | los campos persistidos |

Los tres strings de `ai_analyzer.py` son los peores: **son mensajes visibles** que le dicen
al usuario que falló *Grok* cuando el proveedor configurado es Anthropic. Son literalmente
el fallback silencioso (§0.1) mintiendo sobre la causa.
**Riesgo de no hacerlo:** el renombre de prompts queda cosmético y el usuario sigue viendo
el nombre del proveedor equivocado en el momento exacto en que necesita diagnosticar.

### H11 — El comité pide actualidad macro a la memoria del modelo (o la prohíbe sin darle datos)

`committee_prompts.py:121-126` inyecta hechos macro fechados **sólo si `macro_context` no
está vacío**, y entonces prohíbe usar la memoria. Si `macro_context` está vacío, el prompt
queda pidiendo evaluación macro (`:114-119`) sin fuente y sin prohibición → el agente usa su
corte de entrenamiento como si fuera actualidad, y el resto del comité razona sobre eso.

El mismo patrón, más crudo, en `prompts.py`: «CONTEXTO MACRO GLOBAL Y NACIONAL A CONSIDERAR
(**usá tu conocimiento actual**…)» en `:302`, `:479`, `:574`, `:719`, `:1016`. «Conocimiento
actual» es precisamente lo que un LLM no tiene. La lista curada que sigue es de *categorías*
(«política de tasas», «geopolítica»), no de hechos, así que no sustituye la fuente.

**Adaptación (portable):** cuando no hay `macro_context` fechado, decir explícitamente que
no hay datos macro actuales disponibles y que `macro_factors` debe reflejar sólo factores
**estructurales** verificables contra los números del prompt — nunca eventos ni niveles.
Es el mismo criterio que el proyecto ya aplica a los tailwinds curados (`:202`, «dato
CURADO, fuente de verdad») y a los drags del MC (`:1187-1188`, «el LLM sólo DESCRIBE,
nunca inventa»). Falta aplicarlo al macro.
**Riesgo de no hacerlo:** el único hallazgo con consecuencia financiera directa. Un factor
macro alucinado con fecha implícita entra en `macro_factors`, se persiste en
`PlanSnapshot.macro_risks`, y se le muestra al usuario como análisis del plan meses después.

---

## 3. Portable vs. específico de Claude

La app soporta cuatro proveedores hoy (§0) y el owner eligió **contrato de salida portable
puro**. Esta es la partición resultante.

**Portable — mejora con cualquier modelo, sin bifurcar código:**
H1 (persona neutra), H3 (contrato único de salida), H4 (Markdown → campos JSON),
H5 (deduplicar negaciones), H6 (few-shot balanceado), H7 (delimitador único),
H8 (orden datos→instrucción), H9 (techos de longitud), H10 (renombre), H11 (macro sin memoria).
**Son 10 de los 11 hallazgos.** Esto no es casualidad: casi todo el sesgo a Grok era
*contenido*, y el contenido es portable.

**Específico de Claude — vive en `_call_claude`, no en los prompts:**
H2 (`temperature`), `max_tokens`, lectura de `content` con bloques de thinking,
chequeo de `stop_reason`, y el catálogo de modelos de `9_Settings.py`. Todo esto queda
confinado a `analysis/ai_analyzer.py:389-400` y al selector: **ningún prompt cambia por
proveedor**, que es la garantía de portabilidad que el owner pidió.

**Deliberadamente fuera de alcance (decisión del owner, 2026-09-14):**
- `output_config.format` / structured outputs — garantizaría JSON válido por schema pero es
  Claude-only y forzaría bifurcar el embudo `_call_api`.
  [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
- Prefill de assistant — **no se usa hoy y no debe introducirse**: devuelve 400 en todos los
  modelos 4.6+.
  [Migrating away from prefilled responses](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices#migrating-away-from-prefilled-responses).
- Prompt caching (`cache_control`) — no hay ninguno hoy; H8 deja el terreno preparado pero
  activarlo es otra serie.
  [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
- `thinking` / `effort` explícitos — Sonnet 5 y Opus 5 corren thinking adaptativo por
  defecto sin pedirlo; no hace falta tocarlo salvo que una medición lo pida.
  [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking).

---

## 4. Impacto aguas abajo

### 4.1 Qué consume estos prompts

```
prompts.py ──┬─ equity_moat_prompt ........ moat.py:504 → moat.py:531 extract_json_object
             ├─ equity_decision_prompt .... ai_analyzer.py:99  → _parse_response:468
             │                              committee.py:516   → committee.py:124/143
             ├─ crypto_moat_prompt ........ crypto_analyzer.py:520 → :540
             ├─ crypto_decision_prompt .... ai_analyzer.py:97 / committee.py:516
             ├─ alert_explanation_prompt .. alerts/
             ├─ long_term_plan_narrative .. ai_analyzer.py:112 → _strip_code_fence (SIN parseo)
             ├─ portfolio_optimizer_advice. ai_analyzer.py:230 → :322 extract_json_object
             ├─ plan_level_narrative ...... ai_analyzer.py:160 → :183 extract_json_object
             └─ sector_country_tailwind ... tailwind.py:341 → :350
committee_prompts.py (8) .................. committee.py:34 → :124/:143
                                            chat_agent.py:121 (mismo parser)
```

Todos convergen en `analysis/utils.py:67 extract_json_object`.

### 4.2 Qué rompe cada cambio

| Cambio | Rompe | Acción |
|---|---|---|
| **H1** persona neutra | `tests/test_prompts.py:177,221,298,346,435,682` (6 asserts `"Eres Grok, construido por xAI"`) y el docstring `:6` | Reescribir los 6 asserts contra el rol neutro. Es el único test que valida la voz; conviene que valide **ausencia de marca de proveedor** (`"Grok" not in prompt`), que es el invariante real |
| **H10** renombre de campos | `data/plan_store.py` (`grok_core_holdings`, `ai_grok_narrative`), `tests/test_plan_store.py:32-33,70-72`, `tests/test_tailwind.py:452,471-472`, `tests/test_prompts.py:495`, `portfolio/optimizer.py` (`OptimizationResult`) | **Migración de datos**: `data/retirement_plans.json` del usuario tiene los nombres viejos. `PlanSnapshot.from_dict` debe leer ambos y escribir el nuevo. Sin esto, planes guardados pierden el núcleo y la narrativa |
| **H3** contrato único | Nada en tests hoy | Agregar un test de invariante: *ningún prompt permite texto fuera del JSON* |
| **H4** Markdown → campos | `ai_analyzer.py:160-215` (`generate_plan_narrative` arma `{"narrative", "macro_risks"}`), `dashboard/pages/12_Plan.py` (renderiza `narrative`), `PlanSnapshot.narrative` persistido | El de mayor riesgo. Requiere que `generate_plan_narrative` componga el Markdown desde los campos y siga devolviendo `narrative: str`, para que UI y snapshots guardados no cambien de forma. Los planes viejos siguen leyéndose porque el campo persistido no cambia |
| **H6** few-shot | `tests/test_prompts.py:276` (`assert "FEW-SHOT" in prompt or …`) | Sigue pasando si se mantiene el literal `FEW-SHOT`; si se pasa a `<examples>`, actualizar el assert |
| **H5** deduplicar idioma | `tests/test_prompts.py` no lo asserta | Agregar assert de que la declaración de idioma aparece **exactamente una vez** |
| **H7** delimitadores | `tests/test_prompts.py:273-274` (`"CONSTRAINTS DUROS"`, `"PASOS DE RAZONAMIENTO"`) | Conservar esos literales como nombres de sección, o actualizar los dos asserts |
| **H2** `temperature` | Nada. `tests/test_strategy.py:243` usa `provider="xai"` con un fake | Agregar un test que afirme que `_call_claude` **no** manda `temperature` (mock del cliente) |
| **H11** macro sin memoria | `tests/test_prompts.py:241-244` (asserts sobre `macro_factors`) | Compatible; agregar el caso «sin `macro_context`» |

### 4.3 Lo que **no** cambia

El contrato de campos del JSON (`action`, `confidence`, `rationale`, `risks`,
`recommended_max_allocation_conservative`, `reasoning`, `macro_factors`) se mantiene
**idéntico**. `_parse_response` (`ai_analyzer.py:466-504`), `Decision`, `MoatDetail`,
`CryptoMoatDetail` y `apply_safety_overlay` no se tocan. La única excepción es H4, y ahí
la compatibilidad se preserva recomponiendo `narrative` en `ai_analyzer`, no cambiando el
campo persistido.

---

## 5. Plan por fases (un PR por fase)

### 5.0 Estado de la serie

| PR | Qué | Estado | Commit / rama | Fecha |
|---|---|---|---|---|
| **PR 0** | El fallback deja de mentir sobre la causa (+ H10 completo) | ✅ **Mergeado** | `4462093` (#121), rama `fercalvino-cu/prompts-multimodelo-pr0` | 2026-09-14 |
| **PR 1** | `_call_claude` deja de rechazar los modelos actuales | ✅ **Mergeado** | `129fcf1` (#122), rama `fercalvino-cu/san-juan` | 2026-09-14 |
| **PR 1.5** | Desactivar la bomba de calendario de `test_tracker_curve_oracle` (hallazgo (k)) | ✅ **Implementado** | `c6181f4`, rama `fercalvino-cu/continuar-prs-o-arreglar-findings` | 2026-09-14 |
| **PR 2** | Persona neutra (H1) + contrato de salida único (H3) | ✅ **Implementado** | `0b541c0`, misma rama | 2026-09-14 |
| ~~PR 3~~ | ~~Renombre total y migración de planes guardados (H10)~~ | 🔀 **Absorbido por PR 0** (decisión del owner, 2026-09-14) | — | 2026-09-14 |
| PR 4 | Higiene de instrucciones: idioma, negaciones y few-shot (H5, H6) | ⏳ Abierto | — | — |
| PR 5 | Estructura: delimitador único y orden datos→instrucción (H7, H8, H9) | ⏳ Abierto | — | — |
| PR 6 | Markdown → campos estructurados (H4) | ⏳ Abierto | — | — |
| PR 7 | El macro deja de salir de la memoria del modelo (H11) | ⏳ Abierto | — | — |

> **Numeración canónica (resuelta 2026-09-14).** Esta tabla y los cuerpos de §5 se
> contradecían: la tabla llamaba «PR 4» a la estructura y «PR 5» a la higiene, y los cuerpos
> al revés. **Gana la numeración de los cuerpos** —son los que llevan el «Qué / Por qué /
> Aceptación» que un implementador ejecuta, así que un lector que entre por el cuerpo no
> puede equivocarse—. Queda, para todo el archivo:
> **PR 4 = higiene de instrucciones (H5, H6)** y **PR 5 = estructura (H7, H8, H9)**.
> La tabla de arriba ya está corregida; los cuerpos no se tocaron.

**Orden recomendado (revisado 2026-09-14, con PR 1.5 y PR 2 ya implementados):**
~~PR 1.5~~ → ~~PR 2~~ → **PR 4 → PR 5 → PR 7 → PR 6**. Ninguno de los cuatro PRs que quedan
depende de un hallazgo sin cerrar en sus criterios *sustantivos*: los de PR 4/5/7 son
estáticos sobre el string renderizado y los de PR 6 se ejercitan con `_call_api` mockeado,
igual que los oráculos de PR 0.

`analysis/prompts.py` **ya no está intacto**: PR 2 lo reescribió. Las citas de línea de §2 y
§5 que apuntan a lo que PR 2 tocó están **consumidas** —las 7 aperturas «Eres Grok» de
`:283, :443, :554, :692, :794, :986, :1347` y los 4 permisos «después del JSON» de
`:371, :493, :626, :746` ya no existen—. Las que quedan **se corrieron ~23 líneas hacia
abajo** por el bloque de constantes nuevo (`ANALYST_ROLE`, `JSON_ONLY_CONTRACT`), así que
PR 4 y PR 5 deben re-localizar antes de editar, no confiar en el número: «IDIOMA
OBLIGATORIO» ×9, los `key_strengths`/`key_risks` muertos que §5 citaba en
`:285, :445, :556, :694`, y los 5 «usá tu conocimiento actual» de
`:302, :479, :574, :719, :1016`. El criterio «`make check` verde» pasó de no verificable a
**verificado**: lo destrabó PR 1.5.

> **Nota de entorno (confirmada al ejecutar PR 1.5 / PR 2):** `make check` no corre tal cual
> en un worktree limpio — `ruff` no está en `requirements.txt` (sólo en
> `.github/workflows/ci.yml:32`), así que `make lint` muere con
> `venv/bin/ruff: No such file or directory`. Hay que instalarlo en el venv a mano
> (`venv/bin/pip install ruff`) antes de poder afirmar nada sobre el criterio. Sigue sin
> arreglarse: es un PR de infraestructura, ajeno a esta serie.

Los hallazgos (b) e (i) quedan como **deuda acotada, explícitamente arrastrable**:
`parametro_rechazado` es una causa de **transporte** y los cinco PRs abiertos son de
**prompt**, así que no contaminan nada. Lo único pendiente ahí es una línea de docstring
desactualizada en `tests/test_ai_fallback_cause_oracle.py` (la causa que describe cambió con
PR 1; la conclusión no).

#### Hallazgos de la ejecución de PR 0

**(a) No hizo falta migración de disco — no hay shim.** Verificado antes de escribir
una sola línea de migración: `data/retirement_plans.json` **no existe** en el repo (es un
artefacto de runtime, gitignoreado) y `grep -o 'grok[a-z_]*'` sobre él no devuelve nada.
Leyendo la serialización: `PlanSnapshot.to_dict` es un `asdict(self)` plano
(`data/plan_store.py:366`) sobre campos que ya se llamaban `core_holdings` / `narrative` /
`core_from_ai`, y **no hay `from_dict`** — la lectura reconstruye por nombre de campo del
dataclass. Los cinco `grok_*` vivían **sólo en memoria** sobre `OptimizationResult`, que
nunca se persiste. El renombre es por lo tanto puramente in-process: ni shim, ni lectura de
nombres viejos, ni bump de `ENGINE_VERSION`.

**(b) `parametro_rechazado` no se puede verificar contra la API real; queda para PR 1.**
`_call_claude` sigue mandando `temperature=0` (§0.2), que los modelos actuales rechazan con
400 — o sea que *toda* llamada real devolvería esa causa, lo que la vuelve inútil como
evidencia de que la clasificación funciona. Se verifica con cliente mockeado en
`tests/test_ai_fallback_cause_oracle.py` (`TestClasificacionDeLaExcepcion`,
`TestLasCausasSonDistinguibles`), que es exactamente el mecanismo que la UI ve. Arreglar el
parámetro es PR 1 y la restricción del encargo de PR 0 lo prohíbe explícitamente.

**(c) El cero de `grep -ri grok` depende todavía de PR 2 — y de dos excepciones legítimas.** ✅ *criterio resuelto (owner, 2026-09-14) — ver el recuadro al final.*
Fuera de `analysis/prompts.py` y `tests/test_prompts.py` quedan **seis** ocurrencias (cuatro
al cerrar PR 0, más dos que agregaron los propios tests de PR 0 y PR 1) que no
son restos sino el **nombre propio del proveedor xAI** — el mismo criterio con el que §7 del
encargo deja intacto el «Multi-proveedor AI (Claude / Grok / OpenAI / Nous)» de
`docs/CONTEXT.md` §1:

| Ubicación | Qué es |
|---|---|
| `config.py` — `AI_PROVIDER_DISPLAY["xai"]` | display name del proveedor; es *la* pieza que hace cumplir «ningún string nombra otro proveedor» |
| `dashboard/pages/9_Settings.py:194` | **IDs de modelo reales** de xAI (`grok-4.3`, `grok-build-0.1`) en el selector |
| `dashboard/pages/9_Settings.py:200,214` | etiqueta del proveedor en el selector + el branch que la lee |
| `dashboard/pages/10_About.py:284` | lista de proveedores soportados |
| `tests/test_ai_fallback_cause_oracle.py:371` | comentario que compara las marcas «Grok (xAI)» / «Claude (Anthropic)» — *la agregó PR 0* |
| `tests/test_claude_transport_oracle.py:118` | `AIConfig(provider="xai", model="grok-4.3")` — *la agregó PR 1* |

> **Resuelto (owner, 2026-09-14) — allowlist por ubicación.** El criterio literal
> «`grep -ri grok` = 0 fuera de `prompts.py` / `test_prompts.py`» era **inalcanzable sin
> renombrar identificadores de la API de xAI**, que no son marca sino contrato. Queda
> reescrito así:
>
> > **Criterio (c):** `grep -rin grok --include='*.py' .` (excluyendo `venv/` y
> > `__pycache__/`) no devuelve ninguna ocurrencia fuera de estas cuatro ubicaciones:
> > `AI_PROVIDER_DISPLAY` en `config.py`, el catálogo de modelos de xAI y su etiqueta de
> > proveedor en `dashboard/pages/9_Settings.py`, la lista de proveedores de
> > `dashboard/pages/10_About.py`, y cualquier archivo bajo `tests/` que ejercite el
> > proveedor `xai`.
>
> **Por qué esta y no las otras tres.** Es la única que sigue atrapando el defecto que
> H10 nombraba —un string de UI que nombra al proveedor equivocado, como los 7 de
> `2_Stock_Analysis.py` que PR 0 encontró fuera de la tabla de H10 (hallazgo (d))— y que
> además puede fallar. El «invariante semántico» («ningún string mostrado al usuario
> nombra un proveedor distinto del configurado») describe bien la intención pero **no
> está cubierto por ningún test**: `TestNingunStringNombraOtroProveedor`
> (`tests/test_ai_fallback_cause_oracle.py:361-376`) sólo barre
> `AI_FALLBACK.message(cause, provider)`, un conjunto generado y cerrado;
> `AI_PROVIDER_DISPLAY` no tiene más consumidores que `config.py:624` y ese test. Un
> `st.caption("Grok sugiere…")` nuevo lo pasaría entero. Adoptarlo sería declarar cubierto
> lo que no lo está — el mismo defecto que PR 0 acaba de arreglar en la capa de IA, esta
> vez en la capa de criterios. «Sólo prompts renderizados» es el criterio propio de PR 2 y
> dejaría al resto del repo sin criterio; «dejarlo literal» conserva un criterio que no
> puede ponerse en verde nunca. El costo de mantenimiento es cero por PR: la cuarta
> excepción está escrita por **rol** («tests que ejercitan `xai`»), no por enumeración, así
> que los tests multiproveedor que agreguen PR 2/4/5/6/7 no obligan a editar la lista —
> que es exactamente lo que ya pasó dos veces (`test_ai_fallback_cause_oracle.py:371`,
> `test_claude_transport_oracle.py:118`). **Si la elección resulta mal**, el costo es que
> la allowlist envejezca: el día que xAI deje de ser un proveedor soportado, las tres
> excepciones de producción quedan obsoletas y hay que borrarlas a mano, porque el
> criterio no sabe distinguir «contrato vigente» de «resto».

**(d) H10 llegó más lejos que su propia tabla.** La tabla de H10 no listaba
`dashboard/pages/2_Stock_Analysis.py` (7 strings de UI: «Grok sugiere máximo N %»,
«Factores macro considerados por Grok», …) ni `dashboard/pages/8_Alertas.py:321`
(«Grok/Claude genera…»). Son mensajes visibles que nombran al proveedor equivocado —
exactamente el defecto que H10 describe —, así que entraron en PR 0.

**(e) Un test más de `test_prompts.py` tuvo que actualizarse.** Además de `:495`,
`TestGeneratePlanNarrative::test_fallback_on_api_error` asertaba sobre el texto genérico
«No se pudo generar», que PR 0 reemplaza por `AI_FALLBACK.message(cause, provider)`. Ahora
asierta sobre la causa y el mensaje canónico. La persona de los prompts no se tocó.

---

#### Hallazgos de la ejecución de PR 1

**(f) El defecto era más grande que `temperature`: eran tres, y los tres se veían igual.**
La doctrina vigente confirma los tres ([prompting best practices §
thinking](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices),
[Prompting Claude Sonnet 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5),
[stop reasons](https://platform.claude.com/docs/en/api/handling-stop-reasons)): los parámetros de sampling devuelven 400 en todo
lo posterior a 4.6; el thinking adaptativo está **encendido por defecto** en Sonnet 5 y
Opus 5, así que `content[0]` es un `ThinkingBlock` y `.text` era un `AttributeError`; y
`max_tokens` en esos modelos es el techo de **thinking + texto**, no del texto. Los tres
caían en el mismo `except Exception` de PR 0 y llegaban a la UI como «la IA no anda»,
uno con causa equivocada y dos sin causa. Arreglar sólo `temperature` habría movido el
fallo del 400 al `AttributeError` sin que nadie lo notara.

**(g) `stop_reason` necesitó tres causas nuevas, no una.** El plan pedía reportar
`max_tokens` y `refusal`. Al escribirlo apareció un tercer final propio: un 200 **sin
ningún bloque de texto**. Los tres se agregaron a `AIFallbackConfig` (`config.py`), nunca
inline: `respuesta_truncada`, `rechazo_modelo`, `respuesta_vacia`. El criterio es el
mismo de PR 0 — la causa es el contrato motor↔UI, y llamar «JSON inválido» a un corte por
techo de tokens manda al usuario a mirar el prompt por un problema que no está ahí.
`AI_FALLBACK.label/message` ya degradaban a `otro` ante un slug desconocido, así que
ninguna superficie de UI tuvo que cambiar para renderizarlas.

**(h) El techo de tokens es dos números, no uno, y por eso está en `config.py`.**
`CLAUDE_TRANSPORT` (`ClaudeTransportConfig`) resuelve
`max_tokens = int(presupuesto_de_texto × 1.3) + 12000`. Son dos correcciones distintas y
mezclarlas en una constante habría borrado el porqué: `1.3` es la inflación del tokenizer
de Sonnet 5 sobre el de 4.6 —el número que cada caller pasa (1024 por defecto, 1800 la
narrativa de plan, 2500 el optimizer) fue calibrado contra 4.6, donde era sólo texto—, y
`12000` es la holgura del thinking, que se paga sobre ese mismo techo y no se puede acotar
desde el prompt. El total queda en ~13-15 K, dentro de la banda recomendada para llamadas
**no** streaming, que es lo que el proyecto hace. Es un techo, no un gasto.

**(i) El hallazgo (b) de PR 0 sigue sin poder verificarse contra la API real — y ahora por
el motivo opuesto.** PR 0 anotó que `parametro_rechazado` era inverificable porque *toda*
llamada volvía 400. Con PR 1 la llamada ya no manda ningún parámetro que la API rechace,
así que ahora **ninguna** llamada normal vuelve 400: la causa pasó de ser universal a ser
inalcanzable sin provocar deliberadamente un request inválido. Sigue verificándose con
cliente mockeado (`tests/test_ai_fallback_cause_oracle.py`,
`tests/test_claude_transport_oracle.py`), que es exactamente el mecanismo que la UI ve.
La limitación anotada en el docstring de `test_ai_fallback_cause_oracle.py` quedó
desactualizada en su causa pero no en su conclusión.

**(j) El default `AI_MODEL` se movió: `claude-sonnet-4-6` → `claude-sonnet-5`.** ✅ *criterio resuelto (owner, 2026-09-14) — ver el recuadro al final.* El plan
lo dejaba a decisión. Se mueve porque 4-6 era el **único** ID del selector que no devolvía
400 con la llamada anterior — o sea que no era una elección de modelo sino el defecto
tapándose a sí mismo. Sonnet 5 es el mismo tier, generación actual y más barato por token.
El catálogo del selector pasó a `config.CLAUDE_MODEL_CATALOG`
(`claude-sonnet-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-haiku-4-5`) y
`9_Settings.py` lo importa: la lista hardcodeada era la que hacía alcanzable el defecto
desde la UI sin tocar código.

> **Resuelto (owner, 2026-09-14) — los dos criterios, no uno.** El plan pedía «ningún ID
> del selector está en la lista de los que rechazan la llamada». Como la llamada ya no
> manda sampling, esa lista quedó **vacía por construcción** y el criterio se volvía
> trivialmente cierto para cualquier ID, incluidos los retirados. Queda reemplazado por
> los dos invariantes que los tests de PR 1 ya verifican:
>
> > **Criterio (j.1) — fuente única del catálogo:** el selector no tiene lista propia
> > (importa `CLAUDE_MODEL_CATALOG` de `config.py`) y ningún ID retirado
> > (`claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`) sobrevive fuera
> > de los comentarios que explican por qué se fue.
> > *Test:* `tests/test_claude_transport_oracle.py:221`.
> >
> > **Criterio (j.2) — consistencia transporte↔catálogo:** `_call_claude` no manda ningún
> > parámetro que vuelva inutilizable a un ID del catálogo.
> > *Test:* `tests/test_claude_transport_oracle.py:235`.
>
> **Por qué los dos y no uno.** No son redundancia: cubren dos fallas independientes y
> ninguna implica la otra. (j.1) cae si alguien vuelve a hardcodear una lista en
> `9_Settings.py` —el defecto que hacía alcanzable el 400 desde la UI sin tocar código— y
> no dice nada sobre lo que la llamada manda. (j.2) cae si alguien reintroduce
> `temperature` / `top_p` / `top_k` en `_call_claude` —el defecto de PR 1 volviendo— y no
> dice nada sobre qué IDs ofrece la UI. Con sólo (j.1), reponer `temperature=0` deja el
> criterio en verde y los cuatro modelos del catálogo en 400. Con sólo (j.2), reponer la
> lista hardcodeada con `claude-sonnet-4-6` también lo deja en verde. Elegir una sola sería
> tapar la mitad del defecto que PR 1 arregló. Borrar el criterio (opción 4) es peor
> todavía: los dos tests existen igual, así que el plan quedaría describiendo menos
> cobertura de la real y el próximo lector concluiría que esa capa no tiene criterio.
> `CLAUDE_MODELS_SIN_SAMPLING` (`config.py:573`) queda como documentación de cuáles eran,
> leída por los tests y no por el runtime. **Si la elección resulta mal**, el costo es
> menor y conocido: (j.2) se vuelve a poner trivialmente cierto si algún día la API
> reintroduce sampling y `_call_claude` vuelve a mandarlo legítimamente — ahí hay que
> reescribirlo como «ningún ID del catálogo está en `CLAUDE_MODELS_SIN_SAMPLING`», que hoy
> sería falso.

**(k) `make check` no corre limpio, por un defecto preexistente ajeno — y es una bomba de
tiempo de calendario, no un dato faltante.** ⛔ **Bloqueante de la serie** (re-verificado
2026-09-14 sobre `main` en `129fcf1`, worktree limpio).
`tests/test_tracker_curve_oracle.py::TestTheCurveOnlyCoversWhatWasHeld::test_the_curve_has_no_step_from_a_purchase`
falla con `assert nan < 0.5`. `ruff check .` pasa; el resto es
`1 failed, 4141 passed, 2 skipped`, idéntico con `TZ=UTC`.

**La causa, medida.** No es «una serie vacía por falta de datos de precio»: el fixture está
completamente mockeado (`monkeypatch` de `portfolio.tracker.get_history`) y el problema es
que mezcla una fecha **literal** con una fecha **relativa a `now`**. El fixture
(`tests/test_tracker_curve_oracle.py:66-69`) genera historia semanal sintética con
`_weekly("2024-01-07", 130, ...)` → rango fijo **2024-01-07 → 2026-06-28**, mientras que la
compra de NVDA es `datetime.now() - timedelta(weeks=12)`. Al 2026-09-14 eso cae en
**2026-06-22**, así que después de la última compra sobrevive **una sola barra**:
`curve.pct_change().dropna()` queda vacío y `.max()` es `nan`. El test pasaba hasta
~2026-09-07 y desde entonces falla en toda máquina, incluido el CI. Es exactamente el
defecto que el checklist de `docs/PROMPT_INSTRUCTIONS.md` ya prohíbe para fechas y horas, y
el arreglo es de una línea: anclar el inicio del fixture a `now - N semanas` en vez de al
literal `"2024-01-07"`.

**Por qué bloquea la serie y no es deuda arrastrable.** «`make check` verde» es un criterio
de aceptación de los **cinco** PRs abiertos (PR 2, 4, 5, 6, 7). Mientras el rojo sea ajeno,
ninguno de los cinco puede reportarlo como cumplido sin una excepción escrita a mano, y el
primer fallo genuino que la serie introduzca se esconde detrás del ruido — el mismo defecto
que PR 0 arregló en la capa de IA, repetido en la capa de tests. Va **antes de PR 2**, como
un PR propio de una línea, no como una fase.

---

#### Hallazgos de la ejecución de PR 1.5 / PR 2

**(l) La bomba de calendario ya había explotado, y explotó exactamente como (k) predijo.**
No hizo falta esperar: al 2026-09-14, `TZ=UTC venv/bin/python -m pytest
tests/test_tracker_curve_oracle.py` da

```
FAILED TestTheCurveOnlyCoversWhatWasHeld::test_the_curve_has_no_step_from_a_purchase
E   assert nan < 0.5
E    +  where nan = max()
E    +    where max = Series([], Freq: W-SUN, dtype: float64).max
```

El diagnóstico de (k) era correcto hasta la serie vacía. Lo que (k) **no** anticipaba es
cuántos call sites tenía el literal: no uno, sino **cuatro** (`_weekly("2024-01-07", 130,
...)` en el fixture y en tres tests independientes). Anclar sólo el del fixture habría
dejado tres bombas con temporizadores distintos, porque las otras tres comparan contra
compras de 200 semanas y 3 días, no de 12.

**(m) «Que el test siga siendo verdadero en cualquier fecha futura» no lo garantiza anclar
la fecha; hay que afirmarlo.** Anclar el inicio a `now - 129 semanas` arregla *hoy*, pero
nada impide que mañana alguien reintroduzca un literal, ni que el bracket se rompa por otro
lado. El PR agrega `TestTheFixtureDoesNotExpire`, que no prueba `tracker.py` sino el
acoplamiento entre los precios inyectados y las compras: el historial debe abarcar toda
compra usada por el fixture (parametrizado a 0, 12 y 104 semanas atrás), la ventana
compartida no puede quedar vacía —la forma exacta de la falla— y un guard por AST rechaza
cualquier `_weekly(` con un literal como primer argumento. Un `re.search` de `\d{4}-\d{2}-\d{2}`
sobre el archivo, que fue el primer intento, es **inservible**: matchea la prosa del
docstring que narra el bug. El guard tiene que mirar los call sites, no el texto.

**(n) El «rol neutro» de PR 2 resultó ser una resta, no una reescritura.** El plan (H1)
proponía redactar «un rol neutro de una o dos oraciones que conserve el registro». Medido,
las siete aperturas ya tenían esa oración: `«Eres Grok, construido por xAI.»` era una
**oración aparte**, seguida de `«Eres un analista de inversión senior riguroso, objetivo y
basado en datos, especializado en X. Tenés voz propia: …»`. O sea que el registro no había
que conservarlo redactando algo nuevo —había que no borrarlo—. La adaptación es
`ANALYST_ROLE`, una constante de módulo que normaliza esa segunda oración, y el resto del
párrafo queda literal. Esto baja el riesgo del PR de «reescribimos 7 prompts» a «borramos
una oración y factorizamos otra», y es además lo que la doctrina de Anthropic recomienda:
un rol corto es correcto, y el defecto que sus prompting best practices marcan es la
identidad que *sustituye* al contexto, no el rol en sí.

**(o) H3 subcontaba el problema: no eran 4 sitios, eran 7.** §H3 pedía borrar el permiso de
comentario posterior de `:371, :493, :626, :746` y unificar con la redacción de
`committee_prompts.py:37`. Los 4 permisos estaban donde decía. Pero «unificar **todos** los
prompts JSON» alcanza a tres redacciones más que §H3 lista como si ya estuvieran bien por
prohibir texto extra —`:819` «Respondé SOLO con JSON válido:», `:1042` «Respondé SOLO con el
objeto JSON válido…», `:1287` «Devolvé un objeto JSON válido (y NADA de texto fuera del
JSON)»— y **una cuarta que §H3 no cita en absoluto**: la de
`sector_country_tailwind_prompt`, «El output principal debe ser un objeto JSON válido con
exactamente estos campos:», que no autorizaba prosa pero tampoco la prohibía. Eran siete
redacciones para un solo parser, no cinco.

`JSON_ONLY_CONTRACT` vive ahora en `analysis/prompts.py` y `committee_prompts.py` lo
**importa** en vez de duplicarlo: la fuente de la redacción canónica no puede volver a
divergir de sus consumidores por un typo.

**(p) El contrato único no siempre ahorra: en dos prompts cuesta.** El plan asumía ahorro
(«el modelo gasta tokens en prosa post-JSON que nadie lee»). Medido sobre el prompt
renderizado —en **caracteres**, ver (q)—:

| prompt | antes | después | Δ | Δ% |
|---|---:|---:|---:|---:|
| `equity_moat` | 8816 | 8656 | −160 | −1.8 % |
| `equity_decision` | 6775 | 6625 | −150 | −2.2 % |
| `crypto_moat` | 7937 | 7777 | −160 | −2.0 % |
| `crypto_decision` | 5959 | 5791 | −168 | −2.8 % |
| `alert_explanation` | 1506 | 1580 | **+74** | **+4.9 %** |
| `long_term_plan_narrative` | 2179 | 2179 | 0 | 0.0 % |
| `portfolio_optimizer_advice` | 8515 | 8496 | −19 | −0.2 % |
| `plan_level_narrative` | 4218 | 4240 | **+22** | **+0.5 %** |
| `sector_country_tailwind` | 2489 | 2486 | −3 | −0.1 % |
| **total** | **48394** | **47830** | **−564** | **−1.2 %** |

Los dos que crecen son precisamente los que tenían el contrato **más lacónico**
(`«Respondé SOLO con JSON válido:»`, `«…con exactamente dos campos:»`) y ahora llevan la
redacción completa. Es el precio correcto: el ahorro real de H3 no está en estos caracteres
sino en la prosa post-JSON que el modelo ya no genera, y eso se mide en el *output*, no en
el input. El −1.2 % del input es ruido; no usar este número para justificar el PR.

**(q) No se pudieron reportar tokens, sólo caracteres.** El criterio de aceptación pedía
«tokens del prompt renderizado antes/después». La única forma correcta de contarlos es
`client.messages.count_tokens` (un tokenizador de terceros daría un número que no es el que
la API factura), y en este entorno no hay credencial de Anthropic: `ANTHROPIC_API_KEY` sin
setear y sin CLI `ant` instalada. Los caracteres son un proxy honesto para un Δ de esta
magnitud, pero **no** son el criterio: queda pendiente correr la medición en tokens desde un
entorno con credencial. PR 4 tiene el mismo criterio y se va a topar con lo mismo.

**(r) `long_term_plan_narrative` es el único de los nueve que queda fuera del contrato, y
eso hay que afirmarlo.** Pide Markdown y prohíbe JSON a propósito (es H4, que resuelve PR 6).
El oráculo lo excluye con un test explícito —`test_the_markdown_prompt_is_excluded_on_purpose`—
en vez de con un silencio, porque «unificar el contrato» tiene una forma de trampa obvia:
convertirlo también a JSON y declarar 9/9. El test falla si alguien lo hace.

---

Orden deliberado: **primero lo que hace verificable todo lo demás** (§0.1), después el
transporte, y recién entonces los prompts. Invertir el orden produce PRs de prompts cuyo
efecto nadie puede medir porque el fallback silencioso los tapa.

---

### PR 0 — El fallback deja de mentir sobre la causa ✅ implementado

**Qué:** `AIAnalyzer.analyze` y las tres `generate_*` distinguen y propagan la causa:
`sin API key` / `key inválida (401)` / `parámetro rechazado (400)` / `rate limit (429)` /
`JSON inválido` / `otro`. La causa viaja en el objeto de retorno y la UI la muestra.
`AIConfig.api_key` (`config.py:530-534`) pasa a resolver **por proveedor**, alineado con
`config_validator.py:60-67`.

**Por qué primero:** sin esto ninguna fase posterior tiene criterio de aceptación
verificable — un prompt nuevo que falla se ve igual que uno que anda (§0.1).

**Aceptación:**
- Test: `provider="claude"` con sólo `XAI_API_KEY` seteada → `AIConfig.api_key == ""`, no la
  key de xAI.
- Test: un cliente mockeado que levanta `BadRequestError` produce un resultado cuya causa
  es `parametro_rechazado`, distinguible de `sin_api_key`.
- Ningún string de UI nombra un proveedor que no sea el configurado.
- `make check` verde.

---

### PR 1 — `_call_claude` deja de rechazar los modelos actuales ✅ implementado

**Qué:** en `_call_claude` (`ai_analyzer.py:389-400`): quitar `temperature`; subir el
default de `max_tokens` con holgura para thinking; leer el **primer bloque de tipo `text`**
en vez de `content[0]`; chequear `stop_reason` (`max_tokens` y `refusal`) y reportarlo
vía PR 0. Los branches OpenAI-compatible quedan intactos. En `9_Settings.py:191-195`:
actualizar el catálogo a IDs vigentes (`claude-sonnet-5`, `claude-opus-5`) y sacar los que
devuelven 400.

**Por qué:** H2. Es el defecto que rompe la IA hoy, y es de transporte, no de prompt.

**Aceptación:**
- Test con cliente mockeado: el kwargs de `messages.create` **no** contiene `temperature`,
  `top_p` ni `top_k`.
- Test: una respuesta con `[ThinkingBlock, TextBlock]` devuelve el texto, no un
  `AttributeError`.
- Test: `stop_reason == "max_tokens"` se reporta como causa, no como JSON inválido.
- Ningún ID del selector está en la lista de los que rechazan la llamada.
- `make check` verde.

---

### PR 1.5 — Desactivar la bomba de calendario (hallazgo (k)) ✅ implementado

**Qué:** `tests/test_tracker_curve_oracle.py` mezclaba un inicio literal de precios con
compras relativas a `datetime.now()`. El inicio pasa a ser `now - (_HISTORY_WEEKS - 1)`
semanas, en los **cuatro** call sites (no uno — ver (l)). Lo que el oráculo afirma no cambió;
sólo su reloj.

**Por qué:** «`make check` verde» era criterio de aceptación de los cinco PRs abiertos y el
rojo era ajeno. Va antes de PR 2.

**Aceptación:**
- ✅ El suite queda en 0 failed: `TZ=UTC pytest tests/ -q` → 4147 passed, 2 skipped (antes
  de PR 2).
- ✅ El criterio es «verdadero en cualquier fecha futura», no «verdadero hoy»:
  `TestTheFixtureDoesNotExpire` afirma el bracket relativo, la ventana compartida no vacía y
  —por AST— que ningún call site de `_weekly` reciba un literal. Ver (m).

---

### PR 2 — Persona neutra en los 9 prompts (H1) + contrato único de salida (H3) ✅ implementado

**Qué:** reemplazar las 7 aperturas «Eres Grok, construido por xAI» por un rol neutro de
una o dos oraciones que conserve el registro; borrar «voz de Grok» de `:489`, `:742`,
`:1027`, `:1032`, `:1044`. Unificar el contrato: **todos** los prompts JSON usan la
redacción de `committee_prompts.py:37`; se borra el permiso de comentario posterior de
`:371`, `:493`, `:626`, `:746`.

**Por qué:** H1, H3. Sin renombre de campos persistidos todavía — eso es PR 3.

**Aceptación:**
- ✅ Test nuevo: para los 9 prompts, `"Grok" not in prompt and "xAI" not in prompt`
  (`tests/test_prompt_neutrality_oracle.py::TestNingunPromptNombraUnProveedor`, extendido a
  todo el fuente de `prompts.py` y `committee_prompts.py`, no sólo al string renderizado).
- ✅ Test nuevo: ningún prompt JSON contiene la cadena «después del JSON».
- ✅ Los 6 asserts de voz de `test_prompts.py` reescritos contra `ANALYST_ROLE`.
- ✅ `make check` verde: `ruff check .` limpio y `TZ=UTC pytest tests/ -q` →
  **4201 passed, 2 skipped, 0 failed**.
- ⚠️ Medición en **tokens** antes/después: no verificable en este entorno — ver hallazgo (q).
  Se reporta en caracteres en el hallazgo (p).

**Resultó distinto de lo previsto** en cuatro puntos: el rol neutro era una resta y no una
reescritura (n); H3 subcontaba los sitios, 7 y no 4 (o); el contrato único **agranda** dos
prompts en vez de achicarlos (p); y el criterio de tokens quedó sin verificar (q).

---

### ~~PR 3 — Renombre total y migración de planes guardados (H10)~~ 🔀 absorbido por PR 0

> **Este PR ya no existe.** Su alcance entró completo en PR 0 por decisión del owner
> (2026-09-14), y la migración de disco resultó innecesaria — ver §5.0, hallazgo (a).
> Lo que sigue se conserva como registro del alcance original.

**Qué:** `grok_core_holdings` → `core_holdings_ai`, `ai_grok_narrative` → `ai_narrative`
en `portfolio/optimizer.py`, `data/plan_store.py` y consumidores.
`PlanSnapshot.from_dict` lee **ambos** nombres y escribe el nuevo. Reescribir los tres
strings de UI de `ai_analyzer.py:262,348,374` y los comentarios de `strategy.py:396`,
`moat.py:139`, `crypto_analyzer.py:18,88,91`.

**Por qué:** H10. Se separa de PR 2 porque toca datos del usuario en disco y merece su
propia revisión.

**Aceptación:**
- Test oráculo: un `retirement_plans.json` con los nombres **viejos** se carga sin pérdida
  de `core_holdings` ni de la narrativa, y al re-guardar queda con los nombres nuevos.
- `grep -ri grok --include='*.py' .` devuelve 0 fuera de ese shim de compatibilidad.
- `make check` verde.

---

### PR 4 — Higiene de instrucciones: idioma, negaciones y few-shot (H5, H6)

**Qué:** una sola declaración de idioma por prompt, sin enumerar campos (elimina las listas
muertas de `:445`, `:556`, `:694`, `:796`). Un solo enunciado de anclaje a datos, con su
motivo. Borrar la repetición triple del «no inventes tailwinds» (`:205`, `:1019`, `:1129`),
dejando una. Reemplazar el few-shot único de `:240-242` por 2–3 ejemplos balanceados en
`<examples><example>…</example></examples>`.

**Por qué:** H5, H6. Recupera ~400 tok/llamada de instrucción muerta y corrige el sesgo a
degradar.

**Aceptación:**
- Test: en cada prompt, «IDIOMA OBLIGATORIO» aparece **exactamente una vez**.
- Test: ningún prompt menciona un nombre de campo que no esté en su propio contrato JSON
  (mata las listas muertas por construcción).
- Test: el bloque de ejemplos contiene ≥2 ejemplos y ≥1 con `action` de compra.
- Medición reportada en el PR: tokens del prompt renderizado antes/después, por prompt.
- `make check` verde.

---

### PR 5 — Estructura: delimitador único y orden datos→instrucción (H7, H8, H9)

**Qué:** adoptar `=== SECCIÓN ===` de `committee_prompts.py` en todo `prompts.py`
(conservando los literales `CONSTRAINTS DUROS` y `PASOS DE RAZONAMIENTO` que los tests
asertan). Reordenar: rol corto → datos → instrucciones → contrato de salida, con el bloque
de idioma bajado junto al contrato. Techo de longitud explícito en todo campo de texto libre.

**Por qué:** H7, H8, H9.

**Aceptación:**
- Test: ningún prompt mezcla dos convenciones de delimitador (`---`, `**bold:**`, `━━━`).
- Test: en cada prompt, el índice de la primera sección de datos es menor que el de la
  sección de instrucción final.
- Test: todo campo de texto libre del contrato tiene un límite de longitud declarado.
- `make check` verde.

---

### PR 6 — Narrativa de plan: Markdown → campos estructurados (H4)

**Qué:** `plan_level_narrative_prompt` devuelve `{resumen, fortalezas[], riesgos[],
p10_lectura, duracion_ingreso, recomendaciones[], cierre, macro_risks[]}`.
`generate_plan_narrative` compone el Markdown desde esos campos y **sigue devolviendo
`{"narrative": str, "macro_risks": list}`, sin cambios de forma para la UI ni para
`PlanSnapshot`**. Mismo tratamiento opcional para `long_term_plan_narrative_prompt`.

**Por qué:** H4. Es el de mayor riesgo aguas abajo y va último a propósito.

**Aceptación:**
- Test: dada una respuesta estructurada del modelo, `generate_plan_narrative` produce un
  `narrative` con las 7 secciones en orden.
- Test: una respuesta **vieja** (`narrative` como blob Markdown) se sigue aceptando —
  el fallback de `ai_analyzer.py:196-198` cubre el caso y hay que probarlo.
- `dashboard/pages/12_Plan.py` renderiza sin cambios.
- `make check` verde.

---

### PR 7 — El macro deja de salir de la memoria del modelo (H11)

**Qué:** cuando no hay `macro_context` fechado, el prompt declara explícitamente que no hay
datos macro actuales y restringe `macro_factors` a factores **estructurales** verificables
contra los números del prompt. Aplica a `committee_prompts.py:113-127` y a los cinco
«usá tu conocimiento actual» de `prompts.py:302,479,574,719,1016`.

**Por qué:** H11. Único hallazgo con consecuencia financiera directa: un factor macro
alucinado se persiste en `PlanSnapshot.macro_risks` y se le muestra al usuario como análisis
meses después.

**Aceptación:**
- Test: sin `macro_context`, ningún prompt contiene «conocimiento actual».
- Test: sin `macro_context`, el prompt contiene la instrucción de restringirse a factores
  estructurales.
- Test: con `macro_context`, la prohibición de usar memoria sigue presente.
- `make check` verde.

---

## 6. Fuentes

Toda la doctrina citada es documentación oficial vigente consultada el **2026-09-14**
(`docs.claude.com` redirige a `platform.claude.com`):

- [Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
  — principios generales, rol, ejemplos, XML tags, contexto largo, formato de respuesta,
  self-knowledge, migración
- [Prompting Claude Sonnet 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5)
  — verbosidad, effort, seguimiento literal de instrucciones, y la remoción de `temperature`
- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
  — evaluada y descartada por decisión del owner (Claude-only)
- [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Sonnet 5 migration guide](https://platform.claude.com/docs/en/models/sonnet-5/migration-guide#migrating-from-claude-sonnet-4-6-to-claude-sonnet-5)
</content>
</invoke>
