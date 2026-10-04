"""Oráculo IDEA-3 MENÚ: el menú normal baja de 16 entradas a 11 fusionando pantallas.

Decisión del usuario (2026-09-30, octava ``/decidir-proyecto``), la agrupación
intermedia:

- Allocation y Comité salen del menú; ya se llega desde Optimizer y desde la ficha
  de Stock Analysis y el Chat.
- About se abre desde Settings.
- Watchlist es una pestaña del Screener.
- Alertas y Track Record son una sola página con dos pestañas.

Ninguna página se borra ni cambia de URL: las que salen del menú quedan registradas
con ``visibility="hidden"``, así que ``switch_page``, los deep-links y las URLs
directas siguen andando (``test_direct_page_entry``). Las fusiones son páginas
contenedoras que corren las originales dentro de una pestaña (``shared.run_view``).
Un ``st.stop()`` de Streamlit detiene el script entero y no se puede atrapar, así
que las páginas embebibles cortan con ``shared.stop_view``: dentro de una pestaña
termina sólo esa vista, y suelta es ``st.stop()``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from data.preferences import UserPreferences

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "app.py"
VIEWS = ROOT / "dashboard" / "views"

VISIBLE = {
    "<home>", "18_Chat.py",
    "12_Plan.py", "3_Portfolio.py", "5_Optimizer.py",
    "19_Screener_Watchlist.py", "2_Stock_Analysis.py",
    "7_Simulaciones.py", "6_Backtesting.py",
    # EO-2a (ADR 0001): «Supuestos» muestra las Fuentes y el Desacuerdo de cada Clase,
    # la base de toda proyección desde EO-4; el ADR pide el Desacuerdo siempre visible.
    "21_Supuestos.py",
    "20_Seguimiento.py",
    "9_Settings.py",
}
HIDDEN = {
    "1_Screener.py", "11_Watchlist.py", "8_Alertas.py", "13_Track_Record.py",
    "10_About.py", "15_Comite.py", "4_Allocation.py",
}
DEV_ONLY = {"14_Eval_IA.py", "16_Calidad_Datos.py", "17_Macro_RAG.py"}


def _registered_pages() -> dict[str, str]:
    """Cada ``st.Page(...)`` de ``app.py`` → su visibilidad."""
    pages: dict[str, str] = {}
    for node in ast.walk(ast.parse(APP.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Page"):
            continue
        target = ast.unparse(node.args[0])
        name = next((p for p in VISIBLE | HIDDEN | DEV_ONLY if p in target), "<home>")
        vis = next((ast.literal_eval(k.value) for k in node.keywords if k.arg == "visibility"),
                   "visible")
        pages[name] = vis
    return pages


def test_the_everyday_menu_has_twelve_entries():
    pages = _registered_pages()
    visible = {p for p, v in pages.items() if v == "visible" and p not in DEV_ONLY}
    assert visible == VISIBLE


def test_the_pages_that_left_the_menu_are_still_registered_hidden():
    pages = _registered_pages()
    assert {p: pages.get(p) for p in HIDDEN} == {p: "hidden" for p in HIDDEN}


def test_the_alerts_shortcuts_land_on_the_merged_page():
    from dashboard import shared

    src = (ROOT / "dashboard" / "shared.py").read_text(encoding="utf-8")
    assert '"page": "20_Seguimiento.py"' in src
    assert '"page": "8_Alertas.py"' not in src
    assert '_pages_dir / "20_Seguimiento.py"' in APP.read_text(encoding="utf-8")
    assert callable(shared.run_view)


# --------------------------------------------------------------------------- #
#  Las páginas contenedoras                                                   #
# --------------------------------------------------------------------------- #

def _texts(at) -> str:
    chunks = []
    for coll in (at.markdown, at.caption, at.warning, at.info, at.error,
                 at.subheader, at.header, at.title):
        chunks += [getattr(e, "value", "") or "" for e in coll]
    return "\n".join(chunks)


def test_screener_page_has_a_watchlist_tab_that_survives_the_screener_stopping():
    """Sin universo el Screener corta temprano; la pestaña Watchlist igual se dibuja."""
    at = AppTest.from_file(str(VIEWS / "19_Screener_Watchlist.py"), default_timeout=60)
    at.session_state["user_prefs"] = UserPreferences()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == ["🏠 Screener", "📋 Watchlist"]
    text = _texts(at)
    assert "no está inicializada" in text          # el Screener cortó
    assert "Tu watchlist está vacía" in text       # y la Watchlist se dibujó igual


def test_seguimiento_page_runs_alerts_and_track_record(monkeypatch, tmp_path):
    import analysis.track_record as tr
    from alerts import store

    monkeypatch.setattr(store, "alert_store", store.AlertStore(db_path=tmp_path / "alerts.db"))
    monkeypatch.setattr(tr, "track_record_store", tr.TrackRecordStore(tmp_path / "tr.db"))
    at = AppTest.from_file(str(VIEWS / "20_Seguimiento.py"), default_timeout=60)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    labels = [t.label for t in at.tabs]      # Alertas trae sus propias pestañas adentro
    assert labels[0] == "🔔 Alertas" and "📒 Track Record" in labels
    text = _texts(at)
    # Con el store vacío el Track Record avisa y corta con stop_view: la pestaña
    # termina ahí y la página no se cae.
    assert "Todavía no hay recomendaciones evaluadas" in text


def test_settings_opens_about():
    """Un botón con ``switch_page``: ``st.page_link`` rompe con la página suelta."""
    src = (VIEWS / "9_Settings.py").read_text(encoding="utf-8")
    assert "switch_page" in src and "10_About.py" in src


# --------------------------------------------------------------------------- #
#  stop_view: dentro de una pestaña corta la vista; suelta es st.stop()        #
# --------------------------------------------------------------------------- #

def test_stop_view_outside_a_tab_is_st_stop(monkeypatch):
    from dashboard import shared

    calls = []
    monkeypatch.setattr(shared.st, "stop", lambda: calls.append(1))
    shared.stop_view()
    assert calls == [1]


@pytest.mark.parametrize("page", ["11_Watchlist.py", "13_Track_Record.py", "1_Screener.py"])
def test_embeddable_pages_stop_with_stop_view(page):
    src = (VIEWS / page).read_text(encoding="utf-8")
    assert "st.stop()" not in src
    assert "stop_view()" in src
