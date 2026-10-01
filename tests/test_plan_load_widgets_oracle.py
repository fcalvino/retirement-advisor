"""Oráculo PLAN-LOAD-WIDGETS: «Cargar plan» llega a la pantalla de Simulaciones.

`_render_load_plan` (`12_Plan.py`) escribía las claves de los widgets de
Simulaciones en `st.session_state` durante una corrida de Mi Plan. Al abrir
Simulaciones el script las recibía —`widget.value` daba 15 años—, pero Streamlit
sólo le manda al navegador un valor fijado en la **misma** corrida que crea el
widget (`register_widget` → `value_changed`, que sale de `_new_session_state` y
se vacía en cada rerun). El proto llegaba con `set_value=False`, el navegador
dibujaba el default (20 años, meta 500.000) y al tocar «Ejecutar» devolvía lo que
mostraba: el plan cargado se perdía sin aviso. Visto en la QA en vivo de
PLAN-SAVE-PARAMS y reproducido acá sobre `origin/main` (`c39156e`).

Además `plan_load_session_updates` sembraba el capital de Simulaciones con el del
perfil antes que con el de la corrida, así que aun arreglado volvía con otro
capital. Decisión del usuario (2026-10-01): el Optimizer sigue con el capital del
perfil; Simulaciones, con el de la corrida.

La referencia no es el estado del script —ahí el defecto no se ve— sino lo que
dibuja el navegador, leído del proto con la regla del frontend: con `set_value`
muestra el valor que trae el proto; sin él, su `default`. Se recorre la app real
(`app.py` con `st.navigation`): Mi Plan → «Cargar plan» → Simulaciones.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from data.plan_store import PlanSnapshot
from tests.test_cash_flow_oracle import _flat_history
from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)

APP = str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py")

# La corrida guardada. Cada número difiere del default del widget y del perfil,
# para que un valor que no llegó no pueda pasar por casualidad.
RUN = {
    "horizon_years": 15,            # widget: 20 · perfil: 24
    "initial_value": 900_000,       # widget: 100.000 · perfil: 250.000
    "target_value": 1_500_000,      # widget: 500.000
    "inflation_rate": 2.5,          # widget: 3,0
    "contribution_growth_pct": 2.5,  # widget: 0
    "median_terminal": 1_800_000.0,
}
PROFILE = {"current_capital": 250_000.0, "primary_horizon_years": 24}


def _plan(**overrides) -> PlanSnapshot:
    base = dict(
        id="plan-cargado", name="Plan cargado", created_at="", updated_at="",
        profile_name="Moderado", profile_key="moderate",
        personal=dict(PROFILE), mc_summary=dict(RUN),
    )
    base.update(overrides)
    return PlanSnapshot(**base)


def _load(stores, snap: PlanSnapshot) -> AppTest:  # noqa: F811
    """Mi Plan → «Ver» → «Cargar plan» → Simulaciones, en una misma sesión."""
    from data.preferences import UserPreferences

    stores.plans.upsert(snap)
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["user_prefs"] = UserPreferences()
    at.switch_page("views/12_Plan.py").run()
    assert not at.exception, [e.message for e in at.exception]
    at.button(key=f"view_{snap.id}").click().run()
    at.button(key=f"load_{snap.id}").click().run()
    assert not at.exception, [e.message for e in at.exception]
    # Lo que el Optimizer recibe, leído antes de salir de Mi Plan.
    at.optimizer_capital_after_load = at.session_state["optimizer_total_capital"]
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        at.switch_page("views/7_Simulaciones.py").run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def _shown(at: AppTest, key: str):
    """Lo que dibuja el navegador para el widget `key` del sidebar."""
    if key == "horizon_years":
        w = at.sidebar.selectbox(key=key)
        label = w.proto.raw_value if w.proto.set_value else w.proto.options[w.proto.default]
        return int(label.split()[0])          # «15 años»
    if key == "inflation_rate":
        w = at.sidebar.slider(key=key)
        return (list(w.proto.value) if w.proto.set_value else list(w.proto.default))[0]
    w = at.sidebar.number_input(key=key)
    return w.proto.value if w.proto.set_value else w.proto.default


# --------------------------------------------------------------------------- #
#  El plan cargado es lo que se ve                                            #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", [
    "horizon_years", "target_value", "inflation_rate", "contribution_growth_pct",
])
def test_the_loaded_plan_is_what_the_browser_shows(stores, key):  # noqa: F811
    at = _load(stores, _plan())
    assert at.session_state[key] == RUN[key]       # el script ya lo tenía en main
    assert _shown(at, key) == RUN[key]             # main: el default del widget


def test_the_capital_shown_is_the_runs_not_the_profiles(stores):  # noqa: F811
    at = _load(stores, _plan())
    assert at.session_state["initial_value"] == RUN["initial_value"]   # main: 250.000
    assert _shown(at, "initial_value") == RUN["initial_value"]         # main: 100.000


def test_the_simulaciones_capital_comes_from_the_run_first():
    from data.product_ux import plan_load_session_updates

    out = plan_load_session_updates(_plan(), horizon_years=15)
    assert out["initial_value"] == RUN["initial_value"]                 # main: 250.000


def test_the_page_says_the_plan_was_loaded(stores):  # noqa: F811
    at = _load(stores, _plan())
    assert any("ya están en los controles" in s.value for s in at.sidebar.success)


# --------------------------------------------------------------------------- #
#  Controles: lo que hoy funciona sigue igual                                 #
# --------------------------------------------------------------------------- #

def test_control_the_optimizer_keeps_the_profile_capital(stores):  # noqa: F811
    """Decisión del usuario: el Optimizer reparte el capital del perfil."""
    at = _load(stores, _plan())
    assert at.optimizer_capital_after_load == PROFILE["current_capital"]


def test_control_a_plan_without_monte_carlo_does_not_zero_the_goal(stores):  # noqa: F811
    """Lo que el plan no responde no pisa nada: la meta queda en el default, no en 0."""
    at = _load(stores, _plan(mc_summary=None))
    target = at.sidebar.number_input(key="target_value")
    assert _shown(at, "target_value") == target.proto.default
    assert at.session_state["target_value"] == target.proto.default


def test_control_an_edit_after_loading_is_not_overwritten(stores):  # noqa: F811
    """El plan se aplica una vez: lo que el usuario cambia después se queda."""
    at = _load(stores, _plan())
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        at.sidebar.selectbox(key="horizon_years").set_value(25).run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.session_state["horizon_years"] == 25
    assert not any("ya están en los controles" in s.value for s in at.sidebar.success)
