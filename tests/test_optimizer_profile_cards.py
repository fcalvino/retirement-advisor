"""OPT-PROFILE-CARDS: la bienvenida del Optimizer elige perfil desde las tarjetas.

Las tres tarjetas de perfil eran HTML sin acción y los cuatro presets de retiro
fijaban universo y perfil juntos (4 de las 18 combinaciones, pisando el perfil
elegido). Decisión del usuario (2026-10-10): cada tarjeta tiene un botón que
elige el perfil —el mismo camino de guardado que el radio—, los presets se
sacan de la bienvenida y del sidebar, y el universo se elige con el selector
global, que la bienvenida nombra.
"""

from __future__ import annotations

from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/5_Optimizer.py"


def _optimizer(tmp_path, monkeypatch, profile="Conservador"):
    from streamlit.testing.v1 import AppTest

    from data import preferences as prefs_mod
    from portfolio.tracker import Portfolio

    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "user_preferences.json")
    prefs = prefs_mod.UserPreferences(default_profile=profile, profile_chosen=True)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at, prefs


def _radio(at):
    [radio] = [r for r in at.sidebar.radio if r.label == "Perfil de riesgo"]
    return radio


def test_every_profile_card_has_a_button_and_the_active_one_is_marked(tmp_path, monkeypatch):
    at, _ = _optimizer(tmp_path, monkeypatch)
    cards = {b.key: b for b in at.button if (b.key or "").startswith("welcome_profile_")}
    assert set(cards) == {f"welcome_profile_{k}" for k in ("conservative", "moderate", "aggressive")}
    assert cards["welcome_profile_conservative"].disabled
    assert not cards["welcome_profile_aggressive"].disabled


def test_clicking_a_card_picks_that_profile_and_saves_it(tmp_path, monkeypatch):
    at, prefs = _optimizer(tmp_path, monkeypatch)
    at.button(key="welcome_profile_aggressive").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert "Agresivo" in _radio(at).value
    assert prefs.chosen_profile_key == "aggressive"
    assert at.button(key="welcome_profile_aggressive").disabled


def test_no_retirement_presets_are_left(tmp_path, monkeypatch):
    at, _ = _optimizer(tmp_path, monkeypatch)
    assert not [b for b in at.button if "preset" in (b.key or "")]
    assert not [m for m in at.markdown if "preset de retiro" in (m.value or "")]


def test_the_welcome_names_the_universe_and_where_to_change_it(tmp_path, monkeypatch):
    at, _ = _optimizer(tmp_path, monkeypatch)
    assert any("Universo:" in (c.value or "") and "barra lateral" in (c.value or "")
               for c in at.caption)
