"""Tests for scripts/point_in_time_backtest.py (PR 4/N, Idea 2).

No network: ``_fetch_companyfacts``/``_ensure_cik_map_loaded``/``requests``
are stubbed throughout. Only the store's own ``:memory:`` singleton is
touched (conftest.py already redirects it there for the whole suite), so
these tests exercise the batch loop's *decisions* — what gets fetched,
skipped, and persisted — never a real HTTP call.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.point_in_time_backtest as backtest  # noqa: E402

# Captured before the autouse fixture below stubs it out, so the tests in the
# "actual network boundary" section can restore the real implementation.
_REAL_ENSURE_CIK_MAP_LOADED = backtest._ensure_cik_map_loaded


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


@pytest.fixture(autouse=True)
def _cik_map_preloaded(monkeypatch):
    """Most tests exercise decisions *after* the CIK map is already loaded —
    the handful that test ``_ensure_cik_map_loaded``/``_fetch_companyfacts``
    directly override this within their own body (a later ``monkeypatch``
    call on the same attribute wins).
    """
    monkeypatch.setattr(backtest, "_ensure_cik_map_loaded", lambda: True)
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)


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

    backtest.run(["AAPL"], [date(2020, 6, 1), date(2021, 6, 1)])

    assert calls == ["AAPL"]
    assert len(backtest.synthetic_backtest_store.get_all(symbol="AAPL")) == 2


def test_run_only_fetches_the_still_pending_cutoffs(monkeypatch):
    """One cutoff already logged, a second one new: must fetch (there's still
    pending work) but only persist the missing cutoff, not duplicate the one
    already there.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())

    backtest.run(["AAPL"], [date(2020, 6, 1)])
    backtest.run(["AAPL"], [date(2020, 6, 1), date(2021, 6, 1)])

    rows = backtest.synthetic_backtest_store.get_all(symbol="AAPL")
    assert sorted(r.as_of for r in rows) == ["2020-06-01", "2021-06-01"]


def test_run_skips_gracefully_when_sec_has_no_data(monkeypatch):
    """A non-US filer (no SEC CIK) must not raise — just log and move on,
    same as any other degrade-gracefully path in this codebase.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: None)

    backtest.run(["YPF"], [date(2021, 6, 1)])

    assert backtest.synthetic_backtest_store.get_all(symbol="YPF") == []


def test_run_does_not_fetch_when_nothing_is_pending(monkeypatch):
    """A symbol whose cutoffs are all already logged must never reach
    ``_fetch_companyfacts`` at all — the resumability check short-circuits
    before any network call would happen.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())
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


def test_run_refuses_when_the_unique_index_is_not_verified(monkeypatch):
    """If the resumability guarantee (the migration-created unique index)
    could not be confirmed, ``run()`` itself must refuse — checked here, not
    only through ``main()``, so any direct caller (a scheduler, a notebook)
    gets the same protection a CLI invocation does.
    """
    monkeypatch.setattr(backtest.synthetic_backtest_store, "unique_index_verified", False)
    fetch_calls = []
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: fetch_calls.append(symbol))

    summary = backtest.run(["AAPL"], [date(2021, 6, 1)])

    assert summary == {"written": 0, "skipped": 0, "failed": 1}
    assert fetch_calls == []
    assert backtest.synthetic_backtest_store.get_all() == []


def test_run_fails_fast_once_when_the_cik_map_cannot_be_loaded(monkeypatch):
    """A total SEC outage must abort the whole batch after one failed
    attempt to load the shared CIK map — not retry per symbol, which would
    turn one outage into a retry storm repeated for every remaining ticker.
    """
    load_calls = []
    monkeypatch.setattr(backtest, "_ensure_cik_map_loaded", lambda: (load_calls.append(1), False)[1])
    fetch_calls = []
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: fetch_calls.append(symbol))

    summary = backtest.run(["AAPL", "MSFT", "JNJ"], [date(2021, 6, 1)])

    assert len(load_calls) == 1, "the CIK map load must be attempted once for the whole batch, not per symbol"
    assert fetch_calls == [], "no per-symbol fetch should be attempted once the map load failed"
    assert summary == {"written": 0, "skipped": 0, "failed": 3}


