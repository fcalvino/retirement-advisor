# Documentación — Retirement Advisor

Índice de **toda** la documentación de primera parte (raíz del repo + `docs/`).
Para una introducción general, leé el [`README.md`](../README.md). Para contribuir,
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

**Cómo leer este catálogo:** cada entrada tiene un **rol** para que se distinga
guía viva, metodología, contexto para AI, auditoría histórica e ideación.

No son docs de producto (y no están acá): `logs/*.md` y notas de sesión en `qa/`.

El chequeo `scripts/check_doc_catalog.py` usa la tabla canónica de abajo como
fuente de verdad.

---

## Catálogo canónico (por rol)

Cada fila es un archivo o una **colección** (directorio que termina en `/`).
Los miembros de una colección (p.ej. todo `docs/brainstorm/`) quedan cubiertos
por esa fila.

Roles:

| Rol | Significado |
|-----|-------------|
| `catalog` | Este índice |
| `living-guide` | Cómo usar, contribuir o mantener el proyecto **hoy** |
| `methodology` | Por qué el motor calcula como calcula |
| `how-to` | Cómo correr / publicar algo concreto |
| `ai-context` | Instrucciones para coding assistants (un solo path canónico) |
| `historical-audit` | Informe cerrado o snapshot; no es el próximo sprint |
| `historical-plan` | Plan o roadmap de trabajo **ya shipped** |
| `ideation` | Visión y brainstorm; no es spec de implementación |
| `archive` | Dump histórico; no es guía de integración actual |

<!-- catalog-table -->
| Rol | Path | Descripción |
|-----|------|-------------|
| catalog | `docs/INDEX.md` | Este índice |
| living-guide | `README.md` | Introducción, Quick Start, metodología resumida, árbol del repo |
| living-guide | `CONTRIBUTING.md` | Bugs, ideas, setup de desarrollo, PRs |
| living-guide | `docs/MAINTENANCE.md` | Cómo mantener CONTEXT y el resto de la documentación |
| how-to | `docs/DEMO_HOSTED.md` | Demo Docker (un usuario por instancia, no SaaS) |
| methodology | `docs/architecture.md` | Capas, flujo de datos, módulos |
| methodology | `docs/moat_methodology.md` | Economic Moat cuantitativo + AI |
| methodology | `docs/portfolio_optimizer.md` | SLSQP, constraints, fallback |
| methodology | `docs/alert_system.md` | Tipos de alerta, cooldowns, scheduler |
| ai-context | `docs/PROMPT_INSTRUCTIONS.md` | **Path canónico** — leer `docs/CONTEXT.md` primero |
| ai-context | `docs/CONTEXT.md` | Contexto canónico del proyecto (arquitectura, features, estándares) |
| ai-context | `AI_CODING_GUIDELINES.md` | Puntero corto al path canónico |
| ai-context | `CLAUDE.md` | Puntero Claude Code (`@docs/PROMPT_INSTRUCTIONS.md`) |
| historical-plan | `docs/ROADMAP.md` | Fases ya completadas (no es backlog abierto) |
| historical-plan | `docs/IMPLEMENTATION_PLAN.md` | Plan 2026-06 del Gran Salto — las 5 fases ya están shipped |
| ideation | `docs/VISION_GRAN_SALTO.md` | Visión de producto 2026-06; las 3 apuestas ya están en el código |
| ideation | `docs/brainstorm/` | Colección: un archivo por pantalla + capas; índice `00_INDICE.md` |
| historical-audit | `docs/AUDITORIA_2026-08.md` | Auditoría técnica ago-2026 (Tier 0/1 del motor) |
| historical-audit | `docs/auditoria_project_owner.md` | Auditoría de producto (project owner) |
| historical-audit | `docs/AUDIT_DATA_QUALITY.md` | Calidad de datos + estado P0 |
| historical-audit | `docs/AUDIT_REASONING_QUALITY.md` | Calidad de razonamiento (15/15 cerradas) |
| historical-audit | `docs/DEAD_CODE_AUDIT.md` | Auditoría de código muerto (2026-07) |
| historical-audit | `docs/universe_coverage_analysis.md` | Cobertura del universo (snapshot 2026-07) |
| archive | `docs/archive/code.review.md` | Review dump may-2026; **no** es guía de integración actual |
<!-- /catalog-table -->

---

## Guías vivas

| Documento | Descripción |
|-----------|-------------|
| [`README.md`](../README.md) | Introducción, Quick Start, configuración, metodología resumida |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Bugs, ideas, setup de desarrollo, PRs |
| [`MAINTENANCE.md`](MAINTENANCE.md) | Cómo mantener CONTEXT y el catálogo |
| [`DEMO_HOSTED.md`](DEMO_HOSTED.md) | Demo Docker single-user |

---

## Metodología y diseño

Documentos técnicos que explican el *porqué* detrás de las decisiones. Útiles
antes de modificar los módulos correspondientes.

| Documento | Módulo relacionado | Contenido |
|-----------|-------------------|-----------|
| [`architecture.md`](architecture.md) | Todos | Capas, flujo de datos, dependencias |
| [`moat_methodology.md`](moat_methodology.md) | `analysis/moat.py` | Moat cuantitativo + AI, umbrales Wide/Narrow |
| [`portfolio_optimizer.md`](portfolio_optimizer.md) | `portfolio/optimizer.py` | SLSQP, constraints, ARS discount, fallback |
| [`alert_system.md`](alert_system.md) | `alerts/` + `scripts/run_scheduler.py` | Tipos, cooldowns, cold start, scheduler |

