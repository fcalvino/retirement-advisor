"""Oráculo PLAN-GOALS-KEYS: una meta incompleta no rompe Simulaciones.

Las metas de `data/sample_plans/*.json` traían sólo `name`, `target_amount_today`,
`horizon_years` y `priority`. «Cargar plan» las copia tal cual a `goals_list`
(`plan_load_session_updates`), y dos lectores las leen con `g["…"]`:

- «Mis Metas» (`7_Simulaciones.py`) lee `expected_inflation` y
  `annual_contribution` al dibujar cada meta → `KeyError` al abrir la pestaña.
- `cached_goal_simulation` / `cached_goal_savings_needed` (`dashboard/shared.py`)
  construyen `Goal` con `expected_inflation`, `annual_contribution` y
  `allocated_capital` → arreglar sólo la página corre el `KeyError` a «Simular».

Las metas del formulario traen todas las claves, así que un plan guardado por el
usuario no se rompía; sí uno de ejemplo o un JSON importado. Visto en la QA en
vivo de PLAN-SAVE-PARAMS, igual en `origin/main` (`6b4b647`).

Decisión del usuario: las dos cosas — una meta sin esas claves toma los defaults
de `Goal`, y los JSON de ejemplo se completan. La referencia de los defaults es
un `Goal` construido sólo con sus campos obligatorios, no el código del fix.
"""

from __future__ import annotations

from dataclasses import MISSING, fields
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from data.plan_context import list_sample_plans, load_sample_plan
from data.plan_store import PlanSnapshot
from portfolio.goals import PRIORITY_LABELS, Goal
from tests.test_cash_flow_oracle import _flat_history
from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)

APP = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")
SAMPLE_KEYS = sorted(p["key"] for p in list_sample_plans())

# Lo que leen con `g["…"]` «Mis Metas» y la construcción de `Goal` en shared.py.
READ_KEYS = {
    "name", "target_amount_today", "horizon_years", "priority",
    "expected_inflation", "annual_contribution", "allocated_capital",
}
# Una meta vieja: sólo los campos que `Goal` no puede completar.
OLD_GOAL = {"name": "Casa", "target_amount_today": 200_000, "horizon_years": 8}


def _goals_after_load(snap: PlanSnapshot) -> list[dict]:
    from data.product_ux import plan_load_session_updates

    return plan_load_session_updates(snap, horizon_years=20)["goals_list"]


def _plan(goals: list[dict]) -> PlanSnapshot:
    return PlanSnapshot(id="plan-metas", name="Plan metas", created_at="",
                        updated_at="", goals=goals)


def test_the_samples_exist():
    assert len(SAMPLE_KEYS) == 3, SAMPLE_KEYS


# --------------------------------------------------------------------------- #
#  Lo que llega a `goals_list`                                                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", SAMPLE_KEYS)
def test_every_sample_goal_arrives_with_every_key_its_readers_use(key):
    goals = _goals_after_load(load_sample_plan(key))
    assert goals, f"{key}: el plan de ejemplo no trae metas"
    for g in goals:
        assert READ_KEYS <= set(g), f"{key}: faltan {sorted(READ_KEYS - set(g))}"
        Goal(**{f.name: g[f.name] for f in fields(Goal) if f.name in g})


@pytest.mark.parametrize("key", SAMPLE_KEYS)
def test_every_sample_file_is_complete(key):
    """Los JSON se completan: un archivo de ejemplo no depende del relleno."""
    snap = load_sample_plan(key)
    for g in snap.goals:
        assert READ_KEYS <= set(g), f"{key}.json: faltan {sorted(READ_KEYS - set(g))}"
        # Traían «esencial»/«importante»: `Goal.priority` es 1–3 y un texto rompe
        # «Simular» (`int(goal.priority)`) o pesa como «Media» sin avisar.
        assert g["priority"] in PRIORITY_LABELS, f"{key}.json: priority={g['priority']!r}"


def test_an_old_goal_takes_the_goal_defaults():
    reference = Goal(**OLD_GOAL)
    (g,) = _goals_after_load(_plan([dict(OLD_GOAL)]))
    for f in fields(Goal):
        assert g[f.name] == getattr(reference, f.name), f.name


def test_control_a_complete_goal_is_not_touched():
    """Lo que el formulario escribe —valores que no son el default— queda igual."""
    full = {
        "name": "Retiro", "goal_type": "retiro", "target_amount_today": 900_000.0,
        "horizon_years": 22, "priority": 1, "expected_inflation": 2.25,
        "annual_contribution": 12_000.0, "allocated_capital": 50_000.0,
        "notes": "nota",
    }
    (g,) = _goals_after_load(_plan([dict(full)]))
    assert g == full


def test_control_the_plan_goals_are_not_mutated():
    """Normalizar no escribe sobre el plan guardado."""
    snap = _plan([dict(OLD_GOAL)])
    _goals_after_load(snap)
    assert snap.goals == [OLD_GOAL]


def test_control_every_goal_field_without_default_is_in_the_old_goal():
    """El oráculo cubre todo campo obligatorio de `Goal` (si se agrega uno, avisa)."""
    required = {f.name for f in fields(Goal)
                if f.default is MISSING and f.default_factory is MISSING}
    assert required == set(OLD_GOAL)


# --------------------------------------------------------------------------- #
#  La app real: Mi Plan → «Cargar plan» → Simulaciones → «Simular»            #
# --------------------------------------------------------------------------- #

def _load(stores, snap: PlanSnapshot) -> AppTest:  # noqa: F811
    from data.preferences import UserPreferences

    stores.plans.upsert(snap)
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["user_prefs"] = UserPreferences()
    at.switch_page("views/12_Plan.py").run()
    assert not at.exception, [e.message for e in at.exception]
    at.button(key=f"view_{snap.id}").click().run()
    at.button(key=f"load_{snap.id}").click().run()
    assert not at.exception, [e.message for e in at.exception]
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        at.switch_page("views/7_Simulaciones.py").run()
    return at


@pytest.mark.parametrize("key", SAMPLE_KEYS)
def test_a_loaded_sample_opens_mis_metas_and_simulates(stores, key):  # noqa: F811
    snap = load_sample_plan(key)
    at = _load(stores, snap)
    assert not at.exception, [e.message for e in at.exception]   # main: KeyError
    names = [g["name"] for g in snap.goals]
    assert any(n in m.value for m in at.markdown for n in names)

    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        at.button(key="run_goal_plan").click().run()
    assert not at.exception, [e.message for e in at.exception]
    result = at.session_state["goal_plan_result"]
    assert sorted(r.goal.name for r in result.goal_results) == sorted(names)
