"""Both ends of a track-record return come from the same price series (audit 2026-10-26).

``score_due_recommendations`` took ``price_then`` from ``rec.price_at_rec`` — the price
stored at the moment the recommendation was made, in *that day's* scale — and ``price_now``
and the whole benchmark from ``get_history(..., auto_adjust=True)``, which is rescaled
every time a split or a dividend happens. Two consequences, both on the number the
product publishes as its hit rate:

  * **A split inside the window** reads as a crash. Stored 200 (pre-split); the history
    at the horizon is already post-split (110). ``110 / 200 - 1 = -45 %`` for a stock
    that went up 10 %.
  * **Dividends inside the window** are missing from the stock and present in the
    benchmark. The adjusted history is a total return; ``price_then`` raw against
    ``price_now`` as of the horizon is a price return. SPY's dividends were counted and
    the stock's own were not, so every BUY of a dividend payer started the race a few
    points behind — its yield over the horizon, i.e. several points a year for the
    income names this product recommends.

The return is now ``history(horizon) / history(created) - 1`` for the stock **and** the
benchmark: total return against total return, both starting at the close of the
recommendation day (the benchmark already did; the stock used to start at the intraday
price of the moment). ``price_at_rec`` stays what it was — the price the user saw, shown as
«Precio inicial» — and is no longer an input to the grade.

References are written from the definition (a return compares two prices on one scale),
not from the source. No network: prices are injected.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from analysis.track_record import TrackRecordStore
from analysis.track_record_scorer import score_due_recommendations
from data.clock import utc_now


@pytest.fixture
def store():
    return TrackRecordStore(db_path=":memory:")


def _decision(symbol="NVDA", action="BUY"):
    return SimpleNamespace(
        symbol=symbol, action=action, confidence="HIGH", fundamental_score=72.0,
        technical_signal="BULLISH", rationale=["score alto"],
    )


def _backdate(store, rec_id, when):
    from analysis.track_record import RecommendationLog

    with store._Session() as s:  # noqa: SLF001 - test introspection
        row = s.get(RecommendationLog, rec_id)
        row.created_at = when
        s.commit()


def _lookup(table):
    return lambda symbol, when: table.get((symbol, when.date()))


def _scored(store, *, raw_price_at_rec, history, horizon=30, symbol="NVDA", action="BUY"):
    """Log a recommendation 40 days ago and score it; ``history`` maps symbol -> (then, now)."""
    created = utc_now() - timedelta(days=40)
    rid = store.log_recommendation(_decision(symbol, action), price_at_rec=raw_price_at_rec)
    _backdate(store, rid, created)
    at = created + timedelta(days=horizon)
    table = {}
    for sym, (then, now) in history.items():
        table[(sym, created.date())] = then
        table[(sym, at.date())] = now
    summary = score_due_recommendations(store, price_lookup=_lookup(table))
    return summary, store.get_scored_rows(horizon)


def oracle_return_pct(price_then: float, price_now: float) -> float:
    """A return compares two prices of the SAME series."""
    return (price_now / price_then - 1.0) * 100.0


class TestOneSeriesBothEnds:
    def test_a_split_inside_the_window_is_not_a_crash(self, store):
        """Stored 200 before a 2:1 split; the adjusted history reads 100 then and 110 now."""
        summary, rows = _scored(
            store, raw_price_at_rec=200.0,
            history={"NVDA": (100.0, 110.0), "SPY": (400.0, 400.0)},
        )
        assert summary["scored"] == 1
        assert rows[0]["return_pct"] == pytest.approx(oracle_return_pct(100.0, 110.0), abs=0.01)
        assert rows[0]["return_pct"] == pytest.approx(10.0, abs=0.01)
        assert rows[0]["hit"] is True

    def test_dividends_inside_the_window_count_for_the_stock_as_they_do_for_the_benchmark(self, store):
        """Raw 100 then. The adjusted history reads 96 then (later dividends rescale it) and 100 now.

        Total return: 100/96 - 1 = +4.17 %. The old code graded 100/100 - 1 = 0 % against a
        benchmark that did include its dividends.
        """
        summary, rows = _scored(
            store, raw_price_at_rec=100.0,
            history={"NVDA": (96.0, 100.0), "SPY": (400.0, 402.0)},
        )
        assert summary["scored"] == 1
        want_stock = oracle_return_pct(96.0, 100.0)
        want_bench = oracle_return_pct(400.0, 402.0)
        assert rows[0]["return_pct"] == pytest.approx(want_stock, abs=0.01)
        assert rows[0]["benchmark_return_pct"] == pytest.approx(want_bench, abs=0.01)
        assert rows[0]["excess_return_pct"] == pytest.approx(want_stock - want_bench, abs=0.01)

    def test_the_stored_price_is_not_an_input_of_the_grade(self, store):
        """Same history, wildly different stored price: same outcome."""
        _, a = _scored(store, raw_price_at_rec=1.0,
                       history={"NVDA": (100.0, 120.0), "SPY": (400.0, 420.0)})
        other = TrackRecordStore(db_path=":memory:")
        _, b = _scored(other, raw_price_at_rec=9_999.0,
                       history={"NVDA": (100.0, 120.0), "SPY": (400.0, 420.0)})
        assert a[0]["return_pct"] == b[0]["return_pct"] == pytest.approx(20.0, abs=0.01)

    def test_a_bearish_call_is_graded_on_the_same_total_return(self, store):
        """SELL is a hit when the stock underperforms; dividends must not hide that it didn't."""
        _, rows = _scored(
            store, raw_price_at_rec=100.0, action="SELL",
            history={"NVDA": (96.0, 100.0), "SPY": (400.0, 404.0)},   # stock +4.17 %, SPY +1 %
        )
        assert rows[0]["excess_return_pct"] > 0
        assert rows[0]["hit"] is False        # it outperformed, so selling was wrong


class TestNoHistoryAtTheRecommendationDateMeansNoGrade:
    def test_it_is_skipped_and_retried_not_graded_against_the_stored_price(self, store):
        """Falling back to the stored price would put the two scales back in one return."""
        created = utc_now() - timedelta(days=40)
        rid = store.log_recommendation(_decision(), price_at_rec=100.0)
        _backdate(store, rid, created)
        at = created + timedelta(days=30)
        table = {("NVDA", at.date()): 110.0, ("SPY", created.date()): 400.0, ("SPY", at.date()): 404.0}
        summary = score_due_recommendations(store, price_lookup=_lookup(table))
        assert summary["scored"] == 0 and summary["skipped"] == 1
        assert store.get_scored_rows(30) == []


class TestThePageSaysWhatTheReturnIs:
    def test_the_detail_table_explains_total_return_and_the_unadjusted_initial_price(self):
        from pathlib import Path

        page = Path("dashboard/views/13_Track_Record.py").read_text(encoding="utf-8")
        assert "retornos **totales**" in page
        assert "sin ajustar" in page
