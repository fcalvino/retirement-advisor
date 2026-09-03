"""
Multi-agent investment committee (Gran Salto — Fase 2B).

Replaces the single-shot AI call with a panel of specialised agents that debate
and produce a verdict with **explicit dissent**. The Devil's Advocate always
builds the bear case, so disagreement is auditable rather than smoothed over —
exactly the conservative philosophy of the product ("que el inversor no se
arruine").

Design:
  - Each agent calls an injectable ``call_fn(prompt) -> raw_json_str``. In
    production this wraps the multi-provider ``AIAnalyzer._call_api``; in tests a
    fake is injected, so the whole committee runs with no network.
  - Agents run in parallel via a thread pool (threads, NOT asyncio — the project
    is synchronous per its coding guidelines).
  - Aggregation is **deterministic**: stances map to a numeric lean, a weighted
    vote yields the action, and the bear case is always surfaced as dissent. No
    extra non-deterministic LLM "synthesis" step to audit.
  - The verdict maps to a standard ``Decision`` (``to_decision``) so it slots into
    the existing flow, the eval harness and the track record (source="committee").

Conventions: thresholds/weights from ``config.COMMITTEE``; loguru; verdict cached
in the shared SQLite cache (the committee is reserved for weighty decisions).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from loguru import logger

from analysis.committee_prompts import (
    behavioral_coach_prompt,
    devils_advocate_portfolio_prompt,
    devils_advocate_prompt,
    macro_strategist_portfolio_prompt,
    macro_strategist_prompt,
    plan_strategist_prompt,
    portfolio_manager_prompt,
    risk_manager_portfolio_prompt,
)
from analysis.strategy import Decision
from analysis.utils import extract_json_object
from config import COMMITTEE

# Stance vocabulary shared with Decision.action.
_STANCE_SCORE = {"STRONG BUY": 2.0, "BUY": 1.0, "HOLD": 0.0, "REDUCE": -1.0, "SELL": -2.0}
_CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_RANK_CONFIDENCE = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}

LLMCall = Callable[[str], str]


@dataclass
class AgentOpinion:
    role: str
    stance: str
    confidence: str
    key_points: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.stance in _STANCE_SCORE


@dataclass
class CommitteeVerdict:
    symbol: str
    action: str
    confidence: str
    consensus_points: List[str]
    dissent: List[str]
    opinions: List[AgentOpinion]
    lean: float = 0.0

    def to_decision(self, fund=None, tech=None) -> Decision:
        """Map the verdict into a standard Decision (numbers stay deterministic)."""
        score = 0.0
        signal = ""
        mos = False
        if fund is not None:
            is_crypto = bool(getattr(fund, "is_crypto", False))
            score = getattr(fund, "adjusted_score", 0.0) if is_crypto else getattr(fund, "total_score", 0.0)
            try:
                mos = bool(fund.is_value_stock())
            except Exception:
                mos = False
        if tech is not None:
            signal = getattr(tech, "signal", "")

        reasoning = self._debate_summary()
        return Decision(
            symbol=self.symbol,
            action=self.action,
            confidence=self.confidence,
            fundamental_score=score,
            technical_signal=signal,
            has_margin_of_safety=mos,
            rationale=list(self.consensus_points),
            risks=list(self.dissent),
            ai_reasoning=reasoning,
        )

    def _debate_summary(self) -> str:
        parts = [f"Dictamen del comité: {self.action} (confianza {self.confidence})."]
        for op in self.opinions:
            if op.ok:
                parts.append(f"· {op.role}: {op.stance} ({op.confidence}).")
        if self.dissent:
            parts.append("Disenso (bear case): " + " ".join(f"– {d}" for d in self.dissent))
        return "\n".join(parts)


# --------------------------------------------------------------------------- #
#  Parsing                                                                    #
# --------------------------------------------------------------------------- #

def _parse_agent(role: str, raw: str) -> AgentOpinion:
    try:
        data = extract_json_object(raw)
    except Exception as exc:
        return AgentOpinion(role=role, stance="HOLD", confidence="LOW", error=f"parse: {exc}")
    stance = str(data.get("stance", "HOLD")).upper().strip()
    if stance not in _STANCE_SCORE:
        stance = "HOLD"
    confidence = str(data.get("confidence", "MEDIUM")).upper().strip()
    if confidence not in _CONFIDENCE_RANK:
        confidence = "MEDIUM"
    key_points = [str(x) for x in (data.get("key_points") or [])]
    concerns = [str(x) for x in (data.get("concerns") or [])]
    return AgentOpinion(role=role, stance=stance, confidence=confidence,
                        key_points=key_points, concerns=concerns)


def _parse_fundamental(raw: str) -> AgentOpinion:
    """The Fundamental Analyst reuses the production equity_decision_prompt schema."""
    role = "Analista Fundamental"
    try:
        data = extract_json_object(raw)
    except Exception as exc:
        return AgentOpinion(role=role, stance="HOLD", confidence="LOW", error=f"parse: {exc}")
    stance = str(data.get("action", "HOLD")).upper().strip()
    if stance not in _STANCE_SCORE:
        stance = "HOLD"
    confidence = str(data.get("confidence", "MEDIUM")).upper().strip()
    if confidence not in _CONFIDENCE_RANK:
        confidence = "MEDIUM"
    return AgentOpinion(
        role=role, stance=stance, confidence=confidence,
        key_points=[str(x) for x in (data.get("rationale") or [])],
        concerns=[str(x) for x in (data.get("risks") or [])],
    )


# --------------------------------------------------------------------------- #
#  Aggregation (deterministic)                                                #
# --------------------------------------------------------------------------- #

def _lean_to_action(lean: float) -> str:
    c = COMMITTEE
    if lean >= c.strong_buy_lean:
        return "STRONG BUY"
    if lean >= c.buy_lean:
        return "BUY"
    if lean <= c.sell_lean:
        return "SELL"
    if lean <= c.reduce_lean:
        return "REDUCE"
    return "HOLD"


def aggregate(symbol: str, opinions: List[AgentOpinion], *, weights: Optional[dict] = None) -> CommitteeVerdict:
    """Combine agent opinions into a verdict with explicit, always-present dissent.

    ``weights`` overrides the per-role vote weights (e.g. the portfolio committee
    passes ``COMMITTEE.portfolio_vote_weights``); defaults to the per-ticker set.
    """
    weights = weights or COMMITTEE.vote_weights
    valid = [o for o in opinions if o.ok]

    # Weighted lean across the agents that voted.
    num = 0.0
    den = 0.0
    for o in valid:
        w = float(weights.get(o.role, 0.5))
        num += w * _STANCE_SCORE[o.stance]
        den += w
    lean = (num / den) if den else 0.0
    action = _lean_to_action(lean)

    # Consensus points: from the agents that agree with the final direction.
    final_score = _STANCE_SCORE[action]
    consensus_points: List[str] = []
    for o in valid:
        same_side = (
            (final_score > 0 and _STANCE_SCORE[o.stance] > 0)
            or (final_score < 0 and _STANCE_SCORE[o.stance] < 0)
            or (final_score == 0 and _STANCE_SCORE[o.stance] == 0)
        )
        if same_side:
            consensus_points.extend(o.key_points[:2])

    # Dissent: the Devil's Advocate concerns are ALWAYS included, plus any agent
    # whose stance disagrees with the final direction.
    dissent: List[str] = []
    devil = next((o for o in valid if o.role == "Abogado del Diablo"), None)
    if devil:
        dissent.extend(devil.concerns[:3])
    for o in valid:
        if o.role == "Abogado del Diablo":
            continue
        disagrees = _STANCE_SCORE[o.stance] * final_score < 0  # opposite signs
        if disagrees:
            label = f"{o.role} discrepa ({o.stance})"
            detail = o.concerns[0] if o.concerns else (o.key_points[0] if o.key_points else "")
            dissent.append(f"{label}: {detail}" if detail else label)

    # Confidence: start from the Fundamental Analyst (or median), downgrade on
    # strong dissent — the conservative bias.
    base = next((o for o in valid if o.role == "Analista Fundamental"), None)
    base_conf_rank = _CONFIDENCE_RANK.get(base.confidence, 1) if base else 1
    strong_dissent = bool(
        devil and (devil.confidence == "HIGH" or _STANCE_SCORE.get(devil.stance, 0) <= -1.0)
    )
    spread = _stance_spread(valid)
    if COMMITTEE.downgrade_confidence_on_strong_dissent and (strong_dissent or spread >= 2.0):
        base_conf_rank = max(0, base_conf_rank - 1)
    confidence = _RANK_CONFIDENCE[base_conf_rank]

    # De-duplicate while preserving order.
    consensus_points = _dedupe(consensus_points)
    dissent = _dedupe(dissent)

    return CommitteeVerdict(
        symbol=symbol, action=action, confidence=confidence,
        consensus_points=consensus_points, dissent=dissent,
        opinions=opinions, lean=round(lean, 4),
    )


def _stance_spread(opinions: List[AgentOpinion]) -> float:
    scores = [_STANCE_SCORE[o.stance] for o in opinions if o.ok]
    return (max(scores) - min(scores)) if scores else 0.0


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


# --------------------------------------------------------------------------- #
#  Portfolio-level context assembly (pure; no Streamlit, no network)          #
# --------------------------------------------------------------------------- #

def portfolio_concentration(weights: List[float]) -> dict:
    """Concentration metrics from a list of position weights.

    Robust to weights given as percentages (sum ~100) or fractions (sum ~1):
    they are normalised internally. Returns ``max_weight_pct``, ``top3_weight_pct``
    and ``effective_positions`` (1/HHI — "how many equally-sized names this is
    really worth").
    """
    ws = [float(w) for w in (weights or []) if w is not None and float(w) > 0]
    if not ws:
        return {"max_weight_pct": 0.0, "top3_weight_pct": 0.0, "effective_positions": 0.0}
    total = sum(ws)
    fracs = sorted((w / total for w in ws), reverse=True)
    hhi = sum(f * f for f in fracs)
    return {
        "max_weight_pct": round(fracs[0] * 100, 1),
        "top3_weight_pct": round(sum(fracs[:3]) * 100, 1),
        "effective_positions": round(1.0 / hhi, 1) if hhi > 0 else 0.0,
    }


def build_holdings_committee_context(
    *,
    metrics=None,
    sector_weights=None,
    position_weights=None,
    total_value=None,
    stress_results=None,
    macro_context: str = "",
    active_plan_name: str = "",
    drift_pct=None,
    alignment_trades=None,
) -> dict:
    """Normalise the ACTUAL portfolio (real holdings) into the committee facts dict.

    Pure: reads attributes/dicts defensively. Bases the verdict on realized risk,
    concentration, crisis resistance and drift vs the active plan — no forward
    projection (the real book has no Monte Carlo).
    """
    pw = dict(position_weights or {})
    conc = portfolio_concentration(list(pw.values()))
    top_holdings = sorted(
        ({"symbol": s, "weight_pct": float(w or 0.0)} for s, w in pw.items()),
        key=lambda h: h["weight_pct"], reverse=True,
    )

    ctx: dict = {
        "plan_name": "Tu portfolio actual",
        "n_positions": getattr(metrics, "num_positions", None) if metrics is not None else len(pw),
        "total_value": total_value if total_value is not None else getattr(metrics, "total_value", None),
        "sector_weights": dict(sector_weights or {}),
        "top_holdings": top_holdings,
        "max_weight_pct": conc["max_weight_pct"],
        "top3_weight_pct": conc["top3_weight_pct"],
        "effective_positions": conc["effective_positions"],
        "macro_context": macro_context or "",
    }

    if metrics is not None:
        ctx["realized"] = {
            "annualized_return_pct": getattr(metrics, "annualized_return_pct", None),
            "total_pnl_pct": getattr(metrics, "total_pnl_pct", None),
            "sharpe_ratio": getattr(metrics, "sharpe_ratio", None),
            "downside_vol_ratio": getattr(metrics, "downside_vol_ratio", None),
            "max_drawdown_pct": getattr(metrics, "max_drawdown_pct", None),
            "beta": getattr(metrics, "beta", None),
        }

    if stress_results:
        worst = stress_results[0]
        ctx["worst_crisis"] = {
            "name": getattr(getattr(worst, "scenario", None), "name", ""),
            "drawdown_pct": getattr(worst, "portfolio_drawdown_pct", None),
            "vs_spy_pct": getattr(worst, "relative_performance_pct", None),
        }
        ctx["stress_scenarios"] = [
            {
                "name": getattr(getattr(s, "scenario", None), "name", ""),
                "drawdown_pct": getattr(s, "portfolio_drawdown_pct", None),
            }
            for s in stress_results[:4]
        ]

    if active_plan_name or drift_pct is not None:
        ctx["alignment"] = {
            "plan_name": active_plan_name,
            "drift_pct": drift_pct,
            "trades": [
                {
                    "action": t.get("action"),
                    "symbol": t.get("symbol"),
                    "drift_pct": t.get("drift_pct"),
                }
                for t in (alignment_trades or [])[:5]
            ],
        }

    return ctx


def _goal_field(goal, key):
    return goal.get(key) if isinstance(goal, dict) else getattr(goal, key, None)


def build_portfolio_committee_context(
    *,
    opt_result,
    mc_result=None,
    goals=None,
    stress_results=None,
    macro_context: str = "",
    plan_name: str = "plan actual",
    profile_name: str = "",
    horizon_years=None,
    target_value=None,
) -> dict:
    """Normalise everything the committee may cite into a flat facts dict.

    Pure: reads attributes defensively so it does not couple to the exact
    dataclasses. Recomputes nothing expensive — values come from the optimizer,
    Monte Carlo, the (deterministic) stress test and tailwind fields already
    attached to the result.
    """
    tickers = list(getattr(opt_result, "tickers", []) or [])
    weights = [getattr(t, "weight_pct", 0.0) for t in tickers]
    conc = portfolio_concentration(weights)
    top_holdings = sorted(
        (
            {
                "symbol": getattr(t, "symbol", ""),
                "weight_pct": float(getattr(t, "weight_pct", 0.0) or 0.0),
                "sector": getattr(t, "sector", ""),
            }
            for t in tickers
        ),
        key=lambda h: h["weight_pct"], reverse=True,
    )
    tailwinds = [
        {
            "symbol": getattr(t, "symbol", ""),
            "classification": getattr(t, "tailwind_classification", "") or "",
            "score": float(getattr(t, "tailwind_score", 0.0) or 0.0),
        }
        for t in tickers
        if (getattr(t, "tailwind_classification", "") or "Neutral") not in ("", "Neutral")
    ]

    ctx: dict = {
        "plan_name": plan_name,
        "profile_name": profile_name or getattr(opt_result, "profile_name", ""),
        "n_positions": len(tickers),
        "horizon_years": horizon_years,
        "target_value": target_value,
        "expected_return_pct": getattr(opt_result, "expected_return_pct", None),
        "volatility_pct": getattr(opt_result, "volatility_pct", None),
        "sharpe_ratio": getattr(opt_result, "sharpe_ratio", None),
        "dividend_yield_pct": getattr(opt_result, "dividend_yield_pct", None),
        "adjusted_score_avg": getattr(opt_result, "adjusted_score_avg", None),
        "max_drawdown_estimate_pct": getattr(opt_result, "max_drawdown_estimate_pct", None),
        "sector_weights": dict(getattr(opt_result, "sector_weights", {}) or {}),
        "top_holdings": top_holdings,
        "max_weight_pct": conc["max_weight_pct"],
        "top3_weight_pct": conc["top3_weight_pct"],
        "effective_positions": conc["effective_positions"],
        "macro_context": macro_context or "",
    }

    if mc_result is not None:
        from data.product_ux import mc_has_cash_flows

        ctx.update({
            "prob_target_pct": getattr(mc_result, "prob_achieve_target_pct", None),
            "median_terminal": getattr(mc_result, "median_terminal", None),
            "p10_terminal": getattr(mc_result, "p10_terminal", None),
            "p90_terminal": getattr(mc_result, "p90_terminal", None),
            "median_cagr_pct": getattr(mc_result, "median_cagr_pct", None),
            # U1-7: sin este flag el prompt no puede decir si esa cifra es un
            # retorno o el crecimiento de un pozo alimentado por aportes. El
            # modelo razona sobre lo que la etiqueta nombra (lección de U1-3).
            "mc_has_cash_flows": mc_has_cash_flows(mc_result),
            "sorr_early_drawdown_pct": getattr(mc_result, "sorr_early_drawdown_pct", None),
            "pct_paths_severe_drawdown": getattr(mc_result, "pct_paths_severe_drawdown", None),
        })

    if stress_results:
        worst = stress_results[0]  # StressTester.run() returns worst-first
        ctx["worst_crisis"] = {
            "name": getattr(getattr(worst, "scenario", None), "name", ""),
            "drawdown_pct": getattr(worst, "portfolio_drawdown_pct", None),
            "vs_spy_pct": getattr(worst, "relative_performance_pct", None),
        }
        ctx["stress_scenarios"] = [
            {
                "name": getattr(getattr(s, "scenario", None), "name", ""),
                "drawdown_pct": getattr(s, "portfolio_drawdown_pct", None),
            }
            for s in stress_results[:4]
        ]

    if tailwinds:
        ctx["tailwinds"] = tailwinds

    if goals:
        ctx["goals"] = [
            {
                "name": _goal_field(gg, "name"),
                "target_amount_today": _goal_field(gg, "target_amount_today"),
                "horizon_years": _goal_field(gg, "horizon_years"),
            }
            for gg in goals
        ]

    return ctx


# --------------------------------------------------------------------------- #
#  Orchestrator                                                               #
# --------------------------------------------------------------------------- #

class CommitteeAnalyzer:
    """Runs the committee for a single asset and returns a verdict.

    ``call_fn`` is the injection seam: ``call_fn(prompt) -> raw_json_string``.
    When omitted, an ``ai_config`` must be supplied and the production
    multi-provider API call is used.
    """

    def __init__(self, call_fn: Optional[LLMCall] = None, *, ai_config=None,
                 max_workers: Optional[int] = None, use_cache: bool = True):
        if call_fn is None and ai_config is None:
            raise ValueError("CommitteeAnalyzer needs either call_fn or ai_config")
        self._call_fn = call_fn or self._make_api_call_fn(ai_config)
        self._ai_config = ai_config
        self._max_workers = max_workers or COMMITTEE.max_workers
        self._use_cache = use_cache

    @staticmethod
    def _make_api_call_fn(ai_config) -> LLMCall:
        from analysis.ai_analyzer import AIAnalyzer

        analyzer = AIAnalyzer(ai_config)
        return lambda prompt: analyzer._call_api(prompt, max_tokens=900)

    def analyze(self, fund, tech) -> CommitteeVerdict:
        symbol = fund.symbol
        if self._use_cache:
            cached = self._get_cached(symbol)
            if cached is not None:
                logger.info(f"committee[{symbol}]: cache hit")
                return cached

        # role -> (prompt, parser)
        from analysis.prompts import crypto_decision_prompt, equity_decision_prompt

        is_crypto = bool(getattr(fund, "is_crypto", False))
        fundamental_prompt = (crypto_decision_prompt if is_crypto else equity_decision_prompt)(fund, tech)

        # Fase 3B — inject dated macro context (RAG) into the Macro Strategist.
        try:
            from analysis.macro_rag import macro_context_for

            macro_ctx = macro_context_for(fund)
        except Exception:
            macro_ctx = ""

        jobs = {
            "Analista Fundamental": (fundamental_prompt, _parse_fundamental),
            "Estratega Macro": (macro_strategist_prompt(fund, tech, macro_ctx), lambda r: _parse_agent("Estratega Macro", r)),
            "Abogado del Diablo": (devils_advocate_prompt(fund, tech), lambda r: _parse_agent("Abogado del Diablo", r)),
            "Portfolio Manager": (portfolio_manager_prompt(fund, tech), lambda r: _parse_agent("Portfolio Manager", r)),
            "Behavioral Coach": (behavioral_coach_prompt(fund, tech), lambda r: _parse_agent("Behavioral Coach", r)),
        }

        opinions = self._run_agents(jobs)
        verdict = aggregate(symbol, opinions)
        logger.info(
            f"committee[{symbol}]: {verdict.action} ({verdict.confidence}) lean={verdict.lean} "
            f"dissent={len(verdict.dissent)}"
        )
        if self._use_cache:
            self._set_cached(symbol, verdict)
        return verdict

    def analyze_portfolio(self, ctx: dict, plan_key: str = "plan") -> CommitteeVerdict:
        """Run the committee over the WHOLE plan/portfolio (not a single ticker).

        ``ctx`` is the plain-facts dict from ``build_portfolio_committee_context``.
        Reuses the parallel runner, the deterministic aggregation (with the
        portfolio vote weights) and the SQLite cache. The verdict's ``action``
        uses the same stance vocabulary; the UI maps it to a plan-health label
        via ``COMMITTEE.portfolio_action_labels``.
        """
        cache_symbol = f"portfolio:{plan_key}"
        if self._use_cache:
            cached = self._get_cached(cache_symbol)
            if cached is not None:
                logger.info(f"committee[{cache_symbol}]: cache hit")
                return cached

        jobs = {
            "Estratega del Plan": (plan_strategist_prompt(ctx), lambda r: _parse_agent("Estratega del Plan", r)),
            "Gestor de Riesgo":   (risk_manager_portfolio_prompt(ctx), lambda r: _parse_agent("Gestor de Riesgo", r)),
            "Estratega Macro":    (macro_strategist_portfolio_prompt(ctx), lambda r: _parse_agent("Estratega Macro", r)),
            "Abogado del Diablo": (devils_advocate_portfolio_prompt(ctx), lambda r: _parse_agent("Abogado del Diablo", r)),
        }

        opinions = self._run_agents(jobs)
        verdict = aggregate(plan_key, opinions, weights=COMMITTEE.portfolio_vote_weights)
        logger.info(
            f"committee[{cache_symbol}]: {verdict.action} ({verdict.confidence}) "
            f"lean={verdict.lean} dissent={len(verdict.dissent)}"
        )
        if self._use_cache:
            self._set_cached(cache_symbol, verdict)
        return verdict

    def _run_agents(self, jobs: Dict[str, tuple]) -> List[AgentOpinion]:
        def _one(role_job):
            role, (prompt, parser) = role_job
            try:
                raw = self._call_fn(prompt)
                return parser(raw)
            except Exception as exc:
                logger.warning(f"committee agent {role} failed — {exc}")
                return AgentOpinion(role=role, stance="HOLD", confidence="LOW", error=str(exc))

        workers = max(1, min(self._max_workers, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_one, jobs.items()))
        return results

    # ----- caching ----------------------------------------------------- #

    def _cache_key(self, symbol: str) -> str:
        prov = getattr(self._ai_config, "provider", "inj")
        model = getattr(self._ai_config, "model", "inj")
        return f"committee:{symbol}:{prov}:{model}"

    def _get_cached(self, symbol: str) -> Optional[CommitteeVerdict]:
        try:
            from data.cache import cache

            payload = cache.get(self._cache_key(symbol))
            if not payload:
                return None
            return _verdict_from_dict(payload)
        except Exception:
            return None

    def _set_cached(self, symbol: str, verdict: CommitteeVerdict) -> None:
        try:
            from data.cache import cache

            cache.set(self._cache_key(symbol), _verdict_to_dict(verdict))
        except Exception as exc:
            logger.debug(f"committee cache set skipped — {exc}")


def _verdict_to_dict(v: CommitteeVerdict) -> dict:
    return {
        "symbol": v.symbol, "action": v.action, "confidence": v.confidence,
        "consensus_points": v.consensus_points, "dissent": v.dissent, "lean": v.lean,
        "opinions": [
            {"role": o.role, "stance": o.stance, "confidence": o.confidence,
             "key_points": o.key_points, "concerns": o.concerns, "error": o.error}
            for o in v.opinions
        ],
    }


def _verdict_from_dict(d: dict) -> CommitteeVerdict:
    opinions = [
        AgentOpinion(
            role=o.get("role", ""), stance=o.get("stance", "HOLD"),
            confidence=o.get("confidence", "MEDIUM"),
            key_points=o.get("key_points", []), concerns=o.get("concerns", []),
            error=o.get("error", ""),
        )
        for o in d.get("opinions", [])
    ]
    return CommitteeVerdict(
        symbol=d.get("symbol", ""), action=d.get("action", "HOLD"),
        confidence=d.get("confidence", "MEDIUM"),
        consensus_points=d.get("consensus_points", []), dissent=d.get("dissent", []),
        opinions=opinions, lean=d.get("lean", 0.0),
    )


# ------------------------------------------------------------------ #
#  Holdings committee — orchestration over the ACTUAL portfolio (O4)   #
# ------------------------------------------------------------------ #

def run_holdings_committee(
    *,
    metrics,
    sector_weights: dict[str, float],
    position_weights: dict[str, float],
    total_value: float,
    ai_config,
    stress_results=None,
    active_plan=None,
):
    """Convene the committee over the ACTUAL portfolio (real holdings).

    → ``CommitteeVerdict``, or ``None`` when AI is disabled.

    Interprets, does not recompute: reuses realized ``metrics`` from the tracker,
    the deterministic ``stress_results`` (the Streamlit layer passes the
    ``@st.cache_data`` result), drift vs the active plan
    (``compute_alignment_trades``) and dated macro context. Verdict caching is
    the committee's SQLite layer (keyed by a content hash of the holdings + AI
    provider/model).

    O4: moved here from ``dashboard/shared.py``, which keeps a thin wrapper that
    resolves ``ai_config`` and ``stress_results`` from the Streamlit layer.
    """
    if not getattr(ai_config, "enabled", False):
        return None

    sw = dict(sector_weights or {})
    stress_results = stress_results or []

    # Alignment vs the active plan ("deriva inteligente"), best-effort.
    active_plan_name = ""
    drift_pct = None
    alignment_trades = None
    if active_plan is not None:
        try:
            from data.plan_context import compute_alignment_trades, plan_price_lookup

            _al = compute_alignment_trades(
                active_plan, dict(position_weights or {}), float(total_value or 0.0),
                price_lookup=plan_price_lookup,
            )
            alignment_trades = _al.get("trades")
            drift_pct = (_al.get("summary") or {}).get("total_drift_pct")
            active_plan_name = getattr(active_plan, "name", "")
        except Exception:  # pragma: no cover - alignment is best-effort
            pass

    macro_context = ""
    try:
        from analysis.macro_rag import macro_rag_store

        macro_context = macro_rag_store.build_context(
            f"cartera de retiro {' '.join(sw.keys())} tasas inflación riesgo país"
        )
    except Exception:  # pragma: no cover - macro is best-effort
        macro_context = ""

    import hashlib

    sig = "|".join(
        f"{s}:{round(float(w or 0), 1)}" for s, w in sorted((position_weights or {}).items())
    )
    plan_key = hashlib.md5(sig.encode()).hexdigest()[:12]

    ctx = build_holdings_committee_context(
        metrics=metrics,
        sector_weights=sw,
        position_weights=position_weights,
        total_value=total_value,
        stress_results=stress_results,
        macro_context=macro_context,
        active_plan_name=active_plan_name,
        drift_pct=drift_pct,
        alignment_trades=alignment_trades,
    )
    return CommitteeAnalyzer(ai_config=ai_config).analyze_portfolio(ctx, plan_key=plan_key)
