"""EVAL-GROQ-1 (parte del prompt) — el riesgo país y el cambiario llegan como dato.

Dos fallas estables del banco en vivo (6/6 y 5/6) no eran del modelo:
- ``argentina_adr_macro``: el check pide Argentina en ``macro_factors`` y el
  prompt reservaba ``macro_factors`` a los hechos fechados del RAG (FRED de
  EE.UU.). El ``CONTEXTO PAÍS`` curado pasa a ser una fuente válida.
- ``non_usd_quote``: nada decía que el plan se mide en USD, así que el riesgo
  cambiario no estaba en el input. Una línea determinista lo dice, en el prompt
  de decisión y en el bloque común del comité.
"""

import pytest

from analysis.committee_prompts import committee_context_block
from analysis.prompts import FX_RISK_INSTRUCTION, equity_decision_prompt, plan_currency_note
from config import PORTFOLIO
from tests.test_prompts import _equity_fund, _tech

RAG = "=== CONTEXTO MACRO ===\n- [2026-09-26] (FRED) Tasa de fondos federales: 4.33 %"
COUNTRY_SOURCE = "CONTEXTO PAÍS de arriba es un dato provisto"


def _fund(symbol="AAPL", currency="USD"):
    f = _equity_fund(symbol)
    f.currency = currency
    f.financial_currency = currency
    return f


# --------------------------------------------------------------------------- #
#  Riesgo país                                                                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("macro", [RAG, ""])
def test_argentine_adr_may_cite_country_context_in_macro_factors(macro):
    prompt = equity_decision_prompt(_fund("YPF"), _tech("YPF"), macro)
    assert "CONTEXTO PAÍS — Argentina" in prompt
    assert COUNTRY_SOURCE in prompt
    tail = prompt.split(COUNTRY_SOURCE, 1)[1][:400]
    # mandatory: with «si es material» it lost to the generic «devolvé []» 3 of 6 times
    assert "tiene que ser ese riesgo país" in tail and "macro_factors" in tail


def test_without_rag_an_argentine_adr_is_not_told_to_return_empty_macro():
    prompt = equity_decision_prompt(_fund("YPF"), _tech("YPF"), "")
    # memory is still forbidden; the empty-list order no longer covers the country block
    assert "no cites datos macro de memoria" in prompt
    assert "devolvé `macro_factors: []`" not in prompt


@pytest.mark.parametrize("macro", [RAG, ""])
def test_non_adr_gets_no_country_source_line(macro):
    prompt = equity_decision_prompt(_fund("AAPL"), _tech("AAPL"), macro)
    assert COUNTRY_SOURCE not in prompt


def test_us_asset_without_rag_still_returns_empty_macro():
    assert "devolvé `macro_factors: []`" in equity_decision_prompt(_fund(), _tech(), "")


# --------------------------------------------------------------------------- #
#  Moneda del plan                                                            #
# --------------------------------------------------------------------------- #

def test_note_names_both_currencies_and_the_risk():
    note = plan_currency_note(_fund("NESN.SW", "CHF"))
    assert "CHF" in note and PORTFOLIO.base_currency in note
    assert "riesgo cambiario" in note


@pytest.mark.parametrize("ccy", ["USD", "", None])
def test_no_note_in_the_plan_currency_or_unknown(ccy):
    assert plan_currency_note(_fund("AAPL", ccy)) == ""


def test_decision_prompt_carries_the_note_and_usd_is_unchanged():
    chf = equity_decision_prompt(_fund("NESN.SW", "CHF"), _tech("NESN.SW"), RAG)
    assert plan_currency_note(_fund("NESN.SW", "CHF")) in chf
    assert FX_RISK_INSTRUCTION in chf
    usd = equity_decision_prompt(_fund("AAPL", "USD"), _tech("AAPL"), RAG)
    assert "riesgo cambiario propio" not in usd
    assert FX_RISK_INSTRUCTION not in usd


def test_committee_block_carries_the_note_and_usd_is_unchanged():
    chf = committee_context_block(_fund("NESN.SW", "CHF"), _tech("NESN.SW"))
    assert plan_currency_note(_fund("NESN.SW", "CHF")) in chf
    usd = committee_context_block(_fund("AAPL", "USD"), _tech("AAPL"))
    assert "riesgo cambiario propio" not in usd


# --------------------------------------------------------------------------- #
#  Evidencia del banco en vivo                                                #
# --------------------------------------------------------------------------- #

def test_live_decision_bank_uses_the_case_macro_not_the_rag(monkeypatch):
    import analysis.macro_rag as mr
    from analysis.eval_cases import golden_cases
    from analysis.eval_harness import LiveProvider
    from config import AIConfig

    def boom(*_a, **_k):
        raise AssertionError("el banco de decisión no puede leer el RAG real")

    monkeypatch.setattr(mr, "macro_context_for", boom)
    case = next(c for c in golden_cases() if c.case_id == "argentina_adr_macro")
    assert case.macro_context  # frozen, same block as the stability bank
    provider = LiveProvider(AIConfig(provider="groq", model="m", api_key="k", enabled=True))
    seen = []
    provider._analyzer._call_api = lambda prompt, **_k: seen.append(prompt) or case.replay_response
    provider._analyzer._preflight = lambda: None
    provider.get_decision(case)
    assert case.macro_context in seen[0]
    assert COUNTRY_SOURCE in seen[0]


def test_ai_analyzer_default_macro_source_is_still_the_rag(monkeypatch):
    import analysis.macro_rag as mr
    from analysis.ai_analyzer import AIAnalyzer
    from config import AIConfig

    monkeypatch.setattr(mr, "macro_context_for", lambda _f: "HECHO-RAG-XYZ")
    prompt = AIAnalyzer(AIConfig(provider="groq", model="m", api_key="k", enabled=True))._build_prompt(
        _fund(), _tech())
    assert "HECHO-RAG-XYZ" in prompt


def test_saved_report_keeps_what_the_model_wrote():
    from analysis.eval_harness import ReplayProvider, report_to_dict, run_eval

    rep = report_to_dict(run_eval(ReplayProvider()), bank="decision", provider_name="replay")
    ypf = next(r for r in rep["results"] if r["case_id"] == "argentina_adr_macro")
    assert ypf["risks"] and all(isinstance(x, str) for x in ypf["risks"])
    assert any("Argentina" in str(f) for f in ypf["macro_factors"])
