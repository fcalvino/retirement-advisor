"""Tests for the AI eval harness (Gran Salto, Fase 2A).

Verifies the runner is green on the golden set in replay mode, and that each
check actually catches its failure mode (using deliberately broken responses).
No network / no API key — replay mode only.
"""

from __future__ import annotations

import json

from analysis.eval_cases import GoldenCase, golden_cases
from analysis.eval_harness import (
    ReplayProvider,
    check_allocation_sane,
    check_expected_action,
    check_macro_grounding,
    check_macro_schema,
    check_no_forbidden_action,
    check_reasoning_nonempty,
    check_risks_present,
    check_scores_deterministic,
    check_valid_structure,
    parse_decision,
    run_eval,
)


def _case(**overrides) -> GoldenCase:
    """Take the first golden case and override fields for targeted check tests."""
    base = golden_cases()[0]
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _decision_from(case, **fields):
    """Build a Decision by editing the case's replay JSON, then parsing it."""
    payload = json.loads(case.replay_response)
    payload.update(fields)
    return parse_decision(json.dumps(payload, ensure_ascii=False), case)


# ------------------------------------------------------------------ #
#  Suite-level                                                         #
# ------------------------------------------------------------------ #

def test_replay_suite_is_green():
    report = run_eval(ReplayProvider())
    assert report.n_cases >= 6
    assert report.is_green, [
        (r.case_id, [(f.name, f.detail) for f in r.failures]) for r in report.results if not r.passed
    ]
    # Every golden case is authored to pass fully.
    assert report.n_passed == report.n_cases


def test_check_pass_rates_reported():
    report = run_eval(ReplayProvider())
    rates = report.check_pass_rates()
    assert "valid_structure" in rates
    assert all(0.0 <= v <= 1.0 for v in rates.values())


# ------------------------------------------------------------------ #
#  Individual checks — failure detection                              #
# ------------------------------------------------------------------ #

def test_valid_structure_catches_bad_action():
    case = _case()
    d = _decision_from(case)
    d.action = "MAYBE"  # not a valid action
    assert check_valid_structure(case, d).passed is False


def test_expected_action_detects_mismatch():
    case = golden_cases()[1]  # high_leverage_caution: expects REDUCE/SELL/HOLD
    d = _decision_from(case)
    d.action = "STRONG BUY"
    assert check_expected_action(case, d).passed is False


def test_no_forbidden_action():
    case = golden_cases()[1]  # forbids STRONG BUY / BUY
    d = _decision_from(case)
    d.action = "BUY"
    assert check_no_forbidden_action(case, d).passed is False


def test_scores_must_be_deterministic():
    case = _case()
    d = _decision_from(case)
    d.fundamental_score = 999.0  # LLM tampering — engine value differs
    assert check_scores_deterministic(case, d).passed is False


def test_reasoning_nonempty():
    case = _case()
    d = _decision_from(case, reasoning="corto")
    assert check_reasoning_nonempty(case, d).passed is False


def test_risks_required_on_buy():
    case = _case()  # quality_compounder_buy, action BUY
    d = _decision_from(case, risks=[])
    res = check_risks_present(case, d)
    assert res is not None and res.passed is False


def test_macro_schema_rejects_missing_keys():
    case = _case()
    d = _decision_from(case)
    d.macro_factors = [{"factor": "X"}]  # missing the other 3 keys
    assert check_macro_schema(case, d).passed is False


def test_macro_schema_rejects_too_many():
    case = _case()
    d = _decision_from(case)
    full = {"factor": "a", "why_relevant": "b", "impact": "c", "effect_on_allocation_or_conviction": "d"}
    d.macro_factors = [full, full, full]  # > max (2)
    assert check_macro_schema(case, d).passed is False


def test_macro_grounding_for_argentina_case():
    case = next(c for c in golden_cases() if c.case_id == "argentina_adr_macro")
    d = _decision_from(case)
    # As authored it mentions Argentina -> passes.
    assert check_macro_grounding(case, d).passed is True
    # Strip the grounding -> fails.
    d.macro_factors = []
    assert check_macro_grounding(case, d).passed is False


def test_allocation_cap_enforced():
    case = _case()
    d = _decision_from(case)
    d.recommended_max_allocation_pct = 40.0  # above conservative cap
    assert check_allocation_sane(case, d).passed is False


def test_allocation_none_is_skipped():
    case = _case()
    d = _decision_from(case)
    d.recommended_max_allocation_pct = None
    assert check_allocation_sane(case, d) is None


def test_sell_with_large_allocation_flagged():
    case = golden_cases()[1]
    d = _decision_from(case)
    d.action = "SELL"
    d.recommended_max_allocation_pct = 8.0
    assert check_allocation_sane(case, d).passed is False
