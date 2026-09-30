"""MSI-NET oracle: the score-impact harness does not go to the network.

``scripts/measure_score_impact.py`` says «It never goes to the network» and decides
things on copies of the user's base. It went anyway: ``get_financials`` and
``get_dividends`` do not cache an empty answer, so every run asked Yahoo again for the
statements of the ETFs and crypto that have none (seen in UM-GDR, 2026-09-28). It moved
no measurement — those calls fail without writing — but the promise was false.

Every yfinance fetcher goes through ``data.fetcher._fetch_with_retry`` (N2). Offline, the
harness replaces it with a cache miss that never calls the fetch, records what was missed
and returns what a permanent failure returns — so the scores are the same ones the
network produced for those assets, without the network.

The suite's network guard (``tests/_network_guard.py``) fails any test that tries to
leave; on ``main`` the first test below fails for that reason.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.measure_score_impact as harness  # noqa: E402


def _history_records(n=520):
    idx = pd.date_range(end="2026-09-21", periods=n, freq="W-MON")
    close = 100 * 1.001 ** np.arange(n)
    df = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99,
                       "close": close, "volume": 1_000_000}, index=idx)
    df.index.name = "Date"
    return df.reset_index().assign(Date=lambda d: d["Date"].astype(str)).to_dict(orient="records")


@pytest.fixture
def offline(monkeypatch):
    """Run ``_make_offline`` with every global it touches registered for restore."""
    import data.cache as cache_module
    import data.fetcher as fetcher
    from config import MOAT, MULTI_SOURCE, TAILWINDS

    monkeypatch.setattr(cache_module.cache, "ttl", cache_module.cache.ttl)
    monkeypatch.setattr(MULTI_SOURCE, "attach_in_pipeline", MULTI_SOURCE.attach_in_pipeline)
    for cfg in (MOAT, TAILWINDS):
        monkeypatch.setattr(cfg, "ai_cache_ttl_hours", cfg.ai_cache_ttl_hours)
        monkeypatch.setattr(cfg, "ai_cache_only", cfg.ai_cache_only)
    monkeypatch.setattr(fetcher, "_fetch_with_retry", fetcher._fetch_with_retry)
    monkeypatch.setattr(harness, "OFFLINE_MISSES", [], raising=False)

    # A spy, not a raise: the fetchers swallow exceptions (the retry catches them),
    # so a raising stub would let a network attempt pass unnoticed.
    calls: list = []

    def _yahoo_spy(*a, **k):
        calls.append(a)
        raise RuntimeError("sin red en este test")

    monkeypatch.setattr(fetcher.yf, "Ticker", _yahoo_spy)
    harness._make_offline()
    harness._yahoo_calls = calls
    return harness


def _seed(symbol, *, quote_type="ETF", with_statements=False, pays_dividend=False):
    from data.cache import cache

    info = {
        "symbol": symbol, "quoteType": quote_type, "longName": f"{symbol} Test",
        "currency": "USD", "currentPrice": 150.0, "regularMarketPrice": 150.0,
        "sector": "Technology", "country": "United States",
    }
    if pays_dividend:  # the streak (and so get_dividends) is only read for a payer
        info.update(dividendYield=2.0, trailingAnnualDividendRate=3.0,
                    trailingAnnualDividendYield=0.02, payoutRatio=0.4)
    cache.set(f"info:{symbol}", info)
    cache.set(f"history:{symbol}:10y:1wk", _history_records())
    if with_statements:
        cache.set(f"financials:{symbol}", {"income_stmt": {"2025-12-31": {"Net Income": 1.0}}})
        cache.set(f"dividends:{symbol}", {"2025-06-01 00:00:00": 0.5})


def test_an_asset_without_cached_statements_is_measured_without_the_network(offline):
    _seed("ETFX")
    assert "ETFX" in offline.cached_symbols()
    row = offline.measure_symbol("ETFX")
    assert row is not None and row["symbol"] == "ETFX"
    assert offline._yahoo_calls == [], "el harness offline pidió datos a yfinance"


def test_what_was_not_in_the_cache_is_recorded_not_fetched(offline):
    _seed("ETFX")
    offline.measure_symbol("ETFX")
    assert ("ETFX", "financials") in offline.OFFLINE_MISSES


def test_an_equity_without_statements_or_dividends_records_both(offline):
    _seed("EQX", quote_type="EQUITY", pays_dividend=True)
    offline.measure_symbol("EQX")
    assert ("EQX", "financials") in offline.OFFLINE_MISSES
    assert ("EQX", "dividends") in offline.OFFLINE_MISSES
    assert offline._yahoo_calls == []


def test_a_fully_cached_symbol_records_no_miss(offline):
    _seed("FULL", quote_type="EQUITY", with_statements=True)
    offline.measure_symbol("FULL")
    assert [m for m in offline.OFFLINE_MISSES if m[0] == "FULL"] == []


def test_a_miss_returns_what_a_permanent_failure_returns(offline):
    """Control: the same value the network gave these assets — empty statements,
    empty dividends — so the measurement does not move."""
    from data.fetcher import get_dividends, get_financials

    assert get_financials("NOPE") == {}
    assert get_dividends("NOPE").empty


def test_the_report_names_the_misses():
    text = harness.misses_summary([("A", "financials"), ("B", "financials"), ("A", "dividends")])
    assert "3" in text and "financials 2" in text and "dividends 1" in text
    assert harness.misses_summary([]) == ""
