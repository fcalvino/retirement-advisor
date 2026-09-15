# Próximos pasos de la serie multimodelo — verificado contra el código (2026-09-15)

> **Qué es esto.** Una re-verificación de los cuatro PRs abiertos de
> [`PROMPTS_MULTIMODELO_PLAN.md`](PROMPTS_MULTIMODELO_PLAN.md) (PR 4, 5, 6, 7) **contra el
> archivo de hoy**, no contra el que el plan describe. El plan avisa en §5.0 que PR 2
> reescribió `analysis/prompts.py` y que sus citas de línea están corridas o consumidas;
> acá están re-localizadas, con evidencia `archivo:línea` del 2026-09-15 sobre
> `fa75406` (rama `fercalvino-cu/prompts-multimodelo-plan-analisis`, worktree limpio).
>
> **No se implementó nada.** Ningún archivo de `analysis/`, `tests/` o `dashboard/` se tocó
> en este turno.

---

## 0. Resumen ejecutable

| PR | Hallazgos | ¿Siguen vivos? | Criterios de aceptación | Diff estimado | Riesgo aguas abajo |
|---|---|---|---|---|---|
| **PR 7** — macro sin memoria | H11 | ✅ **completo**, 5 sitios en `prompts.py` + 2 en `committee_prompts.py` | 1 de 3 **inverificable como está escrito** | ~80 líneas | Ninguno (sólo texto de prompt + tests nuevos) |
| **PR 4** — higiene | H5, H6 | ✅ parcial: negaciones y few-shot vivos; **el criterio de idioma ya está verde** | 1 trivialmente cierto, 1 necesita registro de campos, 1 no medible en este entorno | ~250 líneas | Bajo (`tests/test_prompts.py:277`) |
| **PR 5** — estructura | H7, H8, H9 | ✅ completo, y **más grande que lo que el plan dice** | 1 colisiona con H4 (dependencia de PR 6 que el plan niega) | ~500 líneas | Medio (mayor churn de la serie) |
| **PR 6** — Markdown → campos | H4 | ✅ completo | Verificables; las citas de línea están corridas | ~200 líneas | **Alto** (`12_Plan.py`, export PDF, `PlanSnapshot.narrative`) |

**Recomendación: ejecutar PR 7 primero**, no PR 4. Justificación en §5.

---

## 1. PR 7 — El macro deja de salir de la memoria del modelo (H11)

### Estado real

H11 sigue vivo **entero**. Los cinco «usá tu conocimiento actual» de `prompts.py` están
donde el plan dice que deberían estar, corridos:

| Plan (§H11, pre-PR 2) | Hoy | Prompt |
|---|---|---|
| `:302` | `analysis/prompts.py:330` | `equity_moat_prompt` |
| `:479` | `analysis/prompts.py:507` | `equity_decision_prompt` |
| `:574` | `analysis/prompts.py:602` | `crypto_moat_prompt` |
| `:719` | `analysis/prompts.py:747` | `crypto_decision_prompt` |
| `:1016` | `analysis/prompts.py:1044` | `portfolio_optimizer_advice_prompt` |

En el comité, `macro_strategist_prompt` (`analysis/committee_prompts.py:118-132`) conserva
el patrón exacto que H11 describe: `if macro_context:` agrega «Usá EXCLUSIVAMENTE estos
hechos macro fechados … no inventes datos macro ni uses tu memoria de entrenamiento»
(`:128-131`), **sin rama `else`** — o sea que sin contexto el agente queda con el mandato
de evaluar macro (`:120-124`) y ninguna prohibición.

**Hallazgo nuevo, no citado por el plan:** el mismo defecto existe una segunda vez en el
camino de portfolio. `portfolio_committee_context_block`
(`analysis/committee_prompts.py:331-333`) hace `if macro: lines += [… "usalo, no inventes"]`,
también sin `else`. Ese bloque lo consumen los **cuatro** agentes de portfolio
(`plan_strategist`, `risk_manager_portfolio`, `macro_strategist_portfolio`,
`devils_advocate_portfolio`, vía `_portfolio_role_prompt` en `:337`). PR 7 debe tocar
**dos** sitios en `committee_prompts.py`, no uno.

