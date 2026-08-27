"""Tests for the portfolio-level investment committee.

Uses an injected fake LLM (``call_fn``) routed by the role title embedded in each
prompt, so the whole committee runs deterministically with no network. Verifies
the context assembly, the concentration helper, that the four plan-level agents
run, that the Devil's Advocate dissent is ALWAYS surfaced, the fallback on a bad
agent, and the stance→plan-label mapping.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from analysis.committee import (
    CommitteeAnalyzer,
    build_holdings_committee_context,
    build_portfolio_committee_context,
    portfolio_concentration,
)
from config import COMMITTEE

# --------------------------------------------------------------------------- #
#  Fixtures                                                                    #
# --------------------------------------------------------------------------- #

def _opt_result():
    tickers = [
        SimpleNamespace(symbol="AAPL", weight_pct=40.0, sector="Technology",
                        tailwind_classification="Neutral", tailwind_score=0.0),
        SimpleNamespace(symbol="VIST", weight_pct=35.0, sector="Energy",
                        tailwind_classification="Strong", tailwind_score=8.0),
        SimpleNamespace(symbol="JNJ", weight_pct=25.0, sector="Healthcare",
                        tailwind_classification="Neutral", tailwind_score=0.0),
    ]
    return SimpleNamespace(
        tickers=tickers,
        sector_weights={"Technology": 40.0, "Energy": 35.0, "Healthcare": 25.0},
        expected_return_pct=8.5, volatility_pct=16.0, sharpe_ratio=0.45,
        dividend_yield_pct=1.8, adjusted_score_avg=72.0, max_drawdown_estimate_pct=24.0,
        profile_name="Moderado",
    )


def _mc_result():
    return SimpleNamespace(
        prob_achieve_target_pct=82.0, median_terminal=500_000.0,
        p10_terminal=300_000.0, p90_terminal=900_000.0, median_cagr_pct=6.5,
        sorr_early_drawdown_pct=12.0, pct_paths_severe_drawdown=5.0,
    )


def _agent_json(stance, confidence="MEDIUM", key_points=None, concerns=None):
    return json.dumps({
        "stance": stance,
        "confidence": confidence,
        "key_points": key_points or ["punto clave"],
        "concerns": concerns or ["una preocupación"],
    }, ensure_ascii=False)


def make_fake(*, plan, risk, macro, devil):
    """Route the fake response by the role title embedded in each prompt."""
    def call_fn(prompt: str) -> str:
        if "Abogado del Diablo" in prompt:
            return devil
        if "Gestor de Riesgo" in prompt:
            return risk
        if "Estratega Macro" in prompt:
            return macro
        if "Estratega del Plan" in prompt:
            return plan
        return _agent_json("HOLD")
    return call_fn


# --------------------------------------------------------------------------- #
#  Concentration helper                                                        #
# --------------------------------------------------------------------------- #

def test_portfolio_concentration_basic():
    c = portfolio_concentration([40, 30, 20, 10])
    assert c["max_weight_pct"] == 40.0
    assert c["top3_weight_pct"] == 90.0
    assert c["effective_positions"] > 0


def test_portfolio_concentration_normalises_fractions():
    pct = portfolio_concentration([50, 50])
    frac = portfolio_concentration([0.5, 0.5])
    assert pct["max_weight_pct"] == frac["max_weight_pct"] == 50.0
    assert pct["effective_positions"] == frac["effective_positions"] == 2.0


def test_portfolio_concentration_empty():
    c = portfolio_concentration([])
    assert c["max_weight_pct"] == 0.0
    assert c["effective_positions"] == 0.0


# --------------------------------------------------------------------------- #
#  Context assembly                                                            #
# --------------------------------------------------------------------------- #

def test_build_context_has_expected_fields():
    ctx = build_portfolio_committee_context(
        opt_result=_opt_result(), mc_result=_mc_result(),
        goals=[{"name": "Retiro", "target_amount_today": 500_000, "horizon_years": 18}],
        stress_results=None, macro_context="", plan_name="Mi plan",
        profile_name="Moderado", horizon_years=18, target_value=500_000,
    )
    assert ctx["n_positions"] == 3
    assert ctx["expected_return_pct"] == 8.5
    assert ctx["prob_target_pct"] == 82.0
    assert ctx["max_weight_pct"] == 40.0
    # Only non-neutral tailwinds are surfaced.
    assert [t["symbol"] for t in ctx["tailwinds"]] == ["VIST"]
    assert ctx["top_holdings"][0]["symbol"] == "AAPL"
    assert ctx["goals"][0]["name"] == "Retiro"


def test_build_context_with_stress_results():
    worst = SimpleNamespace(
        scenario=SimpleNamespace(name="2008 — Crisis"),
        portfolio_drawdown_pct=-44.0, relative_performance_pct=12.0,
    )
    ctx = build_portfolio_committee_context(
        opt_result=_opt_result(), stress_results=[worst],
    )
    assert ctx["worst_crisis"]["name"] == "2008 — Crisis"
    assert ctx["worst_crisis"]["drawdown_pct"] == -44.0


# --------------------------------------------------------------------------- #
#  End-to-end with injected LLM                                                #
# --------------------------------------------------------------------------- #

def _ctx():
    return build_portfolio_committee_context(opt_result=_opt_result(), mc_result=_mc_result())


def test_analyze_portfolio_runs_four_agents():
    fake = make_fake(
        plan=_agent_json("BUY", "HIGH"),
        risk=_agent_json("HOLD", "MEDIUM"),
        macro=_agent_json("BUY", "MEDIUM"),
        devil=_agent_json("REDUCE", "MEDIUM", concerns=["concentración alta en AR"]),
    )
    analyzer = CommitteeAnalyzer(call_fn=fake, use_cache=False)
    v = analyzer.analyze_portfolio(_ctx(), plan_key="t")
    assert len(v.opinions) == 4
    roles = {o.role for o in v.opinions}
    assert roles == {"Estratega del Plan", "Gestor de Riesgo", "Estratega Macro", "Abogado del Diablo"}
    assert v.action in {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"}


def test_devil_dissent_always_surfaced_even_when_plan_is_solid():
    fake = make_fake(
        plan=_agent_json("STRONG BUY", "HIGH"),
        risk=_agent_json("BUY", "HIGH"),
        macro=_agent_json("BUY", "HIGH"),
        devil=_agent_json("BUY", "LOW", concerns=["el p10 es demasiado bajo"]),
    )
    analyzer = CommitteeAnalyzer(call_fn=fake, use_cache=False)
    v = analyzer.analyze_portfolio(_ctx(), plan_key="t")
    assert "el p10 es demasiado bajo" in v.dissent


def test_one_bad_agent_does_not_break_verdict():
    fake = make_fake(
        plan=_agent_json("BUY", "HIGH"),
        risk="no soy json",  # this agent fails to parse
        macro=_agent_json("BUY", "MEDIUM"),
        devil=_agent_json("HOLD", "LOW", concerns=["riesgo país"]),
    )
    analyzer = CommitteeAnalyzer(call_fn=fake, use_cache=False)
    v = analyzer.analyze_portfolio(_ctx(), plan_key="t")
    bad = next(o for o in v.opinions if o.role == "Gestor de Riesgo")
    assert bad.ok is False
    assert v.action in {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"}


def test_portfolio_action_labels_mapping():
    assert COMMITTEE.portfolio_action_labels["HOLD"] == "Mantener con ajustes"
    assert COMMITTEE.portfolio_action_labels["SELL"] == "Reestructurar"
    assert COMMITTEE.portfolio_action_labels["STRONG BUY"] == "Plan muy sólido"


# --------------------------------------------------------------------------- #
#  Holdings (actual portfolio) context                                         #
# --------------------------------------------------------------------------- #

def _metrics():
    return SimpleNamespace(
        num_positions=4, total_value=120_000.0, annualized_return_pct=9.2,
        total_pnl_pct=18.0, sharpe_ratio=0.6, downside_vol_ratio=0.8,
        max_drawdown_pct=-22.0, beta=1.1,
    )


def test_build_holdings_context_realized_and_concentration():
    ctx = build_holdings_committee_context(
        metrics=_metrics(),
        sector_weights={"Technology": 60.0, "Energy": 40.0},
        position_weights={"AAPL": 50.0, "MSFT": 30.0, "VIST": 20.0},
        total_value=120_000.0,
    )
    assert ctx["plan_name"] == "Tu portfolio actual"
    assert ctx["n_positions"] == 4
    assert ctx["realized"]["sharpe_ratio"] == 0.6
    assert ctx["realized"]["beta"] == 1.1
    assert ctx["max_weight_pct"] == 50.0
    assert ctx["top_holdings"][0]["symbol"] == "AAPL"
    # No forward-projection keys for the real book.
    assert "prob_target_pct" not in ctx


def test_build_holdings_context_includes_alignment():
    ctx = build_holdings_committee_context(
        metrics=_metrics(),
        sector_weights={"Technology": 100.0},
        position_weights={"AAPL": 100.0},
        total_value=50_000.0,
        active_plan_name="Mi retiro 2045",
        drift_pct=18.0,
        alignment_trades=[{"action": "vender", "symbol": "AAPL", "drift_pct": 18.0}],
    )
    assert ctx["alignment"]["plan_name"] == "Mi retiro 2045"
    assert ctx["alignment"]["drift_pct"] == 18.0
    assert ctx["alignment"]["trades"][0]["symbol"] == "AAPL"


def test_analyze_portfolio_over_holdings_context_surfaces_dissent():
    ctx = build_holdings_committee_context(
        metrics=_metrics(),
        sector_weights={"Technology": 60.0, "Energy": 40.0},
        position_weights={"AAPL": 50.0, "MSFT": 30.0, "VIST": 20.0},
        total_value=120_000.0,
        active_plan_name="Mi retiro", drift_pct=22.0,
    )
    fake = make_fake(
        plan=_agent_json("HOLD", "MEDIUM"),
        risk=_agent_json("REDUCE", "HIGH", concerns=["50% en una sola posición"]),
        macro=_agent_json("HOLD", "MEDIUM"),
        devil=_agent_json("REDUCE", "HIGH", concerns=["concentración peligrosa en tech"]),
    )
    v = CommitteeAnalyzer(call_fn=fake, use_cache=False).analyze_portfolio(ctx, plan_key="h")
    assert "concentración peligrosa en tech" in v.dissent
    assert v.action in {"HOLD", "REDUCE", "SELL"}
