# Adaptación multimodelo de los prompts — estado y plan de lo que sigue

> **Rol:** `living-guide`. Quedan abiertos PR 4, 5, 6 y 7 de la serie. En el BACKLOG: PROMPTS-MULTIMODELO,
> MACRO-SIN-FECHA (B2) y CONFIDENCE-SELL-BAND (punta suelta de SIGNAL-3).
> **Alcance:** los prompts de `analysis/prompts.py` y `analysis/committee_prompts.py`, y los
> parámetros de API de `analysis/ai_analyzer.py` que los entregan.
> **Origen:** este archivo reemplaza a tres (`PROMPTS_MULTIMODELO_PLAN.md`,
> `PROMPTS_MULTIMODELO_NEXT_STEPS.md`, `PROMPTS_MULTIMODELO_OWNER_DECISIONS.md`; 2026-09-14/15,
> ~2.200 líneas). Quedan en git, en `826ca50`:
> `git show 826ca50:docs/plans/PROMPTS_MULTIMODELO_PLAN.md` (y `_NEXT_STEPS`, `_OWNER_DECISIONS`). El plan original llevaba la
> tabla de 11 hallazgos (H1–H11) con cita textual, el inventario de prompts y los «Hallazgos de la
> ejecución» de PR 0, 1 y 1.5/2; esta versión conserva las decisiones, los criterios y el orden.
> **Las citas `archivo:línea` de los originales están corridas**: acá se cita por nombre de
> función o de bloque. Re-localizá antes de editar.

## 1. Qué se decidió antes de escribir el plan (owner, 2026-09-14)

1. **Contrato de salida portable puro.** Nada de `output_config.format` de Anthropic. El JSON se
   sigue pidiendo en el texto del prompt y se parsea con `extract_json_object` para los cuatro
   proveedores. Sin bifurcación del embudo.
2. **Persona neutra + renombre total.** Se eliminó la persona «Eres Grok, construido por xAI» y
   también los campos persistidos y strings de UI que decían *Grok*, con migración de los planes
   guardados en disco.

## 2. Qué ya está hecho

| PR | Qué | Estado |
|---|---|---|
| PR 0 | El fallback deja de mentir sobre la causa (+ renombre H10 completo) | ✅ #121, `4462093` |
| PR 1 | `_call_claude` deja de rechazar los modelos actuales (el defecto era un parámetro, `temperature`, no un prompt) | ✅ #122, `129fcf1` |
| PR 1.5 | Se desactiva la bomba de calendario de `test_tracker_curve_oracle` | ✅ `c6181f4` |
| PR 2 | Persona neutra en los 9 prompts (H1) + contrato único de salida (H3): `ANALYST_ROLE` y `JSON_ONLY_CONTRACT` | ✅ `0b541c0` |
| ~~PR 3~~ | Renombre total y migración (H10) | 🔀 absorbido por PR 0 |
| PR 4 | Higiene de instrucciones: idioma, negaciones y few-shot (H5, H6) | ⏳ abierto |
| PR 5 | Estructura: delimitador único y orden datos→instrucción (H7, H8, H9) | ⏳ abierto |
| PR 6 | Markdown → campos estructurados (H4) | ⏳ abierto |
| PR 7 | El macro deja de salir de la memoria del modelo (H11) | ⏳ **parcial**: `equity_decision_prompt` ya está; faltan 4 prompts y dos ramas `else` del comité (ver §3.4) |

**Numeración canónica:** PR 4 = higiene (H5, H6); PR 5 = estructura (H7, H8, H9). La tabla y los
cuerpos del plan original se contradecían; ganó la numeración de los cuerpos.

**Estado en el código al 2026-10-25** (contado sobre `main`, por línea completa en
`prompts.py`; el comité arma sus delimitadores dentro de f-strings):

| Señal | `prompts.py` | `committee_prompts.py` |
|---|---|---|
| «IDIOMA OBLIGATORIO» | 9 | 1 |
| «usá tu conocimiento actual» | 4 (`equity_moat`, `crypto_moat`, `crypto_decision`, `portfolio_optimizer_advice`) | 0 (pero ver las ramas sin `else`, §3.4) |
| cabeceras `--- X ---` | 15 | sí (p. ej. el bloque de contexto de portfolio) |
| cabeceras `━━━` | 5 | 0 |
| líneas `**Texto**` completas | 29 | — |
| cabeceras `=== X ===` | 0 | sí (rol, datos duros, formato, titulares) |
| `<examples>` | 0 | 0 |

## 3. Lo que queda, con sus decisiones y criterios

