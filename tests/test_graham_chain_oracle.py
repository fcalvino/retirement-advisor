"""The Graham chain: three defects on one number (backlog U3-3 / U3-4 / U3-5).

``graham_value`` ends in ``require_margin_of_safety``, the gate that unlocks
STRONG BUY, so an error here does not shade a screen — it changes what the
product tells someone to buy. Three sat on it:

  * **U3-5** — ``g`` came from the CAGR of **Net Income**, under a field named
    ``eps_cagr_5y`` and a label reading "EPS CAGR". With buybacks the two are not
    the same number: fewer shares means earnings per share grow faster than
    earnings. Measured over the cached universe, 80 of 137 tickers grew EPS
    faster than net income and 24 slower — and some flipped sign, which decides
    whether a Graham value is produced at all.
  * **U3-3** — ``if eps > 0 and growth_used > 0`` produced **no value at all**
    for a company with flat earnings. Graham's formula is perfectly defined
    there: ``V = EPS × 8.5 × 4.4 / Y``. A stable, profitable, non-growing
    business is the archetype of a retirement holding, and it was the one the
    valuation silently refused to price.
  * **U3-4** — ``Y`` is a frozen 4.5 % proxy for the AAA corporate yield, and
    every surface printed "Graham Intrinsic Value" with no hint that the rate
    behind it was last true in whatever year someone typed it.

The references below are written from Graham's 1974 revision, not from the
source. Live AAA fetching is explicitly out of scope (X-04): this is about not
hiding which number is being used.

No network, no Streamlit.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from unittest.mock import patch

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer
from config import THRESHOLDS


def oracle_graham_value(eps: float, growth_pct: float, aaa_yield_pct: float) -> float:
    """Reference: Graham's 1974 revised formula, spelled out.

        V = EPS × (8.5 + 2g) × 4.4 / Y

    ``8.5`` is the multiple he assigned to a no-growth company, which is what
    makes ``g = 0`` an ordinary case rather than an undefined one. ``4.4`` is the
    AAA yield of the period, and ``Y`` the yield now, so the ratio rebases the
    multiple onto today's cost of money.
    """
    return eps * (8.5 + 2 * growth_pct) * 4.4 / aaa_yield_pct


def _income_stmt(*, net_income: Optional[List[float]] = None,
                 diluted_eps: Optional[List[float]] = None) -> pd.DataFrame:
    """Annual statement, most recent year first — the yfinance shape."""
    rows: Dict[str, List[float]] = {}
    if net_income:
        rows["Net Income"] = list(net_income)
    if diluted_eps:
        rows["Diluted EPS"] = list(diluted_eps)
    if not rows:
        return pd.DataFrame()
    n = len(next(iter(rows.values())))
    columns = [f"{2025 - i}-12-31 00:00:00" for i in range(n)]
    return pd.DataFrame(rows, index=columns).T


def _analyze(*, eps: float, income_stmt: pd.DataFrame, price: float = 100.0,
             earnings_growth: float = 0.0):
    info = {
        "longName": "Test Co", "sector": "Technology", "industry": "Software",
        "country": "United States", "trailingEps": eps,
        "earningsGrowth": earnings_growth,
        "currentPrice": price, "regularMarketPrice": price, "marketCap": 1e10,
    }
    financials = {"income_stmt": income_stmt, "balance_sheet": pd.DataFrame(),
                  "cashflow": pd.DataFrame()}
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=financials),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze("TEST")


# ================================================================== #
#  U3-3 — a company that does not grow still has a value              #
# ================================================================== #

class TestFlatEarningsAreStillValued:
    def test_the_backlog_oracle(self):
        """V(EPS 5, g 0, Y 4.5) = 41.56 — the engine used to return None."""
        assert oracle_graham_value(5.0, 0.0, 4.5) == pytest.approx(41.56, abs=0.01)

    def test_a_flat_earner_gets_a_graham_value(self):
        flat = [5.0, 5.0, 5.0, 5.0, 5.0]
        result = _analyze(eps=5.0, income_stmt=_income_stmt(diluted_eps=flat))

        assert result.eps_cagr_5y == pytest.approx(0.0, abs=0.05)
        assert result.graham_value is not None
        assert result.graham_value == pytest.approx(
            oracle_graham_value(5.0, 0.0, THRESHOLDS.graham_aaa_yield_pct), rel=1e-6
        )

    def test_shrinking_earnings_still_produce_no_value(self):
        """Anti-cheat: Graham's multiple goes negative below g = −4.25.

        The formula is not defined as a valuation for a company in decline, and
        the fix must not start quoting one.
        """
        shrinking = [3.0, 4.0, 5.0, 6.0, 7.0]   # most recent first → falling
        result = _analyze(eps=3.0, income_stmt=_income_stmt(diluted_eps=shrinking))

        assert result.eps_cagr_5y is not None and result.eps_cagr_5y < 0
        assert result.graham_value is None

    def test_a_company_with_no_earnings_still_produces_no_value(self):
        result = _analyze(eps=-1.0, income_stmt=_income_stmt(diluted_eps=[5.0] * 5))
        assert result.graham_value is None

    def test_growth_still_raises_the_value(self):
        flat = _analyze(eps=5.0, income_stmt=_income_stmt(diluted_eps=[5.0] * 5))
        grown = _analyze(
            eps=5.0,
            income_stmt=_income_stmt(diluted_eps=[5.0, 4.6, 4.2, 3.9, 3.6]),
        )
        assert grown.graham_value > flat.graham_value


# ================================================================== #
#  U3-5 — g is growth per SHARE                                       #
# ================================================================== #

class TestGrowthIsPerShare:
    #: Net income flat, share count falling: earnings per share grow.
    BUYBACK_NI = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0]
    BUYBACK_EPS = [5.0, 4.5, 4.05, 3.65, 3.28]

    def test_buybacks_are_growth_the_shareholder_actually_gets(self):
        result = _analyze(
            eps=5.0,
            income_stmt=_income_stmt(net_income=self.BUYBACK_NI,
                                     diluted_eps=self.BUYBACK_EPS),
        )
        # Net income CAGR here is exactly 0; per share it is ~11%/yr.
        assert result.eps_cagr_5y > 8.0

    def test_dilution_is_not_hidden_by_flat_net_income(self):
        """The mirror case, which is the one that protects a retiree.

        Issuing shares to fund growth leaves the holder with less of it. Reading
        net income alone reports that as no change at all.
        """
        diluted = _analyze(
            eps=4.0,
            income_stmt=_income_stmt(net_income=[1000.0] * 5,
                                     diluted_eps=[4.0, 4.4, 4.8, 5.3, 5.8]),
        )
        assert diluted.eps_cagr_5y < 0

    def test_the_label_stops_being_a_lie(self):
        """``eps_growth_label`` has always said "EPS CAGR". Now it is true."""
        from analysis.fundamental import eps_growth_label

        result = _analyze(eps=5.0, income_stmt=_income_stmt(diluted_eps=[5.0] * 5))
        assert result.eps_growth_source == "statement_cagr"
        assert "EPS CAGR" in eps_growth_label(result)

    def test_net_income_is_the_fallback_not_the_source(self):
        """A statement without a per-share row must still yield something."""
        result = _analyze(
            eps=5.0, income_stmt=_income_stmt(net_income=[1200.0, 1100.0, 1000.0]),
        )
        assert result.eps_cagr_5y is not None
        assert result.eps_growth_source == "net_income_cagr"


# ================================================================== #
#  U3-4 — the yield behind the number is named                        #
# ================================================================== #

class TestTheYieldIsDisclosed:
    def test_the_rate_is_injectable(self):
        low = _analyze(eps=5.0, income_stmt=_income_stmt(diluted_eps=[5.0] * 5))
        with patch.object(THRESHOLDS, "graham_aaa_yield_pct", 9.0):
            high = _analyze(eps=5.0, income_stmt=_income_stmt(diluted_eps=[5.0] * 5))
        assert high.graham_value < low.graham_value

    def test_no_surface_prints_the_value_without_naming_the_rate(self):
        from pathlib import Path

        from data.product_ux import graham_value_help

        help_text = graham_value_help()
        assert f"{THRESHOLDS.graham_aaa_yield_pct:g}" in help_text
        assert "proxy" in help_text.lower()

        page = Path("dashboard/pages/2_Stock_Analysis.py").read_text(encoding="utf-8")
        assert "graham_value_help" in page
        assert 'st.metric("Graham Intrinsic Value", f"${fund.graham_value:.2f}")' not in page

    def test_the_help_quotes_config_rather_than_a_literal(self):
        from data.product_ux import graham_value_help

        with patch.object(THRESHOLDS, "graham_aaa_yield_pct", 7.25):
            assert "7.25" in graham_value_help()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
