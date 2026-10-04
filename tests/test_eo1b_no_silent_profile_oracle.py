"""Oráculo EO-1b: sin Perfil no hay Postura (ADR 0001).

El Perfil es la Postura del inversor (glosario): topes, aversión, Exigencia. Hasta
EO-1b, todo camino sin perfil caía en Conservador en silencio —``UserPreferences``
nacía con ``default_profile = "Conservador"``, el Optimizer arrancaba ahí, el reset
de Settings volvía ahí— y la pestaña «Mis Metas» de Simulaciones arrancaba en
Conservador aunque el usuario hubiera elegido otro: un usuario con Agresivo
optimizaba por metas como Conservador.

Decisiones del usuario (2026-10-04):

* **D1 (a).** Hay Perfil sólo si el inversor lo eligió: la marca ``profile_chosen``
  la ponen el onboarding y el radio del Optimizer. Un archivo de preferencias que
  ya completó el onboarding cuenta como elegido —el usuario real conserva Agresivo
  sin que se le pregunte de nuevo—.
* **D2 (a).** Sin Perfil, lo que dimensiona (el Optimizer, «Optimizar para mis
  metas», la Asignación) pide elegir y no corre; las simulaciones corren igual,
  porque desde EO-0 no dependen del perfil. El reset de Settings deja «sin elegir».
"""

from __future__ import annotations

import json


def _load(tmp_path, monkeypatch, raw: dict):
    from data import preferences as prefs_mod

    path = tmp_path / "user_preferences.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", path)
    return prefs_mod.UserPreferences.load()


# --------------------------------------------------------------------------- #
#  D1: cuándo hay un Perfil                                                    #
# --------------------------------------------------------------------------- #

def test_a_fresh_preferences_object_has_no_profile():
    from data.preferences import UserPreferences

    assert UserPreferences().chosen_profile_key is None      # main: "Conservador"


def test_an_onboarded_file_from_before_the_mark_keeps_its_profile(tmp_path, monkeypatch):
    """Lo que tiene hoy el usuario real: onboarding hecho, Agresivo, sin la marca."""
    prefs = _load(tmp_path, monkeypatch, {
        "default_profile": "Agresivo", "risk_tolerance": "agresiva",
        "onboarded": True, "age": 36,
    })
    assert prefs.chosen_profile_key == "aggressive"


def test_a_file_that_never_onboarded_has_no_profile(tmp_path, monkeypatch):
    """La plantilla versionada dice Moderado sin que nadie lo haya elegido."""
    prefs = _load(tmp_path, monkeypatch, {
        "default_profile": "Moderado", "risk_tolerance": "moderada", "onboarded": False,
    })
    assert prefs.chosen_profile_key is None


# --------------------------------------------------------------------------- #
#  D2: el Optimizer pide elegir                                                #
# --------------------------------------------------------------------------- #

def _optimizer(prefs, tmp_path):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from portfolio.tracker import Portfolio

    page = Path(__file__).resolve().parents[1] / "dashboard/views/5_Optimizer.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def test_without_a_profile_the_optimizer_asks_and_does_not_run(tmp_path):
    from data.preferences import UserPreferences

    at = _optimizer(UserPreferences(), tmp_path)
    assert not [b for b in at.button if b.label == "🚀 Ejecutar Optimización"]
    assert any("Elegí tu perfil" in (i.value or "") for i in at.info)   # main: Conservador
    [radio] = [r for r in at.sidebar.radio if r.label == "Perfil de riesgo"]
    assert radio.value is None


def test_with_a_chosen_profile_the_optimizer_starts_there(tmp_path):
    from data.preferences import UserPreferences

    prefs = UserPreferences(default_profile="Agresivo", profile_chosen=True)
    at = _optimizer(prefs, tmp_path)
    [radio] = [r for r in at.sidebar.radio if r.label == "Perfil de riesgo"]
    assert "Agresivo" in radio.value
    assert [b for b in at.button if b.label == "🚀 Ejecutar Optimización"]


# --------------------------------------------------------------------------- #
#  «Mis Metas» arranca en el perfil elegido                                    #
# --------------------------------------------------------------------------- #

GOAL = {
    "name": "Retiro", "goal_type": "retirement", "target_amount_today": 500_000.0,
    "horizon_years": 15, "priority": 1, "expected_inflation": 3.0,
    "annual_contribution": 0.0, "allocated_capital": 0.0, "notes": "",
}


class _Recorded(Exception):
    """Corta la optimización por metas después de grabar lo que recibió."""


def _simulaciones(prefs, monkeypatch, recorded: list):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dashboard import shared

    def _record(**kwargs):
        recorded.append(kwargs)
        raise _Recorded

    monkeypatch.setattr(shared, "get_user_prefs", lambda: prefs)
    monkeypatch.setattr(shared, "seed_session_defaults_from_profile", lambda *a, **k: None)
    monkeypatch.setattr(shared, "cached_goal_optimization", _record)
    page = Path(__file__).resolve().parents[1] / "dashboard/views/7_Simulaciones.py"
    at = AppTest.from_file(str(page), default_timeout=120)
    at.session_state["goals_list"] = [dict(GOAL)]
    at.session_state["optimizer_scored"] = [{"symbol": "AAPL", "adjusted_score": 70.0}]
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def test_the_goals_tab_starts_on_the_chosen_profile_and_optimizes_with_it(monkeypatch):
    from data.preferences import UserPreferences

    recorded: list = []
    at = _simulaciones(UserPreferences(default_profile="Agresivo", profile_chosen=True),
                       monkeypatch, recorded)
    assert at.session_state["plan_profile"] == "aggressive"     # main: "conservative"
    at.button(key="optimize_for_goals_btn").click().run()
    assert [r["profile_key"] for r in recorded] == ["aggressive"]