---

## Contexto y guías para AI

Un solo path canónico: **`docs/PROMPT_INSTRUCTIONS.md`** (regla: leer
`docs/CONTEXT.md` primero). El resto son punteros.

| Documento | Descripción |
|-----------|-------------|
| [`PROMPT_INSTRUCTIONS.md`](PROMPT_INSTRUCTIONS.md) | Instrucciones obligatorias (Claude Code, Grok Build, etc.) |
| [`CONTEXT.md`](CONTEXT.md) | Contexto canónico — arquitectura, features, estándares, limitaciones |
| [`../AI_CODING_GUIDELINES.md`](../AI_CODING_GUIDELINES.md) | Puntero a `PROMPT_INSTRUCTIONS.md` |
| [`../CLAUDE.md`](../CLAUDE.md) | Puntero Claude Code (no editar el bloque RTK) |
| [`MAINTENANCE.md`](MAINTENANCE.md) | Cómo refrescar CONTEXT (`scripts/refresh_context.py`) |

---

## Planes e ideación (históricos)

No usar estos archivos como “el próximo sprint”. El estado actual de features
está en [`CONTEXT.md` §6](CONTEXT.md).

| Documento | Rol |
|-----------|-----|
| [`ROADMAP.md`](ROADMAP.md) | Diario de fases **ya completadas** |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | Plan operativo 2026-06 (Fases 1–5 shipped) |
| [`VISION_GRAN_SALTO.md`](VISION_GRAN_SALTO.md) | Visión 2026-06; las 3 apuestas ya están en el producto |
| [`brainstorm/00_INDICE.md`](brainstorm/00_INDICE.md) | Ideación por pantalla y capa |

---

## Auditorías históricas

Informes cerrados o snapshots. Útiles para el *porqué* de un fix; no son la
descripción viva del sistema.

| Documento | Contenido |
|-----------|-----------|
| [`AUDITORIA_2026-08.md`](AUDITORIA_2026-08.md) | Motor: D1–D6 (retiros, ruina, μ, oráculos, lockfile, PII) |
| [`auditoria_project_owner.md`](auditoria_project_owner.md) | Diagnóstico y priorización de producto |
| [`AUDIT_DATA_QUALITY.md`](AUDIT_DATA_QUALITY.md) | Fuentes, badges, política partial/poor |
| [`AUDIT_REASONING_QUALITY.md`](AUDIT_REASONING_QUALITY.md) | 15 debilidades de coherencia entre capas |
| [`DEAD_CODE_AUDIT.md`](DEAD_CODE_AUDIT.md) | Dead code 2026-07 |
| [`universe_coverage_analysis.md`](universe_coverage_analysis.md) | Cobertura del universo default (2026-07) |
| [`archive/code.review.md`](archive/code.review.md) | Dump de review may-2026 — **archivo, no guía** |

---

## Dónde encontrar qué

### Quiero entender el score de un ticker
→ [`README.md` § Cómo funciona](../README.md#cómo-funciona) — fórmula resumida
→ `analysis/fundamental.py` — las 5 dimensiones
→ `analysis/scoring.py` — Consistency Score + Piotroski F-Score

### Quiero cambiar el universo de tickers
→ Editar `DEFAULT_TICKERS` en `config.py`, o usar **⚙️ Settings** en el dashboard

### Quiero agregar un nuevo proveedor AI
→ [`architecture.md`](architecture.md) — flujo de la capa AI
→ `analysis/ai_analyzer.py` — clase `AIAnalyzer`
→ `config.py` — `AIConfig`

### Quiero entender el Moat cuantitativo
→ [`moat_methodology.md`](moat_methodology.md)
→ `analysis/moat.py` — `MoatAnalyzer.score_quantitative()`

### Quiero modificar los perfiles del Optimizer
→ [`portfolio_optimizer.md`](portfolio_optimizer.md)
→ `config.py` — `OPTIMIZER_PROFILES`

### Quiero agregar un nuevo escenario de stress test
→ `portfolio/stress_test.py` — dict `SCENARIOS`
→ [`README.md` § Stress Testing](../README.md#stress-testing)

### Quiero configurar alertas por email o Telegram
→ [`alert_system.md`](alert_system.md)
→ `.env.example`

### Quiero correr el scheduler en producción
→ [`alert_system.md`](alert_system.md) — cron, systemd, Docker

### Quiero publicar la demo Docker
→ [`DEMO_HOSTED.md`](DEMO_HOSTED.md)

### Quiero escribir o corregir un test
→ [`CONTRIBUTING.md` § Tests](../CONTRIBUTING.md#tests)
→ `tests/conftest.py`

### Voy a tocar código con un AI assistant
→ [`PROMPT_INSTRUCTIONS.md`](PROMPT_INSTRUCTIONS.md) (leer `CONTEXT.md` primero)

---

## Convenciones de los docs

- Los docs técnicos mencionan el módulo relacionado al inicio (`> **Módulo:** ...`)
- Los ejemplos de código usan snippets reales del codebase, no pseudocódigo
- Las tablas de umbrales describen la intención — si el código difiere, el código tiene precedencia
- Un archivo nuevo en raíz o `docs/` se agrega a la **tabla canónica** de este índice (y se corre `scripts/check_doc_catalog.py`)