Las decisiones Q1–Q5 de abajo son **recomendaciones técnicas fundamentadas, no aprobaciones
explícitas del owner**; salvo el punto de producto de §5, se tomaron por defecto justificado.

**Orden recomendado: PR 7 → PR 4 → PR 5 → PR 6.** PR 7 va primero porque es el único con
consecuencia financiera (un factor macro alucinado se persiste en `PlanSnapshot.macro_risks` y se
le muestra al usuario meses después) y es el diff más chico. PR 6 va último por su riesgo aguas
abajo.

### 3.1 PR 4 — Higiene de instrucciones (H5, H6)

**Qué:** una sola declaración de idioma por prompt, sin enumerar campos (se eliminan las listas
muertas de `key_strengths`/`key_risks` en los prompts que ya no los usan); un solo enunciado de
anclaje a datos con su motivo; reemplazar el few-shot único (un ejemplo, y negativo) por 2–3
balanceados.

**Q2 — decisión:** el few-shot vive en `_hard_decision_constraints_block` y tiene **un solo
caller**, `equity_decision_prompt`. El bloque **conserva un literal de texto plano** (`FEW-SHOT DE
RIGOR …`), **sin `<examples>`** (se rechaza el `<examples><example>` del «Qué» original, no por
comportamiento sino por coherencia con Q3). PR 4 cambia sólo el *contenido*; PR 5, dueño único de
los delimitadores, lo envuelve después. **No se extiende a crypto**: sus constraints duros son
estructuralmente distintos (volatilidad y drawdown, sin ROE ni D/E), ningún hallazgo lo pide y
`crypto_decision_prompt` ya tiene su ejemplo inline. Los constraints financieros duros se
conservan íntegros; el ejemplo de compra no afloja ninguna puerta. Un few-shot 100 % negativo
refuerza un sesgo asimétrico que `apply_safety_overlay` ya garantiza por construcción.