### Criterios de aceptación — corregidos

El plan pide tres. El primero **no es verificable tal como está escrito**:

> ~~Test: sin `macro_context`, ningún prompt contiene «conocimiento actual».~~

`grep -n 'macro_context' analysis/prompts.py` devuelve **cero**: ninguno de los nueve
prompts de `prompts.py` recibe `macro_context`. No hay un «sin `macro_context`» que
ejercitar ahí — la frase «usá tu conocimiento actual» es incondicional. El criterio sólo
tiene sentido para los dos sitios de `committee_prompts.py`. Reformulación propuesta:

- **(7.1)** Ningún prompt de `analysis/prompts.py` contiene «conocimiento actual», en
  ninguna invocación. *(Invariante estático sobre el string renderizado; el fixture
  `prompts` de `tests/test_prompt_neutrality_oracle.py` ya renderiza los nueve.)*
- **(7.2)** Para `macro_strategist_prompt` y para los cuatro prompts de portfolio: **sin**
  `macro_context`, el prompt contiene la declaración de que no hay datos macro actuales y
  la restricción a factores estructurales.
- **(7.3)** **Con** `macro_context`, la prohibición de usar memoria sigue presente (el
  criterio 3 del plan, intacto: es el anti-trampa de (7.2)).
- **(7.4)** `make check` verde — ver §6, requiere `venv/bin/pip install ruff` a mano.

### Dependencias

Ninguna. PR 7 edita cabeceras de sección de macro y una rama `if/else`; no toca contrato de
salida, ni delimitadores, ni orden. Es independiente de PR 4, 5 y 6 en ambos sentidos.

Con una salvedad de orden: PR 5 va a reescribir literalmente las mismas cinco líneas
(`--- CONTEXTO MACRO GLOBAL Y NACIONAL A CONSIDERAR (…) ---` es una de las cuatro
convenciones de delimitador que PR 5 unifica). Hacer PR 7 **antes** de PR 5 cuesta un rebase
textual trivial; hacerlo después obliga a PR 7 a re-localizar otra vez.

### Riesgo aguas abajo

El más bajo de los cuatro. No toca `ai_analyzer.py`, ni `plan_store.py`, ni la UI, ni el
contrato de campos. `tests/test_prompts.py:239-243` asserta sobre `macro_factors` y es
compatible (§4.2 del plan ya lo anticipaba). Tamaño estimado: ~30 líneas de producción +
~150 de oráculo nuevo.

### Pregunta para el owner

**Q1 — alcance del arreglo en `prompts.py`.** Hay dos arreglos posibles y el plan no elige:

1. **Barato:** borrar «usá tu conocimiento actual» de los 5 sitios y reemplazar el encabezado
   por la declaración de «no hay datos macro actuales; `macro_factors` sólo estructurales».
   Cierra H11 tal como el plan lo enuncia, sin tocar callers.
2. **Completo:** enhebrar `macro_context` desde `analysis/macro_rag` hasta los prompts de
   `prompts.py` —como ya hace `committee.py:523-525, 704-712`— para que los cinco puedan
   recibir hechos fechados cuando existan. Es un PR bastante más grande y toca `moat.py`,
   `crypto_analyzer.py`, `ai_analyzer.py` y `tailwind.py`.

El plan describe (1) en su «Qué» pero justifica H11 con un riesgo que sólo (2) elimina del
todo. **Recomiendo (1) ahora y (2) como entrada de backlog**, porque (1) ya corta la
alucinación con fecha implícita, que es el daño financiero.

---

## 2. PR 4 — Higiene de instrucciones: idioma, negaciones y few-shot (H5, H6)

### Estado real

**Vivo:** las negaciones y el few-shot. **Ya resuelto de rebote / mal enunciado:** el
criterio de idioma.

