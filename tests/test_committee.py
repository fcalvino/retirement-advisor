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
from analysis.committee_prompts import DIVIDEND_ROLE
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


def make_fake(*, fundamental, macro, devil, pm, coach, dividend=None):
    """Route the fake response by the role title embedded in each prompt."""
    dividend = dividend or _agent_json("HOLD")
    def call_fn(prompt: str) -> str:
        if "Abogado del Diablo" in prompt:
            return devil
        if "Estratega Macro" in prompt:
            return macro
        if "Portfolio Manager" in prompt:
            return pm
        if "Behavioral Coach" in prompt:
            return coach
        if DIVIDEND_ROLE in prompt:
            # La voz de Dividendo usa el esquema `stance`, no el `action` del
            # Fundamental: caer al default le daba un voto ilegible que antes se
            # coercía a HOLD en silencio — el defecto mismo, dentro del fixture.
            return dividend
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


def test_parse_agent_rejects_a_stance_outside_the_vocabulary():
    """Antes se normalizaba a HOLD con ``ok=True`` — ese era el HOLD silencioso.

    Un `stance` que el vocabulario no reconoce no es una postura neutra: es un
    voto que no se pudo leer, y tiene que salir del quórum como cualquier otro
    fallo del agente. `confidence` sí se coerce: no entra al lean.
    """
    op = _parse_agent("Estratega Macro", json.dumps({"stance": "MAYBE", "confidence": "WAT"}))
    assert not op.ok
    assert op.error_cause == AI_FALLBACK.JSON_INVALIDO

    ok_op = _parse_agent("Estratega Macro", json.dumps({"stance": "BUY", "confidence": "WAT"}))
    assert ok_op.ok and ok_op.stance == "BUY" and ok_op.confidence == "MEDIUM"


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
    from analysis.committee import _pays_dividend

    # Cinco voces fijas + la de dividendo cuando el activo paga (el caso MSFT-like paga).
    assert len(verdict.opinions) == 5 + int(_pays_dividend(fund))
    assert verdict.action in {"BUY", "STRONG BUY", "HOLD"}
    assert "múltiplo alto" in verdict.dissent


def test_fundamental_prompt_receives_rag_macro(monkeypatch):
    """#130 paso 4: the Fundamental sees the same dated macro as the Macro Strategist."""
    import analysis.macro_rag as mr

    monkeypatch.setattr(mr, "macro_context_for", lambda fund: "[2026-09] FEDFUNDS 4.25%")
    seen = []
    base = make_fake(
        fundamental=_fundamental_json("BUY"), macro=_agent_json("BUY"),
        devil=_agent_json("HOLD"), pm=_agent_json("BUY"), coach=_agent_json("HOLD"),
    )

    def call_fn(prompt):
        seen.append(prompt)
        return base(prompt)

    fund, tech = _fund_tech()
    CommitteeAnalyzer(call_fn=call_fn, use_cache=False).analyze(fund, tech)
    fundamental = [p for p in seen if '"recommended_max_allocation_conservative"' in p]
    assert len(fundamental) == 1
    assert "[2026-09] FEDFUNDS 4.25%" in fundamental[0]


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


# --------------------------------------------------------------------------- #
#  Set corto: bloque compartido, PM con cartera real, voz de dividendo         #
# --------------------------------------------------------------------------- #

import copy  # noqa: E402

from analysis.committee import (  # noqa: E402
    DIVIDEND_VOTE_ROLE,
    _pays_dividend,
    _portfolio_variant,
    build_ticker_portfolio_context,
)
from analysis.committee_prompts import (  # noqa: E402
    _role_prompt,
    devils_advocate_prompt,
    portfolio_manager_prompt,
)
from config import STRESS_SCENARIOS  # noqa: E402

_PM_LEGACY_INSTRUCTIONS = (
    "Concilá las visiones (fundamental, macro y el bear case del abogado del diablo) y "
    "decidí el dimensionamiento práctico para una cartera de retiro conservadora "
    "(máximo prudente por nombre ~8-15%). Tu stance es la decisión de cartera, no un "
    "análisis aislado: pesá el upside contra el riesgo de capital. Si el bear case es "
    "serio, reflejalo en una postura y un tamaño más cautos."
)


