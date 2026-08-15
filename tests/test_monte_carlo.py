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


def _make_simulator(symbols=None, weights=None, **kwargs):
    if symbols is None:
        symbols = ["AAPL", "MSFT"]
    return MonteCarloSimulator(symbols=symbols, weights=weights, seed=42, **kwargs)


# ------------------------------------------------------------------ #
#  Conservative adjustment                                             #
# ------------------------------------------------------------------ #

class TestConservativeAdjustment:
    """_conservative_adjustment is an instance method — needs a simulator instance."""

    def _sim(self):
        return MonteCarloSimulator(symbols=["SPY"])

    def test_vol_increases(self):
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02] * 20)
        adjusted = self._sim()._conservative_adjustment(returns)
        assert adjusted.std() > returns.std()

    def test_mean_decreases(self):
        returns = np.array([0.005] * 100)  # constant positive drift
        adjusted = self._sim()._conservative_adjustment(returns)
        assert adjusted.mean() < returns.mean()

    def test_zero_mean_returns_unchanged_mean(self):
        """Zero-mean returns stay zero-mean regardless of vol adjustment."""
        returns = np.array([0.01, -0.01] * 50)
        adjusted = self._sim()._conservative_adjustment(returns)
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


# ------------------------------------------------------------------ #
#  Year-of-max-drawdown dispersion (card audit, case 02)               #
# ------------------------------------------------------------------ #

class TestYearOfMaxDrawdownDispersion:
    """The median alone is an artifact of the horizon — the quartiles say so."""

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_quartiles_are_ordered_and_inside_horizon(self, _mock):
        sim = _make_simulator(["AAPL", "MSFT"])
        horizon = 20
        r = sim.run(horizon_years=horizon, n_sims=2000, initial_value=100_000)

        assert r.p25_year_of_max_dd <= r.median_year_of_max_dd <= r.p75_year_of_max_dd
        for v in (r.p25_year_of_max_dd, r.median_year_of_max_dd, r.p75_year_of_max_dd):
            assert 0.0 <= v <= horizon

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_timing_of_worst_drawdown_is_essentially_unpredictable(self, _mock):
        """The IQR covers a large slice of the horizon — which is exactly why the
        UI must show a band and not a precise "worst year" line.

        Note we assert dispersion, NOT location: where the median lands depends
        on the drift of the series (a strongly trending series pushes the worst
        drawdown late, a driftless one puts it near horizon/2). Neither makes the
        point estimate meaningful — the spread does the talking.
        """
        sim = _make_simulator(["AAPL", "MSFT"])
        horizon = 24
        r = sim.run(horizon_years=horizon, n_sims=3000, initial_value=100_000)

        iqr = r.p75_year_of_max_dd - r.p25_year_of_max_dd
        assert iqr > horizon * 0.25, (
            f"IQR {iqr:.1f}y over a {horizon}y horizon — if this ever gets small, "
            "a point estimate would become defensible and the UI could show one."
        )
        # And the median is not a spike: both quartiles sit clearly away from it.
        assert r.median_year_of_max_dd - r.p25_year_of_max_dd > 1.0
        assert r.p75_year_of_max_dd - r.median_year_of_max_dd > 1.0

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_preexisting_drawdown_metrics_unchanged_by_the_wider_tuple(self, _mock):
        """The 5→7 tuple widening must not disturb the metrics that already existed."""
        sim = _make_simulator(["AAPL"])
        r = sim.run(horizon_years=10, n_sims=1000, initial_value=100_000)

        assert 0.0 <= r.sorr_early_drawdown_pct <= 100.0
        assert 0.0 <= r.median_max_drawdown_pct <= 100.0
        assert 0.0 <= r.pct_paths_severe_drawdown <= 100.0
        assert r.p10_intra_min >= 0.0


# ------------------------------------------------------------------ #
#  Contributions: a NEGATIVE annual_withdrawal is an inflow             #
# ------------------------------------------------------------------ #

