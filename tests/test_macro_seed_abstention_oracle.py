"""Oráculo MACRO-SEED: los docs de ejemplo del RAG no son hechos, y sin hechos el Macro se abstiene.

La base del usuario tenía sólo los 5 docs de ``example_macro_docs`` (doc_key
``seed:*``, un set de demo sembrado el 2026-06-16) y ``build_context`` los inyectaba
como «hechos fechados — usá ESTOS» en tres caminos: el comité por ticker (Macro y
Fundamental), la decisión IA de Stock Analysis y el Macro del comité de cartera. Los
5 dictámenes cacheados del 24/09 citaban «Fed 4.25‑4.50%» del seed.

Decisión (usuario, 2026-09-27): el seed no llega a ningún prompt, y sin docs frescos
reales el Estratega Macro se **abstiene** — no se convoca, como la voz de Dividendo
cuando el activo no paga. No es un voto fallido: uno fallido deja ``complete=False``,
y un veredicto incompleto no se cachea ni se registra en el track record.

Independiente del código bajo prueba: los textos que se buscan salen de
``example_macro_docs`` y de los prompts que el ``call_fn`` falso ve pasar.
"""

from __future__ import annotations

import json

import pytest

import analysis.macro_rag as mr
from analysis.committee import CommitteeAnalyzer, _verdict_from_dict, _verdict_to_dict
from analysis.eval_cases import golden_cases
from analysis.macro_rag import MacroDoc, MacroRagStore, example_macro_docs

MACRO = "Estratega Macro"
SEED_FACT = "4.25-4.50%"  # la tasa de la Fed que trae el doc de ejemplo
REAL_FACT = "Último valor reportado: 3.1"


def _today() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _real_doc() -> MacroDoc:
    return MacroDoc(
        "Índice de precios al consumidor IPC (FRED)",
        f"Dato macro de FRED. {REAL_FACT} (serie CPIAUCSL). Tasas e inflación en EE. UU.",
        source="FRED", as_of=_today(), tags=("fred", "macro"), doc_key="fred:CPIAUCSL",
    )


def _store(*docs: MacroDoc) -> MacroRagStore:
    store = MacroRagStore(":memory:")
    store.ingest_many(list(docs))
    return store


@pytest.fixture
def seed_only(monkeypatch):
    monkeypatch.setattr(mr, "macro_rag_store", _store(*example_macro_docs()))


@pytest.fixture
def seed_and_real(monkeypatch):
    monkeypatch.setattr(mr, "macro_rag_store", _store(*example_macro_docs(), _real_doc()))


def _agent(stance: str) -> str:
    return json.dumps({"stance": stance, "confidence": "MEDIUM",
                       "key_points": ["punto"], "concerns": ["riesgo"]})


def _fundamental(action: str) -> str:
    return json.dumps({"action": action, "confidence": "HIGH", "rationale": ["ok"],
                       "risks": ["valuación"], "reasoning": "x" * 120,
                       "recommended_max_allocation_conservative": 5,
                       "macro_factors": []})


def _recording_fake(seen: list):
    def call_fn(prompt: str) -> str:
        seen.append(prompt)
        if '"recommended_max_allocation_conservative"' in prompt:
            return _fundamental("BUY")
        return _agent("HOLD")
    return call_fn


def _fund_tech():
    case = golden_cases()[0]  # quality_compounder_buy
    return case.fund, case.tech


# --------------------------------------------------------------------------- #
#  El RAG                                                                      #
# --------------------------------------------------------------------------- #

def test_seed_only_store_builds_no_context():
    store = _store(*example_macro_docs())
    assert store.build_context("tasas inflación macro tecnología") == ""


def test_seed_is_filtered_but_real_docs_still_reach_the_block():
    store = _store(*example_macro_docs(), _real_doc())
    block = store.build_context("tasas inflación macro")
    assert REAL_FACT in block
    for doc in example_macro_docs():
        assert doc.body not in block
    assert SEED_FACT not in block


