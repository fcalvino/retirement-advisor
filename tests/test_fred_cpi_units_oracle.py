"""Oráculo FRED-CPI-NIVEL: la inflación llega al RAG como tasa interanual, no como nivel del índice.

``CPIAUCSL`` es el **nivel** del IPC de EE. UU. (base 1982-84 = 100): 334.131 en
2026-08. Se ingería tal cual, bajo el título «Índice de precios al consumidor IPC», y
en la QA de #179 el Estratega Macro escribió «un entorno de inflación alta (IPC
334.131)»: una cifra real, fechada, y sin sentido como inflación. La API de FRED
devuelve la variación contra el mismo mes del año anterior con ``units=pc1``
(3.35302 para 2026-08, verificado en vivo el 2026-09-27).

Independiente del código bajo prueba: las unidades y los valores salen de la API de
FRED (su parámetro ``units``) y de lo que el ``requests.get`` falso ve pasar.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from analysis.macro_rag import MacroDoc, MacroRagStore, ingest_from_fred
from config import MACRO_RAG, MULTI_SOURCE
from data.data_sources import FredSource, SourceValue

CPI_LEVEL = 334.131   # CPIAUCSL, units=lin, 2026-08
CPI_YOY = 3.35302     # CPIAUCSL, units=pc1, 2026-08
PRICE_INDEX_SERIES = {"CPIAUCSL"}  # niveles de índice: sin transformar no son una tasa


class _Resp:
    status_code = 200

    def __init__(self, value):
        self._value = value

    def json(self):
        return {"observations": [{"date": "2026-08-01", "value": str(self._value)}]}


@pytest.fixture
def fred_http(monkeypatch):
    """``requests.get`` falso: responde según ``units`` y registra cada request."""
    import requests

    calls: list = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params or {}))
        return _Resp(CPI_YOY if (params or {}).get("units") == "pc1" else CPI_LEVEL)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(MULTI_SOURCE, "fred_api_key", "test-key")
    return calls


class _RecordingFred:
    """Stands in for FredSource: records the units asked for each series."""

    def __init__(self, asked: dict):
        self._asked = asked

    def latest_series_value(self, series_id, units="lin"):
        self._asked[series_id] = units
        value = CPI_YOY if (series_id == "CPIAUCSL" and units == "pc1") else CPI_LEVEL
        return SourceValue(series_id, value, "fred", as_of="2026-08-01")


# --------------------------------------------------------------------------- #
#  El transporte                                                               #
# --------------------------------------------------------------------------- #

def test_fred_source_sends_the_units_it_is_asked_for(fred_http):
    sv = FredSource().latest_series_value("CPIAUCSL", units="pc1")
    assert fred_http[-1]["units"] == "pc1"
    assert sv.value == pytest.approx(CPI_YOY)


def test_fred_source_default_request_is_unchanged(fred_http):
    FredSource().latest_series_value("FEDFUNDS")
    assert "units" not in fred_http[-1], "las series que ya son tasas piden lo mismo que antes"


# --------------------------------------------------------------------------- #
#  La config                                                                   #
# --------------------------------------------------------------------------- #

def test_no_price_index_is_ingested_as_a_level():
    units = getattr(MACRO_RAG, "fred_series_units", {})
    for series_id in PRICE_INDEX_SERIES & set(MACRO_RAG.fred_series):
        assert units.get(series_id, "lin") != "lin", f"{series_id} entraría como nivel del índice"


# --------------------------------------------------------------------------- #
#  La ingesta                                                                  #
# --------------------------------------------------------------------------- #

def test_ingest_asks_cpi_as_year_over_year_and_says_so(monkeypatch):
    import data.data_sources as ds

    asked: dict = {}
    monkeypatch.setattr(ds, "FredSource", lambda: _RecordingFred(asked))
    store = MacroRagStore(":memory:")
    ingest_from_fred(store)

    assert asked["CPIAUCSL"] == "pc1"
    assert all(u == "lin" for s, u in asked.items() if s != "CPIAUCSL")
    cpi = next(d for d in store.all_docs() if d.doc_key == "fred:CPIAUCSL")
    text = f"{cpi.title} {cpi.body}"
    assert "interanual" in text
    assert "3.35" in cpi.body
    assert str(CPI_LEVEL) not in cpi.body


def test_ingest_replaces_a_previous_level_doc(monkeypatch):
    import data.data_sources as ds

    store = MacroRagStore(":memory:")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    store.ingest(MacroDoc(
        "Índice de precios al consumidor IPC (FRED)",
        f"Dato macro de FRED. Último valor reportado: {CPI_LEVEL} (serie CPIAUCSL).",
        source="FRED", as_of=today, doc_key="fred:CPIAUCSL",
    ))
    monkeypatch.setattr(ds, "FredSource", lambda: _RecordingFred({}))
    ingest_from_fred(store, {"CPIAUCSL": MACRO_RAG.fred_series["CPIAUCSL"]})

    docs = store.all_docs()
    assert len(docs) == 1
    assert str(CPI_LEVEL) not in docs[0].body
    assert "3.35" in docs[0].body
