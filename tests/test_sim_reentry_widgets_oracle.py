"""Oráculo SIM-REENTRY-WIDGETS: volver a Simulaciones muestra lo último de la sesión.

Al cambiar de página Streamlit borra el estado de los widgets que la página
nueva no dibuja, así que las ocho claves del sidebar de Simulaciones
(`horizon_years`, `initial_value`, `monthly_savings`, `annual_withdrawal`,
`contribution_growth_pct`, `target_value`, `inflation_rate`, `n_sims`) no
sobrevivían una ida a Mi Plan. La siembra del perfil se aplica una vez
(`apply_pending_profile_seed` la saca de la sesión), y la vuelta dibujaba los
defaults escritos en cada widget: el caption seguía diciendo «Defaults tomados de
Mi Perfil: horizonte ~25 años · capital $150,000» sobre 20 años y 100.000, que
era lo que corría «Ejecutar». Lo editado en la pantalla también se perdía, las
ocho claves. Reproducido en vivo en `6320795` (perfil 40 → 65 años, 150.000).

Diseño decidido por el usuario (decimotercera repriorización): **conservar lo
editado**. Al volver aparece lo último de la sesión y, si no se tocó, el perfil;
un plan cargado sigue ganando.

La referencia es lo que dibuja el navegador, leído del proto con la regla del
frontend (`_shown`, la de PLAN-LOAD-WIDGETS): con `set_value` muestra el valor
del proto; sin él, su `default`. Se recorre la app real (`app.py` con
`st.navigation`) y la ida y vuelta es `switch_page`. AppTest no reproduce lo que
el navegador manda de vuelta: su `widget.value` lee el estado del script, que en
`main` todavía tenía el perfil, así que «Ejecutar corre lo que se ve» se prueba
en vivo y no acá.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.test_cash_flow_oracle import _flat_history
from tests.test_plan_load_widgets_oracle import RUN, _plan
from tests.test_plan_load_widgets_oracle import _shown as _shown_plan
from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)
from tests.test_profile_seed_widgets_oracle import _app, _home_then_simulaciones

# Perfil de la QA en vivo: 40 → 65 años son 25 de horizonte (una opción exacta) y
# 150.000 de capital; los dos difieren del default del widget (20, 100.000).
PROFILE = dict(onboarded=True, age=40, retirement_age=65,
               current_capital=150_000.0, monthly_savings=2_000.0,
               # An onboarded investor chose a tolerance (EO-1b: there is no default).
               risk_tolerance="moderada")
SHOWN = {"horizon_years": 25, "initial_value": 150_000, "monthly_savings": 2_000}

# Lo editado: cada valor difiere del perfil y del default del widget.
EDITS = {
    "horizon_years": 30,
    "initial_value": 222_000,
    "monthly_savings": 1_234,
    "annual_withdrawal": 5_000,
    "contribution_growth_pct": 2.5,
    "target_value": 777_000,
    "inflation_rate": 4.0,
    "n_sims": 5_000,
}


def _prefs(**overrides):
    from data.preferences import UserPreferences

    return UserPreferences(**{**PROFILE, **overrides})


def _shown(at, key: str):
    if key == "n_sims":
        w = at.sidebar.select_slider(key=key)
        idx = list(w.proto.value) if w.proto.set_value else list(w.proto.default)
        return int(w.proto.options[int(idx[0])].replace(",", "").replace(" ", ""))
    return _shown_plan(at, key)


def _widget(at, key: str):
    if key == "horizon_years":
        return at.sidebar.selectbox(key=key)
    if key == "inflation_rate":
        return at.sidebar.slider(key=key)
    if key == "n_sims":
        return at.sidebar.select_slider(key=key)
    return at.sidebar.number_input(key=key)


def _run(at):
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _round_trip(at):
    """Simulaciones → Mi Plan → Simulaciones, en la misma sesión."""
    at.switch_page("views/12_Plan.py")
    _run(at)
    at.switch_page("views/7_Simulaciones.py")
    return _run(at)


# --------------------------------------------------------------------------- #
#  Sin tocar nada, la vuelta muestra el perfil que nombra el caption           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", sorted(SHOWN))
def test_the_return_shows_the_profile(stores, key):  # noqa: F811
    at = _round_trip(_home_then_simulaciones(_prefs()))
    assert any("Defaults tomados de **Mi Perfil**" in c.value for c in at.caption)
    assert _shown(at, key) == SHOWN[key]           # main: 20 años / 100.000


# --------------------------------------------------------------------------- #
#  Lo editado vuelve, las ocho claves                                          #
# --------------------------------------------------------------------------- #

def _edited_round_trip():
    at = _home_then_simulaciones(_prefs())
    for key, value in EDITS.items():
        _widget(at, key).set_value(value)
        _run(at)
    return _round_trip(at)


@pytest.mark.parametrize("key", list(EDITS))
def test_an_edit_survives_the_round_trip(stores, key):  # noqa: F811
    at = _edited_round_trip()
    assert _shown(at, key) == EDITS[key]           # main: el default del widget


# --------------------------------------------------------------------------- #
#  Lo que manda sobre la memoria                                               #
# --------------------------------------------------------------------------- #

def test_a_loaded_plan_still_beats_the_memory(stores):  # noqa: F811
    """«Cargar plan» después de editar: la vuelta muestra la corrida del plan."""
    snap = _plan()
    stores.plans.upsert(snap)
    at = _home_then_simulaciones(_prefs())
    _widget(at, "initial_value").set_value(EDITS["initial_value"])
    _run(at)
    at.switch_page("views/12_Plan.py")
    _run(at)
    at.button(key=f"view_{snap.id}").click()
    _run(at)
    at.button(key=f"load_{snap.id}").click()
    _run(at)
    at.switch_page("views/7_Simulaciones.py")
    _run(at)
    assert _shown(at, "initial_value") == RUN["initial_value"]
    assert _shown(at, "horizon_years") == RUN["horizon_years"]
    # …y el plan cargado es lo que se recuerda en la vuelta siguiente.
    _round_trip(at)
    assert _shown(at, "initial_value") == RUN["initial_value"]


def test_a_profile_saved_in_settings_beats_the_remembered_savings(stores, tmp_path, monkeypatch):  # noqa: F811
    """Editar el perfil en Settings: la vuelta muestra el ahorro nuevo y conserva la meta."""
    from dashboard import shared

    # Settings cotiza ARS=X; None es lo que da un corte y la página lo rotula (TEST-NET).
    monkeypatch.setattr(shared, "usd_ars_quote", lambda symbol="ARS=X": None)
    with patch("data.preferences._PREFS_PATH", tmp_path / "prefs.json"):
        at = _home_then_simulaciones(_prefs())
        _widget(at, "monthly_savings").set_value(EDITS["monthly_savings"])
        _run(at)
        _widget(at, "target_value").set_value(EDITS["target_value"])
        _run(at)
        at.switch_page("views/9_Settings.py")
        _run(at)
        at.number_input(key="settings_onb_savings").set_value(3_300)
        next(b for b in at.button if "Guardar mi perfil" in b.label).click()
        _run(at)
        at.switch_page("views/7_Simulaciones.py")
        _run(at)
    assert _shown(at, "monthly_savings") == 3_300                 # sin olvidar: 1.234
    assert _shown(at, "target_value") == EDITS["target_value"]    # no es del perfil


def test_a_saved_profile_beats_the_remembered_profile_fields():
    """Guardar el perfil (``force=True``) olvida lo recordado del perfil, no el resto."""
    from data.product_ux import (
        SIM_SIDEBAR_MEMORY_KEY,
        forget_profile_fields_in_sim_memory,
        remember_sim_sidebar,
        sim_sidebar_value,
    )

    state = {"horizon_years": 30, "initial_value": 222_000, "monthly_savings": 1_234,
             "target_value": 777_000, "n_sims": 5_000}
    remember_sim_sidebar(state)
    forget_profile_fields_in_sim_memory(state)
    memory = state[SIM_SIDEBAR_MEMORY_KEY]
    assert set(memory) == {"target_value", "n_sims"}
    assert sim_sidebar_value(state, "monthly_savings", 2_000) == 2_000
    assert sim_sidebar_value(state, "target_value", 500_000) == 777_000


def test_a_remembered_off_grid_horizon_snaps_to_an_option():
    """El preset «Meta importante» escribe 8 años, que no es una opción del selectbox."""
    from dashboard.shared import sim_horizon_index

    assert sim_horizon_index({"_sim_sidebar_memory": {"horizon_years": 8}}) == 1   # 10 años
    assert sim_horizon_index({}) == 3                                              # 20 años


# --------------------------------------------------------------------------- #
#  Controles                                                                   #
# --------------------------------------------------------------------------- #

def test_control_without_profile_the_return_shows_the_config_defaults(stores):  # noqa: F811
    at = _round_trip(_home_then_simulaciones(_prefs(onboarded=False, age=0)))
    assert _shown(at, "horizon_years") == 20
    assert _shown(at, "initial_value") == 100_000


def test_control_first_visit_still_shows_the_profile(stores):  # noqa: F811
    at = _home_then_simulaciones(_prefs())
    for key, value in SHOWN.items():
        assert _shown(at, key) == value


def test_control_a_fresh_session_forgets(stores):  # noqa: F811
    """La memoria es de la sesión: otra sesión arranca del perfil."""
    _edited_round_trip()
    at = _run(_app(_prefs()))
    at.switch_page("views/7_Simulaciones.py")
    _run(at)
    assert _shown(at, "initial_value") == SHOWN["initial_value"]
