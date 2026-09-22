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

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional

from loguru import logger

from analysis.committee_prompts import (
    behavioral_coach_prompt,
    devils_advocate_portfolio_prompt,
    devils_advocate_prompt,
    dividend_capital_prompt,
    macro_strategist_portfolio_prompt,
    macro_strategist_prompt,
    plan_strategist_prompt,
    portfolio_manager_prompt,
    risk_manager_portfolio_prompt,
    sector_stress_shocks,
)
from analysis.strategy import Decision
from analysis.utils import extract_json_object
from config import AI_FALLBACK, COMMITTEE

# Stance vocabulary shared with Decision.action.
_STANCE_SCORE = {"STRONG BUY": 2.0, "BUY": 1.0, "HOLD": 0.0, "REDUCE": -1.0, "SELL": -2.0}
_CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_RANK_CONFIDENCE = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}

LLMCall = Callable[[str], str]

#: Vote key of the dividend voice (its prompt title is the longer DIVIDEND_ROLE).
DIVIDEND_VOTE_ROLE = "Analista de Dividendo"

_RETRY_IN_SECONDS = re.compile(r"try again in ([0-9.]+)\s*s", re.IGNORECASE)


def _is_rate_limit(exc: BaseException) -> bool:
    from analysis.ai_analyzer import classify_ai_failure

    return classify_ai_failure(exc) == AI_FALLBACK.RATE_LIMIT


