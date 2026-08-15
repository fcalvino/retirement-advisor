"""Tests for the "🎯 Resultados por meta" card logic (7_Simulaciones).

These cover the defects found in the 2026-08 audit of that card. The logic under
test deliberately lives in ``portfolio/goals.py`` rather than inside the page, so
it can be asserted without importing Streamlit.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from config import ALERTS, GOAL_CARD
from portfolio.goals import (
    Goal,
    monthly_savings_for_probability,
    sorr_badge_tooltip,
    sorr_risk_badge,
)

PAGE = Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "7_Simulaciones.py"


# ------------------------------------------------------------------ #
#  Case 03 — the badge must implement the rule its tooltip promises    #
# ------------------------------------------------------------------ #

def _rule_from_tooltip(sorr_pct: float, dd_pct: float) -> str:
    """The rule as the tooltip states it, parsed from the tooltip itself.

    Reading the thresholds back out of the user-facing text is the point: if
    someone edits the wording and the numbers drift from the code, this breaks.
    """
    text = sorr_badge_tooltip()
    low = re.search(r"🟢 Bajo \(<([\d.]+)% SORR y <([\d.]+)% drawdown\)", text)
    high = re.search(r"🔴 Alto \(≥([\d.]+)% SORR o ≥([\d.]+)% drawdown\)", text)
    assert low and high, f"tooltip no longer states the rule machine-readably:\n{text}"

    low_sorr, low_dd = float(low.group(1)), float(low.group(2))
    high_sorr, high_dd = float(high.group(1)), float(high.group(2))

    if sorr_pct >= high_sorr or dd_pct >= high_dd:
        return "🔴 Alto"
    if sorr_pct < low_sorr and dd_pct < low_dd:
        return "🟢 Bajo"
    return "🟡 Medio"


class TestSorrBadgeContract:
    @pytest.mark.parametrize("sorr,dd", [
        (0, 0), (10, 90), (20, 25), (24.9, 29.9), (25, 30), (29, 44),
        (30, 0), (35, 20), (44, 44), (45, 45), (51.7, 48), (55, 44),
        (60, 20), (80, 10), (100, 100),
    ])
    def test_badge_matches_its_own_tooltip(self, sorr, dd):
        assert sorr_risk_badge(sorr, dd)[0] == _rule_from_tooltip(sorr, dd)

    @pytest.mark.parametrize("sorr,dd", [(60, 20), (10, 90), (80, 10), (55, 44)])
    def test_either_axis_alone_is_enough_for_high(self, sorr, dd):
        """These all returned 🟡 Medio before the fix: the middle branch was
        ``elif sorr < 50 or dd < 45``, which by De Morgan required BOTH axes to
        be breached to ever reach 🔴 Alto. A 90% median drawdown read as Medio."""
        assert sorr_risk_badge(sorr, dd)[0] == "🔴 Alto"

    def test_low_needs_both_axes_calm(self):
        assert sorr_risk_badge(20, 25)[0] == "🟢 Bajo"
        assert sorr_risk_badge(20, 35)[0] == "🟡 Medio"
        assert sorr_risk_badge(27, 25)[0] == "🟡 Medio"

    def test_badge_returns_a_hex_colour(self):
        for sorr, dd in [(0, 0), (27, 35), (99, 99)]:
            _, colour = sorr_risk_badge(sorr, dd)
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", colour)


class TestDashboardAgreesWithAlerts:
    def test_high_sorr_threshold_matches_the_alert_engine(self):
        """Otherwise a plan at 35% SORR fires a SORR_HIGH email while the
        dashboard paints it yellow."""
        assert GOAL_CARD.high_sorr_pct == ALERTS.sorr_high_threshold_pct

    def test_a_plan_that_alerts_is_shown_as_high_risk(self):
        just_over = ALERTS.sorr_high_threshold_pct + 0.1
        assert sorr_risk_badge(just_over, 0.0)[0] == "🔴 Alto"


class TestTooltipWording:
    def test_accumulation_goal_is_not_told_about_withdrawals(self):
        """An accumulation goal has annual_withdrawal = -contribution ≤ 0, so
        there are no withdrawals for a bad sequence to collide with."""
        text = sorr_badge_tooltip(is_accumulation=True)
        assert "retiro" not in text.lower()
        assert "aportar caro" in text.lower()

    def test_decumulation_goal_is_told_about_withdrawals(self):
        assert "retiro" in sorr_badge_tooltip(is_accumulation=False).lower()

    def test_tooltip_thresholds_come_from_config(self):
        text = sorr_badge_tooltip()
        assert f"{GOAL_CARD.high_sorr_pct:.0f}%" in text
        assert f"{GOAL_CARD.low_dd_pct:.0f}%" in text


# ------------------------------------------------------------------ #
#  Case 04 — savings advice solved against the metric it promises      #
# ------------------------------------------------------------------ #

class _StubResult:
    def __init__(self, prob):
        self.prob_achieve_target_pct = prob


class _StubPlanner:
    """Planner whose probability is a deterministic function of the contribution.

    Keeps the solver's search behavior under test without spending Monte Carlo
    time. ``threshold`` is the monthly contribution at which the goal reaches
    ``prob_at_threshold``.
    """

    def __init__(self, threshold=500.0, ceiling=100.0):
        self.threshold = threshold
        self.ceiling = ceiling
        self.calls = []

    def make_simulator(self, vol_scale=1.0, return_scale=1.0):
        return object()

    def _simulate_goal(self, goal, capital, n_sims, vol_scale, return_scale, sim=None):
        monthly = goal.annual_contribution / 12.0
        self.calls.append(monthly)
        prob = min(self.ceiling, 100.0 * monthly / (2 * self.threshold))
        return _StubResult(prob)


def _goal(**kw):
    base = dict(name="Casa", target_amount_today=150_000, horizon_years=24,
                expected_inflation=3.0, annual_contribution=0.0)
    base.update(kw)
    return Goal(**base)


class TestSavingsSolver:
    def test_returns_a_contribution_that_actually_reaches_the_target(self):
        planner = _StubPlanner(threshold=500.0)
        got = monthly_savings_for_probability(planner, _goal(), 1_000.0, target_prob_pct=80.0)

        assert got is not None
        reached = planner._simulate_goal(
            replace(_goal(), annual_contribution=got * 12), 1_000.0, 10, 1.0, 1.0
        ).prob_achieve_target_pct
        assert reached >= 80.0

    def test_a_smaller_contribution_does_not_reach_it(self):
        planner = _StubPlanner(threshold=500.0)
        got = monthly_savings_for_probability(planner, _goal(), 1_000.0, target_prob_pct=80.0)

        short = planner._simulate_goal(
            replace(_goal(), annual_contribution=got * 0.8 * 12), 1_000.0, 10, 1.0, 1.0
        ).prob_achieve_target_pct
        assert short < 80.0

    def test_returns_none_when_saving_alone_cannot_get_there(self):
        """More honest than handing back a reassuring number."""
        planner = _StubPlanner(ceiling=45.0)   # never exceeds 45%
        assert monthly_savings_for_probability(
            planner, _goal(), 1_000.0, target_prob_pct=80.0
        ) is None

    def test_returns_zero_when_already_at_target(self):
        planner = _StubPlanner(ceiling=99.0)
        planner._simulate_goal = lambda *a, **k: _StubResult(95.0)
        assert monthly_savings_for_probability(
            planner, _goal(), 1_000.0, target_prob_pct=80.0
        ) == 0.0

    def test_probability_is_monotonic_in_the_contribution(self):
        planner = _StubPlanner(threshold=500.0)
        probs = [
            planner._simulate_goal(
                replace(_goal(), annual_contribution=m * 12), 1_000.0, 10, 1.0, 1.0
            ).prob_achieve_target_pct
            for m in (0, 100, 400, 900)
        ]
        assert probs == sorted(probs)

    def test_degenerate_goals_are_refused(self):
        planner = _StubPlanner()
        assert monthly_savings_for_probability(
            planner, _goal(horizon_years=0), 1_000.0
        ) is None

    def test_defaults_come_from_config(self):
        planner = _StubPlanner(threshold=500.0)
        monthly_savings_for_probability(planner, _goal(), 1_000.0)
        # the solver must have aimed at the configured target, not a literal 80
        assert GOAL_CARD.success_target_pct == 80.0


# ------------------------------------------------------------------ #
#  Cases 06/07 — the card's own source                                 #
# ------------------------------------------------------------------ #

class TestCardSource:
    """Assertions over the page source. Streamlit UI is not unit-testable here,
    but these defects are textual and would otherwise silently come back."""

    @pytest.fixture(scope="class")
    def src(self):
        return PAGE.read_text()

    def test_year_of_max_dd_is_formatted_in_exactly_one_place(self, src):
        """It used to be rendered as ':.0f' in the badge and ':.1f' twice more,
        so "año típico: 14" sat next to "típ. en año 13.6"."""
        assert src.count("median_year_of_max_dd") == 0, (
            "the card should present the P25–P75 band, not the point estimate"
        )

    def test_no_markdown_mixes_unsafe_html_with_help(self, src):
        """Streamlit appends the literal ' :help[]' to the markdown; inside a
        raw HTML block CommonMark swallows it and it prints verbatim."""
        import ast
        tree = ast.parse(src)
        offenders = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "markdown"
            and {k.arg for k in node.keywords} >= {"unsafe_allow_html", "help"}
        ]
        assert not offenders, f"unsafe_allow_html + help on lines {offenders}"

    def test_text_deltas_disable_the_arrow(self, src):
        """A delta used as a subtitle must not render as a ▲/▼ change."""
        import ast
        tree = ast.parse(src)
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "metric"):
                continue
            kwargs = {k.arg for k in node.keywords if k.arg}
            delta = next((k.value for k in node.keywords if k.arg == "delta"), None)
            if delta is None or "delta_arrow" in kwargs:
                continue
            # A plain f-string / attribute / literal delta is a subtitle, not a
            # signed change. IfExp deltas in this page are genuine "+X vs base".
            if isinstance(delta, (ast.JoinedStr, ast.Attribute, ast.Name)) or (
                isinstance(delta, ast.Constant) and isinstance(delta.value, str)
            ):
                offenders.append(node.lineno)
        assert not offenders, f"text delta without delta_arrow='off' on lines {offenders}"

    def test_success_threshold_is_not_hardcoded(self, src):
        assert "GOAL_CARD.success_target_pct" in src
        assert "prob_success_pct < 80" not in src

    def test_chart_labels_the_log_axis(self, src):
        """Switching to log without saying so would misrepresent the slope."""
        if 'type="log"' in src:
            assert "escala logarítmica" in src
