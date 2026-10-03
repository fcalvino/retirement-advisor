# Guía de Mantenimiento — Retirement Advisor

> Documento dirigido al maintainer del proyecto (humano o AI). Explica cómo mantener la documentación y el contexto actualizados.

---

## 1. El archivo más importante: `docs/CONTEXT.md`

`docs/CONTEXT.md` es el **contexto canónico del proyecto**. Cualquier AI coding assistant (Claude Code u otro) lee las secciones que toca su tarea antes de planear o codificar (la tabla de `docs/PROMPT_INSTRUCTIONS.md`). Si este archivo está desactualizado, el AI trabajará con información incorrecta.

### Cuándo actualizar CONTEXT.md

| Evento | Sección(es) a actualizar |
|--------|--------------------------|
| Se completa una feature o Fase del roadmap | §6 Estado de Features, §9 Últimos Cambios |
| Se agrega/modifica una dataclass en `config.py` | §7 config.py — Fuente de Verdad |
| Se agrega/elimina un módulo crítico | §4 Mapa de Archivos, §3 Arquitectura |
| Cambia un estándar de código | §5 Estándares de Código |
| Se descubre una nueva limitación | §8 Limitaciones Conocidas |

### Cómo actualizar CONTEXT.md

1. Ejecutar el script de refresh para obtener bloques pre-generados:
   ```bash
   ./venv/bin/python3 scripts/refresh_context.py
   ```
2. Revisar el output (git log reciente + dataclasses de config.py)
3. Pegar lo relevante en las secciones correspondientes de `docs/CONTEXT.md`
4. Actualizar la fecha en el encabezado del archivo

### La columna Commit de §9

Un PR no conoce su SHA de merge, así que escribe su fila de §9 como `` `(pending)` ``.
**El PR siguiente la resuelve** con el SHA del merge que la llevó a `main` antes de
agregar la suya; `scripts/close_row.py` lo busca solo. Puede haber **una sola**
fila `(pending)`, y tiene que ser la primera (la más nueva):
`tests/test_context_changelog_pending.py` lo hace cumplir en `make check` y en el CI.
El 2026-09-28 había 20; las de 2026-06/07 cayeron en commits de importación en bloque
(`5fb471c`, `5eed792`), y ése es su SHA real.

### Cerrar una fila o registrar un PR

Todo PR toca CONTEXT §9 y la cabecera de CONTEXT; el que cierra una fila del BACKLOG
toca además ROADMAP y el BACKLOG. Esas ediciones las hace `scripts/close_row.py`:
la prosa (la celda de §9 y el cuerpo de la entrada de ROADMAP) va en dos archivos que
escribís vos, y el script la pone en su lugar.

```bash
./venv/bin/python3 scripts/close_row.py ID --title "frase" \
    --context-row .context/fila.md --roadmap-body .context/entrada.md        # muestra el diff
./venv/bin/python3 scripts/close_row.py … --write                            # lo aplica
./venv/bin/python3 scripts/close_row.py ID --title "frase" \
    --context-row .context/fila.md --no-row --write                          # PR sin fila
```

Después de `--write` lista las líneas del BACKLOG que todavía nombran el id: el
detalle del Bloque y las listas de `## Orden actual` son decisión tuya. Se niega,
sin escribir nada, si el id no está entre las abiertas, si ROADMAP ya tiene su entrada
o si la fila `(pending)` no llegó a `origin/main` (hacé `git fetch`).

---

## 2. Flujo de trabajo con AI assistants

**Path canónico:** `docs/PROMPT_INSTRUCTIONS.md` (regla: leer por sección las partes de `docs/CONTEXT.md` que toca la tarea).
Los demás archivos de instrucciones son punteros a ese path:

- `CLAUDE.md` → `@docs/PROMPT_INSTRUCTIONS.md`, y nada más: se carga en cada turno.
  Las instrucciones de rtk son de la máquina (`~/.claude/RTK.md`); si `rtk init`
  vuelve a escribir su bloque acá, se borra
- `AI_CODING_GUIDELINES.md` → puntero corto al mismo archivo

