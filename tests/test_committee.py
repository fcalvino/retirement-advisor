"""Tests for the multi-agent committee (Gran Salto, Fase 2B).

Uses an injected fake LLM (``call_fn``) that returns canned JSON per agent role,
so the whole committee runs deterministically with no network. Verifies the
deterministic aggregation, that dissent is ALWAYS surfaced, the conservative
confidence downgrade, and the Decision mapping.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from analysis.ai_analyzer import classify_ai_failure
from analysis.committee import (
    AgentOpinion,
    CommitteeAnalyzer,
    _is_rate_limit,
    _lean_to_action,
    _parse_agent,
    _retry_after_seconds,
    aggregate,
)
from analysis.eval_cases import golden_cases
from config import AI_FALLBACK, COMMITTEE, AIConfig


def _fund_tech():
    case = golden_cases()[0]  # quality_compounder_buy (MSFT-like)
    return case.fund, case.tech


# --------------------------------------------------------------------------- #
#  Fake LLM                                                                    #
# --------------------------------------------------------------------------- #

def _agent_json(stance, confidence="MEDIUM", key_points=None, concerns=None):
    return json.dumps({
        "stance": stance,
        "confidence": confidence,
        "key_points": key_points or ["punto clave"],
        "concerns": concerns or ["una preocupación"],
    }, ensure_ascii=False)


def _fundamental_json(action, confidence="HIGH", rationale=None, risks=None):
    return json.dumps({
        "action": action,
        "confidence": confidence,
        "rationale": rationale or ["fundamento sólido"],
        "risks": risks or ["riesgo de valuación"],
        "reasoning": "x" * 120,
    }, ensure_ascii=False)


def make_fake(*, fundamental, macro, devil, pm, coach):
    """Route the fake response by the role title embedded in each prompt."""
    def call_fn(prompt: str) -> str:
        if "Abogado del Diablo" in prompt:
            return devil
        if "Estratega Macro" in prompt:
            return macro
        if "Portfolio Manager" in prompt:
            return pm
        if "Behavioral Coach" in prompt:
            return coach
        return fundamental  # the equity_decision_prompt has none of the above titles
    return call_fn


# --------------------------------------------------------------------------- #
#  Aggregation                                                                 #
# --------------------------------------------------------------------------- #

def test_all_bullish_yields_buy():
    ops = [
        AgentOpinion("Analista Fundamental", "BUY", "HIGH", ["a"], ["r"]),
        AgentOpinion("Estratega Macro", "BUY", "MEDIUM", ["b"], ["r"]),
        AgentOpinion("Abogado del Diablo", "BUY", "LOW", ["c"], ["bear point"]),
        AgentOpinion("Portfolio Manager", "BUY", "HIGH", ["d"], ["r"]),
        AgentOpinion("Behavioral Coach", "HOLD", "MEDIUM", ["e"], ["r"]),
    ]
    v = aggregate("MSFT", ops)
    assert v.action in {"BUY", "STRONG BUY"}


def test_dissent_always_includes_devil_concerns():
    """Even with a unanimous bull case, the bear case must be surfaced."""
    ops = [
        AgentOpinion("Analista Fundamental", "STRONG BUY", "HIGH", ["a"], ["r"]),
        AgentOpinion("Estratega Macro", "BUY", "HIGH", ["b"], ["r"]),
        AgentOpinion("Abogado del Diablo", "BUY", "LOW", ["c"], ["la valuación es exigente"]),
        AgentOpinion("Portfolio Manager", "STRONG BUY", "HIGH", ["d"], ["r"]),
        AgentOpinion("Behavioral Coach", "BUY", "MEDIUM", ["e"], ["r"]),
    ]
    v = aggregate("MSFT", ops)
    assert "la valuación es exigente" in v.dissent


def test_strong_dissent_downgrades_confidence():
    ops = [
        AgentOpinion("Analista Fundamental", "BUY", "HIGH", ["a"], ["r"]),
        AgentOpinion("Estratega Macro", "BUY", "HIGH", ["b"], ["r"]),
        AgentOpinion("Abogado del Diablo", "SELL", "HIGH", ["c"], ["riesgo de capital serio"]),
        AgentOpinion("Portfolio Manager", "BUY", "HIGH", ["d"], ["r"]),
        AgentOpinion("Behavioral Coach", "HOLD", "MEDIUM", ["e"], ["r"]),
    ]
    v = aggregate("MSFT", ops)
    # Fundamental said HIGH, but strong bear case drops it a notch.
    assert v.confidence in {"MEDIUM", "LOW"}
    assert any("riesgo de capital serio" in d for d in v.dissent)


def test_disagreeing_agent_is_flagged_in_dissent():
    ops = [
        AgentOpinion("Analista Fundamental", "STRONG BUY", "HIGH", ["a"], ["r"]),
        AgentOpinion("Estratega Macro", "REDUCE", "MEDIUM", ["macro flojo"], ["riesgo país"]),
        AgentOpinion("Abogado del Diablo", "BUY", "LOW", ["c"], ["bear"]),
        AgentOpinion("Portfolio Manager", "STRONG BUY", "HIGH", ["d"], ["r"]),
        AgentOpinion("Behavioral Coach", "BUY", "MEDIUM", ["e"], ["r"]),
    ]
    v = aggregate("MSFT", ops)
    assert v.action in {"BUY", "STRONG BUY"}  # net positive
    assert any("Estratega Macro discrepa" in d for d in v.dissent)


def test_lean_to_action_thresholds():
    assert _lean_to_action(2.0) == "STRONG BUY"
    assert _lean_to_action(1.0) == "BUY"
    assert _lean_to_action(0.0) == "HOLD"
    assert _lean_to_action(-1.0) == "REDUCE"
    assert _lean_to_action(-2.0) == "SELL"


# --------------------------------------------------------------------------- #
#  Parsing                                                                     #
# --------------------------------------------------------------------------- #

def test_parse_agent_handles_garbage():
    op = _parse_agent("Estratega Macro", "no soy json")
    assert op.ok is False
    assert op.stance == "HOLD"


def test_parse_agent_normalizes_invalid_stance():
    op = _parse_agent("Estratega Macro", json.dumps({"stance": "MAYBE", "confidence": "WAT"}))
    assert op.stance == "HOLD"
    assert op.confidence == "MEDIUM"


# --------------------------------------------------------------------------- #
#  End-to-end with injected LLM                                                #
# --------------------------------------------------------------------------- #

def test_committee_runs_end_to_end_no_network():
    fund, tech = _fund_tech()
    fake = make_fake(
        fundamental=_fundamental_json("BUY", "HIGH"),
        macro=_agent_json("BUY", "MEDIUM"),
        devil=_agent_json("HOLD", "MEDIUM", concerns=["múltiplo alto"]),
        pm=_agent_json("BUY", "HIGH"),
        coach=_agent_json("HOLD", "MEDIUM"),
    )
    committee = CommitteeAnalyzer(call_fn=fake, use_cache=False)
    verdict = committee.analyze(fund, tech)
    assert len(verdict.opinions) == 5
    assert verdict.action in {"BUY", "STRONG BUY", "HOLD"}
    assert "múltiplo alto" in verdict.dissent


def test_to_decision_maps_fields_and_keeps_scores_deterministic():
    fund, tech = _fund_tech()
    fake = make_fake(
        fundamental=_fundamental_json("BUY", "HIGH"),
        macro=_agent_json("BUY"),
        devil=_agent_json("HOLD", concerns=["valuación"]),
        pm=_agent_json("BUY", "HIGH"),
        coach=_agent_json("HOLD"),
    )
    verdict = CommitteeAnalyzer(call_fn=fake, use_cache=False).analyze(fund, tech)
    d = verdict.to_decision(fund, tech)
    assert d.symbol == fund.symbol
    assert d.action == verdict.action
    assert d.risks == verdict.dissent           # dissent -> risks
    assert d.rationale == verdict.consensus_points
    # Score comes from the engine, never the LLM.
    assert d.fundamental_score == fund.total_score


def test_committee_provider_in_eval_harness():
    from analysis.eval_harness import CommitteeProvider, run_checks

    case = golden_cases()[0]
    fake = make_fake(
        fundamental=_fundamental_json("BUY", "HIGH"),
        macro=_agent_json("BUY"),
        devil=_agent_json("HOLD", concerns=["valuación exigente"]),
        pm=_agent_json("BUY", "HIGH"),
        coach=_agent_json("HOLD"),
    )
    provider = CommitteeProvider(call_fn=fake)
    decision = provider.get_decision(case)
    checks = run_checks(case, decision)
    # Structure + deterministic-score checks must pass for a committee decision.
    by_name = {c.name: c for c in checks}
    assert by_name["valid_structure"].passed
    assert by_name["scores_deterministic"].passed


class _Fake429(Exception):
    def __init__(self, msg="Rate limit reached", retry_after=None):
        super().__init__(msg)
        self.status_code = 429
        if retry_after is not None:
            self.response = type("R", (), {"headers": {"retry-after": str(retry_after)}})()


def test_incomplete_panel_is_not_complete():
    ops = [
        AgentOpinion("Analista Fundamental", "HOLD", "LOW", error="429"),
        AgentOpinion("Estratega Macro", "HOLD", "LOW", error="429"),
        AgentOpinion("Abogado del Diablo", "SELL", "HIGH", ["c"], ["bear"]),
        AgentOpinion("Portfolio Manager", "HOLD", "MEDIUM", ["d"], ["r"]),
        AgentOpinion("Behavioral Coach", "HOLD", "MEDIUM", ["e"], ["r"]),
    ]
    v = aggregate("MSFT", ops)
    assert v.lean == -0.7
    assert v.action == "REDUCE"
    assert v.complete is False


def test_complete_panel_requires_every_agent_ok():
    ops = [
        AgentOpinion("Analista Fundamental", "BUY", "HIGH", ["a"], ["r"]),
        AgentOpinion("Estratega Macro", "BUY", "MEDIUM", ["b"], ["r"]),
        AgentOpinion("Abogado del Diablo", "HOLD", "LOW", ["c"], ["bear"]),
        AgentOpinion("Portfolio Manager", "BUY", "HIGH", ["d"], ["r"]),
        AgentOpinion("Behavioral Coach", "HOLD", "MEDIUM", ["e"], ["r"]),
    ]
    assert aggregate("MSFT", ops).complete is True


def test_rate_limit_retries_then_succeeds():
    fund, tech = _fund_tech()
    hits = {"n": 0}

    def call_fn(prompt: str) -> str:
        hits["n"] += 1
        if hits["n"] == 1:
            raise _Fake429("Please try again in 0.01s. Rate limit reached")
        if "Abogado del Diablo" in prompt:
            return _agent_json("HOLD", concerns=["múltiplo alto"])
        if "Estratega Macro" in prompt:
            return _agent_json("BUY")
        if "Portfolio Manager" in prompt:
            return _agent_json("BUY", "HIGH")
        if "Behavioral Coach" in prompt:
            return _agent_json("HOLD")
        return _fundamental_json("BUY", "HIGH")

    with patch("analysis.committee.time.sleep"):
        v = CommitteeAnalyzer(call_fn=call_fn, use_cache=False).analyze(fund, tech)
    assert v.complete is True
    assert hits["n"] == 6  # 1 fail + 5 successes


def test_permanent_429_does_not_cache(monkeypatch):
    fund, tech = _fund_tech()
    stored = {}

    class _FakeCache:
        def get(self, key):
            return stored.get(key)
        def set(self, key, value):
            stored[key] = value

    monkeypatch.setattr("data.cache.cache", _FakeCache(), raising=False)

    def call_fn(prompt: str) -> str:
        if "Portfolio Manager" in prompt:
            raise _Fake429("Rate limit reached for model")
        if "Abogado del Diablo" in prompt:
            return _agent_json("SELL", "HIGH", concerns=["bear"])
        if "Estratega Macro" in prompt:
            return _agent_json("BUY")
        if "Behavioral Coach" in prompt:
            return _agent_json("HOLD")
        return _fundamental_json("BUY", "HIGH")

    with patch("analysis.committee.time.sleep"):
        analyzer = CommitteeAnalyzer(
            call_fn=call_fn,
            ai_config=AIConfig(provider="groq", model="openai/gpt-oss-120b", api_key="k"),
            use_cache=True,
        )
        # Bypass constructor workers; we still want retries not sleep-real.
        v = analyzer.analyze(fund, tech)
    assert v.complete is False
    assert stored == {}


def test_groq_defaults_to_serial_workers():
    analyzer = CommitteeAnalyzer(
        call_fn=lambda _p: _agent_json("HOLD"),
        ai_config=AIConfig(provider="groq", model="openai/gpt-oss-120b", api_key="k"),
        use_cache=False,
    )
    assert analyzer._max_workers == COMMITTEE.groq_max_workers == 1


def test_committee_max_tokens_lives_in_config():
    src = (Path(__file__).resolve().parents[1] / "analysis/committee.py").read_text()
    assert "max_tokens=900" not in src
    assert "COMMITTEE.max_tokens" in src


def test_retry_after_prefers_header_then_body():
    assert _retry_after_seconds(_Fake429(retry_after=3)) == 3.0
    assert _retry_after_seconds(_Fake429("Please try again in 7.98s.")) == 7.98
    assert _is_rate_limit(_Fake429())
    assert classify_ai_failure(_Fake429()) == AI_FALLBACK.RATE_LIMIT


def test_comite_page_prefetches_without_ai():
    src = (
        Path(__file__).resolve().parents[1] / "dashboard/pages/15_Comite.py"
    ).read_text()
    assert "cached_full_analysis(\n            symbol, ai_cfg.provider, ai_cfg.model, False" in src
    assert "if verdict.complete:" in src
