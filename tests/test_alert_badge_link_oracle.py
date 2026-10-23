"""Oráculo ALERT-BADGE-LINK: el aviso de alertas sin leer del sidebar lleva a las alertas.

El sidebar de ``dashboard/app.py`` dibujaba dos controles para lo mismo. El botón
«🔔 Ver N alertas sin leer» navega con ``st.switch_page`` a ``20_Seguimiento.py``; el
link «🔴 N alertas sin leer →» apuntaba a ``#alertas``, un ancla que no existe en
ninguna página, así que al hacer click solo cambiaba la URL
(``/Stock_Analysis#alertas``) y el usuario se quedaba donde estaba. Queda un solo
control, el botón, que va a la página donde se leen las alertas desde cualquier página.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dashboard import shared

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "dashboard" / "app.py")
BADGE_KEY = "_sidebar_alert_badge"
UNREAD = 24


@pytest.fixture
def unread(monkeypatch):
    monkeypatch.setattr(shared, "unread_alert_count", lambda: UNREAD)


def _run(page: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    if page:
        at.switch_page(page)
    at.run()
    assert not at.exception
    return at


@pytest.mark.parametrize("page", [None, "views/2_Stock_Analysis.py"])
def test_sidebar_has_no_link_to_a_missing_anchor(unread, page):
    at = _run(page)
    links = [m.value for m in at.sidebar.markdown if "](#" in (m.value or "")]
    assert links == [], f"ancla sin destino en el sidebar: {links}"


@pytest.mark.parametrize("page", [None, "views/2_Stock_Analysis.py"])
def test_sidebar_has_exactly_one_unread_alerts_control_and_it_is_a_button(unread, page):
    at = _run(page)
    mentions = [m.value for m in at.sidebar.markdown if "sin leer" in (m.value or "")]
    buttons = [b for b in at.sidebar.button if b.key == BADGE_KEY]
    assert mentions == []
    assert len(buttons) == 1
    assert str(UNREAD) in buttons[0].label and "sin leer" in buttons[0].label


def test_the_button_switches_to_the_page_that_shows_the_alerts(unread, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "streamlit.switch_page", lambda page, **kw: calls.append(str(page))
    )
    at = _run("views/2_Stock_Analysis.py")
    at.sidebar.button(key=BADGE_KEY).click().run()
    assert [Path(c).name for c in calls] == ["20_Seguimiento.py"]
