"""A screener run becomes calibration evidence.

Capture used to happen only when a person opened a ticker, ran the committee, or an
alert fired. Measured on 2026-08-22, that produced 57 recommendations over two months
across **15 of 149 tickers**, distributed 36 BUY / 12 STRONG BUY / 8 HOLD / 1 REDUCE /
**0 SELL**. You cannot calibrate where to draw a line when one side of it has no
observations, and no amount of waiting fixes a sample that only ever records the
tickers someone felt like clicking on.

A full run is the unbiased sample: every ticker, every verdict, including the ones
nobody would have looked at. They carry ``source="screener"`` so they never
masquerade as recommendations the user actually saw.

The round-trip is the subtle part and gets its own tests: the row builder runs inside
a thread pool, so it snapshots the raw inputs and the page rebuilds a stand-in later.
Storing the *processed* fields instead would silently drop the industry metrics.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from analysis.track_record import (
    TrackRecordStore,
    calibration_fields,
    snapshot_calibration_inputs,
)
from dashboard.shared import _track_payload, log_screener_run

# --------------------------------------------------------------------------- #
#  Fixtures                                                                   #
# --------------------------------------------------------------------------- #

def _fund(symbol="O", sector="Real Estate", asset_class="equity", **extra):
    base = dict(
        symbol=symbol,
        company_name="Test Co",
        sector=sector,
        industry="REIT - Retail",
        asset_class=asset_class,
        current_price=57.0,
        adjusted_score=68.0,
        profitability_score=12.0,
        health_score=6.0,
        valuation_score=8.0,
        growth_score=10.0,
        dividend_score=9.0,
        debt_equity=1.35,
        p_ffo=16.5,
        ffo_payout_pct=70.2,
        roe=8.4,
        roic=5.1,
        moat_score=11.0,
        negative_equity=False,
        equity_to_assets_pct=41.2,
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _decision(action="BUY"):
    return SimpleNamespace(
        symbol="O", action=action, confidence="HIGH",
        fundamental_score=68.0, technical_signal="BULLISH",
        rationale=["uno", "dos", "tres", "cuatro", "cinco"],
    )


def _row(fund=None, decision=None):
    fund = fund or _fund()
    decision = decision or _decision()
    return {"Ticker": fund.symbol, "_track": _track_payload(fund, decision)}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    s = TrackRecordStore(db_path=str(tmp_path / "t.db"))
    monkeypatch.setattr("analysis.track_record.track_record_store", s)
    return s


# --------------------------------------------------------------------------- #
#  The snapshot round-trip                                                    #
# --------------------------------------------------------------------------- #

class TestSnapshotRoundTrip:
    def test_a_rebuilt_stand_in_yields_the_same_fields(self):
        """The invariant the thread-pool detour rests on."""
        fund = _fund()
        direct = calibration_fields(fund)
        rebuilt = calibration_fields(SimpleNamespace(**snapshot_calibration_inputs(fund)))
        assert rebuilt == direct

    def test_industry_metrics_survive_the_detour(self):
        """Storing the processed fields instead would lose these."""
        fund = _fund()
        rebuilt = calibration_fields(SimpleNamespace(**snapshot_calibration_inputs(fund)))
        metrics = json.loads(rebuilt["metrics_json"])
        assert metrics["p_ffo"] == 16.5
        assert metrics["equity_to_assets_pct"] == 41.2

    def test_the_payload_is_json_serializable(self):
        """It rides along in the persisted run, so it cannot carry live objects."""
        payload = _track_payload(_fund(), _decision())
        assert json.loads(json.dumps(payload))["symbol"] == "O"

    def test_rationale_is_capped(self):
        payload = _track_payload(_fund(), _decision())
        assert len(payload["rationale"]) <= 4


# --------------------------------------------------------------------------- #
#  Logging a run                                                              #
# --------------------------------------------------------------------------- #

class TestLogScreenerRun:
    def test_one_row_per_analysed_ticker(self, store):
        rows = [_row(_fund(symbol=s), _decision()) for s in ("O", "EQR", "MAA")]
        assert log_screener_run(rows) == 3
        assert len(store.get_recommendations(limit=10)) == 3

    def test_marked_as_screener(self, store):
        log_screener_run([_row()])
        assert store.get_recommendations(limit=1)[0].source == "screener"

    def test_calibration_columns_are_filled(self, store):
        log_screener_run([_row()])
        rec = store.get_recommendations(limit=1)[0]
        assert rec.sector == "Real Estate"
        assert rec.health_score == 6.0
        assert json.loads(rec.metrics_json)["p_ffo"] == 16.5

    def test_the_bottom_of_the_ladder_gets_recorded(self, store):
        """The whole point: REDUCE and SELL had 1 and 0 observations."""
        rows = [
            _row(_fund(symbol="X"), _decision(action="REDUCE")),
            _row(_fund(symbol="Y"), _decision(action="SELL")),
        ]
        assert log_screener_run(rows) == 2
        assert {r.action for r in store.get_recommendations(limit=10)} == {"REDUCE", "SELL"}

    def test_running_twice_the_same_day_does_not_duplicate(self, store):
        rows = [_row()]
        assert log_screener_run(rows) == 1
        assert log_screener_run(rows) == 0
        assert len(store.get_recommendations(limit=10)) == 1

    def test_non_scorable_assets_are_skipped(self, store):
        """An ETF's SELL is an artifact of the equity scorer, not a recommendation."""
        rows = [
            _row(_fund(symbol="SPY", asset_class="fund"), _decision(action="SELL")),
            _row(_fund(symbol="BTC-USD", asset_class="crypto"), _decision(action="HOLD")),
            _row(_fund(symbol="O"), _decision()),
        ]
        assert log_screener_run(rows) == 1
        assert store.get_recommendations(limit=10)[0].symbol == "O"

    def test_rows_without_the_payload_are_ignored(self, store):
        """Runs loaded from an older persisted file have no `_track` key."""
        assert log_screener_run([{"Ticker": "O"}, {"Ticker": "KO", "_track": None}]) == 0

    def test_empty_input_is_survivable(self, store):
        assert log_screener_run([]) == 0
        assert log_screener_run(None) == 0

    def test_a_failing_store_does_not_raise(self, tmp_path, monkeypatch):
        """Capture must never break the page it hangs off."""
        class Broken:
            def log_recommendation(self, *a, **k):
                raise RuntimeError("db caída")

        monkeypatch.setattr("analysis.track_record.track_record_store", Broken())
        assert log_screener_run([_row()]) == 0
