"""The age-based allocation reads the investor's profile (backlog U5-7).

``recommended_bond_pct`` promised, in its own docstring, two rules:

    "Conservative: bond % = age. Aggressive: bond % = age - 10."

and returned ``min(age, 80)`` to everyone. The backlog filed that as hygiene —
"no mueve un número hoy". It moved two numbers on two screens.

**The bond rule.** ``AllocationAdvisor.advise()`` took no profile, so an
aggressive investor was shown the conservative glide path: a flat **10 pp less
equity at every age** (at 60, 40 % instead of 50 %), dragging the equity
sub-allocation with it because US/international/REIT are percentages of
``equity_pct``.

**The concentration limits.** The same function graded concentration against
the *global* ``STRATEGY`` caps (8 / 25 / 10) while the optimizer graded against
the *profile's* (18 / 30 / 5 for aggressive). An aggressive investor holding
15 % of one name read "⚠️ reducir a menos de 8 %" on Allocation while the
Optimizer that built the position caps it at 18 %. Two screens, one portfolio,
contradictory advice. The conservative investor got the mirror image: warned at
the global 25 % sector cap when their own profile says 20 %.

The profile was never missing. The onboarding asks for risk tolerance and
``data/preferences.py`` persists it as ``default_profile``, commented "Risk
tolerance is the single source of truth for the optimizer profile". Both call
sites already held it and dropped it on the floor.

**Why these tests are differential.** ``test_config_single_home_oracle`` states
the trap: asserting the literal "pins the fix's shape, not its meaning — a fix
that moved the number into config and then ignored it would pass". So the
anchor test here moves ``bond_age_offset_pp`` and requires the allocation to
move with it. Asserting `bonds_pct == 45.0` would survive a knob wired to
nothing.

No network, no Streamlit.
"""

from __future__ import annotations

import dataclasses

import pytest

from config import (
    AGGRESSIVE_PROFILE,
    CONSERVATIVE_PROFILE,
    MODERATE_PROFILE,
    OPTIMIZER_PROFILES,
    recommended_bond_pct,
)
from portfolio.allocation import AllocationAdvisor

AGES = (30, 45, 60, 70)


def _advise(age: int, profile=None, **kw):
    return AllocationAdvisor().advise(age, max(age + 1, 65), profile=profile, **kw)


# --------------------------------------------------------------------------- #
#  1. The knob is connected — the test that fails if it is ever unwired again  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("age", AGES)
@pytest.mark.parametrize("delta", (-15.0, -3.0, 4.0))
def test_moving_the_offset_moves_the_allocation_by_the_same_amount(age, delta):
    """The defect was a documented knob that nothing read. Move it, or fail."""
    base = CONSERVATIVE_PROFILE
    tilted = dataclasses.replace(
        base, bond_age_offset_pp=base.bond_age_offset_pp + delta
    )

    before = _advise(age, base)
    after = _advise(age, tilted)

    assert after.bonds_pct - before.bonds_pct == pytest.approx(delta)
    assert after.equity_pct - before.equity_pct == pytest.approx(-delta)


def test_the_offset_is_not_hardcoded_in_the_advisor():
    """Same guard one level down: the rule itself has to read the profile."""
    tilted = dataclasses.replace(CONSERVATIVE_PROFILE, bond_age_offset_pp=-22.0)
    assert recommended_bond_pct(50, tilted) == pytest.approx(28.0)


# --------------------------------------------------------------------------- #
#  2. The promise the docstring made                                          #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("age", AGES)
def test_aggressive_holds_ten_points_more_equity_than_conservative(age):
    """The rule the docstring promised and the code never implemented."""
    cons = _advise(age, CONSERVATIVE_PROFILE)
    aggr = _advise(age, AGGRESSIVE_PROFILE)

    assert cons.bonds_pct - aggr.bonds_pct == pytest.approx(10.0)
    assert aggr.equity_pct - cons.equity_pct == pytest.approx(10.0)


@pytest.mark.parametrize("age", AGES)
def test_moderate_sits_strictly_between_the_two(age):
    """The docstring named two rules for a three-profile product. Moderate is
    the midpoint — monotone with ``risk_aversion`` (4.0 / 2.5 / 1.5)."""
    cons = _advise(age, CONSERVATIVE_PROFILE).equity_pct
    mod = _advise(age, MODERATE_PROFILE).equity_pct
    aggr = _advise(age, AGGRESSIVE_PROFILE).equity_pct

    assert cons < mod < aggr


def test_the_equity_sub_allocation_follows_the_profile():
    """US/international/REIT are shares of equity_pct, so they move too —
    this is the part the row did not mention."""
    cons = _advise(45, CONSERVATIVE_PROFILE)
    aggr = _advise(45, AGGRESSIVE_PROFILE)

    assert aggr.us_large_cap_pct > cons.us_large_cap_pct
    assert aggr.international_pct > cons.international_pct


