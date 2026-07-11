# Dead Code Audit — Retirement Advisor

**Fecha:** 2026-07-11  
**Alcance:** 100% del árbol de proyecto (excl. `venv/`, `.venv/`, `qa/node_modules/`, caches)  
**Iteraciones:** 7 (máximo del goal loop)  
**Resultado:** Criterios de éxito 1–4 verificados positivamente

---

## Resumen ejecutivo

Se realizó una auditoría exhaustiva de código no utilizado, redundante o perjudicial. Se eliminó o cableó dead code de alta confianza, se unificó un helper PDF duplicado, se habilitó detección de imports muertos en ruff (`F401`), y se cablearon las alertas `SORR_HIGH` / `GOAL_RISK` que existían sin callers (bug de feature incompleta).

| Métrica final | Valor |
|---------------|-------|
| Tests | **528 passed** |
| Ruff | **All checks passed** |
| Vulture (`--min-confidence 70`) | **0 hallazgos** |
| Módulos `.py` proyecto | 115 |

---

## Iteraciones

### Iteración 1 — Inventario (readonly)
- 114→115 módulos Python; ~31k LOC producción; 524 tests baseline.
- Grafo de imports, AST de defs huérfanas, duplicados PDF, APIs a medio cablear.
- **¿Última?** No.

### Iteración 2 — P1 dead APIs + imports
**Eliminado:**
| Símbolo | Ubicación |
|---------|-----------|
| `SignalMonitor` | `alerts/notifier.py` + export `__init__` |
| `DataCache.invalidate` | `data/cache.py` |
| `UserPreferences.update_universe` | `data/preferences.py` |
| `AllocationAdvisor.format_summary` | `portfolio/allocation.py` |
| `GoalResult.shortfall_median` / `surplus_median` | `portfolio/goals.py` |
| `TrackRecordStore.get_outcomes` | `analysis/track_record.py` |
| ~25+ imports no usados | varios módulos prod |

**Cableado (side-effect fix):**
- `remove_conviction(sym)` al eliminar posición en `dashboard/pages/3_Portfolio.py`

**Crypto:** imports muertos de `MoatAPIError`/`MoatParseError` removidos; catch amplio documentado.

### Iteración 3 — P0 SORR / GOAL_RISK
**Problema:** `check_sorr` y `check_goal_risk` sin callers; UI/mute/thresholds existían → feature fantasma.

**Solución:**
1. Persistir `sorr_early_drawdown_pct` en `PlanSnapshot.mc_summary` (`data/plan_store.py`).
2. Scheduler `_check_plan_mc_alerts()` llama ambos checks sobre el plan activo.
3. `GOAL_RISK` usa snapshot store (`GOAL:<plan_name>`) para `prev_prob` vs `prob_target_pct`.
4. +4 tests en `tests/test_alert_engine.py`.

### Iteración 4 — Duplicación PDF + lint F401
- Nuevo `reports/pdf_utils.py` con `chart_to_image` (antes 100% duplicado).
- `alerts/reporter.py` y `reports/investment_plan.py` reutilizan el helper.
- `ruff.toml`: se **habilitó F401**; se ignoran `E402`/`W291` intencionales (Streamlit lazy imports / prompts markdown).
- Eliminado bloque muerto `pandas_ta` en `analysis/technical.py` (import + `HAS_TA` sin uso).
- F841: variables muertas `priority_labels`, `recs`, `lb` en PDF/optimizer.

### Iteración 5 — Vulture + residuales
Vulture@70 = 0. Triage@60 → eliminaciones adicionales:

| Símbolo | Acción |
|---------|--------|
| `Backtester._normalize_index` | eliminado |
| `set_conviction` | eliminado (`set_all` es la API real) |
| `CANONICAL_FIELDS` | eliminado |
| `PROFILE_NAME_TO_RISK_TOLERANCE` | eliminado |
| `TICKER_ALIASES` | eliminado (duplicaba `_CRYPTO_NORM`) |
| `ALERTS.alerts_enabled` | **cableado** como master switch en `AlertEngine.run` |

### Iteración 6 — Docs / artifacts
- `code.review.md` (review obsoleto may-2026 con snippet de scoring superado) → `docs/archive/code.review.md`
- `print()` en stress_test/personal_sizer: solo en docstrings de uso → **conservar**

### Iteración 7 — Cierre
Verificaciones automáticas verdes (abajo). Este documento = artefacto final.

---

## Criterios de éxito (verificación final)

