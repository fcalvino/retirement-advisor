"""Oráculo PLAN-LOAD-SAVINGS: «Cargar plan» devuelve el ahorro, el retiro y los supuestos de la corrida.

PLAN-LOAD-WIDGETS hizo que «Cargar plan» llegara al navegador, pero sólo con las
cinco claves que el plan guardaba: horizonte, capital, inflación, suba del ahorro
y meta. El ahorro mensual y el retiro anual de la corrida no estaban en
`mc_summary` —PLAN-SAVE-PARAMS los agregó a `mc_params` para el PDF, no al plan—,
así que un plan cargado corría con el ahorro que tuviera la sesión: en la QA en
vivo, los 2.000/mes del perfil. Lo mismo con la estrategia de retiro y los drags:
el plan los guarda (`withdrawal_strategy`, `drags_at_save`) y nadie los devolvía.

Una trampa del lado del guardado: los parámetros que recibe `from_session` pasan
por `enrich_pdf_mc_params`, que lee un ahorro de 0 como «sin dato» y pone el del
perfil. Copiar de ahí guardaría 2.000 por una corrida que no aportaba; el plan
toma el ahorro de la corrida cruda (`mc_params` de Simulaciones).

Se recorre la app real (`app.py` con `st.navigation`) en una sola sesión, y la
referencia es lo que dibuja el navegador —`set_value` si el proto lo trae, si no
el `default`— y lo que recibe el motor al tocar «Ejecutar» (`mc_result`).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_cash_flow_oracle import _flat_history
from tests.test_plan_load_widgets_oracle import APP, _plan
from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)
from tests.test_plan_save_params_oracle import _opt

# Perfil onboardeado que ahorra 2.000/mes: el valor que el defecto deja en la
# pantalla. Cada número de la corrida difiere de él y de los defaults.
PROFILE = dict(onboarded=True, age=40, retirement_age=60,
               current_capital=250_000.0, monthly_savings=2_000.0)
SAVINGS = 3_300          # perfil: 2.000
WITHDRAWAL = 12_000      # widget: 0
EDITED = 500             # lo que el usuario tipea después de guardar
STRATEGY_AMOUNT = 24_000
FEE = 0.8


def _prefs():
    from data.preferences import UserPreferences

    return UserPreferences(**PROFILE)


def _hist():
    return patch("portfolio.monte_carlo.get_history",
                 side_effect=lambda *a, **k: _flat_history(0.06))


def _ok(at: AppTest) -> AppTest:
    assert not at.exception, [e.message for e in at.exception]
    return at


def _go(at: AppTest, page: str) -> AppTest:
    with _hist():
        at.switch_page(page).run()
    return _ok(at)


def _sim(at: AppTest) -> AppTest:
    return _go(at, "views/7_Simulaciones.py")


def _set(at: AppTest, widget, value) -> None:
    with _hist():
        widget.set_value(value).run()
    _ok(at)


def _execute(at: AppTest):
    at.sidebar.select_slider(key="n_sims").set_value(1_000)
    run = next(b for b in at.button if "Ejecutar simulación Monte Carlo" in b.label)
    with _hist():
        run.click().run()
    _ok(at)
    return at.session_state["mc_result"]


def _session(stores) -> AppTest:  # noqa: F811
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["user_prefs"] = _prefs()
    at.session_state["optimizer_result"] = _opt()
    return _ok(at.run())


def _save(at: AppTest, stores):  # noqa: F811
    _go(at, "views/12_Plan.py")
    at.button(key="plan_save_btn").click().run()
    _ok(at)
    plans = stores.plans.list()
    assert len(plans) == 1
    return plans[0]


def _load(at: AppTest, snap) -> AppTest:
    """Mi Plan → «Ver» → «Cargar plan» → Simulaciones, en la misma sesión."""
    _go(at, "views/12_Plan.py")
    at.button(key=f"view_{snap.id}").click().run()
    at.button(key=f"load_{snap.id}").click().run()
    return _sim(_ok(at))


def _number(at: AppTest, key: str):
    """Lo que dibuja el navegador para un `number_input`."""
    w = at.number_input(key=key)
    return w.proto.value if w.proto.set_value else w.proto.default


def _kind(at: AppTest) -> str:
    from dashboard.shared import _WITHDRAWAL_LABELS

    w = at.selectbox(key="sim_wd_kind")
    label = w.proto.raw_value if w.proto.set_value else w.proto.options[w.proto.default]
    return next(k for k, v in _WITHDRAWAL_LABELS.items() if v == label)


def _drags_on(at: AppTest) -> bool:
    w = at.toggle(key="sim_drags_enabled_toggle")
    return bool(w.proto.value if w.proto.set_value else w.proto.default)


def _round_trip(stores, *, savings, withdrawal=0, strategy=False, drags=None,  # noqa: F811
                then_savings=EDITED, then_strategy=None, then_drags=None):
    """Correr → guardar → cambiar la sesión → cargar: el camino de un usuario real."""
    at = _sim(_session(stores))
    _set(at, at.sidebar.number_input(key="monthly_savings"), savings)
    _set(at, at.sidebar.number_input(key="annual_withdrawal"), withdrawal)
    if strategy:
        _set(at, at.selectbox(key="sim_wd_kind"), "fixed_real")
        _set(at, at.number_input(key="sim_wd_amount"), STRATEGY_AMOUNT)
    if drags is not None:        # los drags vienen prendidos (`DRAGS.enabled`)
        _set(at, at.toggle(key="sim_drags_enabled_toggle"), drags)
    if drags:
        _set(at, at.number_input(key="sim_drag_fee"), FEE)
    _execute(at)
    snap = _save(at, stores)

    # Después de guardar, la sesión se va a otro lado.
    _sim(at)
    _set(at, at.sidebar.number_input(key="monthly_savings"), then_savings)
    _set(at, at.sidebar.number_input(key="annual_withdrawal"), 0)
    if then_strategy == "none":
        _set(at, at.selectbox(key="sim_wd_kind"), "none")
    elif then_strategy:
        _set(at, at.selectbox(key="sim_wd_kind"), "fixed_real")
        _set(at, at.number_input(key="sim_wd_amount"), then_strategy)
    if then_drags is not None:
        _set(at, at.toggle(key="sim_drags_enabled_toggle"), then_drags)
    return _load(at, snap), snap


# --------------------------------------------------------------------------- #
#  El ahorro y el retiro de la corrida vuelven                                #
# --------------------------------------------------------------------------- #

def test_the_loaded_savings_and_withdrawal_are_what_the_browser_shows(stores):  # noqa: F811
    at, snap = _round_trip(stores, savings=SAVINGS, withdrawal=WITHDRAWAL)
    assert snap.mc_summary["monthly_savings"] == SAVINGS
    assert snap.mc_summary["annual_withdrawal"] == WITHDRAWAL
    assert _number(at, "monthly_savings") == SAVINGS          # main: 2.000 (perfil)
    assert _number(at, "annual_withdrawal") == WITHDRAWAL     # main: 0
    mc = _execute(at)
    assert mc.annual_contribution == SAVINGS * 12
    assert mc.annual_withdrawal == WITHDRAWAL


def test_a_plan_that_saved_nothing_loads_nothing_not_the_profile(stores):  # noqa: F811
    """Un ahorro de 0 es una respuesta: el plan cargado no aporta, aunque el perfil sí."""
    at, snap = _round_trip(stores, savings=0)
    assert snap.mc_summary["monthly_savings"] == 0            # enrich: 2.000
    assert _number(at, "monthly_savings") == 0
    assert _execute(at).annual_contribution == 0


# --------------------------------------------------------------------------- #
#  La estrategia de retiro y los drags de la corrida vuelven                  #
# --------------------------------------------------------------------------- #

def test_the_loaded_strategy_is_what_the_browser_shows_and_runs(stores):  # noqa: F811
    at, _ = _round_trip(stores, savings=SAVINGS, strategy=True, then_strategy="none")
    assert _kind(at) == "fixed_real"                          # main: none (la sesión)
    assert _number(at, "sim_wd_amount") == STRATEGY_AMOUNT
    applied = _execute(at).withdrawal_strategy_applied
    assert applied and applied["kind"] == "fixed_real"
    assert applied["annual_amount"] == STRATEGY_AMOUNT


def test_a_plan_without_strategy_turns_off_the_sessions(stores):  # noqa: F811
    """Guardado sin estrategia: cargarlo vuelve a acumulación, aunque la sesión tenga una."""
    at, _ = _round_trip(stores, savings=SAVINGS, then_strategy=30_000)
    assert _kind(at) == "none"
    mc = _execute(at)
    assert not mc.withdrawal_strategy_applied
    assert mc.annual_contribution == SAVINGS * 12


def test_the_loaded_drags_are_what_the_browser_shows_and_runs(stores):  # noqa: F811
    at, _ = _round_trip(stores, savings=SAVINGS, drags=True, then_drags=False)
    assert _drags_on(at)
    assert _number(at, "sim_drag_fee") == FEE
    assert _execute(at).total_annual_drag_pct > 0


def test_a_plan_without_drags_turns_off_the_sessions(stores):  # noqa: F811
    at, _ = _round_trip(stores, savings=SAVINGS, drags=False, then_drags=True)
    assert not _drags_on(at)
    assert _execute(at).total_annual_drag_pct == 0


# --------------------------------------------------------------------------- #
#  Lo que el plan no puede responder no pisa nada                            #
# --------------------------------------------------------------------------- #

def _session_with_strategy_and_savings(stores):  # noqa: F811
    at = _sim(_session(stores))
    _set(at, at.sidebar.number_input(key="monthly_savings"), EDITED)
    _set(at, at.selectbox(key="sim_wd_kind"), "fixed_real")
    _set(at, at.number_input(key="sim_wd_amount"), 30_000)
    _set(at, at.toggle(key="sim_drags_enabled_toggle"), True)
    return at


def test_control_an_old_plan_leaves_the_session_alone(stores):  # noqa: F811
    """Un plan anterior a la fila no sabe su ahorro ni si tenía estrategia: no toca nada.

    El ahorro tipeado no sobrevive a salir de Simulaciones —Streamlit borra la
    clave del widget y la pantalla vuelve a sembrarse con el perfil—, así que lo
    que el plan viejo no toca es eso: lo que se ve sin cargar ningún plan.
    """
    snap = _plan()               # mc_summary sin las claves nuevas ni la marca
    stores.plans.upsert(snap)
    at = _load(_session_with_strategy_and_savings(stores), snap)
    assert _number(at, "monthly_savings") == PROFILE["monthly_savings"]
    assert _kind(at) == "fixed_real"
    assert _number(at, "sim_wd_amount") == 30_000
    assert _drags_on(at)


def test_a_saved_strategy_without_the_marker_still_loads(stores):  # noqa: F811
    """Un dict guardado no es ambiguo: los planes de ejemplo traen el suyo."""
    snap = _plan(withdrawal_strategy={"kind": "constant_pct", "pct": 0.045,
                                      "label": "4.5% del valor actual"})
    stores.plans.upsert(snap)
    at = _load(_sim(_session(stores)), snap)
    assert _kind(at) == "constant_pct"
    assert _number(at, "sim_wd_pct") == pytest.approx(4.5)


def test_savings_above_the_widget_cap_are_capped_and_said(stores):  # noqa: F811
    snap = _plan(mc_summary={**_plan().mc_summary, "monthly_savings": 150_000})
    stores.plans.upsert(snap)
    at = _load(_sim(_session(stores)), snap)
    assert _number(at, "monthly_savings") == at.number_input(key="monthly_savings").proto.max
    assert any("recort" in w.value for w in at.sidebar.warning)


def test_a_strategy_out_of_range_is_not_loaded_and_said(stores):  # noqa: F811
    """Un JSON editado a mano con un 30 % de retiro: el widget no lo admite (0,5–15)."""
    snap = _plan(withdrawal_strategy={"kind": "constant_pct", "pct": 0.30, "label": "30%"})
    stores.plans.upsert(snap)
    at = _load(_session_with_strategy_and_savings(stores), snap)
    assert _kind(at) == "fixed_real"                      # la sesión queda como estaba
    assert any("estrategia de retiro" in w.value for w in at.sidebar.warning)


# --------------------------------------------------------------------------- #
#  El helper puro                                                             #
# --------------------------------------------------------------------------- #

def test_the_helper_maps_each_strategy_back_to_its_session_keys():
    from data.product_ux import plan_load_session_updates

    def updates(strategy, **mc):
        return plan_load_session_updates(
            _plan(withdrawal_strategy=strategy,
                  mc_summary={**_plan().mc_summary, **mc}), horizon_years=15)

    fixed = updates({"kind": "fixed_real", "annual_amount": 24_000}, longevity_years=35)
    assert fixed["withdrawal_kind"] == "fixed_real"
    assert fixed["withdrawal_amount"] == 24_000
    assert fixed["withdrawal_longevity_years"] == 35
    assert updates({"kind": "constant_pct", "pct": 0.045})["withdrawal_pct"] == pytest.approx(4.5)
    assert updates({"kind": "guardrails", "pct": 0.04})["withdrawal_base_pct"] == pytest.approx(4.0)