# --------------------------------------------------------------------------- #
#  3. Allocation may not contradict the Optimizer                             #
# --------------------------------------------------------------------------- #

def _padded(weights: dict) -> dict:
    """Fill out to 10 names so the diversification floor never fires — these
    tests are about the *position* cap, and the floor is exercised separately."""
    held = dict(weights)
    for i in range(10 - len(held)):
        held[f"PAD{i}"] = 1.0
    return held


@pytest.mark.parametrize("key", sorted(OPTIMIZER_PROFILES))
def test_the_position_warning_fires_at_the_profiles_own_cap(key):
    """The screen that warns and the screen that builds must use one number."""
    profile = OPTIMIZER_PROFILES[key]
    cap = profile.max_position_pct

    under = _advise(45, profile, current_position_weights=_padded({"AAPL": cap - 0.5}))
    over = _advise(45, profile, current_position_weights=_padded({"AAPL": cap + 0.5}))

    assert not any("AAPL" in w for w in under.concentration_warnings)
    assert any("AAPL" in w for w in over.concentration_warnings)


def test_a_position_the_aggressive_optimizer_built_is_not_flagged_by_allocation():
    """The concrete contradiction: 15 % of one name is inside the aggressive
    cap (18 %) and outside the conservative one (8 %)."""
    held = _padded({"NVDA": 15.0})

    aggr = _advise(45, AGGRESSIVE_PROFILE, current_position_weights=held)
    cons = _advise(45, CONSERVATIVE_PROFILE, current_position_weights=held)

    assert not any("NVDA" in w for w in aggr.concentration_warnings)
    assert any("NVDA" in w for w in cons.concentration_warnings)


def test_the_sector_warning_fires_at_the_profiles_own_cap():
    """22 % in one sector: over the conservative cap (20), under moderate (25)."""
    held = {"Technology": 22.0}

    cons = _advise(45, CONSERVATIVE_PROFILE, current_sector_weights=held)
    mod = _advise(45, MODERATE_PROFILE, current_sector_weights=held)

    assert any("Technology" in w for w in cons.concentration_warnings)
    assert not mod.concentration_warnings


@pytest.mark.parametrize("key", sorted(OPTIMIZER_PROFILES))
def test_the_diversification_floor_is_the_profiles_own(key):
    profile = OPTIMIZER_PROFILES[key]
    held = {f"T{i}": 1.0 for i in range(profile.min_positions - 1)}

    advice = _advise(45, profile, current_position_weights=held)

    assert any("diversificar" in w for w in advice.concentration_warnings)


# --------------------------------------------------------------------------- #
#  4. Invariants and backward compatibility                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("key", sorted(OPTIMIZER_PROFILES))
@pytest.mark.parametrize("age", range(20, 81))
def test_the_three_sleeves_always_sum_to_a_hundred(key, age):
    advice = _advise(age, OPTIMIZER_PROFILES[key])

    assert advice.bonds_pct >= 0.0
    assert advice.equity_pct >= 0.0
    assert advice.bonds_pct + advice.equity_pct + advice.cash_pct == pytest.approx(100.0)


@pytest.mark.parametrize("age", AGES)
def test_no_profile_is_the_conservative_rule(age):
    """Every existing caller keeps the behaviour it had before this change."""
    default = _advise(age)
    cons = _advise(age, CONSERVATIVE_PROFILE)

    assert default.bonds_pct == cons.bonds_pct
    assert default.equity_pct == cons.equity_pct


def test_the_cap_applies_after_the_offset_not_before():
    """At 90 the two readings of ``min(age, 80) - 10`` diverge: 70 if the cap
    lands first, 80 if the offset does. The slider tops out at 80 so this is
    dormant today — pinned so the next reader does not have to guess."""
    assert recommended_bond_pct(90, CONSERVATIVE_PROFILE) == pytest.approx(80.0)
    assert recommended_bond_pct(90, AGGRESSIVE_PROFILE) == pytest.approx(80.0)


def test_the_bond_rule_never_goes_negative():
    """A 20-year-old aggressive investor is at age - 10 = 10, not below zero."""
    assert recommended_bond_pct(20, AGGRESSIVE_PROFILE) == pytest.approx(10.0)
    assert recommended_bond_pct(5, AGGRESSIVE_PROFILE) == pytest.approx(0.0)


def test_the_advice_names_the_profile_it_used():
    """The screen has to be able to say which profile produced the numbers."""
    assert _advise(45, AGGRESSIVE_PROFILE).profile_name == AGGRESSIVE_PROFILE.name
    assert _advise(45).profile_name == CONSERVATIVE_PROFILE.name
