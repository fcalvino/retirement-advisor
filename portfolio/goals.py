"""
Multi-Goal Financial Planner.

Allows users to define multiple financial goals (e.g. house in 2029,
financial independence in 2035, retirement at 62) and simulate the
full plan with individual Monte Carlo projections per goal.

Usage:
    planner = GoalPlanner(symbols, weights)
    plan = planner.run(
        goals=[
            Goal("Casa en 2029", target_amount_today=300_000, horizon_years=3, priority=1),
            Goal("FIRE 2035", target_amount_today=1_500_000, horizon_years=9, priority=2),
        ],
        total_capital=500_000,
        n_sims=10_000,
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from portfolio.monte_carlo import MonteCarloResult, MonteCarloSimulator


# ------------------------------------------------------------------ #
#  Enums / constants                                                   #
# ------------------------------------------------------------------ #

PRIORITY_LABELS = {1: "Alta", 2: "Media", 3: "Baja"}
PRIORITY_COLORS = {1: "#DC3545", 2: "#FFC107", 3: "#28A745"}
PRIORITY_EMOJIS = {1: "🔴", 2: "🟡", 3: "🟢"}


# ------------------------------------------------------------------ #
#  Goal dataclass                                                      #
# ------------------------------------------------------------------ #

@dataclass
class Goal:
    """
    A single financial goal.

    Parameters
    ----------
    name : human-readable name (e.g. "Casa en 2029")
    target_amount_today : target in TODAY's dollars (will be inflation-adjusted)
    horizon_years : years from now to reach the goal
    priority : 1=high, 2=medium, 3=low
    expected_inflation : annual inflation rate for this goal's adjustment (default 3%)
    annual_contribution : annual savings directed toward this goal (USD/year, positive)
    allocated_capital : initial capital earmarked for this goal (USD)
                        If 0, GoalPlanner will auto-allocate proportional to priority.
    notes : optional free-text description
    """

    name: str
    target_amount_today: float
    horizon_years: int
    priority: int = 2
    expected_inflation: float = 3.0
    annual_contribution: float = 0.0
    allocated_capital: float = 0.0
    notes: str = ""

    @property
    def target_nominal(self) -> float:
        """Target in future dollars (inflation-adjusted)."""
        return self.target_amount_today * (1 + self.expected_inflation / 100) ** self.horizon_years

    @property
    def priority_label(self) -> str:
        return PRIORITY_LABELS.get(self.priority, "Media")

    @property
    def priority_color(self) -> str:
        return PRIORITY_COLORS.get(self.priority, "#FFC107")

    @property
    def priority_emoji(self) -> str:
        return PRIORITY_EMOJIS.get(self.priority, "🟡")


# ------------------------------------------------------------------ #
#  GoalResult: one goal's simulation output                           #
# ------------------------------------------------------------------ #

@dataclass
class GoalResult:
    """Simulation result for a single goal."""

    goal: Goal
    mc_result: MonteCarloResult
    allocated_capital: float

    @property
    def target_nominal(self) -> float:
        return self.goal.target_nominal

    @property
    def prob_success_pct(self) -> float:
        return self.mc_result.prob_achieve_target_pct

    @property
    def median_terminal(self) -> float:
        return self.mc_result.median_terminal

    @property
    def shortfall_median(self) -> float:
        """Median shortfall vs target (negative = surplus)."""
        return max(0.0, self.target_nominal - self.median_terminal)

    @property
    def surplus_median(self) -> float:
        """Median surplus above target (0 if under)."""
        return max(0.0, self.median_terminal - self.target_nominal)

    @property
    def feasibility_label(self) -> str:
        p = self.prob_success_pct
        if p >= 85:
            return "✅ Muy factible"
        elif p >= 65:
            return "⚠️ Factible con riesgos"
        elif p >= 40:
            return "🔶 Difícil — ajustar plan"
        else:
            return "❌ Inviable con parámetros actuales"

    @property
    def sorr_risk_pct(self) -> float:
        """Sequence-of-returns risk: % of paths with >30% drawdown in first 5 years."""
        return self.mc_result.sorr_early_drawdown_pct

    @property
    def max_drawdown_pct(self) -> float:
        """Median peak-to-trough drawdown across all simulation paths."""
        return self.mc_result.median_max_drawdown_pct


# ------------------------------------------------------------------ #
#  GoalPlan: the full multi-goal plan                                  #
# ------------------------------------------------------------------ #

@dataclass
class GoalPlan:
    """Complete multi-goal simulation result."""

    goal_results: List[GoalResult]
    total_capital: float
    n_sims: int

    # Aggregated metrics (computed after init via compute_aggregates)
    total_capital_needed: float = 0.0
    total_capital_allocated: float = 0.0
    capital_gap: float = 0.0            # positive = shortfall
    plan_feasibility_score: float = 0.0  # 0–100 weighted by priority
    warnings: List[str] = field(default_factory=list)

    def compute_aggregates(self) -> None:
        """Compute plan-level aggregates from individual goal results."""
        if not self.goal_results:
            return

        # Priority weights: high=3, medium=2, low=1
        priority_weight = {1: 3, 2: 2, 3: 1}

        weighted_prob_sum = 0.0
        total_weight = 0.0
        capital_needed_sum = 0.0

        for gr in self.goal_results:
            w = priority_weight.get(gr.goal.priority, 2)
            weighted_prob_sum += gr.prob_success_pct * w
            total_weight += w
            capital_needed_sum += gr.target_nominal

        self.plan_feasibility_score = (
            weighted_prob_sum / total_weight if total_weight > 0 else 0.0
        )
        self.total_capital_needed = capital_needed_sum
        self.total_capital_allocated = sum(gr.allocated_capital for gr in self.goal_results)
        self.capital_gap = max(0.0, self.total_capital_needed - sum(
            gr.median_terminal for gr in self.goal_results
        ))

        # Warnings
        for gr in self.goal_results:
            if gr.prob_success_pct < 40 and gr.goal.priority == 1:
                self.warnings.append(
                    f"⚠️ Meta de alta prioridad '{gr.goal.name}' tiene solo "
                    f"{gr.prob_success_pct:.0f}% de probabilidad. Considerá aumentar "
                    "el capital asignado o reducir la meta."
                )
            if gr.goal.horizon_years <= 3 and gr.prob_success_pct < 70:
                self.warnings.append(
                    f"🕐 '{gr.goal.name}' tiene horizonte corto ({gr.goal.horizon_years} años) "
                    "con probabilidad de éxito baja. Para metas de corto plazo, considerá "
                    "instrumentos de menor riesgo."
                )

    @property
    def feasibility_label(self) -> str:
        s = self.plan_feasibility_score
        if s >= 80:
            return "✅ Plan sólido"
        elif s >= 60:
            return "⚠️ Plan viable con ajustes"
        elif s >= 40:
            return "🔶 Plan con riesgos significativos"
        else:
            return "❌ Plan requiere revisión profunda"


# ------------------------------------------------------------------ #
#  GoalPlanner: runs simulations for each goal                        #
# ------------------------------------------------------------------ #

class GoalPlanner:
    """
    Multi-goal Monte Carlo planner.

    Runs an independent simulation per goal. Capital is allocated either
    explicitly (goal.allocated_capital > 0) or proportionally to priority.
    Annual contributions are modeled as negative withdrawals (inflows).
    """

    def __init__(
        self,
        symbols: List[str],
        weights: Optional[np.ndarray] = None,
        seed: int = 42,
    ) -> None:
        self.symbols = symbols
        self.weights = weights
        self.seed = seed

    def run(
        self,
        goals: List[Goal],
        total_capital: float,
        n_sims: int = 10_000,
        vol_scale: float = 1.0,
        return_scale: float = 1.0,
    ) -> GoalPlan:
        """
        Simulate all goals and return a GoalPlan.

        Capital allocation (in order of priority):
          1. Use goal.allocated_capital if explicitly set (> 0).
          2. Auto-allocate: distribute total_capital proportional to
             priority weight (high=3x, medium=2x, low=1x).
        """
        if not goals:
            return GoalPlan(goal_results=[], total_capital=total_capital, n_sims=n_sims)

        allocated = self._allocate_capital(goals, total_capital)

        goal_results: List[GoalResult] = []
        for i, goal in enumerate(goals):
            cap = allocated[i]
            mc_result = self._simulate_goal(goal, cap, n_sims, vol_scale, return_scale)
            goal_results.append(GoalResult(
                goal=goal,
                mc_result=mc_result,
                allocated_capital=cap,
            ))

        plan = GoalPlan(
            goal_results=goal_results,
            total_capital=total_capital,
            n_sims=n_sims,
        )
        plan.compute_aggregates()
        return plan

    # ------------------------------------------------------------------ #
    #  Capital allocation                                                  #
    # ------------------------------------------------------------------ #

    def _allocate_capital(self, goals: List[Goal], total_capital: float) -> List[float]:
        """
        Allocate total_capital across goals.
        Goals with explicit allocated_capital > 0 keep their value.
        Remaining capital split proportionally to priority weight.
        """
        priority_weight = {1: 3, 2: 2, 3: 1}

        explicit_total = sum(g.allocated_capital for g in goals if g.allocated_capital > 0)
        remaining = max(0.0, total_capital - explicit_total)

        auto_goals = [(i, g) for i, g in enumerate(goals) if g.allocated_capital <= 0]
        total_weight = sum(priority_weight.get(g.priority, 2) for _, g in auto_goals)

        allocated: List[float] = []
        for goal in goals:
            if goal.allocated_capital > 0:
                allocated.append(goal.allocated_capital)
            else:
                w = priority_weight.get(goal.priority, 2)
                share = (w / total_weight * remaining) if total_weight > 0 else remaining / len(auto_goals)
                allocated.append(share)

        return allocated

    # ------------------------------------------------------------------ #
    #  Per-goal simulation                                                 #
    # ------------------------------------------------------------------ #

    def _simulate_goal(
        self,
        goal: Goal,
        allocated_capital: float,
        n_sims: int,
        vol_scale: float,
        return_scale: float,
    ) -> MonteCarloResult:
        """Run MonteCarloSimulator for a single goal."""
        sim = MonteCarloSimulator(
            symbols=self.symbols,
            weights=self.weights,
            seed=self.seed,
            vol_scale=vol_scale,
            return_scale=return_scale,
        )
        # annual_contribution is modeled as a negative withdrawal (inflow to portfolio)
        annual_withdrawal = -goal.annual_contribution

        return sim.run(
            horizon_years=goal.horizon_years,
            n_sims=n_sims,
            initial_value=allocated_capital,
            annual_withdrawal=annual_withdrawal,
            target_value=goal.target_nominal,
            withdrawal_growth_rate=0.0,  # contributions are fixed in nominal terms
        )


# ------------------------------------------------------------------ #
#  Helper: required monthly savings to reach a goal                   #
# ------------------------------------------------------------------ #

def required_monthly_savings(
    target_nominal: float,
    initial_capital: float,
    horizon_years: int,
    expected_annual_return: float = 0.07,
) -> float:
    """
    Estimate monthly savings needed to reach target_nominal.

    Uses standard future-value of annuity formula:
        FV = PV*(1+r)^n + PMT * ((1+r)^n - 1) / r
    Solved for PMT (monthly payment).

    Parameters
    ----------
    target_nominal : future goal value (already inflation-adjusted)
    initial_capital : capital already available for this goal
    horizon_years : years to goal
    expected_annual_return : expected portfolio return (default 7%)
    """
    n = horizon_years * 12  # months
    r = (1 + expected_annual_return) ** (1 / 12) - 1  # monthly rate

    fv_pv = initial_capital * (1 + r) ** n
    gap = target_nominal - fv_pv
    if gap <= 0:
        return 0.0

    if r == 0:
        return gap / n

    # PMT = gap * r / ((1+r)^n - 1)
    pmt = gap * r / ((1 + r) ** n - 1)
    return max(0.0, pmt)