| Ítem de H5/H6 | Cita del plan | Hoy | ¿Vivo? |
|---|---|---|---|
| «No fuerces factores de relleno» | `:122` | `analysis/prompts.py:150` | ✅ |
| «NO inventes colas de viento» ×3 | `:205`, `:1019`, `:1129` | `:233`, `:1047`, `:1157` | ✅ las tres |
| «NO inventes números de decumulación» | `:1297` | `:1325` | ✅ |
| «NO inventes colas … ni cambies el score curado» | `:1362` | `:1390` | ✅ |
| 4 negaciones del comité | `cp:106,125,328,339` | `cp:111,130,333,344` | ✅ |
| Listas muertas `key_strengths`/`key_risks` | `:445,:556,:694,:796` | `:313`, `:473`, `:584`, `:722` | ✅ **cuatro**, no cuatro-de-nueve |
| Few-shot único y negativo | `:240-242` | `analysis/prompts.py:268-270` | ✅ |

### Contradicción 1 — el criterio estrella de PR 4 ya está verde

> «Test: en cada prompt, "IDIOMA OBLIGATORIO" aparece **exactamente una vez**.»

Medido hoy: `analysis/prompts.py` tiene **nueve** ocurrencias de `IDIOMA OBLIGATORIO`
(`:313, :473, :584, :722, :824, :896, :1016, :1279, :1377`) y **nueve** prompts públicos
(`def` en `:279, :418, :538, :676, :790, :859, :953, :1101, :1347`). Una por prompt,
exactamente. En el comité la declaración vive una sola vez, dentro de
`AGENT_JSON_SCHEMA` (`analysis/committee_prompts.py:48`), compartida por los ocho agentes.

H5 decía «repetida nueve veces» y el criterio la leyó como repetición **dentro** de un
prompt; son nueve prompts distintos. Escrito así, el test pasa sobre el código de hoy y no
puede detectar el defecto que PR 4 quiere arreglar. **El defecto real es otro:** cuatro de
esas nueve declaraciones enumeran `key_strengths` / `key_risks`, campos que no existen en
el contrato de ninguno de esos cuatro prompts. Criterio reformulado:

- **(4.1)** Ninguna declaración de idioma enumera nombres de campo. *(Mata las cuatro listas
  muertas por construcción y no depende de saber el contrato de cada prompt.)*
- **(4.2)** «IDIOMA OBLIGATORIO» aparece exactamente una vez por prompt renderizado.
  *(Conservar como regresión —hoy verde— y decirlo en el PR: es un candado, no un arreglo.)*
- **(4.3)** «NO inventes colas de viento» aparece **una** vez en el conjunto de los nueve
  prompts, no tres. *(Hoy `:233`, `:1047`, `:1157` son tres capas del mismo pipeline.)*
- **(4.4)** El bloque de ejemplos contiene ≥2 ejemplos y ≥1 con `action` de compra.
  *(Criterio del plan, verificable tal cual.)*

El criterio del plan «ningún prompt menciona un nombre de campo que no esté en su propio
contrato JSON» es verificable **sólo si alguien construye el registro prompt→campos**, que
hoy no existe en ningún lado: cada contrato está embebido en un f-string. Además da falsos
positivos garantizados (`sector_country_tailwind_prompt` renombra el campo en vuelo con
`_macro_factors_output_spec(...).replace("macro_factors", "factors")`, `prompts.py:1392`).
(4.1) captura el mismo defecto sin el registro.

### Contradicción 2 — dónde vive el few-shot

El plan lo presenta como parte de «los prompts de decisión». Medido: el few-shot está en
`_hard_decision_constraints_block` (`analysis/prompts.py:238-278`, el bloque empieza en
`:268`), y ese helper tiene **un solo caller**: `equity_decision_prompt`
(`analysis/prompts.py:514`). `crypto_decision_prompt` tiene su propio bloque de constraints
(`:755-766`) y **no lleva few-shot ninguno**. O sea que H6 afecta a un prompt, no a dos, y
PR 4 tiene que decidir si el few-shot nuevo se replica al camino crypto o no.

### Dependencias y riesgo

Independiente de PR 5, 6 y 7. El único test que rompe es
`tests/test_prompts.py:277` (`assert "FEW-SHOT" in prompt or …`), tal como §4.2 del plan
predice. Diff estimado ~250 líneas (≈40 de producción, el resto oráculo).

