"""AUDIT-UI-ESTADO (Mis Metas) — la prioridad es la que dice el botón y el plan simulado es el de las metas de hoy.

1. ⬆️/⬇️ («Subir prioridad») sólo intercambiaban la posición de la meta en la lista; el motor lee el campo
   ``priority`` (Alta/Media/Baja = peso 3/2/1: ``portfolio/goals.py``) y nunca el orden, así que el botón no
   cambiaba nada del plan. Decisión del usuario (2026-10-28): los botones cambian la prioridad un nivel
   —⬆️ hacia Alta, ⬇️ hacia Baja— y sólo aparecen si hay un nivel adonde moverse; el orden queda como se cargó.
2. ``goal_plan_result`` se mostraba mientras existiera en la sesión: agregar, borrar o cambiar la
   prioridad de una meta dejaba en pantalla el plan de las metas anteriores. Ahora se muestra sólo si las
   metas son las que se simularon; si no, la página lo dice y pide simular de nuevo.

Se recorre la página real con AppTest; el historial de precios es sintético y sin red.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_cash_flow_oracle import _flat_history
from tests.test_eo1c_exigencia_perfil_oracle import GOAL, _prefs

PAGE = str(Path(__file__).resolve().parents[1] / "dashboard" / "views" / "7_Simulaciones.py")
SUMMARY = "📊 Resumen del plan"
STALE_NOTICE = "Cambiaste las metas desde la última simulación"


def _goal(name: str, priority: int) -> dict:
    return {**GOAL, "name": name, "priority": priority}


@pytest.fixture
def goals_page(monkeypatch):
    """``goals_page(goals)`` abre «Mis Metas» con esas metas y devuelve la app ya corrida."""
    from dashboard import shared

    prefs = _prefs("Moderado")
    monkeypatch.setattr(shared, "get_user_prefs", lambda: prefs)
    monkeypatch.setattr(shared, "seed_session_defaults_from_profile", lambda *a, **k: None)
    monkeypatch.setattr("analysis.estimacion.classes_for", lambda syms: {s: None for s in syms})
    monkeypatch.setattr("analysis.estimacion.countries_for", lambda syms: {s: None for s in syms})

    def open_page(goals: list[dict]) -> AppTest:
        at = AppTest.from_file(PAGE, default_timeout=180)
        at.session_state["universe"] = ["AAPL", "MSFT"]
        at.session_state["plan_n_sims"] = 1_000
        at.session_state["goals_list"] = goals
        at.run()
        assert not at.exception, [str(e)[:300] for e in at.exception]
        return at

    return open_page


def _headers(at: AppTest) -> list[str]:
    return [h.value for h in at.subheader]


def _simulate(at: AppTest) -> AppTest:
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda *a, **k: _flat_history(0.06)):
        at.button(key="run_goal_plan").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def _priorities(at: AppTest) -> list[tuple[str, int]]:
    return [(g["name"], g["priority"]) for g in at.session_state["goals_list"]]


# --------------------------------------------------------------------------- #
#  1 — ⬆️/⬇️ cambian la prioridad                                               #
# --------------------------------------------------------------------------- #

def test_the_up_button_raises_the_priority_one_level_and_keeps_the_order(goals_page):
    at = goals_page([_goal("A", 1), _goal("B", 3)])
    at.button(key="up_1").click().run()
    assert _priorities(at) == [("A", 1), ("B", 2)]


def test_the_down_button_lowers_the_priority_one_level_and_keeps_the_order(goals_page):
    at = goals_page([_goal("A", 1), _goal("B", 3)])
    at.button(key="dn_0").click().run()
    assert _priorities(at) == [("A", 2), ("B", 3)]


def test_there_is_no_button_that_has_nowhere_to_go(goals_page):
    at = goals_page([_goal("A", 1), _goal("B", 3), _goal("C", 2)])
    keys = {b.key for b in at.button}
    assert "up_0" not in keys and "dn_0" in keys      # Alta: no sube
    assert "up_1" in keys and "dn_1" not in keys      # Baja: no baja
    assert "up_2" in keys and "dn_2" in keys          # Media: las dos


def test_the_priority_the_page_shows_is_the_one_the_engine_reads(goals_page):
    at = goals_page([_goal("A", 3)])
    at.button(key="up_0").click().run()
    assert "Media" in "\n".join(m.value for m in at.markdown)


# --------------------------------------------------------------------------- #
#  2 — el plan simulado es el de las metas de hoy                              #
# --------------------------------------------------------------------------- #

def test_the_summary_is_shown_for_the_goals_that_were_simulated(goals_page):
    at = _simulate(goals_page([_goal("A", 1), _goal("B", 2)]))
    assert SUMMARY in _headers(at)
    at.run()                                           # un rerun cualquiera no lo borra
    assert SUMMARY in _headers(at)
    assert STALE_NOTICE not in "\n".join(i.value for i in at.info)


@pytest.mark.parametrize("change", ["delete", "reprioritize"])
def test_a_plan_of_other_goals_is_not_shown(goals_page, change):
    at = _simulate(goals_page([_goal("A", 1), _goal("B", 3)]))
    assert SUMMARY in _headers(at)
    at.button(key="del_goal_1" if change == "delete" else "up_1").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert SUMMARY not in _headers(at)
    assert STALE_NOTICE in "\n".join(i.value for i in at.info)


def test_simulating_again_shows_the_plan_of_the_new_goals(goals_page):
    at = _simulate(goals_page([_goal("A", 1), _goal("B", 3)]))
    at.button(key="del_goal_1").click().run()
    _simulate(at)
    assert SUMMARY in _headers(at)
    assert STALE_NOTICE not in "\n".join(i.value for i in at.info)


# --------------------------------------------------------------------------- #
#  3 — lo mismo para el portafolio optimizado para las metas                   #
# --------------------------------------------------------------------------- #

def _with_goal_optimizer(at: AppTest, goals: list[dict]) -> AppTest:
    """Deja en la sesión un portafolio optimizado para estas metas, como lo haría «Optimizar para mis metas»."""
    import json

    from portfolio.optimizer import OptimizationResult, TickerAllocation

    at.session_state["goal_optimizer_result"] = OptimizationResult(
        profile_name="Moderado", method="mean-variance",
        tickers=[TickerAllocation("AAPL", 100.0, 7.0, 20.0, 0.5, 80.0, 5.0, "Technology")],
    )
    at.session_state["goal_optimizer_explanation"] = "Explicación del portafolio"
    at.session_state["goal_optimizer_goals_sig"] = json.dumps(goals, sort_keys=True, default=str)
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


GOAL_OPT_HEADER = "🎯 Portafolio optimizado para tus metas"
GOAL_OPT_NOTICE = "Cambiaste las metas desde la última optimización"


def test_the_portfolio_optimized_for_the_goals_is_shown_while_the_goals_are_the_same(goals_page):
    goals = [_goal("A", 1), _goal("B", 3)]
    at = _with_goal_optimizer(goals_page(goals), goals)
    assert GOAL_OPT_HEADER in _headers(at)
    assert GOAL_OPT_NOTICE not in "\n".join(i.value for i in at.info)


def test_a_portfolio_optimized_for_other_goals_is_not_shown(goals_page):
    goals = [_goal("A", 1), _goal("B", 3)]
    at = _with_goal_optimizer(goals_page(goals), goals)
    at.button(key="del_goal_1").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert GOAL_OPT_HEADER not in _headers(at)
    assert GOAL_OPT_NOTICE in "\n".join(i.value for i in at.info)
