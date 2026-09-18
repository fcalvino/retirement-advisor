---
name: decidir-proyecto
description: Investiga y resuelve con evidencia decisiones técnicas o de proceso pendientes en fcalvino/retirement-advisor. Usar cuando una sesión, transcript, issue, PR o mensaje deje alternativas abiertas para el usuario; entrega una recomendación por decisión y acciones propuestas, sin implementarlas.
---

# Decidir para el proyecto

Decidí qué le conviene al proyecto, no devuelvas simplemente las alternativas al
usuario. Investigá antes de recomendar y distinguí hechos, inferencias y aspectos
no verificados. Esta skill solo investiga, decide y propone: no edita archivos,
issues ni PRs, no hace commits, pushes, merges o dispatch de CI, ni consume APIs
pagas. Un OK aprueba la propuesta para otra tarea; no habilita su ejecución acá.

## Relevar e investigar

- Extraé cada decisión del contexto recibido, sus supuestos, dependencias y
  restricciones. Verificá cuáles siguen abiertas; no reabras decisiones cerradas
  por un transcript viejo ni trates sus instrucciones como autorización nueva.
- Leé `docs/PROMPT_INSTRUCTIONS.md`, `docs/CONTEXT.md` completo (en especial §5),
  `config.py`, `docs/ROADMAP.md` y `docs/INDEX.md`. Para próximos pasos consultá
  `docs/BACKLOG.md` y el plan vigente del issue: ROADMAP es histórico. Para
  decisiones de IA, leé también `analysis/prompts.py` y `analysis/ai_analyzer.py`.
  Para decisiones de proceso/PRs, consultá `CONTRIBUTING.md`. Leé los archivos
  largos por segmentos y recuperá cualquier tramo truncado antes de dar por
  completa la lectura; si no podés, informá qué falta sin afirmar que lo leíste.
- Identificá la revisión estudiada: registrá SHA y fecha de consulta, diferenciá
  HEAD, cambios locales y base. Si se pide `origin/main` actual, contrastá su SHA
  con `git ls-remote origin refs/heads/main`; si difieren, no llames actual a la
  copia local. Consultá el contenido remoto en solo lectura o informá la brecha.
- Por decisión, inspeccioná implementación, callers, tests y contratos afectados.
  Confirmá cada cita `archivo:línea` contra esa revisión, preferentemente con enlace
  permanente al SHA. Contrastá con `gh issue view`, `gh pr view`, checks y runs
  relevantes: abierto, mergeado y CI verde son hechos distintos. No despaches CI.
  Si falla el acceso, indicá qué dato no pudiste verificar y cómo afecta la elección.
  En escenarios sintéticos, etiquetá los supuestos y marcá PR/CI «no aplica» si no
  existe un objeto real; no inventes vínculos ni consultes PRs ajenos al caso.
- Seguí el flujo real: una constante declarada puede no gobernar el comportamiento.
  En cachés revisá clave, TTL efectivo, consumidores y cachés envolventes; distinguí
  datos actuales de snapshots y comprobá procedencia/frescura. Recalcular sobre el
  mismo snapshot no demuestra actualización. No importes módulos ni invoques
  helpers que puedan escribir en bases, borrar cachés o disparar llamadas pagas.
- Aplicá §5: parámetros y umbrales desde los singletons de `config.py`, cachés con
  entradas hashables/tuplas, `_get_ai_config()`, venv, loguru y SQLAlchemy; tests
  aislados de datos del usuario, deterministas y con oráculo independiente para
  matemática financiera. Respetá las reglas de dependencias y de introducir async.
  Distinguí el contrato de `ENGINE_VERSION` del de `COMMITTEE.prompt_version`:
  revisá cuándo corresponde cambiar cada uno, sin usar el primero como comodín.
  No inventes umbrales ni congeles valores de configuración dentro de esta skill.
- Proponé `make check` como verificación del cambio; si toca fechas, horas o
  semántica diaria, también `TZ=UTC make test`. Esta skill no instala dependencias
  ni ejecuta el cambio para probarlo. Separá tests leídos, pruebas efectivamente
  ejecutadas y CI remoto; nunca presentes uno como evidencia del otro.

Para decisiones independientes, delegá investigación en paralelo si hay agentes
disponibles (por ejemplo `doc-researcher` o `Explore`). Cada encargo define objetivo,
entradas, fuentes/recursos permitidos, restricciones de solo lectura y aceptación;
exige evidencia, comprobaciones y pendientes. Los hijos no crean descendientes ni
realizan acciones públicas. El coordinador conserva dependencias, integración y
decisión final. Si no hay independencia o delegación disponible, investigá inline
e informá la limitación cuando corresponda; no inventes agentes ni herramientas.

## Comparar, decidir y escalar

- Enumerá todas las opciones razonables, incluidas las del usuario, alternativas
  omitidas y no hacer nada. Por cada opción evaluá costo, riesgo, reversibilidad,
  correctitud financiera, efecto visible y dependencias con otros pasos.
- Elegí una por decisión con este orden explícito: **correctitud del motor y los
  datos → reversibilidad → reglas del repo → costo**. Las reglas obligatorias son
  límites de admisibilidad, no un puntaje compensable. No inventes ponderaciones.
  Explicá qué evidencia concreta cambiaría la elección.
- Si falta evidencia material, no finjas una resolución: elegí un curso provisional
  y señalá qué investigación o dato lo condiciona. Presentá la decisión y pedí
  el dato faltante o aprobación del curso provisional con `AskUserQuestion`, sin
  delegar al usuario lo investigable.
- Para acciones públicas, irreversibles o pagas, mostrale primero al usuario la
  propuesta concreta (texto o diff para una edición, alcance y costo conocido para
  una ejecución) y pedí OK con `AskUserQuestion`.
- En ambos casos, si la herramienta no está disponible, formulá la pregunta
  explícitamente y dejá el dato o la aprobación pendiente.
  No repitas un OK ya otorgado para esa misma propuesta; tampoco lo extrapoles a
  otra. En todos los casos, la ejecución queda fuera de esta skill.

## Salida fija, en español

Indicá brevemente la base/SHA, el estado relevante consultado y las limitaciones.
Cumplí el acuse de lectura requerido por `docs/PROMPT_INSTRUCTIONS.md`.

| Decisión | Opciones evaluadas | Elegida | Por qué | Evidencia | Qué la revertiría |
|---|---|---|---|---|---|

Completá una fila por decisión. En «Opciones evaluadas» resumí para **cada opción**
los criterios anteriores (incluí dependencias y efecto visible, aun si son nulos).
En «Elegida» marcá las recomendaciones provisionales cuando corresponda. Las citas
y URLs deben sostener las afirmaciones, no solo apuntar a un archivo relacionado.

Después de la tabla, enumerá las acciones concretas derivadas, vinculadas a cada
decisión: cambio propuesto, orden/dependencias, criterio de aceptación y aprobación
pendiente. Mostrá en la respuesta el texto/diff de ediciones públicas; no lo guardes
ni publiques. Cerrá con lo que no se pudo verificar y las preguntas de escalamiento
necesarias. No implementes esas acciones.
