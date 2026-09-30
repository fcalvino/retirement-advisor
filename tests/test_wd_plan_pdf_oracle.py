"""Oráculo WD-PLAN-PDF: el aviso de WD-STRATEGY-CONTRIB viaja con la cifra.

Desde #203, con una estrategia de retiro activa el Monte Carlo deja afuera el ahorro
y lo dice en Simulaciones (`MonteCarloResult.contribution_ignored_by_strategy`,
`warnings`). Pero la cifra sale de esa pantalla: Mi Plan la muestra en vivo y al
guardarla, el PDF la imprime (tres llamadores: Plan, Optimizer, Simulaciones) y la
narrativa del plan se la pasa al modelo junto a «ahorro mensual $X». En ninguno de
esos lugares decía que el ahorro no estaba en los números. Banda 2.

Los planes guardados antes de esta fila no tienen la clave: los tres planes de
ejemplo y el que el usuario cargó de ellos combinan estrategia y ahorro. Para esos
el aviso es condicional —no se sabe qué ahorro tenía la corrida— y se apoya en el
ahorro del perfil del plan. Un plan con estrategia guardado desde ahora siempre
lleva la clave (0 cuando no quedó nada afuera), así que «sin clave» sólo significa
«anterior a WD-PLAN-PDF».
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from portfolio.monte_carlo import MonteCarloResult
from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)

AMOUNT = 24_000.0
KEY = "contribution_ignored_by_strategy"
STRATEGY = {"kind": "fixed_real", "annual_amount": 4_000.0}


def _mc(ignored: float = 0.0, strategy: bool = True) -> MonteCarloResult:
    mc = MonteCarloResult(
        n_sims=200, horizon_years=10, initial_value=100_000.0,
        annual_withdrawal=0.0, target_value=0.0,
        annual_contribution=ignored,
    )
    mc.median_terminal, mc.p10_terminal, mc.p90_terminal = 90_000.0, 60_000.0, 130_000.0
    if strategy:
        mc.withdrawal_strategy_applied = dict(STRATEGY)
        mc.prob_sustain_real_pct = 91.0
        mc.longevity_years = 30
    mc.contribution_ignored_by_strategy = ignored
    return mc


def _mentions(text: str) -> bool:
    return "no incluye tu ahorro" in text or "ese ahorro no está" in text


# --------------------------------------------------------------------------- #
#  El texto: una sola fuente para Plan, PDF y narrativa                        #
# --------------------------------------------------------------------------- #

def test_the_note_names_the_amount_left_out():
    from data.product_ux import strategy_ignored_savings_note

    note = strategy_ignored_savings_note(_mc(AMOUNT))
    assert note and "24,000" in note and "no incluye tu ahorro" in note
    assert strategy_ignored_savings_note({KEY: AMOUNT}) == note


@pytest.mark.parametrize("mc", [
    None,
    _mc(0.0),                                   # estrategia sin ahorro
    _mc(0.0, strategy=False),                   # acumulación
    {KEY: 0.0, "prob_sustain_real_pct": 90.0},  # plan nuevo, nada afuera
    {"median_terminal": 1.0},                   # plan viejo sin estrategia
])
def test_controls_have_no_note(mc):
    from data.product_ux import strategy_ignored_savings_note

    assert strategy_ignored_savings_note(mc, monthly_savings=2_000.0) is None


def test_a_plan_saved_before_the_key_gets_a_conditional_note():
    from data.product_ux import strategy_ignored_savings_note

    legacy = {"prob_sustain_real_pct": 84.0, "median_terminal": 780_000.0}
    note = strategy_ignored_savings_note(legacy, monthly_savings=1_200.0)
    assert note and "ese ahorro no está" in note and "14,400" in note
    assert strategy_ignored_savings_note(legacy, monthly_savings=0.0) is None


# --------------------------------------------------------------------------- #
#  El plan guardado lleva la clave                                            #
# --------------------------------------------------------------------------- #

def _save(mc):
    from data.plan_store import PlanSnapshot

    opt = SimpleNamespace(profile_name="Moderado", tickers=[], sector_weights={})
    return PlanSnapshot.from_session(
        name="Plan test", opt_result=opt, goals=[], mc_result=mc,
        mc_params={"horizon_years": 10, "initial_value": 100_000.0},
        withdrawal_strategy=dict(STRATEGY),
    )


def test_a_saved_plan_records_the_savings_left_out():
    assert _save(_mc(AMOUNT)).mc_summary[KEY] == pytest.approx(AMOUNT)


def test_a_saved_strategy_plan_records_zero_when_nothing_was_left_out():
    """Así «sin clave» queda reservado para los planes anteriores a la fila."""
    assert _save(_mc(0.0)).mc_summary[KEY] == 0.0


def test_an_accumulation_plan_does_not_gain_the_key():
    assert KEY not in _save(_mc(0.0, strategy=False)).mc_summary


# --------------------------------------------------------------------------- #
#  El PDF: la sección de riesgo lo dice (vale para sus tres llamadores)        #
# --------------------------------------------------------------------------- #

def _risk_texts(mc) -> str:
    from reportlab.platypus import Paragraph

    from reports.investment_plan import InvestmentPlanReport, ReportOptions, _styles

    flows = InvestmentPlanReport()._section_risk(
        _styles(), mc, {"horizon_years": 10}, ReportOptions(include_charts=False),
    )
    return "\n".join(f.getPlainText() for f in flows if isinstance(f, Paragraph))


def test_the_pdf_says_the_savings_were_left_out():
    assert _mentions(_risk_texts(_mc(AMOUNT)))


def test_control_the_pdf_of_a_strategy_without_savings_does_not():
    assert not _mentions(_risk_texts(_mc(0.0)))


def test_the_pdf_summary_page_says_it_too():
    """La mediana y el P10 también salen en el resumen ejecutivo de la página 1."""
    from reportlab.platypus import Paragraph

    from reports.investment_plan import InvestmentPlanReport, ReportOptions, _styles

    def summary(mc):
        flows = InvestmentPlanReport()._section_executive_summary(
            _styles(), None, None, mc, {"horizon_years": 10}, "", ReportOptions(),
        )
        return "\n".join(f.getPlainText() for f in flows if isinstance(f, Paragraph))

    assert _mentions(summary(_mc(AMOUNT)))
    assert not _mentions(summary(_mc(0.0)))


# --------------------------------------------------------------------------- #
#  La narrativa del plan: el modelo no puede decir que el ahorro está          #
# --------------------------------------------------------------------------- #

def _prompt(mc_summary, monthly_savings=2_000.0) -> str:
    from analysis.prompts import plan_level_narrative_prompt

    return plan_level_narrative_prompt(
        plan_name="Plan", profile_name="Moderado",
        personal={"monthly_savings": monthly_savings},
        metrics={}, core_holdings=[], allocation=[], sector_weights={}, goals=[],
        mc_summary=mc_summary, withdrawal_strategy=dict(STRATEGY),
    )


def test_the_narrative_prompt_is_told_the_savings_are_not_in_the_numbers():
    assert _mentions(_prompt({KEY: AMOUNT, "prob_sustain_real_pct": 90.0}))


def test_control_the_narrative_prompt_without_ignored_savings_is_unchanged():
    assert not _mentions(_prompt({KEY: 0.0, "prob_sustain_real_pct": 90.0}))


# --------------------------------------------------------------------------- #
#  Mi Plan: en vivo y el plan guardado                                        #
# --------------------------------------------------------------------------- #

@pytest.fixture
def plan_page(stores):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    from portfolio.optimizer import OptimizationResult, TickerAllocation
    from tests.test_plan_page_runtime import PAGE, _FakePrefs

    opt = OptimizationResult(
        profile_name="Moderado", method="mean-variance",
        tickers=[TickerAllocation("AAPL", 100.0, 7.0, 20.0, 0.5, 80.0, 5.0, "Technology")],
    )

    def open_page(mc=None, with_opt=False):
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["user_prefs"] = _FakePrefs()
        if with_opt:
            at.session_state["optimizer_result"] = opt
        if mc is not None:
            at.session_state["mc_result"] = mc
        at.run()
        assert not at.exception, [str(e) for e in at.exception]
        return at

    return open_page


def _page_text(at) -> str:
    from tests.test_plan_page_runtime import _all_text

    return _all_text(at)


def test_the_live_plan_says_the_savings_were_left_out(plan_page):
    assert _mentions(_page_text(plan_page(_mc(AMOUNT), with_opt=True)))


def test_control_the_live_plan_without_ignored_savings(plan_page):
    assert not _mentions(_page_text(plan_page(_mc(0.0), with_opt=True)))


def _saved(store_ns, mc_summary, monthly_savings=2_000.0):
    from tests.test_plan_page_runtime import _snap

    snap = _snap()
    snap.mc_summary = dict(snap.mc_summary, **mc_summary)
    snap.withdrawal_strategy = dict(STRATEGY)
    snap.personal = {"monthly_savings": monthly_savings}
    store_ns.plans.upsert(snap)
    return snap


def _open_saved(plan_page, snap):
    at = plan_page()
    at.button(key=f"view_{snap.id}").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def test_a_saved_plan_says_the_savings_were_left_out(stores, plan_page):  # noqa: F811
    snap = _saved(stores, {KEY: AMOUNT, "prob_sustain_real_pct": 90.0})
    assert _mentions(_page_text(_open_saved(plan_page, snap)))


def test_a_plan_saved_before_the_key_says_it_conditionally(stores, plan_page):  # noqa: F811
    snap = _saved(stores, {"prob_sustain_real_pct": 90.0})
    assert "ese ahorro no está" in _page_text(_open_saved(plan_page, snap))


def test_control_a_saved_strategy_plan_with_nothing_left_out(stores, plan_page):  # noqa: F811
    snap = _saved(stores, {KEY: 0.0, "prob_sustain_real_pct": 90.0})
    assert not _mentions(_page_text(_open_saved(plan_page, snap)))
