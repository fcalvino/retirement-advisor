# Decisiones técnicas Q1–Q5 de la serie multimodelo (2026-09-15)

> **Qué es esto.** La resolución de las cinco preguntas que
> [`PROMPTS_MULTIMODELO_NEXT_STEPS.md`](PROMPTS_MULTIMODELO_NEXT_STEPS.md) §8 dejó abiertas,
> para desbloquear PR 4, PR 5 y PR 7 de
> [`PROMPTS_MULTIMODELO_PLAN.md`](PROMPTS_MULTIMODELO_PLAN.md).
>
> **Estas son recomendaciones técnicas fundamentadas, no aprobaciones del owner.** Donde
> hacía falta una preferencia de producto, se propone un valor por defecto justificado y se
> aísla el punto (§7). Las recomendaciones de los dos documentos de entrada se trataron como
> hipótesis a evaluar, no como decisiones tomadas.
>
> **No se implementó nada.** Ningún archivo de `analysis/`, `tests/` o `dashboard/` se tocó.
> Todas las citas `archivo:línea` se re-verificaron hoy sobre `fa75406`, rama
> `fercalvino-cu/prompts-multimodelo-plan-analisis`.

---

## 1. Resumen y tabla de decisiones

| Q | Decisión recomendada | Evidencia `archivo:línea` | Alternativa descartada | Riesgo residual | PR desbloqueado |
|---|---|---|---|---|---|
| **Q1** | **Arreglo barato**, ampliado a **8 sitios** (5 de `prompts.py` + 2 del comité + `plan_level_narrative_prompt`). La opción completa va a backlog con condición de retoma explícita (§5.1). | `analysis/prompts.py:330,507,602,747,1044`; `analysis/committee_prompts.py:126` y `:331-333`; `data/plan_store.py:108`; `dashboard/pages/12_Plan.py:868` | Enhebrar `macro_context` desde `analysis/macro_rag.py` hasta los 5 prompts | El RAG no impide alucinar; y `macro_rag` **no tiene seeder automático** (`dashboard/pages/17_Macro_RAG.py:29,36` es la única vía) | **PR 7** |
| **Q3** | **`=== SECCIÓN ===` en los dos archivos.** PR 5 pasa a ser el **dueño único** de todo carácter delimitador, y su alcance se amplía a los 8 `---` de `committee_prompts.py`. | `analysis/prompts.py`: 15 `---`, 5 `━━━`, 29 `**bold**`, 0 `===`; `analysis/committee_prompts.py`: 7 `===` **y 8 `---`** (`:219,244,270,280,297,313,324,333`) | XML (`<seccion>`) en ambos archivos | Convención propia del repo: **ningún proveedor la recomienda por nombre** (§3.2) | **PR 5** |
| **Q2** | **Conservar un literal de texto plano** (`FEW-SHOT …`), **sin `<examples>`**. PR 4 cambia sólo el *contenido* del bloque, no sus delimitadores. **No** se extiende a crypto. | `analysis/prompts.py:238-279` (few-shot en `:268-270`), único caller `:514`; `crypto_decision_prompt:755-766` sin few-shot, con ejemplo inline propio en `:783` | `<examples><example>…` que pide el «Qué» de PR 4 | Un tercer PR podría reabrir el envoltorio; se cierra fijando la propiedad en PR 5 | **PR 4** |
| **Q4** | Aceptar 3 reformulaciones, **corregir 2** (la de campos y la de deduplicación) y **rechazar 1** (la medición en tokens como criterio). Detalle en §4. | `analysis/prompts.py:313,473,584,722` (campos muertos) vs. `:557,818` (campos reales); `:233,1047,1157` en 3 prompts independientes | Ejecutar el plan literal y reportar «verde por construcción» | Los criterios son invariantes estáticos: prueban que el prompt cambió, no que el modelo responde mejor | **PR 4 + PR 7** |
| **Q5** | **Opción A**: agregar la quinta excepción («tests que afirman la ausencia de la marca»). | Allowlist vigente en `docs/plans/PROMPTS_MULTIMODELO_PLAN.md:607-612`; `tests/test_prompt_neutrality_oracle.py:3,4,5,28,67` | Re-scopear `test_prompt_neutrality_oracle.py` para que no se auto-detecte | La granularidad de la allowlist es **por archivo**, no por línea — riesgo ya aceptado para la 4ª excepción (`PLAN.md:631-634`) | ninguno (higiene) |

**Orden de PRs resultante: PR 7 → PR 4 → PR 5 → PR 6** (§6). Sólo se mueve PR 7 respecto al
orden del plan, y por la razón que el propio plan da: es el único hallazgo con consecuencia
financiera y el de menor churn.

---

## 2. Q1 — Alcance de PR 7

### 2.1 Traza del contexto macro (verificada)

**Generación.** `MacroRagStore` (`analysis/macro_rag.py:90-209`), SQLite. `build_context()`
(`:193-209`) devuelve `""` si `not MACRO_RAG.enabled` (`:196-197`) o si no hay hits
(`:199-200`). `macro_context_for(fund)` (`:315-322`) envuelve todo en `try/except` → `""`.
Config: `MacroRagConfig` (`config.py:2283-2305`): `enabled=True`, `top_k=4`,
`max_age_days=120`, `min_score=0.02`, `max_context_chars=1200`; singleton en `config.py:2791`.

**Transporte (ya enhebrado, sólo en el comité).** Dos caminos de producción:
`CommitteeAnalyzer.analyze` (`analysis/committee.py:522-527` → `macro_strategist_prompt` en
`:531`), consumido por `dashboard/pages/15_Comite.py:73`; y `run_holdings_committee`
(`:704-712` → `build_holdings_committee_context(macro_context=…)` en `:727`), consumido por
`dashboard/shared.py:1665` → `dashboard/pages/3_Portfolio.py:253`.

**Consumo.** `macro_strategist_prompt` (`analysis/committee_prompts.py:118`) y
`portfolio_committee_context_block` (`:193`, lee `ctx.get("macro_context")` en `:331`), que
alimenta a los **cuatro** agentes de portfolio vía `_portfolio_role_prompt:338` (llamada en
`:345`): `plan_strategist_prompt:352`, `risk_manager_portfolio_prompt:364`,
`macro_strategist_portfolio_prompt:378`, `devils_advocate_portfolio_prompt:390`.

**`analysis/prompts.py` no recibe `macro_context` en ningún prompt** — `grep -n macro_context
analysis/prompts.py` → 0 hits (re-verificado hoy).

**Persistencia — corrección a H11.** El plan (`PLAN.md:427-428`) afirma que un factor macro
alucinado «entra en `macro_factors`, se persiste en `PlanSnapshot.macro_risks`». Eso
conflaciona dos campos de dos prompts distintos:

- `macro_risks` (`data/plan_store.py:108`) lo produce **`plan_level_narrative_prompt`**
  (`analysis/prompts.py:1101`), vía `analysis/ai_analyzer.py:335,350` →
  `dashboard/pages/12_Plan.py:868`. Ese prompt **no** es uno de los 5 sitios de H11 y
  **tampoco** recibe `macro_context`.
