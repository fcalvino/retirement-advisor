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

**Path canónico:** `docs/PROMPT_INSTRUCTIONS.md` (regla: leer `docs/CONTEXT.md` primero).
Los demás archivos de instrucciones son punteros a ese path:

- `CLAUDE.md` → `@docs/PROMPT_INSTRUCTIONS.md` (no editar el bloque RTK)
- `AI_CODING_GUIDELINES.md` → puntero corto al mismo archivo

**Todo prompt a Claude Code o Grok Build debe comenzar así:**

```
Antes de responder, lee docs/CONTEXT.md completo.
[tu pregunta o tarea aquí]
```

O configurar Claude Code para leerlo automáticamente mediante `CLAUDE.md`.

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

## 8. Limpieza de código muerto

El informe histórico está en [`docs/DEAD_CODE_AUDIT.md`](DEAD_CODE_AUDIT.md).
Antes de borrar: `ruff check --select F401,F811,F841`, triage manual (páginas
Streamlit cargadas con `st.Page`, lazy imports, re-exports) y
`./venv/bin/python3 -m pytest tests/ -q`. No tocar el split crypto/equity ni
features marcadas ✅ en `docs/CONTEXT.md` §6 salvo evidencia clara.