**Q2 — ¿`FEW-SHOT` literal o `<examples>`?** El plan pide `<examples><example>…` (doctrina
de Anthropic, portable de hecho) pero H7 deja abierto si el archivo entero sube a XML. Si
PR 4 mete `<examples>` y PR 5 después decide `=== SECCIÓN ===`, el archivo queda con dos
convenciones justo en el prompt más grande. Conviene que el owner fije la convención
**antes** de PR 4, o que PR 4 use el literal `FEW-SHOT` y deje el envoltorio a PR 5.

---

## 3. PR 5 — Estructura: delimitador único y orden datos→instrucción (H7, H8, H9)

### Estado real

Vivo y **más grande de lo que el plan dice**. Conteo de hoy sobre `analysis/prompts.py`:

- 15 cabeceras `--- SECCIÓN ---` (`:254, :261, :479, :500, :507, :515, :602, :703, :729,
  :738, :744, :747, :755, :761, :768`)
- 5 reglas `━━━` (`:348, :360, :372, :383, :393`)
- 7 cabeceras `**Sección:**` (`:588, :599, :610, :647, :919, :1055, :1314`)
- Cabeceras a secas (`REGLAS CRÍTICAS ANTES DE PUNTUAR:` `:340`, `INSTRUCCIÓN FINAL:` `:395`,
  `TAREA:` `:1389`)
- **Cero** ocurrencias de `=== SECCIÓN ===` en `prompts.py`

H9 también intacto: los únicos techos de longitud siguen siendo dos
(`analysis/prompts.py:936` y `:1317`, ambos «180-280 palabras»).

**Contradicción 3 — `committee_prompts.py` no es tan consistente como H7 afirma.** H7 lo
declara «`=== SECCIÓN ===` de forma consistente» y lo propone como modelo. Pero
`analysis/committee_prompts.py:333` usa `--- Contexto macro fechado (usalo, no inventes) ---`,
la convención que PR 5 viene a erradicar, dentro del bloque de contexto más grande del
archivo. PR 5 tiene que tocar `committee_prompts.py` también; su «Qué» dice «en todo
`prompts.py`» y lo deja afuera.

### Criterios de aceptación — corregidos

> «Test: ningún prompt mezcla dos convenciones de delimitador (`---`, `**bold:**`, `━━━`).»

Verificable, con una trampa: `plan_level_narrative_prompt` **exige `**bold**` en su payload**
— el contrato pide viñetas con encabezados en negrita dentro del campo `narrative`
(`analysis/prompts.py:1317-1318`) y el ejemplo lo muestra así (`:1331`). Un test que barra
`**` sobre el prompt renderizado va a marcar ese prompt para siempre, a menos que:
(a) el test distinga cabecera de sección (línea que empieza con `**`) de negrita inline, o
(b) PR 6 llegue primero y elimine el Markdown-dentro-de-JSON. **Esto es una dependencia real
PR 5 ← PR 6** que §5.0 niega explícitamente («ninguno de los cuatro depende de un hallazgo
sin cerrar»). Es cierto que no dependen en sus criterios *sustantivos*; en éste sí.

Criterio (H9) «todo campo de texto libre del contrato tiene un límite de longitud declarado»:
verificable sólo con el mismo registro prompt→campos que falta para PR 4 (§2). Reformulación
barata y honesta: **enumerar a mano los campos de texto libre** (`rationale`, `reasoning`,
`narrative`, `explanation`, `why`, `cierre`, …) en una constante del test y afirmar que cada
uno aparece acompañado de un techo en el prompt donde se declara.

### Dependencias y riesgo

El de mayor churn: reescribe cabeceras en los nueve prompts y reordena los dos grandes
(`portfolio_optimizer_advice_prompt` `:953-1099`, `plan_level_narrative_prompt` `:1101-1345`).
Los asserts existentes son de pertenencia (`"CONSTRAINTS DUROS" in prompt`,
`tests/test_prompts.py:274-275`), no de posición, así que sobreviven al reordenamiento
mientras se conserven los literales — que es exactamente lo que el «Qué» del plan ya manda.
Diff estimado ~500 líneas. Riesgo de producción bajo (nada se parsea posicionalmente), riesgo
de revisión alto (es imposible leer el diff sin renderizar los prompts antes y después).