- Los `macro_factors` de moat/decision viven en caché de 7 días, no en `PlanSnapshot`.
- Los `macro_factors` de `portfolio_optimizer_advice_prompt` se persisten **indirectamente**:
  el propio prompt pide mencionarlos dentro de `narrative` (`analysis/prompts.py:147`), y
  `narrative` sí se persiste (`data/plan_store.py:98`).

**Consecuencia de alcance:** el sitio que produce el daño que H11 describe —«se le muestra al
usuario como análisis del plan meses después»— quedó **fuera** del inventario de los dos
documentos. Por eso la decisión amplía PR 7 a 8 sitios, no a 7.

**Firmas que tocaría la opción completa** (por si se retoma): `MoatAnalyzer._build_prompt` /
`.analyze_with_ai` (`analysis/moat.py:502-505`, `:299`, prompt en `:342`), llamado desde
`analysis/fundamental.py:1012`; `CryptoAnalyzer._build_crypto_moat_prompt` /
`._analyze_crypto_moat` (`analysis/crypto_analyzer.py:518-521`, `:402-408`, prompt en `:427`),
llamado desde `:195`; `AIAnalyzer._build_prompt` (`analysis/ai_analyzer.py:234-240`) y
`.generate_optimizer_advice` (`:362-367`, prompt en `:451`). En los tres primeros el objeto
con `sector/industry/company_name` ya está poblado antes de la llamada
(`analysis/fundamental.py:800` corre antes de `:803`), así que no hace falta reordenar
pipelines. **`analysis/tailwind.py` no está afectado**: `sector_country_tailwind_prompt`
(`analysis/prompts.py:1347-1398`) no contiene «conocimiento actual» ni sección macro —
corrige a `NEXT_STEPS.md:104-105`.

### 2.2 Ausente vs. vacío vs. fechado

| | `prompts.py` (5 sitios) | `macro_strategist_prompt` | bloque de portfolio (4 agentes) |
|---|---|---|---|
| **Ausente** | Siempre, por firma: no existe el parámetro | Sin prohibición de usar memoria; el mandato de evaluar macro sigue (`committee_prompts.py:119-125`) | Sin sección macro; ninguna prohibición explícita |
| **Vacío** | N/A | **Indistinguible de ausente**: `if macro_context:` (`:126`) trata `None`/`""` igual | **Indistinguible**: `if macro:` (`:332`) |
| **Fechado** | N/A | «Usá EXCLUSIVAMENTE estos hechos macro fechados … no inventes … ni uses tu memoria» (`:127-131`) | `--- Contexto macro fechado (usalo, no inventes) ---` (`:333`) |

**Vigencia.** La determina `_days_old(as_of, now)` (`analysis/macro_rag.py:77-87`) contra
`MACRO_RAG.max_age_days=120`, con corte binario (no hay degradación gradual) y sello
`[{doc.as_of}]` en `:203`. **Defecto encontrado, no citado por ninguno de los dos documentos:**
el filtro es `age is None or age <= max_age` (`:160`), y `_days_old` devuelve `None` cuando
`not as_of` (`:78-79`) — un documento **sin fecha pasa el gate de frescura igual que uno de
hoy**. El gate rechaza lo vencido, no lo indatado.

**Hallazgo que cambia el cálculo de Q1:** no hay ningún seeder automático de `macro_rag`. Las
únicas vías de ingesto son los dos botones de `dashboard/pages/17_Macro_RAG.py:29` («Cargar
set de ejemplo») y `:36` («Ingerir desde FRED», deshabilitado sin `FRED_API_KEY`) —
verificado: `example_macro_docs` / `ingest_from_fred` se definen en `analysis/macro_rag.py:228,262`
y no se referencian desde ningún otro módulo de producción. Sin cron ni job de arranque, en
una instalación donde nadie tocó esa página `build_context()` devuelve `""` en el 100% de las
llamadas. *(Inferencia de código: no se consultó una base SQLite en vivo.)*

### 2.3 Riesgo que reduce cada alternativa, y el que permanece

**Opción barata.** Reduce: la instrucción explícita de usar el corte de entrenamiento como si
fuera hoy, en los 8 sitios; y cierra el `if` sin `else` del comité, donde hoy «ausente» se
comporta como «sin restricción». **No cubre:** una instrucción de prompt no impide alucinar
— el modelo puede inventar un dato macro igual, sobre todo si «estructural» queda laxo. No
toca el gate de documentos sin `as_of`. No provee una fuente alternativa cuando el usuario sí
querría actualidad.

**Opción completa.** Reduce lo anterior **más** el vacío de alternativa: da una fuente
fechada cuando existe, y evita el sobre-disparo defensivo (`macro_factors: []` por cautela)
que H5 describe. **No cubre:** exactamente el mismo residuo de alucinación, porque el modelo
sigue pudiendo ignorar el contexto inyectado; y su valor **depende por completo** de que el
store esté poblado, cosa que hoy no ocurre por defecto (§2.2). Implementada hoy produce el
mismo observable que la barata —`macro_context` vacío siempre— con 4-5 archivos de producción
más de superficie y llamadas a SQLite en el hot path de moat/crypto/decision.

### 2.4 Decisión

**Opción barata, ampliada a 8 sitios**, y opción completa a backlog (§5.1).

Justificación por eje: **corrección** — la barata cierra el defecto textual que H11 describe
en el 100% de los sitios verificados, y la completa no mejora la corrección observable
mientras el store esté vacío; **alcance** — 8 sitios de texto, cero firmas de producción
tocadas, contra 4-5 módulos con lógica; **costo** — PR de texto + tests estáticos contra un PR
que además obliga a resolver el ingesto, trabajo que ningún documento dimensiona;
**riesgo** — el más bajo de la serie: no toca `_call_api`, `Decision`, `MoatDetail` ni
`PlanSnapshot`; **portabilidad** — ambas son texto + orquestación Python, ninguna usa una
feature de un solo proveedor; **verificabilidad** — la barata se verifica al 100% con
invariantes estáticos, la completa agrega una superficie que ningún test puede cerrar sin
datos reales; **dependencias** — la barata no tiene ninguna, la completa depende de un trabajo
no iniciado.

**Evidencia que justificaría reconsiderar:** (i) que exista o se decida construir un job que
siembre `macro_rag_store` en producción — cambia por completo el cálculo costo/beneficio; o
(ii) un incidente documentado de un factor macro alucinado que haya llegado a un usuario. Hoy
el argumento es de diseño, no de incidente observado.

### 2.5 Ampliación de alcance propuesta (decisión, no hallazgo suelto)

PR 7 cubre **8 sitios**: los 5 de `analysis/prompts.py` (`:330, :507, :602, :747, :1044`), los
2 del comité (`committee_prompts.py:126` y `:331-333`, este último agregando la rama `else`) y
**`plan_level_narrative_prompt`** — el único cuyo output se persiste de verdad en
`PlanSnapshot.macro_risks` (§2.1). El costo es una declaración más; el beneficio es cubrir
justamente el camino con el que H11 se justifica.

---

## 3. Q3 y Q2 — Delimitadores y few-shot

### 3.1 Recuento real (re-verificado hoy)

