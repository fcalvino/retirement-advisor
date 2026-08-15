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

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

import numpy as np

from config import GOAL_CARD
from portfolio.monte_carlo import MonteCarloResult, MonteCarloSimulator

# ------------------------------------------------------------------ #
#  Enums / constants                                                   #
# ------------------------------------------------------------------ #

PRIORITY_LABELS = {1: "Alta", 2: "Media", 3: "Baja"}
PRIORITY_COLORS = {1: "#DC3545", 2: "#FFC107", 3: "#28A745"}
PRIORITY_EMOJIS = {1: "🔴", 2: "🟡", 3: "🟢"}

GOAL_TYPE_ICONS: Dict[str, str] = {
    "casa":       "🏠",
    "retiro":     "🌴",
    "fire":       "💸",
    "educacion":  "🎓",
    "vehiculo":   "🚗",
    "viaje":      "✈️",
    "emergencia": "🛡️",
    "otro":       "💼",
}

GOAL_TYPE_LABELS: Dict[str, str] = {
    "casa":       "Casa / Propiedad",
    "retiro":     "Retiro",
    "fire":       "FIRE / Independencia Financiera",
    "educacion":  "Educación",
    "vehiculo":   "Vehículo",
    "viaje":      "Viaje / Experiencia",
    "emergencia": "Fondo de emergencia",
    "otro":       "Otro",
}

# Placeholder name suggestion per goal type (shown in form)
GOAL_TYPE_PLACEHOLDERS: Dict[str, str] = {
    "casa":       "ej: Casa en 2028",
    "retiro":     "ej: Retiro a los 65",
    "fire":       "ej: FIRE 2035",
    "educacion":  "ej: Universidad de Luli",
    "vehiculo":   "ej: Auto nuevo 2027",
    "viaje":      "ej: Viaje a Europa 2026",
    "emergencia": "ej: Fondo de emergencia",
    "otro":       "ej: Meta personalizada",
}


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
    goal_type: str = "otro"

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

    @property
    def icon(self) -> str:
        return GOAL_TYPE_ICONS.get(self.goal_type, "💼")

    @property
    def type_label(self) -> str:
        return GOAL_TYPE_LABELS.get(self.goal_type, "Otro")


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

    def make_simulator(
        self,
        vol_scale: float = 1.0,
        return_scale: float = 1.0,
    ) -> MonteCarloSimulator:
        """Build a simulator with this planner's symbols/weights/seed.

        Exposed so callers that need MANY runs with the same assumptions (e.g.
        the savings solver below) can build one instance and reuse it: the
        simulator caches the loaded price history per instance, so reusing it
        avoids re-loading the history on every iteration.
        """
        return MonteCarloSimulator(
            symbols=self.symbols,
            weights=self.weights,
            seed=self.seed,
            vol_scale=vol_scale,
            return_scale=return_scale,
        )

    def _simulate_goal(
        self,
        goal: Goal,
        allocated_capital: float,
        n_sims: int,
        vol_scale: float,
        return_scale: float,
        sim: Optional[MonteCarloSimulator] = None,
    ) -> MonteCarloResult:
        """Run MonteCarloSimulator for a single goal.

        ``sim`` lets a caller inject an already-built simulator to reuse its
        cached price history. When omitted the behavior is unchanged.
        """
        if sim is None:
            sim = self.make_simulator(vol_scale=vol_scale, return_scale=return_scale)
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