class TestContributionsAreApplied:
    """Regression guard for the ``> 0`` guard that dropped inflows silently.

    ``GoalPlanner`` models ``Goal.annual_contribution`` as a negative
    ``annual_withdrawal``. The engine used to test ``if annual_withdrawal > 0``,
    so every contribution the user entered was discarded and goal projections
    were identical with and without savings.
    """

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_contribution_raises_the_projection(self, _mock):
        sim = _make_simulator(["AAPL"])
        kw = dict(horizon_years=10, n_sims=1000, initial_value=10_000)

        without = sim.run(annual_withdrawal=0.0, **kw)
        with_contrib = sim.run(annual_withdrawal=-6_000.0, **kw)

        assert with_contrib.median_terminal > without.median_terminal * 2

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_more_contribution_is_monotonically_better(self, _mock):
        sim = _make_simulator(["AAPL"])
        # Target picked so the three contribution levels land at clearly
        # different probabilities (≈0% / ≈10% / ≈100%) instead of all saturating.
        kw = dict(horizon_years=10, n_sims=1000, initial_value=10_000,
                  target_value=60_000)

        probs = [
            sim.run(annual_withdrawal=-c, **kw).prob_achieve_target_pct
            for c in (0.0, 3_000.0, 12_000.0)
        ]
        # STRICTLY increasing: equality would mean the inflows are being ignored,
        # which is exactly the bug this guards against.
        assert probs[0] < probs[1] < probs[2]

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_zero_withdrawal_still_touches_nothing(self, _mock):
        """The guard change must be a no-op for the accumulation-only path."""
        sim_a = _make_simulator(["AAPL"])
        sim_b = _make_simulator(["AAPL"])
        kw = dict(horizon_years=8, n_sims=500, initial_value=50_000)

        assert (sim_a.run(annual_withdrawal=0.0, **kw).median_terminal
                == sim_b.run(**kw).median_terminal)

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

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_static_weights_warning_always(self, _mock):
        """P2 D11: static-weights assumption is surfaced."""
        sim = _make_simulator(["AAPL", "MSFT"])
        result = sim.run(horizon_years=5, n_sims=100, initial_value=100_000)
        assert any("pesos fijos" in w.lower() for w in result.warnings)

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_crypto_without_extra_vol_warning(self, _mock):
        """P2 D11: crypto + vol_scale=1.0 warns about missing extra haircut."""
        sim = _make_simulator(["BTC-USD", "AAPL"], vol_scale=1.0)
        result = sim.run(horizon_years=5, n_sims=100, initial_value=100_000)
        assert any("crypto" in w.lower() and "vol_scale" in w.lower() for w in result.warnings)

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_crypto_with_extra_vol_no_extra_warning(self, _mock):
        sim = _make_simulator(["BTC-USD"], vol_scale=1.2)
        result = sim.run(horizon_years=5, n_sims=100, initial_value=100_000)
        assert not any("sin haircut extra" in w.lower() for w in result.warnings)


# ------------------------------------------------------------------ #
#  Economic drags (Item 1)                                            #
# ------------------------------------------------------------------ #

class TestEconomicDrags:
    """Drags are opt-in: drags=None must be byte-identical to base behavior."""

    def test_total_drag_fraction_none_is_zero(self):
        assert MonteCarloSimulator._total_drag_fraction(None) == 0.0

    def test_total_drag_fraction_disabled_is_zero(self):
        d = {"enabled": False, "annual_fee_pct": 1.0}
        assert MonteCarloSimulator._total_drag_fraction(d) == 0.0

    def test_total_drag_fraction_sums_components(self):
        d = {"annual_fee_pct": 0.2, "dividend_tax_drag_pct": 0.3,
             "rebalance_cost_annual_pct": 0.05, "ar_buffer_pct": 0.0}
        # 0.55% -> 0.0055
        assert abs(MonteCarloSimulator._total_drag_fraction(d) - 0.0055) < 1e-9

    def test_total_drag_fraction_prefers_explicit_total(self):
        d = {"total_annual_drag_pct": 1.0, "annual_fee_pct": 99.0}
        assert abs(MonteCarloSimulator._total_drag_fraction(d) - 0.01) < 1e-9

    def test_apply_drags_reduces_paths(self):
        paths = np.ones((3, 53))  # 1 year, flat
        out = MonteCarloSimulator._apply_drags(paths, 0.10)  # 10% annual drag
        # After ~52 weeks the multiplier should be ~ (1-0.10)
        assert out[:, -1].mean() < 1.0
        assert abs(out[:, -1].mean() - 0.90) < 0.01
        # Week 0 untouched
        assert np.allclose(out[:, 0], 1.0)

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_run_without_drags_unchanged(self, _mock):
        sim = _make_simulator(["AAPL"])
        result = sim.run(horizon_years=10, n_sims=500, initial_value=100_000)
        assert result.drags_applied is None
        assert result.total_annual_drag_pct == 0.0
        assert result.base_median_terminal == 0.0  # reference unset when no drags

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_run_with_drags_lowers_median_and_sets_base(self, _mock):
        drags = {"enabled": True, "total_annual_drag_pct": 1.5}
        base = _make_simulator(["AAPL"]).run(horizon_years=10, n_sims=800, initial_value=100_000)
        dragged = _make_simulator(["AAPL"]).run(
            horizon_years=10, n_sims=800, initial_value=100_000, drags=drags,
        )
        assert dragged.total_annual_drag_pct == 1.5
        assert dragged.drags_applied == drags
        # Dragged median is lower than base, and base_* reference matches the base run.
        assert dragged.median_terminal < base.median_terminal
        assert dragged.base_median_terminal > dragged.median_terminal
        assert abs(dragged.base_median_terminal - base.median_terminal) < 1.0


