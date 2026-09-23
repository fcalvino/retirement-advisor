"""Backtesting over a multi-currency universe says so (no FX conversion yet).

The backtest sums local-currency price series and grades them against SPY, so
with the global universe active the return and alpha carry the exchange rate.
Driven through AppTest; nothing runs until the button is pressed, so no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGE = str(Path(__file__).resolve().parents[1] / "dashboard" / "views" / "6_Backtesting.py")


def _run(active_key: str) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["universe"] = ["AAPL", "SAP.DE", "7203.T"]
    at.session_state["active_universe_key"] = active_key
    return at.run()


def _fx_warnings(at: AppTest) -> list:
    return [w.value for w in at.warning if "mezcla monedas" in w.value]


def test_global_universe_warns_about_currency():
    at = _run("global_quality")
    assert not at.exception, [str(e.value) for e in at.exception]
    assert _fx_warnings(at)


@pytest.mark.parametrize("key", ["default", "us_quality", "latam_adrs"])
def test_usd_universes_do_not_warn(key):
    at = _run(key)
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not _fx_warnings(at)
