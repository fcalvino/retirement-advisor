"""SA-TR-CAPTION: Stock Analysis dice qué pasó en el track record.

La página llamaba a ``log_recommendation`` y descartaba el resultado. Con 7203.T
y AIR.PA mostraba BUY y el log decía «not logged — cotiza en JPY/EUR»; con un
segundo análisis el mismo día, el dedup tampoco se avisaba. El Comité ya lo decía
desde LLM-2: ahora las dos páginas usan el mismo caption
(``dashboard.shared.track_record_log_caption``), armado con lo que devolvió el
store, ``admission_skip_reason`` y el dedup por fuente (TR-DEDUP-SOURCE).

Sin red: el análisis está stubbeado y el store es uno real en un temporal.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import portfolio.tracker as tracker_mod
from analysis.eval_cases import golden_cases
from analysis.strategy import RetirementStrategy
from analysis.track_record import TrackRecordStore
from portfolio.tracker import Portfolio

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/2_Stock_Analysis.py"


@pytest.fixture
def store(tmp_path):
    return TrackRecordStore(db_path=str(tmp_path / "tr.db"))


def _stock_page(monkeypatch, tmp_path, store, symbol, currency, price):
    from analysis import track_record
    from dashboard import shared

    case = golden_cases()[0]
    fund = replace(case.fund, symbol=symbol, currency=currency, current_price=price)
    decision = RetirementStrategy().decide(fund, case.tech)
    monkeypatch.setattr(shared, "cached_full_analysis", lambda *a, **k: (fund, case.tech, decision))
    monkeypatch.setattr(track_record, "track_record_store", store)
    monkeypatch.setattr(
        tracker_mod, "get_info", lambda s: {"currentPrice": price, "currency": currency}
    )
    monkeypatch.setattr(shared, "get_price_history", lambda *a, **k: pd.DataFrame())
    app = AppTest.from_file(str(PAGE), default_timeout=60)
    app.session_state["analysis_target"] = symbol
    app.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
    app.run()
    assert not app.exception
    return app, decision


def _captions(app) -> str:
    return "\n".join(c.value for c in app.caption)


def test_a_logged_recommendation_says_so(monkeypatch, tmp_path, store):
    app, decision = _stock_page(monkeypatch, tmp_path, store, "AAPL", "USD", 200.0)
    rows = store.get_recommendations()
    assert [(r.symbol, r.source) for r in rows] == [("AAPL", "rule_based")]
    assert (
        f"AAPL quedó registrado en el Track Record con fuente `rule_based` como "
        f"{decision.action}." in _captions(app)
    )


def test_a_foreign_quote_is_not_logged_and_the_page_says_why(monkeypatch, tmp_path, store):
    app, _ = _stock_page(monkeypatch, tmp_path, store, "7203.T", "JPY", 3025.0)
    assert store.get_recommendations() == []
    text = _captions(app)
    assert "No se registra en el Track Record: 7203.T" in text and "JPY" in text
    assert "quedó registrado" not in text


def test_a_second_run_the_same_day_names_the_dedup(monkeypatch, tmp_path, store):
    _stock_page(monkeypatch, tmp_path, store, "AAPL", "USD", 200.0)
    app, decision = _stock_page(monkeypatch, tmp_path, store, "AAPL", "USD", 200.0)
    assert len(store.get_recommendations()) == 1
    text = _captions(app)
    assert "quedó registrado" not in text
    assert (
        f"ya hay un {decision.action} de AAPL registrado hoy por el análisis por reglas"
        in text
    )


def test_a_screener_row_does_not_hide_the_page_row(monkeypatch, tmp_path, store):
    """TR-DEDUP-SOURCE desde esta página: lo que el Screener ya registró hoy no
    tapa la recomendación que el usuario miró."""
    case = golden_cases()[0]
    fund = replace(case.fund, symbol="AAPL", currency="USD", current_price=200.0)
    decision = RetirementStrategy().decide(fund, case.tech)
    assert store.log_recommendation(decision, source="screener", fundamental=fund)

    app, _ = _stock_page(monkeypatch, tmp_path, store, "AAPL", "USD", 200.0)
    assert sorted(r.source for r in store.get_recommendations()) == ["rule_based", "screener"]
    assert "quedó registrado en el Track Record" in _captions(app)
