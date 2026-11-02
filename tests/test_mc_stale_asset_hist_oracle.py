"""AUDIT-MC-ROBUSTEZ (``_asset_hist`` viejo) — un simulador reutilizado no proyecta con los activos de la corrida anterior.

``MonteCarloSimulator._load_returns`` fija ``_asset_hist`` / ``_asset_weights`` / ``_asset_symbols`` solo cuando
logra bajar los precios; si en una corrida posterior no baja ninguno y cae al respaldo de SPY, esos tres quedan con
los de la corrida anterior y ``_estimation_adjustment`` recentra la serie de SPY sobre la Estimación (y los pesos) de
los activos viejos. Los simuladores se reutilizan (planificador de metas, solver de ahorro).

El arreglo los borra al empezar cada carga. Sin red: las historias son sintéticas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import portfolio.monte_carlo as mc_mod
from portfolio.monte_carlo import MonteCarloSimulator

N = 600
IDX = pd.date_range("2015-01-05", periods=N, freq="W-MON")


def _frame(seed, drift):
    weekly = np.random.default_rng(seed).normal(drift, 0.02, N)
    return pd.DataFrame({"close": 100.0 * np.cumprod(1.0 + weekly)}, index=IDX)


@pytest.fixture
def history(monkeypatch):
    frames = {}
    monkeypatch.setattr(mc_mod, "get_history", lambda s, period="10y", interval="1wk": frames.get(s, pd.DataFrame()).copy())
    return frames


def _run(sim):
    sim._rng = np.random.default_rng(1)         # same draws for the reused and the fresh simulator
    return sim.run(horizon_years=10, n_sims=400, initial_value=10_000)


def _simulator():
    return MonteCarloSimulator(["AAA"], seed=1, asset_classes={"AAA": "us_equity"})


def test_a_reused_simulator_that_falls_back_to_spy_is_the_fresh_spy_projection(history):
    """Before: the second run recentred SPY's history on AAA's Estimación; it differed from the fresh one."""
    history["AAA"] = _frame(1, 0.004)
    history["SPY"] = _frame(2, 0.001)
    sim = _simulator()
    first = _run(sim)
    assert first.symbols_used == ["AAA"]

    del history["AAA"]                           # the symbol stops answering; SPY still does
    reused = _run(sim)
    fresh = _run(_simulator())
    assert reused.symbols_used == ["SPY"]
    assert reused.estimations == [] == fresh.estimations
    assert reused.median_terminal == fresh.median_terminal
    assert reused.p10_terminal == fresh.p10_terminal
    assert reused.warnings == fresh.warnings


def test_the_old_assets_are_gone_after_a_load_that_finds_no_prices(history):
    history["AAA"] = _frame(1, 0.004)
    sim = _simulator()
    sim._load_returns()
    assert sim._asset_symbols == ["AAA"] and sim._asset_hist is not None
    del history["AAA"]
    sim._load_returns()                          # no price at all, no SPY either
    assert sim._asset_hist is None and sim._asset_weights is None and sim._asset_symbols == []


def test_a_load_that_succeeds_again_still_sets_the_assets(history):
    history["AAA"] = _frame(1, 0.004)
    sim = _simulator()
    sim._load_returns()
    sim._load_returns()
    assert sim._asset_symbols == ["AAA"]
    assert sim._asset_hist.shape == (N - 1, 1)
    assert sim._asset_weights.tolist() == [1.0]
