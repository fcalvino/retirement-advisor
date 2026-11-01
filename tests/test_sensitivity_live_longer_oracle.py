"""AUDIT-NUMB-5 — «Vivir 5 años más» no se mide en un plan que no retira nada.

La palanca suma ``longevity_delta_years`` a ``horizon_years`` y a ``longevity_years``. En un plan
de acumulación (sin estrategia de retiro ni retiro anual) eso son cinco años más de ahorro y de
rendimiento con la meta fija: el escenario rotulado «riesgo de longevidad» **mejoraba** todo
(medido con el motor real: P10 213 180 → 256 404 a 25 años; mediana 389 654 → 494 218). Vivir más no
puede ser una buena noticia para quien no retira: ahí el escenario no aplica, y la pantalla lo dice
en vez de mostrar un delta positivo o un $0.

Regla: ``live_longer`` exige retiros (``withdrawal_tuple`` no es ``None`` o ``annual_withdrawal`` > 0).
Sin ellos devuelve ``ScenarioResult(applies=False, metrics={}, deltas={})`` con la razón, y no corre
la simulación. Los otros tres escenarios no cambian. Corredor inyectado: sin red ni Monte Carlo.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from config import SENSITIVITY
from portfolio.sensitivity import run_sensitivity


def _recording_runner():
    """Surrogate that behaves like the real engine in the two regimes that matter.

    - No withdrawals: the pot only compounds, so more horizon → MORE terminal (the defect).
    - With withdrawals: more horizon → LESS terminal and more ruin (longevity risk).
    """
    calls: list[dict] = []

    def run(params: dict):
        calls.append(dict(params))
        years = float(params["horizon_years"])
        # Independent of the lab's own rule: a strategy replaces the annual amount; a phased one
        # (years_to_retirement) withdraws nothing inside a horizon that ends before it starts.
        if params.get("withdrawal_tuple"):
            retires = not params.get("years_to_retirement") or params["years_to_retirement"] < params["horizon_years"]
        else:
            retires = float(params.get("annual_withdrawal") or 0) > 0
        if retires:
            median = 800_000.0 - 20_000.0 * years
            ruin = 2.0 * years
        else:
            median = 100_000.0 * 1.07 ** years
            ruin = 0.0
        return SimpleNamespace(
            p10_terminal=median * 0.5, median_terminal=median, p90_terminal=median * 1.6, prob_ruin_pct=ruin
        )

    return run, calls


def _accumulation(**over):
    base = {
        "horizon_years": 20,
        "longevity_years": None,
        "withdrawal_tuple": None,
        "annual_withdrawal": 0.0,
        "annual_contribution": 12_000.0,
        "withdrawal_growth_rate": 0.03,
        "drags_total_pct": 0.25,
        "return_scale": 1.0,
        "vol_scale": 1.0,
    }
    base.update(over)
    return base


def _scenario(res, key):
    return next(s for s in res.scenarios if s.key == key)


def test_the_precondition_the_old_lever_made_an_accumulation_plan_richer():
    """Why this matters: with nothing withdrawn, 25 years is better than 20 on every metric."""
    run, _ = _recording_runner()
    short, long_ = run(_accumulation()), run(_accumulation(horizon_years=25))
    assert long_.median_terminal > short.median_terminal and long_.p10_terminal > short.p10_terminal


@pytest.mark.parametrize("annual_withdrawal", [0.0, 0, None])
@pytest.mark.parametrize("withdrawal_tuple", [None, ()])      # () is "no strategy" for the engine too
def test_a_plan_with_no_withdrawals_does_not_measure_living_longer(annual_withdrawal, withdrawal_tuple):
    run, calls = _recording_runner()
    res = run_sensitivity(run, _accumulation(annual_withdrawal=annual_withdrawal, withdrawal_tuple=withdrawal_tuple))
    sc = _scenario(res, "live_longer")
    assert sc.applies is False
    assert sc.metrics == {} and sc.deltas == {}
    # Not measured at all: no run with the extended horizon exists.
    assert all(c["horizon_years"] != 20 + SENSITIVITY.longevity_delta_years for c in calls)
    assert "retiros" in sc.reason


def test_the_lever_keeps_its_slot_and_label_so_the_table_can_say_it_does_not_apply():
    run, _ = _recording_runner()
    res = run_sensitivity(run, _accumulation())
    sc = _scenario(res, "live_longer")
    assert sc.label == f"Vivir {SENSITIVITY.longevity_delta_years} años más"
    assert sc.description
    assert len(res.scenarios) == 4


def test_a_plan_with_an_annual_withdrawal_measures_it_as_before():
    run, calls = _recording_runner()
    res = run_sensitivity(run, _accumulation(annual_withdrawal=30_000.0))
    sc = _scenario(res, "live_longer")
    assert sc.applies is True and sc.reason == ""
    plus = 20 + SENSITIVITY.longevity_delta_years
    assert sc.metrics["median_terminal"] == pytest.approx(800_000.0 - 20_000.0 * plus)
    assert sc.deltas["median_terminal"] == pytest.approx(-20_000.0 * SENSITIVITY.longevity_delta_years)
    assert sc.deltas["prob_ruin_pct"] > 0                # living longer is worse here
    assert any(c["horizon_years"] == plus for c in calls)


def test_a_plan_with_a_withdrawal_strategy_measures_it_even_with_a_zero_annual_amount():
    """The strategy carries the spending; ``annual_withdrawal`` is 0 there."""
    run, _ = _recording_runner()
    res = run_sensitivity(run, _accumulation(withdrawal_tuple=(("method", "constant_pct"),), longevity_years=30))
    sc = _scenario(res, "live_longer")
    assert sc.applies is True and sc.deltas["median_terminal"] < 0


def test_a_phased_plan_that_retires_after_the_horizon_does_not_measure_it_either():
    """H=20, retirement in 25: the terminal is read before the first withdrawal (the engine's own rule)."""
    run, calls = _recording_runner()
    strategy = (("method", "fixed_real"), ("annual", 30_000))
    res = run_sensitivity(run, _accumulation(withdrawal_tuple=strategy, years_to_retirement=25))
    sc = _scenario(res, "live_longer")
    assert sc.applies is False and sc.metrics == {} and sc.deltas == {}
    assert "después del horizonte" in sc.reason
    assert all(c["horizon_years"] != 20 + SENSITIVITY.longevity_delta_years for c in calls)
    # Retirement starting exactly at the horizon withdraws nothing inside it either.
    at_h = run_sensitivity(run, _accumulation(withdrawal_tuple=strategy, years_to_retirement=20))
    assert _scenario(at_h, "live_longer").applies is False


def test_a_phased_plan_that_retires_inside_the_horizon_is_measured():
    run, _ = _recording_runner()
    strategy = (("method", "fixed_real"), ("annual", 30_000))
    res = run_sensitivity(run, _accumulation(withdrawal_tuple=strategy, years_to_retirement=15))
    sc = _scenario(res, "live_longer")
    assert sc.applies is True and sc.deltas["median_terminal"] < 0


def test_a_strategy_replaces_the_annual_amount():
    """With a phased strategy that starts after the horizon, ``annual_withdrawal`` is not spent."""
    run, _ = _recording_runner()
    res = run_sensitivity(run, _accumulation(
        annual_withdrawal=30_000.0, withdrawal_tuple=(("method", "fixed_real"),), years_to_retirement=30))
    assert _scenario(res, "live_longer").applies is False


def test_the_other_scenarios_are_unchanged_on_an_accumulation_plan():
    run, _ = _recording_runner()
    res = run_sensitivity(run, _accumulation())
    for key in ("inflation_hot", "drags_full", "adverse_market"):
        sc = _scenario(res, key)
        assert sc.metrics and sc.deltas, key               # they ran
        assert set(sc.deltas) == set(res.base), key


# --- la tabla de la pantalla ----------------------------------------------------------------------

def _rows(res, metric="median_terminal"):
    from data.product_ux import sensitivity_scenario_rows

    return sensitivity_scenario_rows(
        res.scenarios, metric, "Caso más probable (mediana)", lambda v: f"${v:,.0f}", "no aplica a este plan"
    )


def test_the_table_shows_dashes_and_the_reason_not_zero_dollars():
    run, _ = _recording_runner()
    row = next(r for r in _rows(run_sensitivity(run, _accumulation())) if r["Escenario"].startswith("Vivir"))
    assert row["Caso más probable (mediana)"] == "—"            # not "$0"
    assert row["Δ vs base"] == "no aplica a este plan"
    assert "No se mide: tu plan no tiene retiros" in row["Qué cambia"]      # the wide column, not the delta cell
    assert "$0" not in "".join(str(v) for v in row.values())


def test_the_table_keeps_formatting_the_scenarios_that_were_measured():
    run, _ = _recording_runner()
    res = run_sensitivity(run, _accumulation(annual_withdrawal=30_000.0))
    row = next(r for r in _rows(res) if r["Escenario"].startswith("Vivir"))
    assert row["Caso más probable (mediana)"] == f"${_scenario(res, 'live_longer').metrics['median_terminal']:,.0f}"
    assert "-" in row["Δ vs base"]                       # a loss, as the old table printed it