def _fund_with(**overrides):
    fund, tech = _fund_tech()
    fund = copy.deepcopy(fund)
    for k, v in overrides.items():
        setattr(fund, k, v)
    return fund, tech


def _routing_fake(dividend_stance="SELL"):
    base = make_fake(
        fundamental=_fundamental_json("BUY", "HIGH"),
        macro=_agent_json("BUY"),
        devil=_agent_json("HOLD", concerns=["valuación"]),
        pm=_agent_json("BUY", "HIGH"),
        coach=_agent_json("HOLD"),
    )

    def call_fn(prompt):
        if DIVIDEND_ROLE in prompt:
            return _agent_json(dividend_stance)
        return base(prompt)
    return call_fn


def test_devils_advocate_now_sees_engine_warnings():
    fund, tech = _fund_with(warnings=["Payout alto 140% — el dividendo puede no ser sostenible"])
    prompt = devils_advocate_prompt(fund, tech)
    assert "Alertas del motor" in prompt
    assert "Payout alto 140%" in prompt


def test_shared_block_adds_country_and_omits_empty_facts():
    fund, tech = _fund_with(country="Argentina", warnings=[])
    prompt = devils_advocate_prompt(fund, tech)
    assert "País: Argentina" in prompt
    assert "Alertas del motor" not in prompt


def test_pm_prompt_byte_identical_without_portfolio():
    fund, tech = _fund_tech()
    legacy = _role_prompt("Portfolio Manager", _PM_LEGACY_INSTRUCTIONS, fund, tech)
    assert portfolio_manager_prompt(fund, tech) == legacy
    assert portfolio_manager_prompt(fund, tech, None) == legacy


def test_pm_prompt_carries_real_weight_and_sector_shock():
    fund, tech = _fund_tech()
    ctx = build_ticker_portfolio_context(
        fund.symbol, fund.sector,
        position_weights={fund.symbol: 12.3, "KO": 87.7},
        sector_weights={fund.sector: 40.0},
    )
    prompt = portfolio_manager_prompt(fund, tech, ctx)
    assert "TU CARTERA REAL" in prompt
    assert "12.3%" in prompt
    worst_name, worst_shock = ctx["sector_shocks"][0]
    assert worst_name in prompt and f"{worst_shock:.0f}%" in prompt


def test_ticker_portfolio_context_edges():
    assert build_ticker_portfolio_context("MSFT", "Technology", position_weights={}) is None

    ctx = build_ticker_portfolio_context("MSFT", "Technology", position_weights={"KO": 100.0})
    assert ctx["weight_pct"] == 0.0
    assert "plan_target_pct" not in ctx
    assert len(ctx["sector_shocks"]) == len(STRESS_SCENARIOS)

    class _Plan:
        name = "Retiro"

        def target_weights(self):
            return {"MSFT": 10.0, "KO": 90.0}

    ctx = build_ticker_portfolio_context(
        "MSFT", "Technology", position_weights={"MSFT": 15.0, "KO": 85.0}, active_plan=_Plan(),
    )
    assert ctx["plan_target_pct"] == 10.0
    assert ctx["drift_pct"] == 5.0


def test_dividend_voice_abstains_without_dividend_and_for_crypto():
    for overrides in ({"dividend_yield": 0.0}, {"dividend_yield": None},
                      {"dividend_yield": 3.0, "is_crypto": True}):
        fund, tech = _fund_with(**overrides)
        v = CommitteeAnalyzer(call_fn=_routing_fake(), use_cache=False).analyze(fund, tech)
        assert all(o.role != DIVIDEND_VOTE_ROLE for o in v.opinions)
        assert len(v.opinions) == 5
        five = [o for o in v.opinions]
        assert v.lean == aggregate(fund.symbol, five).lean