def test_without_a_profile_the_goals_tab_does_not_optimize(monkeypatch):
    from data.preferences import UserPreferences

    at = _simulaciones(UserPreferences(), monkeypatch, [])
    assert at.button(key="optimize_for_goals_btn").disabled      # main: optimiza como Conservador
    assert at.session_state["plan_profile"] is None


# --------------------------------------------------------------------------- #
#  El reset de Settings deja «sin elegir»                                      #
# --------------------------------------------------------------------------- #

def test_the_settings_reset_leaves_no_profile(tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dashboard import shared
    from data import preferences as prefs_mod

    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(shared, "usd_ars_quote", lambda *a, **k: None)   # sin red
    prefs = prefs_mod.UserPreferences(default_profile="Agresivo", profile_chosen=True,
                                      risk_tolerance="agresiva", onboarded=True, age=40)
    page = Path(__file__).resolve().parents[1] / "dashboard/views/9_Settings.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["universe"] = ["AAPL"]
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    next(b for b in at.button if "Sí, resetear preferencias" in b.label).click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    reset = at.session_state["user_prefs"]
    assert reset.chosen_profile_key is None                      # main: Conservador
    assert reset.default_profile == ""
    assert "optimizer_profile_label" not in at.session_state


# --------------------------------------------------------------------------- #
#  La Asignación pide elegir                                                   #
# --------------------------------------------------------------------------- #

def _allocation(prefs, tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dashboard import shared
    from portfolio.tracker import Portfolio

    monkeypatch.setattr(shared, "get_user_prefs", lambda: prefs)
    page = Path(__file__).resolve().parents[1] / "dashboard/views/4_Allocation.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def test_without_a_profile_the_allocation_asks(tmp_path, monkeypatch):
    from data.preferences import UserPreferences

    at = _allocation(UserPreferences(), tmp_path, monkeypatch)
    assert any("Elegí tu perfil" in (i.value or "") for i in at.info)
    assert not any("perfil **Conservador**" in (c.value or "") for c in at.caption)   # main


def test_with_a_chosen_profile_the_allocation_uses_it(tmp_path, monkeypatch):
    from data.preferences import UserPreferences

    prefs = UserPreferences(default_profile="Agresivo", profile_chosen=True)
    at = _allocation(prefs, tmp_path, monkeypatch)
    assert any("perfil **Agresivo**" in (c.value or "") for c in at.caption)


# --------------------------------------------------------------------------- #
#  El onboarding no preselecciona la tolerancia al riesgo                     #
# --------------------------------------------------------------------------- #

def _settings(prefs, tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dashboard import shared
    from data import preferences as prefs_mod

    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(shared, "usd_ars_quote", lambda *a, **k: None)   # sin red
    monkeypatch.setattr(shared, "get_user_prefs", lambda: prefs)
    page = Path(__file__).resolve().parents[1] / "dashboard/views/9_Settings.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["universe"] = ["AAPL"]
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def test_the_wizard_does_not_preselect_a_risk_tolerance(tmp_path, monkeypatch):
    from data.preferences import UserPreferences

    prefs = UserPreferences()
    at = _settings(prefs, tmp_path, monkeypatch)
    assert at.radio(key="settings_onb_risk").value is None       # main: «conservadora»
    next(b for b in at.button if "Guardar mi perfil" in b.label).click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert at.session_state["user_prefs"].chosen_profile_key is None
    assert any("tolerancia al riesgo" in (w.value or "") for w in at.warning)


def test_saving_the_wizard_with_a_choice_records_it(tmp_path, monkeypatch):
    from data.preferences import UserPreferences

    prefs = UserPreferences()
    at = _settings(prefs, tmp_path, monkeypatch)
    at.radio(key="settings_onb_risk").set_value("agresiva")
    next(b for b in at.button if "Guardar mi perfil" in b.label).click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert at.session_state["user_prefs"].chosen_profile_key == "aggressive"


def test_the_browser_shows_the_chosen_profile_after_adding_the_first_goal(monkeypatch):
    """La QA en vivo: sin metas el selector no existe, así que el valor sembrado en
    la sesión no viaja al navegador (el mecanismo de PLAN-LOAD-WIDGETS) y, al
    agregar la primera meta, el navegador dibujaba su primera opción, Conservador."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dashboard import shared
    from data.preferences import UserPreferences

    prefs = UserPreferences(default_profile="Agresivo", profile_chosen=True)
    monkeypatch.setattr(shared, "get_user_prefs", lambda: prefs)
    monkeypatch.setattr(shared, "seed_session_defaults_from_profile", lambda *a, **k: None)
    page = Path(__file__).resolve().parents[1] / "dashboard/views/7_Simulaciones.py"
    at = AppTest.from_file(str(page), default_timeout=120)
    at.run()
    at.button(key="add_goal_btn").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    w = at.selectbox(key="plan_profile")
    shown = w.proto.raw_value if w.proto.set_value else w.proto.options[w.proto.default]
    assert "Agresivo" in shown                                   # main y la QA: Conservador
