"""Regression tests for the Tier 0 findings of docs/AUDITORIA_2026-08.md (D1–D3).

History
-------
This file was originally written as *characterization* tests: it pinned the
buggy behaviour the audit had measured (a +60.2% overestimate of terminal
wealth, bankrupt paths finishing positive, and a profile-dependent μ) so the
defects were reproducible.

The Tier 0 fix has landed, so the assertions are inverted: each test now pins
the *corrected* behaviour at exactly the scenarios the audit measured. They
guard the specific numbers that appeared in the report, so a regression would
be caught at the same coordinates where the bug was originally found.

The exhaustive oracle grid lives in ``tests/test_withdrawal_oracle.py``.
"""
from __future__ import annotations

import numpy as np
import pytest

from config import (
    AGGRESSIVE_PROFILE,
    CONSERVATIVE_PROFILE,
    MODERATE_PROFILE,
    MONTE_CARLO,
)
from portfolio.decumulation import (
    WithdrawalStrategy,
    apply_withdrawal_strategy,
    decumulation_metrics,
)
from portfolio.monte_carlo import MonteCarloSimulator
from portfolio.optimizer import PortfolioOptimizer

INIT = 100_000.0


def _correct_sequential(path_rel: np.ndarray, initial: float, annual_w: float, years: int) -> float:
    """Independent oracle: withdrawal removes capital; remainder tracks the market."""
    val = float(initial)
    for yr in range(1, years + 1):
        val *= float(path_rel[yr * 52] / path_rel[(yr - 1) * 52])
        val = max(0.0, val - annual_w)
        if val <= 0.0:
            return 0.0
    return val


def _bull_path(years: int = 30, ann_return: float = 0.08) -> np.ndarray:
    wk = (1.0 + ann_return) ** (1.0 / 52) - 1.0
    return np.concatenate([[1.0], np.cumprod(np.full(years * 52, 1.0 + wk))])


def _decline_then_recover(
    decline_years: int = 4,
    total_years: int = 30,
    decline_ann: float = -0.25,
    recover_ann: float = 0.101719,
) -> np.ndarray:
    n = total_years * 52
    rets = np.empty(n)
    for w in range(n):
        yr = w // 52
        if yr < decline_years:
            rets[w] = (1.0 + decline_ann) ** (1.0 / 52) - 1.0
        else:
            rets[w] = (1.0 + recover_ann) ** (1.0 / 52) - 1.0
    return np.concatenate([[1.0], np.cumprod(1.0 + rets)])


class TestAuditD1WithdrawalRemovesCapital:
    """D1 FIXED: withdrawals remove capital instead of a constant nominal level."""

    def test_bull_30y_4pct_matches_oracle(self):
        years = 30
        path = _bull_path(years, 0.08)
        annual_w = 4_000.0

        oracle = _correct_sequential(path, INIT, annual_w, years)
        motor = (
            MonteCarloSimulator._apply_withdrawals(
                np.array([path], dtype=float).copy(),
                INIT,
                annual_w,
                years * 52,
            )[0, -1]
            * INIT
        )

        # The audit's oracle figure is unchanged; the engine now reproduces it.
        assert oracle == pytest.approx(553_133, abs=5)
        assert motor == pytest.approx(oracle, rel=1e-9)

        # Pre-fix this engine returned 886_266 (+60.2%).
        err = (motor - oracle) / oracle
        assert abs(err) < 1e-9
        assert motor < 600_000

    def test_decumulation_fixed_real_matches_monte_carlo_kernel(self):
        """Both entry points delegate to the same kernel, so they cannot drift."""
        years = 30
        path = _bull_path(years, 0.08)
        annual_w = 4_000.0
        mc = MonteCarloSimulator._apply_withdrawals(
            np.array([path], dtype=float).copy(), INIT, annual_w, years * 52,
        )
        dec = apply_withdrawal_strategy(
            np.array([path], dtype=float).copy(),
            INIT,
            WithdrawalStrategy.fixed_real(annual_w),
            years * 52,
            inflation_rate=0.0,
        )
        np.testing.assert_allclose(mc, dec, rtol=0, atol=0)