`CLAUDE.md` carga `docs/PROMPT_INSTRUCTIONS.md` en cada sesión, así que un prompt no
necesita pedir que se lea CONTEXT: alcanza con nombrar la tarea.

---

## 3. Docs existentes

El catálogo por rol (guía viva vs metodología vs auditoría histórica vs ideación)
es `docs/INDEX.md`. Al agregar o borrar un `.md` de primera parte, actualizá la
**tabla canónica** de ese índice y corré:

```bash
./venv/bin/python3 scripts/check_doc_catalog.py
```

| Archivo | Cuándo actualizarlo |
|---------|---------------------|
| `docs/INDEX.md` | Al agregar, mover o borrar un `.md` de primera parte |
| `docs/architecture.md` | Cuando cambia el flujo de datos o se agrega una capa |
| `docs/ROADMAP.md` | Al completar una Fase (es diario histórico, no backlog abierto) |
| `docs/moat_methodology.md` | Al cambiar algoritmo o umbrales de moat |
| `docs/portfolio_optimizer.md` | Al cambiar constraints o función objetivo del optimizer |
| `docs/alert_system.md` | Al agregar tipos de alerta o cambiar el scheduler |
| `docs/DEMO_HOSTED.md` | Al cambiar el empaquetado Docker de la demo |
| `docs/IMPLEMENTATION_PLAN.md` / `docs/VISION_GRAN_SALTO.md` | No reabrir como “empezar ya”; son históricos / ideación |

---

## 4. Tests

Antes de cualquier merge:
```bash
make check
```

Es exactamente lo que corre el CI: `ruff check .` **antes** que los tests, así que un
error de formato aborta el build sin correr un solo test (`docs/PROMPT_INSTRUCTIONS.md`).
Si el cambio toca fechas u horas, además `TZ=UTC make test`.

Los tests deben pasar sin regresiones. Si se agrega una feature nueva, agregar tests en `tests/`.

---

## 5. Variables de entorno

Ver `.env.example` para la lista completa. Las más críticas:
- `ANTHROPIC_API_KEY` / `XAI_API_KEY` / `OPENAI_API_KEY` — para AI
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — para alertas
- `SMTP_*` — para email

Testear Telegram: `./venv/bin/python3 scripts/test_telegram.py`

---

## 6. Scheduler de alertas

Correr una vez manualmente:
```bash
./venv/bin/python3 scripts/run_scheduler.py --once
```

Para producción (cron diario):
```bash
# Agregar en crontab -e:
0 9 * * 1-5 /ruta/al/proyecto/scripts/run_daily_alerts.sh
```

En macOS, `make launchd-install` (launchd corre el disparo perdido al despertar).
`--once` también puntúa el track record y el backtesting point-in-time.

### Evidencia point-in-time (PIT-2)

```bash
./venv/bin/python3 scripts/point_in_time_backtest.py       # volumen: SYNTHETIC_BACKTEST.pit2_*
./venv/bin/python3 scripts/score_synthetic_outcomes.py     # outcome a 1 año
./venv/bin/python3 scripts/pit_evidence_report.py --out docs/PIT2_EVIDENCIA_$(date +%Y-%m).md
```

---

## 7. Convenciones generales

- **Sin comentarios obvios** — los nombres de funciones y variables deben ser auto-explicativos
- **Sin hardcodear thresholds** — todo en `config.py`
- **Sin `print()`** — usar `from loguru import logger`
- **Parámetros de cache como tuplas** — para hashability de `@st.cache_data`
- **No romper la API pública de los módulos de análisis** — el dashboard depende de `FundamentalResult`, `MonteCarloResult`, `GoalPlan`, etc.

## 8. Limpieza de código muerto

El informe histórico está en [`docs/DEAD_CODE_AUDIT.md`](DEAD_CODE_AUDIT.md).
Antes de borrar: `ruff check --select F401,F811,F841`, triage manual (páginas
Streamlit cargadas con `st.Page`, lazy imports, re-exports) y
`./venv/bin/python3 -m pytest tests/ -q`. No tocar el split crypto/equity ni
features marcadas ✅ en `docs/CONTEXT.md` §6 salvo evidencia clara.
