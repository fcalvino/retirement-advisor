"""Tests for MonteCarloSimulator — uses mocked fetcher to avoid network calls."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from portfolio.monte_carlo import MonteCarloResult, MonteCarloSimulator


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _fake_history(symbol: str, period: str = "10y", interval: str = "1wk") -> pd.DataFrame:
    """Return 5 years of fake weekly price history (deterministic, upward trend)."""
    n = 260  # ~5 years of weekly bars
    rng = np.random.default_rng(seed=42)
    prices = 100.0 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    dates = pd.date_range("2018-01-01", periods=n, freq="W")
    return pd.DataFrame({"close": prices}, index=dates)


def _make_simulator(symbols=None, weights=None):
    if symbols is None:
        symbols = ["AAPL", "MSFT"]
    return MonteCarloSimulator(symbols=symbols, weights=weights, seed=42)


# ------------------------------------------------------------------ #
#  Conservative adjustment                                             #
# ------------------------------------------------------------------ #

class TestConservativeAdjustment:
    def test_vol_increases(self):
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02] * 20)
        adjusted = MonteCarloSimulator._conservative_adjustment(returns)
        assert adjusted.std() > returns.std()

    def test_mean_decreases(self):
        returns = np.array([0.005] * 100)  # constant positive drift
        adjusted = MonteCarloSimulator._conservative_adjustment(returns)
        assert adjusted.mean() < returns.mean()

    def test_zero_mean_returns_unchanged_mean(self):
        """Zero-mean returns stay zero-mean regardless of vol adjustment."""
        returns = np.array([0.01, -0.01] * 50)
        adjusted = MonteCarloSimulator._conservative_adjustment(returns)
        assert abs(adjusted.mean()) < 1e-10


# ------------------------------------------------------------------ #
#  Simulation paths                                                    #
# ------------------------------------------------------------------ #

class TestSimulatePaths:
    def test_path_shape(self):
        sim = _make_simulator()
        port_hist = np.random.default_rng(0).normal(0.001, 0.02, 260)
        paths = sim._simulate_paths(port_hist, n_sims=100, n_weeks=52)
        assert paths.shape == (100, 53)  # 52 steps + initial value

    def test_paths_start_at_one(self):
        sim = _make_simulator()
        port_hist = np.random.default_rng(0).normal(0.001, 0.02, 260)
        paths = sim._simulate_paths(port_hist, n_sims=200, n_weeks=52)
        assert np.all(paths[:, 0] == 1.0)

    def test_paths_non_negative(self):
        """With realistic return history, paths should stay positive."""
        sim = _make_simulator()
        port_hist = np.random.default_rng(0).normal(0.001, 0.015, 260)
        paths = sim._simulate_paths(port_hist, n_sims=500, n_weeks=104)
        assert np.all(paths >= 0)


# ------------------------------------------------------------------ #
#  Withdrawals                                                         #
# ------------------------------------------------------------------ #

class TestApplyWithdrawals:
    def test_withdrawal_reduces_terminal_value(self):
        """A path with annual withdrawals should have lower terminal value."""
        n_sims, n_weeks = 100, 104
        paths_no_wd = np.ones((n_sims, n_weeks + 1)) * np.linspace(1.0, 1.5, n_weeks + 1)

        paths_wd = paths_no_wd.copy()
        paths_wd = MonteCarloSimulator._apply_withdrawals(
            paths_wd, initial_value=100_000, annual_withdrawal=5_000, n_horizon_weeks=n_weeks
        )
        assert paths_wd[:, -1].mean() < paths_no_wd[:, -1].mean()

    def test_paths_never_go_below_zero(self):
        """Heavy withdrawal on flat path should floor at 0."""
        n_sims, n_weeks = 10, 52
        # Constant path at 1.0
        paths = np.ones((n_sims, n_weeks + 1))
        paths = MonteCarloSimulator._apply_withdrawals(
            paths, initial_value=100_000, annual_withdrawal=200_000, n_horizon_weeks=n_weeks
        )
        assert np.all(paths >= 0)


# ------------------------------------------------------------------ #
#  Fan paths                                                           #
# ------------------------------------------------------------------ #

class TestFanPaths:
    def test_fan_paths_structure(self):
        sim = _make_simulator()
        n_sims, n_years = 200, 5
        paths_usd = np.random.default_rng(0).lognormal(0, 0.3, (n_sims, n_years * 52 + 1)) * 100_000
        fan = sim._fan_paths(paths_usd, horizon_years=n_years)

        assert set(fan.keys()) == set(range(n_years + 1))
        for yr_data in fan.values():
            assert set(yr_data.keys()) == {5, 10, 25, 50, 75, 90, 95}

    def test_fan_paths_percentiles_monotonic(self):
        sim = _make_simulator()
        n_sims = 500
        paths_usd = np.random.default_rng(0).lognormal(0, 0.3, (n_sims, 261)) * 100_000
        fan = sim._fan_paths(paths_usd, horizon_years=5)

        for yr_data in fan.values():
            pcts = [5, 10, 25, 50, 75, 90, 95]
            values = [yr_data[p] for p in pcts]
            assert values == sorted(values), f"Percentiles not monotonic: {yr_data}"

    def test_year_0_equals_initial(self):
        """Year-0 fan paths should be constant (all paths start at same value)."""
        sim = _make_simulator()
        n_sims = 100
        initial = 100_000.0
        # All paths start at initial
        paths_usd = np.ones((n_sims, 261)) * initial
        fan = sim._fan_paths(paths_usd, horizon_years=5)
        for pct, val in fan[0].items():
            assert abs(val - initial) < 1.0


# ------------------------------------------------------------------ #
#  Full run (mocked fetcher)                                           #
# ------------------------------------------------------------------ #

class TestFullRun:
    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_run_returns_result_object(self, _mock):
        sim = _make_simulator(["AAPL", "MSFT"])
        result = sim.run(horizon_years=5, n_sims=500, initial_value=100_000)
        assert isinstance(result, MonteCarloResult)

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_median_greater_than_p10(self, _mock):
        sim = _make_simulator(["AAPL"])
        result = sim.run(horizon_years=10, n_sims=1000, initial_value=100_000)
        assert result.median_terminal > result.p10_terminal

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_p90_greater_than_median(self, _mock):
        sim = _make_simulator(["AAPL"])
        result = sim.run(horizon_years=10, n_sims=1000, initial_value=100_000)
        assert result.p90_terminal > result.median_terminal

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_prob_ruin_between_0_and_100(self, _mock):
        sim = _make_simulator(["AAPL"])
        result = sim.run(horizon_years=10, n_sims=500, initial_value=100_000)
        assert 0.0 <= result.prob_ruin_pct <= 100.0

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_target_probability_zero_for_impossible_target(self, _mock):
        """Probability of reaching $1 trillion should be ~0."""
        sim = _make_simulator(["AAPL"])
        result = sim.run(
            horizon_years=5, n_sims=200,
            initial_value=100_000, target_value=1_000_000_000_000,
        )
        assert result.prob_achieve_target_pct < 1.0

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_target_probability_high_for_trivial_target(self, _mock):
        """Probability of reaching $1 (less than initial) should be ~100%."""
        sim = _make_simulator(["AAPL"])
        result = sim.run(
            horizon_years=5, n_sims=500,
            initial_value=100_000, target_value=1,
        )
        assert result.prob_achieve_target_pct > 95.0

    @patch("portfolio.monte_carlo.get_history", return_value=pd.DataFrame())
    def test_spy_fallback_on_empty_history(self, _mock_empty):
        """When all tickers return empty history, simulator falls back to SPY."""
        with patch("portfolio.monte_carlo.get_history") as mock_hist:
            # First calls return empty, SPY fallback also called
            mock_hist.side_effect = lambda sym, **kw: (
                _fake_history(sym) if sym == "SPY" else pd.DataFrame()
            )
            sim = _make_simulator(["FAKEX"])
            result = sim.run(horizon_years=5, n_sims=200, initial_value=100_000)
            assert "SPY" in result.symbols_used or len(result.warnings) > 0

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_fan_paths_year_keys_cover_full_horizon(self, _mock):
        sim = _make_simulator(["AAPL"])
        result = sim.run(horizon_years=10, n_sims=200, initial_value=100_000)
        assert set(result.years) == set(range(11))  # 0..10

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_insufficient_history_adds_warning(self, _mock):
        """< min_history_weeks triggers warning in result.warnings."""
        def short_history(sym, **kw):
            df = _fake_history(sym)
            return df.head(30)  # only 30 weeks — below 104 minimum

        with patch("portfolio.monte_carlo.get_history", side_effect=short_history):
            sim = _make_simulator(["AAPL"])
            result = sim.run(horizon_years=5, n_sims=100, initial_value=100_000)
            assert any("insuficiente" in w.lower() or "insuficient" in w.lower() for w in result.warnings)
