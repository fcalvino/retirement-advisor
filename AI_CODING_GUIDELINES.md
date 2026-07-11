# AI Coding Guidelines — Retirement Advisor

> Para: Claude Code, Grok Build, Cursor, GitHub Copilot, o cualquier AI coding assistant.

---

## ANTES DE EMPEZAR — OBLIGATORIO

**Lee siempre estos archivos antes de planear o escribir código:**

1. `docs/CONTEXT.md` — contexto completo del proyecto (arquitectura, features, estándares, limitaciones)
2. `config.py` — fuente de verdad de thresholds y parámetros
3. `analysis/prompts.py` — si vas a tocar lógica de IA
4. `docs/ROADMAP.md` — si vas a planear una nueva fase

**Confirma al inicio de tu respuesta:**
```
✅ He leído CONTEXT.md actualizado
```

---

## Principios de diseño del proyecto

| Principio | Descripción |
|-----------|-------------|
| Config centralizada | Todos los thresholds en `config.py`. Nunca hardcodear números en módulos de análisis. |
| Cache explícito | Dashboard usa `@st.cache_data`. Parámetros como tuplas para hashability. |
| Sin async | El proyecto es síncrono. No introducir `asyncio` sin consenso. |
| Sin mocks de DB | Los tests que tocan SQLite usan DB real (SQLite en memoria), no mocks. |
| Logging con loguru | Nunca `print()`. Importar `from loguru import logger`. |
| Multi-proveedor AI | Soporte para Claude, Grok, OpenAI, Nous. Cambios de AI deben funcionar con todos. |

---

## Patrones frecuentes

### Agregar una función cacheada al dashboard
```python
@st.cache_data(ttl=3600)
def cached_nueva_funcion(param1: str, param2: tuple[float, ...]) -> ResultType:
    # params como tipos simples o tuplas — nunca listas ni objetos complejos
    ...
```

### Leer config AI desde el dashboard
```python
from dashboard.shared import _get_ai_config
ai_config = _get_ai_config()  # resuelve desde st.session_state
```

### Usar thresholds de config.py
```python
from config import THRESHOLDS, STRATEGY, MONTE_CARLO
# No: if score > 75:
# Sí:
if score >= STRATEGY.strong_buy:
```

---

## Estructura de directorios

```
retirement_advisor/
├── analysis/       # Scoring, moat, backtesting, AI layer
├── portfolio/      # Optimizer, Monte Carlo, goals, stress test
├── dashboard/      # Streamlit UI (app.py + pages/)
├── alerts/         # Engine, store, notifier, reporter
├── data/           # Fetcher, cache SQLite
├── scripts/        # Scheduler, utilidades
├── tests/          # Test suite (pytest)
├── docs/           # Documentación técnica
└── config.py       # Configuración centralizada
```

---

## Verificación antes de proponer cambios

```bash
# Correr tests
./venv/bin/python3 -m pytest tests/ -v

# Actualizar contexto
./venv/bin/python3 scripts/refresh_context.py
```

---

## Recursos adicionales

- `docs/architecture.md` — diagrama de capas y flujo de datos detallado
- `docs/moat_methodology.md` — metodología del Economic Moat
- `docs/portfolio_optimizer.md` — algoritmo del optimizer (SLSQP, constraints)
- `docs/alert_system.md` — tipos de alerta, cooldowns, scheduler
- `docs/MAINTENANCE.md` — cómo mantener la documentación actualizada
