"""Shared fixtures for the Retirement Advisor test suite.

Data-shaped, with two exceptions: an autouse fixture that zeroes the network
retry backoff (see ``no_retry_backoff``) and the import-time redirection of the
track record and the alert store away from the user's database (see below).
"""

from __future__ import annotations

import pandas as pd
import pytest

import alerts.store as _alerts_store
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
_track_record.track_record_store._engine.dispose()  # release the user's file
_track_record.DB_PATH = ":memory:"
_track_record.track_record_store = _track_record.TrackRecordStore()


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
_alerts_store.alert_store._engine.dispose()  # release the user's file
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


# ---- Network retry backoff (N2) ---------------------------------- #

@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch):
    """Zero the fetch backoff for the whole suite.

    N2 routed every networked fetcher through ``_fetch_with_retry``, which sleeps
    2 s, then 4 s, before giving up. Tests reach that path even when they think
    they have mocked it out: ``data_sources.YFinanceSource`` imports
    ``get_financials`` locally, so ``patch("analysis.fundamental.get_financials")``
    does not intercept it, and for a synthetic ticker there is no cache entry to
    serve it. That call always failed; it used to fail instantly.

    Left alone the suite goes from 23 s to 7m26. The retry policy is right in
    production and irrelevant here, so the delay — not the retry — is what gets
    removed.
    """
    from config import FETCH

    monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)
