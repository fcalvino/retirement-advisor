"""Backtesting over a multi-currency universe says what it does with the currency.

Before #154 PR B the page warned that prices were summed unconverted against a USD
benchmark. The engine now converts every series to ``PORTFOLIO.base_currency``
(``data/fx.py``), so the warning would be false: the page says the prices are
converted, and never again that they are not. Driven through AppTest; nothing runs
until the button is pressed, so no network.
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


def _texts(at: AppTest) -> list[str]:
    return [w.value for w in at.warning] + [c.value for c in at.caption]


def test_global_universe_says_prices_are_converted():
    at = _run("global_quality")
    assert not at.exception, [str(e.value) for e in at.exception]
    assert any("se convierte a USD" in t for t in _texts(at))


@pytest.mark.parametrize("key", ["global_quality", "default", "us_quality", "latam_adrs"])
def test_no_universe_claims_the_prices_are_unconverted(key):
    at = _run(key)
    assert not at.exception, [str(e.value) for e in at.exception]
    assert not [t for t in _texts(at) if "sin convertir" in t]


@pytest.mark.parametrize("key", ["default", "us_quality", "latam_adrs"])
def test_usd_universes_do_not_mention_currencies(key):
    at = _run(key)
    assert not [t for t in _texts(at) if "mezcla monedas" in t]
