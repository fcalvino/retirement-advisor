"""A committee convened with no API key must say so, not blame the key.

`AIAnalyzer._preflight` exists precisely so a missing key is reported as
``sin_api_key`` instead of being indistinguishable from a 401. The committee
calls ``AIAnalyzer._call_api`` directly and used to skip that pre-flight, so the
Groq transport's "No credentials found" RuntimeError was classified by string
match ("credential") as ``key_invalida``: the UI told the user to fix a key they
never set.

Offline: with an empty key the Groq branch raises before building a client.
"""

from analysis.committee import CommitteeAnalyzer, _parse_agent, aggregate
from config import AI_FALLBACK, AIConfig


def test_committee_without_api_key_reports_sin_api_key(monkeypatch):
    for var in ("GROQ_API_KEY", "AI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    cfg = AIConfig(provider="groq", model="openai/gpt-oss-120b", api_key="", enabled=True)
    assert cfg.api_key == ""

    analyzer = CommitteeAnalyzer(ai_config=cfg, use_cache=False)
    jobs = {role: ("prompt", lambda raw, r=role: _parse_agent(r, raw))
            for role in ("Estratega Macro", "Portfolio Manager")}
    verdict = aggregate("KO", analyzer._run_agents(jobs))

    assert verdict.action == "UNAVAILABLE"
    assert verdict.failure_causes == [AI_FALLBACK.SIN_API_KEY]