**Q3 — `=== SECCIÓN ===` o XML.** H7 clasifica los XML tags como «Claude-first, sin costo de
portabilidad» y el owner no eligió. La decisión cambia el tamaño de PR 5 y condiciona a PR 4
(§2, Q2).

---

## 4. PR 6 — Narrativa de plan: Markdown → campos estructurados (H4)

### Estado real

Vivo. Los dos sitios están donde H4 describe, corridos:

- `long_term_plan_narrative_prompt`: Markdown puro con encabezados en negrita
  (`analysis/prompts.py:922-938`), cerrando con «Respondé SOLO con el texto en el formato
  pedido. Nada de JSON» (`:938`). Es el único de los nueve fuera de `JSON_ONLY_CONTRACT`, y
  `tests/test_prompt_neutrality_oracle.py:201` lo excluye con un test explícito
  (`test_the_markdown_prompt_is_excluded_on_purpose`) — **ese test hay que actualizarlo si
  PR 6 lo convierte a JSON**, porque hoy falla si alguien lo hace. Es el anti-trampa de PR 2
  funcionando exactamente como se diseñó; PR 6 es la razón legítima para levantarlo.
- `plan_level_narrative_prompt`: Markdown serializado dentro del campo JSON `narrative`
  (`analysis/prompts.py:1317-1331`).

**Contradicción 4 — la cita del fallback está corrida y es doble.** El plan dice
«el fallback de `ai_analyzer.py:196-198` cubre el caso». Hoy `generate_plan_narrative` vive
en `analysis/ai_analyzer.py:294-360` y el rescate de prosa son **dos** ramas distintas:
`:330-333` (el JSON no parsea → `data = {}`) y `:345-347` (parsea pero sin `narrative` → se
toma el texto crudo). El criterio «una respuesta vieja se sigue aceptando» tiene que cubrir
las dos, no una.

### Criterios de aceptación

Verificables tal como están, con las líneas corregidas. Agregaría un cuarto, porque el
riesgo real de PR 6 no es el parseo sino la recomposición:

- **(6.5)** El Markdown compuesto por `generate_plan_narrative` es byte-comparable en
  estructura con el que hoy produce el modelo (mismos siete encabezados, mismo orden), para
  que un `PlanSnapshot` guardado ayer y uno guardado después de PR 6 se rendericen igual.

### Riesgo aguas abajo — el más alto de los cuatro

- `dashboard/pages/12_Plan.py:255-259` renderiza la narrativa viva con `st.markdown`, y
  `:844-851` la narrativa **persistida** (`snap.narrative`). Ninguno cambia si
  `generate_plan_narrative` sigue devolviendo `narrative: str`.
- `dashboard/pages/12_Plan.py:379-387` la mete en el export PDF
  (`include_ai_narrative`) — superficie que el plan no menciona.
- `data/plan_store.py:98` (`narrative: str = ""`) y `:325` (se puebla desde
  `opt_result.ai_narrative`): **no cambian de forma**, que es la garantía que PR 6 debe
  preservar y el motivo por el que va último.
- Tests que tocan la forma: `tests/test_prompts.py:631-671`
  (`test_parses_narrative_and_caps_macro_at_two`, `test_non_json_response_becomes_narrative`)
  — son exactamente los que ejercitan las dos ramas de rescate.

Diff estimado ~200 líneas (≈70 de producción: el contrato nuevo del prompt + el compositor
en `ai_analyzer`).

---

## 5. Recomendación: **el próximo PR es PR 7**

El plan recomienda `PR 4 → PR 5 → PR 7 → PR 6`. Con lo medido arriba, propongo
**`PR 7 → PR 4 → PR 5 → PR 6`**. Sólo se mueve PR 7, del tercer lugar al primero.

**Por qué PR 7 antes que PR 4:**

1. **Es el único con consecuencia financiera.** El propio plan lo dice (H11: «único hallazgo
   con consecuencia financiera directa») y lo mide bien: un factor macro alucinado entra en
   `macro_factors`, se persiste en `PlanSnapshot.macro_risks` y se le muestra al usuario como
   análisis del plan meses después. H5 y H6 son costo de tokens y sesgo de estilo; H7/H8/H9
   son legibilidad. Nada en el orden original justifica postergar el único defecto que puede
   hacerle perder plata a alguien — lo que sí lo justificaba era la dependencia de
   verificabilidad de PR 0/1, y ésa ya está cerrada.