**Criterios de aceptación** (reemplazan a los cinco originales):
- **(4.1')** Para cada prompt renderizado, todo identificador `snake_case` enumerado en su
  declaración de idioma aparece **al menos una vez más** en el mismo prompt renderizado.
  Demuestra la corrección (hoy falla en los prompts con `key_strengths`/`key_risks` muertos).
  Opera sobre el texto renderizado, así que el renombrado en vuelo de
  `sector_country_tailwind_prompt` no da falso positivo.
- **(4.2')** «IDIOMA OBLIGATORIO» aparece exactamente una vez por prompt renderizado. **Candado,
  no arreglo**: ya está verde con 9 ocurrencias para 9 prompts, y el PR debe decirlo.
- **(4.3')** Ninguna instrucción se repite **dentro de un mismo prompt renderizado**. La unidad es
  el prompt renderizado, no el archivo ni el helper: «NO inventes colas de viento» vive en tres
  prompts independientes (`equity_decision`, `portfolio_optimizer_advice`,
  `plan_level_narrative`), y borrar dos no ahorra un token en ninguna llamada.
- **(4.4')** El bloque de ejemplos contiene ≥2 ejemplos y ≥1 con `action` de compra.
- **(4.5')** `make check` verde.
- **Dato reportado, no criterio:** delta de **caracteres** del prompt renderizado, antes y
  después, por prompt. No es tokens: la única cuenta correcta es
  `client.messages.count_tokens` y exige `ANTHROPIC_API_KEY`. El ahorro de ~400 tok/llamada del
  plan original queda como estimación no verificada.

### 3.2 PR 5 — Estructura (H7, H8, H9)

**Qué:** adoptar `=== SECCIÓN ===` en **`prompts.py` y `committee_prompts.py`** (conservando los
literales `CONSTRAINTS DUROS` y `PASOS DE RAZONAMIENTO` que los tests asertan). Reordenar: rol
corto → datos → instrucciones → contrato de salida, con el bloque de idioma bajado junto al
contrato. Techo de longitud explícito en todo campo de texto libre. **PR 5 es el dueño único de
todo carácter delimitador de la serie**: ningún otro PR introduce ni modifica delimitadores.

**Q3 — decisión: `=== SECCIÓN ===`, no XML.** No hay evidencia de que XML se comporte mejor ni de
que sea más portable: OpenAI trata encabezados Markdown y tags XML como complementarios; Google
exige consistencia dentro de un prompt, no una sintaxis; Anthropic recomienda XML (cita no
re-verificada); de xAI no se encontró documentación oficial de prompting. Las razones son
propias: `===` ya es el convenio dominante del comité (menor diff combinado), XML es la
recomendación nombrada de un solo proveedor y la restricción del owner es no sesgar hacia
ninguno, y PR 5 ya es el de mayor churn (~500 líneas).

**El alcance real incluye al comité.** `committee_prompts.py` mezcla `===` (secciones del rol) con
8 `---` dentro de `portfolio_committee_context_block` (subsecciones de datos): una jerarquía de
dos niveles deliberada, que PR 5 debe resolver. «Adoptar `===` en `prompts.py` usando el comité
como modelo sin tocarlo» lo dejaría con las dos convenciones conviviendo.

**Tres cosas que no hay que confundir:** (1) cabeceras de sección (lo que PR 5 unifica);
(2) bloques de ejemplos (uno solo, bajo la misma convención de texto plano); (3) Markdown exigido
dentro del payload de salida. Sobre (3): `plan_level_narrative_prompt` **no** da falsos positivos
(10 matches, las 10 son cabeceras legítimas; la línea del ejemplo empieza con
`"narrative": "**Resumen…`). `long_term_plan_narrative_prompt` **sí**: devuelve texto libre y su
plantilla de salida usa la misma forma `**Texto**` que sus cabeceras, y ninguna regex las
distingue; se excluye **por nombre**, con el precedente
`test_the_markdown_prompt_is_excluded_on_purpose` de `tests/test_prompt_neutrality_oracle.py`. No
hay dependencia PR 5 ← PR 6.

**Criterios de aceptación:**
- **(5.1')** Ningún prompt renderizado mezcla dos convenciones de delimitador. Cuenta sólo si la
  **línea completa** es el delimitador (tras `strip()`), lo que excluye la negrita inline:
  ```python
  SECTION_HEADER_RE = re.compile(
      r'^(?:---\s+\S.*\S\s+---|===\s+\S.*\S\s+===|━{3,}|\*\*[^*]+\*\*:?)$'
  )
  ```
- **(5.2')** El mismo test sobre los prompts renderizados de `committee_prompts.py`.
- **(5.4)** *(criterio original, sigue vigente; Q4 sólo reemplazó el primero y el tercero)* En cada
  prompt renderizado, el índice de la primera sección de datos es menor que el de la sección de
  instrucción final.
- **(5.3')** Todo campo de texto libre del contrato tiene techo de longitud declarado, contra una
  constante enumerada a mano en el test (`rationale`, `reasoning`, `narrative`, `explanation`,
  `why`, `cierre`, …). No existe un registro prompt→campos y construirlo no es parte de PR 5.
- `make check` verde.

### 3.3 PR 6 — Narrativa de plan: Markdown → campos estructurados (H4)

**Qué:** `plan_level_narrative_prompt` devuelve `{resumen, fortalezas[], riesgos[],
p10_lectura, duracion_ingreso, recomendaciones[], cierre, macro_risks[]}`.
`generate_plan_narrative` compone el Markdown desde esos campos y **sigue devolviendo
`{"narrative": str, "macro_risks": list}`**, sin cambio de forma para la UI ni para
`PlanSnapshot`. Mismo tratamiento opcional para `long_term_plan_narrative_prompt`; si se
convierte a JSON hay que **actualizar** `test_the_markdown_prompt_is_excluded_on_purpose`, que hoy
falla si alguien lo hace (es el anti-trampa de PR 2 funcionando).

**Riesgo aguas abajo: el más alto de los cuatro.** La narrativa se renderiza en la página del
Plan (viva y persistida, `snap.narrative`) y entra al export PDF (`include_ai_narrative`).
`PlanSnapshot.narrative: str` y su población desde `opt_result.ai_narrative` no deben cambiar de
forma: es la garantía a preservar y el motivo por el que va último.

**Criterios de aceptación:**
- Dada una respuesta estructurada, `generate_plan_narrative` produce un `narrative` con las 7
  secciones en orden.
- Una respuesta **vieja** se sigue aceptando, y el fallback son **dos** ramas que hay que
  probar: JSON que no parsea (`data = {}`) y JSON que parsea pero sin `narrative` (se toma el
  texto crudo). Los tests que ejercitan esas ramas son `test_parses_narrative_and_caps_macro_at_two`
  y `test_non_json_response_becomes_narrative` de `tests/test_prompts.py`.
- **(6.5)** El Markdown compuesto es comparable en estructura con el que hoy produce el modelo
  (mismos siete encabezados, mismo orden), para que un `PlanSnapshot` guardado antes y uno
  guardado después se rendericen igual. El riesgo real no es el parseo sino la recomposición.
- La página del Plan renderiza sin cambios. `make check` verde.

### 3.4 PR 7 — El macro deja de salir de la memoria del modelo (H11)

**Estado real hoy:** avanzado, pero no cerrado.
- Ya cumplen: `equity_decision_prompt` recibe `macro_context` y, sin hechos fechados, declara que
  no los hay y devuelve `macro_factors: []` (`_equity_macro_block`, EVAL-GROQ-1).
- **Siguen pidiendo memoria 4 prompts** de `prompts.py`: `equity_moat_prompt`, `crypto_moat_prompt`,
  `crypto_decision_prompt` y `portfolio_optimizer_advice_prompt` («usá tu conocimiento actual»).
- **Dos ramas del comité siguen sin `else`** (los «2 sitios del comité» de Q1): en
  `macro_strategist_prompt`, `if macro_context:` agrega los hechos fechados pero sin ellos no dice
  nada; y el bloque de contexto de portfolio (`ctx.get("macro_context")`) tampoco declara la
  ausencia. Lo mitiga —no lo cumple— la abstención del Macro cuando no hay documentos frescos que
  no sean seed (MACRO-SEED, `analysis/committee.py`): el rol no se convoca, pero el texto del prompt
  no declara la ausencia.
- `plan_level_narrative_prompt` ancla `macro_risks` «a los datos de arriba» y permite `[]`, pero no
  dice que deban ser estructurales ni verificables (7.4).

**Independiente de PR 4/5/6**: PR 7 toca cabeceras de macro y una rama `if/else`, no el contrato,
los delimitadores ni el orden. Por eso conviene hacerlo **antes de PR 5**: cinco de las quince
cabeceras `---` que PR 5 reescribe son las suyas, y hacerlo antes ahorra re-localizar.

**Q1 — decisión: la opción barata, ampliada a 8 sitios** (los 5 de `prompts.py`, los 2 del comité y
`plan_level_narrative_prompt`). Cuando no hay contexto macro fechado, el prompt
declara explícitamente que no hay datos macro actuales y restringe `macro_factors` a factores
**estructurales** verificables contra los números del prompt. Texto + tests estáticos, cero firmas
de producción tocadas, el riesgo más bajo de la serie. La ampliación a `plan_level_narrative_prompt`
importa porque es el único cuyo `macro_risks` se persiste de verdad.

**Criterios de aceptación** (reemplazan a los tres originales):
- **(7.1)** Ninguno de los prompts de `prompts.py` contiene «conocimiento actual» en su string
  renderizado. Para los 4 que no reciben `macro_context` es un invariante incondicional; el
  fixture `all_prompts()` de `tests/test_prompt_neutrality_oracle.py` ya los renderiza. Demuestra
  la corrección: hoy falla en esos 4.
- **(7.2)** Llamados **sin** `macro_context`, el prompt contiene la declaración de que no hay
  datos macro actuales y la restricción a factores estructurales. Ya se cumple en
  `equity_decision_prompt`; **falta** en `macro_strategist_prompt` y en los prompts de portfolio
  con un `ctx` sin la clave. (Para los 4 que no reciben `macro_context`, 7.2 se reduce a 7.1 más la
  declaración fija de ausencia.)
  Queda por cumplir también en `macro_strategist_prompt` (rama `else`) y en el bloque de portfolio.
- **(7.3)** Llamados **con** `macro_context` no vacío, la prohibición de usar memoria de
  entrenamiento sigue presente (regresión, ya verde en `tests/test_macro_rag.py`; es el
  anti-trampa de 7.2).
- **(7.4)** `plan_level_narrative_prompt` declara que los ítems de `macro_risks` deben ser
  estructurales y verificables contra los números del prompt.
- **(7.5)** `make check` verde. Cambiar un prompt del comité exige subir `COMMITTEE.prompt_version`
  (ver `BACKLOG`/EVAL-GROQ-1: el prompt de decisión también es el del Analista Fundamental).

**Opción completa (B1, no se hace hoy):** enhebrar `macro_context` real desde `macro_rag` hasta los
prompts de análisis individual que aún no lo reciben (`equity_moat`, `crypto_moat`,
`crypto_decision`, `portfolio_optimizer_advice`; `equity_decision` ya lo tiene; **no**
`sector_country_tailwind_prompt`, que no tiene sección macro). **Actualización 2026-10-25:** el
disparador (a) **ya se cumple**: `scripts/run_scheduler.py` define `job_ingest_macro`, que llama
`ingest_from_fred`, agendado a diario y también al arrancar (#135, `85fc76c`, 2026-09-18, posterior
a los documentos originales). Con la salvedad de que **sin `FRED_API_KEY` ingiere 0 documentos**.
El (b) ya no sirve: desde MACRO-SEED los documentos `seed:` se excluyen por defecto. Lo que queda
por decidir es si B1 se justifica ahora. Cambia firmas en `analysis/moat.py`, `analysis/crypto_analyzer.py` y
`analysis/ai_analyzer.py`; `_run_moat_pipeline` ya tiene sector e industria poblados. **Disparadores
originales:** (a) un job programado que llame `ingest_from_fred()` periódicamente; (b) un paso de
arranque que cargue `example_macro_docs()` si el store está vacío; (c) evidencia de que un usuario
mantiene alimentada la página de Macro RAG. Sin uno de los tres no hay observable que la distinga
de la barata. Criterios si se retoma: con store poblado y fresco esos prompts traen el
bloque de hechos fechados y no «conocimiento actual»; con store vacío declaran la ausencia (al menos
tan bien como la barata); ningún caller degrada sucio si el store lanza (patrón `try/except → ""`
de `analysis/committee.py`).

### 3.5 Q4 — Cómo se leen los criterios de aceptación

Aceptar tres reformulaciones, **corregir dos** (campos y deduplicación) y **rechazar una** (medir
en tokens como criterio). Los criterios son invariantes estáticos: prueban que el prompt cambió,
no que el modelo responde mejor. Eliminar enumeraciones de campos **recorta** la cobertura buscada,
y «ahorro» en caracteres, tokens y mejora del modelo son tres cosas distintas.

### 3.6 Q5 — Excepción del criterio (c) del PR 0

El criterio (c) de PR 0 (`grep -rin grok --include='*.py' .` sin ocurrencias fuera de una
allowlist) se corre **a mano** al cerrar un PR; ningún test lo implementa. La allowlist
vigente nombra **cuatro** ubicaciones: `AI_PROVIDER_DISPLAY` en `config.py`, el catálogo de modelos de
xAI y su etiqueta de proveedor en la página de Settings, la lista de proveedores de la página About,
y cualquier archivo bajo `tests/` que ejercite el proveedor `xai` (escrita por **rol**, no por
enumeración). La decisión (opción A) fue agregar una **quinta** excepción: cualquier archivo bajo `tests/` cuya única mención de las
marcas de proveedor esté dentro de una aserción que verifica su **ausencia** (p. ej.
`VENDOR_MARKS` en `assert mark not in …`, como en `tests/test_prompt_neutrality_oracle.py`). Se
descartó ofuscar la constante (`"Gr" + "ok"`) porque deja ilegible el grep que debería
protegerla. La excepción está acotada a `tests/` y por rol semántico del assert; una aserción de
presencia (`assert texto == "Grok dice: …"`) sigue marcándose. La granularidad es por archivo, no
por línea: riesgo ya aceptado por el owner.

## 4. Backlog derivado

| # | Entrada | Estado 2026-10-25 |
|---|---|---|
| B1 | Enhebrar `macro_context` real hasta los 4 prompts restantes (§3.4) | El disparador (a) ya se cumple (job de ingesta en el scheduler); falta decidir si se justifica, y con `FRED_API_KEY` |
| B2 | El gate de frescura de `analysis/macro_rag.py` acepta un documento **sin** `as_of` como fresco (`age is None or age <= max_age`) | **Sigue abierto** (verificado hoy). Defecto acotado e independiente; bloquea B1 |
| B3 | Ingesto automático de `MacroRagStore` | **Resuelto** (job diario de FRED en `scripts/run_scheduler.py`, #135); sin `FRED_API_KEY` ingiere 0 |
| B4 | `build_portfolio_committee_context` (`analysis/committee.py`) sin caller de producción, sólo tests | **Sigue así** (verificado hoy): decidir si se activa o se borra |
| B5 | `ruff` fuera de `requirements.txt` | **Resuelto**: `requirements-dev.txt` lo fija (`make setup`) |
| B6 | `docs/INDEX.md` decía «8 PRs» con PR 3 absorbido | **Cerrado** al fusionar estos tres documentos |
| B7 | Nombrar explícitamente en la allowlist de (c) la rama de `9_Settings.py` (el catálogo de modelos de xAI) | Abierto, cosmético; junto con la quinta excepción |

## 5. Punto de producto sin resolver

Una sola preferencia no se deriva del código: **si el sistema debe aspirar a dar contexto macro
fechado o si es aceptable que declare permanentemente que no tiene datos macro actuales.** Valor
por defecto propuesto: que opere declarando la ausencia hasta que exista ingesto automático. No
cambia el comportamiento real (sin seeder, el store ya está vacío por defecto): lo hace explícito,
al modelo y al usuario. La decisión de MACRO-SEED (2026-09-27, el Macro del comité se abstiene)
va en la misma dirección.