### Criterio 1 — Inventario 100%
Escaneados: `alerts/`, `analysis/`, `dashboard/` (+pages), `data/`, `portfolio/`, `reports/`, `scripts/`, `tests/`, `main.py`, `config*.py`, configs, docs, QA scripts (no node_modules).  
Hallazgos con `archivo:línea` documentados en iters 1–5.

### Criterio 2 — Impacto + solución
Cada P0/P1 fue eliminado, cableado o documentado. Residual consciente abajo.

### Criterio 3 — Verificación automática
```text
./venv/bin/python3 -m pytest tests/ -q   → 528 passed
./venv/bin/ruff check .                  → All checks passed
./venv/bin/vulture ... --min-confidence 70 → 0
rg de símbolos eliminados                → 0 refs (salvo docs de auditoría)
```

### Criterio 4 — Reporte consolidado
Este archivo.

---

## Residual consciente (no es “dead” accionable sin diseño)

| Ítem | Por qué se conserva |
|------|---------------------|
| Config fields no leídos (`require_technical_uptrend`, `min_margin_of_safety_pct`, `min_severity_*` en ALERTS, singletons `CONSISTENCY`/`PIOTROSKI`/`MOAT` si el código instancia la clase) | Contrato de config / futuro; scoring instancia `ConsistencyThresholds()` en lugar del singleton — candidata a unificar en follow-up no bloqueante |
| `load_snapshot` / `save_snapshot_to_path` | API offline Fase G; cubierta por tests |
| Scripts CLI (`refresh_context`, `run_scheduler`, `test_telegram`, `brainstorm_capture`) | Entry points documentados en MAINTENANCE |
| Páginas Streamlit sin import estático | Carga por path vía `st.Page` |
| `build_portfolio_committee_context` | Helper genérico + tests; `build_holdings_*` es el path UI |
| Dataclass fields / `session_state` attrs | Falsos positivos de vulture@60 |
| `sys.path.insert` en ~20 páginas | Deuda de empaquetado; refactor de alto diff, bajo valor dead-code |
| `_make_header_footer` / `_styles` divergentes entre PDF de alertas y plan | Solo `_chart_to_image` era idéntico; estilos/títulos distintos a propósito |
| `qa/out_*.json`, screenshots | Artifacts de QA manual, no código ejecutable |

---

## Recomendaciones follow-up — implementadas (2026-07-11)

| # | Follow-up | Estado | Notas |
|---|-----------|--------|-------|
| 1 | Singletons `CONSISTENCY`/`PIOTROSKI`/`MOAT` | ✅ | `scoring.py` usa singletons; `moat.py` thresholds/bonus/TTL desde `MOAT` |
| 2 | Wire strategy params | ✅ | **WIRE** (no delete): `is_value_stock` → `STRATEGY.min_margin_of_safety_pct`; `require_technical_uptrend` degrada BUY/STRONG_BUY → HOLD sin uptrend. Tests en `tests/test_strategy.py` |
| 3 | Centralizar `sys.path` | ✅ | `bootstrap.py` + entry points; páginas multipage sin inserts |
| 4 | Header/footer PDF paramétrico | ✅ | `reports/pdf_utils.make_header_footer` — callers solo pasan params |
| 5 | Vulture CI no bloqueante | ✅ | Job `dead-code` en `.github/workflows/ci.yml` con `continue-on-error: true`, `--min-confidence 80` |

---

## Lista de archivos tocados (principales)

- `alerts/{__init__,notifier,reporter,engine,store}.py`
- `analysis/{track_record,crypto_analyzer,committee,fundamental,scoring,technical,chat_tools,backtesting}.py`
- `dashboard/{app,shared}.py`, `pages/{3_Portfolio,7_Simulaciones,8_Alertas,10_About}.py` + F401 autofix en otras pages
- `data/{cache,preferences,personal_book_convictions,plan_store,data_sources,crypto_fetcher,plan_health}.py`
- `portfolio/{allocation,goals,tracker,optimizer}.py`
- `reports/{investment_plan,pdf_utils}.py` (nuevo)
- `scripts/run_scheduler.py`
- `config.py`, `ruff.toml`
- `tests/test_alert_engine.py`, `tests/test_plan_store.py`
- `docs/archive/code.review.md`, `docs/DEAD_CODE_AUDIT.md`

---

## ¿Esta fue la última iteración completa o se necesita una iteración adicional para verificar exhaustividad?

**Esta es la última iteración completa.**  
Criterios 1–4 verificados; vulture@70 limpio; suite y ruff verdes; residual documentado y no bloqueante.
