"""Tests for the macro RAG (Gran Salto, Fase 3B).

In-memory store, no network. Verifies ingest/roundtrip, idempotent upsert,
TF-IDF relevance ranking, the freshness gate, and the dated context block + its
injection into the committee Macro Strategist prompt.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from analysis.committee_prompts import macro_strategist_prompt
from analysis.macro_rag import MacroDoc, MacroRagStore, macro_query_for


@pytest.fixture
def store():
    return MacroRagStore(db_path=":memory:")


def _today(offset_days=0):
    return (datetime.utcnow() - timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _seed(store):
    store.ingest_many([
        MacroDoc("Tasa de la Fed", "La Fed mantuvo la tasa de fondos federales en 4.5%.",
                 source="Fed", as_of=_today(2), tags=("tasas", "us"), doc_key="d_fed"),
        MacroDoc("Inflación CPI", "El IPC interanual fue 2.9%, inflación de servicios rígida.",
                 source="FRED", as_of=_today(3), tags=("inflacion",), doc_key="d_cpi"),
        MacroDoc("Riesgo Argentina", "Controles de cambio y brecha cambiaria en Argentina afectan ADRs.",
                 source="seed", as_of=_today(5), tags=("argentina", "fx"), doc_key="d_ar"),
    ])


# ------------------------------------------------------------------ #
#  Store                                                              #
# ------------------------------------------------------------------ #

def test_ingest_and_count(store):
    _seed(store)
    assert store.count() == 3


def test_idempotent_upsert(store):
    d = MacroDoc("Tasa", "v1", source="Fed", as_of=_today(), doc_key="k1")
    store.ingest(d)
    store.ingest(MacroDoc("Tasa", "v2 actualizado", source="Fed", as_of=_today(), doc_key="k1"))
    assert store.count() == 1
    assert store.all_docs()[0].body == "v2 actualizado"


def test_clear(store):
    _seed(store)
    store.clear()
    assert store.count() == 0


# ------------------------------------------------------------------ #
#  Retrieval                                                          #
# ------------------------------------------------------------------ #

def test_retrieval_ranks_relevant_first(store):
    _seed(store)
    hits = store.retrieve("argentina brecha cambiaria adr", k=3)
    assert hits, "expected at least one hit"
    assert hits[0][0].doc_key == "d_ar"


def test_retrieval_inflation_query(store):
    _seed(store)
    hits = store.retrieve("inflación ipc servicios", k=1)
    assert hits[0][0].doc_key == "d_cpi"


def test_freshness_gate_excludes_old_docs(store):
    store.ingest(MacroDoc("Vieja", "dato macro viejo sobre tasas", source="x",
                          as_of=_today(400), doc_key="old"))
    store.ingest(MacroDoc("Nueva", "dato macro nuevo sobre tasas", source="x",
                          as_of=_today(1), doc_key="new"))
    hits = store.retrieve("tasas macro", k=5, max_age_days=120)
    keys = [d.doc_key for d, _ in hits]
    assert "new" in keys
    assert "old" not in keys


def test_empty_store_returns_no_context(store):
    assert store.build_context("cualquier cosa") == ""


# ------------------------------------------------------------------ #
#  Context block + prompt injection                                   #
# ------------------------------------------------------------------ #

def test_context_block_is_dated(store):
    _seed(store)
    ctx = store.build_context("tasas inflación argentina")
    assert "CONTEXTO MACRO RECIENTE" in ctx
    assert _today(2) in ctx or _today(3) in ctx or _today(5) in ctx
    assert "[" in ctx  # dated stamps


def test_macro_prompt_injects_context():
    from types import SimpleNamespace

    fund = SimpleNamespace(symbol="MSFT", company_name="Microsoft", sector="Technology",
                           industry="Software", is_crypto=False, total_score=70.0,
                           adjusted_score=70.0, moat_classification="Wide", current_price=400.0,
                           roe=38.0, roic=30.0, net_margin=36.0, debt_equity=0.5, pe_ratio=30.0,
                           margin_of_safety_pct=10.0, revenue_cagr_5y=9.0, eps_cagr_5y=11.0)
    tech = SimpleNamespace(signal="BULLISH", rsi_weekly=58.0, price_vs_52w_high_pct=-5.0)

    ctx = "=== CONTEXTO MACRO RECIENTE ===\n- [2026-06-01] Tasa Fed: 4.5%"
    prompt_with = macro_strategist_prompt(fund, tech, ctx)
    prompt_without = macro_strategist_prompt(fund, tech, "")
    assert "CONTEXTO MACRO RECIENTE" in prompt_with
    assert "no inventes datos macro" in prompt_with
    assert "CONTEXTO MACRO RECIENTE" not in prompt_without


def test_macro_query_flags_argentina():
    from types import SimpleNamespace

    fund = SimpleNamespace(symbol="YPF", company_name="YPF", sector="Energy", industry="Oil")
    q = macro_query_for(fund)
    assert "argentina" in q.lower()
