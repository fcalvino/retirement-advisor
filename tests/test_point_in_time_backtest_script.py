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


def test_run_paces_between_real_network_calls(monkeypatch):
    sleeps = []
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))

    backtest.run(["AAPL", "MSFT"], [date(2021, 6, 1)])

    assert len(sleeps) == 2   # one real fetch per symbol
    from config import MULTI_SOURCE
    assert all(s == MULTI_SOURCE.sec_bulk_request_delay_s for s in sleeps)


def test_run_does_not_pace_when_nothing_needed_fetching(monkeypatch):
    """A symbol whose cutoffs are all already logged costs no network call
    and therefore no pacing delay either.
    """
    monkeypatch.setattr(backtest, "_fetch_companyfacts", lambda symbol: _fake_companyfacts())
    monkeypatch.setattr(backtest.time, "sleep", lambda *_: None)
    backtest.run(["AAPL"], [date(2021, 6, 1)])

    sleeps = []
    monkeypatch.setattr(backtest.time, "sleep", lambda s: sleeps.append(s))
    backtest.run(["AAPL"], [date(2021, 6, 1)])

    assert sleeps == []