2. **Es el diff más chico y el de menor churn** (~30 líneas de producción), así que es el que
   menos ensucia los rebases de PR 4 y PR 5.
3. **PR 4 rinde menos de lo que el plan cree.** Su criterio de aceptación estrella ya está
   verde sobre el código de hoy (§2, contradicción 1), su medición en tokens es inverificable
   en este entorno (hallazgo (q) del plan, reconfirmado en §6) y su ahorro declarado
   (~400 tok/llamada) es justamente lo que no se puede medir. Sigue valiendo la pena —las
   cuatro listas muertas y el few-shot de un solo lado son defectos reales— pero no es el
   trabajo más urgente.
4. **El orden relativo PR 7 → PR 5 ahorra una re-localización.** Las cinco líneas que PR 7
   edita son cinco de las quince cabeceras `---` que PR 5 reescribe.

El resto del orden del plan se sostiene: PR 4 antes que PR 5 (higiene antes que
reestructura, para no reordenar texto que después se borra), y PR 6 último por riesgo aguas
abajo — con el matiz de §3: si el owner quiere que el criterio de delimitadores de PR 5 sea
limpio, PR 6 podría adelantarse a PR 5. No lo recomiendo: el costo de scopear el test de
delimitadores a «cabeceras de línea» es de una línea de regex, y es mucho menor que adelantar
el PR más riesgoso de la serie.

---

## 6. Contradicciones plan ↔ código encontradas

1. **PR 4, criterio de idioma: ya está verde.** «IDIOMA OBLIGATORIO exactamente una vez por
   prompt» es cierto hoy — nueve ocurrencias, nueve prompts
   (`analysis/prompts.py:313,473,584,722,824,896,1016,1279,1377` vs. `def` en
   `:279,418,538,676,790,859,953,1101,1347`). El defecto real es la enumeración de campos
   muertos en cuatro de ellas. §2, (4.1).
2. **PR 7, criterio 1: inverificable.** «Sin `macro_context`, ningún prompt contiene
   "conocimiento actual"» — `analysis/prompts.py` **no recibe `macro_context` en ningún
   prompt** (`grep 'macro_context' analysis/prompts.py` → 0 hits). La condición no existe.
   §1, (7.1).
3. **PR 7 subcuenta los sitios del comité.** El plan cita `committee_prompts.py:113-127`
   (hoy `:118-132`). Falta `portfolio_committee_context_block:331-333`, mismo patrón
   `if macro:` sin `else`, consumido por los cuatro agentes de portfolio vía `:337`.
4. **H7 llama consistente a `committee_prompts.py` y no lo es.** `:333` usa
   `--- Contexto macro fechado ---`. PR 5 debe alcanzar ese archivo; su «Qué» dice sólo
   «en todo `prompts.py`».
5. **H6 ubica mal el few-shot.** Vive en `_hard_decision_constraints_block`
   (`analysis/prompts.py:238-278`, el bloque en `:268-270`), cuyo **único** caller es
   `equity_decision_prompt` (`:514`). `crypto_decision_prompt` tiene constraints propios
   (`:755-766`) sin few-shot.
6. **PR 5 depende de PR 6 en un criterio.** «Ningún prompt mezcla dos convenciones» choca con
   el contrato de `plan_level_narrative_prompt`, que **exige** `**bold**` dentro de
   `narrative` (`:1317-1318`, ejemplo en `:1331`). §5.0 afirma que ninguno de los cuatro
   depende de otro; en este criterio sí.
7. **PR 6 cita un fallback que se movió y que es doble.** `ai_analyzer.py:196-198` → hoy
   `analysis/ai_analyzer.py:330-333` **y** `:345-347`, dentro de
   `generate_plan_narrative` (`:294-360`).
8. **La magnitud del corrimiento está subestimada.** §5.0 dice «~23 líneas hacia abajo»;
   medido es **28** en `equity_moat` (285→313), **28** en `equity_decision` (445→473) y
   **28** en `sector_country_tailwind` (1349→1377). No cambia ninguna conclusión, pero el
   número que §5.0 le da al próximo implementador es incorrecto.
