"""A shortfall has to be in dollars of one year (backlog U5-13).

``GoalPlan.compute_aggregates`` summed each goal's ``target_nominal`` — the
amount needed **in that goal's own target year** — and subtracted the sum of each
goal's ``median_terminal``, also in its own year. A car in 2031 and a retirement
in 2051 were added together and the result presented as *"te falta esto"*.

Nominal dollars from different years are not the same unit, so their sum is not a
quantity. It also runs one way: the further out the goal, the more its inflated
nominal target overstates what reaching it actually costs in effort today. On a
plausible three-goal plan — a car at 5 years, a house at 12, retirement at 25 —
the nominal sum reads **$1.92 M against $980 k in today's money, a 96 %
overstatement**, and the figure shown had no year attached to it at all.

The fix deflates each goal to today with the goal's own ``expected_inflation``
over its own horizon, using ``product_ux.present_value_usd`` — already the single
implementation of ``nominal / (1 + i) ** n`` for the product surface. The fields
carry a ``_today`` suffix because a number whose name does not say its unit is
how this one survived.

No network, no Streamlit.
"""

from __future__ import annotations

import pytest

from data.product_ux import present_value_usd
from portfolio.goals import Goal, GoalPlan, GoalResult
from portfolio.monte_carlo import MonteCarloResult


def oracle_present_value(nominal: float, inflation_pct: float, years: float) -> float:
    """Reference: what a future amount is worth in today's purchasing power."""
    return nominal / ((1.0 + inflation_pct / 100.0) ** years)


def _result(name: str, *, today_amount: float, years: int, terminal: float,
            inflation: float = 3.0) -> GoalResult:
    goal = Goal(name=name, target_amount_today=today_amount, horizon_years=years,
                expected_inflation=inflation)
    mc = MonteCarloResult(
        n_sims=100, horizon_years=years, initial_value=0.0,
        annual_withdrawal=0.0, target_value=goal.target_nominal,
    )
    mc.median_terminal = terminal
    mc.prob_achieve_target_pct = 50.0
    return GoalResult(goal=goal, mc_result=mc, allocated_capital=0.0)


def _plan(*results: GoalResult) -> GoalPlan:
    plan = GoalPlan(goal_results=list(results), total_capital=0.0, n_sims=100)
    plan.compute_aggregates()
    return plan


class TestTheTotalIsInOneYearsDollars:
    def test_a_single_goal_total_is_its_target_in_todays_money(self):
        """With one goal there is nothing to mix, so the answer is exact."""
        plan = _plan(_result("Auto", today_amount=30_000, years=5, terminal=0.0))
        assert plan.total_capital_needed_today == pytest.approx(30_000, rel=1e-9)

    def test_two_goals_are_not_added_in_different_years(self):
        near = _result("Auto", today_amount=30_000, years=5, terminal=0.0)
        far = _result("Retiro", today_amount=800_000, years=25, terminal=0.0)
        plan = _plan(near, far)

        nominal_sum = near.target_nominal + far.target_nominal
        assert plan.total_capital_needed_today == pytest.approx(830_000, rel=1e-9)
        assert plan.total_capital_needed_today < nominal_sum

    def test_the_further_goal_is_discounted_more(self):
        """The overstatement grows with the horizon; that is its shape."""
        near = _plan(_result("A", today_amount=100_000, years=5, terminal=0.0))
        far = _plan(_result("B", today_amount=100_000, years=25, terminal=0.0))
        assert near.total_capital_needed_today == pytest.approx(
            far.total_capital_needed_today, rel=1e-9
        )
        # Same purchasing power today, different nominal targets: exactly the
        # twenty extra years of inflation between them, and nothing else.
        ratio = far.goal_results[0].target_nominal / near.goal_results[0].target_nominal
        assert ratio == pytest.approx(1.03 ** 20, rel=1e-9)

    def test_each_goal_uses_its_own_inflation(self):
        low = _plan(_result("A", today_amount=100_000, years=10, terminal=0.0, inflation=2.0))
        high = _plan(_result("B", today_amount=100_000, years=10, terminal=0.0, inflation=8.0))
        assert low.total_capital_needed_today == pytest.approx(
            high.total_capital_needed_today, rel=1e-9
        )


class TestTheGapIsInOneYearsDollars:
    def test_the_gap_matches_the_reference(self):
        gr = _result("Casa", today_amount=150_000, years=12, terminal=100_000.0)
        plan = _plan(gr)

        expected = oracle_present_value(gr.target_nominal - 100_000.0, 3.0, 12)
        assert plan.capital_gap_today == pytest.approx(expected, rel=1e-9)
        assert plan.capital_gap_today == pytest.approx(
            present_value_usd(gr.target_nominal - 100_000.0,
                              annual_inflation_pct=3.0, years=12),
            rel=1e-9,
        )

    def test_a_goal_that_overshoots_does_not_mask_one_that_falls_short(self):
        """Each goal is deflated before they meet, not after.

        Netting the nominal sums first lets a surplus in 2051 dollars cancel a
        shortfall in 2031 dollars — two different units.
        """
        short = _result("Auto", today_amount=30_000, years=5, terminal=0.0)
        over = _result("Retiro", today_amount=100_000, years=25, terminal=10_000_000.0)
        plan = _plan(short, over)

        assert plan.capital_gap_today == pytest.approx(30_000, rel=1e-9)

    def test_a_fully_funded_plan_has_no_gap(self):
        gr = _result("Auto", today_amount=30_000, years=5, terminal=1_000_000.0)
        assert _plan(gr).capital_gap_today == 0.0

    def test_the_gap_never_goes_negative(self):
        gr = _result("Auto", today_amount=30_000, years=5, terminal=999_999_999.0)
        assert _plan(gr).capital_gap_today >= 0.0

    def test_an_empty_plan_reports_nothing_rather_than_zero_confidence(self):
        plan = GoalPlan(goal_results=[], total_capital=0.0, n_sims=100)
        plan.compute_aggregates()
        assert plan.capital_gap_today == 0.0


class TestNoSurfaceQuotesAMixedYearSum:
    def test_the_mixed_year_fields_are_gone(self):
        plan = _plan(_result("Auto", today_amount=30_000, years=5, terminal=0.0))
        assert not hasattr(plan, "capital_gap")
        assert not hasattr(plan, "total_capital_needed")

    def test_both_surfaces_name_the_year_the_dollars_are_in(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for rel in ("dashboard/pages/7_Simulaciones.py", "reports/investment_plan.py"):
            src = (root / rel).read_text(encoding="utf-8")
            assert "capital_gap_today" in src, rel
            assert "hoy" in src.lower(), rel


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
