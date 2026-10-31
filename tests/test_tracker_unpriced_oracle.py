"""AUDIT-NUMB-2 — a position the market has no price for is not valued at its cost.

``get_current_values`` used ``info.get("currentPrice") or ... or pos.avg_cost``: a ticker whose feed
returned nothing was priced at what it cost, so it showed +0 %, added a number nobody observed to the
total value, and diluted every weight — and the Alertas page then wrote that cost down as the price
(``vals.get("current_price", pos.avg_cost)``), defeating the U2-3 guard that leaves an unknown quote
out of the detector.

Rule: no quote → the row carries ``priced: False`` and ``None`` (never 0, never the cost); the totals
are those of the priced positions; the weights are over the priced ones and the unpriced one is
absent (the page shows «—»); every decision that reads the weights (drift, rebalancing,
concentration, sizing, the committee) gets ``{}`` with ``require_complete=True`` and says which
symbols are missing.

Expected figures are written by hand from the book below. Prices injected, no network.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import portfolio.tracker as tracker_mod
from portfolio.tracker import (
    Portfolio,
    Position,
    position_weights_from,
    priced_values,
    sector_weights_from,
    unpriced_symbols,
)

VIEWS = Path(__file__).resolve().parents[1] / "dashboard" / "views"

#: AAPL 10 sh @150 (cost 1500) → 2000;  KO 100 sh @50 (cost 5000) → 6000;  ZZZ 4 sh @25 (cost 100), no quote.
QUOTES = {
    "AAPL": {"currentPrice": 200.0, "sector": "Technology"},
    "KO": {"currentPrice": 60.0, "sector": "Consumer Defensive"},
    "ZZZ": {"sector": "Energy"},
}


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: dict(QUOTES.get(sym, {})))
    monkeypatch.setattr(tracker_mod, "get_history", lambda *a, **k: pd.DataFrame())
    p = Portfolio(file_path=tmp_path / "portfolio.json")
    p.positions["AAPL"] = Position("AAPL", 10, 150.0, "2024-01-15", sector="Technology")
    p.positions["KO"] = Position("KO", 100, 50.0, "2024-01-15", sector="Consumer Defensive")
    p.positions["ZZZ"] = Position("ZZZ", 4, 25.0, "2024-01-15", sector="Energy")
    return p


# --- the row --------------------------------------------------------------------------------------

def test_the_unpriced_row_has_nones_and_not_the_cost(book):
    row = book.get_current_values()["ZZZ"]
    assert row["priced"] is False
    assert row["current_price"] is None            # not 25.0 = avg_cost
    assert row["market_value"] is None             # not 100.0
    assert row["pnl"] is None and row["pnl_pct"] is None   # not +0 %
    assert row["cost_basis"] == pytest.approx(100.0)


def test_a_priced_row_is_valued_as_before(book):
    row = book.get_current_values()["AAPL"]
    assert row["priced"] is True
    assert row["current_price"] == 200.0
    assert row["market_value"] == pytest.approx(2000.0)
    assert row["pnl"] == pytest.approx(500.0)
    assert row["pnl_pct"] == pytest.approx(500.0 / 1500.0 * 100)


@pytest.mark.parametrize("info", [
    {},
    {"currentPrice": 0},
    {"currentPrice": None, "regularMarketPrice": None},
    {"currentPrice": -3.0},
    {"currentPrice": float("nan")},
    {"currentPrice": float("inf")},
    {"currentPrice": "N/A"},
])
def test_what_the_feed_may_return_instead_of_a_quote(book, monkeypatch, info):
    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: dict(info))
    assert unpriced_symbols(book.get_current_values()) == ["AAPL", "KO", "ZZZ"]


def test_the_second_quote_field_is_a_quote(book, monkeypatch):
    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {"currentPrice": 0, "regularMarketPrice": 61.0})
    row = book.get_current_values()["KO"]
    assert row["priced"] is True and row["current_price"] == 61.0


# --- the totals -----------------------------------------------------------------------------------

def test_the_totals_are_those_of_the_priced_positions(book):
    m = book.compute_metrics()
    assert m.unpriced_symbols == ["ZZZ"]
    assert m.num_positions == 3                     # the book still has three positions
    assert m.total_value == pytest.approx(8000.0)   # 2000 + 6000, not 8100
    assert m.total_cost == pytest.approx(6500.0)    # 1500 + 5000, not 6600
    assert m.total_pnl == pytest.approx(1500.0)
    assert m.total_pnl_pct == pytest.approx(1500.0 / 6500.0 * 100)


def test_a_complete_book_has_nothing_unpriced(book, monkeypatch):
    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {"currentPrice": 10.0, "sector": "X"})
    m = book.compute_metrics()
    assert m.unpriced_symbols == []
    assert m.total_value == pytest.approx(10.0 * (10 + 100 + 4))


def test_a_book_with_no_quote_at_all_has_zero_totals_and_names_everyone(book, monkeypatch):
    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {})
    m = book.compute_metrics()
    assert m.unpriced_symbols == ["AAPL", "KO", "ZZZ"]
    assert m.total_value == 0.0 and m.total_cost == 0.0
    assert book.get_position_weights() == {} and book.get_sector_weights() == {}


# --- the weights ----------------------------------------------------------------------------------

def test_weights_are_over_the_priced_positions_and_the_unpriced_one_is_absent(book):
    assert book.get_position_weights() == {"AAPL": 25.0, "KO": 75.0}     # no "ZZZ": 0 % would be a lie
    assert book.get_sector_weights() == {"Consumer Defensive": 75.0, "Technology": 25.0}


def test_a_decision_gets_no_weights_at_all_while_a_position_is_unpriced(book):
    assert book.get_position_weights(require_complete=True) == {}
    assert book.get_sector_weights(require_complete=True) == {}


def test_require_complete_changes_nothing_on_a_complete_book(book, monkeypatch):
    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {"currentPrice": 10.0, "sector": "X"})
    assert book.get_position_weights(require_complete=True) == book.get_position_weights()
    assert sorted(book.get_position_weights(require_complete=True)) == ["AAPL", "KO", "ZZZ"]


def test_the_weight_helpers_work_on_the_rows_the_pages_already_hold(book):
    values = book.get_current_values()
    assert position_weights_from(values) == {"AAPL": 25.0, "KO": 75.0}
    assert position_weights_from(values, require_complete=True) == {}
    assert sector_weights_from(values, require_complete=True) == {}
    assert set(priced_values(values)) == {"AAPL", "KO"}


# --- the notice -----------------------------------------------------------------------------------

def test_the_notice_names_the_symbols_and_says_what_is_left_out():
    from data.product_ux import unpriced_positions_notice

    one = unpriced_positions_notice(["ZZZ"], "Los pesos esperan.")
    assert "ZZZ" in one and "no se valúan a su costo" in one and "Los pesos esperan." in one
    many = unpriced_positions_notice(["ZZZ", "QQQ"])
    assert "ZZZ, QQQ" in many and "posiciones" in many
    assert unpriced_positions_notice([]) == ""
    assert unpriced_positions_notice(None) == ""


# --- the pages ------------------------------------------------------------------------------------

def _page(book, name):
    app = AppTest.from_file(str(VIEWS / name), default_timeout=60)
    app.session_state["portfolio"] = book
    app.run()
    assert not app.exception
    return app


def _texts(app):
    return [e.value for e in (*app.warning, *app.info, *app.caption)]


def test_the_portfolio_page_names_the_unpriced_symbol_and_does_not_value_it(book):
    app = _page(book, "3_Portfolio.py")
    assert any("ZZZ" in t and "Sin cotización" in t for t in (w.value for w in app.warning))
    totals = {m.label: m.value for m in app.metric}
    assert totals["Valor total"] == "$8,000"        # not $8,100
    assert totals["P&L total"] == "$1,500"          # not the +0 of a position valued at cost


def test_the_portfolio_page_computes_no_drift_and_convenes_no_committee_on_an_incomplete_book(book, monkeypatch):
    """Drift, trades, sizing and the committee read the whole book: with ZZZ unpriced they wait."""
    from types import SimpleNamespace

    import data.plan_context as plan_context

    plan = SimpleNamespace(id="mine", name="Mi plan", core_holdings=[], target_weights=lambda: {"AAPL": 50.0, "KO": 50.0})
    monkeypatch.setattr(plan_context, "get_active_plan", lambda *a, **k: plan)
    app = AppTest.from_file(str(VIEWS / "3_Portfolio.py"), default_timeout=60)
    app.session_state["portfolio"] = book
    app.session_state["ai_enabled"] = True
    app.run()
    assert not app.exception
    assert "Deriva total" not in {m.label for m in app.metric}
    assert not [b for b in app.button if "Convocar al comité" in b.label]
    texts = [e.value for e in (*app.warning, *app.info)]
    # Text unique to each gate: the header warning also names ZZZ, "deriva" and "sizing".
    assert any("ZZZ" in t and "ni los trades sugeridos" in t for t in texts)
    assert any("ZZZ" in t and "El comité espera" in t for t in texts)
    [run] = [b for b in app.button if "análisis de sizing" in b.label]
    run.click().run()
    assert not app.exception
    assert any("ZZZ" in w.value and "no se calcula hasta que todas" in w.value for w in app.warning)
    assert "_personal_book_analysis" not in app.session_state


def test_the_portfolio_page_with_a_complete_book_still_computes_the_drift(book, monkeypatch):
    from types import SimpleNamespace

    import data.plan_context as plan_context

    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {"currentPrice": 100.0, "sector": "X"})
    plan = SimpleNamespace(id="mine", name="Mi plan", core_holdings=[], target_weights=lambda: {"AAPL": 50.0, "KO": 50.0})
    monkeypatch.setattr(plan_context, "get_active_plan", lambda *a, **k: plan)
    monkeypatch.setattr("dashboard.shared.plan_price_lookup", lambda sym: 100.0)    # no network
    app = AppTest.from_file(str(VIEWS / "3_Portfolio.py"), default_timeout=60)
    app.session_state["portfolio"] = book
    app.run()
    assert not app.exception
    assert "Deriva total" in {m.label for m in app.metric}


def test_the_allocation_page_does_not_evaluate_concentration_on_an_incomplete_book(book, monkeypatch):
    from data.preferences import UserPreferences
    from portfolio.allocation import AllocationAdvisor

    seen = {}
    real = AllocationAdvisor.advise

    def spy(self, age, retirement_age, sector_weights, position_weights, **kw):
        seen["sector"], seen["position"] = sector_weights, position_weights
        return real(self, age, retirement_age, sector_weights, position_weights, **kw)

    monkeypatch.setattr(AllocationAdvisor, "advise", spy)
    prefs = UserPreferences()
    prefs.choose_profile("Moderado")
    app = AppTest.from_file(str(VIEWS / "4_Allocation.py"), default_timeout=60)
    app.session_state["portfolio"] = book
    app.session_state["user_prefs"] = prefs
    app.run()
    assert not app.exception
    assert any("ZZZ" in w.value for w in app.warning)
    assert seen == {"sector": {}, "position": {}}      # not the weights of the two priced ones


def test_the_alerts_page_does_not_write_the_cost_down_as_a_price(book, monkeypatch):
    """The U2-3 guard leaves an unknown quote out of the detector; the page had defeated it."""
    from alerts import store
    from dashboard import shared

    monkeypatch.setattr(store, "alert_store", store.AlertStore(db_path=book.file_path.parent / "alerts.db"))
    seen = {}

    def fake_engine(scored, *, active_profile, positions=None, current_prices=None, optimizer_weights=None):
        seen["positions"], seen["current_prices"] = positions, current_prices
        return []

    monkeypatch.setattr(shared, "_fetch_universe_parallel", lambda *a, **k: [])
    monkeypatch.setattr(shared, "run_alert_engine", fake_engine)
    app = AppTest.from_file(str(VIEWS / "8_Alertas.py"), default_timeout=60)
    app.session_state["portfolio"] = book
    app.session_state["universe"] = ["AAPL"]
    app.run()
    assert not app.exception
    [run] = [b for b in app.button if "Ejecutar análisis ahora" in b.label]
    run.click().run()
    assert not app.exception
    assert seen["current_prices"] == {"AAPL": 200.0, "KO": 60.0}     # no "ZZZ": 25.0 = its cost
    assert set(seen["positions"]) == {"AAPL", "KO", "ZZZ"}


# --- review findings ------------------------------------------------------------------------------

def test_the_annualized_return_takes_its_age_from_the_priced_positions(book, monkeypatch):
    """An old position outside the totals must not set the exponent of a value it is not part of."""
    from datetime import datetime, timedelta

    def ago(days):
        return (datetime.now() - timedelta(days=days)).date().isoformat()

    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {"currentPrice": 110.0} if sym == "A" else {})
    book.positions.clear()
    book.positions["A"] = Position("A", 10, 100.0, ago(800))
    alone = book.compute_metrics().annualized_return_pct
    book.positions["Z"] = Position("Z", 10, 100.0, ago(4000))        # unpriced and much older
    m = book.compute_metrics()
    assert m.unpriced_symbols == ["Z"]
    assert m.annualized_return_pct == pytest.approx(alone)
    assert m.annualized_return_pct == pytest.approx((1.10 ** (365.25 / 800) - 1) * 100, rel=1e-9)


def test_the_portfolio_page_shows_dashes_not_zero_when_nothing_has_a_quote(book, monkeypatch):
    monkeypatch.setattr(tracker_mod, "get_info", lambda sym: {})
    app = _page(book, "3_Portfolio.py")
    totals = {m.label: m.value for m in app.metric}
    assert totals["Valor total"] == "—" and totals["P&L total"] == "—"


def test_a_committee_verdict_from_a_priced_book_is_not_shown_on_an_incomplete_one(book, monkeypatch):
    """Its footer would read «posición máx 0%» from the empty weights."""
    from analysis.committee import AgentOpinion, aggregate

    verdict = aggregate("portfolio", [AgentOpinion("Gestor de Riesgo", "HOLD", "MEDIUM")])
    app = AppTest.from_file(str(VIEWS / "3_Portfolio.py"), default_timeout=60)
    app.session_state["portfolio"] = book
    app.session_state["ai_enabled"] = True
    app.session_state["holdings_committee_verdict"] = verdict
    app.run()
    assert not app.exception
    assert not any("posición máx" in e.value for e in (*app.caption, *app.markdown))


def test_the_personal_sizer_refuses_a_book_with_an_unpriced_row(book):
    from portfolio.personal_sizer import analyze_personal_book

    with pytest.raises(ValueError, match="ZZZ"):
        analyze_personal_book(book.get_current_values(), convictions={}, enrich_fn=lambda s: {})


def test_the_committee_page_gives_the_pm_no_book_when_a_position_is_unpriced(book, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from analysis import committee, track_record
    from analysis.ai_analyzer import AIAnalyzer
    from analysis.eval_cases import golden_cases
    from dashboard import shared

    case = golden_cases()[0]
    monkeypatch.setattr(shared, "cached_full_analysis", lambda *a, **kw: (case.fund, case.tech, None))
    monkeypatch.setattr(committee.CommitteeAnalyzer, "_get_cached", lambda *a: None)
    # Any provider failure: the test is about the context the page builds before the panel runs.
    monkeypatch.setattr(AIAnalyzer, "_call_api", Mock(side_effect=RuntimeError("sin red")))
    monkeypatch.setattr(track_record, "track_record_store", SimpleNamespace(log_recommendation=Mock()))
    spy = Mock(return_value=None)
    monkeypatch.setattr(committee, "build_ticker_portfolio_context", spy)
    app = AppTest.from_file(str(VIEWS / "15_Comite.py"), default_timeout=30)
    for key, value in dict(ai_enabled=True, ai_provider="groq", ai_model="openai/gpt-oss-120b", ai_api_key="k").items():
        app.session_state[key] = value
    app.session_state["portfolio"] = book
    app.run()
    next(b for b in app.button if "Convocar" in b.label).click().run()
    assert not app.exception
    spy.assert_not_called()                                    # the weights of an incomplete book
    assert any("ZZZ" in c.value and "El PM opina sin tu cartera" in c.value for c in app.caption)
