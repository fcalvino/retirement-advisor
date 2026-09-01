"""YFinanceSource is a cache reader, not a second fetcher (backlog N2b).

N2 already retries the four yfinance fetchers. The leftover was cheaper and
narrower than the row sounded: ``YFinanceSource.fetch_fundamentals`` imported
``get_financials`` *inside the method*, so ``patch("analysis.fundamental.get_financials")``
missed it. When ``analyze()`` had just failed, the adapter paid a second retry
loop for the same miss — the suite jumped from 23 s to 7m26 until the backoff
fixture zeroed the sleep.

SEC/FMP still cannot replace statement DataFrames (four canonical facts vs
income/BS/CF). This oracle therefore locks the design that was measured, not
the one the row wished for:

  * the adapter does not go to the network
  * a failed primary fetch is not paid twice
  * fallback facts keep their own source name
  * fallback facts do not rewrite ``adjusted_score``

No network: failures are injected, SEC is a fake source.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import data.cache as cache_mod
import data.fetcher as fetcher
from analysis.data_reconciliation import data_quality_agent, reconcile
from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from config import FETCH
from data.data_sources import DataSource, SourceValue, YFinanceSource

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
#  Cache double so tests never touch the user's SQLite                         #
# --------------------------------------------------------------------------- #


class _MemCache:
    def __init__(self):
        self.store: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


@pytest.fixture
def mem_cache(monkeypatch):
    mem = _MemCache()
    monkeypatch.setattr(cache_mod.cache, "get", mem.get)
    monkeypatch.setattr(cache_mod.cache, "set", mem.set)
    monkeypatch.setattr(fetcher.cache, "get", mem.get)
    monkeypatch.setattr(fetcher.cache, "set", mem.set)
    return mem


def _info_ok():
    return {
        "regularMarketPrice": 10.0,
        "currentPrice": 10.0,
        "longName": "Synthetic Co",
        "sector": "Technology",
        "industry": "Software",
        "country": "United States",
        "quoteType": "EQUITY",
        "marketCap": 1e9,
        "sharesOutstanding": 1e8,
        "trailingEps": 1.0,
    }


class _FakeSec(DataSource):
    name = "sec_edgar"

    def __init__(self, revenue=1_000.0):
        self._revenue = revenue

    def fetch_fundamentals(self, symbol):
        return {
            "total_revenue": SourceValue(
                "total_revenue", self._revenue, self.name, as_of="2025-12-31", unit="USD"
            )
        }


# --------------------------------------------------------------------------- #
#  1. The adapter is not a fetcher                                             #
# --------------------------------------------------------------------------- #


class TestAdapterIsNotAFetcher:
    def test_fetch_fundamentals_does_not_import_or_call_the_network(self):
        src = textwrap.dedent(inspect.getsource(YFinanceSource.fetch_fundamentals))
        tree = ast.parse(src)
        imports = [
            ast.unparse(n)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        assert not any("get_financials" in i or "get_info" in i for i in imports), (
            "YFinanceSource no puede importar el fetcher adentro del método — "
            "eso es lo que duplicó el retry: " + ", ".join(imports)
        )
        assert "yf.Ticker" not in src
        assert "_fetch_with_retry" not in src

    def test_the_module_does_not_retry(self):
        src = (ROOT / "data" / "data_sources.py").read_text(encoding="utf-8")
        assert "_fetch_with_retry" not in src

    def test_cache_only_is_the_shipped_default(self):
        from config import FetchConfig

        assert FetchConfig().adapter_reads_cache_only is True
        assert FETCH.adapter_reads_cache_only is True


# --------------------------------------------------------------------------- #
#  2–3. A miss is paid once; a hit is not paid again                          #
# --------------------------------------------------------------------------- #


class TestAFailedFetchIsNotPaidTwice:
    def test_empty_financials_do_not_double_retry(self, mem_cache, monkeypatch):
        """Info succeeds (and is cached). Financials fail every attempt.

        Before N2b the adapter called ``get_financials`` again and paid
        ``FETCH.max_retries`` a second time. After, Ticker is built once for
        info and ``max_retries`` times for financials — never twice that.
        """
        monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)
        state = {"ticker": 0}

        class _Ticker:
            def __init__(self, symbol):
                state["ticker"] += 1

            @property
            def info(self):
                return _info_ok()

            @property
            def financials(self):
                raise ConnectionError("boom")

            @property
            def balance_sheet(self):
                raise ConnectionError("boom")

            @property
            def cashflow(self):
                raise ConnectionError("boom")

        monkeypatch.setattr(fetcher.yf, "Ticker", _Ticker)
        monkeypatch.setattr(
            "data.data_sources.default_fundamental_sources",
            lambda: [YFinanceSource()],
        )

        FundamentalAnalyzer().analyze("ZZZZN2B")

        assert state["ticker"] == 1 + FETCH.max_retries, (
            f"Ticker se construyó {state['ticker']} veces; "
            f"esperado 1 (info) + {FETCH.max_retries} (financials), "
            "no el doble que cobraba el adapter"
        )

    def test_a_cache_hit_does_not_build_another_ticker(self, mem_cache, monkeypatch):
        monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)
        state = {"ticker": 0}
        frame = pd.DataFrame({"2025": [1.0]}, index=["Net Income"])

        class _Ticker:
            def __init__(self, symbol):
                state["ticker"] += 1

            @property
            def info(self):
                return _info_ok()

            financials = frame
            balance_sheet = pd.DataFrame({"2025": [2.0]}, index=["Total Assets"])
            cashflow = pd.DataFrame({"2025": [3.0]}, index=["Free Cash Flow"])

        monkeypatch.setattr(fetcher.yf, "Ticker", _Ticker)
        monkeypatch.setattr(
            "data.data_sources.default_fundamental_sources",
            lambda: [YFinanceSource()],
        )

        FundamentalAnalyzer().analyze("ZZZZN2B")
        # One Ticker for info, one for financials. The adapter reads the cache.
        assert state["ticker"] == 2

    def test_empty_cache_does_not_call_the_fetcher(self, mem_cache, monkeypatch):
        monkeypatch.setattr(
            fetcher.yf,
            "Ticker",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")),
        )
        out = YFinanceSource().fetch_fundamentals("NOCACHE")
        assert out == {}


# --------------------------------------------------------------------------- #
#  5. Provenance stays on the source that produced the fact                    #
# --------------------------------------------------------------------------- #


class TestFallbackProvenance:
    def test_sec_facts_are_not_labelled_yfinance(self):
        sec = _FakeSec()
        facts = sec.fetch_fundamentals("US")
        assert facts["total_revenue"].source == "sec_edgar"
        assert facts["total_revenue"].source != "yfinance"

    def test_badge_names_both_legs_when_primary_has_no_statements(self):
        base = {
            "level": "poor",
            "warnings": ["Sin estados financieros — scores de salud/crecimiento son neutrales."],
        }
        results = {
            "sec_edgar": {
                "total_revenue": SourceValue(
                    "total_revenue", 1000.0, "sec_edgar", as_of="2025-12-31"
                )
            }
        }
        merged = data_quality_agent(base, reconcile("US", results))
        assert merged["level"] == "poor", "SEC no sube el badge: eso reintroduciría un BUY"
        assert merged["primary_source"] == "yfinance"
        assert "sec_edgar" in (merged.get("fallback_available") or [])
        assert any("no usados para puntuar" in w for w in merged["warnings"])


# --------------------------------------------------------------------------- #
#  6. Fallback does not rewrite the score                                      #
# --------------------------------------------------------------------------- #


class TestFallbackDoesNotRewriteScores:
    def test_adjusted_score_is_identical_with_or_without_sec(self, mem_cache, monkeypatch):
        monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)

        def _info(symbol):
            return _info_ok()

        def _financials(symbol):
            return {}

        monkeypatch.setattr(fetcher, "get_info", _info)
        monkeypatch.setattr(fetcher, "get_financials", _financials)
        monkeypatch.setattr("analysis.fundamental.get_info", _info)
        monkeypatch.setattr("analysis.fundamental.get_financials", _financials)

        with patch(
            "data.data_sources.default_fundamental_sources",
            lambda: [YFinanceSource()],
        ):
            without = FundamentalAnalyzer().analyze("ZZZZN2B")
        with patch(
            "data.data_sources.default_fundamental_sources",
            lambda: [YFinanceSource(), _FakeSec(revenue=99_999.0)],
        ):
            with_sec = FundamentalAnalyzer().analyze("ZZZZN2B")

        assert without.adjusted_score == with_sec.adjusted_score
        assert without.data_quality["level"] == "poor"
        assert with_sec.data_quality["level"] == "poor"
        # The statements the scorer saw stayed empty even with a fat 10-K sitting
        # on the verification path. Copying SEC revenue into income_stmt would
        # move growth / totals and fail this.
        assert without.total_score == with_sec.total_score


def test_empty_financials_keep_has_financials_false():
    """Direct contract the scorer reads — independent of analyze() wiring."""
    from analysis.fundamental import compute_data_quality

    r = FundamentalResult(symbol="X", sector="Technology", current_price=10.0)
    dq = data_quality_agent(
        compute_data_quality(r, has_financials=False),
        reconcile(
            "X",
            {
                "sec_edgar": {
                    "total_revenue": SourceValue(
                        "total_revenue", 1.0, "sec_edgar", "2025-12-31"
                    )
                }
            },
        ),
    )
    assert dq["level"] == "poor"
