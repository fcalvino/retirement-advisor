"""Oráculo N8b: los aportes crecen con su propia tasa, no con la que indexa el gasto.

Hasta N8b ``MonteCarloSimulator._apply_cash_flows`` hacía crecer depósitos y retiros
con el mismo ``withdrawal_growth_rate``. Simulaciones le pasa la inflación, así que
su proyección principal indexaba los aportes, mientras Metas (``portfolio/goals.py``)
los dejaba nominales: dos pantallas contestaban «¿llego?» con supuestos de ahorro
distintos. Medido el 2026-09-30 sobre los planes del usuario: P10 +25–30 %. Y la
palanca «Indexación del gasto» del laboratorio, en acumulación, sólo movía los
aportes: subirla subía el P10 (signo invertido, N8).

Decisión del usuario (2026-09-30): ``contribution_growth_rate`` propio, default 0;
``withdrawal_growth_rate`` mueve sólo el gasto.

Independiente del código bajo prueba: mercado determinístico (historia plana, el
bootstrap devuelve la constante) y referencias escritas como loops desde la
definición en ``tests/test_cash_flow_oracle.py`` más una propia para los retiros.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from config import MONTE_CARLO
from portfolio.monte_carlo import MonteCarloSimulator
from portfolio.sensitivity import METRIC_KEYS, run_sensitivity
from tests.test_cash_flow_oracle import (
    _flat_history,
    _index,
    oracle_monthly_contribution_sequence,
)

HORIZON = 15
RATE = 0.05
CONTRIB = 12_000.0
INITIAL = 50_000.0


def _run(**kw):
    sim = MonteCarloSimulator(["AAPL"], seed=7)
    with patch("portfolio.monte_carlo.get_history",
               side_effect=lambda *a, **k: _flat_history(RATE)):
        return sim.run(horizon_years=HORIZON, n_sims=200, initial_value=INITIAL, **kw)


def _oracle_growing_withdrawals(index: np.ndarray, initial: float, withdrawal: float,
                                years: int, growth: float) -> float:
    """Reference: the year's withdrawal leaves in equal parts, stepping once a year."""
    periods = MONTE_CARLO.withdrawal_periods_per_year
    wealth, previous = initial, 0
    for yr in range(1, years + 1):
        for m in range(1, periods + 1):
            week = round(m * 52 / periods) + (yr - 1) * 52
            wealth *= index[week] / index[previous]
            wealth -= withdrawal / periods * (1.0 + growth) ** (yr - 1)
            previous = week
    return wealth * index[-1] / index[previous]


def test_spending_indexation_leaves_the_savings_nominal():
    """Simulaciones pasa la inflación como withdrawal_growth_rate: el ahorro no crece."""
    result = _run(annual_contribution=CONTRIB, withdrawal_growth_rate=0.03)
    expected = oracle_monthly_contribution_sequence(
        _index(RATE, HORIZON), INITIAL, CONTRIB, HORIZON, growth_rate=0.0)
    assert result.median_terminal == pytest.approx(expected, rel=1e-9)


def test_savings_grow_only_with_their_own_rate():
    result = _run(annual_contribution=CONTRIB, contribution_growth_rate=0.03)
    expected = oracle_monthly_contribution_sequence(
        _index(RATE, HORIZON), INITIAL, CONTRIB, HORIZON, growth_rate=0.03)
    assert result.median_terminal == pytest.approx(expected, rel=1e-9)


def test_withdrawals_still_grow_with_the_spending_rate():
    result = _run(annual_withdrawal=2_000.0, withdrawal_growth_rate=0.03,
                  contribution_growth_rate=0.10)  # no aportes: la tasa del ahorro no pesa
    expected = _oracle_growing_withdrawals(_index(RATE, HORIZON), INITIAL, 2_000.0,
                                           HORIZON, 0.03)
    assert result.median_terminal == pytest.approx(expected, rel=1e-9)


def _oracle_mixed(index, initial, contribution, c_growth, withdrawal, w_growth, years):
    """Reference: deposits and withdrawals on one calendar, each with its own raise.

    Same weeks as the engine's documented cadence; a deposit and a withdrawal on
    the same week — the deposit first (you get paid, then you spend).
    """
    events = []
    for periods, amount, growth, sign, order in (
        (MONTE_CARLO.contribution_periods_per_year, contribution, c_growth, +1.0, 0),
        (MONTE_CARLO.withdrawal_periods_per_year, withdrawal, w_growth, -1.0, 1),
    ):
        for yr in range(1, years + 1):
            for m in range(1, periods + 1):
                week = round(m * 52 / periods) + (yr - 1) * 52
                events.append((week, order, sign * amount / periods * (1.0 + growth) ** (yr - 1)))
    wealth, previous = initial, 0
    for week, _, cash in sorted(events):
        wealth *= index[week] / index[previous]
        wealth += cash
        previous = week
    return wealth * index[-1] / index[previous]


def test_each_direction_grows_with_its_own_rate_in_the_same_plan():
    result = _run(annual_contribution=CONTRIB, contribution_growth_rate=0.02,
                  annual_withdrawal=3_000.0, withdrawal_growth_rate=0.04)
    expected = _oracle_mixed(_index(RATE, HORIZON), INITIAL, CONTRIB, 0.02,
                             3_000.0, 0.04, HORIZON)
    assert result.median_terminal == pytest.approx(expected, rel=1e-9)


def test_in_accumulation_the_spending_lever_moves_nothing():
    base = _run(annual_contribution=CONTRIB, withdrawal_growth_rate=0.0)
    hot = _run(annual_contribution=CONTRIB, withdrawal_growth_rate=0.05)
    for k in METRIC_KEYS:
        assert getattr(hot, k) == getattr(base, k), k


def test_the_lab_labels_the_indexation_lever_not_applicable_in_accumulation():
    """El tornado ya no dibuja el signo invertido: la palanca no toca este plan."""
    def run_fn(params):
        # Sólo importa la palanca de indexación; las otras tres no se miden acá.
        return _run(annual_contribution=CONTRIB,
                    withdrawal_growth_rate=float(params.get("withdrawal_growth_rate", 0.0)))

    res = run_sensitivity(run_fn, {"withdrawal_growth_rate": 0.03}, include_scenarios=False)
    indexation = next(f for f in res.factors if f.key == "inflation")
    assert indexation.applies is False
