"""Oráculo WD-STRATEGY-CONTRIB: con estrategia de retiro, el ahorro no entra y se dice.

Con una estrategia de retiro activa, ``MonteCarloSimulator.run`` pasa por
``apply_withdrawal_strategy``, que no recibe los aportes. Medido el 2026-09-30 sobre
los planes del usuario: con y sin ahorro, la proyección es idéntica en 5 de 5; en la
app, 2.000/mes de ahorro y un retiro fijo del 4 % bajan el P10 de $2,13 M a $365 K,
y la pantalla no dice que el ahorro quedó afuera (el sidebar sigue mostrando
«≈ $24.000/año, en doce depósitos»). Banda 1.

Decisión del usuario (2026-09-30): la estrategia sigue significando «ya estás
retirado»; el ahorro **no** se suma, y el motor y la pantalla lo dicen. Ningún número
se mueve, así que el oráculo fija las dos mitades: el aviso aparece y la proyección es
la misma que sin ahorro. Mercado determinístico (historia plana).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from portfolio.decumulation import WithdrawalStrategy
from portfolio.monte_carlo import MonteCarloSimulator
from tests.test_cash_flow_oracle import _flat_history

CONTRIB = 24_000.0
STRATEGY = WithdrawalStrategy.fixed_real(4_000.0)


def _run(**kw):
    sim = MonteCarloSimulator(["AAPL"], seed=11)
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(0.05)):
        return sim.run(horizon_years=10, n_sims=200, initial_value=100_000.0,
                       withdrawal_growth_rate=0.03, **kw)


def _mentions_ignored_savings(result) -> bool:
    return any("ahorro" in w and "estrategia de retiro" in w for w in result.warnings)


def test_the_result_says_the_savings_were_left_out():
    result = _run(annual_contribution=CONTRIB, withdrawal_strategy=STRATEGY)
    assert _mentions_ignored_savings(result)
    assert result.contribution_ignored_by_strategy == pytest.approx(CONTRIB)


def test_the_projection_is_the_strategy_without_savings():
    """La decisión: no se suma. Byte-idéntico a la misma estrategia sin ahorro."""
    with_savings = _run(annual_contribution=CONTRIB, withdrawal_strategy=STRATEGY)
    without = _run(withdrawal_strategy=STRATEGY)
    for field in ("p10_terminal", "median_terminal", "p90_terminal",
                  "prob_achieve_target_pct", "prob_sustain_real_pct", "median_legacy"):
        assert getattr(with_savings, field) == getattr(without, field), field


def test_control_accumulation_with_savings_has_no_such_warning():
    result = _run(annual_contribution=CONTRIB)
    assert not _mentions_ignored_savings(result)
    assert result.contribution_ignored_by_strategy == 0.0


def test_control_a_strategy_without_savings_has_no_such_warning():
    result = _run(withdrawal_strategy=STRATEGY)
    assert not _mentions_ignored_savings(result)
    assert result.contribution_ignored_by_strategy == 0.0


def test_a_legacy_negative_withdrawal_is_savings_too():
    """``annual_withdrawal < 0`` se lee como aporte: con estrategia también queda afuera."""
    result = _run(annual_withdrawal=-CONTRIB, withdrawal_strategy=STRATEGY)
    assert result.contribution_ignored_by_strategy == pytest.approx(CONTRIB)


# --------------------------------------------------------------------------- #
#  La pantalla: el aviso del sidebar sale de la misma estrategia que el motor   #
# --------------------------------------------------------------------------- #

@pytest.fixture
def page(monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dashboard import shared
    from data.preferences import UserPreferences

    monkeypatch.setattr(shared, "get_user_prefs", lambda: UserPreferences())
    monkeypatch.setattr(shared, "seed_session_defaults_from_profile", lambda *a, **k: None)
    path = Path(__file__).resolve().parents[1] / "dashboard/views/7_Simulaciones.py"

    def open_page(**state):
        app = AppTest.from_file(str(path), default_timeout=60)
        app.session_state["universe"] = ["AAPL", "MSFT"]
        app.session_state["monthly_savings"] = 2_000
        for k, v in state.items():
            app.session_state[k] = v
        app.run()
        assert not app.exception, [e.message for e in app.exception]
        return app

    return open_page


def _sidebar_warns(app) -> bool:
    return any("no entra" in c.value for c in app.sidebar.caption)


def test_the_sidebar_warns_in_the_same_run_the_strategy_is_chosen(page):
    app = page()
    assert not _sidebar_warns(app)
    app.selectbox(key="sim_wd_kind").select("fixed_real").run()
    assert not app.exception, [e.message for e in app.exception]
    assert _sidebar_warns(app)


def test_a_strategy_with_nothing_to_withdraw_is_not_a_strategy(page):
    """Monto 0: el builder no arma estrategia, el motor suma el ahorro y no hay aviso."""
    app = page(withdrawal_kind="fixed_real", withdrawal_amount=0.0)
    assert not _sidebar_warns(app)
