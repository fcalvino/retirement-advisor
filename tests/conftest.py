"""Shared fixtures for the Retirement Advisor test suite.

Data-shaped, with five exceptions: the suite's own database, set before any
project import (see below); the network guard, installed right after it
(TEST-NET, see ``no_network``); the import-time redirection of the track record
and the alert store to ``:memory:``; an autouse fixture that zeroes the network
retry backoff (see ``no_retry_backoff``); and another that keeps the committee
off the yfinance news feed (see ``no_committee_news``).
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# ------------------------------------------------------------------ #
#  The suite never touches the user's database (TEST-CACHE)            #
# ------------------------------------------------------------------ #
#
# N6 (below) moved the stores off ``config.DB_PATH``, but the data cache lives
# in the same file, and ``DataCache.get`` *deletes* the row it finds expired:
# one ``make test`` deleted 4 cached rows and re-downloaded 7 histories into the
# user's cache, which is how BND's signal "changed" in the #160 measurement.
#
# Pointing ``config.DB_PATH`` elsewhere here — and not re-pointing each
# singleton afterwards, the N6 way — was measured against both alternatives on
# identical copies of the database (2026-09-24). Only this reaches the child
# processes, which inherit the environment: ``test_direct_page_entry`` runs the
# dashboard in four of them, and each still opened the user's cache and read
# the real ``portfolio.json`` under the N6-style redirect. It also covers what
# hangs off ``DB_PATH.parent`` (``portfolio.json``, saved backtests) and the
# import-time opens the N6 blocks below used to make on the user's file. Those
# blocks stay: the stores still get a ``:memory:`` of their own, so their rows
# do not pile up in the file the whole suite shares.
#
# It has to run before the first project import, because ``config`` reads the
# variable once. ``tests/test_data_cache_isolation_oracle.py`` fails if an
# import moves above it.
_test_db_dir = Path(tempfile.mkdtemp(prefix="ra-test-db-"))
atexit.register(shutil.rmtree, _test_db_dir, ignore_errors=True)
os.environ["RETIREMENT_ADVISOR_DB_PATH"] = str(_test_db_dir / "retirement_advisor.db")

# ------------------------------------------------------------------ #
#  The suite never reaches the network (TEST-NET)                      #
# ------------------------------------------------------------------ #
#
# Installed here, at import, for the same reason as the block above: a fixture
# would miss collection, session fixtures and threads outliving a teardown. It
# imports no project module, so the ordering TEST-CACHE depends on holds. The
# per-test half — failing the test that tried — is ``no_network`` below.
# ``tests/_network_guard.py`` explains the three layers and the two modes.
from tests import _network_guard  # noqa: E402

_network_guard.install()

# scripts/_bootstrap.py is importable only when scripts/ is on sys.path.
# Tests that import scripts.* modules need this added before collection.
_scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import pandas as pd
import pytest

import alerts.store as _alerts_store
import analysis.synthetic_backtest as _synthetic_backtest
import analysis.track_record as _track_record

# ------------------------------------------------------------------ #
#  Track record: the suite never writes to the user's database (N6)    #
# ------------------------------------------------------------------ #
#
# ``AlertEngine._log_opportunity`` imports the module-level singleton
# ``track_record_store``, which points at ``config.DB_PATH``. The ``store``
# fixture of ``test_alert_engine.py`` replaces the *alert* store, not this one,
# so every test that fires an opportunity alert logged a real recommendation
# into the user's track record: 53 of its 470 rows as of 2026-08-30, and 11 of
# its 22 scored outcomes — which published a 68,2 % hit rate where the engine's
# own recommendations score 45,5 %.
#
# Two shapes were available. Injecting the store into ``AlertEngine`` (the way
# the alert store already is) is more explicit, but it only covers that one
# caller: six other call sites reach the same singleton — ``track_record_scorer``
# and ``dashboard/shared.py`` among them, both with a ``log_recommendation``
# path — and each new one would have to remember. This covers every caller,
# present and future, which is what a leak into the user's data warrants.
#
# It runs at import time, not as an autouse fixture, and that is the whole
# point: a fixture runs *after* collection, and ``analysis.track_record_scorer``
# binds ``track_record_store`` into its own namespace when it is imported during
# collection. A fixture would leave that binding pointed at the user's database.
#
# Patching ``DB_PATH`` inside the module — not just the singleton — is what
# covers the caller that constructs its own store instead of importing this one.
# ``tests/test_track_record_isolation_oracle.py`` fails if any of this regresses.
_track_record.track_record_store._engine.dispose()  # release the suite's file
_track_record.DB_PATH = ":memory:"
_track_record.track_record_store = _track_record.TrackRecordStore()


# ------------------------------------------------------------------ #
#  Synthetic backtest: same leak class as N6, guarded from the start    #
# ------------------------------------------------------------------ #
#
# ``analysis/synthetic_backtest.py`` (Idea 2, point-in-time backtesting) was
# built deliberately separate from ``analysis.track_record`` so a leak here
# can never contaminate the real track record's published hit rate — but it
# is still its own singleton on ``config.DB_PATH``, so it needs the exact same
# import-time redirect N6 taught this file to apply, before any test that
# might construct or import it runs. ``tests/test_synthetic_backtest_isolation_oracle.py``
# fails if this regresses.
_synthetic_backtest.synthetic_backtest_store._engine.dispose()
_synthetic_backtest.DB_PATH = ":memory:"
_synthetic_backtest.synthetic_backtest_store = _synthetic_backtest.SyntheticBacktestStore()


# ------------------------------------------------------------------ #
#  Alerts: the suite never writes to the user's database (N6c)         #
# ------------------------------------------------------------------ #
#
# Same leak as N6, one table over, and one level deeper. ``alerts/store.py``
# has its own module-level singleton on ``config.DB_PATH``, and two of its
# writers run before any assert does: ``AlertEngine.__init__`` calls
# ``purge_expired_mutes()`` (a ``DELETE`` + commit), and ``set_cooldown()`` is
# reachable straight off the store without going through the engine at all.
# That second path is the one that actually left rows behind: ``alert_cooldowns``
# carried two ``TEST1`` rows from 2026-05-24, and ``alert_snapshots`` is empty,
# which ``AlertEngine.run`` could not have produced — it saves a snapshot for
# every symbol it touches and nothing in the repo deletes them.
#
# **This block mutates the store in place; it does not replace it, and that is
# the difference from the track record above.** ``alerts/engine.py`` binds the
# singleton as a *default argument* (``store: AlertStore = alert_store``), which
# is evaluated at import and keeps the object, not the name. Rebinding
# ``alerts.store.alert_store`` to a fresh instance leaves that default pointing
# at the user's database — measured, ``AlertEngine.__init__.__defaults__[0]`` is
# still the original object. Replacing the singleton here would go green while
# the leak stayed open, so every existing reference has to be fixed through the
# object itself.
#
# Patching ``DB_PATH`` inside the module — not just the singleton — is what
# covers the caller that constructs its own store instead of importing this one.
# ``tests/test_alert_store_isolation_oracle.py`` fails if any of this regresses.
_alerts_store.alert_store._engine.dispose()  # release the suite's file
_alerts_store.DB_PATH = ":memory:"
_isolated_alerts = _alerts_store.AlertStore()
_alerts_store.alert_store._engine = _isolated_alerts._engine
_alerts_store.alert_store._Session = _isolated_alerts._Session


# ------------------------------------------------------------------ #
#  Financial statement fixtures                                        #
# ------------------------------------------------------------------ #

def _make_income_stmt(
    net_income: list[float],
    revenue: list[float],
    gross_profit: list[float] | None = None,
    years: list[int] | None = None,
) -> pd.DataFrame:
    """Build a yfinance-style income statement (rows=metrics, cols=dates, descending)."""
    if years is None:
        years = list(range(2023, 2023 - len(net_income), -1))
    dates = pd.to_datetime([f"{y}-12-31" for y in years])

    data: dict[str, list] = {
        "Net Income": net_income,
        "Total Revenue": revenue,
    }
    if gross_profit is not None:
        data["Gross Profit"] = gross_profit

    df = pd.DataFrame(data, index=dates).T
    df.columns = dates
    return df


def _make_balance_sheet(
    stockholders_equity: list[float],
    total_assets: list[float],
    long_term_debt: list[float] | None = None,
    current_assets: list[float] | None = None,
    current_liab: list[float] | None = None,
    shares: list[float] | None = None,
    years: list[int] | None = None,
) -> pd.DataFrame:
    if years is None:
        years = list(range(2023, 2023 - len(stockholders_equity), -1))
    dates = pd.to_datetime([f"{y}-12-31" for y in years])

    data: dict[str, list] = {
        "Stockholders Equity": stockholders_equity,
        "Total Assets": total_assets,
    }
    if long_term_debt is not None:
        data["Long Term Debt"] = long_term_debt
    if current_assets is not None:
        data["Current Assets"] = current_assets
    if current_liab is not None:
        data["Current Liabilities"] = current_liab
    if shares is not None:
        data["Ordinary Shares Number"] = shares

    df = pd.DataFrame(data, index=dates).T
    df.columns = dates
    return df


def _make_cashflow(
    operating_cf: list[float],
    years: list[int] | None = None,
) -> pd.DataFrame:
    if years is None:
        years = list(range(2023, 2023 - len(operating_cf), -1))
    dates = pd.to_datetime([f"{y}-12-31" for y in years])
    df = pd.DataFrame({"Operating Cash Flow": operating_cf}, index=dates).T
    df.columns = dates
    return df


# ------------------------------------------------------------------ #
#  Pytest fixtures                                                     #
# ------------------------------------------------------------------ #

@pytest.fixture
def stable_income_stmt():
    """Company with very stable revenues and margins (ideal consistency)."""
    return _make_income_stmt(
        net_income  =[1_000, 1_050, 1_100, 1_080],
        revenue     =[5_000, 5_100, 5_200, 5_150],
        gross_profit=[2_500, 2_550, 2_600, 2_580],
    )


@pytest.fixture
def volatile_income_stmt():
    """Company with wildly swinging net income."""
    return _make_income_stmt(
        net_income  =[1_000, -500, 2_000, -800],
        revenue     =[5_000, 4_800, 6_000, 4_500],
        gross_profit=[2_500, 2_400, 3_000, 2_200],
    )


@pytest.fixture
def stable_balance_sheet():
    return _make_balance_sheet(
        stockholders_equity=[10_000, 9_500, 9_000, 8_600],
        total_assets        =[20_000, 19_000, 18_500, 18_000],
        long_term_debt      =[4_000,  4_200,  4_500,  4_800],
        current_assets      =[5_000,  4_800,  4_600,  4_500],
        current_liab        =[2_000,  2_100,  2_200,  2_300],
        shares              =[1_000,  1_000,  1_000,  1_020],
    )


@pytest.fixture
def minimal_info():
    """Minimal yfinance info dict with positive OCF."""
    return {
        "operatingCashflow": 1_200,
        "sharesOutstanding": 1_000,
    }


@pytest.fixture
def stable_cashflow():
    return _make_cashflow(operating_cf=[1_200, 1_150, 1_100, 1_050])


@pytest.fixture
def sample_sector_weights():
    """Representative conservative portfolio sector weights summing to 100."""
    return {
        "Technology": 18.0,
        "Financials": 15.0,
        "Healthcare": 20.0,
        "Consumer Staples": 15.0,
        "Energy": 10.0,
        "Industrials": 8.0,
        "ETF": 14.0,
    }


@pytest.fixture
def sample_ticker_data():
    """Minimal scored-ticker dicts used by AlertEngine."""
    return [
        {
            "symbol": "AAPL",
            "adjusted_score": 75.0,
            "signal": "STRONG_BUY",
            "moat_classification": "Wide",
            "company_name": "Apple Inc.",
        },
        {
            "symbol": "T",
            "adjusted_score": 42.0,
            "signal": "HOLD",
            "moat_classification": "Narrow",
            "company_name": "AT&T",
        },
    ]


# ---- No network (TEST-NET) --------------------------------------- #

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "allow_network: the test may reach the real network (TEST-NET opt-out)",
    )


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("RA_NETGUARD_OUT")
    if out:
        _network_guard.dump(out)


@pytest.fixture(autouse=True)
def no_network(request):
    """Fail the test that tried to reach the network, even if the product code
    swallowed the ``NetworkBlockedInTest`` — which it does: ``_fetch_with_retry``
    and the fetchers degrade to empty on any exception, so a blocked call alone
    would leave the traffic invisible and the test green.

    ``RA_NETGUARD=report`` blocks but does not fail (see ``_network_guard``).
    """
    allowed = request.node.get_closest_marker("allow_network") is not None
    _network_guard.begin_test(request.node.nodeid, allowed=allowed)
    yield
    found = _network_guard.end_test()
    if found and _network_guard.MODE == "strict":
        pytest.fail(_network_guard.describe(found), pytrace=False)


@pytest.fixture(autouse=True)
def no_sec_edgar(monkeypatch):
    """Every ``FundamentalAnalyzer.analyze`` attaches the cross-source check
    (``MULTI_SOURCE.attach_in_pipeline``), which asks SEC EDGAR for the
    ticker->CIK map. It was the bulk of TEST-NET: 83 of the 112 tests that tried
    to reach the network, hidden behind ``SecEdgarSource._cik_map`` — the first
    test to succeed filled the class-level cache and the rest looked offline.

    ``None`` is what a failed request already returns, so the check degrades
    exactly as it does without network. FMP only joins with a key, so the key
    goes too: a developer's ``FMP_API_KEY`` must not decide what the suite does.
    Tests of the reconciliation pass ``sources=`` explicitly and are unaffected.
    """
    from config import MULTI_SOURCE
    from data.data_sources import SecEdgarSource

    monkeypatch.setattr(SecEdgarSource, "_http_json", lambda self, url: None)
    monkeypatch.setattr(MULTI_SOURCE, "fmp_api_key", "")


# ---- Network retry backoff (N2) ---------------------------------- #

@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch):
    """Zero the fetch backoff for the whole suite.

    N2 routed every networked fetcher through ``_fetch_with_retry``, which sleeps
    2 s, then 4 s, before giving up. N2b stopped ``YFinanceSource`` from being a
    second fetcher (it reads the cache ``analyze()`` already filled). The fixture
    stays because any test that still reaches yfinance — the retry oracle
    included — would otherwise sleep. The delay is what gets removed, not the
    retry.
    """
    from config import FETCH

    monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)


# ---- Committee news feed (#130 paso 7) --------------------------- #

@pytest.fixture(autouse=True)
def no_committee_news(monkeypatch):
    """``CommitteeAnalyzer.analyze`` fetches yfinance headlines for the DA.

    Without this, every committee test would reach the network and its prompt
    would depend on today's news. Tests that want headlines patch it back.
    """
    monkeypatch.setattr("analysis.committee._ticker_news", lambda symbol: [])
    monkeypatch.setattr("analysis.committee._ticker_drawdowns", lambda symbol: {})
