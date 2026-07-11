"""Tests for the decumulation / withdrawal-strategy engine (Fase H.1).

Pure NumPy — no network, no Streamlit. Verifies strategy mechanics,
byte-identity of ``fixed_real`` with the legacy MC withdrawal math, and the
retirement success metrics.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio.decumulation import (
    WithdrawalStrategy,
    apply_withdrawal_strategy,
    decumulation_metrics,
)
from portfolio.monte_carlo import MonteCarloSimulator

# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _flat_paths(n_sims: int, horizon_years: int, value: float = 1.0) -> np.ndarray:
    """Constant relative paths (no growth) of shape (n_sims, weeks+1)."""
    n_weeks = horizon_years * 52
    return np.full((n_sims, n_weeks + 1), value, dtype=float)


# ------------------------------------------------------------------ #
#  Strategy descriptor                                                 #
# ------------------------------------------------------------------ #

class TestWithdrawalStrategy:
    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError):
            WithdrawalStrategy(kind="nonsense")

    def test_coerce_none(self):
        assert WithdrawalStrategy.coerce(None) is None

    def test_coerce_dict_roundtrip(self):
        s = WithdrawalStrategy.guardrails(0.035)
        d = s.to_dict()
        again = WithdrawalStrategy.coerce(d)
        assert again.kind == "guardrails"
        assert again.pct == pytest.approx(0.035)

    def test_coerce_passthrough_instance(self):
        s = WithdrawalStrategy.fixed_real(40_000)
        assert WithdrawalStrategy.coerce(s) is s

    def test_constructors_set_labels(self):
        assert WithdrawalStrategy.fixed_real(40_000).label
        assert WithdrawalStrategy.constant_pct(0.04).label
        assert WithdrawalStrategy.guardrails(0.04).label


# ------------------------------------------------------------------ #
#  fixed_real byte-identity with legacy engine                         #
# ------------------------------------------------------------------ #

class TestFixedRealParity:
    def test_matches_legacy_apply_withdrawals(self):
        rng = np.random.default_rng(0)
        n_weeks = 20 * 52
        paths = np.cumprod(
            1 + rng.normal(0.001, 0.02, size=(500, n_weeks)), axis=1
        )
        paths = np.concatenate([np.ones((500, 1)), paths], axis=1)
        initial, amount, infl = 100_000.0, 4_000.0, 0.03

        legacy = MonteCarloSimulator._apply_withdrawals(
            paths.copy(), initial, amount, n_weeks, withdrawal_growth_rate=infl
        )
        strat = WithdrawalStrategy.fixed_real(amount)
        new = apply_withdrawal_strategy(paths, initial, strat, n_weeks, inflation_rate=infl)

        np.testing.assert_array_equal(legacy, new)

    def test_does_not_mutate_input(self):
        paths = _flat_paths(10, 5)
        original = paths.copy()
        apply_withdrawal_strategy(
            paths, 100_000, WithdrawalStrategy.fixed_real(4_000), 5 * 52
        )
        np.testing.assert_array_equal(paths, original)


# ------------------------------------------------------------------ #
#  constant_pct mechanics                                              #
# ------------------------------------------------------------------ #

class TestConstantPct:
    def test_never_negative(self):
        paths = _flat_paths(50, 30)
        out = apply_withdrawal_strategy(
            paths, 100_000, WithdrawalStrategy.constant_pct(0.10), 30 * 52
        )
        assert (out >= 0).all()

    def test_reduces_value_each_year(self):
        # Flat market, 10% of current each year → geometric decay 0.9**yr.
        paths = _flat_paths(1, 3, value=1.0)
        out = apply_withdrawal_strategy(
            paths, 100_000, WithdrawalStrategy.constant_pct(0.10), 3 * 52
        )
        # After yr1 (week 52): 0.9 ; yr2: 0.81 ; yr3 (terminal): 0.729
        assert out[0, -1] == pytest.approx(0.729, abs=1e-9)


# ------------------------------------------------------------------ #
#  guardrails mechanics                                                #
# ------------------------------------------------------------------ #

class TestGuardrails:
    def test_cuts_spending_in_down_market(self):
        # Portfolio drops to 0.5 immediately → withdrawal rate doubles vs initial,
        # breaching the upper guardrail → spending should be cut below the base.
        n_weeks = 5 * 52
        paths = np.full((1, n_weeks + 1), 0.5, dtype=float)
        paths[0, 0] = 1.0
        strat = WithdrawalStrategy.guardrails(0.04, ceiling_band=0.20, cut_pct=0.10)
        out = apply_withdrawal_strategy(paths, 100_000, strat, n_weeks)
        # First-year withdrawal = base*(1-cut) of relative units = 0.04*0.9 = 0.036
        # value at wk52 before wd = 0.5 → after = 0.5 - 0.036 = 0.464
        assert out[0, 52] == pytest.approx(0.464, abs=1e-6)

    def test_raises_spending_in_up_market(self):
        # Portfolio grows to 2.0 → withdrawal rate halves, below lower guardrail
        # → spending raised above base.
        n_weeks = 5 * 52
        paths = np.full((1, n_weeks + 1), 2.0, dtype=float)
        paths[0, 0] = 1.0
        strat = WithdrawalStrategy.guardrails(0.04, floor_band=0.20, raise_pct=0.10)
        out = apply_withdrawal_strategy(paths, 100_000, strat, n_weeks)
        # withdrawal = 0.04*1.1 = 0.044 of relative units; value 2.0 → 1.956
        assert out[0, 52] == pytest.approx(1.956, abs=1e-6)

    def test_guardrails_sustains_better_than_fixed_in_crash(self):
        # A path that crashes then stays low: guardrails (which cut spending)
        # should leave more money than a fixed-real withdrawal.
        n_weeks = 20 * 52
        paths = np.full((5, n_weeks + 1), 0.4, dtype=float)
        paths[:, 0] = 1.0
        fixed = apply_withdrawal_strategy(
            paths, 100_000, WithdrawalStrategy.fixed_real(4_000), n_weeks
        )
        guard = apply_withdrawal_strategy(
            paths, 100_000, WithdrawalStrategy.guardrails(0.04), n_weeks
        )
        assert guard[:, -1].mean() >= fixed[:, -1].mean()


# ------------------------------------------------------------------ #
#  Success metrics                                                     #
# ------------------------------------------------------------------ #

class TestDecumulationMetrics:
    def test_all_sustained_no_depletion(self):
        paths_usd = _flat_paths(100, 10, value=1.0) * 100_000
        m = decumulation_metrics(paths_usd, 10, 100_000)
        assert m["prob_sustain_real_pct"] == 100.0
        assert m["prob_legacy_pct"] == 100.0
        assert m["expected_depletion_year"] == 0.0
        assert m["longevity_years"] == 10

    def test_full_depletion_metrics(self):
        # Every path is zero from week 52 onward → depleted at year 1.
        paths_usd = np.zeros((10, 10 * 52 + 1))
        paths_usd[:, :52] = 100_000.0
        m = decumulation_metrics(paths_usd, 10, 100_000)
        assert m["prob_sustain_real_pct"] == 0.0
        assert m["prob_legacy_pct"] == 0.0
        assert m["expected_depletion_year"] == pytest.approx(1.0, abs=0.05)

    def test_longevity_window_caps_horizon(self):
        # Money lasts 8 years then depletes; measuring only 5 years → sustained.
        paths_usd = np.full((4, 10 * 52 + 1), 100_000.0)
        paths_usd[:, 8 * 52:] = 0.0
        m5 = decumulation_metrics(paths_usd, 10, 100_000, longevity_years=5)
        m10 = decumulation_metrics(paths_usd, 10, 100_000, longevity_years=10)
        assert m5["prob_sustain_real_pct"] == 100.0
        assert m10["prob_sustain_real_pct"] == 0.0

    def test_empty_paths(self):
        m = decumulation_metrics(np.empty((0, 0)), 10, 100_000)
        assert m["prob_sustain_real_pct"] == 0.0
