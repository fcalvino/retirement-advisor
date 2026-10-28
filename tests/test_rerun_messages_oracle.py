"""AUDIT-RESIDUALES (mensajes) — los mensajes que se dibujaban justo antes de un ``st.rerun()`` sí se ven.

Un ``st.rerun()`` descarta lo que el script dibujó en esa corrida, así que un ``st.success(...)`` seguido
de ``st.rerun()`` no llega a la pantalla. Pasaba en cinco lugares, el más grave en Alertas: «▶ Ejecutar
análisis ahora» registra las alertas pero el resumen de lo que detectó (o «Sin cambios significativos»)
se perdía y el usuario no sabía qué pasó. La referencia correcta era ``3_Portfolio.py`` (``_portfolio_msg``
con ``pop``); ahora es ``flash``/``show_flash`` en ``dashboard/shared.py``.

Con AppTest; sin red y sin tocar la base, las preferencias ni el ``.env`` reales.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_goals_state_oracle import _goal, goals_page  # noqa: F401  (fixture)

VIEWS = Path(__file__).resolve().parents[1] / "dashboard" / "views"
ALERTAS = str(VIEWS / "8_Alertas.py")
SETTINGS = str(VIEWS / "9_Settings.py")


def _texts(at: AppTest) -> str:
    chunks: list[str] = []
    for coll in (at.success, at.info, at.warning, at.markdown, at.caption):
        chunks += [getattr(e, "value", "") or "" for e in coll]
    return "\n".join(chunks)


# --------------------------------------------------------------------------- #
#  Alertas                                                                     #
# --------------------------------------------------------------------------- #

def _alert(severity: str, message: str, explanation: str = "") -> SimpleNamespace:
    return SimpleNamespace(severity=severity, message=message, explanation=explanation)


@pytest.fixture
def alertas(tmp_path, monkeypatch):
    """``alertas(fired)`` abre Alertas y deja que «Ejecutar análisis» devuelva esas alertas."""
    from alerts import store
    from dashboard import shared

    monkeypatch.setattr(shared, "_fetch_universe_parallel", lambda *a, **k: [])
    monkeypatch.setattr(store, "alert_store", store.AlertStore(db_path=tmp_path / "alerts.db"))

    def open_page(fired: list) -> AppTest:
        monkeypatch.setattr(shared, "run_alert_engine", lambda *a, **k: fired)
        at = AppTest.from_file(ALERTAS, default_timeout=60)
        at.session_state["universe"] = ["AAPL", "MSFT"]
        at.run()
        assert not at.exception, [str(e)[:300] for e in at.exception]
        return at

    return open_page


def _run_analysis(at: AppTest) -> AppTest:
    next(b for b in at.button if b.label.startswith("▶ Ejecutar análisis")).click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def test_the_alerts_that_were_detected_are_shown_after_the_run(alertas):
    fired = [_alert("critical", "AAPL cayó 20 %", "Pérdida fuerte"), _alert("info", "MSFT subió su score")]
    text = _texts(_run_analysis(alertas(fired)))
    assert "2 alertas detectadas y registradas" in text
    assert "AAPL cayó 20 %" in text and "MSFT subió su score" in text
    assert "Pérdida fuerte" in text


def test_more_than_ten_alerts_say_how_many_are_left(alertas):
    fired = [_alert("warning", f"Alerta {i}") for i in range(13)]
    text = _texts(_run_analysis(alertas(fired)))
    assert "13 alertas detectadas" in text
    assert "Alerta 9" in text and "Alerta 10" not in text
    assert "y 3 más" in text


def test_a_run_without_alerts_says_so(alertas):
    assert "Sin cambios significativos detectados" in _texts(_run_analysis(alertas([])))


def test_the_summary_is_shown_once(alertas):
    at = _run_analysis(alertas([_alert("info", "MSFT subió su score")]))
    at.run()
    assert "MSFT subió su score" not in _texts(at)


def test_a_mute_confirms_itself(alertas):
    at = alertas([])
    next(b for b in at.button if b.label == "➕ Agregar").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert "Silenciado: *" in _texts(at)


# --------------------------------------------------------------------------- #
#  Settings                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture
def settings(tmp_path, monkeypatch):
    from dashboard import shared
    from data import preferences as prefs_mod

    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(shared, "usd_ars_quote", lambda *a, **k: None)         # sin red
    monkeypatch.setattr(shared, "clear_data_cache", lambda: None)             # no borra el caché real
    monkeypatch.setattr(shared, "_save_ai_config_to_env", lambda *a, **k: None)

    def open_page() -> AppTest:
        at = AppTest.from_file(SETTINGS, default_timeout=60)
        at.session_state["user_prefs"] = prefs_mod.UserPreferences()
        at.session_state["universe"] = ["AAPL"]
        at.session_state["active_universe_key"] = "default"
        at.run()
        assert not at.exception, [str(e)[:300] for e in at.exception]
        return at

    return open_page


def test_saving_the_parallel_quote_confirms_itself(settings):
    at = settings()
    at.number_input(key="usd_ars_parallel_input").set_value(1500.0)
    at.button(key="save_usd_ars_parallel").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert "Cotización guardada" in _texts(at)


def test_clearing_the_parallel_quote_says_so(settings):
    at = settings()
    at.button(key="save_usd_ars_parallel").click().run()      # el campo arranca en 0: borra
    assert "Paralelo borrado" in _texts(at)


def test_clearing_the_cache_confirms_itself(settings):
    at = settings()
    next(b for b in at.button if "Limpiar todo el caché" in b.label).click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert "Caché limpiado" in _texts(at)


# --------------------------------------------------------------------------- #
#  Mis Metas                                                                   #
# --------------------------------------------------------------------------- #

def test_adding_a_goal_confirms_itself(goals_page):  # noqa: F811
    at = goals_page([_goal("A", 1)])
    at.button(key="add_goal_btn").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert "agregada al plan" in _texts(at)
    assert len(at.session_state["goals_list"]) == 2


def test_flash_rejects_a_kind_streamlit_does_not_have():
    from dashboard.shared import flash

    with pytest.raises(ValueError, match="flash kind"):
        flash("k", "warn", "texto")
