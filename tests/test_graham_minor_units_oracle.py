"""Graham margin of safety for quotes in a minor currency unit (London pence).

yfinance quotes `.L` listings in pence ("GBp") but reports ``trailingEps`` in
pounds. Measured 2026-09-23: SHEL.L price 3580, EPS 3.38 → price/EPS 1059,
while (3580 / 100) / 3.38 = 10.59 is yfinance's own trailingPE. The engine
compared a pound Graham value against a pence price, so every London margin of
safety sat near −5000 % and STRONG BUY was unreachable.

The oracle below is written from the definition, converting the price to the
major unit by hand; it does not call the engine's helpers.

No network, no Streamlit.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer
from config import THRESHOLDS


def oracle_mos_pct(eps: float, price_major: float, growth_pct: float = 0.0) -> float:
    """MoS with price and value in the same (major) unit."""
    value = eps * (8.5 + 2 * growth_pct) * 4.4 / THRESHOLDS.graham_aaa_yield_pct
    return (value - price_major) / value * 100


def _analyze(*, symbol: str, currency: str, eps: float, price: float):
    flat = pd.DataFrame(
        {f"{2025 - i}-12-31 00:00:00": [eps] for i in range(5)}, index=["Diluted EPS"]
    )
    info = {
        "longName": "Test plc", "sector": "Energy", "industry": "Oil & Gas",
        "country": "United Kingdom", "trailingEps": eps, "currency": currency,
        "currentPrice": price, "regularMarketPrice": price, "marketCap": 1e10,
        "quoteType": "EQUITY",
    }
    financials = {"income_stmt": flat, "balance_sheet": pd.DataFrame(),
                  "cashflow": pd.DataFrame()}
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=financials),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze(symbol)


def test_pence_quote_is_compared_in_pounds():
    # A cheap London stock: price 2000p = £20, EPS £3 → value ≈ £24.9.
    r = _analyze(symbol="SHEL.L", currency="GBp", eps=3.0, price=2000.0)
    assert r.margin_of_safety_pct == pytest.approx(oracle_mos_pct(3.0, 20.0), abs=0.1)
    assert r.margin_of_safety_pct > 0            # was ≈ −7900 % before the fix
    # The value is reported in the quote unit, next to the pence price.
    value_pence = 3.0 * 8.5 * 4.4 / THRESHOLDS.graham_aaa_yield_pct * 100
    assert r.graham_value == pytest.approx(value_pence, abs=0.01)


@pytest.mark.parametrize("currency,price", [("USD", 20.0), ("JPY", 20.0), ("", 20.0)])
def test_major_unit_quotes_are_unchanged(currency, price):
    # "" = a result cached before `currency` existed → factor 1, as before.
    r = _analyze(symbol="X", currency=currency, eps=3.0, price=price)
    assert r.margin_of_safety_pct == pytest.approx(oracle_mos_pct(3.0, price), abs=0.1)


def test_an_expensive_london_stock_is_still_not_a_value_stock():
    # Anti-cheat: the fix must not hand every `.L` a margin of safety.
    r = _analyze(symbol="AZN.L", currency="GBp", eps=3.0, price=6000.0)
    assert r.margin_of_safety_pct == pytest.approx(oracle_mos_pct(3.0, 60.0), abs=0.1)
    assert not r.is_value_stock()
