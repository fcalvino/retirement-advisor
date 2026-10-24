"""Oráculo GOAL-MANUAL-CAPITAL: el capital fijado a mano en una meta no desaparece.

`GoalPlanner._allocate_capital` respeta el «Capital asignado» de una meta (> 0) y
reparte lo que sobra del total del plan entre las metas en auto, con piso en 0.
Si lo fijado a mano supera el total, el total deja de mandar y nada lo decía: con
una meta de 14.030 y un total de 1.000 el resumen mostraba «Capital total
asignado $14.030» junto a un campo que decía 1000.

La referencia es la definición: «manual» es `allocated_capital > 0` de la meta, y
el aviso corresponde cuando la suma de lo manual supera `total_capital`.
"""

from __future__ import annotations

import pytest

from portfolio.goals import Goal, GoalPlan, GoalPlanner, GoalResult
from portfolio.monte_carlo import MonteCarloResult


def _goal(name: str, allocated: float = 0.0, priority: int = 1) -> Goal:
    return Goal(name=name, target_amount_today=100_000.0, horizon_years=10,
                priority=priority, allocated_capital=allocated)


def _plan(goals: list[Goal], total: float) -> GoalPlan:
    caps = GoalPlanner.__new__(GoalPlanner)._allocate_capital(goals, total)
    mc = MonteCarloResult(n_sims=10, horizon_years=10, initial_value=0.0,
                          annual_withdrawal=0.0, target_value=0.0)
    results = [GoalResult(goal=g, mc_result=mc, allocated_capital=c)
               for g, c in zip(goals, caps)]
    return GoalPlan(goal_results=results, total_capital=total, n_sims=10)


def test_a_goal_with_capital_set_is_manual_and_one_at_zero_is_auto():
    plan = _plan([_goal("Casa", 14_030), _goal("Retiro", 0)], total=500_000)
    manual = {gr.goal.name: gr.capital_is_manual for gr in plan.goal_results}
    assert manual == {"Casa": True, "Retiro": False}


def test_the_manual_sum_counts_only_manual_goals():
    plan = _plan([_goal("Casa", 14_030), _goal("Retiro", 0)], total=500_000)
    assert plan.manual_capital_total == 14_030


def test_manual_above_the_plan_total_is_flagged():
    """El caso de la QA: 14.030 a mano contra un total de 1.000."""
    plan = _plan([_goal("FIRE 2050", 14_030)], total=1_000)
    assert plan.goal_results[0].allocated_capital == 14_030
    assert plan.manual_capital_exceeds_total is True


def test_auto_goals_get_nothing_when_manual_eats_the_total():
    """Lo que el aviso dice de las metas en auto es lo que hace el reparto."""
    plan = _plan([_goal("Casa", 14_030), _goal("Retiro", 0)], total=1_000)
    assert plan.manual_capital_exceeds_total is True
    auto = [gr for gr in plan.goal_results if not gr.capital_is_manual]
    assert [gr.allocated_capital for gr in auto] == [0.0]


def test_manual_equal_to_the_total_is_flagged_only_when_auto_goals_are_left_at_zero():
    """Con una meta en auto, manual == total la deja en 0 sin avisar; sin ella, no hay nada que avisar."""
    with_auto = _plan([_goal("Casa", 14_030), _goal("Retiro", 0)], total=14_030)
    assert [gr.allocated_capital for gr in with_auto.goal_results if not gr.capital_is_manual] == [0.0]
    assert with_auto.manual_capital_exceeds_total is True
    assert _plan([_goal("Casa", 14_030)], total=14_030).manual_capital_exceeds_total is False


@pytest.mark.parametrize("manual, total", [(14_030, 14_030), (10_000, 500_000), (0, 1_000)])
def test_control_manual_within_the_total_is_not_flagged(manual, total):
    plan = _plan([_goal("Casa", manual)], total=total)
    assert plan.manual_capital_exceeds_total is False