`analysis/prompts.py`: **15** `--- SECCIÓN ---` (`:254,261,479,500,507,515,602,703,729,738,744,747,755,761,768`),
**5** `━━━` (`:348,360,372,383,393`), **0** `=== SECCIÓN ===`, y **29** líneas cuyo contenido
completo es `**Texto**` — no 7 como dice `NEXT_STEPS.md` §3. El subconteo omite 5 subcabeceras
de rúbrica de `crypto_moat_prompt` (`:614,621,628,634,640`), el bloque de
`long_term_plan_narrative_prompt` (`:898,903,910,919,924,927,929`) y el de
`plan_level_narrative_prompt` (`:1283-1314`).

`analysis/committee_prompts.py`: **7** `===` (`:111,113,114,180,344,347,348`) **y 8** `---`
(`:219,244,270,280,297,313,324,333`), todas dentro de `portfolio_committee_context_block`.
`NEXT_STEPS.md` §3 cita una sola (`:333`) como si fuera un caso aislado; son ocho, y forman
una jerarquía deliberada de dos niveles (`===` para las secciones top-level del rol, `---`
para las subsecciones de datos). **H7 llama «consistente» a este archivo y no lo es** — eso ya
lo dice `NEXT_STEPS`, pero la magnitud es 8×, no 1×.

### 3.2 Q3 — Decisión: `=== SECCIÓN ===` en los dos archivos

**Evidencia de proveedores (consultada hoy, documentación oficial):**

- **OpenAI** — [Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering):
  trata encabezados Markdown y tags XML como **complementarios**, sin declarar superioridad.
- **Google (Gemini)** — [Prompting strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies):
  «XML-style tags … or Markdown headings are effective»; lo que exige es **consistencia dentro
  de un mismo prompt**, no una sintaxis.
- **Anthropic** — recomienda XML explícitamente; se toma de la cita ya existente del plan
  (`PLAN.md` §6, `platform.claude.com`, consultada 2026-09-14). **No re-verificada hoy.**
- **xAI** — **no se encontró documentación oficial de prompting.** No se hace ninguna
  afirmación sobre qué recomienda.

**Por lo tanto: no hay evidencia de que XML se comporte mejor ni de que sea más portable.** La
decisión no se apoya en doctrina sino en tres razones propias: (1) `===` ya es el convenio
dominante de `committee_prompts.py`, así que unificar hacia ahí es el menor diff combinado;
(2) XML es la recomendación **nombrada** de un solo proveedor, y la restricción del owner es
no sesgar hacia ninguno — `===` es neutral por ausencia de marca; (3) PR 5 ya es el PR de
mayor churn de la serie (~500 líneas) y subir a XML lo agranda sin beneficio demostrable.

**Ampliación de alcance de PR 5:** su «Qué» dice «adoptar `=== SECCIÓN ===` de
`committee_prompts.py` en todo `prompts.py`», usando ese archivo como modelo **sin tocarlo**.
Ejecutado literal, deja `committee_prompts.py` con 7 `===` + 8 `---` conviviendo. PR 5 debe
alcanzar los dos archivos.

### 3.3 Las tres cosas que no hay que confundir

1. **Cabeceras de sección** (instrucciones y datos): lo que PR 5 unifica.
2. **Bloques de ejemplos**: uno solo hoy (§3.4). Queda bajo la misma convención de texto plano.
3. **Markdown exigido dentro del payload de salida**: dos casos, y **se comportan distinto**.

**La dependencia PR 5 ← PR 6 que `NEXT_STEPS` §3 declara «real» no lo es para
`plan_level_narrative_prompt`.** Renderizado el prompt con datos reales y corrido el regex de
cabecera estricta, da **10 matches, las 10 cabeceras legítimas, cero falsos positivos**: la
línea del ejemplo empieza con `"narrative": "**Resumen…` y la de instrucción con `- **Resumen…`,
así que ninguna es «línea completa = sólo el delimitador».

**Donde sí hay un problema estructural es en `long_term_plan_narrative_prompt`**, que
`NEXT_STEPS` no cubre: devuelve texto libre y su plantilla de salida (`analysis/prompts.py:924-929`)
usa exactamente la misma forma `**Texto**` que sus propias cabeceras (`:898,903,910,919`). 3 de
las 6 líneas de plantilla matchean el regex. **No hay regex que los distinga** — y no se
resuelve con PR 6. La solución es excluir ese prompt **por nombre**, con el precedente ya
existente de `test_the_markdown_prompt_is_excluded_on_purpose`
(`tests/test_prompt_neutrality_oracle.py:201`), que lo excluye por la misma razón.

### 3.4 Q2 — Decisión: literal de texto plano, sin `<examples>`, sin extender a crypto

El few-shot vive en `_hard_decision_constraints_block` (`analysis/prompts.py:238-279`, texto en
`:268-270`) y tiene **un solo caller**: `equity_decision_prompt:514`. `crypto_decision_prompt`
tiene constraints propios (`:755-766`) **sin few-shot**, más un ejemplo inline de una frase
para justificar `confidence` (`:783`).

**Decisión (consistente con Q3):** el bloque conserva un literal de texto plano. PR 4 cambia
sólo el **contenido** (1 ejemplo negativo → 2-3 balanceados) y **no toca ningún delimitador**;
PR 5, dueño único de los delimitadores, lo envuelve después en `=== EJEMPLOS ===` junto con el
resto. Así no hay retrabajo y el archivo nunca queda con dos convenciones. Esto **rechaza** el
`<examples><example>…` que pide el «Qué» de PR 4 (`PLAN.md`, cuerpo de PR 4) — no por
comportamiento, sino por coherencia con Q3.

**No se extiende a crypto.** Razones: los constraints duros son estructuralmente distintos
(equity usa D/E y P/B; crypto usa volatilidad y drawdown, sin ROE ni D/E), así que un ejemplo
copiado no tendría términos válidos; H5/H6 citan sólo `prompts.py:240-242` y no mencionan
crypto; y `crypto_decision_prompt` ya tiene su propio ejemplo inline. Ampliarlo duplicaría el
diff de PR 4 sin que ningún hallazgo lo pida.

**Los constraints financieros duros se conservan íntegros.** El ejemplo de compra **y** el de
no-compra se justifican porque `apply_safety_overlay` (serie SIGNAL) sólo puede empujar el
veredicto del modelo **hacia abajo**: un few-shot 100% negativo refuerza un sesgo asimétrico
que el overlay ya garantiza por construcción. El ejemplo de compra no afloja ningún
constraint — sigue sujeto a las mismas puertas duras.

---

## 4. Q4 — Criterios de aceptación: qué se acepta, se corrige y se rechaza

### 4.1 Correspondencia criterio → defecto → redacción

