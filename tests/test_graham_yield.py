"""P3 D14 — Graham AAA yield is config-driven via the shipped analyzer."""

from unittest.mock import patch

import pandas as pd

from analysis.fundamental import FundamentalAnalyzer
from config import THRESHOLDS


def _equity_info(*, eps: float, earnings_growth: float, price: float) -> dict:
    return {
        "longName": "Test Co",
        "sector": "Technology",
        "industry": "Software",
        "country": "United States",
        "trailingEps": eps,
        "earningsGrowth": earnings_growth,
        "currentPrice": price,
        "regularMarketPrice": price,
        "marketCap": 1e9,
    }


def _empty_financials() -> dict:
    return {
        "income_stmt": pd.DataFrame(),
        "balance_sheet": pd.DataFrame(),
        "cashflow": pd.DataFrame(),
    }


def _analyze_with_yield(y_aaa: float):
    info = _equity_info(eps=10.0, earnings_growth=0.10, price=100.0)
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=_empty_financials()),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
        patch.object(THRESHOLDS, "graham_aaa_yield_pct", y_aaa),
    ):
        return FundamentalAnalyzer().analyze("TEST")


class TestGrahamAaaYield:
    def test_higher_yield_lowers_graham_value(self):
        """Shipped analyze() uses THRESHOLDS.graham_aaa_yield_pct in the Graham V."""
        low_y = _analyze_with_yield(4.5)
        high_y = _analyze_with_yield(6.0)

        assert low_y.graham_value is not None
        assert high_y.graham_value is not None
        assert high_y.graham_value < low_y.graham_value
        # V ∝ 1/Y on the shipped path (same EPS and g).
        assert abs(low_y.graham_value * 4.5 - high_y.graham_value * 6.0) < 0.05

    def test_config_field_exists(self):
        assert hasattr(THRESHOLDS, "graham_aaa_yield_pct")
        assert THRESHOLDS.graham_aaa_yield_pct > 0