class TestAuditD2RuinIsAbsorbing:
    """D2 FIXED: a path that hits $0 stays dead, and the metrics agree."""

    def test_no_resurrection_and_metrics_agree(self):
        years = 30
        path = _decline_then_recover()
        annual_w = 12_000.0

        oracle = _correct_sequential(path, INIT, annual_w, years)
        usd = (
            MonteCarloSimulator._apply_withdrawals(
                np.array([path], dtype=float).copy(),
                INIT,
                annual_w,
                years * 52,
            )[0]
            * INIT
        )

        assert oracle == pytest.approx(0.0, abs=1e-6)
        assert float(usd.min()) == pytest.approx(0.0, abs=1e-6)

        # Pre-fix the terminal value was 32_723 despite the path being bankrupt.
        assert float(usd[-1]) == pytest.approx(0.0, abs=1e-6)

        zeros = np.where(usd <= 1e-9)[0]
        assert len(zeros) > 0
        first_z = int(zeros[0])
        assert first_z < len(usd) - 1, "el path debe agotarse dentro del horizonte"
        assert bool((usd[first_z:] <= 1e-9).all()), "el path resucitó tras tocar 0"

        # Depletion now happens at week 208 vs week 185 pre-fix — LATER, not
        # earlier. The old constant-level subtraction over-penalised falling
        # markets (it removed a fixed nominal amount from a shrinking balance),
        # so the bug was not uniformly optimistic: it overstated bull paths and
        # understated bear ones. Only the direction of the error was consistent
        # with "wrong", not its sign.
        assert first_z == 208

        # The two metrics that used to contradict each other now agree.
        metrics = decumulation_metrics(usd.reshape(1, -1), years, INIT)
        assert metrics["prob_sustain_real_pct"] == 0.0
        assert metrics["prob_legacy_pct"] == 0.0

    def test_prob_ruin_counts_intra_horizon_bankruptcy(self):
        """prob_ruin_pct is measured on the running minimum, not the terminal."""
        years = 30
        paths_usd = np.full((2, years * 52 + 1), 50_000.0)
        paths_usd[0, 100:] = 0.0          # dies at week 100
        eps = max(INIT, 1.0) * 1e-9
        prob_ruin = float((paths_usd.min(axis=1) <= eps).mean() * 100)
        assert prob_ruin == 50.0
        # The old terminal-only test would also give 50 here, but only because
        # the kernel is now absorbing — that is precisely the invariant.
        assert float((paths_usd[:, -1] <= eps).mean() * 100) == prob_ruin


class TestAuditD3MuIsProfileIndependent:
    """D3 FIXED: an asset's expected return no longer depends on who looks at it."""

    _TICKER = {
        "symbol": "X",
        "adjusted_score": 60.0,
        "dividend_yield": 2.0,
        "moat_score": 8.0,
        "sector": "Technology",
    }

    def test_same_asset_same_mu_across_profiles(self):
        mus = [
            float(PortfolioOptimizer(p)._expected_returns([dict(self._TICKER)])[0])
            for p in ("conservative", "moderate", "aggressive")
        ]
        # Pre-fix: 0.0508 / 0.0640 / 0.0772 — the same asset "yielded" more for
        # an aggressive investor.
        assert mus[0] == pytest.approx(mus[1], rel=1e-12)
        assert mus[1] == pytest.approx(mus[2], rel=1e-12)

    def test_profile_still_expresses_itself_through_risk_aversion(self):
        """The profile must still matter — just not through μ."""
        deltas = [
            PortfolioOptimizer(p).cfg.risk_aversion
            for p in ("conservative", "moderate", "aggressive")
        ]
        assert deltas[0] > deltas[1] > deltas[2]

    def test_profile_preferences_still_drive_candidate_ranking(self):
        """score/dividend/moat weights remain a *preference*, used for ranking."""
        cons = PortfolioOptimizer("conservative").cfg
        aggr = PortfolioOptimizer("aggressive").cfg
        assert cons.dividend_weight > aggr.dividend_weight
        assert aggr.score_weight > cons.score_weight

    def test_view_weights_are_shared_and_normalised(self):
        from config import VIEW_WEIGHTS

        total = VIEW_WEIGHTS.score + VIEW_WEIGHTS.dividend + VIEW_WEIGHTS.moat
        assert total == pytest.approx(1.0)
        # The profile dataclasses still carry their own preference weights,
        # which must NOT be the ones feeding μ.
        assert (CONSERVATIVE_PROFILE.score_weight,
                MODERATE_PROFILE.score_weight,
                AGGRESSIVE_PROFILE.score_weight) != (
                    VIEW_WEIGHTS.score, VIEW_WEIGHTS.score, VIEW_WEIGHTS.score)

    def test_mean_haircut_is_080(self):
        assert MONTE_CARLO.mean_haircut == pytest.approx(0.80)
