"""Oráculo PLAN-SAVE-PARAMS: un plan lleva los parámetros de la corrida que lo produjo.

Mi Plan guarda y exporta el Monte Carlo con `_session_mc_params()`, que armaba los
parámetros desde las **claves de los widgets** de Simulaciones (`horizon_years`,
`inflation_rate`, `target_value`, …). Streamlit borra esas claves cuando la página
de Simulaciones deja de dibujarse, así que en Mi Plan casi nunca estaban, y la
corrida real —`st.session_state["mc_params"]`, escrito junto a `mc_result`— no se
leía. Cuatro síntomas, uno por test en rojo contra `origin/main` (`1853cdf`):

1. La suba del ahorro (N8b) no se guardaba nunca: `assemble_plan_pdf_mc_params` no
   la llevaba, y el oráculo de N8b probaba `from_session` con un dict a mano.
2. El horizonte salía del perfil (24 años) y no de la corrida (20), o `None` si el
   perfil no tenía edad («Horizonte Nonea»).
3. La inflación quedaba en `None` y la conversión a pesos decía que no podía.
4. El PDF recibía el horizonte del perfil como `float` y el fan chart caía en un
   `try` y desaparecía sin aviso.

Los tests de la página corren `12_Plan.py` real con AppTest y leen el JSON que
escribe el botón «Guardar»: el agujero de N8b fue probar el helper y no la página.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from portfolio.monte_carlo import MonteCarloResult
from tests.test_plan_page_runtime import PAGE, _FakePrefs, stores  # noqa: F401  (fixture)

# La corrida: lo que `7_Simulaciones.py` deja en `st.session_state["mc_params"]`.
RUN = {
    "horizon_years": 20,
    "initial_value": 250_000,
    "inflation_rate": 2.5,
    "contribution_growth_pct": 3.0,
    "target_value": 900_000,
    "annual_withdrawal": 0,
    "monthly_savings": 1_500,      # el perfil (`_FakePrefs`) dice 500
    "annual_contribution": 18_000,
    "n_sims": 1_000,
    "drags": {"enabled": True, "fee_pct": 1.25, "total_annual_drag_pct": 1.25},
    "withdrawal_strategy": None,
}
PROFILE_HORIZON = 24   # el perfil dice otra cosa que la corrida, a propósito


class _Prefs(_FakePrefs):
    primary_horizon_years = PROFILE_HORIZON


class _PrefsWithoutAge(_FakePrefs):
    primary_horizon_years = 0   # perfil incompleto: `UserPreferences` da 0


def _mc() -> MonteCarloResult:
    mc = MonteCarloResult(
        n_sims=RUN["n_sims"], horizon_years=RUN["horizon_years"],
        initial_value=float(RUN["initial_value"]), annual_withdrawal=0.0,
        target_value=float(RUN["target_value"]),
    )
    mc.median_terminal, mc.p10_terminal, mc.p90_terminal = 1_200_000.0, 700_000.0, 2_000_000.0
    mc.prob_achieve_target_pct = 71.0
    # La forma real del motor: {año: {percentil: valor}} (`MonteCarloSimulator._fan_paths`).
    mc.fan_paths = {
        y: {p: 250_000.0 * (1.0 + 0.004 * p) ** y for p in (5, 10, 25, 50, 75, 90, 95)}
        for y in range(RUN["horizon_years"] + 1)
    }
    return mc


def _opt():
    from portfolio.optimizer import OptimizationResult, TickerAllocation

    return OptimizationResult(
        profile_name="Moderado", method="mean-variance",
        tickers=[TickerAllocation("AAPL", 100.0, 7.0, 20.0, 0.5, 80.0, 5.0, "Technology")],
    )


def _open(prefs, *, run=True, widgets=None) -> AppTest:
    """Mi Plan después de pasar por Simulaciones: hay corrida y (por defecto) no
    quedan claves de widget, que es como llega la sesión al cambiar de página."""
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["optimizer_result"] = _opt()
    if run:
        at.session_state["mc_result"] = _mc()
        at.session_state["mc_params"] = dict(RUN)
    for k, v in (widgets or {}).items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def _save(stores, prefs, **kw):  # noqa: F811
    at = _open(prefs, **kw)
    at.button(key="plan_save_btn").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    plans = stores.plans.list()
    assert len(plans) == 1
    return plans[0]


# --------------------------------------------------------------------------- #
#  El plan guardado lleva la corrida                                          #
# --------------------------------------------------------------------------- #

def test_the_saved_plan_carries_the_run_not_the_profile(stores):  # noqa: F811
    m = _save(stores, _Prefs()).mc_summary
    assert m["horizon_years"] == RUN["horizon_years"]            # main: 24.0 (perfil)
    assert m["inflation_rate"] == RUN["inflation_rate"]          # main: None
    assert m["contribution_growth_pct"] == RUN["contribution_growth_pct"]   # main: None
    assert m["target_value"] == RUN["target_value"]              # main: None


def test_the_run_wins_over_widgets_left_with_other_values(stores):  # noqa: F811
    """Si los widgets siguen vivos pero cambiaron después de correr, los números
    guardados son los de la corrida: el plan describe lo que se calculó."""
    m = _save(stores, _Prefs(), widgets={
        "horizon_years": 30, "inflation_rate": 4.0,
        "target_value": 500_000, "contribution_growth_pct": 0.0,
    }).mc_summary
    assert m["horizon_years"] == RUN["horizon_years"]
    assert m["inflation_rate"] == RUN["inflation_rate"]
    assert m["target_value"] == RUN["target_value"]
    assert m["contribution_growth_pct"] == RUN["contribution_growth_pct"]


def test_a_profile_without_age_still_saves_the_run_horizon(stores):  # noqa: F811
    m = _save(stores, _PrefsWithoutAge()).mc_summary
    assert m["horizon_years"] == RUN["horizon_years"]            # main: None («Nonea»)


def test_loading_the_saved_plan_brings_the_savings_raise_back(stores):  # noqa: F811
    from data.product_ux import plan_load_session_updates

    snap = _save(stores, _Prefs())
    updates = plan_load_session_updates(snap, horizon_years=RUN["horizon_years"])
    assert updates.get("contribution_growth_pct") == RUN["contribution_growth_pct"]
    assert updates.get("inflation_rate") == RUN["inflation_rate"]
    assert updates.get("target_value") == RUN["target_value"]


def test_the_saved_plan_can_be_spoken_about_in_pesos(stores):  # noqa: F811
    from config import AR_FX
    from data.product_ux import ar_dual_context

    m = _save(stores, _Prefs()).mc_summary
    fx = ar_dual_context(
        float(m["median_terminal"]), fx_config=AR_FX, label="mediana del plan",
        horizon_years=m["horizon_years"], usd_inflation_pct=m["inflation_rate"],
    )
    assert fx["available"], fx["reason"]                         # main: falta la inflación


# --------------------------------------------------------------------------- #
#  El PDF de Mi Plan                                                          #
# --------------------------------------------------------------------------- #

def test_the_saved_plan_records_the_runs_drags_not_the_sessions(stores):  # noqa: F811
    """Los supuestos guardados son los de la corrida detrás de `mc_summary`: la
    sesión de ahora (drags por defecto) puede no ser la que se simuló."""
    assert _save(stores, _Prefs()).drags_at_save == RUN["drags"]


def test_the_plan_pdf_gets_the_run_and_its_fan_chart_does_not_raise(monkeypatch):
    from reports import investment_plan as ip

    captured = {}

    def _fake_generate(self, **kw):
        captured.update(kw)
        return b"%PDF-fake"

    monkeypatch.setattr(ip.InvestmentPlanReport, "generate", _fake_generate)
    at = _open(_Prefs())
    at.button(key="plan_pdf_btn").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    params = captured["mc_params"]
    assert params["horizon_years"] == RUN["horizon_years"]
    assert params["inflation_rate"] == RUN["inflation_rate"]
    assert float(params["monthly_savings"]) == RUN["monthly_savings"]   # main: 500 del perfil
    # El fan chart real con esos parámetros: con 24.0 lanzaba TypeError y el
    # `try` de `_section_risk` lo sacaba del PDF sin decir nada. Sólo se prueba
    # que no lanza: que el dibujo sea correcto es PDF-FAN-PATHS (lee los ejes
    # de `fan_paths` al revés), fuera de este oráculo.
    ip.InvestmentPlanReport()._fan_chart(captured["mc_result"], params)


# --------------------------------------------------------------------------- #
#  Controles: lo que hoy funciona sigue igual                                 #
# --------------------------------------------------------------------------- #

def test_control_without_a_run_the_profile_still_fills_the_pdf():
    """Sin corrida no hay nada que pisar: widgets y después el perfil, como antes."""
    from data.product_ux import assemble_plan_pdf_mc_params

    out = assemble_plan_pdf_mc_params(
        session={}, prefs=_Prefs(),
        personal={"monthly_savings": 500.0, "primary_horizon_years": PROFILE_HORIZON},
    )
    assert float(out["horizon_years"]) == PROFILE_HORIZON
    assert float(out["monthly_savings"]) == pytest.approx(500.0)


def test_control_without_a_run_the_widgets_still_win_over_the_profile():
    from data.product_ux import assemble_plan_pdf_mc_params

    out = assemble_plan_pdf_mc_params(
        session={"horizon_years": 15, "inflation_rate": 4.0}, prefs=_Prefs(),
        personal={"primary_horizon_years": PROFILE_HORIZON},
    )
    assert out["horizon_years"] == 15
    assert out["inflation_rate"] == 4.0


def test_control_an_old_plan_without_the_raise_leaves_the_users_value(stores):  # noqa: F811
    from data.product_ux import plan_load_session_updates
    from tests.test_plan_page_runtime import _snap

    updates = plan_load_session_updates(_snap(), horizon_years=20)
    assert "contribution_growth_pct" not in updates


def test_control_a_plan_saved_without_a_run_has_no_mc_summary(stores):  # noqa: F811
    assert _save(stores, _Prefs(), run=False).mc_summary is None