| Criterio original (plan) | Defecto que busca detectar | Propuesta de `NEXT_STEPS` | Veredicto |
|---|---|---|---|
| «IDIOMA OBLIGATORIO aparece exactamente una vez» (PR 4) | Repetición de la declaración de idioma | (4.2): conservarlo como **regresión**, hoy verde | **Aceptar**, con la etiqueta de regresión explícita en el PR |
| «Ningún prompt menciona un campo que no esté en su contrato» (PR 4) | Las 4 listas muertas `key_strengths`/`key_risks` | (4.1): «ninguna declaración de idioma enumera nombres de campo» | **Corregir** — recorta cobertura (§4.3) |
| «NO inventes colas de viento» ×3 → 1 | Instrucción duplicada, costo de tokens | (4.3): una sola vez **en el conjunto de los nueve prompts** | **Rechazar tal como está redactado** (§4.4) |
| «El bloque de ejemplos tiene ≥2 ejemplos y ≥1 de compra» | Few-shot único y negativo | (4.4): idéntico | **Aceptar** sin cambios |
| «Medición de tokens antes/después» (PR 4) | Ahorro de ~400 tok/llamada | `NEXT_STEPS` §7: inverificable en este entorno | **Rechazar como criterio**, reportar como dato (§4.5) |
| «Sin `macro_context`, ningún prompt contiene “conocimiento actual”» (PR 7) | Actualidad pedida a la memoria | (7.1)+(7.2): partirlo en dos | **Aceptar con matiz** (§4.6) |
| «Con `macro_context`, la prohibición sigue presente» (PR 7) | Anti-trampa de la anterior | (7.3): intacto | **Aceptar**, es regresión hoy verde (`tests/test_macro_rag.py:106-121`) |
| «Todo campo de texto libre tiene techo declarado» (PR 5, H9) | Campos que se estiran | Enumerar campos a mano en una constante del test | **Aceptar**, es la única forma verificable hoy |

**Regresión vs. corrección.** Son regresión (hoy verdes, sirven de candado, **no** demuestran
nada): la unicidad de «IDIOMA OBLIGATORIO», la prohibición con `macro_context` presente
(`tests/test_macro_rag.py:120`), y los asserts de pertenencia de `tests/test_prompts.py:274-275`.
Demuestran la corrección (hoy fallan): la ausencia de «conocimiento actual» en los 9 prompts,
la declaración de ausencia de macro sin contexto, los nombres de campo inexistentes, y el
bloque de ejemplos balanceado. **Cada PR debe decir cuál es cuál** — un criterio verde por
construcción presentado como evidencia de arreglo es exactamente el defecto que PR 0 corrigió
en la capa de IA.

### 4.2 «Sin `macro_context` es inverificable»: la afirmación es medio cierta

`NEXT_STEPS` §6.2 la enuncia como un bloque. Hay que separar dos cosas:

- **Parámetro inexistente** — en `analysis/prompts.py` no existe el parámetro `macro_context`
  en ninguno de los 9 prompts (0 hits, re-verificado). Ahí la condición «sin `macro_context`»
  **no puede ejercitarse**: no hay dos ramas que comparar. El criterio se convierte en un
  invariante incondicional de ausencia de texto. `NEXT_STEPS` tiene razón.
- **Condición implícita de ausencia** — en `committee_prompts.py` el parámetro **sí existe**
  (`:118`, `:331`) y la ausencia **sí es un estado alcanzable y verificable**: basta llamar con
  `""` o con un `ctx` sin la clave. Ahí el criterio original es perfectamente verificable y no
  hay nada que reformular. Decir «inverificable» a secas borra este caso.

Redacción final en §5.2, criterios (7.1) y (7.2), que respeta la distinción.

### 4.3 Eliminar enumeraciones de campos **recorta** la cobertura buscada

Medido hoy: de las 9 declaraciones de idioma, **4** enumeran `key_strengths`/`key_risks`
(`:313, :473, :584, :722`) y esos dos nombres **no aparecen en ninguna otra línea del archivo**
— son campos muertos. Pero las otras enumeraciones son **correctas**: `:824` nombra
`explanation` y `action_suggested`, y `action_suggested` existe en su contrato
(`analysis/prompts.py:818`); `:584` nombra además `retirement_risk_summary`, que existe
(`:557`); `:1016` nombra `narrative`, `why` y `tips`, abreviatura de `human_review_tips`
(`:1081`).

(4.1) mata las 4 líneas defectuosas **y también** las 3 correctas, y a cambio deja de detectar
el defecto genérico que el criterio original perseguía: que aparezca *cualquier* nombre de
campo inexistente, en *cualquier* parte del prompt.

**Corrección propuesta — no hace falta el registro prompt→campos.** El criterio original es
verificable sobre el **string renderizado**, comparando el prompt contra sí mismo:

> Para cada prompt renderizado: todo identificador `snake_case` enumerado en su declaración de
> idioma debe aparecer **al menos una vez más** en el mismo prompt renderizado.

Hoy falla en las 4 líneas muertas (`key_strengths` y `key_risks` no aparecen en ningún otro
lado) y pasa en las 5 restantes. Y resuelve por construcción el falso positivo que `NEXT_STEPS`
señala con razón: `sector_country_tailwind_prompt` renombra el campo en vuelo con
`.replace("macro_factors", "factors")` (`analysis/prompts.py:1392`), pero como el test opera
sobre el texto ya renderizado, ve `factors` en los dos lados. Cobertura del criterio original,
sin construir ningún registro.

### 4.4 Deduplicar: la unidad de medida es el **prompt renderizado**

«NO inventes colas de viento» aparece en `:233`, `:1047` y `:1157`. Verificado: `:233` vive en
`_tailwind_context_block` (`:212`), cuyo único caller es `equity_decision_prompt` (`:469`);
`:1047` está en `portfolio_optimizer_advice_prompt`; `:1157` en `plan_level_narrative_prompt`.
Son **tres prompts independientes**, cada uno enviado en su propia llamada a la API.

(4.3) —«una vez en el conjunto de los nueve prompts»— **borraría la instrucción de dos prompts
que hoy la necesitan**, sin ahorrar un solo token por llamada: el modelo nunca ve los tres
juntos. Es eliminar protección, no deduplicar.