def test_dividend_voice_votes_with_configured_weight():
    fund, tech = _fund_with(dividend_yield=3.2)
    v = CommitteeAnalyzer(call_fn=_routing_fake("SELL"), use_cache=False).analyze(fund, tech)
    div = next(o for o in v.opinions if o.role == DIVIDEND_VOTE_ROLE)
    assert div.stance == "SELL"

    score = {"STRONG BUY": 2.0, "BUY": 1.0, "HOLD": 0.0, "REDUCE": -1.0, "SELL": -2.0}
    w = COMMITTEE.vote_weights
    num = sum(w[o.role] * score[o.stance] for o in v.opinions)
    den = sum(w[o.role] for o in v.opinions)
    assert w[DIVIDEND_VOTE_ROLE] == 0.6
    assert v.lean == round(num / den, 4)


def test_cache_key_distinguishes_portfolio_context():
    c = CommitteeAnalyzer(call_fn=lambda p: "{}", use_cache=False)
    ctx = build_ticker_portfolio_context("MSFT", "Technology", position_weights={"MSFT": 10.0})
    plain = c._cache_key("MSFT", _portfolio_variant(None))
    with_pf = c._cache_key("MSFT", _portfolio_variant(ctx))
    assert plain == c._cache_key("MSFT")  # sin cartera: la clave de siempre
    assert with_pf != plain
    assert with_pf == c._cache_key("MSFT", _portfolio_variant(dict(ctx)))
    other = build_ticker_portfolio_context("MSFT", "Technology", position_weights={"MSFT": 20.0})
    assert c._cache_key("MSFT", _portfolio_variant(other)) != with_pf
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
        if DIVIDEND_ROLE in prompt:
            return _agent_json("HOLD")
        return _fundamental_json("BUY", "HIGH")

    with patch("analysis.committee.time.sleep"):
        v = CommitteeAnalyzer(call_fn=call_fn, use_cache=False).analyze(fund, tech)
    assert v.complete is True
    assert hits["n"] == 1 + 5 + int(_pays_dividend(fund))


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
        if DIVIDEND_ROLE in prompt:
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
        Path(__file__).resolve().parents[1] / "dashboard/views/15_Comite.py"
    ).read_text()
    assert "cached_full_analysis(\n            symbol, ai_cfg.provider, ai_cfg.model, False" in src
    assert "if verdict.complete:" in src


# --------------------------------------------------------------------------- #
#  #130 paso 1 — el bear case ve la crisis del sector y las alertas técnicas    #
# --------------------------------------------------------------------------- #

from analysis.committee_prompts import (  # noqa: E402
    behavioral_coach_prompt,
    macro_strategist_prompt,
    sector_stress_shocks,
)


def test_devils_advocate_sees_sector_stress_shocks():
    fund, tech = _fund_tech()
    prompt = devils_advocate_prompt(fund, tech)
    worst_name, worst_shock = sector_stress_shocks(fund.sector)[0]
    assert "Caída de su sector en crisis históricas" in prompt
    assert worst_name in prompt and f"{worst_shock:.0f}%" in prompt


def test_devils_advocate_tech_warnings_only_when_present():
    fund, tech = _fund_tech()
    tech = copy.deepcopy(tech)
    tech.warnings = ["RSI sobrecomprado"]
    assert "Alertas técnicas: RSI sobrecomprado" in devils_advocate_prompt(fund, tech)
    tech.warnings = []
    assert "Alertas técnicas" not in devils_advocate_prompt(fund, tech)


def test_stress_facts_stay_out_of_the_shared_block():
    fund, tech = _fund_tech()
    for prompt in (macro_strategist_prompt(fund, tech), behavioral_coach_prompt(fund, tech)):
        assert "Caída de su sector en crisis históricas" not in prompt


def test_sector_stress_shocks_match_the_pm_context():
    ctx = build_ticker_portfolio_context("MSFT", "Technology", position_weights={"MSFT": 10.0})
    assert ctx["sector_shocks"] == sector_stress_shocks("Technology")
    assert len(ctx["sector_shocks"]) == len(STRESS_SCENARIOS)


