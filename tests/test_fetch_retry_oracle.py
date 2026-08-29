"""Every network fetch retries, or none of them do (backlog N2).

`X-08` filed "yfinance as the only source" as out of scope and CONTEXT §8 has
carried it as a known limitation ever since — *"no hay retry automático; si falla
un ticker, se loggea y se continúa"*.

**That sentence is out of date.** ``_fetch_with_retry`` exists and does the right
thing: three attempts, exponential backoff, ``None`` on permanent failure. What
is true is narrower and stranger — it protects two of the four fetchers:

    get_info         retry: yes
    get_history      retry: yes
    get_financials   retry: NO
    get_dividends    retry: NO

The two unprotected ones are not the harmless half. A transient failure on
``get_financials`` returns empty statements, and the chain from there is short
and entirely silent:

    empty statements → has_financials=False → data_quality "poor"
                     → apply_data_quality_policy demotes BUY to HOLD

So one flaky HTTP call, on a call path that already knows how to survive flaky
HTTP calls, changes what the product recommends. ``get_dividends`` failing takes
the dividend dimension and the growth streak with it.

This is N2's cheap half, and only that. Falling back to a *second source* on the
fetch path — ``data_sources.py`` already talks to SEC EDGAR and FMP for
reconciliation — is the expensive half and stays open: those sources disagree,
which is why the reconciliation layer exists, and picking a winner is a different
job from asking the same source twice.

No network: the failure is injected.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

import data.fetcher as fetcher

ROOT = Path(__file__).resolve().parents[1]


def _networked_fetchers() -> list[str]:
    """Every ``get_*`` in the module that reaches yfinance."""
    src = (ROOT / "data" / "fetcher.py").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"\ndef (get_\w+)\(", src):
        end = src.find("\ndef ", m.end())
        body = src[m.end(): end if end > 0 else len(src)]
        if "yf.Ticker" in body or "yf.download" in body:
            out.append((m.group(1), body))
    return out


class TestEveryNetworkedFetchRetries:
    def test_the_module_has_networked_fetchers(self):
        """Guard on the guard: an empty list would make the sweep vacuous."""
        assert len(_networked_fetchers()) >= 4

    def test_none_of_them_call_yfinance_unprotected(self):
        offenders = [
            name for name, body in _networked_fetchers()
            if "_fetch_with_retry" not in body
        ]
        assert not offenders, (
            "fetchers que van a la red sin reintento: " + ", ".join(offenders)
        )

    def test_the_retry_policy_is_config_driven(self):
        """Three attempts and a two-second base are a choice, not a constant."""
        from config import FETCH

        assert FETCH.max_retries >= 2
        assert FETCH.retry_base_delay_s > 0
        src = (ROOT / "data" / "fetcher.py").read_text(encoding="utf-8")
        body = src.split("def _fetch_with_retry")[1].split("\ndef ")[0]
        assert "FETCH." in body


class TestATransientFailureIsSurvived:
    @staticmethod
    def _flaky(succeed_on: int):
        """Fails until ``succeed_on``, then works. Counts its own calls."""
        state = {"n": 0}

        def call():
            state["n"] += 1
            if state["n"] < succeed_on:
                raise ConnectionError("boom")
            return "ok"

        return call, state

    def test_it_recovers_on_a_later_attempt(self, monkeypatch):
        from config import FETCH

        monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)
        call, state = self._flaky(succeed_on=3)
        assert fetcher._fetch_with_retry(call, "X", "test") == "ok"
        assert state["n"] == 3

    def test_it_gives_up_rather_than_hanging(self, monkeypatch):
        from config import FETCH

        monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)
        call, state = self._flaky(succeed_on=99)
        assert fetcher._fetch_with_retry(call, "X", "test") is None
        assert state["n"] == FETCH.max_retries

    def test_financials_survive_a_flaky_first_attempt(self, monkeypatch):
        """The chain that matters: empty statements demote a BUY to HOLD."""
        from config import FETCH

        monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)
        monkeypatch.setattr(fetcher.cache, "get", lambda *a, **k: None)
        monkeypatch.setattr(fetcher.cache, "set", lambda *a, **k: None)

        state = {"n": 0}

        class _Ticker:
            def __init__(self, symbol):
                state["n"] += 1
                if state["n"] < 2:
                    raise ConnectionError("boom")

            financials = pd.DataFrame({"2025": [1.0]}, index=["Net Income"])
            balance_sheet = pd.DataFrame({"2025": [2.0]}, index=["Total Assets"])
            cashflow = pd.DataFrame({"2025": [3.0]}, index=["Free Cash Flow"])

        monkeypatch.setattr(fetcher.yf, "Ticker", _Ticker)
        out = fetcher.get_financials("X")
        assert not out["income_stmt"].empty
        assert state["n"] == 2

    def test_dividends_survive_a_flaky_first_attempt(self, monkeypatch):
        from config import FETCH

        monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)
        monkeypatch.setattr(fetcher.cache, "get", lambda *a, **k: None)
        monkeypatch.setattr(fetcher.cache, "set", lambda *a, **k: None)

        state = {"n": 0}

        class _Ticker:
            def __init__(self, symbol):
                state["n"] += 1
                if state["n"] < 2:
                    raise ConnectionError("boom")

            dividends = pd.Series(
                [0.5, 0.5], index=pd.to_datetime(["2025-01-01", "2025-04-01"])
            )

        monkeypatch.setattr(fetcher.yf, "Ticker", _Ticker)
        assert len(fetcher.get_dividends("X")) == 2
        assert state["n"] == 2

    def test_a_permanent_failure_still_degrades_quietly(self, monkeypatch):
        """Anti-cheat: retrying must not turn a real outage into a crash."""
        from config import FETCH

        monkeypatch.setattr(FETCH, "retry_base_delay_s", 0.0)
        monkeypatch.setattr(fetcher.cache, "get", lambda *a, **k: None)

        def _boom(symbol):
            raise ConnectionError("down")

        monkeypatch.setattr(fetcher.yf, "Ticker", _boom)
        out = fetcher.get_financials("X")
        assert out["income_stmt"].empty


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
