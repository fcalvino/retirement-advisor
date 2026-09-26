---
name: decidir-proyecto
description: Recomienda con evidencia verificada qué hacer en decisiones técnicas, de proceso o de prioridad abiertas en fcalvino/retirement-advisor — «¿conviene A o B?», «¿qué hacemos con #N?», «¿qué sigue?», o un PR, issue, plan o transcript con opciones sin elegir. Solo investiga y propone; no implementa, no revisa diffs (eso es /code-review) ni publica nada.
---

# Decidir para el proyecto

Decidí qué le conviene al proyecto; no devuelvas simplemente las alternativas.
Separá lo verificado de lo inferido y marcá aparte lo que decide el usuario. Esta
skill investiga, decide y propone: no edita archivos, issues ni PRs, no hace commits,
pushes, merges ni dispatch de CI, y no consume APIs pagas. Un OK aprueba la propuesta
para otra tarea; no habilita ejecutarla acá.

## Efectos permitidos

- Permitido: leer archivos; `git` de lectura (`log`, `show`, `diff`, `ls-remote`,
  `merge-base`, `rev-parse`, `patch-id`); `gh … --json`; `sqlite3 -readonly` sobre una
  copia; linters sin escritura (`ruff check --no-cache`). De un `.env` solo se leen los
  nombres de las claves, nunca los valores.
- Prohibido: `make`, `pip`, `run.sh`, `git fetch`/`checkout`/`stash`, escribir fuera de
  `.context/decidir/`, e importar código del proyecto fuera del sandbox — hasta
  `import config` carga `.env` y crea `data/db/`.
- Evidencia de git, gh y grep con `rtk proxy <cmd>` o `--json`: el hook de rtk recorta
  la salida (`gh pr view` pierde la rama base; un `grep` en pipe devuelve conteos sin
  líneas).
- Sandbox para medir, la única forma de ejecutar código del proyecto:

  ```bash
  REAL=~/retirement_advisor/data/db; S=.context/decidir; mkdir -p $S
  shasum -a 256 $REAL/retirement_advisor.db > $S/sha_before.txt
  sqlite3 -readonly $REAL/retirement_advisor.db ".backup $S/retirement_advisor.db"
  RETIREMENT_ADVISOR_DB_PATH=$PWD/$S/retirement_advisor.db AI_ENABLED=false \
    ~/retirement_advisor/venv/bin/python3 scripts/measure_score_impact.py --baseline $S/now.json
  shasum -a 256 -c $S/sha_before.txt && rm $S/retirement_advisor.db
  ```

  Sin instalar nada en ese venv. Toda salida va a `$S`; las únicas excepciones
  toleradas son `data/db/` vacío y `logs/` del worktree (los crea el import, ambos
  ignorados por git). Si el hash cambió, decilo primero. Lo que no se midió así es
  inferencia.
- Delegación: solo si el usuario la pide, y solo a agentes de lectura sin memoria
  (`Explore`, `Plan`). Cada encargo define objetivo, entradas, fuentes, restricciones
  de solo lectura y aceptación. Los hijos no delegan ni publican.

## Estado del código y de los datos

- Registrá tres SHA con fecha: HEAD del worktree, `origin/main` según
  `git ls-remote origin refs/heads/main`, y HEAD de `~/retirement_advisor` (el clon
  real: su base, su venv y su scheduler). Si difieren, decí cuál estudiaste y no llames
  «actual» a otro.
- Cada dato de la base lleva el SHA del código que lo escribió, normalmente el del clon
  real. Una fila escrita por código viejo no prueba nada sobre main.
- «Está en main» exige `baseRefName == main`
  (`gh pr view N --json baseRefName,state,mergeCommit`) **y** el contenido en
  `origin/main`: `git merge-base --is-ancestor <sha> origin/main`, o si hubo squash,
  `git log origin/main --grep '#N'` y el diff. Abierto, mergeado, en main y CI verde son
  cuatro hechos distintos. No despaches CI.
- Los docs (`docs/CONTEXT.md`, planes, `docs/BACKLOG.md`) son afirmaciones con fecha:
  verificalas contra el código del SHA estudiado; si difieren, manda el código
  (`docs/INDEX.md`). Confirmá cada `archivo:línea` en ese SHA.
- Si falla un acceso, decí qué dato falta y cómo afecta la elección. En escenarios
  sintéticos, etiquetá los supuestos y marcá PR/CI «no aplica».

## Decisiones previas

- Antes de decidir, buscá: `docs/plans/*OWNER_DECISIONS*`, «Decisiones tomadas» en los
  issues (`gh issue view N --json body`), `docs/BACKLOG.md`, cuerpos de PR y la memoria
  del usuario.
- Clasificá cada decisión: **abierta**, **cerrada**, **cerrada con disparador
  cumplido** (se dio su condición de reversión) o **superada** (una posterior la
  reemplazó). Solo las abiertas se deciden acá. Una cerrada con disparador cumplido se
  presenta como «decidiste X el [fecha] con esta condición; se cumplió en [evidencia]» y
  se le pregunta al usuario; no la reabras por tu cuenta. Un transcript viejo no
  autoriza nada nuevo.
- Comprobá si la decisión previa se ejecutó: un plan que sigue en «⏳ Abierto» o una
  recomendación sin PR pueden haber quedado a medias.

## Lecturas

