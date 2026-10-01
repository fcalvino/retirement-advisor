"""Oráculo PROFILE-SEED-WIDGETS: el perfil llega a la pantalla de Simulaciones.

`seed_session_defaults_from_profile` (`dashboard/shared.py`) corre una vez por
sesión desde `app.py`, en la primera página que se abre —casi siempre Inicio—, y
escribía `horizon_years` e `initial_value`, claves de los widgets de
Simulaciones. Es el defecto de PLAN-LOAD-WIDGETS: Streamlit sólo le manda al
navegador un valor fijado en la **misma** corrida que crea el widget, así que al
abrir Simulaciones después el script tenía el perfil, el proto llegaba con
`set_value=False` y el navegador dibujaba el default (20 años, 100.000), que
«Ejecutar» devolvía. El caption «Defaults tomados de Mi Perfil: horizonte ~24
años · capital $11,412» contradecía a los widgets. Visto en la QA en vivo de
PLAN-LOAD-WIDGETS sobre el perfil real, igual en `origin/main` (`fda6601`).

La referencia es lo que dibuja el navegador, leído del proto con la regla del
frontend (`_shown`, compartida con el oráculo de PLAN-LOAD-WIDGETS): con
`set_value` muestra el valor del proto; sin él, su `default`. Se recorre la app
real (`app.py` con `st.navigation`).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_cash_flow_oracle import _flat_history
from tests.test_plan_load_widgets_oracle import APP, RUN, _plan, _shown
from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)

# Perfil: 41 → 56 años son 15 de horizonte (una opción exacta del selectbox) y
# 333.000 de capital. Los dos difieren del default del widget (20, 100.000) y de
# la corrida guardada del plan (15 años pero 900.000), así que un valor que no
# llegó no puede pasar por casualidad.
PROFILE = dict(onboarded=True, age=41, retirement_age=56,
               current_capital=333_000.0, monthly_savings=2_000.0)
SHOWN = {"horizon_years": 15, "initial_value": 333_000}

# El wizard: otro perfil, guardado desde Inicio en la misma sesión.
WIZARD = {"age": 40, "retage": 50, "capital": 444_000}
WIZARD_SHOWN = {"horizon_years": 10, "initial_value": 444_000}


def _prefs(**overrides):
    from data.preferences import UserPreferences

    return UserPreferences(**{**PROFILE, **overrides})


def _app(prefs) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["user_prefs"] = prefs
    return at


def _simulaciones(at: AppTest) -> AppTest:
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        at.switch_page("views/7_Simulaciones.py").run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _home_then_simulaciones(prefs) -> AppTest:
    """Inicio (la siembra corre acá) → Simulaciones, en una misma sesión."""
    at = _app(prefs).run()
    assert not at.exception, [e.message for e in at.exception]
    return _simulaciones(at)


# --------------------------------------------------------------------------- #
#  El perfil es lo que se ve                                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", ["horizon_years", "initial_value"])
def test_the_profile_is_what_the_browser_shows(stores, key):  # noqa: F811
    at = _home_then_simulaciones(_prefs())
    assert at.session_state[key] == SHOWN[key]     # el script ya lo tenía en main
    assert _shown(at, key) == SHOWN[key]           # main: el default del widget


def test_the_caption_and_the_widgets_say_the_same(stores):  # noqa: F811
    """El caption nombra el perfil; los widgets tienen que mostrar ese perfil."""
    at = _home_then_simulaciones(_prefs())
    assert any("Defaults tomados de **Mi Perfil**" in c.value for c in at.caption)
    assert _shown(at, "initial_value") == PROFILE["current_capital"]


@pytest.mark.parametrize("key", ["horizon_years", "initial_value"])
def test_the_wizard_refreshes_what_the_browser_shows(stores, tmp_path, key):  # noqa: F811
    """Guardar el wizard en Inicio (``force=True``) llega a Simulaciones."""
    with patch("data.preferences._PREFS_PATH", tmp_path / "prefs.json"):
        at = _app(_prefs(onboarded=False, age=0)).run()
        assert not at.exception, [e.message for e in at.exception]
        at.number_input(key="home_onb_age").set_value(WIZARD["age"])
        at.number_input(key="home_onb_retage").set_value(WIZARD["retage"])
        at.number_input(key="home_onb_capital").set_value(WIZARD["capital"])
        next(b for b in at.button if "Guardar mi perfil" in b.label).click()
        at.run()
        assert not at.exception, [e.message for e in at.exception]
        assert at.session_state["user_prefs"].is_onboarded
        _simulaciones(at)
    assert _shown(at, key) == WIZARD_SHOWN[key]    # main: el default del widget


# --------------------------------------------------------------------------- #
#  Controles: lo que hoy funciona sigue igual                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", ["horizon_years", "initial_value"])
def test_control_simulaciones_opened_first_shows_the_profile(stores, key):  # noqa: F811
    """Abierta como primera página, la siembra cae en la misma corrida."""
    at = _simulaciones(_app(_prefs()))
    assert _shown(at, key) == SHOWN[key]


def test_control_a_loaded_plan_beats_the_profile(stores):  # noqa: F811
    """«Cargar plan» después de la siembra: Simulaciones muestra la corrida del plan."""
    snap = _plan()
    stores.plans.upsert(snap)
    at = _app(_prefs()).run()
    at.switch_page("views/12_Plan.py").run()
    at.button(key=f"view_{snap.id}").click().run()
    at.button(key=f"load_{snap.id}").click().run()
    assert not at.exception, [e.message for e in at.exception]
    _simulaciones(at)
    assert _shown(at, "initial_value") == RUN["initial_value"]
    assert _shown(at, "horizon_years") == RUN["horizon_years"]


def test_control_an_edit_on_the_page_is_not_overwritten(stores):  # noqa: F811
    """La siembra se aplica una vez: lo que el usuario cambia después se queda."""
    at = _home_then_simulaciones(_prefs())
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        at.sidebar.selectbox(key="horizon_years").set_value(25).run()
        at.sidebar.number_input(key="initial_value").set_value(50_000).run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.session_state["horizon_years"] == 25
    assert at.session_state["initial_value"] == 50_000


def test_control_a_user_without_profile_keeps_the_widget_defaults(stores):  # noqa: F811
    """Sin perfil no hay siembra: la pantalla muestra los defaults del widget."""
    at = _home_then_simulaciones(_prefs(onboarded=False, age=0))
    assert _shown(at, "horizon_years") == 20
    assert _shown(at, "initial_value") == 100_000