# --------------------------------------------------------------------------- #
#  Comité por ticker                                                           #
# --------------------------------------------------------------------------- #

def test_macro_abstains_and_no_prompt_sees_the_seed(seed_only):
    seen: list = []
    fund, tech = _fund_tech()
    verdict = CommitteeAnalyzer(call_fn=_recording_fake(seen), use_cache=False).analyze(fund, tech)

    assert not any(MACRO in p for p in seen), "el Macro no se convoca: no se paga su llamada"
    assert not any(SEED_FACT in p for p in seen), "el seed llegó a un prompt (Fundamental incluido)"
    assert MACRO not in {o.role for o in verdict.opinions}
    assert MACRO in verdict.abstentions
    # Abstenerse no es fallar: el panel queda completo, con quórum pleno, y se registra.
    assert verdict.complete is True
    assert verdict.quorum_pct == 100.0
    decision = verdict.to_decision(fund, tech)
    assert decision.action in {"STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL", "AVOID"}


def test_macro_is_convened_when_there_is_a_real_fresh_doc(seed_and_real):
    seen: list = []
    fund, tech = _fund_tech()
    verdict = CommitteeAnalyzer(call_fn=_recording_fake(seen), use_cache=False).analyze(fund, tech)

    macro_prompts = [p for p in seen if MACRO in p]
    assert len(macro_prompts) == 1
    assert REAL_FACT in macro_prompts[0]
    assert SEED_FACT not in macro_prompts[0]
    assert MACRO in {o.role for o in verdict.opinions}
    assert not verdict.abstentions


def test_abstention_survives_the_cache_round_trip(seed_only):
    fund, tech = _fund_tech()
    verdict = CommitteeAnalyzer(call_fn=_recording_fake([]), use_cache=False).analyze(fund, tech)
    back = _verdict_from_dict(json.loads(json.dumps(_verdict_to_dict(verdict))))
    assert back.abstentions == verdict.abstentions
    assert MACRO in back.abstentions


# --------------------------------------------------------------------------- #
#  Comité de cartera                                                           #
# --------------------------------------------------------------------------- #

def test_portfolio_macro_abstains_without_macro_context():
    from analysis.committee import build_holdings_committee_context

    seen: list = []
    ctx = build_holdings_committee_context(
        position_weights={"AAPL": 60.0, "JNJ": 40.0},
        sector_weights={"Technology": 60.0, "Healthcare": 40.0},
        macro_context="",
    )
    verdict = CommitteeAnalyzer(call_fn=_recording_fake(seen), use_cache=False).analyze_portfolio(
        ctx, plan_key="oracle"
    )
    assert not any(MACRO in p for p in seen)
    assert MACRO in verdict.abstentions
    assert verdict.complete is True


# --------------------------------------------------------------------------- #
#  Decisión IA de Stock Analysis                                               #
# --------------------------------------------------------------------------- #

def test_single_call_decision_prompt_does_not_see_the_seed(seed_only):
    from analysis.ai_analyzer import AIAnalyzer
    from config import AIConfig

    fund, tech = _fund_tech()
    prompt = AIAnalyzer(AIConfig())._build_prompt(fund, tech)
    assert SEED_FACT not in prompt


# --------------------------------------------------------------------------- #
#  Lo que ve el usuario                                                        #
# --------------------------------------------------------------------------- #

def test_ui_caption_names_the_abstaining_voice(seed_only):
    from dashboard.shared import committee_abstention_caption

    fund, tech = _fund_tech()
    verdict = CommitteeAnalyzer(call_fn=_recording_fake([]), use_cache=False).analyze(fund, tech)
    caption = committee_abstention_caption(verdict)
    assert MACRO in caption and "se abstuvo" in caption


def test_ui_caption_is_empty_for_a_full_panel(seed_and_real):
    from dashboard.shared import committee_abstention_caption

    fund, tech = _fund_tech()
    verdict = CommitteeAnalyzer(call_fn=_recording_fake([]), use_cache=False).analyze(fund, tech)
    assert committee_abstention_caption(verdict) == ""