# --------------------------------------------------------------------------- #
#  #130 paso 2 — la versión del prompt invalida los veredictos cacheados        #
# --------------------------------------------------------------------------- #

def test_cache_key_changes_with_prompt_version():
    c = CommitteeAnalyzer(call_fn=lambda p: "{}", use_cache=False)
    before = c._cache_key("MSFT")
    assert f"v{COMMITTEE.prompt_version}" in before
    with patch.object(COMMITTEE, "prompt_version", "otra"):
        assert c._cache_key("MSFT") != before


# --------------------------------------------------------------------------- #
#  #130 paso 5 — data_quality modula la confianza, no el voto                  #
# --------------------------------------------------------------------------- #

from analysis.committee import _data_quality_variant  # noqa: E402


def _quality_ops(fund_conf="HIGH"):
    return [
        AgentOpinion("Analista Fundamental", "BUY", fund_conf, ["a"], ["r"]),
        AgentOpinion("Estratega Macro", "BUY", "MEDIUM", ["b"], ["r"]),
        AgentOpinion("Abogado del Diablo", "HOLD", "LOW", ["c"], ["bear"]),
        AgentOpinion("Portfolio Manager", "BUY", "HIGH", ["d"], ["r"]),
        AgentOpinion("Behavioral Coach", "HOLD", "MEDIUM", ["e"], ["r"]),
    ]


def test_data_quality_downgrades_confidence_not_vote():
    thr = COMMITTEE.data_quality_downgrade_missing_fields
    base = aggregate("MSFT", _quality_ops())
    assert base.confidence == "HIGH"
    for dq in ({"stale": True, "n_missing": 0}, {"stale": False, "n_missing": thr}):
        v = aggregate("MSFT", _quality_ops(), data_quality=dq)
        assert v.confidence == "MEDIUM"
        assert (v.lean, v.action) == (base.lean, base.action)
    ok = aggregate("MSFT", _quality_ops(), data_quality={"stale": False, "n_missing": thr - 1})
    assert ok.confidence == "HIGH"
    floor = aggregate("MSFT", _quality_ops("LOW"), data_quality={"stale": True, "n_missing": 0})
    assert floor.confidence == "LOW"


def test_data_quality_cache_variant():
    assert _data_quality_variant(None) == ""
    a = {"stale": False, "n_missing": 1, "freshness_hours": 2.0}
    assert _data_quality_variant(a) == _data_quality_variant(dict(a, freshness_hours=5.0))
    assert _data_quality_variant(a) != _data_quality_variant(dict(a, stale=True))


def test_analyze_keys_cache_and_confidence_by_data_quality(monkeypatch):
    seen = []
    monkeypatch.setattr(CommitteeAnalyzer, "_get_cached", lambda self, s, v="": seen.append(v))
    monkeypatch.setattr(CommitteeAnalyzer, "_set_cached", lambda self, s, verdict, v="": None)
    c = CommitteeAnalyzer(call_fn=_routing_fake(), use_cache=True)

    fund, tech = _fund_with(data_quality=None)
    fresh = c.analyze(fund, tech)
    fund, tech = _fund_with(data_quality={"stale": True, "n_missing": 0})
    stale = c.analyze(fund, tech)

    assert seen[0] == ""  # sin calidad: la clave de siempre
    assert seen[1] == "dq:s1m0"
    assert (stale.lean, stale.action) == (fresh.lean, fresh.action)
    rank = ["LOW", "MEDIUM", "HIGH"]
    assert rank.index(stale.confidence) == max(0, rank.index(fresh.confidence) - 1)


# --------------------------------------------------------------------------- #
#  #130 paso 7 — titulares de yfinance solo para el Abogado del Diablo        #
# --------------------------------------------------------------------------- #

from datetime import datetime  # noqa: E402

