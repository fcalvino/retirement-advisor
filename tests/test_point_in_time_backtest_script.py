"""Tests for scripts/point_in_time_backtest.py (PR 4/N, Idea 2).

No network: ``_fetch_companyfacts``/``requests`` are stubbed throughout. Only
the store's own ``:memory:`` singleton is touched (conftest.py already
redirects it there for the whole suite), so these tests exercise the batch
loop's *decisions* — what gets fetched, skipped, and persisted — never a real
HTTP call.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.point_in_time_backtest as backtest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch):
    """A fresh, isolated :memory: store per test — the module singleton
    conftest.py already redirects away from the user's database, but each
    test still needs its own clean slate.
    """
    from analysis.synthetic_backtest import SyntheticBacktestStore

    fresh = SyntheticBacktestStore(":memory:")
    monkeypatch.setattr(backtest, "synthetic_backtest_store", fresh)
    yield fresh


def _fake_companyfacts(revenue_2019=900.0, revenue_2020=1000.0):
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    {"val": revenue_2019, "start": "2019-01-01", "end": "2019-12-31",
                     "filed": "2020-02-01", "form": "10-K", "fp": "FY"},
                    {"val": revenue_2020, "start": "2020-01-01", "end": "2020-12-31",
                     "filed": "2021-02-01", "form": "10-K", "fp": "FY"},
                ]}},
            }
        }
    }


def test_run_persists_one_row_per_symbol_per_cutoff(monkeypatch):
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    backtest.run(["AAPL"], [date(2021, 6, 1)])

    rows = backtest.synthetic_backtest_store.get_all(symbol="AAPL")
    assert len(rows) == 1
    assert rows[0].as_of == "2021-06-01"


def test_run_skips_a_pair_already_logged_without_fetching(monkeypatch):
    calls = []

    def _fetch(symbol):
        calls.append(symbol)
        return _fake_companyfacts()

    monkeypatch.setattr(backtest, "_fetch_companyfacts", _fetch)
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    backtest.run(["AAPL"], [date(2021, 6, 1)])
    assert calls == ["AAPL"]

    # Second run, same (symbol, cutoff): must not spend a second network call.
    backtest.run(["AAPL"], [date(2021, 6, 1)])
    assert calls == ["AAPL"], "a fully-cached symbol must not be re-fetched"

    rows = backtest.synthetic_backtest_store.get_all(symbol="AAPL")
    assert len(rows) == 1, "re-running must not duplicate the row"


def test_run_fetches_once_for_multiple_pending_cutoffs(monkeypatch):
    """One companyfacts call covers a ticker's whole history — scoring it
    against N cutoffs must not cost N network calls.
    """
    calls = []
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: (calls.append(symbol), _fake_companyfacts())[1])
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    backtest.run(["AAPL"], [date(2020, 6, 1), date(2021, 6, 1)])

    assert calls == ["AAPL"]
    assert len(backtest.synthetic_backtest_store.get_all(symbol="AAPL")) == 2


def test_run_only_fetches_the_still_pending_cutoffs(monkeypatch):
    """One cutoff already logged, a second one new: must fetch (there's still
    pending work) but only persist the missing cutoff, not duplicate the one
    already there.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    backtest.run(["AAPL"], [date(2020, 6, 1)])
    backtest.run(["AAPL"], [date(2020, 6, 1), date(2021, 6, 1)])

    rows = backtest.synthetic_backtest_store.get_all(symbol="AAPL")
    assert sorted(r.as_of for r in rows) == ["2020-06-01", "2021-06-01"]


def test_run_skips_gracefully_when_sec_has_no_data(monkeypatch):
    """A non-US filer (no SEC CIK) must not raise — just log and move on,
    same as any other degrade-gracefully path in this codebase.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: None)
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    backtest.run(["YPF"], [date(2021, 6, 1)])

    assert backtest.synthetic_backtest_store.get_all(symbol="YPF") == []


def test_run_does_not_pace_when_nothing_needed_fetching(monkeypatch):
    """A symbol whose cutoffs are all already logged costs no network call
    and therefore no pacing delay either — verified at the run() level since
    that's the resumability check that must short-circuit before ever
    reaching ``_fetch_companyfacts``.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)
    backtest.run(["AAPL"], [date(2021, 6, 1)])

    fetch_calls = []
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: fetch_calls.append(symbol))
    backtest.run(["AAPL"], [date(2021, 6, 1)])

    assert fetch_calls == [], "a fully-cached symbol must never reach _fetch_companyfacts"