**Regla general para toda la serie:** la unidad de medida es el **prompt renderizado**. No la
fuente (un helper compartido aparece una vez y se renderiza N veces), no el helper (mide
autoría, no exposición), no la llamada (no es observable en un test estático). Redacción en
§5.2, criterio (4.3').

### 4.5 Caracteres, tokens y mejora del modelo son tres cosas distintas

Verificado hoy: `ANTHROPIC_API_KEY` no está definida en este entorno, y no hay ninguna llamada
a `count_tokens` en el repo. La única cuenta correcta es `client.messages.count_tokens`; un
tokenizador de terceros da un número que no es el que se factura. Y ninguno de los dos mide lo
que el plan quiere afirmar realmente («el modelo responde mejor»), que requeriría un arnés de
evaluación que el repo no tiene.

**Decisión:** la medición en tokens **sale de los criterios de aceptación** y entra como dato
reportado. El PR informa el delta en **caracteres** por prompt, con la aclaración de que no es
tokens y que el ahorro de ~400 tok/llamada del plan sigue siendo una estimación no verificada.

### 4.6 `make check`

Re-verificado hoy: `venv/bin/ruff` no existe y `ruff` no está en `requirements.txt`; el
`Makefile:32` lo invoca y sólo el CI lo instala. Sigue requiriendo `venv/bin/pip install ruff`
a mano. La nota de entorno del plan §5.0 sigue vigente. Además, por el checklist del repo, un
PR que toque fechas u «por día» debe correr también `TZ=UTC make test`; ninguno de estos cuatro
PRs toca fechas, así que no aplica.

---

## 5. Redacción exacta propuesta

### 5.1 Entrada de backlog (Q1, opción completa)

```
Título: Enhebrar macro_context real (macro_rag) hasta los 5 prompts de análisis
individual de analysis/prompts.py — opción completa de Q1 / PR 7 / H11

Alcance:
- Pasar macro_context desde analysis/macro_rag.macro_context_for(fund) —o
  build_context() con una query equivalente donde no haya un `fund` único—
  hasta equity_moat_prompt, equity_decision_prompt, crypto_moat_prompt,
  crypto_decision_prompt y portfolio_optimizer_advice_prompt.
- Firmas a cambiar (verificadas 2026-09-15):
  · analysis/moat.py: MoatAnalyzer._build_prompt (:502-505) y
    .analyze_with_ai (:299).
  · analysis/crypto_analyzer.py: ._build_crypto_moat_prompt (:518-521) y
    ._analyze_crypto_moat (:402-408).
  · analysis/ai_analyzer.py: ._build_prompt (:234-240) —ya tiene `fund`, sólo
    hay que llamar macro_context_for(fund)— y .generate_optimizer_advice
    (:362-367), que necesita construir la query desde opt_result.sector_weights
    replicando el patrón de analysis/committee.py:704-712.
  · analysis/fundamental.py: _run_moat_pipeline ya recibe `result` con
    sector/industry poblados (:800 corre antes de :803) — no hace falta
    reordenar el pipeline, sólo pasar el dato un nivel más abajo.
- NO incluye analysis/tailwind.py: sector_country_tailwind_prompt no tiene
  sección macro ni la frase "conocimiento actual" (analysis/prompts.py:1347-1398).

Dependencias bloqueantes:
1. Ingesto automático de MacroRagStore. Hoy la única vía de poblarla es manual,
   por los botones de dashboard/pages/17_Macro_RAG.py:29 y :36 (este último
   requiere FRED_API_KEY). Sin ingesto programado, build_context() devuelve ""
   en el 100% de las llamadas y esta serie no cambia ningún observable respecto
   del arreglo barato ya mergeado.
2. Gate de frescura de analysis/macro_rag.py:160 — la condición
   `age is None or age <= max_age` acepta un documento SIN `as_of` como si
   fuera de hoy (_days_old devuelve None en :78-79). Hay que decidir si un
   documento sin fecha se rechaza.

Criterios de aceptación:
- Con el store poblado y fresco para el sector del caso de test, los 5 prompts
  contienen el bloque de hechos fechados y NO contienen "conocimiento actual".
- Con el store vacío (instalación nueva), los 5 prompts declaran la ausencia de
  datos macro actuales y restringen macro_factors a factores estructurales —
  es decir, el fallback de esta opción es al menos tan bueno como el arreglo
  barato.
- Ningún caller degrada sucio si el store lanza: mismo patrón try/except → ""
  que ya usan analysis/committee.py:522-527 y :704-712.

Condición concreta de retoma:
Retomar cuando exista, o se decida construir dentro del mismo PR, uno de estos
tres: (a) un job programado que llame ingest_from_fred() periódicamente;
(b) un paso de arranque que cargue example_macro_docs() si el store está vacío,
para no operar nunca en modo "siempre ausente"; o (c) evidencia de que un
usuario real mantiene alimentada la página 17_Macro_RAG.py de forma sostenida.
Sin uno de los tres, no hay observable que distinga esta opción de la barata.
```

### 5.2 Criterios de aceptación reescritos

**PR 7** (reemplazan los tres del cuerpo de PR 7 en `PLAN.md`):

> - **(7.1)** Ninguno de los nueve prompts de `analysis/prompts.py` contiene «conocimiento
>   actual» en su string renderizado. *(Invariante incondicional: ninguno recibe
>   `macro_context`, así que no hay dos ramas que comparar. El fixture `all_prompts()` de
>   `tests/test_prompt_neutrality_oracle.py:131-148` ya los renderiza.)* **Demuestra la
>   corrección** — hoy falla en 5.
> - **(7.2)** Llamados **sin** `macro_context` —`macro_strategist_prompt(fund, tech, "")` y
>   los cuatro prompts de portfolio con un `ctx` sin la clave `macro_context`— el prompt
>   contiene la declaración de que no hay datos macro actuales y la restricción a factores
>   estructurales. *(Acá la condición de ausencia **sí** existe y es alcanzable.)*
>   **Demuestra la corrección** — hoy falla en los 5.
> - **(7.3)** Llamados **con** `macro_context` no vacío, la prohibición de usar memoria de
>   entrenamiento sigue presente. **Regresión** — hoy verde
>   (`tests/test_macro_rag.py:106-121`); es el anti-trampa de (7.2).
> - **(7.4)** `plan_level_narrative_prompt` declara que los ítems de `macro_risks` deben ser
>   estructurales y verificables contra los números del prompt. **Demuestra la corrección** —
>   es el único campo macro que se persiste en `PlanSnapshot` (`data/plan_store.py:108`).
> - **(7.5)** `make check` verde (requiere `venv/bin/pip install ruff`, ver nota de entorno).

**PR 4** (reemplazan los cinco del cuerpo de PR 4):

> - **(4.1')** Para cada prompt renderizado: todo identificador `snake_case` enumerado en su
>   declaración de idioma aparece **al menos una vez más** en el mismo prompt renderizado.
>   **Demuestra la corrección** — hoy falla en `analysis/prompts.py:313, :473, :584, :722`
>   (`key_strengths`, `key_risks`). Opera sobre el texto renderizado, así que el renombrado en
>   vuelo de `sector_country_tailwind_prompt` (`:1392`) no genera falso positivo.
> - **(4.2')** «IDIOMA OBLIGATORIO» aparece exactamente una vez por prompt renderizado.
>   **Regresión, hoy verde** — 9 ocurrencias para 9 prompts. El PR debe decirlo: es un candado,
>   no un arreglo.
> - **(4.3')** Ninguna instrucción se repite **dentro de un mismo prompt renderizado**. La
>   unidad de medida es el prompt renderizado, no el archivo ni el helper: «NO inventes colas
>   de viento» en `:233`, `:1047` y `:1157` vive en **tres prompts independientes**
>   (`equity_decision` vía `_tailwind_context_block:212`→`:469`,
>   `portfolio_optimizer_advice`, `plan_level_narrative`), y borrar dos no ahorra un token en
>   ninguna llamada.
> - **(4.4')** El bloque de ejemplos contiene ≥2 ejemplos y ≥1 con `action` de compra.
>   **Demuestra la corrección** — hoy el único ejemplo es negativo (`:268-270`).
> - **(4.5')** `make check` verde.
>
> **Dato reportado, no criterio:** delta de **caracteres** del prompt renderizado, antes y
> después, por prompt. No es tokens: la única cuenta correcta es
> `client.messages.count_tokens` y este entorno no tiene `ANTHROPIC_API_KEY`. El ahorro de
> ~400 tok/llamada del plan queda como estimación no verificada.

**PR 5** (reemplazan el primero y el tercero):

> - **(5.1')** Ningún prompt renderizado mezcla dos convenciones de delimitador. Una
>   convención sólo cuenta si la **línea completa** es el delimitador (tras `strip()`), lo que
>   excluye la negrita inline:
>   ```python
>   SECTION_HEADER_RE = re.compile(
>       r'^(?:---\s+\S.*\S\s+---|===\s+\S.*\S\s+===|━{3,}|\*\*[^*]+\*\*:?)$'
>   )
>   ```
>   **`plan_level_narrative_prompt` NO se excluye** — verificado sobre el prompt renderizado:
>   10 matches, las 10 cabeceras legítimas, cero falsos positivos del Markdown exigido en
>   `narrative`. **`long_term_plan_narrative_prompt` sí se excluye por nombre**, con el mismo
>   precedente de `tests/test_prompt_neutrality_oracle.py:201`: su plantilla de salida usa la
>   misma forma `**Texto**` que sus cabeceras (`analysis/prompts.py:924-929` vs.
>   `:898,903,910,919`) y ninguna regex de línea puede distinguirlas.
> - **(5.2')** El mismo test se aplica a los prompts renderizados de
>   `analysis/committee_prompts.py`. Hoy falla para los cuatro agentes de portfolio con
>   `{'===', '---'}`: 7 `===` y **8** `---` (`:219,244,270,280,297,313,324,333`).
> - **(5.3')** Todo campo de texto libre del contrato tiene techo de longitud declarado,
>   contra una constante enumerada a mano en el test (`rationale`, `reasoning`, `narrative`,
>   `explanation`, `why`, `cierre`, …). No existe un registro prompt→campos y construirlo no
>   está en el alcance de PR 5.

**Ampliación del «Qué» de PR 5:**

> Adoptar `=== SECCIÓN ===` en **`analysis/prompts.py` y `analysis/committee_prompts.py`**
> (conservando los literales `CONSTRAINTS DUROS` y `PASOS DE RAZONAMIENTO` que los tests
> asertan). PR 5 es el **dueño único de todo carácter delimitador de la serie**: ningún otro
> PR introduce ni modifica delimitadores.

### 5.3 Allowlist del criterio (c) — Q5

**Redacción vigente**, `docs/plans/PROMPTS_MULTIMODELO_PLAN.md:607-612` (cita textual):

> **Criterio (c):** `grep -rin grok --include='*.py' .` (excluyendo `venv/` y `__pycache__/`)
> no devuelve ninguna ocurrencia fuera de estas cuatro ubicaciones: `AI_PROVIDER_DISPLAY` en
> `config.py`, el catálogo de modelos de xAI y su etiqueta de proveedor en
> `dashboard/pages/9_Settings.py`, la lista de proveedores de `dashboard/pages/10_About.py`, y
> cualquier archivo bajo `tests/` que ejercite el proveedor `xai`.

**Redacción propuesta** (reemplaza ese bloque):

> **Criterio (c):** `grep -rin grok --include='*.py' .` (excluyendo `venv/` y `__pycache__/`)
> no devuelve ninguna ocurrencia fuera de estas **cinco** ubicaciones: `AI_PROVIDER_DISPLAY`
> en `config.py`, el catálogo de modelos de xAI y su etiqueta de proveedor en
> `dashboard/pages/9_Settings.py`, la lista de proveedores de `dashboard/pages/10_About.py`,
> cualquier archivo bajo `tests/` que ejercite el proveedor `xai`, y cualquier archivo bajo
> `tests/` cuya **única** mención de las marcas de proveedor sea dentro de una aserción que
> verifica su **ausencia** en el código o prompt bajo prueba (p. ej. una constante
> `VENDOR_MARKS`/`FORBIDDEN_MARKS` usada en `assert mark not in …`).

**Comentario opcional**, arriba de `tests/test_prompt_neutrality_oracle.py:67`:

```python
#: Marcas de proveedor que ningún prompt puede volver a nombrar. Esta constante y los
#: asserts que la usan son la QUINTA excepción del criterio (c) de
#: docs/plans/PROMPTS_MULTIMODELO_PLAN.md — "tests que afirman la ausencia de la marca",
#: no la cuarta ("tests que ejercitan xai").
VENDOR_MARKS = ("Grok", "xAI")
```

**Por qué A y no B.** El criterio (c) **no tiene hoy ningún test que lo implemente** —
verificado: no existe ningún test que recorra el árbol (`rglob`/`os.walk`/`glob`) verificando
marcas. Es un criterio documental que se corre a mano al cerrar un PR. Por lo tanto la opción
A es **puramente texto del plan**, cero riesgo de romper la suite. La opción B exige que
`test_prompt_neutrality_oracle.py` deje de contener el substring `grok` en su fuente, lo que
obliga a ofuscar `VENDOR_MARKS` (`"Gr" + "ok"`) o a mudar la prosa del docstring (`:3-5,28`):
no cambia lo que el test hace, lo vuelve ilegible para el propio grep que debería protegerlo, y
sienta el precedente de que el próximo test que necesite nombrar una marca en negativo invente
su propia evasión. Con B, un `grep` en cero deja de ser evidencia de nada.

**La excepción no abre una puerta indiscriminada.** Sigue detectando marca indebida en
producción: un `st.caption("Grok sugiere reducir la posición")` en
`dashboard/pages/2_Stock_Analysis.py` cae fuera —la excepción está acotada a `tests/`, y las
tres excepciones de producción siguen siendo enumeración cerrada por ubicación exacta—. Y no
permite excluir tests a voluntad, porque está escrita por **rol semántico del assert**, no por
carpeta: un `assert resultado.texto == "Grok dice: comprá más bonos"` en un test nuevo es una
aserción de **presencia**, no de ausencia, y el barrido lo sigue marcando. La granularidad por
archivo (no por línea) que hereda de la cuarta excepción es un riesgo ya aceptado
explícitamente por el owner (`PLAN.md:631-634`).

### 5.4 Barrido del criterio (c), revalidado hoy

12 ocurrencias de `grok` en `*.py`, todas clasificadas:

| Archivo:línea | Qué es | Excepción | Dentro/Fuera |
|---|---|---|---|
| `config.py:548` | `"xai": "Grok (xAI)"` | 1 | Dentro |
| `dashboard/pages/9_Settings.py:197` | catálogo de modelos de xAI | 2 | Dentro |
| `dashboard/pages/9_Settings.py:203` | etiqueta de proveedor | 2 | Dentro |
| `dashboard/pages/9_Settings.py:217` | branch que lee la etiqueta | 2, por extensión | Dentro (ver nota) |
| `dashboard/pages/10_About.py:284` | lista de proveedores | 3 | Dentro |
| `tests/test_prompt_neutrality_oracle.py:3,4,5,28,67` | docstring + `VENDOR_MARKS` | — | **FUERA hoy**; **Dentro** con la 5ª |
| `tests/test_ai_fallback_cause_oracle.py:371` | comentario | 4 | Dentro — el archivo sí ejercita `xai` (`:142-146` parametriza sobre `AI_PROVIDER_KEY_ENV`) |
| `tests/test_claude_transport_oracle.py:118` | `AIConfig(provider="xai", model="grok-4.3")` | 4 | Dentro — llama `_call_openai_compatible` |

Confirma exactamente la lista de `NEXT_STEPS.md:366-367`: no le sobra ni le falta nada.

*Nota de imprecisión preexistente, ajena a Q5:* el texto ratificado de la allowlist nombra dos
categorías en `9_Settings.py` («catálogo» y «etiqueta»), mientras que la tabla de hallazgos
previa (`PLAN.md:597`) nombraba también «el branch que la lee» (`:217`). Se interpreta cubierto
por intención —mismo archivo, mismo string, código que consume la etiqueta ya exceptuada—,
pero conviene corregirlo al mismo tiempo que se agrega la quinta excepción.

*Fuera del alcance del criterio por diseño:* las ocurrencias en `README.md`, `.env.example`,
`CONTRIBUTING.md` y `qa/sectionC.mjs` no son `.py`, así que el grep del criterio nunca las
alcanza; y las menciones de `xai` sin `grok` (`config.py:534,540`,
`analysis/ai_analyzer.py:518-519,614,616-617`, `config_validator.py:39-41`) no entran porque el
patrón grepeado es literalmente `grok`.

---

## 6. Orden de PRs y dependencias reales

**Orden recomendado: PR 7 → PR 4 → PR 5 → PR 6.** Difiere del plan (`PR 4 → PR 5 → PR 7 → PR 6`)
sólo en mover PR 7 al primer lugar.

**Por qué PR 7 primero:** es el único con consecuencia financiera —y con la ampliación de §2.5
ahora cubre el único campo que efectivamente se persiste (`PlanSnapshot.macro_risks`)—; es el
diff más chico, así que es el que menos ensucia los rebases; y sus cinco líneas de
`prompts.py` son cinco de las quince cabeceras `---` que PR 5 va a reescribir, así que hacerlo
antes ahorra una re-localización. El argumento en contra que da el plan —la dependencia de
verificabilidad de PR 0/1— ya está cerrado.

**Dependencias reales, después de estas decisiones:**

| Dependencia | ¿Real? | Resolución |
|---|---|---|
| PR 4 → PR 5 (convención del few-shot) | **Sí, y se resuelve por decisión**: Q2 fija que PR 4 no toca delimitadores y PR 5 es el dueño único | Q2 + Q3 (§3.4) |
| PR 5 ← PR 6 (`**bold**` exigido en `plan_level_narrative_prompt`) | **No.** Verificado sobre el prompt renderizado: 0 falsos positivos con el regex de línea completa | (5.1') |
| PR 5 ← PR 6 (`long_term_plan_narrative_prompt`) | **Existe, pero PR 6 no la resuelve** — se resuelve excluyendo el prompt por nombre | (5.1') |
| PR 7 ↔ PR 4/5/6 | **No.** PR 7 toca cabeceras de macro y una rama `if/else`; no toca contrato, delimitadores ni orden | §2 |
| PR 6 → todo | Va último por riesgo aguas abajo (`dashboard/pages/12_Plan.py:255-259, :379-387, :844-851`; `data/plan_store.py:98, :325`) | sin cambios respecto al plan |

`NEXT_STEPS` §6.6 declara «PR 5 depende de PR 6 en un criterio» y §5.0 del plan lo niega. **La
razón la tiene el plan**, por un motivo distinto al que da: la dependencia se disuelve con el
regex scopeado a línea completa, no porque los criterios sustantivos sean independientes.

---

## 7. Punto de producto aislado (no resuelto técnicamente)

Una sola preferencia de producto no se puede derivar del código: **si el sistema debe aspirar a
dar contexto macro fechado, o si es aceptable que declare permanentemente que no tiene datos
macro actuales.** La decisión de Q1 no la responde — sólo elige el camino barato *hoy* y deja
la condición de retoma escrita.

**Valor por defecto propuesto, con su fundamento:** que el sistema opere declarando la ausencia
de datos macro actuales, hasta que exista un mecanismo de ingesto automático. Fundamento: hoy
el módulo de RAG existe y está enhebrado en el comité, pero sin seeder automático el store está
vacío por defecto (§2.2) — o sea que el producto ya *funciona* así de hecho, sin decírselo al
modelo ni al usuario. El default propuesto no cambia el comportamiento: lo hace explícito.

---

## 8. Backlog derivado

| # | Entrada | Origen | Bloquea | Condición de retoma |
|---|---|---|---|---|
| **B1** | Enhebrar `macro_context` hasta los 5 prompts (texto completo en §5.1) | Q1 | nada | Que exista ingesto automático de `macro_rag_store` |
| **B2** | Gate de frescura acepta documentos sin `as_of` (`analysis/macro_rag.py:160` + `:78-79`) | Q1 (§2.2) | B1 | Inmediata: es un defecto acotado e independiente |
| **B3** | Ingesto automático de `MacroRagStore` (hoy sólo manual: `dashboard/pages/17_Macro_RAG.py:29,36`) | Q1 (§2.2) | B1 | Depende del punto de producto de §7 |
| **B4** | `build_portfolio_committee_context` (`analysis/committee.py:368-379`) no tiene caller de producción — sólo `tests/test_portfolio_committee.py:106,127,139` | Q1 | nada | Decidir si se activa el camino o se borra el helper |
| **B5** | `ruff` fuera de `requirements.txt` (`Makefile:32` lo invoca, sólo el CI lo instala) | §4.6 | ninguno, pero cuesta un paso manual en cada PR | Inmediata; es infraestructura ajena a esta serie |
| **B6** | `docs/INDEX.md:71` dice «8 PRs» y la numeración canónica lista nueve entradas con PR 3 absorbido | `NEXT_STEPS` §6.10 | nada | Cosmético, al cerrar la serie |
| **B7** | Corregir la allowlist para nombrar explícitamente el branch de `9_Settings.py:217` | Q5 (§5.4) | nada | Junto con la quinta excepción |

---

## 9. Matriz de verificación

| # | Caso | Resultado esperado | Defecto que detecta | Estado hoy |
|---|---|---|---|---|
| V1 | Renderizar los 9 prompts; buscar «conocimiento actual» | 0 ocurrencias | Actualidad macro pedida a la memoria del modelo | **Falla** (5) |
| V2 | `macro_strategist_prompt(fund, tech, "")` | Contiene «no hay datos macro actuales» + restricción a estructurales | Rama `if` sin `else`: ausencia = sin restricción | **Falla** |
| V3 | Los 4 prompts de portfolio con `ctx` sin `macro_context` | Idem V2 | Mismo defecto, ×4 agentes, no citado por el plan | **Falla** |
| V4 | `macro_strategist_prompt(fund, tech, "…hechos…")` | La prohibición de usar memoria sigue presente | Que V2 se implemente borrando la prohibición | **Verde** (regresión) |
| V5 | `plan_level_narrative_prompt` | Declara que `macro_risks` debe ser estructural y verificable | El único campo macro persistido en `PlanSnapshot` | **Falla** |
| V6 | Identificadores `snake_case` de la declaración de idioma, contra el mismo prompt renderizado | Cada uno aparece ≥1 vez más | Campos inexistentes en el contrato (`key_strengths`, `key_risks`) | **Falla** (4) |
| V7 | «IDIOMA OBLIGATORIO» por prompt renderizado | Exactamente 1 | Declaración de idioma duplicada | **Verde** (regresión) |
| V8 | Instrucciones repetidas dentro de **un mismo** prompt renderizado | Ninguna se repite | Duplicación que sí cuesta tokens — sin borrar protección de prompts independientes | **Verde** (regresión) |
| V9 | Bloque de ejemplos de `equity_decision_prompt` | ≥2 ejemplos, ≥1 de compra | Few-shot único y negativo → sesgo a degradar | **Falla** |
| V10 | `SECTION_HEADER_RE` sobre cada prompt renderizado de `prompts.py` (excl. `long_term_plan_narrative`) | ≤1 convención por prompt | 4 convenciones conviviendo | **Falla** |
| V11 | Idem sobre los prompts renderizados de `committee_prompts.py` | ≤1 convención | 7 `===` + 8 `---` en el mismo archivo | **Falla** (4 agentes) |
| V12 | `SECTION_HEADER_RE` sobre `plan_level_narrative_prompt` renderizado | 10 matches, 0 del Markdown de `narrative` | Que el test dé falso positivo por el `**bold**` exigido en el payload | **Verde** (verificado) |
| V13 | Campos de texto libre enumerados a mano | Cada uno con techo declarado | Campos que se estiran sin límite (H9) | **Falla** (sólo 2 techos: `:936`, `:1317`) |
| V14 | `grep -rin grok --include='*.py' .` | Sólo las 5 ubicaciones de la allowlist nueva | Marca de proveedor reintroducida en producción | **Verde con la 5ª excepción**; falla con la redacción actual |

---

## 10. Comandos ejecutados, resultados y limitaciones

**Ejecutado en este turno (sólo lectura; ningún archivo de producción, test o workspace externo
fue modificado):**

- `grep -n "IDIOMA OBLIGATORIO" analysis/prompts.py` → **9** (`:313,473,584,722,824,896,1016,1279,1377`);
  `grep -nE "^def " analysis/prompts.py` → **9 prompts públicos** (`:279,418,538,676,790,859,953,1101,1347`).
  **Una declaración por prompt: el criterio estrella de PR 4 ya está verde.**
- `grep -n "conocimiento actual" analysis/prompts.py` → **5** (`:330,507,602,747,1044`), confirma
  `NEXT_STEPS` §1 línea por línea. `grep -c macro_context analysis/prompts.py` → **0**.
- `grep -n "key_strengths\|key_risks" analysis/prompts.py` → **sólo** las 4 líneas de idioma;
  `retirement_risk_summary` (`:557`) y `action_suggested` (`:818`) **sí** existen en sus
  contratos; `tips` es abreviatura de `human_review_tips` (`:1081`).
- `grep -n "_tailwind_context_block\|_hard_decision_constraints_block" analysis/prompts.py` →
  un caller cada uno (`:469`, `:514`). Confirma que `:233`, `:1047` y `:1157` son tres prompts
  independientes.
- Script Python con `SECTION_HEADER_RE` sobre ambos archivos →
  `prompts.py`: 15 `---`, 5 `━━━`, 29 `**bold**`, 0 `===`;
  `committee_prompts.py`: **7 `===` y 8 `---`** (`:219,244,270,280,297,313,324,333`).
- Render real de `plan_level_narrative_prompt` y `long_term_plan_narrative_prompt` en un venv
  descartable **fuera del repo** (`/tmp`), con los mismos kwargs de los fixtures existentes →
  10 matches / 0 falsos positivos en el primero; 3 falsos positivos en el segundo.
- `grep -rn "build_portfolio_committee_context("` → definición (`analysis/committee.py:368`) +
  **sólo tests** (`tests/test_portfolio_committee.py:106,127,139`).
- `grep -rn "ingest_from_fred\|example_macro_docs"` → definiciones + **sólo**
  `dashboard/pages/17_Macro_RAG.py:29,36`. Sin seeder automático.
- `grep -n macro_risks data/plan_store.py dashboard/pages/12_Plan.py` → `:108` / `:827-868`:
  confirma la cadena de persistencia y que la produce `plan_level_narrative_prompt`.
- `grep -rin grok` sobre `*.py` → 12 ocurrencias, clasificadas en §5.4.
- `ls venv/bin/ruff` → no existe; `grep -n ruff requirements.txt` → sin resultados;
  `Makefile:32` lo invoca. `ANTHROPIC_API_KEY` no está definida; no hay `count_tokens` en el repo.
- `WebFetch` a `developers.openai.com/api/docs/guides/prompt-engineering` y a
  `ai.google.dev/gemini-api/docs/prompting-strategies` (citas en §3.2); `WebSearch` para xAI →
  **sin documentación oficial de prompting**.

**Resultados históricos, no re-ejecutados:** el «4201 passed, 2 skipped» de PR 2 se toma del
plan. Los diffs estimados (~80 / ~250 / ~500 / ~200 líneas) vienen de `NEXT_STEPS` §0 y no se
recalcularon.

**Verificaciones pendientes y limitaciones:**

- **No se corrió `pytest` ni `make check`.** El encargo es de análisis sin editar código, y
  `make check` sigue requiriendo `venv/bin/pip install ruff` a mano.
- **No se llamó a ningún modelo.** Ninguna afirmación de comportamiento está verificada: que el
  few-shot negativo sesgue hacia HOLD/REDUCE, que las negaciones apiladas produzcan
  `macro_factors: []`, o que los campos sin techo se estiren, son hipótesis de la doctrina
  citada. **Todos los criterios de estos PRs son invariantes estáticos sobre el string
  renderizado: prueban que el prompt cambió como se quería, no que el modelo responde mejor.**
  Conviene decirlo en cada PR.
- **La doctrina de Anthropic no se re-consultó hoy** — se usa la cita del plan (2026-09-14).
- **El estado real del store de `macro_rag` en runtime** (que `count()` sea 0) es una inferencia
  de código por ausencia de seeder, no una observación de una base SQLite en vivo.
- **Sólo se renderizaron 2 de los 9 prompts** end-to-end; para los otros 7 y para
  `committee_prompts.py` se usó grep sobre la fuente como proxy, válido porque ninguna línea de
  cabecera candidata tiene interpolación antes del delimitador.
- **`analysis/eval_harness.py:280` instancia `CommitteeAnalyzer`** y no se verificó si ejercita
  `build_portfolio_committee_context`; eso movería el hallazgo B4 de «sin caller» a «sin caller
  salvo el harness de evaluación».
- **Discrepancia de fuentes.** El encargo apuntaba a una copia de `NEXT_STEPS.md` en
  `/Users/fercalvino/conductor/workspaces/retirement-advisor/prompts-multimodelo-plan-analisis/`.
  Ese path es un **symlink al mismo worktree** (`vientiane`): no existe una segunda copia, y
  por lo tanto no hay diferencias que conciliar. No se reemplazó ninguna fuente.
