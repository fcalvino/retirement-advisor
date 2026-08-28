"""Oracle tests for how money ENTERS the pot (backlog U4-2 and U4-1).

``tests/test_withdrawal_oracle.py`` pinned the way money leaves (audit D1/D2).
Nothing pinned the way it arrives, and two defects lived there:

  * **U4-2** — the cash flow is expressed as a fraction of ``initial_value``
    (``monte_carlo.py``, ``_apply_withdrawals``), so a plan that starts with no
    capital has no unit to express its savings in. The code turned that into
    ``0.0`` and the whole plan projected zero: 0 % probability of success for
    the one question a young saver asks. A silent zero, not an error.
  * **U4-1** — a monthly saving was multiplied by twelve and deposited whole in
    week 52, so eleven of the twelve deposits lost their partial year of growth.

Both are cash-flow *accounting*, so both are testable the way the audit demands:
against a slow reference written from the financial definition — a saver who
deposits on a date and whose money only compounds from that date — never against
the engine's own previous output, which would freeze the bug rather than find it.

The market model is not under test here, so it is made deterministic: a history
whose weekly return is constant resamples to itself, so every bootstrapped path
is the same geometric curve and the reference can be written in closed form.

No network, no Streamlit, no fixtures shared with the production modules.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from config import MONTE_CARLO
from portfolio.monte_carlo import MonteCarloSimulator

# ------------------------------------------------------------------ #
#  Deterministic market (shared inputs, not shared logic)              #
# ------------------------------------------------------------------ #

MONTHS_PER_YEAR = 12


def _weekly_rate(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 52.0) - 1.0


def _flat_history(annual_rate: float, n_bars: int = 520):
    """A price series whose weekly return never varies.

    Resampling a constant series returns the constant, so the bootstrap becomes
    deterministic and the projection is a plain geometric curve. That removes
    the stochastic model from the picture and leaves only the cash-flow
    accounting, which is what these tests are about.
    """
    weekly = _weekly_rate(annual_rate)
    prices = 100.0 * np.cumprod(np.full(n_bars, 1.0 + weekly))
    dates = pd.date_range("2016-01-03", periods=n_bars, freq="W")
    return pd.DataFrame({"close": prices}, index=dates)


def _effective_weekly(annual_rate: float) -> float:
    """The weekly rate the engine actually projects with.

    ``_conservative_adjustment`` keeps ``mean_haircut`` of the historical mean
    and widens deviations by ``vol_adjustment``. With a constant history there
    are no deviations, so only the haircut survives. Read from config rather
    than hardcoded — the haircut is an input to these tests, not their subject.
    """
    return _weekly_rate(annual_rate) * MONTE_CARLO.mean_haircut


def _index(annual_rate: float, years: int) -> np.ndarray:
    """The relative market curve the engine projects, starting at 1.0."""
    w = _effective_weekly(annual_rate)
    return np.concatenate([[1.0], np.cumprod(np.full(years * 52, 1.0 + w))])


def _contribution_weeks(years: int) -> list[int]:
    """Week index of each monthly deposit. Month 12 lands exactly on week 52."""
    return [
        round(m * 52 / MONTHS_PER_YEAR) + (yr - 1) * 52
        for yr in range(1, years + 1)
        for m in range(1, MONTHS_PER_YEAR + 1)
    ]


# ================================================================== #
#  References — written from the definition, not from the source       #
# ================================================================== #

def oracle_monthly_contribution_sequence(
    index: np.ndarray,
    initial: float,
    annual_contribution: float,
    years: int,
    growth_rate: float = 0.0,
) -> float:
    """Reference: a saver who deposits one twelfth on the first bar of a month.

    Walks the market curve one deposit at a time. Each deposit joins the pot at
    the level of the week it arrives and compounds only from there — which is
    what depositing money means. The annual raise is applied once per year, so
    the twelve deposits of a year sum to exactly the year's nominal total.
    """
    wealth = initial
    previous_week = 0
    for week in _contribution_weeks(years):
        year = min(max((week - 1) // 52 + 1, 1), years)
        wealth *= index[week] / index[previous_week]
        wealth += (annual_contribution / MONTHS_PER_YEAR) * (
            (1.0 + growth_rate) ** (year - 1)
        )
        previous_week = week
    wealth *= index[-1] / index[previous_week]
    return wealth


def oracle_annual_lump_sequence(
    index: np.ndarray,
    initial: float,
    annual_contribution: float,
    years: int,
) -> float:
    """Reference for the PRE-FIX instrument: one deposit per year, at week 52.

    Kept as a reference so the direction of the change is provable rather than
    asserted: the same money deposited later can never be worth more.
    """
    wealth = initial
    for yr in range(1, years + 1):
        wealth *= index[yr * 52] / index[(yr - 1) * 52]
        wealth += annual_contribution
    return wealth


# ================================================================== #
#  1. A plan that starts empty (U4-2)                                  #
# ================================================================== #

class TestZeroCapitalAccumulationOracle:
    """"¿Llego si ahorro X por mes?" must be answerable without seed capital."""

    HORIZON = 20
    RATE = 0.07
    CONTRIB = 12_000.0

    def _run(self, initial: float, contribution: float, **kw):
        sim = MonteCarloSimulator(["AAPL"], seed=42)
        with patch(
            "portfolio.monte_carlo.get_history",
            side_effect=lambda *a, **k: _flat_history(self.RATE),
        ):
            return sim.run(
                horizon_years=self.HORIZON,
                n_sims=200,
                initial_value=initial,
                annual_withdrawal=-contribution,
                **kw,
            )

    def test_a_plan_that_starts_empty_still_compounds_its_savings(self):
        result = self._run(initial=0.0, contribution=self.CONTRIB)

        expected = oracle_monthly_contribution_sequence(
            _index(self.RATE, self.HORIZON), 0.0, self.CONTRIB, self.HORIZON
        )
        assert result.median_terminal > 0.0
        assert result.median_terminal == pytest.approx(expected, rel=1e-9)

    def test_savings_only_plan_can_reach_its_target(self):
        result = self._run(initial=0.0, contribution=self.CONTRIB, target_value=100_000.0)
        assert result.prob_achieve_target_pct > 0.0

    def test_ruin_does_not_count_the_weeks_before_the_first_deposit(self):
        """Starting empty is the accumulation phase, not bankruptcy.

        The pot is worth 0 until the first contribution lands. Reading that
        prefix as ruin would report 100 % failure for every saver who begins
        with nothing — the opposite of the truth about their plan.
        """
        result = self._run(initial=0.0, contribution=self.CONTRIB)
        assert result.prob_ruin_pct == 0.0

    def test_a_plan_with_neither_capital_nor_savings_is_still_zero(self):
        """Anti-cheat: the fix must not be "never report a zero"."""
        result = self._run(initial=0.0, contribution=0.0)
        assert result.median_terminal == 0.0

    def test_annualised_growth_stays_a_finite_number_without_capital(self):
        """Pot growth divides by ``initial_value``; with no capital it is undefined.

        It must degrade to something a caller can render, not to ``inf``.
        """
        result = self._run(initial=0.0, contribution=self.CONTRIB)
        assert np.isfinite(result.median_cagr_pct)
        assert np.isfinite(result.p10_cagr_pct)


# ================================================================== #
#  2. Cadence (U4-1)                                                   #
# ================================================================== #

class TestMonthlyCadenceOracle:
    """A monthly saving must arrive monthly, not as a lump every December."""

    HORIZON = 15
    CONTRIB = 12_000.0

    def _run(self, annual_rate: float, initial: float, contribution: float, **kw):
        sim = MonteCarloSimulator(["AAPL"], seed=7)
        with patch(
            "portfolio.monte_carlo.get_history",
            side_effect=lambda *a, **k: _flat_history(annual_rate),
        ):
            return sim.run(
                horizon_years=self.HORIZON,
                n_sims=200,
                initial_value=initial,
                annual_withdrawal=-contribution,
                **kw,
            )

    @pytest.mark.parametrize("annual_rate", [-0.04, 0.0, 0.05, 0.09])
    def test_engine_matches_the_monthly_reference(self, annual_rate):
        result = self._run(annual_rate, initial=50_000.0, contribution=self.CONTRIB)

        expected = oracle_monthly_contribution_sequence(
            _index(annual_rate, self.HORIZON), 50_000.0, self.CONTRIB, self.HORIZON
        )
        assert result.median_terminal == pytest.approx(expected, rel=1e-9)

    def test_twelve_monthly_deposits_beat_one_annual_lump(self):
        """The same money, deposited earlier, is worth more. That is the bug."""
        index = _index(0.07, self.HORIZON)
        monthly = oracle_monthly_contribution_sequence(
            index, 0.0, self.CONTRIB, self.HORIZON
        )
        lump = oracle_annual_lump_sequence(index, 0.0, self.CONTRIB, self.HORIZON)

        assert monthly > lump
        result = self._run(0.07, initial=0.0, contribution=self.CONTRIB)
        assert result.median_terminal == pytest.approx(monthly, rel=1e-9)

    def test_cadence_cannot_matter_in_a_market_that_does_not_move(self):
        """With no growth to lose, timing is worth exactly nothing."""
        index = _index(0.0, self.HORIZON)
        monthly = oracle_monthly_contribution_sequence(
            index, 0.0, self.CONTRIB, self.HORIZON
        )
        lump = oracle_annual_lump_sequence(index, 0.0, self.CONTRIB, self.HORIZON)
        assert monthly == pytest.approx(lump, rel=1e-12)

    def test_the_annual_raise_moves_the_timing_not_the_yearly_total(self):
        """Inflation-adjusted savings still deposit the year's nominal total.

        The raise steps once a year, so the twelve deposits of year *k* sum to
        the same amount the old yearly lump would have deposited. Only *when*
        the money arrives changes — which is what makes the direction of the
        fix provable instead of merely different.
        """
        growth, rate = 0.03, 0.0
        index = _index(rate, self.HORIZON)
        with_raise = oracle_monthly_contribution_sequence(
            index, 0.0, self.CONTRIB, self.HORIZON, growth_rate=growth
        )
        expected_nominal = sum(
            self.CONTRIB * (1.0 + growth) ** (yr - 1) for yr in range(1, self.HORIZON + 1)
        )
        assert with_raise == pytest.approx(expected_nominal, rel=1e-12)

        result = self._run(
            rate, initial=0.0, contribution=self.CONTRIB, withdrawal_growth_rate=growth
        )
        assert result.median_terminal == pytest.approx(with_raise, rel=1e-9)


# ================================================================== #
#  3. The invariants the fix must not break                            #
# ================================================================== #

class TestDepletionIsStillAbsorbing:
    """U4-2 makes an empty pot fundable. It must not make a ruined pot revivable."""

    def test_market_growth_never_revives_a_pot_that_was_spent(self):
        sim = MonteCarloSimulator(["AAPL"], seed=3)
        with patch(
            "portfolio.monte_carlo.get_history",
            side_effect=lambda *a, **k: _flat_history(0.05),
        ):
            result = sim.run(
                horizon_years=30,
                n_sims=200,
                initial_value=100_000.0,
                annual_withdrawal=50_000.0,   # spends the pot within a few years
            )
        assert result.prob_ruin_pct == 100.0
        assert result.median_terminal == 0.0

    def test_a_cash_flow_never_mutates_the_market_series(self):
        """U2-2 holds because drawdown is read off an untouched market curve.

        Today that is true only because ``run`` computes the drawdown before
        calling the kernel — the legacy kernel writes through its input. Making
        it structurally true is what lets the ordering stop being load-bearing.
        """
        path = np.array([_index(0.06, 10)])
        before = path.copy()
        MonteCarloSimulator._apply_withdrawals(path, 100_000.0, 5_000.0, 10 * 52)
        np.testing.assert_array_equal(path, before)


# ================================================================== #
#  4. One unit, one source (U4-1's second oracle)                      #
# ================================================================== #

class TestContributionUnitsContract:
    """Simulaciones and Metas must ask for the same money.

    They cannot be compared as rendered numbers: the main Monte Carlo tab has
    no contribution widget at all (its only cash-flow input is a withdrawal
    floored at zero), while Metas asks for a yearly figure seeded from a
    monthly profile. So the contract is asserted where it can be true — one
    pure helper owning the ×12, and both surfaces reading it.
    """

    def test_the_helper_converts_in_one_place(self):
        from data.product_ux import contribution_inputs

        resolved = contribution_inputs(personal={"monthly_savings": 500.0})
        assert resolved["monthly"] == pytest.approx(500.0)
        assert resolved["annual"] == pytest.approx(6_000.0)
        assert resolved["source"]

    def test_no_surface_multiplies_savings_by_twelve_on_its_own(self):
        from pathlib import Path

        page = Path("dashboard/pages/7_Simulaciones.py").read_text(encoding="utf-8")
        assert "contribution_inputs" in page

    def test_no_surface_reads_a_session_key_no_widget_writes(self):
        """``annual_contribution`` is read from session state but never written.

        A key nothing writes always resolves to its fallback, which is a silent
        zero wearing the costume of a user input.
        """
        from pathlib import Path

        page = Path("dashboard/pages/7_Simulaciones.py").read_text(encoding="utf-8")
        assert 'st.session_state.get("annual_contribution")' not in page


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
