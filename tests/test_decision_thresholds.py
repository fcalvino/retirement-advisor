"""The score→signal ladder is coherent and lives entirely in config.

No oracle here, and deliberately so: there is no financial mathematics to verify
against a definition — where to draw STRONG BUY *is* a product decision. What can
be pinned down is that the ladder is internally consistent, that every rung comes
from ``StrategyConfig``, and that its badge cannot contradict its own verdict.

Background (2026-08-22): the thresholds were re-anchored from 75/60/45 to 82/68/55.
They had been calibrated for ``total_score`` but, since
``use_adjusted_score_for_decision`` defaults to True, they were being applied to
``adjusted_score`` — which carries consistency, Piotroski, moat and tailwind on top,
+20.3 points on average over the 149 cached equities. The marks never moved; the
ruler beneath them grew, so 33% of an already-curated universe came out STRONG BUY
and only 3 of 149 names fell below HOLD.

Two rungs were not in config at all and would have drifted silently:
``decide()`` carried a bare ``35`` for the REDUCE/SELL boundary, and
``Decision.score_badge`` repeated 75/60/45 to pick its emoji.
"""

from __future__ import annotations

import inspect
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import analysis.strategy as strategy_module
from analysis.strategy import Decision, RetirementStrategy
from config import STRATEGY

# --------------------------------------------------------------------------- #
#  Fixtures — the ladder in isolation                                         #
# --------------------------------------------------------------------------- #

def _fund(score: float):
    """Fundamental stand-in that clears every gate except the score ladder."""
    return SimpleNamespace(
        symbol="TEST",
        total_score=score,
        adjusted_score=score,
        is_crypto=False,
        debt_equity=0.5,
        pb_ratio=2.0,
        negative_equity=False,
        margin_of_safety_pct=25.0,
        graham_value=100.0,
        is_value_stock=lambda: True,
        roe=20.0,
        revenue_cagr_5y=10.0,
        eps_cagr_5y=10.0,
        fcf_yield=4.0,
        payout_ratio=40.0,
        warnings=[],
        notes={},
        data_quality={"level": "good", "missing_fields": []},
        tailwind_classification="Neutral",
        tailwind_detail=None,
    )


def _tech():
    return SimpleNamespace(
        symbol="TEST",
        signal="BULLISH",
        signal_strength=60,
        above_sma200=True,
        golden_cross=False,
        rsi_weekly=55.0,
        sma200_slope_pct=5.0,
        price_vs_52w_high_pct=-5.0,
        price_vs_52w_low_pct=30.0,
        warnings=[],
    )


def _action_for(score: float) -> str:
    return RetirementStrategy().decide(_fund(score), _tech()).action


# --------------------------------------------------------------------------- #
#  The ladder itself                                                          #
# --------------------------------------------------------------------------- #

class TestLadderBoundaries:
    """Just above and just below each rung, with all other gates satisfied."""

    @pytest.mark.parametrize("rung,above,below", [
        ("strong_buy_score", "STRONG BUY", "BUY"),
        ("buy_score", "BUY", "HOLD"),
        ("hold_score", "HOLD", "REDUCE"),
        ("reduce_score", "REDUCE", "SELL"),
    ])
    def test_each_rung_separates_two_actions(self, rung, above, below):
        threshold = getattr(STRATEGY, rung)
        assert _action_for(threshold + 0.1) == above
        assert _action_for(threshold - 0.1) == below

    def test_the_threshold_value_itself_is_inclusive(self):
        """`>=` everywhere: landing exactly on a rung earns it."""
        assert _action_for(STRATEGY.strong_buy_score) == "STRONG BUY"
        assert _action_for(STRATEGY.buy_score) == "BUY"
        assert _action_for(STRATEGY.hold_score) == "HOLD"
        assert _action_for(STRATEGY.reduce_score) == "REDUCE"

    def test_the_ladder_is_ordered(self):
        assert (STRATEGY.reduce_score
                < STRATEGY.hold_score
                < STRATEGY.buy_score
                < STRATEGY.strong_buy_score)

    def test_action_never_improves_as_the_score_falls(self):
        rank = {"SELL": 0, "REDUCE": 1, "HOLD": 2, "BUY": 3, "STRONG BUY": 4}
        scores = [float(s) for s in range(0, 101, 2)]
        ranks = [rank[_action_for(s)] for s in scores]
        assert ranks == sorted(ranks), "la escalera debe ser monótona en el score"


