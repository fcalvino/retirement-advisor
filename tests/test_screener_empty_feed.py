"""A symbol the feed answered with nothing is a failed fetch, not a SELL.

Measured 2026-09-22 with a made-up ``NODATA.DE``: no exception, an analyzer
result with no price and every metric missing, score 0 → the strategy's bottom
band → **SELL**, shown in the table and logged to the track record as a real
call. The data-quality policy never softens it because it only caps buys.

Drives the real ``_analyse_universe_parallel`` with the analysis stubbed.
No network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from analysis.strategy import Decision
from data.screener_store import EMPTY_FEED_TYPE, is_empty_feed


def _fund(**overrides):
    base = dict(
        company_name="Test Co", sector="Technology", asset_class="equity",
        adjusted_score=70.0, total_score=65.0, consistency_score=10.0,
        piotroski_score=7.0, moat_score=12.0, moat_classification="Wide",
        tailwind_classification="Neutral", tailwind_score=0.0, pe_ratio=18.0,
        roe=22.0, revenue_cagr_5y=8.0, dividend_yield=1.2, margin_of_safety_pct=5.0,
        current_price=100.0, data_quality={"level": "good", "stale": False},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _empty():
    return _fund(company_name="NODATA.DE", sector="Unknown", adjusted_score=0.0,
                 total_score=0.0, current_price=0.0,
                 data_quality={"level": "poor", "stale": False})


# --------------------------------------------------------------------------- #
#  The rule                                                                   #
# --------------------------------------------------------------------------- #

def test_no_price_and_poor_data_is_empty():
    assert is_empty_feed(_empty())
    assert is_empty_feed(_fund(current_price=None, data_quality={"level": "poor"}))


@pytest.mark.parametrize("fund", [
    _fund(),                                                       # healthy
    _fund(data_quality={"level": "poor"}),                         # poor but priced
    _fund(current_price=0.0, data_quality={"level": "partial"}),   # no price, some data
    _fund(current_price=0.0, data_quality={"level": "poor"}, asset_class="crypto"),
    _fund(current_price=0.0, data_quality={"level": "poor"}, is_crypto=True),
    _fund(current_price=0.0, data_quality=None),                   # quality unknown
])
def test_anything_else_is_not_empty(fund):
    assert not is_empty_feed(fund)


# --------------------------------------------------------------------------- #
#  The Screener row builder                                                   #
# --------------------------------------------------------------------------- #

class _Bar:
    def progress(self, *_a, **_k):
        return None


class _Status:
    def text(self, *_a, **_k):
        return None


def _run(monkeypatch, funds: dict):
    from dashboard import shared as shared_mod

    def fake_analysis(sym, *_a, **_k):
        return funds[sym], SimpleNamespace(signal="NEUTRAL"), Decision(
            symbol=sym, action="SELL" if funds[sym].adjusted_score == 0 else "BUY",
            confidence="LOW",
        )

    monkeypatch.setattr(shared_mod, "cached_full_analysis", fake_analysis)
    return shared_mod._analyse_universe_parallel(
        list(funds), SimpleNamespace(provider="x", model="y", enabled=False, api_key=""),
        _Bar(), _Status(),
    )


def test_empty_symbol_becomes_a_failure_not_a_sell_row(monkeypatch):
    rows, failures, _ = _run(monkeypatch, {"NODATA.DE": _empty(), "SAP.DE": _fund()})
    assert [r["Ticker"] for r in rows] == ["SAP.DE"]
    assert len(failures) == 1
    assert failures[0]["Ticker"] == "NODATA.DE"
    assert failures[0]["Tipo"] == EMPTY_FEED_TYPE
    assert failures[0]["Error"]


def test_empty_symbol_never_reaches_the_track_record(monkeypatch, tmp_path):
    from analysis.track_record import TrackRecordStore
    from dashboard.shared import log_screener_run

    store = TrackRecordStore(db_path=str(tmp_path / "t.db"))
    monkeypatch.setattr("analysis.track_record.track_record_store", store)
    rows, _, _ = _run(monkeypatch, {"NODATA": _empty()})
    assert rows == []
    assert log_screener_run(rows) == 0
    assert store.get_recommendations(limit=10) == []


def test_a_priced_poor_quality_stock_is_still_a_row(monkeypatch):
    rows, failures, _ = _run(monkeypatch, {"X": _fund(data_quality={"level": "poor"})})
    assert failures == [] and [r["Ticker"] for r in rows] == ["X"]
