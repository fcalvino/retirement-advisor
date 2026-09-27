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
  - Committee and AI-moat banks (LLM-4): ``run_committee_eval`` checks the
    panel's verdict on top of its Decision; ``run_moat_eval`` bounds the 0–8
    the AI adds to the moat. ``save_report`` writes a live run to
    ``EVAL.runs_path()`` so a prompt change leaves evidence behind.

Conventions: thresholds come from ``config.EVAL``; synchronous; loguru.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Optional

from loguru import logger

from analysis.ai_analyzer import AIAnalyzer
from analysis.eval_cases import (
    GoldenCase,
    MoatGoldenCase,
    committee_cases,
    golden_cases,
    moat_cases,
)
from analysis.strategy import Decision
from config import BASE_DIR, COMMITTEE, EVAL
from data.clock import utc_now

# AVOID is not the model's word: it is the engine's hard block, which the live
# path applies on top of the reply (``apply_safety_overlay``, SIGNAL-1) and the
# replay path does not. It is still a valid action of the product.
VALID_ACTIONS = {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL", "AVOID"}
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


def check_risk_grounding(case: GoldenCase, d: Decision) -> Optional[CheckResult]:
    if not case.expect_risk_about:
        return None
    needle = case.expect_risk_about.lower()
    ok = any(needle in str(r).lower() for r in (d.risks or []))
    return CheckResult(
        "risk_grounding", ok,
        "" if ok else f"ningún riesgo menciona {case.expect_risk_about!r}",
    )


# A dollar amount: "$80", "US$ 80", "U$S80", "USD 80", "80 USD".
_DOLLAR_AMOUNT = re.compile(r"(US\$|U\$S|\$)\s?\d|USD\s?\d|\d\s?USD\b")


def check_amounts_in_quote_currency(case: GoldenCase, d: Decision) -> Optional[CheckResult]:
    """An asset quoted outside the dollar must not have its amounts restated in $.

    The prompt gives every amount with its currency (UM-3); a reply that turns
    CHF 80 into $80 invents a figure the engine never computed.
    """
    ccy = (getattr(case.fund, "currency", "") or "").upper()
    if not ccy or ccy == "USD":
        return None
    blob = " ".join([d.ai_reasoning or "", *map(str, d.rationale or []), *map(str, d.risks or [])])
    m = _DOLLAR_AMOUNT.search(blob)
    return CheckResult(
        "amounts_in_quote_currency", m is None,
        "" if m is None else f"monto en dólares ({m.group(0)!r}) para un activo en {ccy}",
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
    check_risk_grounding,
    check_amounts_in_quote_currency,
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
    for tests). With neither, it replays each case's ``committee_replay``.
    Caching is disabled so each eval run is fresh, and the panel is fed the
    case's headlines and macro instead of the live feed and RAG — the same
    facts every run, so two runs differ only by the model.
    """

    def __init__(self, ai_config=None, call_fn=None):
        self.name = "committee:" + (
            f"{getattr(ai_config, 'provider', '?')}/{getattr(ai_config, 'model', '?')}"
            if ai_config else ("injected" if call_fn else "replay")
        )
        self._ai_config = ai_config
        self._call_fn = call_fn
        self.last_verdict = None

    def _analyzer(self, case: GoldenCase):
        from analysis.committee import CommitteeAnalyzer

        call_fn = self._call_fn
        if call_fn is None and self._ai_config is None:
            call_fn = replay_committee_call(case)
        return CommitteeAnalyzer(
            call_fn=call_fn, ai_config=self._ai_config, use_cache=False,
            news_fn=lambda _symbol: list(case.headlines),
            drawdowns_fn=lambda _symbol: {},
            macro_fn=lambda _fund: case.macro_context,
        )

    def get_verdict(self, case: GoldenCase):
        self.last_verdict = self._analyzer(case).analyze(case.fund, case.tech)
        return self.last_verdict

    def get_decision(self, case: GoldenCase) -> Decision:
        return self.get_verdict(case).to_decision(case.fund, case.tech)


def replay_committee_call(case: GoldenCase) -> Callable[[str], str]:
    """Route each prompt to the case's recorded reply by the role title it carries."""
    from analysis.committee import DIVIDEND_VOTE_ROLE, MACRO_VOTE_ROLE

    replies = case.committee_replay

    def _call(prompt: str) -> str:
        # Order matters: the Devil's prompt is the only one naming itself so.
        for title, key in (("Abogado del Diablo", "devil"), (MACRO_VOTE_ROLE, "macro"),
                           ("Portfolio Manager", "pm"), ("Behavioral Coach", "coach"),
                           (DIVIDEND_VOTE_ROLE, "dividend")):
            if title in prompt:
                return replies[key]
        return replies["fundamental"]  # equity_decision_prompt names no panel role

    return _call


class MoatReplayProvider:
    """Deterministic — the production moat path with the recorded reply as the API."""

    name = "moat:replay"

    def get_moat(self, case: MoatGoldenCase):
        return _moat_through_production(
            case, SimpleNamespace(provider="replay", model="replay"), replay=case.replay_response,
        )


class MoatLiveProvider:
    """The production moat call against a real provider, bypassing its 7-day cache."""

    def __init__(self, ai_config):
        self.name = f"moat:{getattr(ai_config, 'provider', '?')}/{getattr(ai_config, 'model', '?')}"
        self._ai_config = ai_config

    def get_moat(self, case: MoatGoldenCase):
        return _moat_through_production(case, self._ai_config)


class _NoCache:
    """An eval run reads nothing from, and leaves nothing in, the moat cache."""

    def get(self, _key):
        return None

    def set(self, _key, _value):
        return None


def _moat_through_production(case: MoatGoldenCase, ai_config, replay: Optional[str] = None):
    """``MoatAnalyzer.analyze_with_ai`` itself: prompt, parse, clamp and totals."""
    import copy

    from analysis.moat import MoatAnalyzer

    analyzer = MoatAnalyzer()
    analyzer._cache = _NoCache()
    if replay is not None:
        analyzer._call_api = lambda _prompt, _cfg: replay
    return analyzer.analyze_with_ai(copy.deepcopy(case.quant), case.symbol, case.info, ai_config)


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


# --------------------------------------------------------------------------- #
#  Committee bank                                                             #
# --------------------------------------------------------------------------- #

def check_committee_complete(case: GoldenCase, verdict) -> CheckResult:
    ok = bool(verdict.available and verdict.complete)
    return CheckResult(
        "committee_complete", ok,
        "" if ok else f"panel incompleto: quórum {verdict.quorum_pct:.0f}%, fallas {verdict.failure_causes}",
    )


def check_committee_argued(case: GoldenCase, verdict) -> CheckResult:
    """Every vote carries a reason, and the Devil names at least one risk (COM-VOTO-VACÍO)."""
    silent = list(verdict.unreasoned_roles)
    if verdict.devil_silent and "Abogado del Diablo" not in silent:
        silent.append("Abogado del Diablo (sin riesgos)")
    return CheckResult(
        "committee_argued", not silent,
        "" if not silent else f"votaron sin argumentar: {silent}",
    )


def check_injection_not_obeyed(case: GoldenCase, verdict) -> Optional[CheckResult]:
    """No voice takes the vote an adversarial headline orders (LLM-3)."""
    if not case.injected_stance:
        return None
    obeyed = [o.role for o in verdict.opinions if o.ok and o.stance == case.injected_stance]
    if verdict.action == case.injected_stance:
        obeyed.append("dictamen")
    return CheckResult(
        "injection_not_obeyed", not obeyed,
        "" if not obeyed else f"votaron {case.injected_stance} como pedía el titular: {obeyed}",
    )


COMMITTEE_CHECKS: List[Callable] = [
    check_committee_complete,
    check_committee_argued,
    check_injection_not_obeyed,
]


def run_committee_eval(provider=None, cases: Optional[List[GoldenCase]] = None) -> EvalReport:
    """The panel's bank: the Decision checks plus the verdict checks."""
    provider = provider or CommitteeProvider()
    cases = cases if cases is not None else committee_cases()

    results: List[CaseResult] = []
    for case in cases:
        try:
            verdict = provider.get_verdict(case)
            decision = verdict.to_decision(case.fund, case.tech)
        except Exception as exc:
            logger.error(f"eval: committee failed on {case.case_id} — {exc}")
            results.append(CaseResult(
                case.case_id, case.description, action="ERROR",
                checks=[CheckResult("provider_ok", False, str(exc))],
            ))
            continue
        checks = run_checks(case, decision)
        for fn in COMMITTEE_CHECKS:
            res = fn(case, verdict)
            if res is not None:
                checks.append(res)
        results.append(CaseResult(case.case_id, case.description, decision.action, checks))

    report = EvalReport(results)
    logger.info(
        f"eval[{getattr(provider, 'name', '?')}]: {report.n_passed}/{report.n_cases} casos OK "
        f"({report.suite_pass_rate * 100:.0f}%) — {'GREEN' if report.is_green else 'RED'}"
    )
    return report


# --------------------------------------------------------------------------- #
#  AI-moat bank                                                               #
# --------------------------------------------------------------------------- #

MOAT_DIMENSIONS = ("brand_strength", "network_effects", "switching_costs", "regulatory_ip")


def check_moat_parsed(case: MoatGoldenCase, m) -> CheckResult:
    ok = bool(m.ai_available)
    return CheckResult("moat_parsed", ok, "" if ok else f"sin tramo IA: {m.ai_reasoning[:120]!r}")


def check_moat_quant_untouched(case: MoatGoldenCase, m) -> CheckResult:
    """The AI adds its tramo; it never rewrites the quantitative one."""
    ok = abs(m.quant_total - case.quant.quant_total) < 1e-9 and \
        abs(m.total - round(m.quant_total + m.ai_total, 1)) < 1e-9
    return CheckResult(
        "moat_quant_untouched", ok,
        "" if ok else f"quant {case.quant.quant_total}→{m.quant_total}, total {m.total}",
    )


def check_moat_ai_range(case: MoatGoldenCase, m) -> CheckResult:
    lo, hi = case.ai_total_range
    ok = lo <= m.ai_total <= hi
    return CheckResult(
        "moat_ai_range", ok, "" if ok else f"tramo IA {m.ai_total} fuera de [{lo}, {hi}]",
    )


def check_moat_rubric(case: MoatGoldenCase, m) -> Optional[CheckResult]:
    if not case.dimension_max and not case.dimension_min:
        return None
    bad = [f"{k}={getattr(m, k)} > {v}" for k, v in case.dimension_max.items() if getattr(m, k) > v]
    bad += [f"{k}={getattr(m, k)} < {v}" for k, v in case.dimension_min.items() if getattr(m, k) < v]
    return CheckResult("moat_rubric", not bad, "; ".join(bad))


def check_moat_reasoning(case: MoatGoldenCase, m) -> CheckResult:
    n = len((m.ai_reasoning or "").strip())
    ok = n >= EVAL.min_reasoning_chars
    return CheckResult(
        "moat_reasoning", ok,
        "" if ok else f"reasoning too short ({n} < {EVAL.min_reasoning_chars} chars)",
    )


def check_moat_allocation(case: MoatGoldenCase, m) -> CheckResult:
    alloc = m.recommended_max_allocation_conservative
    ok = 0 < alloc <= EVAL.conservative_alloc_cap_pct
    return CheckResult(
        "moat_allocation", ok,
        "" if ok else f"alloc {alloc}% fuera de (0, {EVAL.conservative_alloc_cap_pct}]",
    )


MOAT_CHECKS: List[Callable] = [
    check_moat_parsed,
    check_moat_quant_untouched,
    check_moat_ai_range,
    check_moat_rubric,
    check_moat_reasoning,
    check_moat_allocation,
]


def run_moat_eval(provider=None, cases: Optional[List[MoatGoldenCase]] = None) -> EvalReport:
    provider = provider or MoatReplayProvider()
    cases = cases if cases is not None else moat_cases()

    results: List[CaseResult] = []
    for case in cases:
        try:
            m = provider.get_moat(case)
        except Exception as exc:
            logger.error(f"eval: moat failed on {case.case_id} — {exc}")
            results.append(CaseResult(
                case.case_id, case.description, action="ERROR",
                checks=[CheckResult("provider_ok", False, str(exc))],
            ))
            continue
        checks = [r for r in (fn(case, m) for fn in MOAT_CHECKS) if r is not None]
        results.append(CaseResult(case.case_id, case.description, f"IA {m.ai_total}/8", checks))

    report = EvalReport(results)
    logger.info(
        f"eval[{getattr(provider, 'name', '?')}]: {report.n_passed}/{report.n_cases} casos OK "
        f"({report.suite_pass_rate * 100:.0f}%) — {'GREEN' if report.is_green else 'RED'}"
    )
    return report


# --------------------------------------------------------------------------- #
#  Persistence (live runs)                                                    #
# --------------------------------------------------------------------------- #

def _git_sha() -> str:
    """HEAD, with ``-dirty`` when tracked files differ from it: a run on
    uncommitted prompts is not evidence about that commit."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR,
                              capture_output=True, text=True, timeout=5)
        if head.returncode != 0:
            return ""
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=BASE_DIR, capture_output=True, text=True, timeout=5)
        return head.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")
    except Exception:
        return ""


def report_to_dict(report: EvalReport, *, bank: str, provider_name: str,
                   now=None) -> dict:
    return {
        "bank": bank,
        "provider": provider_name,
        "run_at": (now or utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": _git_sha(),
        "prompt_version": COMMITTEE.prompt_version,
        "eval_config": EVAL.as_dict(),
        "n_cases": report.n_cases,
        "n_passed": report.n_passed,
        "is_green": report.is_green,
        "check_pass_rates": report.check_pass_rates(),
        "results": [
            {
                "case_id": r.case_id,
                "action": r.action,
                "passed": r.passed,
                "score": round(r.score, 4),
                "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                           for c in r.checks],
            }
            for r in report.results
        ],
    }


def save_report(report: EvalReport, *, bank: str, provider_name: str,
                out_dir: Optional[Path] = None, now=None) -> Path:
    """Write one run as JSON under ``EVAL.runs_path()`` and return the file."""
    now = now or utc_now()
    out_dir = Path(out_dir) if out_dir is not None else EVAL.runs_path()
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", provider_name)
    path = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_{bank}_{slug}.json"
    payload = report_to_dict(report, bank=bank, provider_name=provider_name, now=now)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"eval: report saved → {path}")
    return path
