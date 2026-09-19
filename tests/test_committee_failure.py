"""A failed AI panel must never masquerade as an investment recommendation."""

import json

import pytest
from loguru import logger

from analysis.committee import (
    AgentOpinion,
    CommitteeAnalyzer,
    _parse_agent,
    _parse_fundamental,
    _verdict_from_dict,
    _verdict_to_dict,
    aggregate,
)
from config import AI_FALLBACK


class AuthenticationFailure(RuntimeError):
    status_code = 401


def test_authentication_failure_is_unavailable_and_does_not_expose_credentials():
    secret = "gsk_test_secret_do_not_expose"
    calls = []
    messages = []

    def fail(prompt):
        calls.append(prompt)
        raise AuthenticationFailure(f"Invalid API Key: {secret}")

    handler = logger.add(lambda message: messages.append(str(message)))
    try:
        analyzer = CommitteeAnalyzer(call_fn=fail, use_cache=False)
        jobs = {str(i): ("prompt", _parse_fundamental) for i in range(6)}
        opinions = analyzer._run_agents(jobs)
    finally:
        logger.remove(handler)
    verdict = aggregate("MSFT", opinions)

    assert len(calls) == 6  # Authentication failures are not retried.
    assert verdict.action == "UNAVAILABLE"
    assert verdict.confidence == "LOW"
    assert not verdict.available
    assert not verdict.complete
    assert verdict.failure_causes == [AI_FALLBACK.KEY_INVALIDA]
    assert all(op.error_cause == AI_FALLBACK.KEY_INVALIDA for op in opinions)
    assert secret not in json.dumps(_verdict_to_dict(verdict))
    assert secret not in "".join(messages)
    assert AI_FALLBACK.KEY_INVALIDA in "".join(messages)
    with pytest.raises(ValueError, match="unavailable"):
        verdict.to_decision()


@pytest.mark.parametrize("parser", [lambda raw: _parse_agent("Macro", raw), _parse_fundamental])
def test_unparseable_vote_reports_safe_classified_failure(parser):
    opinion = parser("not valid json")
    assert not opinion.ok
    assert opinion.error_cause == AI_FALLBACK.JSON_INVALIDO


def test_partial_panel_preserves_valid_vote_and_failure_cause_roundtrip():
    verdict = aggregate("MSFT", [
        AgentOpinion("Analista Fundamental", "BUY", "HIGH"),
        AgentOpinion("Macro", "HOLD", "LOW", error="key_invalida", error_cause=AI_FALLBACK.KEY_INVALIDA),
    ])
    restored = _verdict_from_dict(_verdict_to_dict(verdict))
    assert restored.available and not restored.complete
    assert restored.action == "BUY"
    assert restored.failure_causes == [AI_FALLBACK.KEY_INVALIDA]
    assert restored.to_decision().action == "BUY"


def test_legacy_cached_opinion_without_error_cause_still_loads():
    verdict = _verdict_from_dict({"symbol": "MSFT", "action": "BUY", "opinions": [
        {"role": "Analista Fundamental", "stance": "BUY", "confidence": "HIGH"},
    ]})
    assert verdict.available and verdict.complete
    assert verdict.failure_causes == []


def test_empty_panel_is_unavailable():
    verdict = aggregate("MSFT", [])
    assert verdict.action == "UNAVAILABLE"
    assert not verdict.available
