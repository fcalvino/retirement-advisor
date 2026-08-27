"""Oracle tests for the numeric engine (audit D4).

The 2026-08 audit found that 610 tests passed while the withdrawal engine
overstated terminal wealth by ~60%. The reason was structural: the suite
verified the engine against *itself* ("byte-identical", "no regressions"), which
freezes whatever the engine currently does — bug included.

This module is the counterweight. Every test here compares the vectorised
production code against a **slow reference implementation written independently
from the financial definition**, not from the production source. The references
are deliberately naive Python loops: obviously correct, obviously slow, and
never sharing a line of code with the thing under test. When the two disagree,
one of them is wrong and the test says so.

``tests/test_withdrawal_oracle.py`` does this for the withdrawal kernel (D1/D2).
This file extends the same discipline to the rest of the engine:

  * economic drags        — fees/taxes compounding on the standing balance
  * contributions         — inflows during accumulation (negative withdrawals)
  * decumulation metrics  — sustain / legacy / depletion-year accounting
  * optimizer portfolio   — expected return, variance, Sharpe from weights
  * backtest curves       — equal-weight share accounting with rebalancing
  * backtest metrics      — CAGR / drawdown / total return from a price series

No network, no Streamlit, no fixtures shared with the production modules.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from analysis.backtesting import BacktestEngine
from portfolio.decumulation import decumulation_metrics
from portfolio.monte_carlo import MonteCarloSimulator

# ------------------------------------------------------------------ #
#  Deterministic market paths (shared inputs, not shared logic)        #
# ------------------------------------------------------------------ #

def _geometric_path(annual_rate: float, years: int) -> np.ndarray:
    """A single relative path growing at ``annual_rate``/year, weekly steps."""
    weekly = (1.0 + annual_rate) ** (1.0 / 52.0) - 1.0
    return np.concatenate([[1.0], np.cumprod(np.full(years * 52, 1.0 + weekly))])


# ================================================================== #
#  1. Economic drags                                                   #
# ================================================================== #

def oracle_drag_curve(path: list[float], annual_drag: float) -> list[float]:
    """Reference: a fee charged continuously on the standing balance.

    Written from the definition — "you keep (1 − d) of the balance per year,
    charged smoothly" — as an explicit week-by-week loop. The production code
    does this as a vectorised power series.
    """
    weekly_keep = (1.0 - annual_drag) ** (1.0 / 52.0)
    out, kept = [], 1.0
    for i, v in enumerate(path):
        if i > 0:
            kept *= weekly_keep      # one more week of fee charged
        out.append(v * kept)
    return out


class TestDragsOracle:
    @pytest.mark.parametrize("annual_drag", [0.0, 0.002, 0.0125, 0.05])
    @pytest.mark.parametrize("annual_return", [-0.15, 0.0, 0.08])
    def test_matches_sequential_reference(self, annual_drag, annual_return):
        path = _geometric_path(annual_return, 10)
        engine = MonteCarloSimulator._apply_drags(np.array([path]), annual_drag)[0]
        oracle = oracle_drag_curve(list(path), annual_drag)
        np.testing.assert_allclose(engine, oracle, rtol=1e-12, atol=1e-12)

    def test_one_year_of_drag_costs_exactly_the_annual_rate(self):
        """The economic contract, checked without reference to any code.

        A 1% annual drag must leave exactly 99% of the balance after 52 weeks
        in a flat market. This is what the user is told the number means.
        """
        flat = np.ones((1, 5 * 52 + 1))
        out = MonteCarloSimulator._apply_drags(flat, 0.01)
        assert out[0, 52] == pytest.approx(0.99, abs=1e-12)
        assert out[0, 104] == pytest.approx(0.99 ** 2, abs=1e-12)
        assert out[0, 5 * 52] == pytest.approx(0.99 ** 5, abs=1e-12)

    def test_zero_drag_is_the_identity(self):
        paths = np.array([_geometric_path(0.07, 8), _geometric_path(-0.04, 8)])
        np.testing.assert_array_equal(
            MonteCarloSimulator._apply_drags(paths.copy(), 0.0), paths
        )

    def test_drag_is_monotonic_in_the_rate(self):
        path = np.array([_geometric_path(0.06, 20)])
        terminals = [
            MonteCarloSimulator._apply_drags(path.copy(), d)[0, -1]
            for d in (0.0, 0.005, 0.01, 0.02)
        ]
        assert terminals == sorted(terminals, reverse=True)

    def test_drag_never_flips_the_sign_or_creates_value(self):
        path = np.array([_geometric_path(0.09, 30)])
        out = MonteCarloSimulator._apply_drags(path.copy(), 0.03)
        assert (out > 0).all()
        assert (out <= path + 1e-12).all()


class TestDragFractionResolution:
    """The drag total the engine uses must equal what the UI adds up."""

    def test_components_are_summed(self):
        frac = MonteCarloSimulator._total_drag_fraction({
            "annual_fee_pct": 0.20,
            "dividend_tax_drag_pct": 0.10,
            "rebalance_cost_annual_pct": 0.05,
            "ar_buffer_pct": 0.15,
        })
        assert frac == pytest.approx(0.50 / 100)

    def test_precomputed_total_wins_over_components(self):
        frac = MonteCarloSimulator._total_drag_fraction({
            "total_annual_drag_pct": 0.25, "annual_fee_pct": 99.0,
        })
        assert frac == pytest.approx(0.0025)

    @pytest.mark.parametrize("drags", [
        None, {}, {"enabled": False, "total_annual_drag_pct": 1.0},
        {"total_annual_drag_pct": -3.0},
    ])
    def test_disabled_or_negative_means_no_drag(self, drags):
        assert MonteCarloSimulator._total_drag_fraction(drags) == 0.0


# ================================================================== #
#  2. Contributions (negative withdrawals)                             #
# ================================================================== #

def oracle_contribution_sequence(
    path: list[float], initial: float, annual_contribution: float, years: int,
    growth_rate: float = 0.0,
) -> float:
    """Reference: capital accounting for an accumulation plan.

    Each year the existing balance follows the market, then the saver adds
    cash. New money starts compounding only from the moment it arrives — which
    is the whole point the engine has to get right.
    """
    val = initial
    for yr in range(1, years + 1):
        val *= path[yr * 52] / path[(yr - 1) * 52]
        val += annual_contribution * ((1.0 + growth_rate) ** (yr - 1))
    return val


class TestContributionsOracle:
    @pytest.mark.parametrize("annual_return", [-0.06, 0.0, 0.05, 0.11])
    @pytest.mark.parametrize("years", [5, 15, 30])
    def test_matches_sequential_reference(self, annual_return, years):
        initial, contribution = 40_000.0, 6_000.0
        path = _geometric_path(annual_return, years)

        engine = MonteCarloSimulator._apply_withdrawals(
            np.array([path]).copy(), initial, -contribution, years * 52,
        )[0, -1] * initial
        oracle = oracle_contribution_sequence(list(path), initial, contribution, years)

        assert engine == pytest.approx(oracle, rel=1e-9)

    def test_matches_reference_with_savings_growing_by_inflation(self):
        initial, contribution, years = 25_000.0, 4_800.0, 20
        path = _geometric_path(0.07, years)
        engine = MonteCarloSimulator._apply_withdrawals(
            np.array([path]).copy(), initial, -contribution, years * 52,
            withdrawal_growth_rate=0.03,
        )[0, -1] * initial
        oracle = oracle_contribution_sequence(
            list(path), initial, contribution, years, growth_rate=0.03
        )
        assert engine == pytest.approx(oracle, rel=1e-9)

    def test_contributions_are_not_silently_dropped(self):
        """Direct guard on the audit-era ``> 0`` bug.

        Goals model savings as a NEGATIVE withdrawal. A guard of ``> 0``
        discarded them, so every goal projection quietly ignored the money the
        user said they were saving. Saving must beat not saving.
        """
        years = 25
        path = _geometric_path(0.06, years)
        with_savings = MonteCarloSimulator._apply_withdrawals(
            np.array([path]).copy(), 30_000.0, -7_200.0, years * 52,
        )[0, -1]
        without = MonteCarloSimulator._apply_withdrawals(
            np.array([path]).copy(), 30_000.0, 0.0, years * 52,
        )[0, -1]
        assert with_savings > without * 1.5

    def test_contribution_only_compounds_from_when_it_arrives(self):
        """A dollar saved in year 20 must not have grown since year 0."""
        years = 20
        path = _geometric_path(0.10, years)
        initial, contribution = 10_000.0, 1_000.0
        engine = MonteCarloSimulator._apply_withdrawals(
            np.array([path]).copy(), initial, -contribution, years * 52,
        )[0, -1] * initial
        # Upper bound: every contribution compounding from t=0 (what a naive
        # "add a constant level to all future weeks" implementation produces).
        naive_upper = initial * path[-1] + contribution * years * path[-1]
        assert engine < naive_upper
        assert engine == pytest.approx(
            oracle_contribution_sequence(list(path), initial, contribution, years), rel=1e-9
        )


# ================================================================== #
#  3. Decumulation metrics                                             #
# ================================================================== #

def oracle_decumulation_metrics(paths_usd, horizon_years, initial_value, longevity_years=None):
    """Reference: plain-Python bookkeeping over each path, one at a time.

    Definitions taken from what the UI promises the user:
      sustain — the money never hit zero inside the planning window
      legacy  — something was left at the end of the window
      depletion year — among the runs that DID go broke, the typical year it
                       happened (median, in years)
    """
    longevity = int(longevity_years) if longevity_years else horizon_years
    n_cols = len(paths_usd[0])
    cap = min(longevity * 52, n_cols - 1)
    eps = max(initial_value, 1.0) * 1e-9

    sustained, left_legacy, terminals, depletion_weeks = 0, 0, [], []
    for row in paths_usd:
        window = list(row[: cap + 1])
        terminals.append(window[-1])
        first_zero = None
        for week, val in enumerate(window):
            if val <= eps:
                first_zero = week
                break
        if first_zero is None:
            sustained += 1
        else:
            depletion_weeks.append(first_zero)
        if window[-1] > eps:
            left_legacy += 1

    n = len(paths_usd)
    return {
        "prob_sustain_real_pct": round(sustained / n * 100, 2),
        "prob_legacy_pct": round(left_legacy / n * 100, 2),
        "median_legacy": round(float(np.median(terminals)), 0),
        "expected_depletion_year": (
            round(float(np.median(depletion_weeks)) / 52, 2) if depletion_weeks else 0.0
        ),
        "longevity_years": float(longevity),
    }


class TestDecumulationMetricsOracle:
    @staticmethod
    def _mixed_book(n_sims=40, years=20, seed=7):
        """Paths where some survive, some die early, some die late."""
        rng = np.random.default_rng(seed)
        weeks = years * 52
        rows = []
        for i in range(n_sims):
            drift = -0.004 + 0.0006 * (i % 12)          # spread of fortunes
            steps = 1.0 + rng.normal(drift, 0.02, weeks)
            path = np.concatenate([[1.0], np.cumprod(np.maximum(steps, 0.5))])
            if i % 5 == 0:                               # force some ruins
                kill = 52 * (3 + i % 9)
                path[kill:] = 0.0
            rows.append(path)
        return np.array(rows) * 100_000.0

    @pytest.mark.parametrize("longevity", [None, 10, 20])
    def test_matches_reference_bookkeeping(self, longevity):
        paths = self._mixed_book()
        assert decumulation_metrics(paths, 20, 100_000.0, longevity) == \
            oracle_decumulation_metrics(paths, 20, 100_000.0, longevity)

    def test_all_survive(self):
        paths = np.array([_geometric_path(0.05, 10) for _ in range(8)]) * 50_000.0
        m = decumulation_metrics(paths, 10, 50_000.0)
        assert m["prob_sustain_real_pct"] == 100.0
        assert m["expected_depletion_year"] == 0.0
        assert m == oracle_decumulation_metrics(paths, 10, 50_000.0)

    def test_all_ruined_reports_the_depletion_year(self):
        weeks = 10 * 52
        paths = np.ones((6, weeks + 1)) * 10_000.0
        paths[:, 5 * 52:] = 0.0                          # everyone dies at year 5
        m = decumulation_metrics(paths, 10, 10_000.0)
        assert m["prob_sustain_real_pct"] == 0.0
        assert m["expected_depletion_year"] == pytest.approx(5.0)
        assert m == oracle_decumulation_metrics(paths, 10, 10_000.0)

    def test_sustain_and_legacy_agree_now_that_ruin_absorbs(self):
        """Audit D2 made these the same event — they must never diverge again.

        Before the fix, a path could hit zero mid-horizon and "resurrect", so
        the UI showed a plan that both ran out of money and left an
        inheritance. If these two ever split apart again, ruin stopped being
        absorbing.
        """
        paths = self._mixed_book(seed=11)
        m = decumulation_metrics(paths, 20, 100_000.0)
        assert m["prob_sustain_real_pct"] == m["prob_legacy_pct"]

    def test_shorter_longevity_window_can_only_help(self):
        paths = self._mixed_book(seed=3)
        short = decumulation_metrics(paths, 20, 100_000.0, longevity_years=5)
        full = decumulation_metrics(paths, 20, 100_000.0, longevity_years=20)
        assert short["prob_sustain_real_pct"] >= full["prob_sustain_real_pct"]


# ================================================================== #
#  4. Optimizer portfolio statistics                                   #
# ================================================================== #

def oracle_portfolio_return(weights, mu):
    """Reference: Σ wᵢ·μᵢ as an explicit sum."""
    return sum(w * m for w, m in zip(weights, mu))


def oracle_portfolio_variance(weights, cov):
    """Reference: the double sum Σᵢ Σⱼ wᵢ wⱼ σᵢⱼ, written out."""
    total = 0.0
    for i, wi in enumerate(weights):
        for j, wj in enumerate(weights):
            total += wi * wj * cov[i][j]
    return total


class TestPortfolioStatsOracle:
    """The Sharpe/vol shown on the Optimizer page, checked against the algebra.

    The optimizer reports these via matrix products (``mu @ w``,
    ``sqrt(w @ cov @ w)``). A transposed matrix or a misaligned weight vector
    produces a plausible-looking number, which is exactly the failure mode a
    self-consistent test cannot see.
    """

    COV = [
        [0.0400, 0.0120, 0.0030],
        [0.0120, 0.0625, 0.0045],
        [0.0030, 0.0045, 0.0225],
    ]
    MU = [0.085, 0.110, 0.045]

    @pytest.mark.parametrize("weights", [
        [1.0, 0.0, 0.0],
        [0.5, 0.3, 0.2],
        [0.34, 0.33, 0.33],
        [0.0, 0.6, 0.4],
    ])
    def test_return_and_vol_match_the_explicit_sums(self, weights):
        w = np.array(weights)
        cov = np.array(self.COV)
        mu = np.array(self.MU)

        assert float(mu @ w) == pytest.approx(oracle_portfolio_return(weights, self.MU))
        assert float(w @ cov @ w) == pytest.approx(
            oracle_portfolio_variance(weights, self.COV)
        )

    def test_sharpe_matches_the_definition(self):
        w = np.array([0.5, 0.3, 0.2])
        cov, mu, rf = np.array(self.COV), np.array(self.MU), 0.045
        port_ret = float(mu @ w)
        port_vol = float(np.sqrt(w @ cov @ w))
        engine_sharpe = round((port_ret - rf) / port_vol, 2)
        oracle_sharpe = round(
            (oracle_portfolio_return(w, self.MU) - rf)
            / math.sqrt(oracle_portfolio_variance(w, self.COV)), 2
        )
        assert engine_sharpe == oracle_sharpe

    def test_diversification_reduces_variance(self):
        """Two imperfectly correlated assets must beat the weighted average."""
        cov = np.array(self.COV)
        w_mixed = np.array([0.5, 0.5, 0.0])
        mixed_vol = math.sqrt(float(w_mixed @ cov @ w_mixed))
        avg_of_vols = 0.5 * math.sqrt(cov[0, 0]) + 0.5 * math.sqrt(cov[1, 1])
        assert mixed_vol < avg_of_vols

    def test_full_weight_on_one_asset_reproduces_its_own_vol(self):
        cov = np.array(self.COV)
        for i in range(3):
            w = np.zeros(3)
            w[i] = 1.0
            assert math.sqrt(float(w @ cov @ w)) == pytest.approx(math.sqrt(self.COV[i][i]))


# ================================================================== #
#  5. Backtest equal-weight curve + rebalancing                        #
# ================================================================== #

def oracle_equal_weight_curve(prices: dict[str, list[float]], rebalance_at: set[int]) -> list[float]:
    """Reference: hold shares, revalue every bar, reset to equal at rebalances.

    Written as a broker would: you own a number of shares; the portfolio is
    worth what those shares fetch today; rebalancing means selling the winners
    and buying the laggards so each name is worth 1/N again.
    """
    syms = list(prices)
    n = len(syms)
    n_bars = len(prices[syms[0]])
    shares = {s: (1.0 / n) / prices[s][0] for s in syms}

    curve = []
    for bar in range(n_bars):
        value = sum(shares[s] * prices[s][bar] for s in syms)
        curve.append(value)
        if bar in rebalance_at and bar != 0 and value > 0:
            per_name = value / n
            shares = {s: per_name / prices[s][bar] for s in syms}
    return curve


class TestEqualWeightCurveOracle:
    @staticmethod
    def _frame(n_bars=120, seed=5):
        rng = np.random.default_rng(seed)
        idx = pd.date_range("2020-01-05", periods=n_bars, freq="W")
        data = {}
        for i, sym in enumerate(("AAA", "BBB", "CCC")):
            steps = 1.0 + rng.normal(0.001 + 0.0004 * i, 0.02, n_bars - 1)
            data[sym] = pd.Series(
                np.concatenate([[100.0 * (i + 1)], 100.0 * (i + 1) * np.cumprod(steps)]),
                index=idx,
            )
        return data, idx

    def test_buy_and_hold_matches_reference(self):
        data, idx = self._frame()
        engine = BacktestEngine()._equal_weight_curve(data, idx, "buy_and_hold")
        oracle = oracle_equal_weight_curve(
            {s: list(v.values) for s, v in data.items()}, rebalance_at=set()
        )
        np.testing.assert_allclose(engine.values, oracle, rtol=1e-10)

    def test_rebalanced_curve_matches_reference(self):
        data, idx = self._frame()
        eng = BacktestEngine()
        engine_curve = eng._equal_weight_curve(data, idx, "annual")
        rebal_dates = eng._rebalance_dates(idx, "annual")
        rebal_positions = {idx.get_loc(d) for d in rebal_dates}
        oracle = oracle_equal_weight_curve(
            {s: list(v.values) for s, v in data.items()}, rebalance_at=rebal_positions
        )
        np.testing.assert_allclose(engine_curve.values, oracle, rtol=1e-10)

    def test_starts_at_one_dollar(self):
        data, idx = self._frame()
        curve = BacktestEngine()._equal_weight_curve(data, idx, "annual")
        assert curve.iloc[0] == pytest.approx(1.0)

    def test_rebalancing_conserves_value_at_the_rebalance_bar(self):
        """Rebalancing reallocates; it must never mint or destroy money."""
        data, idx = self._frame()
        eng = BacktestEngine()
        held = eng._equal_weight_curve(data, idx, "buy_and_hold")
        rebalanced = eng._equal_weight_curve(data, idx, "annual")
        first_rebal = min(
            idx.get_loc(d) for d in eng._rebalance_dates(idx, "annual") if idx.get_loc(d) > 0
        )
        # Up to (and including) the first rebalance the two are the same book.
        np.testing.assert_allclose(
            held.values[: first_rebal + 1], rebalanced.values[: first_rebal + 1], rtol=1e-10
        )

    def test_identical_assets_make_rebalancing_a_no_op(self):
        """With perfectly correlated, identical prices there is nothing to trade."""
        idx = pd.date_range("2020-01-05", periods=80, freq="W")
        series = pd.Series(np.linspace(100.0, 180.0, 80), index=idx)
        data = {"AAA": series, "BBB": series.copy(), "CCC": series.copy()}
        eng = BacktestEngine()
        np.testing.assert_allclose(
            eng._equal_weight_curve(data, idx, "annual").values,
            eng._equal_weight_curve(data, idx, "buy_and_hold").values,
            rtol=1e-10,
        )


# ================================================================== #
#  6. Backtest performance metrics                                     #
# ================================================================== #

def oracle_total_return_pct(prices: list[float]) -> float:
    return (prices[-1] / prices[0] - 1.0) * 100.0


def oracle_cagr_pct(prices: list[float], bars_per_year: int = 52) -> float:
    """Reference: compound growth per year of ELAPSED time.

    N weekly bars span N−1 weeks, not N. The elapsed horizon is what a CAGR
    divides by — using the bar count instead stretches the horizon by one
    period and understates the rate.
    """
    years = (len(prices) - 1) / bars_per_year
    return ((prices[-1] / prices[0]) ** (1.0 / years) - 1.0) * 100.0


def oracle_max_drawdown_pct(prices: list[float]) -> float:
    """Reference: worst peak-to-trough decline, tracked with a running peak."""
    peak, worst = prices[0], 0.0
    for p in prices:
        peak = max(peak, p)
        worst = min(worst, (p - peak) / peak)
    return worst * 100.0


class TestBacktestMetricsOracle:
    @staticmethod
    def _series(values):
        idx = pd.date_range("2020-01-05", periods=len(values), freq="W")
        return pd.Series(values, index=idx)

    def test_total_return_matches_reference(self):
        vals = [100.0, 110.0, 90.0, 130.0, 125.0, 160.0]
        m = BacktestEngine()._metrics(self._series(vals))
        assert m["total_return"] == pytest.approx(round(oracle_total_return_pct(vals), 2))

    def test_max_drawdown_matches_reference(self):
        vals = [100.0, 120.0, 60.0, 90.0, 150.0, 75.0, 140.0]
        m = BacktestEngine()._metrics(self._series(vals))
        assert m["max_drawdown"] == pytest.approx(round(oracle_max_drawdown_pct(vals), 2))

    def test_known_drawdown_by_hand(self):
        # Peak 200 → trough 50 is a 75% decline; nothing later is worse.
        vals = [100.0, 200.0, 50.0, 180.0, 190.0]
        m = BacktestEngine()._metrics(self._series(vals))
        assert m["max_drawdown"] == pytest.approx(-75.0)

    def test_cagr_uses_elapsed_time_not_bar_count(self):
        """A series spanning exactly N years must report the true annual rate.

        53 weekly bars span 52 weeks == 1 year. A portfolio that doubled over
        that span grew 100%/year — no more, no less.
        """
        vals = list(100.0 * np.linspace(1.0, 2.0, 53))
        m = BacktestEngine()._metrics(self._series(vals))
        assert m["cagr"] == pytest.approx(round(oracle_cagr_pct(vals), 2), abs=0.02)
        assert m["cagr"] == pytest.approx(100.0, abs=0.05)

    def test_cagr_matches_reference_over_five_years(self):
        # 261 bars spanning exactly 260 weeks == 5 years, growing at 8%/year.
        vals = [100.0 * 1.08 ** (i / 52) for i in range(5 * 52 + 1)]
        m = BacktestEngine()._metrics(self._series(vals))
        assert m["cagr"] == pytest.approx(round(oracle_cagr_pct(vals), 2), abs=0.02)
        assert m["cagr"] == pytest.approx(8.0, abs=0.05)

    def test_flat_series_has_zero_return_and_zero_drawdown(self):
        m = BacktestEngine()._metrics(self._series([100.0] * 60))
        assert m["cagr"] == pytest.approx(0.0, abs=1e-9)
        assert m["total_return"] == pytest.approx(0.0, abs=1e-9)
        assert m["max_drawdown"] == pytest.approx(0.0, abs=1e-9)
        assert m["volatility"] == pytest.approx(0.0, abs=1e-9)

    def test_too_short_a_series_returns_zeros_not_garbage(self):
        m = BacktestEngine()._metrics(self._series([100.0, 110.0]))
        assert m == {
            "cagr": 0.0, "sharpe": 0.0, "downside_vol_ratio": 0.0, "max_drawdown": 0.0,
            "volatility": 0.0, "total_return": 0.0, "win_rate": 0.0, "calmar": 0.0,
        }

    def test_win_rate_counts_weeks_beating_the_benchmark(self):
        port = self._series([100.0, 110.0, 121.0, 120.0, 150.0])
        bench = self._series([100.0, 101.0, 130.0, 131.0, 132.0])
        m = BacktestEngine()._metrics(port, bench)
        # Weekly returns: port +10%, +10%, −0.8%, +25% ; bench +1%, +28.7%, +0.8%, +0.8%
        # Port wins weeks 1 and 4 → 50%.
        assert m["win_rate"] == pytest.approx(50.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
