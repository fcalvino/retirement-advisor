"""Tests for the track record (Gran Salto, Fase 1).

Covers persistence round-trip, same-day dedupe, idempotent scoring, the
directional hit logic, and the calibration metric. Uses a real in-memory SQLite
store (project convention: no DB mocks) and an injected price lookup so the
scorer never touches the network.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from analysis.track_record import TrackRecordStore, filter_by_sources
from analysis.track_record_scorer import (
    calibration_by_confidence,
    compute_hit,
    equity_curve,
    score_due_recommendations,
    summary_stats,
)
from data.clock import utc_now


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
    created = utc_now() - timedelta(days=40)
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
        row.created_at = utc_now() - timedelta(days=300)
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
    now = utc_now()
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


# --------------------------------------------------------------------------- #
#  Uncertainty band (2026-08-22) — the sample size travels with the average   #
# --------------------------------------------------------------------------- #

def test_mean_with_band_matches_a_hand_computation():
    """[2,4,4,6]: mean 4 · sd √(8/3)=1.633 · se 0.8165 · t(3)=3.182 · band 2.598."""
    import math

    from analysis.track_record_scorer import mean_with_band

    values = [2.0, 4.0, 4.0, 6.0]
    expected_se = math.sqrt(8 / 3) / math.sqrt(4)

    out = mean_with_band(values)
    assert out["n"] == 4
    assert out["mean"] == pytest.approx(4.0)
    assert out["band"] == pytest.approx(3.182 * expected_se, abs=0.01)
    assert out["inconclusive"] is False   # 4.0 sits outside ±2.60


def test_small_samples_use_t_not_the_normal_approximation():
    """At n=4 the normal critical value understates the band by 60 %.

    That is the sample size where overconfidence does the most damage, so the more
    conservative value is exactly the one that must be used there.
    """
    from analysis.track_record_scorer import mean_with_band

    values = [2.0, 4.0, 4.0, 6.0]
    band = mean_with_band(values)["band"]
    normal_band = 1.96 * (8 / 3) ** 0.5 / 2
    assert band > normal_band * 1.5


def test_mean_with_band_flags_a_result_indistinguishable_from_zero():
    from analysis.track_record_scorer import mean_with_band

    out = mean_with_band([-10.0, 12.0, -8.0, 9.0])
    assert out["inconclusive"] is True


def test_mean_with_band_survives_tiny_samples():
    from analysis.track_record_scorer import mean_with_band

    assert mean_with_band([])["n"] == 0
    assert mean_with_band([])["inconclusive"] is True
    single = mean_with_band([7.0])
    assert single["mean"] == pytest.approx(7.0)
    assert single["band"] is None
    assert single["inconclusive"] is True   # one observation is never a finding


def test_the_real_observations_from_2026_08_22():
    """Regression on the actual rows in the database, not on invented ones.

    The page showed STRONG BUY +10.39 % (n=4) beside BUY +4.08 % (n=13) and it read
    like a six-point edge. What the numbers really say is subtler, and the point of
    the band is to show it: BUY's own average is **not** distinguishable from zero
    (it ranges from −23.5 % to +29.0 %), so the six-point gap rests on one side that
    is itself noise. This test fails if either group's reading flips silently.
    """
    from analysis.track_record_scorer import hit_rate_by_action

    strong = [7.39, 9.88, 11.65, 12.66]
    buy = [4.40, 1.39, 4.07, 12.45, 9.77, 4.63, 8.59, 8.67, 1.42, -23.52, -3.32, -4.55, 29.02]
    rows = (
        [{"action": "STRONG BUY", "hit": True, "excess_return_pct": v} for v in strong]
        + [{"action": "BUY", "hit": True, "excess_return_pct": v} for v in buy]
    )

    out = hit_rate_by_action(rows)
    assert out["STRONG BUY"]["n"] == 4
    assert out["STRONG BUY"]["mean_excess_pct"] == pytest.approx(10.39, abs=0.02)
    assert out["BUY"]["n"] == 13
    assert out["BUY"]["mean_excess_pct"] == pytest.approx(4.08, abs=0.02)

    # BUY's dispersion swallows its own average.
    assert out["BUY"]["excess_band_pct"] > abs(out["BUY"]["mean_excess_pct"])
    assert out["BUY"]["inconclusive"] is True, (
        "con este rango (−23,5 % a +29,0 %) el promedio de BUY no se distingue de cero"
    )


# --------------------------------------------------------------------------- #
#  Scheduler wiring (2026-08-22)                                              #
# --------------------------------------------------------------------------- #

def test_scheduler_exposes_a_track_record_job():
    """The scorer existed and was wired to nothing — only the 30d horizon had data."""
    import scripts.run_scheduler as sched

    assert hasattr(sched, "job_score_track_record")


def test_the_scheduler_job_never_propagates_failures(monkeypatch):
    import scripts.run_scheduler as sched

    def boom():
        raise RuntimeError("scorer caído")

    monkeypatch.setattr(
        "analysis.track_record_scorer.score_due_recommendations", boom
    )
    sched.job_score_track_record()   # must not raise


# --------------------------------------------------------------------------- #
#  U7-2 — Fuente vacío es ninguna fila, no todas                               #
# --------------------------------------------------------------------------- #


def test_filter_by_sources_empty_picked_is_no_rows():
    rows = [{"source": "screener"}, {"source": "rule_based"}]
    assert filter_by_sources(rows, []) == []


def test_filter_by_sources_none_picked_keeps_all():
    rows = [{"source": "screener"}, {"source": "rule_based"}]
    assert [r["source"] for r in filter_by_sources(rows, None)] == [
        "screener", "rule_based",
    ]


def test_filter_by_sources_subset():
    rows = [{"source": "screener"}, {"source": "rule_based"}]
    kept = filter_by_sources(rows, ["screener"])
    assert [r["source"] for r in kept] == ["screener"]
