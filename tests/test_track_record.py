"""Tests for the track record (Gran Salto, Fase 1).

Covers persistence round-trip, same-day dedupe, idempotent scoring, the
directional hit logic, and the calibration metric. Uses a real in-memory SQLite
store (project convention: no DB mocks) and an injected price lookup so the
scorer never touches the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from analysis.track_record import TrackRecordStore
from analysis.track_record_scorer import (
    calibration_by_confidence,
    compute_hit,
    equity_curve,
    score_due_recommendations,
    summary_stats,
)


@pytest.fixture
def store():
    """A fresh in-memory store per test."""
    return TrackRecordStore(db_path=":memory:")


def _decision(symbol="AAPL", action="BUY", confidence="HIGH", score=72.0):
    return SimpleNamespace(
        symbol=symbol,
        action=action,
        confidence=confidence,
        fundamental_score=score,
        technical_signal="BULLISH",
        rationale=["score alto", "moat ancho"],
    )


# ------------------------------------------------------------------ #
#  Persistence                                                         #
# ------------------------------------------------------------------ #

def test_log_and_read_roundtrip(store):
    rid = store.log_recommendation(_decision(), source="ai", price_at_rec=180.0)
    assert rid is not None
    recs = store.get_recommendations()
    assert len(recs) == 1
    r = recs[0]
    assert r.symbol == "AAPL"
    assert r.action == "BUY"
    assert r.confidence == "HIGH"
    assert r.source == "ai"
    assert r.price_at_rec == 180.0


def test_symbol_is_uppercased_and_filterable(store):
    store.log_recommendation(_decision(symbol="msft"), source="rule_based")
    assert store.get_recommendations(symbol="MSFT")
    assert store.get_recommendations(source="rule_based")
    assert not store.get_recommendations(source="committee")


def test_same_day_dedupe(store):
    first = store.log_recommendation(_decision())
    second = store.log_recommendation(_decision())  # same symbol+action same day
    assert first is not None
    assert second is None
    assert len(store.get_recommendations()) == 1


def test_different_action_not_deduped(store):
    store.log_recommendation(_decision(action="BUY"))
    store.log_recommendation(_decision(action="HOLD"))
    assert len(store.get_recommendations()) == 2


# ------------------------------------------------------------------ #
#  Hit logic (pure)                                                    #
# ------------------------------------------------------------------ #

def test_compute_hit_bullish():
    assert compute_hit("BUY", return_pct=10.0, excess_return_pct=4.0) is True
    assert compute_hit("STRONG BUY", return_pct=-2.0, excess_return_pct=-3.0) is False


def test_compute_hit_bearish():
    # SELL is a hit when we underperform the benchmark (avoiding it was right).
    assert compute_hit("SELL", return_pct=-5.0, excess_return_pct=-6.0) is True
    assert compute_hit("REDUCE", return_pct=8.0, excess_return_pct=3.0) is False


def test_compute_hit_hold_band():
    assert compute_hit("HOLD", return_pct=2.0, excess_return_pct=1.0) is True   # within band
    assert compute_hit("HOLD", return_pct=20.0, excess_return_pct=5.0) is False  # big move missed


# ------------------------------------------------------------------ #
#  Scoring job                                                         #
# ------------------------------------------------------------------ #

def _price_lookup_factory():
    """Deterministic price lookup: ticker doubles over time, SPY flat-ish.

    Encodes prices keyed by (symbol, date.date()). Missing keys -> None.
    """
    table = {}

    def add(symbol, when, price):
        table[(symbol, when.date())] = price

    def lookup(symbol, when):
        return table.get((symbol, when.date()))

    return table, add, lookup


def _backdate(store, rec_id, when):
    from analysis.track_record import RecommendationLog

    with store._Session() as s:  # noqa: SLF001 - test introspection
        row = s.get(RecommendationLog, rec_id)
        row.created_at = when
        s.commit()


def test_scoring_is_idempotent_and_correct(store):
    # A BUY 40 days ago; we score at the 30-day horizon.
    created = datetime.utcnow() - timedelta(days=40)
    rid = store.log_recommendation(_decision(symbol="NVDA", action="BUY"), price_at_rec=100.0)
    assert rid is not None
    _backdate(store, rid, created)

    table, add, lookup = _price_lookup_factory()
    horizon_date = created + timedelta(days=30)
    # NVDA +20%, SPY +5% over the horizon.
    add("NVDA", horizon_date, 120.0)
    add("SPY", created, 400.0)
    add("SPY", horizon_date, 420.0)

    # First run scores it.
    res1 = score_due_recommendations(store, price_lookup=lookup)
    assert res1["scored"] >= 1

    rows = store.get_scored_rows(30)
    assert len(rows) == 1
    row = rows[0]
    assert row["return_pct"] == pytest.approx(20.0, abs=0.01)
    assert row["benchmark_return_pct"] == pytest.approx(5.0, abs=0.01)
    assert row["excess_return_pct"] == pytest.approx(15.0, abs=0.01)
    assert row["hit"] is True

    # Second run must not duplicate the outcome.
    score_due_recommendations(store, price_lookup=lookup)
    assert len(store.get_scored_rows(30)) == 1


def test_scoring_skips_when_price_missing(store):
    store.log_recommendation(_decision(symbol="XYZ", action="BUY"), price_at_rec=None)
    # Backdate it so it's due.
    recs = store.get_recommendations()
    with store._Session() as s:  # noqa: SLF001 - test introspection
        from analysis.track_record import RecommendationLog

        row = s.get(RecommendationLog, recs[0].id)
        row.created_at = datetime.utcnow() - timedelta(days=300)
        s.commit()

    res = score_due_recommendations(store, price_lookup=lambda sym, when: None)
    assert res["scored"] == 0
    assert res["skipped"] >= 1


# ------------------------------------------------------------------ #
#  Metrics                                                             #
# ------------------------------------------------------------------ #

def test_calibration_by_confidence_synthetic():
    rows = [
        {"confidence": "HIGH", "hit": True, "excess_return_pct": 5.0},
        {"confidence": "HIGH", "hit": True, "excess_return_pct": 3.0},
        {"confidence": "HIGH", "hit": False, "excess_return_pct": -1.0},
        {"confidence": "LOW", "hit": False, "excess_return_pct": -2.0},
        {"confidence": "LOW", "hit": True, "excess_return_pct": 1.0},
    ]
    calib = calibration_by_confidence(rows)
    assert calib["HIGH"]["n"] == 3
    assert calib["HIGH"]["hit_rate"] == pytest.approx(2 / 3, abs=0.001)
    assert calib["LOW"]["hit_rate"] == pytest.approx(0.5, abs=0.001)
    # Well-calibrated: HIGH should out-hit LOW here.
    assert calib["HIGH"]["hit_rate"] > calib["LOW"]["hit_rate"]


def test_summary_and_equity_curve():
    now = datetime.utcnow()
    rows = [
        {"action": "BUY", "hit": True, "excess_return_pct": 4.0, "return_pct": 10.0,
         "benchmark_return_pct": 6.0, "created_at": now - timedelta(days=2)},
        {"action": "BUY", "hit": False, "excess_return_pct": -1.0, "return_pct": 2.0,
         "benchmark_return_pct": 3.0, "created_at": now - timedelta(days=1)},
    ]
    s = summary_stats(rows)
    assert s["n"] == 2
    assert s["overall_hit_rate"] == pytest.approx(0.5, abs=0.001)

    eq = equity_curve(rows)
    assert len(eq) == 2
    # 1.10 * 1.02 = 1.122
    assert eq.iloc[-1]["model_equity"] == pytest.approx(1.122, abs=0.001)
