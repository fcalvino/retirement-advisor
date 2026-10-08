"""Oráculo STREAMLIT-1.65: volver a Simulaciones muestra lo editado, también con Streamlit 1.65.

Streamlit 1.65.0 dibuja, para un widget creado en la corrida, el valor que quedó bajo su clave
antes de crearlo. La siembra del perfil escribe ``horizon_years`` e ``initial_value`` en la
sesión desde la primera página; al volver a Simulaciones esas claves traían el perfil y no lo
editado (1.61.1–1.64.0 no lo hacían). Tres casos de ``test_sim_reentry_widgets_oracle`` lo
reproducían (sólo en 1.65.0). El arreglo: al **llegar** a la página, la memoria de la sesión
vuelve a las claves que ya están en el estado, antes de la siembra, el plan cargado y los
presets, que siguen ganándole. «Llegar» lo marca ``dashboard/app.py`` en cada corrida
(``track_page_entry``): en un rerun de la misma página restaurar desharía lo recién tipeado.

Los esperados están hechos a mano. Los casos de pantalla corren con la versión instalada
(1.65.0 en el venv aislado de la medición, la del lock en CI). Sin red.
"""

from __future__ import annotations

import pytest

from data.product_ux import (
    NAV_PAGE_KEY,
    PAGE_ENTERED_KEY,
    SIM_SIDEBAR_MEMORY_KEY,
    restore_sim_sidebar,
    track_page_entry,
)
from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)
from tests.test_profile_seed_widgets_oracle import _home_then_simulaciones
from tests.test_sim_reentry_widgets_oracle import EDITS, _prefs, _round_trip, _run, _shown, _widget

# --------------------------------------------------------------------------- #
#  La marca de llegada                                                         #
# --------------------------------------------------------------------------- #

def test_the_first_run_and_a_change_of_page_are_arrivals_a_rerun_is_not():
    state: dict = {}
    assert track_page_entry(state, "simulaciones") is True        # la primera corrida
    assert state[PAGE_ENTERED_KEY] is True and state[NAV_PAGE_KEY] == "simulaciones"
    assert track_page_entry(state, "simulaciones") is False       # un rerun: tipeaste algo
    assert state[PAGE_ENTERED_KEY] is False
    assert track_page_entry(state, "plan") is True                # te fuiste
    assert track_page_entry(state, "simulaciones") is True        # y volviste


# --------------------------------------------------------------------------- #
#  Qué restaura                                                                #
# --------------------------------------------------------------------------- #

def _state(**over):
    return {SIM_SIDEBAR_MEMORY_KEY: {"horizon_years": 30, "initial_value": 222_000,
                                     "n_sims": 5_000, "target_value": 777_000}, **over}


def test_a_stale_key_gets_the_remembered_value_and_an_absent_key_is_left_alone():
    # El perfil sembró horizon_years/initial_value (valores viejos bajo la clave); n_sims y
    # target_value no están: ya abren con su memoria por value=, y escribirlos no hace falta.
    state = _state(horizon_years=25, initial_value=150_000)
    restore_sim_sidebar(state)
    assert (state["horizon_years"], state["initial_value"]) == (30, 222_000)
    assert "n_sims" not in state and "target_value" not in state


def test_without_memory_nothing_is_written():
    state = {"horizon_years": 25}
    restore_sim_sidebar(state)
    assert state == {"horizon_years": 25}


def test_an_off_grid_remembered_horizon_snaps_to_an_option():
    """El preset «Meta importante» recuerda 8 años; el selectbox no ofrece 8."""
    from dashboard.shared import snap_sim_horizon

    state = {SIM_SIDEBAR_MEMORY_KEY: {"horizon_years": 8}, "horizon_years": 25}
    restore_sim_sidebar(state, snap_horizon=snap_sim_horizon)
    assert state["horizon_years"] == 10                           # la opción más cercana


# --------------------------------------------------------------------------- #
#  La pantalla                                                                 #
# --------------------------------------------------------------------------- #

def test_an_edit_followed_by_a_rerun_on_the_same_page_is_not_undone(stores):  # noqa: F811
    """Restaurar en un rerun pisaría lo recién tipeado con la memoria de la corrida anterior.

    En un rerun de la misma página lo que manda es el estado del script (el navegador no
    vuelve a dibujar el widget), así que se lee ``widget.value``, no lo que «se ve».
    """
    at = _home_then_simulaciones(_prefs())
    _widget(at, "horizon_years").set_value(EDITS["horizon_years"])
    _run(at)
    assert _widget(at, "horizon_years").value == EDITS["horizon_years"]
    _widget(at, "initial_value").set_value(EDITS["initial_value"])
    _run(at)
    assert _widget(at, "initial_value").value == EDITS["initial_value"]
    assert _widget(at, "horizon_years").value == EDITS["horizon_years"]


def test_app_marks_the_arrival_before_each_page_runs(stores):  # noqa: F811
    at = _home_then_simulaciones(_prefs())
    assert at.session_state[PAGE_ENTERED_KEY] is True             # recién llegó a Simulaciones
    _run(at)
    assert at.session_state[PAGE_ENTERED_KEY] is False            # un rerun
    at = _round_trip(at)
    assert at.session_state[PAGE_ENTERED_KEY] is True             # volvió


@pytest.mark.parametrize("key", ["horizon_years", "initial_value"])
def test_the_profile_seed_still_wins_on_a_fresh_profile_save(stores, key):  # noqa: F811
    """El caso opuesto: sin nada recordado, la vuelta muestra el perfil (no se rompió la siembra)."""
    from tests.test_sim_reentry_widgets_oracle import SHOWN

    at = _round_trip(_home_then_simulaciones(_prefs()))
    assert _shown(at, key) == SHOWN[key]
