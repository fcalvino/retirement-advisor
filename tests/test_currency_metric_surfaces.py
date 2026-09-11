"""Currency suppression is an explanation, never a new scoring input (offline)."""

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from analysis.fundamental import FundamentalResult
from analysis.prompts import equity_decision_prompt
from analysis.strategy import RetirementStrategy
from analysis.technical import TechnicalResult


def currency_note(metric, financial="BRL", quote="USD"):
    if metric == "fcf_yield":
        return (
            f"FCF yield no medible: el free cash flow viene en {financial} y el "
            f"market cap en {quote}; un yield sólo está definido si ambas "
            "patas comparten moneda."
        )
    return (
        f"P/FFO no medible: el FFO viene en {financial} y el market cap "
        f"en {quote}; un múltiplo sólo está definido si ambas "
        "patas comparten moneda."
    )


BACKSTOP = (
    "FCF yield descartado por implausible: 400% (techo 50%) — probable moneda de "
    "los estados distinta de la de cotización sin campo financialCurrency."
)


def fund_fixture():
    return FundamentalResult(
        symbol="TEST", sector="Real Estate", industry="REIT - Retail",
        total_score=65, adjusted_score=65, current_price=100.0,
    )


@pytest.mark.parametrize("metric,label,numerator", [
    ("fcf_yield", "FCF Yield", "FCF"), ("p_ffo", "P/FFO", "FFO"),
])
@pytest.mark.parametrize("financial,quote", [("COP", "USD"), ("BRL", "USD"), ("USD", "CAD")])
def test_currency_note_reaches_prompt_and_neutral_rationale(metric, label, numerator, financial, quote):
    fund = fund_fixture()
    fund.notes[f"{metric}_currency"] = currency_note(metric, financial, quote)
    tech = TechnicalResult("TEST")
    prompt = equity_decision_prompt(fund, tech)
    assert f"{label}=no medible ({numerator} en {financial}, market cap en {quote})" in prompt
    decision = RetirementStrategy().decide(fund, tech)
    rationale_label = "FCF yield" if metric == "fcf_yield" else label
    assert f"{rationale_label} not measurable: statements in {financial}, quote in {quote}" in decision.rationale


@pytest.mark.parametrize("metric,label", [("fcf_yield", "FCF Yield"), ("p_ffo", "P/FFO")])
def test_missing_without_note_does_not_invent_currency_problem(metric, label):
    fund = fund_fixture()
    tech = TechnicalResult("TEST")
    assert f"{label}=N/A" in equity_decision_prompt(fund, tech)
    assert not any("not measurable" in s for s in RetirementStrategy().decide(fund, tech).rationale)


def test_measurable_values_and_existing_fcf_highlight():
    fund = fund_fixture()
    fund.fcf_yield, fund.p_ffo = 4.5, 12.5
    tech = TechnicalResult("TEST")
    prompt = equity_decision_prompt(fund, tech)
    assert "FCF Yield=4.5%" in prompt
    assert "P/FFO=12.5x" in prompt
    assert "Attractive FCF yield: 4.5%" in RetirementStrategy().decide(fund, tech).rationale


@pytest.mark.parametrize("note", [BACKSTOP, "Causa conservada de una nota futura."])
def test_unrecognized_note_keeps_actual_reason_without_fabricated_currencies(note):
    fund = fund_fixture()
    fund.notes["fcf_yield_currency"] = note
    tech = TechnicalResult("TEST")
    assert f"FCF Yield=no medible ({note})" in equity_decision_prompt(fund, tech)
    rationale = RetirementStrategy().decide(fund, tech).rationale
    assert f"FCF yield not measurable: {note}" in rationale
    assert not any("statements in" in s for s in rationale)


def test_both_notes_only_change_rationale_not_decision_or_scores():
    fund = fund_fixture()
    tech = TechnicalResult("TEST")
    control = asdict(RetirementStrategy().decide(fund, tech))
    fund.notes = {f"{m}_currency": currency_note(m) for m in ("fcf_yield", "p_ffo")}
    before = deepcopy(fund)
    result = asdict(RetirementStrategy().decide(fund, tech))
    assert len(result.pop("rationale")) == len(control.pop("rationale")) + 2
    assert result == control
    assert fund == before
    prompt = equity_decision_prompt(fund, tech)
    assert "FCF Yield=no medible" in prompt and "P/FFO=no medible" in prompt


def test_legacy_object_without_notes_and_operating_company():
    fund = fund_fixture()
    fund.sector, fund.industry = "Technology", "Software"
    attrs = vars(fund).copy()
    attrs.pop("notes")
    legacy = SimpleNamespace(**attrs, is_value_stock=fund.is_value_stock)
    tech = TechnicalResult("TEST")
    prompt = equity_decision_prompt(legacy, tech)
    assert "FCF Yield=N/A" in prompt
    assert "P/FFO=" not in prompt
    RetirementStrategy().decide(legacy, tech)


def test_argentine_adr_prompt_does_not_assert_usd_statements():
    fund = fund_fixture()
    fund.symbol = "CEPU"
    fund.notes["fcf_yield_currency"] = currency_note("fcf_yield", "ARS")
    prompt = equity_decision_prompt(fund, TechnicalResult("CEPU"))
    assert "Los reportes financieros están en USD" not in prompt
    assert "FCF en ARS, market cap en USD" in prompt