def test_a_duplicate_cutoff_in_the_input_is_not_counted_as_a_failure(monkeypatch):
    """A duplicate --cutoffs entry must be de-duped up front, not scored
    twice and have its second write rejected by the unique index as if
    something had actually gone wrong.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())

    summary = backtest.run(["AAPL"], [date(2021, 6, 1), date(2021, 6, 1)])

    assert summary == {"written": 1, "skipped": 0, "failed": 0}
    assert len(backtest.synthetic_backtest_store.get_all(symbol="AAPL")) == 1


def test_run_returns_counts_main_uses_for_the_exit_code(monkeypatch):
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())

    summary = backtest.run(["AAPL"], [date(2020, 6, 1), date(2021, 6, 1)])

    assert summary == {"written": 2, "skipped": 0, "failed": 0}


def test_main_refuses_to_run_when_the_unique_index_is_not_verified(monkeypatch):
    """If the resumability guarantee (the migration-created unique index)
    could not be confirmed, a batch run must refuse outright — proceeding
    would silently risk duplicate rows inflating the calibration sample.
    """
    monkeypatch.setattr(backtest.synthetic_backtest_store, "unique_index_verified", False)
    monkeypatch.setattr(sys, "argv", ["point_in_time_backtest.py", "--symbols", "AAPL", "--cutoffs", "2021-06-01"])

    exit_code = backtest.main()

    assert exit_code == 1
    assert backtest.synthetic_backtest_store.get_all() == []


def test_main_exits_nonzero_when_everything_failed(monkeypatch):
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: None)  # SEC unreachable for everyone
    monkeypatch.setattr(sys, "argv", ["point_in_time_backtest.py", "--symbols", "AAPL", "--cutoffs", "2021-06-01"])

    exit_code = backtest.main()

    assert exit_code == 1


def test_main_exits_zero_when_nothing_failed(monkeypatch):
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())
    monkeypatch.setattr(sys, "argv", ["point_in_time_backtest.py", "--symbols", "AAPL", "--cutoffs", "2021-06-01"])

    exit_code = backtest.main()

    assert exit_code == 0


def test_a_reconstruction_failure_for_one_cutoff_does_not_abort_the_batch(monkeypatch):
    """``piotroski_as_of`` has no reason to raise against well-formed data,
    but a real payload is not a test fixture — one bad cutoff must be logged
    and skipped, not kill every remaining symbol in the run, the same
    resiliency guarantee ``log_piotroski`` itself already has.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())

    real_piotroski_as_of = backtest.piotroski_as_of

    def _flaky(us_gaap, cutoff):
        if cutoff == date(2020, 6, 1):
            raise ValueError("simulated reconstruction failure")
        return real_piotroski_as_of(us_gaap, cutoff)

    monkeypatch.setattr(backtest, "piotroski_as_of", _flaky)

    backtest.run(["AAPL"], [date(2020, 6, 1), date(2021, 6, 1)])

    rows = backtest.synthetic_backtest_store.get_all(symbol="AAPL")
    assert [r.as_of for r in rows] == ["2021-06-01"]


# ------------------------------------------------------------------ #
#  Pacing — exercised at _fetch_companyfacts/_resolve_cik_paced level,  #
#  since that's where the actual network calls (and their retries) live #
# ------------------------------------------------------------------ #

@pytest.fixture(autouse=True)
def _reset_cik_cache():
    """``SecEdgarSource._cik_map`` is a *class*-level cache shared across the
    whole process — reset it around each test so one test's cached map can't
    leak into another's "is this the first lookup" assertion.
    """
    from data.data_sources import SecEdgarSource

    original = SecEdgarSource._cik_map
    SecEdgarSource._cik_map = None
    yield
    SecEdgarSource._cik_map = original


def test_fetch_companyfacts_paces_after_a_real_facts_request(monkeypatch):
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(SecEdgarSource, "_cik_map", {"AAPL": 320193})  # CIK already known

    sleeps = []
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return _fake_companyfacts()

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())

    result = backtest._fetch_companyfacts("AAPL")

    assert result is not None
    from config import MULTI_SOURCE
    assert sleeps == [MULTI_SOURCE.sec_bulk_request_delay_s]


def test_fetch_companyfacts_does_not_pace_on_a_cached_cik_map_miss(monkeypatch):
    """CIK map already cached, symbol just isn't in it (non-US filer): zero
    network calls, so zero pacing delay.
    """
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(SecEdgarSource, "_cik_map", {"AAPL": 320193})  # populated, YPF absent

    sleeps = []
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))

    result = backtest._fetch_companyfacts("YPF")

    assert result is None
    assert sleeps == []


def test_resolve_cik_paces_only_the_first_uncached_lookup(monkeypatch):
    """The first symbol in a process pays the CIK-map fetch (and its pacing
    delay); every symbol after that is a free in-memory lookup — SEC's
    ticker→CIK map is one shared file, not one request per ticker.
    """
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(SecEdgarSource, "_cik_map", None)

    sleeps = []
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))

    def _fake_resolve(self, symbol):
        SecEdgarSource._cik_map = {"AAPL": 320193}  # simulates a successful fetch
        return SecEdgarSource._cik_map.get(symbol)

    monkeypatch.setattr(SecEdgarSource, "_resolve_cik", _fake_resolve)

    first = backtest._resolve_cik_paced("AAPL")
    second = backtest._resolve_cik_paced("AAPL")

    assert first == 320193
    assert second == 320193
    assert len(sleeps) == 1, "only the first, uncached lookup should pace"