def monthly_savings_for_probability(
    planner: "GoalPlanner",
    goal: Goal,
    allocated_capital: float,
    target_prob_pct: float = GOAL_CARD.success_target_pct,
    n_sims: int = GOAL_CARD.advice_n_sims,
    max_iter: int = GOAL_CARD.advice_max_iter,
    vol_scale: float = 1.0,
    return_scale: float = 1.0,
) -> Optional[float]:
    """
    TOTAL monthly contribution that brings this goal to ``target_prob_pct``.

    Why this exists instead of :func:`required_monthly_savings`: that function
    solves a deterministic annuity at the *median* CAGR. A no-volatility
    calculation at the median return lands, by construction, near 50 % success —
    never the 80 % the UI implies. This one bisects on the **same metric the
    card displays** (``prob_achieve_target_pct`` from the Monte Carlo engine),
    so advice and metric stop living in different models.

    Returns ``None`` when no contribution reaches the target within the
    explored range — saying "more saving alone won't do it" is more honest than
    handing back a reassuring number.

    Notes
    -----
    - The returned figure is the **total** monthly contribution. Callers that
      want the *additional* amount must subtract ``goal.annual_contribution/12``.
    - One simulator is built and reused across all iterations (cached price
      history), so the ~12–18 runs cost well under two seconds at
      ``GOAL_CARD.advice_n_sims``.
    """
    if goal.horizon_years <= 0 or target_prob_pct <= 0:
        return None

    sim = planner.make_simulator(vol_scale=vol_scale, return_scale=return_scale)

    def _prob(monthly: float) -> float:
        g = replace(goal, annual_contribution=max(0.0, monthly) * 12.0)
        return planner._simulate_goal(
            g, allocated_capital, n_sims, vol_scale, return_scale, sim=sim
        ).prob_achieve_target_pct

    # Already there without extra saving? Nothing to advise.
    if _prob(0.0) >= target_prob_pct:
        return 0.0

    # Seed the bracket with the deterministic annuity: it is the wrong model for
    # a probability promise, but it is a decent order-of-magnitude first guess.
    seed = required_monthly_savings(
        target_nominal=goal.target_nominal,
        initial_capital=allocated_capital,
        horizon_years=goal.horizon_years,
        expected_annual_return=0.07,
    )
    hi = max(seed, goal.target_nominal / (goal.horizon_years * 12), 100.0)

    for _ in range(6):                       # expand until the target is cleared
        if _prob(hi) >= target_prob_pct:
            break
        hi *= 2
    else:
        return None                          # unreachable with saving alone

    lo = 0.0
    for _ in range(max_iter):                # bisection
        mid = (lo + hi) / 2
        if _prob(mid) >= target_prob_pct:
            hi = mid
        else:
            lo = mid

    return hi


# ------------------------------------------------------------------ #
#  SORR badge: risk level + its tooltip, from a single source          #
# ------------------------------------------------------------------ #

def sorr_risk_badge(sorr_pct: float, dd_pct: float) -> tuple:
    """
    (badge_label, hex_color) for the SORR traffic light.

    The severe case is evaluated FIRST and with an OR: either axis on its own is
    enough to call the risk high. The previous implementation tested
    ``elif sorr < 50 or dd < 45`` in the middle branch, which by De Morgan
    required BOTH to be breached to ever reach "Alto" — so a median drawdown of
    90 % was labelled 🟡 Medio. See :func:`sorr_badge_tooltip`, which states the
    same rule to the user from the same thresholds.
    """
    if sorr_pct >= GOAL_CARD.high_sorr_pct or dd_pct >= GOAL_CARD.high_dd_pct:
        return "🔴 Alto", "#DC3545"
    if sorr_pct < GOAL_CARD.low_sorr_pct and dd_pct < GOAL_CARD.low_dd_pct:
        return "🟢 Bajo", "#28A745"
    return "🟡 Medio", "#FFC107"


def sorr_badge_tooltip(is_accumulation: bool = True) -> str:
    """
    Help text for the SORR badge, generated from the SAME thresholds as
    :func:`sorr_risk_badge` so the two cannot drift apart again.

    ``is_accumulation`` picks the right consequence: a goal that only receives
    contributions (``annual_contribution > 0`` ⇒ the engine models a negative
    withdrawal) has no withdrawals to collide with, so the damage there is
    buying expensive right before the fall — not selling into it.
    """
    consequence = (
        "En una meta de acumulación el daño es aportar caro justo antes de la "
        "caída: el capital que entra arriba tarda años en recuperarse."
        if is_accumulation else
        "Si la mala secuencia coincide con retiros, el daño se multiplica: "
        "vender abajo consume unidades que ya no vuelven a componer."
    )
    return (
        "Sequence of Returns Risk: riesgo de que una mala secuencia de retornos "
        "al inicio del horizonte destruya el plan aunque el CAGR promedio sea "
        f"positivo. {consequence}\n\n"
        f"🟢 Bajo (<{GOAL_CARD.low_sorr_pct:.0f}% SORR y <{GOAL_CARD.low_dd_pct:.0f}% drawdown) · "
        f"🟡 Medio · "
        f"🔴 Alto (≥{GOAL_CARD.high_sorr_pct:.0f}% SORR o ≥{GOAL_CARD.high_dd_pct:.0f}% drawdown)."
    )
