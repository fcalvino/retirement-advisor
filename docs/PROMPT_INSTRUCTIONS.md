# INSTRUCCIONES OBLIGATORIAS PARA CUALQUIER AI CODING ASSISTANT

> Aplica a: **Claude Code**, **Grok Build**, **Cursor**, **Copilot**, o cualquier otro AI coding assistant.

---

## REGLA PRINCIPAL

**Antes de generar CUALQUIER plan, fix, feature o código en este proyecto:**

1. Lee completamente el archivo `docs/CONTEXT.md`
2. Lee `config.py` (fuente de verdad de thresholds, perfiles y parámetros)
3. Si vas a modificar prompts o lógica AI → lee `analysis/prompts.py`
4. Si vas a modificar el roadmap o planear una Fase nueva → lee `docs/ROADMAP.md`

**Incluye al inicio de tu respuesta:**
```
✅ He leído CONTEXT.md actualizado
```

Nunca propongas cambios sin haber cargado primero este contexto.

---

## Por qué esto es importante

- `config.py` tiene singletons globales (`THRESHOLDS`, `MONTE_CARLO`, `OPTIMIZER_PROFILES`, etc.) — nunca hardcodees números en el código de análisis
- Los estándares de código del proyecto (cache con tuplas, `_get_ai_config()`, loguru, NullPool) están documentados en `docs/CONTEXT.md §5`
- El estado actual de features (qué está ✅ completo y qué está ⏳ pendiente) está en `docs/CONTEXT.md §6`
- Las limitaciones conocidas (EMFILE, KaTeX, hot-reload, etc.) están en `docs/CONTEXT.md §8`

---

## Checklist antes de proponer código

- [ ] ¿Leí `docs/CONTEXT.md` completo?
- [ ] ¿El cambio requiere editar thresholds? → hacerlo en `config.py`, no inline
- [ ] ¿Agrego una función de dashboard? → usar `@st.cache_data` y pasar params como tuplas
- [ ] ¿Toco lógica AI? → revisar `analysis/prompts.py` y `analysis/ai_analyzer.py`
- [ ] ¿Los tests pasan? → `./venv/bin/python3 -m pytest tests/`
- [ ] ¿Actualicé `docs/CONTEXT.md` si el cambio es grande?

---

## Para mantener CONTEXT.md actualizado

Ver `docs/MAINTENANCE.md` y ejecutar:
```bash
./venv/bin/python3 scripts/refresh_context.py
```
