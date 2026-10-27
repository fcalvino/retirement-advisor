"""AUDIT-CHAT-PROYECCION — «¿me alcanza?» se proyecta con el ahorro, el retiro y la meta del plan.

``retirement_projection`` (la herramienta del chat) tomaba ``initial_value`` y ``horizon_years`` del plan
activo, pero ``annual_contribution``, ``annual_withdrawal`` y ``target_value`` salían sólo de los argumentos
del LLM, con 0 por defecto: una pregunta sin cifras proyectaba un plan sin ahorro, sin retiro y sin meta, y
la respuesta («tu probabilidad de ruina es X %») describía otro plan. El plan guarda lo que corrió en
``mc_summary`` (``monthly_savings``, ``annual_withdrawal``, ``target_value``); el perfil, en ``personal``.

Los esperados están escritos a mano (1 500/mes = 18 000/año; 800/mes = 9 600/año). El simulador se
reemplaza por uno que registra con qué lo llamaron: lo que se mide es la entrada, no la simulación. Sin red.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

import analysis.chat_tools as chat_tools


class _FakeSim:
    """Registra los argumentos de ``run``; devuelve un resultado con los campos que la herramienta lee."""

    last_run: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def run(self, **kwargs):
        type(self).last_run = dict(kwargs)
        return NS(median_terminal=1.0, p10_terminal=1.0, p90_terminal=1.0,
                  prob_ruin_pct=0.0, prob_achieve_target_pct=50.0)


def _plan(*, mc=None, personal=None, strategy=None, drags=None):
    return NS(
        name="Plan", profile_key="moderate", mc_summary=mc, personal=personal or {},
        withdrawal_strategy=strategy, drags_at_save=drags,
        target_weights=lambda: {"SPY": 60.0, "BND": 40.0},
    )


@pytest.fixture
def project(monkeypatch):
    """``project(plan, prefs=None, **args)`` corre la herramienta y devuelve ``(salida, run_kwargs)``."""
    import analysis.estimacion as estimacion
    import data.preferences as preferences
    import portfolio.monte_carlo as monte_carlo

    monkeypatch.setattr(monte_carlo, "MonteCarloSimulator", _FakeSim)
    # Sin red: las clases y los países de los símbolos no se consultan al feed.
    monkeypatch.setattr(estimacion, "classes_for", lambda symbols: {s: "equity" for s in symbols})
    monkeypatch.setattr(estimacion, "countries_for", lambda symbols: {s: "US" for s in symbols})

    def _run(plan, prefs=None, **args):
        _FakeSim.last_run = {}
        monkeypatch.setattr(chat_tools, "_active_plan", lambda: plan)
        monkeypatch.setattr(
            preferences.UserPreferences, "load", classmethod(lambda cls: prefs or NS(
                chosen_profile_key=None, planning_scenario=None,
                monthly_savings=None, annual_savings=None))
        )
        out = chat_tools._tool_retirement_projection(args)
        return out, dict(_FakeSim.last_run)

    return _run


def test_without_arguments_the_projection_uses_the_savings_the_plan_ran_with(project):
    plan = _plan(mc={"monthly_savings": 1500.0, "annual_withdrawal": 0.0, "target_value": 500_000.0},
                 personal={"current_capital": 200_000, "primary_horizon_years": 20})
    out, run = project(plan)
    assert out["ok"], out
    assert run["annual_contribution"] == 18_000.0
    assert run["target_value"] == 500_000.0
    assert run["annual_withdrawal"] == 0.0
    assert run["initial_value"] == 200_000.0 and run["horizon_years"] == 20


def test_the_plan_withdrawal_is_used_when_the_plan_has_no_strategy(project):
    plan = _plan(mc={"monthly_savings": 0.0, "annual_withdrawal": 30_000.0},
                 personal={"current_capital": 400_000, "primary_horizon_years": 25})
    _, run = project(plan)
    assert run["annual_withdrawal"] == 30_000.0


def test_explicit_arguments_win_over_the_plan(project):
    plan = _plan(mc={"monthly_savings": 1500.0, "annual_withdrawal": 30_000.0, "target_value": 500_000.0})
    _, run = project(plan, annual_contribution=6_000, annual_withdrawal=10_000, target_value=900_000)
    assert (run["annual_contribution"], run["annual_withdrawal"], run["target_value"]) == (6_000.0, 10_000.0, 900_000.0)


def test_an_explicit_zero_is_an_answer_not_a_missing_argument(project):
    """«Si dejo de ahorrar»: el 0 explícito gana sobre los 18 000 del plan."""
    plan = _plan(mc={"monthly_savings": 1500.0})
    _, run = project(plan, annual_contribution=0)
    assert run["annual_contribution"] == 0.0


def test_a_plan_that_ran_without_saving_is_not_given_the_profile_savings(project):
    """Un 0 guardado por el plan es «no aporto»: no se lo reemplaza por el ahorro del perfil."""
    plan = _plan(mc={"monthly_savings": 0.0}, personal={"monthly_savings": 2_000})
    _, run = project(plan)
    assert run["annual_contribution"] == 0.0


def test_a_plan_without_a_saved_run_falls_back_to_its_profile_then_to_the_current_one(project):
    # El perfil guardado con el plan.
    out, run = project(_plan(mc=None, personal={"monthly_savings": 1_000}))
    assert run["annual_contribution"] == 12_000.0
    assert out["assumption_sources"]["annual_contribution"] == "perfil del plan"
    # Sin eso, el perfil de hoy.
    prefs = NS(chosen_profile_key=None, planning_scenario=None, monthly_savings=800, annual_savings=None)
    out, run = project(_plan(mc=None), prefs=prefs)
    assert run["annual_contribution"] == 9_600.0
    assert out["assumption_sources"]["annual_contribution"] == "perfil actual"


def test_with_no_savings_figure_anywhere_it_says_so(project):
    out, run = project(_plan(mc=None))
    assert run["annual_contribution"] == 0.0
    assert out["assumption_sources"]["annual_contribution"] == "sin dato"


def test_each_assumption_says_where_it_came_from(project):
    plan = _plan(mc={"monthly_savings": 1500.0, "target_value": 500_000.0},
                 personal={"current_capital": 200_000})
    out, _ = project(plan, annual_withdrawal=5_000)
    assert out["assumption_sources"] == {
        "annual_contribution": "plan",
        "annual_withdrawal": "argumento",
        "target_value": "plan",
    }


STRATEGY = {"kind": "constant_pct", "pct": 0.04}
DRAGS = {"enabled": True, "annual_fee_pct": 0.5}


def test_a_plan_with_a_withdrawal_strategy_is_run_with_that_strategy_and_its_saving_years(project):
    """La estrategia, los años de ahorro y la longevidad viajan al motor: él decide qué hace con el ahorro.

    Sumar a mano el ahorro y un retiro fijo daba un híbrido que el plan nunca corrió (ahorra todo el
    horizonte y no retira nada).
    """
    plan = _plan(mc={"monthly_savings": 1500.0, "annual_withdrawal": 30_000.0, "retirement_years": 0,
                     "longevity_years": 30}, strategy=STRATEGY)
    out, run = project(plan)
    assert run["withdrawal_strategy"] == STRATEGY
    assert run["years_to_retirement"] == 0 and run["longevity_years"] == 30
    assert run["annual_withdrawal"] == 0.0          # el monto fijo no entra: lo reemplaza la estrategia
    assert out["withdrawal_strategy"] == "constant_pct"
    assert out["assumption_sources"]["annual_withdrawal"] == "estrategia del plan"


def test_a_phased_plan_keeps_its_years_of_saving(project):
    plan = _plan(mc={"monthly_savings": 1500.0, "retirement_years": 12, "longevity_years": 25}, strategy=STRATEGY)
    _, run = project(plan)
    assert run["years_to_retirement"] == 12


def test_a_fixed_withdrawal_asked_by_the_model_replaces_the_plan_strategy_and_says_so(project):
    plan = _plan(mc={"monthly_savings": 1500.0, "retirement_years": 12, "longevity_years": 25}, strategy=STRATEGY)
    out, run = project(plan, annual_withdrawal=40_000)
    assert run["annual_withdrawal"] == 40_000.0
    assert run["withdrawal_strategy"] is None and run["years_to_retirement"] is None
    assert run["longevity_years"] is None
    assert any("estrategia de retiro" in note for note in out["plan_not_applied"])


def test_a_plan_without_a_strategy_passes_none_of_the_strategy_arguments(project):
    _, run = project(_plan(mc={"monthly_savings": 1500.0}))
    assert run["withdrawal_strategy"] is None and run["years_to_retirement"] is None
    assert run["longevity_years"] is None


def test_the_plan_drags_are_passed_to_the_engine(project):
    out, run = project(_plan(mc={"monthly_savings": 1500.0}, drags=DRAGS))
    assert run["drags"] == DRAGS
    assert out["drags_applied"] is True
    _, run = project(_plan(mc={"monthly_savings": 1500.0}))
    assert run["drags"] is None


def test_the_growth_of_the_withdrawal_and_of_the_savings_come_from_the_run(project):
    """Simulaciones pasa inflation_rate/100 y contribution_growth_pct/100: 3 % y 2 % son 0,03 y 0,02."""
    plan = _plan(mc={"monthly_savings": 1500.0, "inflation_rate": 3.0, "contribution_growth_pct": 2.0})
    _, run = project(plan)
    assert run["withdrawal_growth_rate"] == pytest.approx(0.03)
    assert run["contribution_growth_rate"] == pytest.approx(0.02)
    _, run = project(_plan(mc={"monthly_savings": 1500.0}))     # plan anterior: sin esas claves
    assert run["withdrawal_growth_rate"] == 0.0 and run["contribution_growth_rate"] == 0.0


def test_capital_and_horizon_come_from_the_run_before_the_profile(project):
    """Como al cargar el plan: la corrida manda sobre el perfil, para no mezclar dos planes."""
    plan = _plan(mc={"monthly_savings": 1500.0, "initial_value": 250_000, "horizon_years": 30},
                 personal={"current_capital": 200_000, "primary_horizon_years": 20})
    _, run = project(plan)
    assert run["initial_value"] == 250_000.0 and run["horizon_years"] == 30
    _, run = project(_plan(mc=None, personal={"current_capital": 200_000, "primary_horizon_years": 20}))
    assert run["initial_value"] == 200_000.0 and run["horizon_years"] == 20


def test_the_tool_tells_the_model_each_omitted_argument_comes_from_the_plan():
    spec = chat_tools.build_default_registry()["retirement_projection"]
    assert "omitilos para proyectar el plan tal como está" in spec.description
    for name in ("annual_withdrawal", "annual_contribution", "target_value"):
        assert "omitido = el del plan" in spec.parameters[name], name


def test_an_argument_that_is_not_a_number_falls_back_to_the_plan_and_says_so(project):
    plan = _plan(mc={"monthly_savings": 1500.0})
    out, run = project(plan, annual_contribution="mucho")
    assert run["annual_contribution"] == 18_000.0
    assert out["assumption_sources"]["annual_contribution"] == "plan"
