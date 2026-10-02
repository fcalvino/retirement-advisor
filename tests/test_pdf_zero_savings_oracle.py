"""Oráculo PDF-ZERO-SAVINGS: una corrida sin ahorro no se describe con el ahorro del perfil.

`enrich_pdf_mc_params` (`data/product_ux.py`) leía un ahorro ≤ 0 como «sin dato»
y ponía el del perfil, y `InvestmentPlanReport` (`reports/investment_plan.py`) lo
vuelve a llamar antes de armar «Para compartir». En la QA en vivo sobre
`origin/main` (`d4a8d5b`), con un perfil de 2.000/mes y una corrida con ahorro 0,
el PDF de Mi Plan decía «Aportar ~$2,000/mes a Plan de retiro», al lado de la
probabilidad y la mediana de una corrida que no aportó nada. El checklist del
plan activo en Mi Plan decía lo mismo («Meta de aporte anual: 24,000 (según tu
perfil/plan)») aunque el plan guardó `mc_summary.monthly_savings = 0.0`:
`build_annual_action_list` tenía su propio relleno y la página le pasaba el ahorro
del perfil.

La regla es la de U4-5 (`contribution_inputs`): un ahorro **presente** en 0 es una
respuesta —«no aporto»—; ausente o `None` es «no sé» y sigue cayendo al perfil.
Decisiones del usuario (2026-10-02): el arreglo cubre el PDF y el checklist; con
0 la acción dice «Esta proyección no incluye aportes»; un 0 tipeado en el widget
de Simulaciones también cuenta, sin corrida.

La referencia es la corrida: el texto tiene que nombrar el ahorro que la corrida
usó, o decir que no hubo. El perfil del disco (`UserPreferences.load`, que el
reporte lee) se fija en cada test para que el resultado no dependa de la máquina.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_plan_page_runtime import PAGE, _FakePrefs, _snap, stores  # noqa: F401  (fixture)
from tests.test_plan_save_params_oracle import RUN, _mc, _opt

PROFILE_MONTHLY = 2_000.0          # lo que el defecto pone en el PDF
NO_CONTRIBUTIONS = "Esta proyección no incluye aportes"
DEFINE_SAVINGS = "Definí cuánto podés aportar"


class _Prefs(_FakePrefs):
    monthly_savings = PROFILE_MONTHLY
    annual_savings = PROFILE_MONTHLY * 12


class _PrefsWithoutSavings(_FakePrefs):
    monthly_savings = 0.0          # perfil sin completar: `UserPreferences` da 0
    annual_savings = 0.0


def _disk_prefs(monkeypatch, prefs) -> None:
    """El perfil que el reporte lee de disco es el mismo que el de la página."""
    from data import preferences as prefs_mod

    monkeypatch.setattr(prefs_mod.UserPreferences, "load", classmethod(lambda cls, *a, **k: prefs))


def _run(monthly: float) -> dict:
    run = dict(RUN)
    run["monthly_savings"] = monthly
    run["annual_contribution"] = monthly * 12
    return run


def _shareable_text(monkeypatch) -> list:
    """Envuelve la sección real y guarda su texto: el PDF se arma de verdad."""
    from reports import investment_plan as ip

    seen: list = []
    original = ip.InvestmentPlanReport._section_shareable_for_partner

    def _spy(self, *a, **k):
        elements = original(self, *a, **k)
        seen.append(" ".join(getattr(e, "text", "") or "" for e in elements))
        return elements

    monkeypatch.setattr(ip.InvestmentPlanReport, "_section_shareable_for_partner", _spy)
    return seen


def _plan_pdf(monkeypatch, prefs, run: dict | None) -> str:
    """Mi Plan después de Simulaciones (sin claves de widget) → «Generar PDF»."""
    _disk_prefs(monkeypatch, prefs)
    seen = _shareable_text(monkeypatch)
    at = AppTest.from_file(PAGE, default_timeout=120)
    at.session_state["user_prefs"] = prefs
    at.session_state["optimizer_result"] = _opt()
    if run is not None:
        at.session_state["mc_result"] = _mc()
        at.session_state["mc_params"] = run
    at.run()
    at.button(key="plan_pdf_btn").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert "plan_pdf_bytes" in at.session_state, "el PDF no se generó"
    assert len(seen) == 1
    return seen[0]


def _monthly(text_amount: float) -> str:
    return f"~${text_amount:,.0f}/mes"


# --------------------------------------------------------------------------- #
#  El PDF de Mi Plan describe la corrida                                      #
# --------------------------------------------------------------------------- #

def test_the_plan_pdf_of_a_zero_savings_run_says_it_has_no_contributions(monkeypatch):
    text = _plan_pdf(monkeypatch, _Prefs(), _run(0.0))
    assert _monthly(PROFILE_MONTHLY) not in text      # main: «Aportar ~$2,000/mes»
    assert NO_CONTRIBUTIONS in text
    assert DEFINE_SAVINGS not in text                 # la corrida respondió: no aporta


def test_the_report_keeps_a_zero_that_reaches_it(monkeypatch):
    """La segunda llamada a `enrich_pdf_mc_params`, dentro del reporte, tampoco
    puede convertir el 0 en el perfil: ni el de disco ni el de `goal_plan`."""
    from reports import investment_plan as ip

    _disk_prefs(monkeypatch, _Prefs())
    elements = ip.InvestmentPlanReport()._section_shareable_for_partner(
        ip._styles(),
        goal_plan=SimpleNamespace(personal={"monthly_savings": PROFILE_MONTHLY}),
        opt_result=_opt(),
        mc_result=_mc(),
        mc_params={"horizon_years": 20, "initial_value": 250_000, "monthly_savings": 0.0},
        options=ip.ReportOptions(user_name="QA"),
    )
    text = " ".join(getattr(e, "text", "") or "" for e in elements)
    assert _monthly(PROFILE_MONTHLY) not in text      # main: «Aportar ~$2,000/mes»
    assert NO_CONTRIBUTIONS in text


def test_a_zero_typed_in_simulaciones_is_an_answer_without_a_run():
    """Mis Metas arma el PDF con la sesión de Simulaciones y sin corrida: el
    widget «Ahorro mensual (0 = no aporto)» en 0 es lo que el usuario dijo."""
    from data.product_ux import assemble_plan_pdf_mc_params

    out = assemble_plan_pdf_mc_params(
        session={"monthly_savings": 0}, prefs=_Prefs(),
        personal={"monthly_savings": PROFILE_MONTHLY},
    )
    assert out["monthly_savings"] == 0                # main: 2.000 del perfil
    assert out["annual_savings"] == 0


def test_the_typed_zero_wins_over_another_savings_key():
    """Precedencia de `contribution_inputs`: la primera clave con valor decide, y
    `monthly_savings` va primero. Un aporte de meta a medio tipear
    (`new_goal_contribution`, que `assemble_plan_pdf_mc_params` usa como
    `annual_contribution`) no pisa el 0 del widget."""
    from data.product_ux import assemble_plan_pdf_mc_params

    out = assemble_plan_pdf_mc_params(
        session={"monthly_savings": 0, "new_goal_contribution": 12_000}, prefs=_Prefs(),
    )
    assert out["monthly_savings"] == 0                # main: 1.000 (12.000 / 12)


# --------------------------------------------------------------------------- #
#  El checklist del plan activo describe el plan guardado                     #
# --------------------------------------------------------------------------- #

def _checklist(stores, prefs, mc_summary: dict) -> str:  # noqa: F811
    snap = _snap()
    snap.mc_summary = mc_summary
    # Como lo deja `PlanSnapshot.from_session`: el perfil al guardar.
    snap.personal = {"monthly_savings": PROFILE_MONTHLY, "annual_savings": PROFILE_MONTHLY * 12}
    stores.plans.upsert(snap)
    prefs.set_active_plan(snap.id)
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    items = [m.value for m in at.markdown if " · _" in (m.value or "")]
    assert items, "el checklist del plan activo no se dibujó"
    return "\n".join(items)


def test_the_active_plan_checklist_reads_the_savings_the_plan_saved(stores):  # noqa: F811
    text = _checklist(stores, _Prefs(), {**_snap().mc_summary, "monthly_savings": 0.0})
    assert "2,000/mes" not in text                    # main: «Aportar ~$2,000/mes»
    assert "24,000" not in text                       # main: «Meta de aporte anual: $24,000»
    assert NO_CONTRIBUTIONS in text


def test_the_active_plan_checklist_names_the_plans_savings_not_the_profiles(stores):  # noqa: F811
    text = _checklist(stores, _Prefs(), {**_snap().mc_summary, "monthly_savings": 1_500.0})
    assert "1,500/mes" in text                        # main: 2,000 del perfil
    assert "2,000/mes" not in text


def test_a_zero_is_an_answer_the_action_list_does_not_fill_from_the_plan():
    """`build_annual_action_list` tenía su propio relleno: 0 caía al `personal`
    del plan, que es el perfil al guardar."""
    from data.product_ux import build_annual_action_list

    actions = build_annual_action_list(
        plan_snapshot=SimpleNamespace(name="Plan", personal={"monthly_savings": PROFILE_MONTHLY}),
        monthly_savings=0.0,
    )
    assert actions[0]["title"] == NO_CONTRIBUTIONS    # main: «Aportar ~$2,000/mes a Plan»
    assert not any("2,000" in a["title"] or "2,000" in a["detail"] for a in actions)


# --------------------------------------------------------------------------- #
#  Controles: lo que hoy funciona sigue igual                                 #
# --------------------------------------------------------------------------- #

def test_control_a_run_with_savings_is_described_with_them(monkeypatch):
    text = _plan_pdf(monkeypatch, _Prefs(), _run(1_500.0))
    assert _monthly(1_500.0) in text
    assert NO_CONTRIBUTIONS not in text


def test_control_without_a_run_the_profile_still_fills_the_pdf(monkeypatch):
    """Optimizer y Mi Plan sin corrida: `None` sigue cayendo al perfil."""
    text = _plan_pdf(monkeypatch, _Prefs(), None)
    assert _monthly(PROFILE_MONTHLY) in text
    assert NO_CONTRIBUTIONS not in text


def test_control_with_no_savings_anywhere_the_pdf_asks_to_define_them(monkeypatch):
    """Sin corrida y sin perfil no hay respuesta: no es un «no aporto»."""
    text = _plan_pdf(monkeypatch, _PrefsWithoutSavings(), None)
    assert DEFINE_SAVINGS in text
    assert NO_CONTRIBUTIONS not in text


def test_control_an_old_plan_without_saved_savings_uses_the_profile(stores):  # noqa: F811
    """Un plan guardado antes de PLAN-LOAD-SAVINGS no dice cuánto ahorraba."""
    text = _checklist(stores, _Prefs(), dict(_snap().mc_summary))
    assert "2,000/mes" in text


def test_control_the_action_list_without_savings_still_reads_the_plan_profile():
    """Un llamador que no pasa ahorro (`None`) sigue usando el `personal` del plan."""
    from data.product_ux import build_annual_action_list

    actions = build_annual_action_list(
        plan_snapshot=SimpleNamespace(name="Plan", personal={"monthly_savings": 700}),
    )
    assert actions[0]["id"] == "contribute"
    assert "700" in actions[0]["title"]


@pytest.mark.parametrize("value", [None, "", "abc"])
def test_control_an_unreadable_savings_value_is_not_an_answer(value):
    from data.product_ux import enrich_pdf_mc_params

    out = enrich_pdf_mc_params({"monthly_savings": value}, prefs=_Prefs())
    assert out["monthly_savings"] == PROFILE_MONTHLY
