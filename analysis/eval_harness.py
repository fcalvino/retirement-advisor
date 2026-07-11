"""
AI eval harness (Gran Salto — Fase 2A).

Scores the *quality* of AI investment decisions against the golden cases in
``analysis/eval_cases.py``. This is the prerequisite that lets the multi-agent
committee (Fase 2B) be improved without flying blind: change a prompt, re-run the
harness, see whether quality went up or down instead of guessing.

Pieces:
  - Checks: small pure functions, each asserting one quality property of a
    Decision (valid structure, expected action, deterministic scores, macro
    schema, conservative allocation cap, risks present / anti-complacency...).
  - Providers: ``ReplayProvider`` (deterministic, no API key — used in CI) and
    ``LiveProvider`` (calls the real multi-provider AIAnalyzer).
  - Runner + report: run every case through a provider, score it, aggregate.

Conventions: thresholds come from ``config.EVAL``; synchronous; loguru.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable, List, Optional

from loguru import logger

from analysis.ai_analyzer import AIAnalyzer
from analysis.eval_cases import GoldenCase, golden_cases
from analysis.strategy import Decision
from config import EVAL

VALID_ACTIONS = {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"}
VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
BULLISH_ACTIONS = {"STRONG BUY", "BUY"}


# --------------------------------------------------------------------------- #
#  Result models                                                              #
# --------------------------------------------------------------------------- #

@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    weight: float = 1.0


@dataclass
class CaseResult:
    case_id: str
    description: str
    action: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def score(self) -> float:
        total = sum(c.weight for c in self.checks)
        if total == 0:
            return 1.0
        got = sum(c.weight for c in self.checks if c.passed)
        return got / total

    @property
    def passed(self) -> bool:
        return self.score >= EVAL.case_pass_threshold

    @property
    def failures(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed]


@dataclass
class EvalReport:
    results: List[CaseResult]

    @property
    def n_cases(self) -> int:
        return len(self.results)

    @property
    def n_passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def suite_pass_rate(self) -> float:
        return self.n_passed / self.n_cases if self.n_cases else 1.0

    @property
    def is_green(self) -> bool:
        return self.suite_pass_rate >= EVAL.suite_pass_threshold

    def check_pass_rates(self) -> dict:
        """Pass rate per check name across all cases (diagnostic)."""
        names: dict[str, list] = {}
        for r in self.results:
            for c in r.checks:
                names.setdefault(c.name, []).append(c.passed)
        return {n: round(sum(v) / len(v), 4) for n, v in names.items() if v}


# --------------------------------------------------------------------------- #
#  Parsing                                                                    #
# --------------------------------------------------------------------------- #

# A single throwaway analyzer instance — _parse_response does not use config.
_PARSER = AIAnalyzer(SimpleNamespace(provider="replay", model="replay", enabled=False))


def parse_decision(raw: str, case: GoldenCase) -> Decision:
    """Parse a raw AI JSON response into a Decision using the production parser."""
    return _PARSER._parse_response(raw, case.fund, case.tech)


# --------------------------------------------------------------------------- #
#  Checks (each returns CheckResult, or None when not applicable)             #
# --------------------------------------------------------------------------- #

def check_valid_structure(case: GoldenCase, d: Decision) -> CheckResult:
    ok = d.action in VALID_ACTIONS and (d.confidence or "").upper() in VALID_CONFIDENCE
    return CheckResult(
        "valid_structure", ok,
        "" if ok else f"action={d.action!r} confidence={d.confidence!r}",
    )


def check_expected_action(case: GoldenCase, d: Decision) -> CheckResult:
    ok = d.action in case.expected_actions
    return CheckResult(
        "expected_action", ok,
        "" if ok else f"got {d.action!r}, expected one of {sorted(case.expected_actions)}",
    )


def check_no_forbidden_action(case: GoldenCase, d: Decision) -> Optional[CheckResult]:
    if not case.forbidden_actions:
        return None
    ok = d.action not in case.forbidden_actions
    return CheckResult(
        "no_forbidden_action", ok,
        "" if ok else f"{d.action!r} is forbidden for this case",
    )


def check_scores_deterministic(case: GoldenCase, d: Decision) -> CheckResult:
    """The numeric score must come from the engine, never the LLM.

    This is the concrete form of "la IA nunca inventa cifras": the parser is
    expected to stamp the deterministic fundamental score onto the Decision.
    """
    expected = case.fund.adjusted_score if getattr(case.fund, "is_crypto", False) else case.fund.total_score
    ok = abs(float(d.fundamental_score) - float(expected)) < 1e-6
    return CheckResult(
        "scores_deterministic", ok,
        "" if ok else f"score={d.fundamental_score} but engine={expected}",
    )


def check_reasoning_nonempty(case: GoldenCase, d: Decision) -> CheckResult:
    n = len((d.ai_reasoning or "").strip())
    ok = n >= EVAL.min_reasoning_chars
    return CheckResult(
        "reasoning_nonempty", ok,
        "" if ok else f"reasoning too short ({n} < {EVAL.min_reasoning_chars} chars)",
    )


def check_risks_present(case: GoldenCase, d: Decision) -> Optional[CheckResult]:
    """Risks must be listed when the case requires it, or for any BUY (anti-complacency)."""
    bullish = d.action in BULLISH_ACTIONS
    required = case.must_have_risks or (EVAL.require_risk_on_buy and bullish)
    if not required:
        return None
    ok = bool(d.risks)
    why = "anti-complacencia: un BUY debe nombrar riesgos" if bullish else "el caso exige riesgos"
    return CheckResult("risks_present", ok, "" if ok else f"sin riesgos ({why})")


def check_macro_schema(case: GoldenCase, d: Decision) -> CheckResult:
    factors = d.macro_factors or []
    if len(factors) > EVAL.max_macro_factors:
        return CheckResult("macro_schema", False, f"{len(factors)} factores > máx {EVAL.max_macro_factors}")
    required_keys = {"factor", "why_relevant", "impact", "effect_on_allocation_or_conviction"}
    for i, fct in enumerate(factors):
        if not isinstance(fct, dict) or not required_keys.issubset(fct.keys()):
            return CheckResult("macro_schema", False, f"factor #{i} con claves faltantes")
        if any(not str(fct.get(k, "")).strip() for k in required_keys):
            return CheckResult("macro_schema", False, f"factor #{i} con claves vacías")
    return CheckResult("macro_schema", True)


def check_macro_grounding(case: GoldenCase, d: Decision) -> Optional[CheckResult]:
    if not case.expect_macro_about:
        return None
    needle = case.expect_macro_about.lower()
    blob = " ".join(
        str(v) for fct in (d.macro_factors or []) if isinstance(fct, dict) for v in fct.values()
    ).lower()
    ok = needle in blob
    return CheckResult(
        "macro_grounding", ok,
        "" if ok else f"macro_factors no mencionan {case.expect_macro_about!r}",
    )


def check_allocation_sane(case: GoldenCase, d: Decision) -> Optional[CheckResult]:
    alloc = d.recommended_max_allocation_pct
    if alloc is None:
        return None
    cap = EVAL.conservative_alloc_cap_pct
    if alloc < 0 or alloc > cap:
        return CheckResult("allocation_sane", False, f"alloc {alloc}% fuera de [0, {cap}]")
    if d.action == "SELL" and alloc > 1.0:
        return CheckResult("allocation_sane", False, f"SELL con alloc {alloc}% (debería ~0)")
    return CheckResult("allocation_sane", True)


ALL_CHECKS: List[Callable] = [
    check_valid_structure,
    check_expected_action,
    check_no_forbidden_action,
    check_scores_deterministic,
    check_reasoning_nonempty,
    check_risks_present,
    check_macro_schema,
    check_macro_grounding,
    check_allocation_sane,
]


def run_checks(case: GoldenCase, d: Decision) -> List[CheckResult]:
    out: List[CheckResult] = []
    for fn in ALL_CHECKS:
        res = fn(case, d)
        if res is not None:
            out.append(res)
    return out


# --------------------------------------------------------------------------- #
#  Providers                                                                  #
# --------------------------------------------------------------------------- #

class ReplayProvider:
    """Deterministic — returns the recorded replay_response for each case."""

    name = "replay"

    def get_decision(self, case: GoldenCase) -> Decision:
        return parse_decision(case.replay_response, case)


class LiveProvider:
    """Calls the real multi-provider AIAnalyzer. Requires a working AI config."""

    def __init__(self, ai_config):
        self.name = f"live:{getattr(ai_config, 'provider', '?')}/{getattr(ai_config, 'model', '?')}"
        self._analyzer = AIAnalyzer(ai_config)

    def get_decision(self, case: GoldenCase) -> Decision:
        return self._analyzer.analyze(case.fund, case.tech)


class CommitteeProvider:
    """Runs the multi-agent committee and returns its verdict as a Decision.

    Lets the same golden cases measure committee quality vs single-shot. Accepts
    either a real ``ai_config`` (live) or an injected ``call_fn`` (deterministic,
    for tests). Caching is disabled so each eval run is fresh.
    """

    def __init__(self, ai_config=None, call_fn=None):
        from analysis.committee import CommitteeAnalyzer

        self.name = "committee:" + (
            f"{getattr(ai_config, 'provider', '?')}/{getattr(ai_config, 'model', '?')}"
            if ai_config else "injected"
        )
        self._committee = CommitteeAnalyzer(call_fn=call_fn, ai_config=ai_config, use_cache=False)

    def get_decision(self, case: GoldenCase) -> Decision:
        verdict = self._committee.analyze(case.fund, case.tech)
        return verdict.to_decision(case.fund, case.tech)


# --------------------------------------------------------------------------- #
#  Runner                                                                     #
# --------------------------------------------------------------------------- #

def run_eval(provider=None, cases: Optional[List[GoldenCase]] = None) -> EvalReport:
    """Run every case through ``provider`` (default: ReplayProvider) and score it."""
    provider = provider or ReplayProvider()
    cases = cases if cases is not None else golden_cases()

    results: List[CaseResult] = []
    for case in cases:
        try:
            decision = provider.get_decision(case)
        except Exception as exc:  # a provider failure is a hard case failure
            logger.error(f"eval: provider failed on {case.case_id} — {exc}")
            results.append(CaseResult(
                case.case_id, case.description, action="ERROR",
                checks=[CheckResult("provider_ok", False, str(exc))],
            ))
            continue
        checks = run_checks(case, decision)
        results.append(CaseResult(case.case_id, case.description, decision.action, checks))

    report = EvalReport(results)
    logger.info(
        f"eval[{getattr(provider, 'name', '?')}]: {report.n_passed}/{report.n_cases} casos OK "
        f"({report.suite_pass_rate * 100:.0f}%) — {'GREEN' if report.is_green else 'RED'}"
    )
    return report