def _retry_after_seconds(exc: BaseException) -> float:
    """Seconds to wait after a 429. Prefers the header, then Groq's body text."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    raw = None
    if hasattr(headers, "get"):
        raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    match = _RETRY_IN_SECONDS.search(str(exc))
    if match:
        return max(0.0, float(match.group(1)))
    return float(COMMITTEE.rate_limit_backoff_seconds)


@dataclass
class AgentOpinion:
    role: str
    stance: str
    confidence: str
    key_points: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    error: str = ""
    error_cause: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.error_cause and self.stance in _STANCE_SCORE


@dataclass
class CommitteeVerdict:
    symbol: str
    action: str
    confidence: str
    consensus_points: List[str]
    dissent: List[str]
    opinions: List[AgentOpinion]
    lean: float = 0.0
    #: Share (%) of the convened vote weight that actually voted. Defaults to
    #: "quorum met" because ``_verdict_from_dict`` does not deserialise it: a
    #: cache hit must not come back looking like a failed panel.
    quorum_pct: float = 100.0

    @property
    def available(self) -> bool:
        """Whether enough of the panel voted for there to be a verdict at all.

        One valid opinion is not a committee. The per-role weights are calibrated
        as a *share* of the total (the Devil's Advocate is ~14 % of the lean by
        design), so a decimated panel would publish one agent's standing mandate
        under the committee's name — and the DA's mandate is bearish by
        construction. ``COMMITTEE.min_quorum_weight_pct`` is the floor.
        """
        if not any(o.ok for o in self.opinions):
            return False
        return self.quorum_pct >= COMMITTEE.min_quorum_weight_pct

    @property
    def failure_causes(self) -> List[str]:
        """Safe, classified causes for failed agents, preserving panel order."""
        return _dedupe([o.error_cause or AI_FALLBACK.OTRO for o in self.opinions if not o.ok])

    @property
    def complete(self) -> bool:
        """True only when every agent returned a parseable vote (no ``error``)."""
        return bool(self.opinions) and all(o.ok for o in self.opinions)

    @property
    def unreasoned_roles(self) -> List[str]:
        """Roles that voted without offering a single reason (no points, no concerns).

        NOT a failure: the stance is legible, so the vote is real and keeps its
        weight in the quorum — excluding it would change the lean to fix what is
        a presentation problem, and a model that is systematically terse would
        take the whole panel below ``min_quorum_weight_pct``. But a verdict built
        only on these is not an *argued* verdict, and the consensus/dissent boxes
        come back empty for a reason the UI must not confuse with disagreement.
        """
        return [
            o.role for o in self.opinions
            if o.ok and not any(t.strip() for t in (*o.key_points, *o.concerns))
        ]

    @property
    def devil_silent(self) -> bool:
        """The Devil's Advocate voted but named no concern.

        The panel's one hard guarantee is that the bear case is always surfaced
        (see the module docstring). When the DA returns no ``concerns`` the
        guarantee produces nothing, and because the vote itself is valid nothing
        else in the pipeline registers it.
        """
        devil = next((o for o in self.opinions if o.ok and o.role == "Abogado del Diablo"), None)
        # `any(...)` and not `not devil.concerns`: ``concerns=[""]`` is prose only
        # in form — ``_dedupe`` drops it, so the dissent box ends up empty anyway.
        return devil is not None and not any(c.strip() for c in devil.concerns)

    def to_decision(self, fund=None, tech=None) -> Decision:
        """Map the verdict into a standard Decision (numbers stay deterministic)."""
        if not self.available:
            raise ValueError("Committee verdict unavailable: no valid AI opinions")
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


def _failed_opinion(role: str, exc: BaseException) -> AgentOpinion:
    """Retain the failure category, never an SDK exception containing credentials."""
    from analysis.ai_analyzer import classify_ai_failure

    cause = classify_ai_failure(exc)
    logger.warning(f"committee agent {role} failed — cause={cause}")
    return AgentOpinion(role=role, stance="HOLD", confidence="LOW", error=cause, error_cause=cause)


# --------------------------------------------------------------------------- #
#  Parsing                                                                    #
# --------------------------------------------------------------------------- #

def _invalid_vote(role: str, field: str, raw_value) -> AgentOpinion:
    """A vote outside the stance vocabulary is a FAILED agent, not a neutral one.

    Coercing it to HOLD used to return ``ok=True``, so the vote entered the
    weighted average with its full weight and a score of 0.0: a formatting slip
    by the model dragged the lean toward the centre, ``complete`` stayed True,
    and the verdict was cached for 24 h and written to the track record with no
    signal that anything had failed. Excluding it instead renormalises the lean
    over the agents that really voted — the same rule ``_pays_dividend`` already
    applies to the dividend voice (an unconvened voice leaves the lean untouched;
    a forced HOLD dilutes it).
    """
    logger.warning(
        f"committee agent {role}: vote rejected — {field}={str(raw_value)[:40]!r} "
        f"is outside the stance vocabulary"
    )
    return AgentOpinion(
        role=role, stance="HOLD", confidence="LOW",
        error=AI_FALLBACK.JSON_INVALIDO, error_cause=AI_FALLBACK.JSON_INVALIDO,
    )


def _coerced_confidence(role: str, raw_value) -> str:
    """``confidence`` does not enter the lean, so a bad label never voids a vote."""
    confidence = str(raw_value).upper().strip() if raw_value is not None else "MEDIUM"
    if confidence in _CONFIDENCE_RANK:
        return confidence
    if raw_value is not None:
        logger.warning(
            f"committee agent {role}: confidence={str(raw_value)[:40]!r} unknown — using MEDIUM"
        )
    return "MEDIUM"


def _parse_agent(role: str, raw: str) -> AgentOpinion:
    try:
        data = extract_json_object(raw)
    except Exception as exc:
        return _failed_opinion(role, exc)
    raw_stance = data.get("stance")
    stance = str(raw_stance).upper().strip()
    if stance not in _STANCE_SCORE:
        return _invalid_vote(role, "stance", raw_stance)
    confidence = _coerced_confidence(role, data.get("confidence"))
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
        return _failed_opinion(role, exc)
    raw_action = data.get("action")
    stance = str(raw_action).upper().strip()
    if stance not in _STANCE_SCORE:
        return _invalid_vote(role, "action", raw_action)
    confidence = _coerced_confidence(role, data.get("confidence"))
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


def aggregate(
    symbol: str,
    opinions: List[AgentOpinion],
    *,
    weights: Optional[dict] = None,
    data_quality: Optional[dict] = None,
) -> CommitteeVerdict:
    """Combine agent opinions into a verdict with explicit, always-present dissent.

    ``weights`` overrides the per-role vote weights (e.g. the portfolio committee
    passes ``COMMITTEE.portfolio_vote_weights``); defaults to the per-ticker set.
    ``data_quality`` (``fund.data_quality``) only moves the confidence: stale or
    thin data drops it one notch, never the lean or the action.
    """
    weights = weights or COMMITTEE.vote_weights
    valid = [o for o in opinions if o.ok]

    # Weighted lean across the agents that voted. The denominator is the weight
    # that voted, not the weight convened: an agent that failed is EXCLUDED, not
    # counted as a zero — counting it would drag every lean toward HOLD.
    num = 0.0
    den = 0.0
    for o in valid:
        w = float(weights.get(o.role, 0.5))
        num += w * _STANCE_SCORE[o.stance]
        den += w
    convened = sum(float(weights.get(o.role, 0.5)) for o in opinions)
    quorum_pct = round(100.0 * den / convened, 2) if convened else 0.0

    if not valid or quorum_pct < COMMITTEE.min_quorum_weight_pct:
        if valid:
            logger.warning(
                f"committee[{symbol}]: quorum {quorum_pct:.0f}% < "
                f"{COMMITTEE.min_quorum_weight_pct:.0f}% — no verdict "
                f"(lean of the surviving {len(valid)} would have been {num / den:+.4f})"
            )
        return CommitteeVerdict(
            symbol=symbol, action="UNAVAILABLE", confidence="LOW",
            consensus_points=[], dissent=[], opinions=opinions,
            quorum_pct=quorum_pct,
        )

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
    if _data_quality_degraded(data_quality):
        base_conf_rank = max(0, base_conf_rank - 1)
    confidence = _RANK_CONFIDENCE[base_conf_rank]

    # De-duplicate while preserving order.
    consensus_points = _dedupe(consensus_points)
    dissent = _dedupe(dissent)

    # The bear case is the panel's one hard guarantee, and a DA that votes without
    # naming a concern defeats it without failing: the vote is valid, so `complete`
    # stays True and `failures=` sees nothing. Checked AFTER _dedupe, which drops
    # empty strings — concerns=[""] reaches here as no dissent at all. Leaves a
    # trace only: the stance was legible, so the lean is untouched.
    if devil and not dissent:
        logger.warning(
            f"committee[{symbol}]: el Abogado del Diablo votó ({devil.stance}) sin fundamentar "
            f"el bear case — dictamen sin disenso"
        )

    return CommitteeVerdict(
        symbol=symbol, action=action, confidence=confidence,
        consensus_points=consensus_points, dissent=dissent,
        opinions=opinions, lean=round(lean, 4), quorum_pct=quorum_pct,
    )


def counterfactual_verdict(verdict: CommitteeVerdict, role: str, stance: str) -> CommitteeVerdict:
    """The verdict the same panel would have produced had ``role`` voted ``stance``.

    Pure what-if over the deterministic aggregation: no AI call, no new numbers.
    Only a valid opinion is swapped — a failed agent stays failed, so the quorum
    is the original one. ``verdict`` is not mutated.
    """
    opinions = [
        replace(o, stance=stance) if o.role == role and o.ok else o
        for o in verdict.opinions
    ]
    return aggregate(verdict.symbol, opinions)


def _data_quality_flags(dq: Optional[dict]) -> Optional[tuple]:
    """(stale, too_many_missing) from ``fund.data_quality``; None when absent."""
    if not isinstance(dq, dict):
        return None
    try:
        n_missing = int(dq.get("n_missing") or 0)
    except (TypeError, ValueError):
        n_missing = 0
    return bool(dq.get("stale")), n_missing >= COMMITTEE.data_quality_downgrade_missing_fields


def _data_quality_degraded(dq: Optional[dict]) -> bool:
    flags = _data_quality_flags(dq)
    return bool(flags and any(flags))


def _data_quality_variant(dq: Optional[dict]) -> str:
    """Cache-key suffix: a verdict whose confidence saw one quality bucket must
    not be served for another. Empty when there is no quality info."""
    flags = _data_quality_flags(dq)
    if flags is None:
        return ""
    stale, thin = flags
    return f"dq:s{int(stale)}m{int(thin)}"


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


def _pays_dividend(fund) -> bool:
    """The dividend voice only votes when there is a dividend to judge.

    Crypto and non-payers abstain: an unconvened voice leaves the lean untouched,
    whereas a forced HOLD would dilute it toward zero.
    """
    if bool(getattr(fund, "is_crypto", False)):
        return False
    try:
        yld = float(getattr(fund, "dividend_yield", None) or 0.0)
    except (TypeError, ValueError):
        return False
    return yld > COMMITTEE.dividend_voice_min_yield_pct


def build_ticker_portfolio_context(
    symbol: str,
    sector: str,
    *,
    position_weights=None,
    sector_weights=None,
    active_plan=None,
) -> Optional[dict]:
    """The investor's real book as seen from ONE ticker, for the Portfolio Manager.

    Pure: weights come from the tracker (the caller already has them), drift goes
    through the canonical ``drift_breakdown`` and the sector shocks are the
    config constants of the stress test — nothing is recomputed or fetched.
    Returns None for an empty book, so the PM prompt stays byte-identical.
    """
    pw = {str(k).upper(): float(v or 0.0) for k, v in (position_weights or {}).items()}
    if not pw:
        return None
    sym = (symbol or "").upper()
    sw = dict(sector_weights or {})
    ctx: dict = {
        "symbol": sym,
        "sector": sector or "",
        "weight_pct": round(pw.get(sym, 0.0), 1),
        "sector_weight_pct": round(float(sw.get(sector, 0.0) or 0.0), 1),
    }

    if active_plan is not None:
        try:
            from data.plan_context import drift_breakdown

            target = {str(k).upper(): v for k, v in (active_plan.target_weights() or {}).items()}
            row = next(r for r in drift_breakdown(target, pw)["rows"] if r["symbol"] == sym)
            ctx["plan_name"] = getattr(active_plan, "name", "")
            ctx["plan_target_pct"] = round(row["target_pct"], 1)
            ctx["drift_pct"] = round(row["drift_pct"], 1)
        except StopIteration:
            pass  # neither held nor in the plan — no drift to report
        except Exception as exc:  # pragma: no cover - plan data is best-effort
            logger.debug(f"committee[{sym}]: plan drift skipped — {exc}")

    ctx["sector_shocks"] = sector_stress_shocks(sector)
    return ctx


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

def _ticker_news(symbol: str) -> list:
    """yfinance headlines for the Devil's Advocate (#130 paso 7); ``[]`` on any failure.

    Not part of the cache key: headlines move within the 24 h verdict TTL, and
    a verdict built on this morning's news is still a valid verdict.
    """
    from config import NEWS

    if not NEWS.enabled:
        return []
    try:
        from data.fetcher import get_news

        return get_news(symbol)
    except Exception as exc:
        logger.debug(f"committee[{symbol}]: news fetch failed — {exc}")
        return []


def _ticker_drawdowns(symbol: str) -> dict:
    """The asset's own worst drawdowns for the Devil's Advocate; ``{}`` on any failure.

    Reads the same weekly 10y history ``analysis.technical`` already cached, so
    it is normally a cache hit. Not part of the cache key, like the headlines.
    """
    if not COMMITTEE.drawdown_enabled:
        return {}
    try:
        from analysis.committee_prompts import price_drawdowns
        from data.fetcher import get_history

        hist = get_history(symbol, period="10y", interval="1wk")
        if hist is None or hist.empty or "close" not in hist:
            return {}
        return price_drawdowns(hist["close"], COMMITTEE.drawdown_windows_years)
    except Exception as exc:
        logger.debug(f"committee[{symbol}]: drawdowns skipped — {exc}")
        return {}


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
        if max_workers is not None:
            self._max_workers = max_workers
        elif getattr(ai_config, "provider", "") == "groq":
            self._max_workers = COMMITTEE.groq_max_workers
        else:
            self._max_workers = COMMITTEE.max_workers
        self._use_cache = use_cache

    @staticmethod
    def _make_api_call_fn(ai_config) -> LLMCall:
        from analysis.ai_analyzer import AIAnalyzer

        analyzer = AIAnalyzer(ai_config)

        def _call(prompt: str) -> str:
            # Without the pre-flight a missing key reaches the transport, whose
            # "No credentials found" is string-matched as key_invalida — the UI
            # then asks the user to fix a key they never set.
            analyzer._preflight()
            return analyzer._call_api(prompt, max_tokens=COMMITTEE.max_tokens)

        return _call

    def analyze(self, fund, tech, portfolio_ctx: Optional[dict] = None) -> CommitteeVerdict:
        """``portfolio_ctx`` (from ``build_ticker_portfolio_context``) reaches only the PM."""
        symbol = fund.symbol
        dq = getattr(fund, "data_quality", None)
        variant = ":".join(
            p for p in (_portfolio_variant(portfolio_ctx), _data_quality_variant(dq)) if p
        )
        if self._use_cache:
            cached = self._get_cached(symbol, variant)
            if cached is not None:
                logger.info(f"committee[{symbol}]: cache hit")
                return cached

        # role -> (prompt, parser)
        from analysis.prompts import crypto_decision_prompt, equity_decision_prompt

        # Fase 3B — dated macro context (RAG) for the Macro Strategist and,
        # since #130 paso 4, the Fundamental Analyst too.
        try:
            from analysis.macro_rag import macro_context_for

            macro_ctx = macro_context_for(fund)
        except Exception:
            macro_ctx = ""

        is_crypto = bool(getattr(fund, "is_crypto", False))
        news = [] if is_crypto else _ticker_news(symbol)
        drawdowns = _ticker_drawdowns(symbol)
        if is_crypto:
            fundamental_prompt = crypto_decision_prompt(fund, tech)
        else:
            fundamental_prompt = equity_decision_prompt(fund, tech, macro_ctx)

        jobs = {
            "Analista Fundamental": (fundamental_prompt, _parse_fundamental),
            "Estratega Macro": (macro_strategist_prompt(fund, tech, macro_ctx), lambda r: _parse_agent("Estratega Macro", r)),
            "Abogado del Diablo": (devils_advocate_prompt(fund, tech, news, drawdowns), lambda r: _parse_agent("Abogado del Diablo", r)),
            "Portfolio Manager": (portfolio_manager_prompt(fund, tech, portfolio_ctx), lambda r: _parse_agent("Portfolio Manager", r)),
            "Behavioral Coach": (behavioral_coach_prompt(fund, tech), lambda r: _parse_agent("Behavioral Coach", r)),
        }
        if _pays_dividend(fund):
            jobs[DIVIDEND_VOTE_ROLE] = (
                dividend_capital_prompt(fund, tech),
                lambda r: _parse_agent(DIVIDEND_VOTE_ROLE, r),
            )

        opinions = self._run_agents(jobs)
        verdict = aggregate(symbol, opinions, data_quality=dq)
        logger.info(
            f"committee[{symbol}]: {verdict.action} ({verdict.confidence}) lean={verdict.lean} "
            f"dissent={len(verdict.dissent)} complete={verdict.complete} "
            f"quorum={verdict.quorum_pct:.0f}% failures={verdict.failure_causes}"
        )
        if self._use_cache and verdict.complete:
            self._set_cached(symbol, verdict, variant)
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
            f"lean={verdict.lean} dissent={len(verdict.dissent)} complete={verdict.complete} "
            f"quorum={verdict.quorum_pct:.0f}% failures={verdict.failure_causes}"
        )
        if self._use_cache and verdict.complete:
            self._set_cached(cache_symbol, verdict)
        return verdict

    def _run_agents(self, jobs: Dict[str, tuple]) -> List[AgentOpinion]:
        def _one(role_job):
            role, (prompt, parser) = role_job
            attempts = 1 + max(0, COMMITTEE.rate_limit_retries)
            last_exc: Optional[BaseException] = None
            for attempt in range(attempts):
                try:
                    raw = self._call_fn(prompt)
                    return parser(raw)
                except Exception as exc:
                    last_exc = exc
                    if attempt + 1 < attempts and _is_rate_limit(exc):
                        wait = _retry_after_seconds(exc)
                        logger.warning(
                            f"committee agent {role} rate-limited "
                            f"(attempt {attempt + 1}/{attempts}); retry in {wait:.1f}s"
                        )
                        time.sleep(wait)
                        continue
                    return _failed_opinion(role, exc)
            return _failed_opinion(role, last_exc or RuntimeError("AI request failed"))

        workers = max(1, min(self._max_workers, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_one, jobs.items()))
        return results

    # ----- caching ----------------------------------------------------- #

    def _cache_key(self, symbol: str, variant: str = "") -> str:
        prov = getattr(self._ai_config, "provider", "inj")
        model = getattr(self._ai_config, "model", "inj")
        # The prompt version invalidates verdicts built by an older prompt.
        key = f"committee:{symbol}:{prov}:{model}:v{COMMITTEE.prompt_version}"
        return f"{key}:{variant}" if variant else key

    def _get_cached(self, symbol: str, variant: str = "") -> Optional[CommitteeVerdict]:
        try:
            from data.cache import cache

            payload = cache.get(self._cache_key(symbol, variant))
            if not payload:
                return None
            return _verdict_from_dict(payload)
        except Exception:
            return None

    def _set_cached(self, symbol: str, verdict: CommitteeVerdict, variant: str = "") -> None:
        try:
            from data.cache import cache

            cache.set(self._cache_key(symbol, variant), _verdict_to_dict(verdict))
        except Exception as exc:
            logger.debug(f"committee cache set skipped — {exc}")


def _portfolio_variant(portfolio_ctx: Optional[dict]) -> str:
    """Cache-key suffix: a verdict built on one book must not be served for another."""
    if not portfolio_ctx:
        return ""
    import hashlib
    import json

    digest = hashlib.md5(json.dumps(portfolio_ctx, sort_keys=True, default=str).encode()).hexdigest()
    return f"pf:{digest[:12]}"


def _verdict_to_dict(v: CommitteeVerdict) -> dict:
    return {
        "symbol": v.symbol, "action": v.action, "confidence": v.confidence,
        "consensus_points": v.consensus_points, "dissent": v.dissent, "lean": v.lean,
        "opinions": [
            {"role": o.role, "stance": o.stance, "confidence": o.confidence,
             "key_points": o.key_points, "concerns": o.concerns, "error": o.error,
             "error_cause": o.error_cause}
            for o in v.opinions
        ],
    }


def _verdict_from_dict(d: dict) -> CommitteeVerdict:
    opinions = [
        AgentOpinion(
            role=o.get("role", ""), stance=o.get("stance", "HOLD"),
            confidence=o.get("confidence", "MEDIUM"),
            key_points=o.get("key_points", []), concerns=o.get("concerns", []),
            error=o.get("error", ""), error_cause=o.get("error_cause", ""),
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