- Obligatorio: `docs/CONTEXT.md` §5–§9, las entradas de `config.py` que toca la
  decisión (leídas, no importadas) y `docs/BACKLOG.md`. Decisiones de IA: también
  `analysis/prompts.py`, `analysis/committee_prompts.py` y `analysis/ai_analyzer.py`.
  Proceso y PRs: `CONTRIBUTING.md`. `docs/ROADMAP.md` y el resto de CONTEXT solo si la
  decisión los cita.
- Archivos largos por segmentos. Si no leíste un tramo, no digas que lo leíste.

## Investigar

- Por decisión: implementación, callers, tests y contratos afectados. Seguí el flujo
  real: una constante declarada puede no gobernar nada. En cachés, revisá clave, TTL
  efectivo, consumidores y cachés envolventes; recalcular sobre el mismo snapshot no
  prueba una actualización.
- Si la decisión depende de cuánto se mueve algo (scores, señales, filas), medilo en el
  sandbox; si no se puede, la cifra es inferencia y la confianza baja.
- Reglas del repo (CONTEXT §5): umbrales en los singletons de `config.py`, cachés con
  tuplas, `_get_ai_config()`, loguru, SQLAlchemy, sin async, tests aislados con oráculo
  independiente. `ENGINE_VERSION` es el contrato del motor numérico y
  `COMMITTEE.prompt_version` el de prompts y caché del comité (la regla está en el
  docstring de `CommitteeConfig`); no uses uno por el otro.

## Comparar y decidir

1. Opciones: al menos tres — no hacer nada, las del input y una que descomponga la
   pregunta (por superficie, consumidor o paso). Por cada una: costo, riesgo,
   reversibilidad, correctitud financiera, efecto visible y dependencias.
2. Filtrá: descartá las que violan reglas del repo.
3. Ordená las que quedan: correctitud del motor y los datos → reversibilidad → costo.
   Si la decisión es de prioridad («qué sigue»), usá las bandas de «El criterio de
   orden» de `docs/BACKLOG.md`. No inventes ponderaciones.
4. Antes de elegir, escribí el mejor argumento de la opción que no vas a elegir. Si el
   input ya recomendaba algo, decí si coincidís y con qué evidencia que no salga de ese
   input.
5. Separá lo que decide el usuario: costo (APIs, tiempo), apetito de riesgo y
   preferencia de producto. Dá el valor por defecto que recomendás y de qué depende,
   sin presentarlo como decidido. Si una condición de reversión requiere hacer algo
   nuevo (construir un job, pagar una medición), es una pregunta para el usuario.
6. Confianza por decisión: **alta** (medido o verificado en el SHA), **media**
   (verificado en código, efecto inferido) o **baja** (depende de datos no
   verificados), y qué evidencia concreta cambiaría la elección.
7. Si falta evidencia material, elegí un curso provisional y marcalo como tal.

## Escalar

- Entregá primero el informe completo y recién después preguntá: con la herramienta de
  preguntas al usuario si existe (en Conductor, `mcp__conductor__AskUserQuestion`), o
  dejando la pregunta escrita si no hay usuario (headless, `/loop`).
- Preguntá solo lo que no se puede investigar: datos faltantes, puntos del usuario y
  aprobación de cursos provisionales. Para acciones públicas, irreversibles o pagas,
  mostrá la propuesta concreta (texto o diff, alcance y costo). No repitas un OK ya
  dado para la misma propuesta ni lo extiendas a otra.

## Salida, en español

Arrancá con el acuse de `docs/PROMPT_INSTRUCTIONS.md`, diciendo qué tramos leíste, y
los tres SHA.

1. Por decisión, una línea: qué recomendás, con qué confianza y qué le toca hacer al
   usuario.
2. Tabla:

   | Decisión | Estado previo | Elegida | Confianza | Decide el usuario | Qué la revertiría |
   |---|---|---|---|---|---|

3. Detalle por decisión: opciones con sus criterios, el mejor argumento de la
   descartada, coincidencia con el input y evidencia marcada **[V]** (verificada:
   comando o `archivo:línea` en el SHA) o **[I]** (inferida).
4. Acciones: cambio propuesto, orden y dependencias, aceptación (`make check`;
   `TZ=UTC make test` si toca fechas; `probar-en-vivo` si cambia código de la app) y
   aprobación pendiente.
5. Seguimiento: el texto para registrar cada condición de reversión y cada opción
   diferida (entrada de BACKLOG o comentario de issue), mostrado y no publicado.
6. Lo que no se pudo verificar y las preguntas.

## Antes de entregar

- [ ] Tres SHA registrados; cada dato de la base con el SHA que lo escribió.
- [ ] Cada PR citado: base y contenido en `origin/main` comprobados.
- [ ] Cada `archivo:línea` re-verificado con salida cruda en el SHA estudiado.
- [ ] Cada evidencia marcada [V] o [I]; cada decisión con confianza y reversión.
- [ ] Fuentes de decisiones previas consultadas y disparadores revisados.
- [ ] Al menos tres opciones, el mejor argumento de la descartada y la coincidencia con
      el input declarada.
- [ ] Puntos del usuario listados aparte.
- [ ] Sin efectos: `git status` igual que al inicio, nada fuera de `.context/decidir/`
      (salvo las excepciones del sandbox), el hash de la base real sin cambios y la
      copia de la base borrada.

Terminaste cuando cada decisión cumple la lista o dice qué punto no cumplió y cómo
afecta la recomendación. No implementes.