def test_run_refuses_with_a_deduped_failure_count_when_symbols_repeat(monkeypatch):
    """A duplicate --symbols entry combined with an early refusal (unique
    index unverified) must report the failure count for the distinct
    ticker×cutoff pairs actually at stake, not inflated by the duplicate.
    """
    monkeypatch.setattr(backtest.synthetic_backtest_store, "unique_index_verified", False)

    summary = backtest.run(["AAPL", "AAPL"], [date(2021, 6, 1)])

    assert summary == {"written": 0, "skipped": 0, "failed": 1}


def test_main_refuses_to_run_when_the_unique_index_is_not_verified(monkeypatch):
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
#  _ensure_cik_map_loaded / _fetch_companyfacts — the actual network    #
#  boundary, and where pacing/retry live                                #
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


def test_ensure_cik_map_loaded_is_a_noop_when_already_cached(monkeypatch):
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(backtest, "_ensure_cik_map_loaded", _REAL_ENSURE_CIK_MAP_LOADED)
    monkeypatch.setattr(SecEdgarSource, "_cik_map", {"AAPL": 320193})
    sleeps = []
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))

    assert backtest._ensure_cik_map_loaded() is True
    assert sleeps == [], "an already-cached map must not trigger a network attempt"


def test_ensure_cik_map_loaded_paces_after_a_real_attempt(monkeypatch):
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(backtest, "_ensure_cik_map_loaded", _REAL_ENSURE_CIK_MAP_LOADED)

    def _fake_resolve(self, symbol):
        SecEdgarSource._cik_map = {"AAPL": 320193}
        return SecEdgarSource._cik_map.get(symbol)

    monkeypatch.setattr(SecEdgarSource, "_resolve_cik", _fake_resolve)
    sleeps = []
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))

    assert backtest._ensure_cik_map_loaded() is True
    from config import MULTI_SOURCE
    assert sleeps == [MULTI_SOURCE.sec_bulk_request_delay_s]


def test_ensure_cik_map_loaded_returns_false_after_retries_are_exhausted(monkeypatch):
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(backtest, "_ensure_cik_map_loaded", _REAL_ENSURE_CIK_MAP_LOADED)
    monkeypatch.setattr(SecEdgarSource, "_resolve_cik", lambda self, symbol: None)  # map never populates
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    assert backtest._ensure_cik_map_loaded() is False


def test_ensure_cik_map_loaded_treats_an_empty_map_as_failure(monkeypatch):
    """SEC's response can be non-empty but its rows can lack the expected
    ticker/cik_str keys (a schema change, a truncated body) — that leaves
    ``_cik_map`` as ``{}``, not ``None``. Reading that as success would let
    every subsequent symbol lookup "genuinely" resolve to no CIK, silently
    hiding a systemic problem behind what looks like 100% non-US filers.
    """
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(backtest, "_ensure_cik_map_loaded", _REAL_ENSURE_CIK_MAP_LOADED)
    monkeypatch.setattr(SecEdgarSource, "_cik_map", {})  # populated, but empty
    monkeypatch.setattr(SecEdgarSource, "_resolve_cik", lambda self, symbol: None)
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)

    assert backtest._ensure_cik_map_loaded() is False


def test_fetch_companyfacts_is_a_pure_lookup_once_the_map_is_cached(monkeypatch):
    """No pacing/retry inside ``_fetch_companyfacts`` for the CIK step
    itself — that cost was already paid once by ``_ensure_cik_map_loaded``.
    """
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(SecEdgarSource, "_cik_map", {"AAPL": 320193})

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return _fake_companyfacts()

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    sleeps = []
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))

    result = backtest._fetch_companyfacts("AAPL")

    assert result is not None
    from config import MULTI_SOURCE
    assert sleeps == [MULTI_SOURCE.sec_bulk_request_delay_s]  # one pace, for the companyfacts request


def test_fetch_companyfacts_returns_none_for_a_ticker_absent_from_the_cached_map(monkeypatch):
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(SecEdgarSource, "_cik_map", {"AAPL": 320193})  # populated, YPF absent
    sleeps = []
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))

    result = backtest._fetch_companyfacts("YPF")

    assert result is None
    assert sleeps == [], "no network call was made, so no pacing delay either"
