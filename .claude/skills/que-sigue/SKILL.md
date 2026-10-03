---
name: que-sigue
description: Arranque de sesión — foto del repo con scripts/estado.py, qué sigue con decidir-proyecto, y el prompt listo para el paso elegido.
disable-model-invocation: true
argument-hint: "[tema opcional]"
---

# Qué sigue

El estado del repo y el orden del backlog ya están escritos: se leen, no se
reconstruyen desde los diffs de los docs.

1. Corré `~/retirement_advisor/venv/bin/python3 scripts/estado.py`. Es la foto de
   partida: los tres SHA, los PR abiertos, los worktrees, `## Orden actual` y la
   fila `(pending)` de CONTEXT §9. Copiá cada línea `⚠` a la respuesta tal cual.
   Listo cuando tenés la salida completa.
2. Invocá la skill `decidir-proyecto` con esta pregunta: «$ARGUMENTS». Si quedó
   vacía, la pregunta es «¿qué sigue?». Su estado de partida es la salida del paso 1,
   así que los SHA ya están registrados. Listo cuando hay una recomendación con lo
   verificado separado de lo inferido y lo que decide el usuario marcado aparte.
3. Cerrá con el prompt para ejecutar el paso recomendado, escrito con la skill
   `claude-prompt-architect`, en un bloque aparte que el usuario pueda copiar. Lo
   ejecuta una tarea nueva, después de su OK.
