"""``analysis.moat.call_ai_api`` — the O2 shim over ``AIAnalyzer._call_api``.

Dispatch now lives in ``AIAnalyzer``; this file pins the shim's own logic
(delegation, ``max_tokens`` passthrough, provider lower-casing, ``MoatAPIError``
re-wrapping) since the callers all patch ``call_ai_api`` wholesale.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from analysis.moat import MoatAPIError, call_ai_api


@dataclass
class _Cfg:
    provider: str
    model: str = "m"
    api_key: str = "k"


def test_delegates_to_aianalyzer_with_max_tokens(monkeypatch):
    seen = {}

    def _fake_call_api(self, prompt, max_tokens=None):
        seen["provider"] = self.config.provider
        seen["prompt"] = prompt
        seen["max_tokens"] = max_tokens
        return "RAW"

    monkeypatch.setattr("analysis.ai_analyzer.AIAnalyzer._call_api", _fake_call_api)

    out = call_ai_api("hello", _Cfg(provider="claude"), max_tokens=777)

    assert out == "RAW"
    assert seen == {"provider": "claude", "prompt": "hello", "max_tokens": 777}


def test_provider_is_lower_cased_before_dispatch(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "analysis.ai_analyzer.AIAnalyzer._call_api",
        lambda self, prompt, max_tokens=None: seen.setdefault("provider", self.config.provider) or "x",
    )

    call_ai_api("p", _Cfg(provider="OpenAI"))

    assert seen["provider"] == "openai"


def test_any_failure_is_rewrapped_as_moat_api_error(monkeypatch):
    def _boom(self, prompt, max_tokens=None):
        raise RuntimeError("network down")

    monkeypatch.setattr("analysis.ai_analyzer.AIAnalyzer._call_api", _boom)

    with pytest.raises(MoatAPIError, match="claude API error: network down"):
        call_ai_api("p", _Cfg(provider="claude"))


def test_moat_api_error_passes_through_unwrapped(monkeypatch):
    def _boom(self, prompt, max_tokens=None):
        raise MoatAPIError("Unknown AI provider: 'zzz'")

    monkeypatch.setattr("analysis.ai_analyzer.AIAnalyzer._call_api", _boom)

    with pytest.raises(MoatAPIError, match="Unknown AI provider"):
        call_ai_api("p", _Cfg(provider="zzz"))