9. **El criterio (c) resuelto por el owner deja afuera al oráculo que lo hace cumplir.** La
   allowlist admite «cualquier archivo bajo `tests/` que **ejercite** el proveedor `xai`».
   `tests/test_prompt_neutrality_oracle.py` (`:3,4,5,28,67` — `VENDOR_MARKS = ("Grok",
   "xAI")`) no ejercita `xai`: afirma su **ausencia**. Corriendo el criterio literal hoy,
   ese archivo cae fuera de la allowlist. El resto del barrido está limpio y dentro de las
   excepciones (`config.py:548`, `9_Settings.py:197,203,217`, `10_About.py:284`,
   `test_ai_fallback_cause_oracle.py:371`, `test_claude_transport_oracle.py:118`).
   Arreglo de una línea: agregar a la allowlist «tests que afirman la ausencia de la marca».
10. **`docs/INDEX.md:71` dice «8 PRs»** y la numeración canónica de §5.0 lista nueve entradas
    con PR 3 absorbido. Cosmético; no lo toqué.

---

## 7. Lo que no se pudo verificar, y por qué

- **La medición en tokens que PR 4 exige como criterio.** Igual que el hallazgo (q) del plan:
  la única cuenta correcta es `client.messages.count_tokens`, y en este entorno no hay
  `ANTHROPIC_API_KEY`. Un tokenizador de terceros daría un número que no es el que la API
  factura. PR 4 se va a topar con exactamente lo mismo que PR 2: o se corre desde un entorno
  con credencial, o se reporta en caracteres y se dice que no es el criterio.
- **`make check` verde.** Sigue requiriendo `venv/bin/pip install ruff` a mano:
  `venv/bin/ruff` no existe y `ruff` no está en `requirements.txt` — el `Makefile:32` lo
  invoca y sólo el CI lo instala. La nota de entorno de §5.0 sigue vigente sin cambios al
  2026-09-15.
- **El estado verde del suite.** No corrí `pytest` en este turno (el encargo lo restringe a
  análisis sin editar código, y la corrida completa no aporta a la decisión de orden). El
  «4201 passed, 2 skipped» de PR 2 se toma del plan, no se re-verificó.
- **Cualquier afirmación de comportamiento.** Que el few-shot de `:268-270` efectivamente
  sesgue hacia HOLD/REDUCE, que las negaciones apiladas produzcan `macro_factors: []` por
  cautela, o que los campos sin techo se estiren con Opus 5, son hipótesis de la doctrina
  citada en §6 del plan: no hay arnés de evaluación en el repo ni credencial para armarlo.
  **Todos los criterios de aceptación de los cuatro PRs abiertos son invariantes estáticos
  sobre el string renderizado** — lo cual está bien, pero conviene decirlo en cada PR: se
  verifica que el prompt cambió como se quería, no que el modelo responde mejor.

---

## 8. Preguntas abiertas para el owner

| # | Pregunta | Bloquea |
|---|---|---|
| **Q1** | PR 7: ¿arreglo barato (borrar «conocimiento actual» + restringir a estructurales) o completo (enhebrar `macro_context` de `macro_rag` hasta `prompts.py`)? Recomiendo barato ahora, completo al backlog. | PR 7 |
| **Q2** | ¿El few-shot de PR 4 conserva el literal `FEW-SHOT` o pasa a `<examples>`? Depende de Q3. | PR 4 |
| **Q3** | PR 5: ¿`=== SECCIÓN ===` (mínimo viable, portable) o XML tags en los dos archivos a la vez? H7 lo dejó abierto. | PR 4, PR 5 |
| **Q4** | ¿Se acepta reformular los criterios marcados en §1 y §2, o el plan se ejecuta literal y se reporta «verde por construcción» en el de idioma? | PR 4, PR 7 |
| **Q5** | Criterio (c): ¿se agrega la quinta excepción de la allowlist («tests que afirman la ausencia de la marca») o se re-scopea `test_prompt_neutrality_oracle.py`? | ninguno (higiene) |