# --------------------------------------------------------------------------- #
#  Every rung comes from config                                               #
# --------------------------------------------------------------------------- #

class TestLadderIsConfigDriven:
    def test_moving_strong_buy_moves_the_frontier(self):
        score = STRATEGY.strong_buy_score + 3
        assert _action_for(score) == "STRONG BUY"
        with patch.object(STRATEGY, "strong_buy_score", score + 10):
            assert _action_for(score) == "BUY"

    def test_moving_buy_moves_the_frontier(self):
        score = STRATEGY.buy_score + 3
        assert _action_for(score) == "BUY"
        with patch.object(STRATEGY, "buy_score", score + 10):
            assert _action_for(score) == "HOLD"

    def test_moving_reduce_moves_the_frontier(self):
        """This is the test that fails if the bare `35` ever comes back."""
        score = STRATEGY.reduce_score + 3
        assert _action_for(score) == "REDUCE"
        with patch.object(STRATEGY, "reduce_score", score + 5):
            assert _action_for(score) == "SELL"

    def test_reduce_score_exists_with_the_agreed_value(self):
        assert STRATEGY.reduce_score == 45.0

    def test_the_agreed_ladder(self):
        assert (STRATEGY.strong_buy_score, STRATEGY.buy_score, STRATEGY.hold_score) \
            == (82.0, 68.0, 55.0)


def test_no_bare_thresholds_left_in_the_decision_path():
    """Guard: the old literals must not reappear in decide() or score_badge.

    Same shape as the window guard in tests/test_cagr_window.py — a rung written
    as a literal is one that stops following config the moment someone tunes it.
    """
    for func in (RetirementStrategy.decide, Decision.score_badge.fget):
        source = inspect.getsource(func)
        # Comparisons of the shape `score >= 75` / `s >= 45`, not incidental numbers.
        offenders = re.findall(r"[<>]=?\s*(?:75|60|45|35)(?!\d)", source)
        assert not offenders, (
            f"{func.__qualname__} compara contra literales {offenders} — "
            "esos umbrales tienen que salir de StrategyConfig"
        )


# --------------------------------------------------------------------------- #
#  Badge and verdict must agree                                               #
# --------------------------------------------------------------------------- #

class TestBadgeMatchesVerdict:
    @pytest.mark.parametrize("score", [float(s) for s in range(0, 101, 5)])
    def test_excellent_badge_only_where_the_engine_says_strong_buy(self, score):
        decision = Decision(symbol="TEST", fundamental_score=score)
        if decision.score_badge == "⭐ Excellent":
            assert score >= STRATEGY.strong_buy_score

    @pytest.mark.parametrize("badge,rung", [
        ("⭐ Excellent", "strong_buy_score"),
        ("✅ Good", "buy_score"),
        ("🟡 Fair", "hold_score"),
    ])
    def test_each_badge_starts_at_its_rung(self, badge, rung):
        threshold = getattr(STRATEGY, rung)
        assert Decision(symbol="T", fundamental_score=threshold).score_badge == badge
        assert Decision(symbol="T", fundamental_score=threshold - 0.1).score_badge != badge

    def test_badge_follows_a_retuned_ladder(self):
        score = STRATEGY.strong_buy_score + 1
        assert Decision(symbol="T", fundamental_score=score).score_badge == "⭐ Excellent"
        with patch.object(STRATEGY, "strong_buy_score", score + 10):
            assert Decision(symbol="T", fundamental_score=score).score_badge == "✅ Good"

    def test_weak_badge_below_the_bottom_rung(self):
        below = STRATEGY.hold_score - 1
        assert Decision(symbol="T", fundamental_score=below).score_badge == "⚠️ Weak"


# --------------------------------------------------------------------------- #
#  The prompt the LLM reads quotes the live ladder                            #
# --------------------------------------------------------------------------- #

def test_the_llm_prompt_states_the_current_thresholds():
    """analysis/prompts.py interpolates STRATEGY — verify it, don't assume it."""
    source = inspect.getsource(strategy_module)
    assert "CFG.reduce_score" in source

    from analysis.prompts import _hard_decision_constraints_block

    block = _hard_decision_constraints_block(_fund(70.0), _tech())
    assert f"STRONG≥{STRATEGY.strong_buy_score:.0f}" in block
    assert f"BUY≥{STRATEGY.buy_score:.0f}" in block
    assert f"HOLD≥{STRATEGY.hold_score:.0f}" in block
