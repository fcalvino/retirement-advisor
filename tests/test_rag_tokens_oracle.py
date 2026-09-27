"""Oráculo RAG-TOKENS: los hechos de FRED llegan al prompt sin depender de la consulta.

``MacroRagStore.retrieve`` puntúa por coincidencia exacta de palabras (TF-IDF sin
stemming): «tasas» no encuentra «Tasa de fondos federales». El comité por ticker
recibía las 4 series sólo porque su consulta trae «macro» (palabra que está en todo
body de FRED); la del comité de cartera no la trae y recibía **sólo la inflación**.
Decisión del usuario (2026-09-27): los docs de FRED frescos y no-seed entran siempre.

Independiente del código bajo prueba: los docs los escribe el ``ingest_from_fred`` real
a partir de un ``requests.get`` falso (el patrón de ``test_fred_cpi_units_oracle.py``),
y lo que se afirma es la presencia de cada título de ``MACRO_RAG.fred_series`` en el
bloque que llega al prompt.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from analysis.macro_rag import (
    MacroDoc,
    MacroRagStore,
    example_macro_docs,
    ingest_from_fred,
    macro_query_for,
    portfolio_macro_query,
)
from config import MACRO_RAG, MULTI_SOURCE
from data.clock import utc_now

#: Valores de 2026-08/09 vistos en la ingesta real del 2026-09-27.
FRED_VALUES = {"FEDFUNDS": 3.63, "CPIAUCSL": 3.35302, "DGS10": 5.18, "A191RL1Q225SBEA": 1.5}
FRED_TITLES = list(MACRO_RAG.fred_series.values())

#: La consulta que la página Macro RAG trae de ejemplo: devolvía 0 docs.
PAGE_EXAMPLE_QUERY = "tecnología tasas valuación"


class _Resp:
    status_code = 200

    def __init__(self, value):
        self._value = value

    def json(self):
        return {"observations": [{"date": "2026-08-01", "value": str(self._value)}]}


@pytest.fixture
def fred_http(monkeypatch):
    import requests

    def fake_get(url, params=None, timeout=None):
        return _Resp(FRED_VALUES[(params or {})["series_id"]])

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(MULTI_SOURCE, "fred_api_key", "test-key")


@pytest.fixture
def store(fred_http):
    s = MacroRagStore(db_path=":memory:")
    assert ingest_from_fred(s) == len(MACRO_RAG.fred_series)
    return s


def _missing(block: str) -> list:
    return [t for t in FRED_TITLES if t not in block]


# --------------------------------------------------------------------------- #
#  Las consultas                                                               #
# --------------------------------------------------------------------------- #

def test_portfolio_committee_query_gets_every_fred_series(store):
    block = store.build_context(portfolio_macro_query({"Technology": 40.0, "Healthcare": 20.0}))
    assert _missing(block) == []


def test_portfolio_query_with_no_sectors_gets_every_fred_series(store):
    assert _missing(store.build_context(portfolio_macro_query({}))) == []


def test_the_macro_rag_page_example_query_gets_every_fred_series(store):
    assert _missing(store.build_context(PAGE_EXAMPLE_QUERY)) == []


def test_ticker_query_keeps_every_fred_series(store):
    """Control: la consulta por ticker ya las traía, y las sigue trayendo."""
    from types import SimpleNamespace

    fund = SimpleNamespace(symbol="MSFT", sector="Technology", industry="Software",
                           company_name="Microsoft")
    assert _missing(store.build_context(macro_query_for(fund))) == []


# --------------------------------------------------------------------------- #
#  Lo que la regla no cambia                                                   #
# --------------------------------------------------------------------------- #

def test_a_stale_fred_doc_does_not_get_in(fred_http):
    s = MacroRagStore(db_path=":memory:")
    old = utc_now() - timedelta(days=MACRO_RAG.max_age_days + 5)
    ingest_from_fred(s, now=old)
    assert s.build_context(portfolio_macro_query({"Technology": 50.0})) == ""


def test_seed_docs_stay_out(store):
    store.ingest_many(example_macro_docs())
    block = store.build_context(PAGE_EXAMPLE_QUERY)
    assert _missing(block) == []
    for seed in example_macro_docs():
        assert seed.body not in block


def test_other_docs_still_compete_on_relevance(store):
    today = utc_now().strftime("%Y-%m-%d")
    store.ingest_many([
        MacroDoc("Riesgo país Argentina", "El riesgo país argentino subió 120 puntos.",
                 source="BCRA", as_of=today, doc_key="news:ar"),
        MacroDoc("Cosecha de soja", "Récord de cosecha de soja en Brasil.",
                 source="agro", as_of=today, doc_key="news:soja"),
    ])
    block = store.build_context(portfolio_macro_query({"Financial Services": 30.0}))
    assert _missing(block) == []
    assert "riesgo país argentino" in block
    assert "soja" not in block


def test_fred_docs_survive_the_context_cap(store, monkeypatch):
    """Van primero: el recorte de ``max_context_chars`` corta lo recuperado, no a FRED."""
    today = utc_now().strftime("%Y-%m-%d")
    store.ingest(MacroDoc("Tasas cartera retiro inflación riesgo país", "x " * 400,
                          source="nota", as_of=today, doc_key="news:long"))
    block = store.build_context(portfolio_macro_query({"Technology": 50.0}))
    assert _missing(block) == []
    assert len(block) <= MACRO_RAG.max_context_chars + len("\n- […]")


def test_fred_ingest_prefix_is_the_pinned_one():
    from analysis.macro_rag import FRED_DOC_KEY_PREFIX

    assert FRED_DOC_KEY_PREFIX in MACRO_RAG.pinned_doc_key_prefixes


# --------------------------------------------------------------------------- #
#  El comité de cartera, de punta a punta                                      #
# --------------------------------------------------------------------------- #

def test_the_portfolio_macro_strategist_sees_every_fred_series(store, monkeypatch):
    import json
    from types import SimpleNamespace

    import analysis.macro_rag as macro_rag
    from analysis.committee import MACRO_VOTE_ROLE, CommitteeAnalyzer, run_holdings_committee

    monkeypatch.setattr(macro_rag, "macro_rag_store", store)
    prompts: list = []

    def fake_call(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps({"stance": "HOLD", "confidence": "MEDIUM",
                           "key_points": ["p"], "concerns": ["c"]})

    monkeypatch.setattr(CommitteeAnalyzer, "_make_api_call_fn", staticmethod(lambda _cfg: fake_call))
    verdict = run_holdings_committee(
        metrics=SimpleNamespace(total_value=100_000.0),
        sector_weights={"Technology": 61.3, "Healthcare": 38.7},
        position_weights={"RAGTOK1": 61.3, "RAGTOK2": 38.7},
        total_value=100_000.0,
        ai_config=SimpleNamespace(enabled=True, provider="test", model="rag-tokens"),
    )
    assert verdict is not None
    macro_prompts = [p for p in prompts if MACRO_VOTE_ROLE in p]
    assert len(macro_prompts) == 1, "el Estratega Macro tiene que ser convocado"
    assert _missing(macro_prompts[0]) == []
