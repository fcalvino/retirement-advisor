"""LLM-1 oracle: the committee's logged action never exceeds the engine's.

Contract (``config.py``, SIGNAL-1): «El LLM puede ser más prudente que la
escalera, nunca menos». The single-call AI path enforces it through
``apply_safety_overlay``; the committee's ``to_decision`` — what the Comité page
writes to the track record as ``source=committee`` — must too. The oracle is
``RetirementStrategy().decide()`` on the same (fund, tech): independent of the
committee, and the raw vote (``verdict.action``) stays untouched for display.

A fake ``call_fn`` makes every agent vote BUY/HIGH, so the panel is as
optimistic as it can be; no network.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from analysis.committee import CommitteeAnalyzer
from analysis.eval_cases import golden_cases
from analysis.strategy import RetirementStrategy, _rank
from config import STRATEGY
from tests.test_committee import _agent_json, _fundamental_json, make_fake


def _base():
    case = golden_cases()[0]  # quality_compounder_buy: engine and panel agree on BUY
    return case.fund, case.tech


def _all_buy():
    return make_fake(
        fundamental=_fundamental_json("BUY", "HIGH"),
        macro=_agent_json("BUY", "HIGH"),
        devil=_agent_json("BUY", "HIGH"),
        pm=_agent_json("BUY", "HIGH"),
        coach=_agent_json("BUY", "HIGH"),
        dividend=_agent_json("BUY", "HIGH"),
    )


def _high_leverage(f, t):
    return replace(f, debt_equity=STRATEGY.max_debt_equity + 1.0), t


def _negative_equity(f, t):
    return replace(f, negative_equity=True), t


def _poor_data(f, t):
    return replace(f, data_quality={**(f.data_quality or {}), "level": "poor"}), t


def _no_uptrend(f, t):
    # ADBE 15-16/09 (ids 1022, 1179): measured, not missing — no uptrend.
    return f, replace(t, signal="NEUTRAL", above_sma200=False)


@pytest.mark.parametrize(
    "mutate", [_high_leverage, _negative_equity, _poor_data, _no_uptrend],
    ids=["de_above_max", "negative_equity", "quality_poor", "no_technical_uptrend"],
)
def test_committee_logged_action_never_exceeds_engine(mutate):
    fund, tech = mutate(*_base())
    engine = RetirementStrategy().decide(fund, tech)
    verdict = CommitteeAnalyzer(call_fn=_all_buy(), use_cache=False).analyze(fund, tech)

    # Precondition: the case is one decide() blocks or caps below the panel's vote.
    assert _rank(engine.action) < _rank(verdict.action), (engine.action, verdict.action)

    logged = verdict.to_decision(fund, tech)
    assert _rank(logged.action) <= _rank(engine.action), (logged.action, engine.action)
    # The raw vote is kept for display (hybrid decision), not overwritten.
    assert verdict.action in ("BUY", "STRONG BUY")


def test_committee_more_prudent_than_engine_is_kept():
    """«más prudente, nunca menos»: the overlay floors, it never raises."""
    fund, tech = _base()
    fake = make_fake(
        fundamental=_fundamental_json("HOLD", "HIGH"),
        macro=_agent_json("HOLD"), devil=_agent_json("SELL"),
        pm=_agent_json("HOLD"), coach=_agent_json("HOLD"), dividend=_agent_json("HOLD"),
    )
    verdict = CommitteeAnalyzer(call_fn=fake, use_cache=False).analyze(fund, tech)
    assert verdict.to_decision(fund, tech).action == verdict.action
