"""Persisted Screener runs and run cost (audit items 13, 15, 16, 17).

Measured on 2026-08-17: a cold run over the 85-ticker universe took **~5 minutes**
and lived only in `st.session_state`, while the page's caption promised "~15s".
Restarting the server threw it all away.

The four items are one problem seen from four sides — the run is expensive, and
nothing about the page acknowledged it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from config import SCREENER
from data.screener_store import (
    SCHEMA_VERSION,
    ScreenerRun,
    ScreenerRunStore,
    filter_to_selected,
    format_eta,
    is_subset_cache_hit,
    merge_screener_rows,
    prioritize_universe,
    uncovered_selected,
)

ROOT = Path(__file__).resolve().parents[1]
SCREENER_SRC = (ROOT / "dashboard" / "pages" / "1_Screener.py").read_text(encoding="utf-8")


def _row(tk, score=80.0, hours_ago=0.0):
    return {
        "Ticker": tk,
        "Adj. Score": score,
        "_measured_at": (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds"),
    }


@pytest.fixture
def store(tmp_path):
    return ScreenerRunStore(tmp_path / "runs.json")


# --------------------------------------------------------------------------- #
#  15 — the run survives a restart                                            #
# --------------------------------------------------------------------------- #


def test_round_trip(store):
    run = ScreenerRun(universe_key="us_quality", duration_s=302.5,
                      rows=[_row("AAPL"), _row("MSFT")],
                      failures=[{"Ticker": "X", "Tipo": "RuntimeError", "Error": "boom"}])
    store.save(run)

    back = store.load("us_quality")
    assert back is not None
    assert back.tickers == ["AAPL", "MSFT"]
    assert back.duration_s == pytest.approx(302.5)
    assert back.failures[0]["Ticker"] == "X"


def test_runs_are_kept_per_universe(store):
    store.save(ScreenerRun(universe_key="a", rows=[_row("AAPL")]))
    store.save(ScreenerRun(universe_key="b", rows=[_row("KO")]))
    assert store.load("a").tickers == ["AAPL"]
    assert store.load("b").tickers == ["KO"]
    assert store.load("nope") is None


def test_missing_corrupt_and_stale_schema_files_are_survivable(store, tmp_path):
    assert store.load("anything") is None          # no file at all

    store.path.write_text("{ not json", encoding="utf-8")
    assert store.load("anything") is None          # unreadable → start fresh

    store.path.write_text(json.dumps({"u": {"schema_version": 999, "rows": [_row("A")]}}))
    assert store.load("u") is None                 # old schema is ignored, not crashed


def test_a_cache_that_cannot_be_written_never_breaks_the_run(tmp_path):
    """Persistence is a convenience; losing it must not lose the analysis."""
    bad = ScreenerRunStore(tmp_path / "nope" / "deep" / "x.json")
    bad.path.parent.mkdir(parents=True)
    bad.path.parent.chmod(0o500)
    try:
        bad.save(ScreenerRun(rows=[_row("AAPL")]))   # must not raise
    finally:
        bad.path.parent.chmod(0o700)


def test_clear(store):
    store.save(ScreenerRun(universe_key="a", rows=[_row("AAPL")]))
    store.save(ScreenerRun(universe_key="b", rows=[_row("KO")]))
    store.clear("a")
    assert store.load("a") is None and store.load("b") is not None
    store.clear()
    assert store.load("b") is None


def test_page_seeds_the_session_from_disk():
    assert "screener_run_store.load(_universe_key)" in SCREENER_SRC
    assert "if _cached_rows is None and _stored and _stored.rows:" in SCREENER_SRC
    assert "def _persist(" in SCREENER_SRC


# --------------------------------------------------------------------------- #
#  13 — an ETA measured, not asserted                                          #
# --------------------------------------------------------------------------- #


def test_seconds_per_ticker_counts_failures_too():
    """They cost time even though they produce no row."""
    run = ScreenerRun(duration_s=100.0, rows=[_row("A"), _row("B")],
                      failures=[{"Ticker": "C"}, {"Ticker": "D"}])
    assert run.seconds_per_ticker() == pytest.approx(25.0)


def test_seconds_per_ticker_is_none_without_a_measurement():
    assert ScreenerRun().seconds_per_ticker() is None
    assert ScreenerRun(rows=[_row("A")]).seconds_per_ticker() is None      # no duration
    assert ScreenerRun(duration_s=10.0).seconds_per_ticker() is None       # nothing measured


@pytest.mark.parametrize("seconds,expected", [
    (0, "~0s"), (12, "~12s"), (89, "~89s"),
    (95, "~1.6 min"), (300, "~5 min"), (900, "~15 min"),
])
def test_format_eta_says_minutes_when_it_is_minutes(seconds, expected):
    assert format_eta(seconds) == expected


def test_format_eta_never_reports_a_five_minute_job_in_seconds():
    """The exact defect: '~15s' printed over a ~5 minute run."""
    measured = ScreenerRun(duration_s=302.0, rows=[_row(f"T{i}") for i in range(85)])
    eta = format_eta(measured.seconds_per_ticker() * 85)
    assert "min" in eta
    assert eta != "~15s"


def test_page_estimates_from_the_stored_run_and_drops_the_fixed_caption():
    assert "~15s" not in SCREENER_SRC
    assert "seconds_per_ticker()" in SCREENER_SRC
    assert "medido en tu última corrida" in SCREENER_SRC
    assert "eta_per_ticker=" in SCREENER_SRC


# --------------------------------------------------------------------------- #
#  16 — refresh what needs it                                                 #
# --------------------------------------------------------------------------- #


def test_stale_tickers_uses_the_per_row_timestamp():
    run = ScreenerRun(rows=[_row("FRESH", hours_ago=1), _row("OLD", hours_ago=70)])
    assert run.stale_tickers(48.0) == ["OLD"]
    assert set(run.stale_tickers(0.5)) == {"FRESH", "OLD"}


def test_a_row_with_no_timestamp_counts_as_stale():
    """Unknown age is not evidence of freshness."""
    run = ScreenerRun(rows=[{"Ticker": "NOSTAMP", "Adj. Score": 50.0}])
    assert run.stale_tickers(48.0) == ["NOSTAMP"]


def test_missing_tickers_enables_resuming_an_interrupted_run():
    run = ScreenerRun(rows=[_row("A"), _row("B")], failures=[{"Ticker": "C"}])
    assert run.missing_tickers(["A", "B", "C", "D", "E"]) == ["D", "E"]
    assert run.missing_tickers(["A"]) == []


def test_page_offers_partial_refresh_instead_of_only_all_or_nothing():
    assert "stale_tickers(" in SCREENER_SRC
    assert "missing_tickers(" in SCREENER_SRC
    assert "screener_rerun_subset" in SCREENER_SRC
    assert "Actualización parcial disponible" in SCREENER_SRC


def test_partial_rerun_replaces_rows_instead_of_duplicating_them():
    """Re-measuring AAPL must update its row, not append a second one."""
    block = SCREENER_SRC[SCREENER_SRC.index("if _rerun_only:") : SCREENER_SRC.index("elif _cached_rows")]
    assert "merge_screener_rows(" in block
    assert "_persist(_new_rows, _new_failures" in block


# --------------------------------------------------------------------------- #
#  17 — capping the run keeps what matters                                    #
# --------------------------------------------------------------------------- #


def test_priority_order_is_watchlist_holdings_previous_best_rest():
    out = prioritize_universe(
        ["AAPL", "MSFT", "KO", "JNJ", "XOM"],
        watchlist=["JNJ"], holdings=["XOM"],
        previous_scores={"KO": 90.0, "AAPL": 40.0},
    )
    assert out == ["JNJ", "XOM", "KO", "AAPL", "MSFT"]


def test_priority_is_deterministic_and_keeps_every_ticker():
    tickers = [f"T{i}" for i in range(20)]
    out = prioritize_universe(tickers, previous_scores={"T7": 99.0})
    assert sorted(out) == sorted(tickers)
    assert out[0] == "T7"
    assert out == prioritize_universe(tickers, previous_scores={"T7": 99.0})


def test_priority_is_case_insensitive_on_membership():
    out = prioritize_universe(["aapl", "KO"], watchlist=["AAPL"])
    assert out[0] == "aapl"


def test_no_hints_preserves_the_original_order():
    tickers = ["C", "A", "B"]
    assert prioritize_universe(tickers) == tickers


def test_page_caps_a_prioritised_order_not_a_file_slice():
    assert "selected = _ordered[:max_tickers]" in SCREENER_SRC
    assert "prioritize_universe(" in SCREENER_SRC
    assert "SCREENER.default_max_tickers" in SCREENER_SRC


def test_default_cap_is_not_the_slowest_possible_run():
    assert SCREENER.default_max_tickers == 25
    assert SCREENER.default_max_tickers < 85


def test_schema_version_is_pinned():
    assert SCHEMA_VERSION == 2
    assert ScreenerRun().schema_version == SCHEMA_VERSION


def test_stored_run_is_matched_by_membership_not_by_order():
    """Rows come back in thread-pool completion order.

    Keying the session cache on a tuple made the stored run miss on every load,
    so persistence silently did nothing and the page re-analysed anyway — visible
    only in the running app, never in a test whose fixture returned rows in
    request order.
    """
    assert "_sel_key = frozenset(selected)" in SCREENER_SRC
    assert "_cached_key = frozenset(_stored.covered_tickers())" in SCREENER_SRC
    assert "_sel_key = tuple(selected)" not in SCREENER_SRC

    requested = ["AAPL", "MSFT", "KO"]
    completed = ["KO", "AAPL", "MSFT"]          # what the pool actually returns
    assert frozenset(requested) == frozenset(completed)
    assert tuple(requested) != tuple(completed)


def test_page_hits_when_selected_is_a_subset_of_covered():
    """Slider 25 vs last run of 85 must not re-run or overwrite the JSON."""
    assert "is_subset_cache_hit(" in SCREENER_SRC
    assert "_cached_key == _sel_key" not in SCREENER_SRC
    assert "uncovered_selected(" in SCREENER_SRC
    assert "log_screener_run(new_rows)" in SCREENER_SRC
    assert "log_screener_run(rows)" not in SCREENER_SRC

    covered = [f"T{i:02d}" for i in range(85)]
    selected = covered[:25]
    assert is_subset_cache_hit(selected, covered)
    assert not is_subset_cache_hit(covered, selected)
    assert uncovered_selected(selected, covered) == []
    assert uncovered_selected(covered[:30], covered[:20]) == covered[20:30]


def test_merge_screener_rows_keeps_uncovered():
    prev = [_row("A", 80), _row("B", 70), _row("C", 60)]
    new = [_row("B", 99)]
    rows, failures = merge_screener_rows(prev, [{"Ticker": "X"}], new, [])
    assert [r["Ticker"] for r in rows] == ["A", "C", "B"]
    assert rows[-1]["Adj. Score"] == 99
    assert failures == [{"Ticker": "X"}]
    assert [r["Ticker"] for r in filter_to_selected(rows, ["A", "B"])] == ["A", "B"]


# --------------------------------------------------------------------------- #
#  A failed ticker is covered, not missing                                    #
# --------------------------------------------------------------------------- #


def test_covered_tickers_counts_the_ones_that_failed():
    """A ticker that blew up is not unknown — the run reached it.

    The page keys its session cache on what the stored run covered. While that
    key came off `rows` alone, one yfinance hiccup made it disagree with the
    requested universe forever, so reopening the app paid another cold run — the
    exact cost item 15 exists to avoid.
    """
    run = ScreenerRun(
        rows=[_row("AAPL"), _row("MSFT")],
        failures=[{"Ticker": "BROKEN", "Tipo": "RuntimeError", "Error": "boom"}],
    )
    assert run.covered_tickers() == {"AAPL", "MSFT", "BROKEN"}
    assert run.missing_tickers(["AAPL", "MSFT", "BROKEN"]) == []
    assert run.missing_tickers(["AAPL", "NVDA"]) == ["NVDA"]


def test_the_page_keys_its_cache_on_everything_the_run_covered():
    """Source contract: the failure path is what made this regress."""
    assert "_cached_key = frozenset(_stored.covered_tickers())" in SCREENER_SRC
    assert "_cached_key = frozenset(_stored.tickers)" not in SCREENER_SRC


# --------------------------------------------------------------------------- #
#  13 (again) — a partial refresh must not deflate the ETA                    #
# --------------------------------------------------------------------------- #


def test_measured_n_is_the_denominator_when_recorded():
    """85 rows carrying the duration of a 3-ticker refresh is not 85 measurements."""
    partial = ScreenerRun(
        rows=[_row(f"T{i}") for i in range(85)], duration_s=11.0, measured_n=3,
    )
    assert partial.seconds_per_ticker() == pytest.approx(11.0 / 3)
    # Without the field it would have claimed 0.13 s/ticker — a ~11s ETA for a
    # five-minute job, which is the "~15s" caption item 13 was created to kill.
    assert format_eta(partial.seconds_per_ticker() * 85) != format_eta(11.0 / 85 * 85)


def test_measured_n_defaults_to_the_historical_denominator():
    """Runs stored before the field exists must keep their meaning."""
    old = ScreenerRun(rows=[_row("A"), _row("B")], duration_s=100.0,
                      failures=[{"Ticker": "C"}])
    assert old.measured_n == 0
    assert old.seconds_per_ticker() == pytest.approx(100.0 / 3)


def test_measured_n_survives_the_round_trip(store):
    store.save(ScreenerRun(universe_key="us", duration_s=302.0, measured_n=85,
                           rows=[_row("A")]))
    assert store.load("us").measured_n == 85


def test_a_partial_rerun_carries_the_measurement_forward_instead_of_overwriting_it():
    """Source contract for the page's partial-refresh branch."""
    branch = SCREENER_SRC[
        SCREENER_SRC.index("if _rerun_only:") : SCREENER_SRC.index("elif _cached_rows is not None")
    ]
    assert "_persist(_new_rows, _new_failures, _elapsed)" in branch
    assert "replace_throughput" not in branch
    persist_def = SCREENER_SRC[
        SCREENER_SRC.index("def _persist(") : SCREENER_SRC.index("if refresh:")
    ]
    assert "elif _stored:" in persist_def
    assert "_stored.duration_s" in persist_def
    assert "_stored.measured_n" in persist_def
