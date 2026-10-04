"""Oráculo EO-0: la pestaña «Mis Metas» simula con los supuestos de la principal.

La pestaña de metas de Simulaciones multiplicaba el rendimiento y la volatilidad
por una escala del selector «Perfil de riesgo» (``_PLAN_MC_SCALES``), encima del
haircut global de ``MONTE_CARLO``: con Conservador —la primera opción, la que
aparece sin tocar nada— el rendimiento quedaba ×0,56 y la volatilidad ×1,265,
mientras la pestaña principal corre con escala 1,0. Las dos pestañas proyectaban
el mismo plan con supuestos distintos, sin decirlo (ADR 0001, Consecuencias).

Decisión del usuario (sesión de diseño del 2026-10-03, ADR 0001): el Perfil no toca
la Estimación. El selector se queda —elige el perfil del optimizador por metas y
el que nombra el PDF—, pero deja de escalar la simulación. La pestaña «Comparar
perfiles» conserva su escala hasta EO-4 (decisión del usuario, 2026-10-04).

Se ejercita la página real (``AppTest``) y se graban las llamadas: la referencia es
lo que recibe la corrida de la pestaña principal, no el código de la pestaña de
metas.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_cash_flow_oracle import _flat_history

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/7_Simulaciones.py"
PROFILES = ("conservative", "moderate", "aggressive")

# Una meta que no llega al objetivo de probabilidad, para que la página también
# calcule el ahorro necesario (la segunda simulación de la pestaña).
HARD_GOAL = {
    "name": "Retiro",
    "goal_type": "retirement",
    "target_amount_today": 5_000_000.0,
    "horizon_years": 10,
    "priority": 1,
    "expected_inflation": 3.0,
    "annual_contribution": 0.0,
    "allocated_capital": 0.0,
    "notes": "",
}


def _scales(kwargs: dict) -> tuple[float, float]:
    """Las escalas efectivas de una llamada: sin el argumento, la firma pone 1,0."""
    return (float(kwargs.get("vol_scale", 1.0)), float(kwargs.get("return_scale", 1.0)))


@pytest.fixture
def calls(monkeypatch):
    from dashboard import shared
    from data.preferences import UserPreferences

    recorded: dict[str, list[dict]] = {}

    def recorder(name):
        real = getattr(shared, name)

        def _record(**kwargs):
            recorded.setdefault(name, []).append(dict(kwargs))
            return real(**kwargs)

        return _record

    for name in ("cached_monte_carlo", "cached_goal_simulation", "cached_goal_savings_target"):
        monkeypatch.setattr(shared, name, recorder(name))
    monkeypatch.setattr(shared, "get_user_prefs", lambda: UserPreferences())
    monkeypatch.setattr(shared, "seed_session_defaults_from_profile", lambda *a, **k: None)
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.06)):
        yield recorded


def _click(app, label: str):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception, [e.message for e in app.exception]


def _run_both_tabs(profile: str):
    app = AppTest.from_file(str(PAGE), default_timeout=180)
    app.session_state["universe"] = ["AAPL", "MSFT"]
    app.session_state["n_sims"] = 1_000
    app.session_state["plan_n_sims"] = 1_000
    app.session_state["goals_list"] = [dict(HARD_GOAL)]
    app.session_state["plan_profile"] = profile
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    _click(app, "▶ Ejecutar simulación Monte Carlo")
    _click(app, "▶ Simular plan completo")
    return app


@pytest.mark.parametrize("profile", PROFILES)
def test_the_goals_tab_simulates_with_the_main_tabs_scales(calls, profile):
    _run_both_tabs(profile)
    main = _scales(calls["cached_monte_carlo"][-1])
    assert main == (1.0, 1.0)                       # la principal no escala
    [goal_run] = calls["cached_goal_simulation"]
    assert _scales(goal_run) == main                # main: (1.15, 0.70) con Conservador


@pytest.mark.parametrize("profile", PROFILES)
def test_the_savings_advice_solves_with_the_main_tabs_scales(calls, profile):
    """El «ahorro necesario» de cada meta corre otra simulación: la misma regla."""
    _run_both_tabs(profile)
    main = _scales(calls["cached_monte_carlo"][-1])
    advice = calls.get("cached_goal_savings_target", [])
    assert advice, "la meta llegó al objetivo: el consejo de ahorro no se calculó"
    assert {_scales(c) for c in advice} == {main}
