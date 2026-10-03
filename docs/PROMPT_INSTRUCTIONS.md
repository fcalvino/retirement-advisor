# INSTRUCCIONES OBLIGATORIAS PARA CUALQUIER AI CODING ASSISTANT

> Aplica a: **Claude Code** u otro AI coding assistant.

---

## REGLA PRINCIPAL

**Antes de generar CUALQUIER plan, fix, feature o código en este proyecto, cargá el
contexto que toca la tarea.** `docs/CONTEXT.md` y `config.py` son demasiado largos
para leerlos enteros: se leen por sección.

| Para saber… | Leé |
|---|---|
| Qué sigue, qué está abierto y en qué SHA estás | `make estado`: Orden actual, PR abiertos, worktrees, los tres SHA y la fila `(pending)`, en una llamada |
| Dónde vive algo | `docs/CONTEXT.md` §4, mapa de archivos |
| Cómo se escribe código acá | `docs/CONTEXT.md` §5, estándares — siempre que vayas a escribir código |
| Qué umbral o parámetro existe | `docs/CONTEXT.md` §7 y la dataclass de `config.py` que toca el cambio |
| Si algo ya falló antes | `docs/CONTEXT.md` §8, buscando por término |
| Qué cambió y por qué | `docs/CONTEXT.md` §9 (una fila por PR) y `docs/ROADMAP.md` |
| Prompts o lógica de IA | `analysis/prompts.py` y `analysis/ai_analyzer.py` |

Las secciones se ubican con `grep -n '^## ' docs/CONTEXT.md`.

**Al inicio de tu respuesta, nombrá las secciones que leíste.**

---

## Por qué esto es importante

- `config.py` tiene singletons globales (`THRESHOLDS`, `MONTE_CARLO`, `OPTIMIZER_PROFILES`, etc.) — nunca hardcodees números en el código de análisis
- Los estándares de código del proyecto (cache con tuplas, `_get_ai_config()`, loguru, NullPool) están documentados en `docs/CONTEXT.md §5`
- El estado actual de features (qué está ✅ completo y qué está ⏳ pendiente) está en `docs/CONTEXT.md §6`
- Las limitaciones conocidas (EMFILE, KaTeX, hot-reload, etc.) están en `docs/CONTEXT.md §8`
- El catálogo de documentación (guía viva vs auditoría histórica vs ideación) está en `docs/INDEX.md`

---

## Checklist antes de proponer código

- [ ] ¿Leí las secciones de `docs/CONTEXT.md` que toca el cambio (§5 si escribo código)?
- [ ] ¿El cambio requiere editar thresholds? → hacerlo en `config.py`, no inline
- [ ] ¿Agrego una función de dashboard? → usar `@st.cache_data` y pasar params como tuplas
- [ ] ¿Toco lógica AI? → revisar `analysis/prompts.py` y `analysis/ai_analyzer.py`
- [ ] ¿Pasan **lint y tests**? → `make check` (es exactamente lo que corre el CI).
      `pytest` solo no alcanza: el job corre `ruff check .` **antes** que los
      tests, así que un error de formato aborta el build sin ejecutar un solo
      test — y en verde local eso no se ve
- [ ] ¿El cambio toca fechas, horas o "por día"? → correr también
      **`TZ=UTC make test`**. El CI corre en UTC y tu máquina probablemente no:
      un test que hereda la zona del entorno pasa acá y falla allá, y el verde
      local deja de ser evidencia. Es el mismo defecto que el repo ya prohíbe
      con `hash()` (CONTEXT §5), pero más silencioso, porque el reloj parece
      parte del problema y no del setup. Costó una vuelta de CI en U5-18
- [ ] **Obligatorio después de cualquier desarrollo:** ¿probé el cambio en la
      **app en vivo**? → skill `probar-en-vivo` (`.claude/skills/probar-en-vivo/`):
      Streamlit sobre una copia de la base, Playwright, capturas, y el hash de la
      base real igual antes y después. `make check` y AppTest no la reemplazan:
      EMPTY-FEED-SA y el caption de LLM-2 aparecieron recién en la QA en vivo. Si
      no se pudo (sin red, sin key), el PR lo dice con nombre
- [ ] ¿Abro un PR? → la fila de CONTEXT §9, la entrada de ROADMAP y la fila del
      BACKLOG las escribe `scripts/close_row.py` (`--help`; `--no-row` si el PR no
      cierra una fila). Vos escribís la prosa; el script la pone en su lugar
- [ ] ¿Agregué o borré un `.md`? → actualizar la tabla canónica de `docs/INDEX.md`

---

## Para mantener CONTEXT.md actualizado

Ver `docs/MAINTENANCE.md` y ejecutar:
```bash
./venv/bin/python3 scripts/refresh_context.py
```