class TestRealisticReference:
    """Realistic reference is opt-in: off → byte-identical; on → higher than conservative."""

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_off_by_default_unchanged(self, _mock):
        sim = _make_simulator(["AAPL"])
        result = sim.run(horizon_years=10, n_sims=500, initial_value=100_000)
        assert result.realistic_reference_applied is False
        assert result.realistic_median_terminal == 0.0
        assert result.realistic_p10_terminal == 0.0
        assert result.realistic_p90_terminal == 0.0

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_on_lifts_median_and_downside(self, _mock):
        result = _make_simulator(["AAPL"]).run(
            horizon_years=10, n_sims=4000, initial_value=100_000,
            include_realistic_reference=True,
        )
        assert result.realistic_reference_applied is True
        # Removing the haircut (higher drift, lower vol) lifts the median and,
        # most reliably, the pessimistic floor (p10). The optimistic tail (p90)
        # is intentionally NOT asserted: inflating volatility in the conservative
        # case fattens its upper tail, so p90 can move either way.
        assert result.realistic_median_terminal >= result.median_terminal
        assert result.realistic_p10_terminal > result.p10_terminal

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_on_does_not_change_conservative_numbers(self, _mock):
        base = _make_simulator(["AAPL"]).run(
            horizon_years=10, n_sims=800, initial_value=100_000,
        )
        withref = _make_simulator(["AAPL"]).run(
            horizon_years=10, n_sims=800, initial_value=100_000,
            include_realistic_reference=True,
        )
        # The main (conservative) metrics must be unchanged by the extra pass.
        assert abs(withref.median_terminal - base.median_terminal) < 1.0
        assert abs(withref.p10_terminal - base.p10_terminal) < 1.0

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_realistic_target_prob_is_populated(self, _mock):
        result = _make_simulator(["AAPL"]).run(
            horizon_years=10, n_sims=1500, initial_value=100_000,
            target_value=120_000, include_realistic_reference=True,
        )
        # When a target is set, the realistic reference reports its own hit-rate.
        assert result.realistic_prob_achieve_target_pct > 0.0


# ------------------------------------------------------------------ #
#  Decumulation / withdrawal strategies (Fase H.1)                     #
# ------------------------------------------------------------------ #

from portfolio.decumulation import WithdrawalStrategy  # noqa: E402


class TestWithdrawalStrategyRun:
    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_no_strategy_leaves_decumulation_fields_default(self, _mock):
        result = _make_simulator(["AAPL"]).run(
            horizon_years=10, n_sims=400, initial_value=100_000
        )
        assert result.withdrawal_strategy_applied is None
        assert result.prob_sustain_real_pct == 0.0
        assert result.longevity_years == 0

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_fixed_real_strategy_matches_legacy_annual_withdrawal(self, _mock):
        """A fixed_real strategy must be byte-identical to the legacy path."""
        legacy = _make_simulator(["AAPL"]).run(
            horizon_years=15, n_sims=600, initial_value=100_000,
            annual_withdrawal=4_000, withdrawal_growth_rate=0.03,
        )
        strat = WithdrawalStrategy.fixed_real(4_000)
        new = _make_simulator(["AAPL"]).run(
            horizon_years=15, n_sims=600, initial_value=100_000,
            withdrawal_growth_rate=0.03, withdrawal_strategy=strat,
        )
        assert new.median_terminal == pytest.approx(legacy.median_terminal, abs=1e-6)
        assert new.p10_terminal == pytest.approx(legacy.p10_terminal, abs=1e-6)
        # Decumulation metrics are populated only on the strategy run.
        assert new.withdrawal_strategy_applied["kind"] == "fixed_real"
        assert legacy.withdrawal_strategy_applied is None

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_strategy_populates_decumulation_metrics(self, _mock):
        strat = WithdrawalStrategy.guardrails(0.04)
        result = _make_simulator(["AAPL"]).run(
            horizon_years=25, n_sims=800, initial_value=100_000,
            withdrawal_growth_rate=0.03, withdrawal_strategy=strat,
            longevity_years=25,
        )
        assert 0.0 <= result.prob_sustain_real_pct <= 100.0
        assert 0.0 <= result.prob_legacy_pct <= 100.0
        assert result.longevity_years == 25
        assert result.withdrawal_strategy_applied["kind"] == "guardrails"

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_guardrails_sustains_at_least_as_well_as_fixed(self, _mock):
        """Guardrails cut spending in downturns → never worse sustain odds."""
        common = dict(horizon_years=30, n_sims=1000, initial_value=100_000,
                      withdrawal_growth_rate=0.03, longevity_years=30)
        fixed = _make_simulator(["AAPL"]).run(
            withdrawal_strategy=WithdrawalStrategy.fixed_real(5_000), **common
        )
        guard = _make_simulator(["AAPL"]).run(
            withdrawal_strategy=WithdrawalStrategy.guardrails(0.05), **common
        )
        assert guard.prob_sustain_real_pct >= fixed.prob_sustain_real_pct

    @patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
    def test_dict_strategy_is_coerced(self, _mock):
        result = _make_simulator(["AAPL"]).run(
            horizon_years=10, n_sims=300, initial_value=100_000,
            withdrawal_strategy={"kind": "constant_pct", "pct": 0.04},
        )
        assert result.withdrawal_strategy_applied["kind"] == "constant_pct"