from analysis.committee import _ticker_news as _real_ticker_news  # noqa: E402  (antes del autouse)
from analysis.committee_prompts import relevant_headlines  # noqa: E402
from analysis.prompts import equity_decision_prompt  # noqa: E402
from data.clock import utc_now  # noqa: E402

_NOW = datetime(2026, 9, 18, 12, 0)
_NEWS = [
    {"title": "Microsoft faces antitrust probe in EU", "summary": "Regulators open a case.",
     "published": "2026-09-17", "provider": "Reuters"},
    {"title": "Nvidia-backed Nscale files for IPO", "summary": "AI data centers.",
     "published": "2026-09-18", "provider": "Stocktwits"},
    {"title": "MSFT slides after guidance cut", "summary": "",
     "published": "2026-09-18", "provider": "Barrons"},
    {"title": "Microsoft old story", "summary": "", "published": "2026-07-01", "provider": ""},
]


def test_relevant_headlines_keeps_mentions_fresh_newest_first():
    fund, _ = _fund_tech()
    kept = relevant_headlines(_NEWS, fund, now=_NOW)
    assert [h["title"] for h in kept] == [
        "MSFT slides after guidance cut",
        "Microsoft faces antitrust probe in EU",
    ]


def test_relevant_headlines_respects_max_items():
    fund, _ = _fund_tech()
    with patch.object(__import__("config").NEWS, "max_items", 1):
        assert len(relevant_headlines(_NEWS, fund, now=_NOW)) == 1


def test_devils_advocate_sees_dated_headlines():
    fund, tech = _fund_tech()
    with patch("analysis.committee_prompts.utc_now", return_value=_NOW):
        prompt = devils_advocate_prompt(fund, tech, _NEWS)
    assert "Titulares recientes" in prompt
    assert "- [2026-09-17] (Reuters) Microsoft faces antitrust probe in EU: Regulators open a case." in prompt
    assert "Nscale" not in prompt
    assert "old story" not in prompt


def test_devils_advocate_byte_identical_without_headlines():
    fund, tech = _fund_tech()
    base = devils_advocate_prompt(fund, tech)
    assert devils_advocate_prompt(fund, tech, []) == base
    assert devils_advocate_prompt(fund, tech, None) == base
    with patch("analysis.committee_prompts.utc_now", return_value=_NOW):
        irrelevant = [_NEWS[1]]
        assert devils_advocate_prompt(fund, tech, irrelevant) == base


def test_only_the_devils_advocate_receives_news():
    seen = []
    base = make_fake(
        fundamental=_fundamental_json("BUY", "HIGH"),
        macro=_agent_json("BUY"),
        devil=_agent_json("HOLD"),
        pm=_agent_json("BUY"),
        coach=_agent_json("HOLD"),
    )

    def call_fn(prompt):
        seen.append(prompt)
        return base(prompt)

    fund, tech = _fund_tech()
    fresh = [dict(_NEWS[0], published=utc_now().strftime("%Y-%m-%d"))]
    with patch("analysis.committee._ticker_news", return_value=fresh):
        CommitteeAnalyzer(call_fn=call_fn, use_cache=False).analyze(fund, tech)
    with_news = [p for p in seen if "antitrust probe" in p]
    assert len(with_news) == 1
    assert "Abogado del Diablo" in with_news[0]
    assert "antitrust" not in equity_decision_prompt(fund, tech)


def test_news_failure_degrades_to_no_headlines():
    with patch("data.fetcher.get_news", side_effect=ConnectionError("boom")):
        assert _real_ticker_news("MSFT") == []
    with patch.object(__import__("config").NEWS, "enabled", False), \
            patch("data.fetcher.get_news", side_effect=AssertionError("no debe llamarse")):
        assert _real_ticker_news("MSFT") == []


# --------------------------------------------------------------------------- #
#  Drawdowns del propio activo, solo para el Abogado del Diablo (alternativa   #
#  determinista a un loop ReAct: hechos fechados, sin tool calling)            #
# --------------------------------------------------------------------------- #

import pandas as pd  # noqa: E402

