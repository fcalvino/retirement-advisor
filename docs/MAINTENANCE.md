# Guía de Mantenimiento — Retirement Advisor

> Documento dirigido al maintainer del proyecto (humano o AI). Explica cómo mantener la documentación y el contexto actualizados.

---

## 1. El archivo más importante: `docs/CONTEXT.md`

`docs/CONTEXT.md` es el **contexto canónico del proyecto**. Cualquier AI coding assistant (Claude Code, Grok Build, etc.) debe leerlo antes de planear o codificar. Si este archivo está desactualizado, el AI trabajará con información incorrecta.

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

---

## 2. Flujo de trabajo con AI assistants

**Todo prompt a Claude Code o Grok Build debe comenzar así:**

```
Antes de responder, lee docs/CONTEXT.md completo.
[tu pregunta o tarea aquí]
```

O configurar Claude Code para leerlo automáticamente mediante `CLAUDE.md` (ya está configurado via `@docs/PROMPT_INSTRUCTIONS.md`).

---

## 3. Docs técnicos existentes

| Archivo | Cuándo actualizarlo |
|---------|---------------------|
| `docs/architecture.md` | Cuando cambia el flujo de datos o se agrega una capa |
| `docs/ROADMAP.md` | Al completar una Fase o definir una nueva |
| `docs/moat_methodology.md` | Al cambiar algoritmo o umbrales de moat |
| `docs/portfolio_optimizer.md` | Al cambiar constraints o función objetivo del optimizer |
| `docs/alert_system.md` | Al agregar tipos de alerta o cambiar el scheduler |
| `docs/INDEX.md` | Al agregar un nuevo archivo de docs |

---

## 4. Tests

Antes de cualquier merge:
```bash
./venv/bin/python3 -m pytest tests/ -v
```

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

---

## 7. Convenciones generales

- **Sin comentarios obvios** — los nombres de funciones y variables deben ser auto-explicativos
- **Sin hardcodear thresholds** — todo en `config.py`
- **Sin `print()`** — usar `from loguru import logger`
- **Parámetros de cache como tuplas** — para hashability de `@st.cache_data`
- **No romper la API pública de los módulos de análisis** — el dashboard depende de `FundamentalResult`, `MonteCarloResult`, `GoalPlan`, etc.

## 8. Limpieza de código innecesario, inutilizado y duplicado

Sigue el plan dedicado en `.grok/sessions/.../plan.md` (o búscalo en el historial de la sesión) para investigar y remover dead code / duplicados que cumplen la misma función.

**Pasos típicos (resumen):**
1. Investigación (antes de borrar):
   - `./venv/bin/python3 -m pytest tests/ -q` (baseline).
   - Auditoría: `ruff check --select F401,F811,F841` (o equivalente). Instalar `vulture` si es necesario (`pip install vulture`) y correr con `--min-confidence 70 --exclude venv,__pycache__`. **Siempre** triage manual: falsos positivos comunes por carga dinámica de páginas Streamlit (`st.Page`), lazy imports, re-exports en `__init__.py`, entry points y `@st.cache_data`.
   - Conteo de referencias: `grep` / `rg` por `from X import|import X` (excluyendo tests/venv) para cada módulo bajo `analysis/`, `portfolio/`, `data/`, `alerts/`, `reports/`, `dashboard/` (excluyendo el monolith ya removido).
   - Buscar duplicados explícitos de funciones (mismo nombre/firma o comportamiento idéntico) vía grep de `^def ` + diff manual.
2. Limpieza priorizada:
   - El caso más grande histórico fue `dashboard/app_monolith.py` (2540 LOC de UI legacy + copia exacta de helpers que ahora están solo en `shared.py`). Confirmado 0 refs → `git rm`.
   - Pequeños: duplicados de datos (ej. tickers repetidos en `config.py`), funciones internas sin callers.
   - **No tocar** (salvo evidencia clara): split crypto/equity (intencional, usa `CRYPTO_MOAT`, `crypto_analyzer`, tests dedicados), scripts documentados en este archivo (refresh_context, run_scheduler, test_telegram), features marcadas ✅ en `docs/CONTEXT.md` §6.
3. Después de cada borrado/edición:
   - Tests completos + smoke manual de **todas** las páginas (Screener, Optimizer, Simulaciones, Stock Analysis, etc.) + CLI (`main.py`).
   - `grep -r --include="*.py" --include="*.md" --exclude-dir=venv --exclude-dir=__pycache__ "nombre_del_archivo_borrado" .` debe dar 0.
   - `git add` **solo** los paths intencionales (el D del rm + tus edits). Ignora otros M/?? locales (prefs, logs, artifacts).
4. Docs:
   - Actualizar `docs/architecture.md` (descripciones de UI), `docs/CONTEXT.md` (mapa de archivos, §9 últimos cambios si aplica) y este archivo.
   - Correr siempre `./venv/bin/python3 scripts/refresh_context.py` y pegar bloques relevantes.
5. Convención: documentar la limpieza en el commit ("chore: remove dead monolith...") y opcionalmente agregar nota en ROADMAP o como "último cambio" en CONTEXT.

Este proceso mantiene el repo magro, reduce confusión y respeta la deuda técnica del refactor multipage + estándares del proyecto.
