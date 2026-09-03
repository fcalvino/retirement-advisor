# `scripts/migrations/` — migraciones one-shot

Scripts que ya cumplieron su propósito. **No se corren de forma rutinaria.** Viven
acá —separados de las herramientas operacionales (`run_scheduler.py`, `run_eval.py`,
`measure_score_impact.py`, …)— para que un contribuidor nuevo distinga de un vistazo
"herramienta que se corre seguido" de "script que arregló algo una vez".

Todos son **dry-run por default** y **idempotentes**: una segunda corrida no cambia
nada y lo dice. Se conservan versionados porque documentan qué se tocó en la base del
usuario y cuándo, y porque `--apply` sigue siendo reversible/re-ejecutable si hiciera
falta.

| Script | Qué hace | Corrido | Contexto |
|--------|----------|---------|----------|
| `mark_test_fixture_rows.py` | Marca 53 filas de `recommendation_log` (escritas por la suite) con `source='test_fixture'` — no borra nada. | 2026-08-30 (`--apply`) | N6 / U5-18d — ver `docs/ROADMAP.md` y `docs/CONTEXT.md §8` |
| `purge_test_alert_rows.py` | Borra 2 filas de cooldown `TEST1` que dejó la suite en `alert_cooldowns`. | 2026-08-31 (`--apply`) | N6c — ver `docs/ROADMAP.md` |

Uso (desde la raíz del repo):

```bash
./venv/bin/python3 scripts/migrations/<script>.py            # sólo muestra
./venv/bin/python3 scripts/migrations/<script>.py --apply    # escribe
```