from analysis.committee import _ticker_drawdowns as _real_ticker_drawdowns  # noqa: E402
from analysis.committee_prompts import price_drawdowns  # noqa: E402


def _weekly(values, end="2026-09-18"):
    idx = pd.date_range(end=end, periods=len(values), freq="W-FRI")
    return pd.Series(values, index=idx, dtype=float)


def test_price_drawdowns_oracle():
    # 100 → 120 → 60 → 90 en la última semana: pico 120, valle 60 ⇒ −50 %.
    close = _weekly([100.0] * 60 + [120.0, 60.0, 90.0])
    dd = price_drawdowns(close, (1,))
    assert dd == {"as_of": close.index[-1].strftime("%Y-%m-%d"), "by_window": [(1, -50.0)]}


def test_price_drawdowns_window_only_sees_its_own_bars():
    # Caída de hace ~2 años (−80 %): fuera de la ventana de 1 año, dentro de la de 3.
    close = _weekly([100.0] * 60 + [20.0] + [100.0] * 101 + [90.0])
    got = dict(price_drawdowns(close, (1, 3))["by_window"])
    assert got[1] == -10.0
    assert got[3] == -80.0


def test_price_drawdowns_omits_uncovered_windows_and_empty():
    close = _weekly([100.0] * 70)  # ~1,3 años de historia
    assert [y for y, _ in price_drawdowns(close, (1, 3, 5))["by_window"]] == [1]
    assert price_drawdowns(_weekly([100.0] * 10), (1,)) == {}
    assert price_drawdowns(pd.Series(dtype=float), (1,)) == {}
    assert price_drawdowns(None, (1,)) == {}


def test_price_drawdowns_anchor_is_last_bar_not_clock():
    close = _weekly([100.0] * 60 + [120.0, 60.0, 90.0], end="2020-01-03")
    with patch("analysis.committee_prompts.utc_now", return_value=_NOW):
        dd = price_drawdowns(close, (1,))
    assert dd["as_of"] == "2020-01-03"


def test_devils_advocate_sees_dated_drawdowns():
    fund, tech = _fund_tech()
    dd = {"as_of": "2026-09-18", "by_window": [(1, -12.3), (3, -34.0), (5, -41.6)]}
    prompt = devils_advocate_prompt(fund, tech, None, dd)
    assert "Peor caída del propio activo (al 2026-09-18): 1a -12%, 3a -34%, 5a -42%" in prompt


def test_devils_advocate_byte_identical_without_drawdowns():
    fund, tech = _fund_tech()
    base = devils_advocate_prompt(fund, tech)
    assert devils_advocate_prompt(fund, tech, None, None) == base
    assert devils_advocate_prompt(fund, tech, None, {}) == base


def test_only_the_devils_advocate_receives_drawdowns():
    seen = []
    base = make_fake(
        fundamental=_fundamental_json("BUY", "HIGH"),
        macro=_agent_json("BUY"),
        devil=_agent_json("HOLD"),
        pm=_agent_json("BUY"),
        coach=_agent_json("HOLD"),
    )

    def call_fn(prompt):
        seen.append(prompt)
        return base(prompt)

    fund, tech = _fund_tech()
    dd = {"as_of": "2026-09-18", "by_window": [(1, -12.0)]}
    with patch("analysis.committee._ticker_drawdowns", return_value=dd):
        CommitteeAnalyzer(call_fn=call_fn, use_cache=False).analyze(fund, tech)
    with_dd = [p for p in seen if "Peor caída del propio activo" in p]
    assert len(with_dd) == 1
    assert "Abogado del Diablo" in with_dd[0]


def test_drawdowns_failure_degrades_to_empty():
    with patch("data.fetcher.get_history", side_effect=ConnectionError("boom")):
        assert _real_ticker_drawdowns("MSFT") == {}
    with patch.object(__import__("config").COMMITTEE, "drawdown_enabled", False), \
            patch("data.fetcher.get_history", side_effect=AssertionError("no debe llamarse")):
        assert _real_ticker_drawdowns("MSFT") == {}
