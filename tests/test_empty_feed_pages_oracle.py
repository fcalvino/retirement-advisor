"""A symbol the feed answered with nothing is a failed fetch on every page, not a SELL.

The Screener already routes it to its failures list (``is_empty_feed``,
``tests/test_screener_empty_feed.py``). QA on 2026-09-25 found the other doors
still open: Stock Analysis showed ``ZZZZQX`` — and MSFT with the network down —
as **SELL** and logged it to the track record (ids 1535, 1539 on a copy of the
user's DB), and the Watchlist listed the same SELL at $0.00. The raw input
``AAPL;<b>x</b>`` was even stored verbatim as a symbol.

The oracle is the decision the engine itself makes on the empty result: it is
SELL (the bottom band), so any page that shows or logs it is publishing the
absence of data as a verdict. No network: the analysis is stubbed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from analysis.fundamental import FundamentalResult
from analysis.strategy import RetirementStrategy
from analysis.technical import TechnicalResult
from data.screener_store import is_empty_feed

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/2_Stock_Analysis.py"


def _empty_result(symbol="ZZZZQX"):
    fund = FundamentalResult(symbol=symbol)
    fund.data_quality = {"level": "poor", "stale": False}
    tech = TechnicalResult(symbol=symbol)
    return fund, tech, RetirementStrategy().decide(fund, tech)


def test_precondition_engine_calls_the_empty_result_a_sell():
    fund, _tech, decision = _empty_result()
    assert is_empty_feed(fund)
    assert decision.action == "SELL"


def _stock_page(monkeypatch, target, result=None):
    from analysis import track_record
    from dashboard import shared

    analyse = Mock(return_value=result or _empty_result(target))
    monkeypatch.setattr(shared, "cached_full_analysis", analyse)
    record = Mock()
    monkeypatch.setattr(track_record, "track_record_store", SimpleNamespace(log_recommendation=record))
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.session_state["analysis_target"] = target
    app.run()
    return app, analyse, record


def _page_text(app):
    return " ".join(e.value for e in (*app.markdown, *app.error, *app.warning, *app.info, *app.success))


def test_stock_analysis_does_not_publish_or_log_an_empty_feed(monkeypatch):
    app, _analyse, record = _stock_page(monkeypatch, "ZZZZQX")
    assert not app.exception
    record.assert_not_called()
    assert "SELL" not in _page_text(app)
    assert any("ZZZZQX" in e.value and "datos" in e.value for e in app.error)


def test_stock_analysis_rejects_a_malformed_symbol_before_fetching(monkeypatch):
    app, analyse, record = _stock_page(monkeypatch, "AAPL;<B>X</B>")
    assert not app.exception
    analyse.assert_not_called()
    record.assert_not_called()
    assert app.error


def test_parallel_fetch_drops_an_empty_feed(monkeypatch):
    """Watchlist, Alertas, Optimizer and Backtesting share this fetcher; the
    Watchlist renders a dropped symbol as «⚠️ sin datos» instead of a SELL row."""
    from dashboard import shared

    good = (FundamentalResult(symbol="MSFT", current_price=400.0), TechnicalResult(symbol="MSFT"), None)
    monkeypatch.setattr(
        shared, "cached_full_analysis",
        lambda sym, *a, **kw: good if sym == "MSFT" else _empty_result(sym),
    )
    bar = SimpleNamespace(progress=lambda *_: None)
    text = SimpleNamespace(text=lambda *_: None)
    ai = SimpleNamespace(provider="", model="", enabled=False, api_key="")
    out = shared._fetch_universe_parallel(["MSFT", "ZZZZQX"], ai, bar, text)
    assert [row[0] for row in out] == ["MSFT"]
