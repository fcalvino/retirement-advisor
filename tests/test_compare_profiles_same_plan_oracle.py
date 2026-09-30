"""Oráculo COMPARE-NO-SAVINGS: «Comparar Perfiles» corre el mismo plan que la pestaña principal.

La pestaña «🔀 Comparar Perfiles» de Simulaciones llamaba a ``cached_monte_carlo`` sin
``annual_contribution``, sin drags y sin la estrategia de retiro, mientras la
pestaña Monte Carlo sí los pasa. Medido el 2026-09-30 sobre el perfil real del
usuario (2.000/mes, meta 500 K): probabilidad de meta 2,5 % / 5,6 % / 14,5 % por
perfil, contra 97,5 % / 99,0 % / 99,9 % con su ahorro; en la app, con los mismos
inputs, P10 Agresivo $610.009 contra $2.127.991 en la pestaña principal, sin una
palabra sobre el ahorro. Banda 1: es el número con el que se elige un perfil.

Decisión del usuario (2026-09-30): los tres perfiles usan exactamente los mismos
supuestos que la pestaña principal; sólo cambian ``vol_scale`` y ``return_scale``.

Se ejercita la página real (``AppTest``): se graba cada llamada a
``cached_monte_carlo`` y se compara lo que recibió la corrida principal con lo que
recibió cada perfil. La referencia es la llamada principal, no el código bajo prueba
de la pestaña.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_cash_flow_oracle import _flat_history

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/7_Simulaciones.py"
SCALE_KEYS = {"vol_scale", "return_scale"}


@pytest.fixture
def calls(monkeypatch):
    from dashboard import shared
    from data.preferences import UserPreferences

    real = shared.cached_monte_carlo
    recorded: list[dict] = []

    def recorder(**kwargs):
        recorded.append(dict(kwargs))
        return real(**kwargs)

    monkeypatch.setattr(shared, "cached_monte_carlo", recorder)
    monkeypatch.setattr(shared, "get_user_prefs", lambda: UserPreferences())
    monkeypatch.setattr(shared, "seed_session_defaults_from_profile", lambda *a, **k: None)
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        yield recorded


def _app():
    app = AppTest.from_file(str(PAGE), default_timeout=120)
    app.session_state["universe"] = ["AAPL", "MSFT"]
    app.session_state["n_sims"] = 1_000
    app.session_state["monthly_savings"] = 2_000
    app.session_state["contribution_growth_pct"] = 2.0
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    return app


def _click(app, label: str):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception, [e.message for e in app.exception]


def test_every_profile_runs_the_plan_the_main_tab_runs(calls):
    app = _app()
    _click(app, "▶ Ejecutar simulación Monte Carlo")
    main = calls[-1]
    assert main["annual_contribution"] == pytest.approx(24_000.0)

    calls.clear()
    _click(app, "▶ Comparar los 3 perfiles")
    assert len(calls) == 3
    expected = {k: v for k, v in main.items() if k not in SCALE_KEYS}
    for call in calls:
        assert {k: v for k, v in call.items() if k not in SCALE_KEYS} == expected


def test_the_profiles_still_differ_only_by_their_scales(calls):
    app = _app()
    _click(app, "▶ Comparar los 3 perfiles")
    scales = {(c.get("vol_scale"), c.get("return_scale")) for c in calls}
    assert len(scales) == 3
