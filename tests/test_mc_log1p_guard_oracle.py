"""AUDIT-MC-ROBUSTEZ (log1p) — una semana que la volatilidad escalada lleva a −100 % o menos no da NaN.

``MonteCarloSimulator._estimation_adjustment`` recentra el portafolio con ``np.log1p(port_dev)``, donde
``port_dev = Σ w·(r − m)·vol_scale``. ``log1p(−1)`` es ``−inf`` y ``log1p(<−1)`` es ``nan``: con ``vol_scale`` 1,15
(el del perfil conservador) alcanza una semana de ≈ −87 % en un activo único para que la mediana, el p10 y el
resto de la proyección salgan NaN (reproducido con una historia sintética de una semana de −95 %; con
``vol_scale`` 1,0 la misma historia daba un resultado finito).

El arreglo acota el factor semanal ``1 + x`` por abajo en ``MONTE_CARLO.min_weekly_factor`` y lo avisa, en el
recentrado por Estimación y también en el ajuste histórico (``_conservative_adjustment``: sin ``asset_classes``, con
bonos o con SPY de respaldo), donde la misma semana daba riqueza negativa en vez de NaN. Donde el factor no llega al
piso —toda historia ordinaria— el resultado es **bit a bit el de antes**.

Sin red: las historias son sintéticas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import portfolio.monte_carlo as mc_mod
from analysis.estimacion import OBJETIVA, asset_estimations
from config import ESTIMACION, MONTE_CARLO
from portfolio.monte_carlo import MonteCarloResult, MonteCarloSimulator

N = 600
IDX = pd.date_range("2015-01-05", periods=N, freq="W-MON")


def _frame(weekly):
    return pd.DataFrame({"close": 100.0 * np.cumprod(1.0 + np.asarray(weekly))}, index=IDX)


def _weekly(seed=0, crash=None):
    r = np.random.default_rng(seed).normal(0.003, 0.02, N)
    if crash is not None:
        r[300] = crash
    return r


@pytest.fixture
def history(monkeypatch):
    frames = {}
    monkeypatch.setattr(mc_mod, "get_history", lambda s, period="10y", interval="1wk": frames.get(s, pd.DataFrame()).copy())
    return frames


def _adjusted(frames, weekly, vol_scale, symbols=("AAA",)):
    for s in symbols:
        frames[s] = _frame(weekly)
    sim = MonteCarloSimulator(list(symbols), seed=1, asset_classes={s: "us_equity" for s in symbols}, vol_scale=vol_scale)
    port, *_ = sim._load_returns()
    result = MonteCarloResult(n_sims=10, horizon_years=10, initial_value=1.0, annual_withdrawal=0.0,
                              annual_contribution=0.0, target_value=0.0)
    return sim, sim._estimation_adjustment(port, result), result


def _reference(sim, floor):
    """The recentring from its definition, with a loop and the floor applied to the weekly factor."""
    ests = asset_estimations(sim._asset_symbols, sim._asset_classes, sim.scenario, sim._countries)
    periods = ESTIMACION.periods_per_year
    hist, w = sim._asset_hist, sim._asset_weights
    target = 0.0
    dev = np.zeros(hist.shape[0])
    for j, e in enumerate(ests):
        assert e.mode == OBJETIVA
        col = hist[:, j]
        dev += w[j] * (col - col.mean()) * sim.vol_scale
        target += w[j] * np.expm1(np.log1p(e.annual_pct / 100.0) * sim.return_scale)
    logr = np.array([np.log(max(1.0 + d, floor)) for d in dev])
    return np.array([np.expm1(x - logr.mean() + np.log1p(target) / periods) for x in logr])


def test_a_crash_week_under_a_conservative_vol_scale_is_not_nan(history):
    """Before: the adjusted series had a NaN, and so did every statistic of the projection."""
    _, adj, _ = _adjusted(history, _weekly(crash=-0.95), vol_scale=1.15)
    assert np.isfinite(adj).all()
    assert (adj > -1.0).all()                                   # no weekly return of −100 % or worse


def test_the_whole_projection_comes_out_finite(history):
    history["AAA"] = _frame(_weekly(crash=-0.95))
    sim = MonteCarloSimulator(["AAA"], seed=1, asset_classes={"AAA": "us_equity"}, vol_scale=1.15)
    res = sim.run(horizon_years=10, n_sims=300, initial_value=10_000)
    stats = [res.median_terminal, res.p10_terminal, res.p25_terminal, res.p75_terminal, res.p90_terminal]
    assert all(np.isfinite(stats)), stats                       # before: nan for all of them


def test_the_adjusted_series_matches_the_reference_where_the_floor_binds(history):
    sim, adj, _ = _adjusted(history, _weekly(crash=-0.95), vol_scale=1.15)
    assert adj == pytest.approx(_reference(sim, MONTE_CARLO.min_weekly_factor), abs=1e-12)


def _unguarded(sim):
    """The series as the code produced it before the guard: ``log1p`` straight on the weighted deviation."""
    ests = asset_estimations(sim._asset_symbols, sim._asset_classes, sim.scenario, sim._countries)
    r = sim._asset_hist[:, 0]
    w = sim._asset_weights[0]
    port_dev = ((r - r.mean()) * sim.vol_scale) * w
    target = np.expm1(np.log1p(ests[0].annual_pct / 100.0) * sim.return_scale) * w
    logr = np.log1p(port_dev)
    return np.expm1(logr - logr.mean() + np.log1p(target) / ESTIMACION.periods_per_year)


def test_an_ordinary_history_is_bit_for_bit_what_it_was(history):
    """The control that matters: the guard moves nothing where nothing was broken."""
    sim, adj, _ = _adjusted(history, _weekly(seed=3), vol_scale=1.15)
    assert (adj == _unguarded(sim)).all()


def test_the_same_crash_with_a_unit_vol_scale_was_already_finite_and_does_not_move(history):
    sim, adj, result = _adjusted(history, _weekly(crash=-0.95), vol_scale=1.0)
    assert np.isfinite(adj).all()
    assert (adj == _unguarded(sim)).all()                        # the floor does not bind: same bits as before
    assert not any("−100 %" in w for w in result.warnings)


def test_the_floor_is_announced_and_only_when_it_binds(history):
    _, _, hit = _adjusted(history, _weekly(crash=-0.95), vol_scale=1.15)
    assert any("−100 %" in w for w in hit.warnings)
    _, _, quiet = _adjusted(history, _weekly(seed=3), vol_scale=1.15)
    assert not any("−100 %" in w for w in quiet.warnings)


def test_the_floor_comes_from_the_config(history, monkeypatch):
    monkeypatch.setattr(MONTE_CARLO, "min_weekly_factor", 0.5)
    sim, adj, _ = _adjusted(history, _weekly(crash=-0.95), vol_scale=1.15)
    assert adj == pytest.approx(_reference(sim, 0.5), abs=1e-12)


def test_a_two_asset_portfolio_where_one_asset_crashes_is_also_finite(history):
    """The deviation is the weighted sum: the floor also binds when one asset of two carries the crash."""
    history["AAA"] = _frame(_weekly(seed=1, crash=-0.99))
    history["BBB"] = _frame(_weekly(seed=2))
    sim = MonteCarloSimulator(["AAA", "BBB"], weights=np.array([0.7, 0.3]), seed=1,
                              asset_classes={"AAA": "us_equity", "BBB": "us_equity"}, vol_scale=1.5)
    port, *_ = sim._load_returns()
    result = MonteCarloResult(n_sims=10, horizon_years=10, initial_value=1.0, annual_withdrawal=0.0,
                              annual_contribution=0.0, target_value=0.0)
    adj = sim._estimation_adjustment(port, result)
    assert np.isfinite(adj).all()
    assert adj == pytest.approx(_reference(sim, MONTE_CARLO.min_weekly_factor), abs=1e-12)
    assert any("−100 %" in w for w in result.warnings)


def test_a_week_between_minus_99_and_minus_100_percent_was_finite_and_is_now_floored(history):
    """The honest edge of the change: the floor also moves the band that ``log1p`` could still take."""
    sim, adj, result = _adjusted(history, _weekly(crash=-0.99), vol_scale=1.0)
    assert adj == pytest.approx(_reference(sim, MONTE_CARLO.min_weekly_factor), abs=1e-12)
    assert any("−100 %" in w for w in result.warnings)


def _haircut(history, weekly, vol_scale):
    history["AAA"] = _frame(weekly)
    sim = MonteCarloSimulator(["AAA"], seed=1, vol_scale=vol_scale)          # no asset_classes: the historical haircut
    port, *_ = sim._load_returns()
    result = MonteCarloResult(n_sims=10, horizon_years=10, initial_value=1.0, annual_withdrawal=0.0,
                              annual_contribution=0.0, target_value=0.0)
    return sim, port, sim._estimation_adjustment(port, result), result


def test_the_historical_haircut_does_not_return_a_week_below_minus_100_percent(history):
    """Before: the same crash gave a weekly return of -1.08 here, i.e. negative wealth (no NaN to give it away)."""
    _, _, adj, result = _haircut(history, _weekly(crash=-0.85), vol_scale=1.15)
    assert adj.min() >= MONTE_CARLO.min_weekly_factor - 1.0
    assert any("−100 %" in w for w in result.warnings)


def test_the_historical_haircut_is_bit_for_bit_what_it_was_when_the_floor_does_not_bind(history):
    sim, port, adj, result = _haircut(history, _weekly(seed=5), vol_scale=1.15)
    old = (port - port.mean()) * (MONTE_CARLO.vol_adjustment * 1.15) + port.mean() * (MONTE_CARLO.mean_haircut * sim.return_scale)
    assert (adj == old).all()
    assert not any("−100 %" in w for w in result.warnings)


def test_the_historical_haircut_projection_has_no_negative_wealth(history):
    history["AAA"] = _frame(_weekly(crash=-0.85))
    res = MonteCarloSimulator(["AAA"], seed=1, vol_scale=1.15).run(horizon_years=10, n_sims=400, initial_value=10_000)
    assert res.p10_terminal >= 0.0 and res.median_terminal > 0.0        # before: p10 negative


def test_the_spy_fallback_is_floored_too(history):
    """With ``asset_classes`` but no price history for the symbol, the run falls back to SPY and the haircut."""
    history["SPY"] = _frame(_weekly(crash=-0.85))
    sim = MonteCarloSimulator(["AAA"], seed=1, asset_classes={"AAA": "us_equity"}, vol_scale=1.15)
    port, _, used, _ = sim._load_returns()
    assert used == ["SPY"] and sim._asset_hist is None
    result = MonteCarloResult(n_sims=10, horizon_years=10, initial_value=1.0, annual_withdrawal=0.0,
                              annual_contribution=0.0, target_value=0.0)
    adj = sim._estimation_adjustment(port, result)
    assert adj.min() >= MONTE_CARLO.min_weekly_factor - 1.0
    assert any("−100 %" in w for w in result.warnings)
