# Documentación — Retirement Advisor

Índice de toda la documentación técnica del proyecto. Para una introducción general, leé el [`README.md`](../README.md) en la raíz. Para contribuir, leé [`CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## Guías de usuario

| Documento | Descripción |
|-----------|-------------|
| [`README.md`](../README.md) | Introducción, Quick Start, configuración, metodología resumida, estructura del proyecto |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Cómo reportar bugs, proponer ideas, hacer setup de desarrollo y abrir PRs |

---

## Metodología y diseño

Documentos técnicos que explican el *porqué* detrás de las decisiones de diseño. Útiles antes de modificar los módulos correspondientes.

| Documento | Módulo relacionado | Contenido |
|-----------|-------------------|-----------|
| [`architecture.md`](architecture.md) | Todos | Mapa de capas del sistema, flujo de datos, dependencias entre módulos |
| [`moat_methodology.md`](moat_methodology.md) | `analysis/moat.py` | Cálculo del Economic Moat (cuantitativo + AI), umbrales Wide/Narrow/Minimal/None, ejemplos reales |
| [`portfolio_optimizer.md`](portfolio_optimizer.md) | `portfolio/optimizer.py` | SLSQP, función objetivo, constraints por perfil, ARS discount, fallback score-weighted |
| [`alert_system.md`](alert_system.md) | `alerts/` + `scripts/run_scheduler.py` | Tipos de alerta, cooldowns, cold start, scheduler cron/systemd/Docker |

---

## Historial del proyecto

| Documento | Contenido |
|-----------|-----------|
| [`ROADMAP.md`](ROADMAP.md) | Fases completadas (1 → 13), decisiones de arquitectura por fase, archivos principales |

---

## Dónde encontrar qué

### Quiero entender el score de un ticker
→ [`README.md § Cómo funciona`](../README.md#cómo-funciona) — fórmula resumida  
→ `analysis/fundamental.py` — implementación de las 5 dimensiones  
→ `analysis/scoring.py` — Consistency Score + Piotroski F-Score  

### Quiero cambiar el universo de tickers
→ Editar `DEFAULT_TICKERS` en `config.py`, o usar **⚙️ Settings** en el dashboard  

### Quiero agregar un nuevo proveedor AI
→ [`architecture.md`](architecture.md) — flujo de la capa AI  
→ `analysis/ai_analyzer.py` — clase `AIAnalyzer`, método `analyze()`  
→ `config.py` — `AIConfig`  

### Quiero entender el Moat cuantitativo
→ [`moat_methodology.md`](moat_methodology.md) — metodología completa con umbrales  
→ `analysis/moat.py` — `MoatAnalyzer.score_quantitative()`  

### Quiero modificar los perfiles del Optimizer
→ [`portfolio_optimizer.md`](portfolio_optimizer.md) — tabla de constraints  
→ `config.py` — `OPTIMIZER_PROFILES`  

### Quiero agregar un nuevo escenario de stress test
→ `portfolio/stress_test.py` — dict `SCENARIOS`, método `run()`  
→ [`README.md § Stress Testing`](../README.md#stress-testing)  

### Quiero configurar alertas por email o Telegram
→ [`alert_system.md`](alert_system.md) — variables de entorno y ejemplos  
→ `.env.example` — variables necesarias  

### Quiero correr el scheduler en producción
→ [`alert_system.md § Scheduler`](alert_system.md) — cron, systemd, Docker  

### Quiero escribir o corregir un test
→ [`CONTRIBUTING.md § Tests`](../CONTRIBUTING.md#tests) — convenciones y ejemplos de mocks  
→ `tests/conftest.py` — fixtures compartidos  

---

## Convenciones de los docs

- Los docs técnicos mencionan el módulo relacionado al inicio (`> **Módulo:** ...`)
- Los ejemplos de código usan snippets reales del codebase, no pseudocódigo
- Las tablas de umbrales son la fuente de verdad — si el código difiere, el código tiene precedencia
