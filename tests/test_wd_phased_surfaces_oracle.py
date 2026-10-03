"""Oráculo WD-PHASED PR 2 — las superficies describen y reproducen el plan por fases.

El PR 1 (#219) hizo que el motor ahorre hasta la edad de retiro y gaste
después, pero sólo Simulaciones lo usaba. Verificado en ``b3441aa``:

* un plan cargado corría con el R del perfil **actual**, no con el suyo:
  ``mc_summary.retirement_years`` se guardaba y nadie lo leía;
* Mi Plan, el PDF, la narrativa y la métrica de Simulaciones decían «dure {L}
  años» y «año X», con L contado desde el retiro y X desde hoy, sin decirlo;
* la narrativa describía los retiros como si empezaran hoy;
* la ayuda de «Retiro anual» decía «el primer año», y con fases el monto está en
  dólares de hoy;
* los planes de ejemplo traen estrategia y edad de retiro por delante, pero no R.

Decisiones del usuario (2026-10-03): el plan cargado corre con su R guardado y un
aviso dice si el perfil da otro, con un botón para volver al perfil; sin la clave
el plan es «ya retirado»; los rótulos van como edad cuando hay edad y, si no, en
años con «desde el retiro» / «desde hoy»; los ejemplos reciben su R.

La referencia de los rótulos es la definición: el retiro empieza a los
``edad + R`` —el R con que corrió el plan, no la edad de retiro del perfil, que
un plan cargado puede no compartir— y el agotamiento, contado desde hoy, cae a
los ``edad + X``. Ningún número del motor cambia.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from portfolio.monte_carlo import MonteCarloResult
from tests.test_plan_load_savings_oracle import (
    _execute,
    _load,
    _ok,
    _session,
    _set,
    _sim,
)
from tests.test_plan_page_runtime import _all_text, stores  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
STRATEGY = {"kind": "fixed_real", "annual_amount": 4_000.0}

AGE, R, L, X = 40, 25, 30, 47
SPAN_AGE = "de los 65 a los 95"
DEPLETION_AGE = "a los 87"
SPAN_YEARS = "30 años desde el retiro, que empieza en 25 años"
DEPLETION_YEARS = "en el año 47 desde hoy"


# --------------------------------------------------------------------------- #
#  Los rótulos: un helper, la definición                                       #
# --------------------------------------------------------------------------- #

def test_span_as_age_from_the_run_retirement():
    from data.product_ux import decumulation_span_text

    assert decumulation_span_text(L, R, age=AGE) == SPAN_AGE
    assert decumulation_span_text(L, 0, age=70) == "de los 70 a los 100"


def test_span_without_age_says_from_when():
    from data.product_ux import decumulation_span_text

    assert decumulation_span_text(L, R) == SPAN_YEARS
    assert decumulation_span_text(L, 0) == "30 años desde hoy"
    assert decumulation_span_text(L, R, age=0) == SPAN_YEARS


def test_depletion_is_counted_from_today():
    from data.product_ux import depletion_text

    assert depletion_text(X, age=AGE) == DEPLETION_AGE
    assert depletion_text(X) == DEPLETION_YEARS
    assert depletion_text(46.6, age=AGE) == "a los 87"


# --------------------------------------------------------------------------- #
#  El aviso del plan cargado                                                   #
# --------------------------------------------------------------------------- #

def test_note_when_the_plan_and_the_profile_differ():
    from data.product_ux import loaded_plan_saving_years_note

    note = loaded_plan_saving_years_note(10, 20, profile_has_age=True)
    assert "retiro en 10 años, como se guardó" in note and "tu perfil hoy da 20 años" in note


@pytest.mark.parametrize(("plan", "profile", "has_age", "expected"), [
    (0, 20, True, "se guardó ya retirado"),
    (10, 0, False, "tu perfil no tiene edad de retiro"),
    (10, 0, True, "según tu perfil ya estás retirado"),
])
def test_note_in_its_degenerate_cases(plan, profile, has_age, expected):
    from data.product_ux import loaded_plan_saving_years_note

    assert expected in loaded_plan_saving_years_note(plan, profile, profile_has_age=has_age)


def test_no_note_when_they_agree():
    from data.product_ux import loaded_plan_saving_years_note

    assert loaded_plan_saving_years_note(20, 20, profile_has_age=True) is None
    assert loaded_plan_saving_years_note(0, 0, profile_has_age=False) is None


# --------------------------------------------------------------------------- #
#  Cargar un plan siembra su R                                                 #
# --------------------------------------------------------------------------- #

def _snap(strategy=STRATEGY, **mc):
    return SimpleNamespace(
        mc_summary=dict({"longevity_years": L}, **mc) if mc is not None else None,
        withdrawal_strategy=strategy, drags_at_save=None,
    )


@pytest.mark.parametrize(("snap", "expected"), [
    (_snap(retirement_years=10), 10),
    (_snap(), 0),                                                       # sin la clave: ya retirado
    (_snap(strategy=None, run_assumptions_from_run=True), None),        # sin estrategia
    (_snap(strategy={"kind": "fixed_real", "annual_amount": 0.0},
           retirement_years=10), None),                                 # estrategia rechazada
    (SimpleNamespace(mc_summary=None, withdrawal_strategy=None, drags_at_save=None), None),
])
def test_loading_seeds_the_plan_retirement_years(snap, expected):
    from data.product_ux import LOADED_PLAN_RETIREMENT_KEY, plan_load_run_assumptions

    updates, _ = plan_load_run_assumptions(snap)
    assert LOADED_PLAN_RETIREMENT_KEY in updates, "siempre se escribe: un R viejo no sobrevive"
    assert updates[LOADED_PLAN_RETIREMENT_KEY] == expected


@pytest.mark.parametrize(("key", "expected"), [
    ("conservador_30y", 20), ("fire_moderado", 18), ("retiro_ar_adrs", 15),
])
def test_sample_plans_carry_their_retirement_years(key, expected):
    """Edad de retiro − edad de su perfil: cargan como plan por fases."""
    from data.plan_context import load_sample_plan
    from data.product_ux import LOADED_PLAN_RETIREMENT_KEY, plan_load_run_assumptions

    raw = json.loads((ROOT / "data/sample_plans" / f"{key}.json").read_text(encoding="utf-8"))
    assert expected == raw["personal"]["retirement_age"] - raw["personal"]["age"]
    updates, _ = plan_load_run_assumptions(load_sample_plan(key))
    assert updates[LOADED_PLAN_RETIREMENT_KEY] == expected


def test_a_phased_plan_without_the_ignored_key_is_not_told_savings_are_out():
    """La nota condicional de WD-PLAN-PDF supone «ya retirado»; un plan con R lo
    contradice: su ahorro sí entró."""
    from data.product_ux import strategy_ignored_savings_note

    phased = {"prob_sustain_real_pct": 84.0, "retirement_years": 18}
    assert strategy_ignored_savings_note(phased, monthly_savings=1_200.0) is None
    assert strategy_ignored_savings_note(
        {"prob_sustain_real_pct": 84.0, "retirement_years": 0}, monthly_savings=1_200.0
    )


# --------------------------------------------------------------------------- #
#  Simulaciones corre el plan cargado con su R (la app real, una sesión)       #
# --------------------------------------------------------------------------- #

def _with_strategy(at):
    """«Retiro fijo real» elegido en el selectbox, como lo haría el usuario."""
    _set(at, at.selectbox(key="sim_wd_kind"), "fixed_real")
    return at


def _strategy_plan(stores, retirement_years):  # noqa: F811
    from tests.test_plan_page_runtime import _snap as _base

    snap = _base()
    snap.withdrawal_strategy = dict(STRATEGY)
    snap.mc_summary = dict(snap.mc_summary, longevity_years=L,
                           retirement_years=retirement_years, prob_sustain_real_pct=90.0)
    stores.plans.upsert(snap)
    return snap


def test_a_loaded_plan_runs_with_its_own_retirement_years(stores):  # noqa: F811
    # perfil: 40 → 60, R = 20; el plan se guardó con R = 10
    at = _session(stores)
    at = _load(at, _strategy_plan(stores, 10))
    text = _all_text(at)
    assert "retiro en 10 años, como se guardó" in text and "tu perfil hoy da 20 años" in text
    assert _execute(at).retirement_years == 10

    at.button(key="sim_use_profile_retirement").click().run()
    _ok(at)
    assert "como se guardó" not in _all_text(at)
    assert _execute(at).retirement_years == 20


def test_control_a_plan_with_the_profile_retirement_has_no_note(stores):  # noqa: F811
    at = _load(_session(stores), _strategy_plan(stores, 20))
    assert "como se guardó" not in _all_text(at)
    assert _execute(at).retirement_years == 20


def test_without_a_loaded_plan_the_profile_rules(stores):  # noqa: F811
    at = _with_strategy(_sim(_session(stores)))
    assert _execute(at).retirement_years == 20


# --------------------------------------------------------------------------- #
#  Simulaciones: la métrica y la ayuda de «Retiro anual»                       #
# --------------------------------------------------------------------------- #

def test_simulaciones_labels_the_income_span_as_age(stores):  # noqa: F811
    at = _with_strategy(_sim(_session(stores)))
    _execute(at)
    labels = [m.label for m in at.metric]
    assert "Prob. de que dure de los 60 a los 90" in labels, labels


def test_the_withdrawal_help_says_todays_dollars(stores):  # noqa: F811
    at = _with_strategy(_sim(_session(stores)))
    helps = [w.help or "" for w in at.number_input if w.key == "sim_wd_amount"]
    assert helps and "dólares de hoy" in helps[0] and "al retirarte" in helps[0]
    assert "el primer año" not in helps[0]


# --------------------------------------------------------------------------- #
#  Mi Plan: el plan guardado                                                   #
# --------------------------------------------------------------------------- #

def _saved_phased(stores, personal):  # noqa: F811
    from tests.test_plan_page_runtime import _snap as _base

    snap = _base()
    snap.withdrawal_strategy = dict(STRATEGY)
    snap.mc_summary = dict(
        snap.mc_summary, longevity_years=L, retirement_years=R,
        prob_sustain_real_pct=80.0, median_legacy=1.0, expected_depletion_year=float(X),
        contribution_ignored_by_strategy=0.0,
    )
    snap.personal = personal
    stores.plans.upsert(snap)
    return snap


@pytest.fixture
def plan_page(stores):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    from tests.test_plan_page_runtime import PAGE, _FakePrefs

    def open_saved(snap):
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["user_prefs"] = _FakePrefs()
        at.run()
        at.button(key=f"view_{snap.id}").click().run()
        assert not at.exception, [str(e) for e in at.exception]
        return _all_text(at)

    return open_saved


def test_mi_plan_labels_as_age(stores, plan_page):  # noqa: F811
    text = plan_page(_saved_phased(stores, {"age": AGE, "retirement_age": 65}))
    assert f"dure {SPAN_AGE}" in text and f"se agota típicamente {DEPLETION_AGE}" in text


def test_mi_plan_without_age_says_from_when(stores, plan_page):  # noqa: F811
    text = plan_page(_saved_phased(stores, {"monthly_savings": 1_000.0}))
    assert f"dure {SPAN_YEARS}" in text and f"se agota típicamente {DEPLETION_YEARS}" in text


# --------------------------------------------------------------------------- #
#  El PDF                                                                      #
# --------------------------------------------------------------------------- #

def _mc_phased() -> MonteCarloResult:
    mc = MonteCarloResult(n_sims=200, horizon_years=20, initial_value=100_000.0,
                          annual_withdrawal=0.0, target_value=0.0)
    mc.median_terminal, mc.p10_terminal, mc.p90_terminal = 900_000.0, 600_000.0, 1_300_000.0
    mc.withdrawal_strategy_applied = dict(STRATEGY)
    mc.prob_sustain_real_pct, mc.longevity_years = 80.0, L
    mc.retirement_years, mc.expected_depletion_year = R, float(X)
    return mc


def _pdf_risk_text(mc_params) -> str:
    from reportlab.platypus import Paragraph, Table

    from reports.investment_plan import InvestmentPlanReport, ReportOptions, _styles

    out = []
    for f in InvestmentPlanReport()._section_risk(
        _styles(), _mc_phased(), mc_params, ReportOptions(include_charts=False),
    ):
        if isinstance(f, Paragraph):
            out.append(f.getPlainText())
        elif isinstance(f, Table):
            out += [c.getPlainText() if isinstance(c, Paragraph) else str(c)
                    for row in f._cellvalues for c in row]
    return "\n".join(out)


def test_the_pdf_labels_as_age():
    text = _pdf_risk_text({"horizon_years": 20, "age": AGE})
    assert f"Prob. de que el ingreso dure {SPAN_AGE}" in text and DEPLETION_AGE in text


def test_the_pdf_without_age_says_from_when():
    text = _pdf_risk_text({"horizon_years": 20})
    assert f"Prob. de que el ingreso dure {SPAN_YEARS}" in text and DEPLETION_YEARS in text


def test_the_pdf_params_carry_the_age_of_the_profile():
    from data.preferences import UserPreferences
    from data.product_ux import enrich_pdf_mc_params

    prefs = UserPreferences(onboarded=True, age=AGE, retirement_age=65)
    assert enrich_pdf_mc_params({}, prefs=prefs)["age"] == AGE
    assert enrich_pdf_mc_params({}, personal={"age": 52})["age"] == 52
    assert "age" not in enrich_pdf_mc_params({}, prefs=UserPreferences())


# --------------------------------------------------------------------------- #
#  La narrativa del plan                                                       #
# --------------------------------------------------------------------------- #

def _prompt(retirement_years: int, personal=None, strategy=None) -> str:
    from analysis.prompts import plan_level_narrative_prompt

    return plan_level_narrative_prompt(
        plan_name="Plan", profile_name="Moderado",
        personal=personal if personal is not None else {"age": AGE, "retirement_age": 65},
        metrics={}, core_holdings=[], allocation=[], sector_weights={}, goals=[],
        mc_summary={"longevity_years": L, "retirement_years": retirement_years,
                    "prob_sustain_real_pct": 80.0, "expected_depletion_year": float(X),
                    "contribution_ignored_by_strategy": 0.0},
        withdrawal_strategy=dict(strategy or STRATEGY),
    )


def test_the_narrative_names_the_saving_phase():
    text = _prompt(R)
    assert "FASE DE AHORRO" in text and "ahorra 25 años (hasta los 65)" in text
    assert "dólares de hoy" in text and "25 años de inflación" in text
    assert f"dure {SPAN_AGE}" in text and DEPLETION_AGE in text


def test_control_an_already_retired_plan_has_no_saving_phase():
    text = _prompt(0, personal={"age": 70, "retirement_age": 65})
    assert "FASE DE AHORRO" not in text
    assert "dure de los 70 a los 100" in text


def test_the_narrative_without_age_says_from_when():
    text = _prompt(R, personal={})
    assert f"dure {SPAN_YEARS}" in text and DEPLETION_YEARS in text


@pytest.mark.parametrize("strategy", [
    {"kind": "constant_pct", "pct": 0.04},
    {"kind": "guardrails", "pct": 0.05},
])
def test_only_the_fixed_withdrawal_is_said_in_todays_dollars(strategy):
    """Un porcentaje sale del pozo de cada camino: no tiene monto en dólares de hoy."""
    text = _prompt(R, strategy=strategy)
    assert "FASE DE AHORRO" in text and "ahorra 25 años (hasta los 65)" in text
    assert "dólares de hoy" not in text
