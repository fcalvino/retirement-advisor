"""PORTFOLIO-CCY: a position quoted in another currency does not enter the book.

«➕ Agregar al Portfolio» in Stock Analysis prefilled ``fund.current_price`` —
the local price — into a field labelled «Costo promedio (USD)», and
``Portfolio.add_position`` stored it as such. For 7203.T that is a position of
3025 **dollars** a share. The defect is wider than the cost: the tracker values
every position at its own quote (``get_current_values``) and ``compute_metrics``
and the weights add those values up as dollars, so the total, the concentration
and the drift all read yen as dollars.

Converting needs an FX decision that is still open (#154). Until then the book
only admits its own currency — one rule, in the store, that the page repeats.
What the feed does not say does not block, same contract as the track record's
``admission_skip_reason`` (LLM-2). No network: prices and sectors are stubbed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import portfolio.tracker as tracker_mod
from analysis.eval_cases import golden_cases
from analysis.strategy import RetirementStrategy
from portfolio.tracker import Portfolio, Position

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/2_Stock_Analysis.py"

#: symbol → (quote, currency the feed reports; None = the feed does not say)
QUOTES = {
    "AAPL": (200.0, "USD"),
    "7203.T": (3025.0, "JPY"),
    "AZN.L": (11_000.0, "GBp"),
    "NOCCY": (50.0, None),
}


def _info(sym):
    price, ccy = QUOTES[sym]
    info = {"currentPrice": price, "sector": "Test"}
    if ccy is not None:
        info["currency"] = ccy
    return info


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_mod, "get_info", _info)
    monkeypatch.setattr(tracker_mod, "get_history", lambda *a, **k: pd.DataFrame())
    return Portfolio(file_path=tmp_path / "portfolio.json")


def test_precondition_a_foreign_quote_is_summed_as_dollars(book):
    """Why it matters: once in, 10 Toyota shares weigh as 30 250 «dollars»."""
    book.positions["AAPL"] = Position("AAPL", 10, 200.0, "2024-01-15")
    book.positions["7203.T"] = Position("7203.T", 10, 3025.0, "2024-01-15")
    assert book.compute_metrics().total_value == pytest.approx(10 * 200.0 + 10 * 3025.0)
    assert book.get_position_weights()["7203.T"] > 90


@pytest.mark.parametrize("sym, ccy", [("7203.T", "JPY"), ("AZN.L", "GBp")])
def test_a_position_in_another_currency_is_not_added(book, sym, ccy):
    reason = book.add_position(sym, 10, QUOTES[sym][0], "2024-01-15")
    assert book.positions == {}
    assert not book.file_path.exists()
    assert reason and ccy in reason


def test_it_does_not_average_into_a_held_symbol_either(book):
    book.positions["7203.T"] = Position("7203.T", 10, 20.0, "2024-01-15")
    assert book.add_position("7203.T", 10, 3025.0, "2024-06-15")
    assert book.positions["7203.T"].shares == 10
    assert book.positions["7203.T"].avg_cost == 20.0


# Controls: green before and after.
def test_a_usd_position_is_added(book):
    assert book.add_position("AAPL", 10, 200.0, "2024-01-15") is None
    assert book.positions["AAPL"].cost_basis == 2_000.0
    assert book.file_path.exists()


def test_an_unknown_currency_does_not_block(book):
    assert book.add_position("NOCCY", 10, 50.0, "2024-01-15") is None
    assert "NOCCY" in book.positions


def test_averaging_a_usd_position_is_unchanged(book):
    book.add_position("AAPL", 10, 100.0, "2024-01-15")
    book.add_position("AAPL", 30, 200.0, "2024-06-15")
    assert book.positions["AAPL"].shares == 40
    assert book.positions["AAPL"].avg_cost == pytest.approx(175.0)


# The page says what the store does.
def _stock_page(monkeypatch, tmp_path, symbol, currency, price):
    from analysis import track_record
    from dashboard import shared

    case = golden_cases()[0]
    fund = replace(case.fund, symbol=symbol, currency=currency, current_price=price)
    decision = RetirementStrategy().decide(fund, case.tech)
    monkeypatch.setattr(shared, "cached_full_analysis", lambda *a, **k: (fund, case.tech, decision))
    monkeypatch.setattr(track_record, "track_record_store", SimpleNamespace(log_recommendation=Mock()))
    monkeypatch.setattr(tracker_mod, "get_info", _info)
    app = AppTest.from_file(str(PAGE), default_timeout=60)
    app.session_state["analysis_target"] = symbol
    app.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
    app.run()
    assert not app.exception
    return app


def _add_buttons(app):
    return [b for b in app.button if b.label == "Agregar posición"]


def test_the_page_does_not_offer_a_foreign_position(monkeypatch, tmp_path):
    app = _stock_page(monkeypatch, tmp_path, "7203.T", "JPY", 3025.0)
    assert not _add_buttons(app)
    assert not [n for n in app.number_input if "USD" in n.label]
    assert any("JPY" in e.value for e in (*app.info, *app.warning))


def test_the_page_still_offers_a_usd_position(monkeypatch, tmp_path):
    app = _stock_page(monkeypatch, tmp_path, "AAPL", "USD", 200.0)
    assert _add_buttons(app)
