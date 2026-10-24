"""COMBINAR-UNIVERSOS: el combo «Agregar tickers de» ofrece todos los universos.

El multiselect del Optimizer tenía `max_selections=2` (Fase 14, 2026-05-25, sin una
razón escrita más que «máx 2 adicionales»), así que el «Select all» que trae
Streamlit 1.65 sólo elegía los dos primeros. El tope sale: «Select all» elige
todos los universos que hay para combinar.

La «x» de «Clear all» no tiene test acá a propósito: el defecto es del frontend
de Streamlit 1.65 (con las etiquetas largas el campo con foco crece una fila, el
botón —centrado— sube al perder el foco en el `pointerdown` y el `pointerup` cae
fuera), y AppTest no ve layout ni punteros. La evidencia es la corrida en vivo
con Playwright; acá sólo se fija el CSS que ancla el botón arriba.
"""

from __future__ import annotations

from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/5_Optimizer.py"


def _optimizer(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from data import preferences as prefs_mod
    from portfolio.tracker import Portfolio

    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "user_preferences.json")
    prefs = prefs_mod.UserPreferences(default_profile="Moderado", profile_chosen=True)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def _combo(at):
    [combo] = [m for m in at.sidebar.multiselect if m.label == "Agregar tickers de"]
    return combo


def test_the_combo_has_no_selection_cap(tmp_path, monkeypatch):
    combo = _combo(_optimizer(tmp_path, monkeypatch))
    # 0 = sin tope en el proto; con `max_selections=2` el frontend corta «Select all» en 2.
    assert combo.proto.max_selections == 0
    assert len(combo.options) > 2


def test_every_other_universe_can_be_combined_at_once(tmp_path, monkeypatch):
    from data.universe_loader import list_universes, load_universe

    at = _optimizer(tmp_path, monkeypatch)
    active = at.session_state["active_universe_key"] if "active_universe_key" in at.session_state else "default"
    others = [k for k in list_universes() if k != active]
    assert len(others) > 2
    _combo(at).set_value(others)
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert list(_combo(at).value) == others
    # El universo combinado es la unión sin duplicados del activo y de todos los demás.
    union = list(dict.fromkeys(list(at.session_state["universe"]) + [t for k in others for t in load_universe(k)]))
    [slider] = [s for s in at.sidebar.slider if s.label == "Tickers a analizar"]
    assert slider.max == len(union)


def test_the_help_no_longer_promises_a_cap(tmp_path, monkeypatch):
    assert "máx 2" not in (_combo(_optimizer(tmp_path, monkeypatch)).help or "")


def test_the_clear_button_is_pinned_so_focus_does_not_move_it():
    """Mitigación del bug de Streamlit 1.65: el botón no se mueve al crecer el campo."""
    src = PAGE.read_text(encoding="utf-8")
    assert '[class*="st-key-optimizer_extra_universes"] button[aria-label="Clear all"]' in src
    assert "align-self: flex-start" in src


def test_all_five_tags_stay_visible_and_the_style_leaves_no_gap():
    """Con los 5 universos el campo no corta el último tag, y el <style> va por `st.html`.

    `st.markdown` deja un elemento de ~16 px de hueco bajo «Combinar universos»; un
    <style> solo en `st.html` no. El alto máximo de ~155 px del campo (Streamlit 1.65)
    se levanta en su contenedor. Los dos son layout: la evidencia es la corrida en vivo.
    """
    src = PAGE.read_text(encoding="utf-8")
    assert 'div:has(> [data-testid="stMultiSelectTagsContainer"])' in src
    assert "max-height: none !important" in src
    assert "st.sidebar.html(" in src
    assert "st.sidebar.markdown(\n    \"\"\"<style>" not in src
