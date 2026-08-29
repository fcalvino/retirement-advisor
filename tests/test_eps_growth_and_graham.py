"""Earnings growth and Graham's `g` (oracle-first, CONTEXT §5).

The defect, in two halves that share one field:

1. ``_score_growth`` read yfinance's ``earningsGrowth`` first and stored it in
   ``eps_cagr_5y``. That field is a **single quarter against the same quarter a
   year earlier**, not a compounded rate. Off a depressed base it reaches triple
   digits: measured on the cached universe (2026-08-22), 49 of 149 companies
   published an "EPS CAGR" above 50% — VLO 453.5%, LMT 443.8%, GOOGL 294.0% —
   each collecting the full 7 growth points. The fallback was silent too: CLX,
   with earnings down 50% year over year, skipped to a net-income CAGR off the
   depressed base and reported +57.9%.

2. The same number was fed to Graham as ``g`` in ``V = EPS × (8.5 + 2g) × 4.4 / Y``.
   The formula is linear in ``g``, so a quarterly spike produced intrinsic values
   in the thousands: PAM $7,921, LMT $23,780. Result — 40 of 149 companies showed
   a margin of safety above 80%, and ``margin_of_safety_pct`` is exactly what
   ``is_value_stock()`` reads to unlock STRONG BUY under
   ``STRATEGY.require_margin_of_safety``.

Per CONTEXT §5 both oracles below come from the definitions — compound growth
solved by bisection over a forward-compounding loop, and the Graham formula
evaluated term by term. ``oracle_cagr`` is deliberately re-derived here instead of
imported from ``test_cagr_window.py`` so the two suites cannot fail together
through a shared helper.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, eps_growth_label
from config import STRATEGY
from config import THRESHOLDS as T

# --------------------------------------------------------------------------- #
#  Oracles                                                                    #
# --------------------------------------------------------------------------- #

def oracle_cagr(start_value: float, end_value: float, n_years: int) -> float:
    """Rate r such that compounding start_value n times lands on end_value."""
    def compound(rate: float) -> float:
        value = start_value
        for _ in range(n_years):
            value *= (1.0 + rate)
        return value

    lo, hi = -0.9999, 100.0
    for _ in range(400):
        mid = (lo + hi) / 2.0
        if compound(mid) < end_value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def oracle_graham(eps: float, growth_pct: float, aaa_yield_pct: float, cap_pct: float) -> float:
    """V = EPS × (8.5 + 2g) × 4.4 / Y, with g the sustainable rate (capped)."""
    g = min(growth_pct, cap_pct)
    base_multiple = 8.5
    growth_term = 2.0 * g
    return eps * (base_multiple + growth_term) * 4.4 / aaa_yield_pct


# --------------------------------------------------------------------------- #
#  Fixtures                                                                   #
# --------------------------------------------------------------------------- #

def _income_stmt(net_income_recent_first: Optional[List[float]] = None,
                 revenue_recent_first: Optional[List[float]] = None) -> pd.DataFrame:
    if net_income_recent_first is None:
        return pd.DataFrame()
    n = len(net_income_recent_first)
    columns = [f"{2025 - i}-12-31 00:00:00" for i in range(n)]
    rows: Dict[str, List[float]] = {"Net Income": list(net_income_recent_first)}
    if revenue_recent_first:
        rows["Total Revenue"] = list(revenue_recent_first)
    return pd.DataFrame(rows, index=columns).T


def _analyze(info_overrides: Dict[str, Any], income_stmt: pd.DataFrame):
    info = {
        "longName": "Test Co",
        "sector": "Technology",
        "industry": "Software",
        "country": "United States",
        "currentPrice": 100.0,
        "regularMarketPrice": 100.0,
        "marketCap": 1e10,
    }
    info.update(info_overrides)
    financials = {
        "income_stmt": income_stmt,
        "balance_sheet": pd.DataFrame(),
        "cashflow": pd.DataFrame(),
    }
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=financials),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze("TEST")


# --------------------------------------------------------------------------- #
#  Oracle self-check                                                          #
# --------------------------------------------------------------------------- #

class TestOracles:
    def test_cagr_oracle_on_known_growth(self):
        assert oracle_cagr(100.0, 200.0, 3) == pytest.approx(0.259921, abs=1e-5)
        assert oracle_cagr(100.0, 100.0, 4) == pytest.approx(0.0, abs=1e-6)

    def test_graham_oracle_is_linear_in_g_below_the_cap(self):
        a = oracle_graham(10.0, 5.0, 4.5, 15.0)
        b = oracle_graham(10.0, 10.0, 4.5, 15.0)
        c = oracle_graham(10.0, 15.0, 4.5, 15.0)
        assert (b - a) == pytest.approx(c - b)

    def test_graham_oracle_saturates_above_the_cap(self):
        assert oracle_graham(10.0, 400.0, 4.5, 15.0) == oracle_graham(10.0, 15.0, 4.5, 15.0)


# --------------------------------------------------------------------------- #
#  Half 1: the growth figure                                                  #
# --------------------------------------------------------------------------- #

class TestGrowthSource:
    def test_statements_win_over_the_quarterly_figure(self):
        """Both available ⇒ the compounded rate is what gets reported.

        ``_income_stmt`` carries only a Net Income row, so since U3-5 this
        exercises the labelled *fallback*: per-share growth is preferred when the
        statement has ``Diluted EPS``, which is the shipped path and is covered in
        ``tests/test_graham_chain_oracle.py``. The rate itself is unchanged — what
        moved is that the source now says which series it came from.
        """
        result = _analyze(
            {"earningsGrowth": 2.94},                      # +294% YoY, the old winner
            _income_stmt([90.0, 80.0, 65.0, 50.0]),        # 3-year window
        )
        expected = oracle_cagr(50.0, 90.0, 3) * 100
        assert result.eps_cagr_5y == pytest.approx(expected, abs=0.1)
        assert result.eps_cagr_years == 3
        assert result.eps_growth_source == "net_income_cagr"

    def test_quarterly_figure_survives_as_a_labelled_fallback(self):
        result = _analyze({"earningsGrowth": 0.12}, _income_stmt(None))
        assert result.eps_cagr_5y == pytest.approx(12.0)
        assert result.eps_cagr_years == 1
        assert result.eps_growth_source == "yoy"
        assert "CAGR" not in eps_growth_label(result)

    def test_declining_earnings_are_not_laundered_into_growth(self):
        """CLX shape: −50% YoY used to be replaced by a positive multi-year CAGR."""
        result = _analyze(
            {"earningsGrowth": -0.50},
            _income_stmt([40.0, 95.0, 90.0, 85.0]),   # last year collapsed
        )
        expected = oracle_cagr(85.0, 40.0, 3) * 100
        assert result.eps_cagr_5y == pytest.approx(expected, abs=0.1)
        assert result.eps_cagr_5y < 0
        assert result.eps_growth_source == "net_income_cagr"   # no per-share row here

    @pytest.mark.parametrize("cagr_pct,expected_points", [
        (T.eps_cagr_excellent + 5, 7.0),
        (T.eps_cagr_good + 1, 4.0),
        (T.eps_cagr_ok + 0.5, 2.0),
        (0.5, 0.0),
    ])
    def test_growth_points_follow_the_compounded_rate(self, cagr_pct, expected_points):
        start = 100.0
        end = start * (1 + cagr_pct / 100.0) ** 3
        result = _analyze({}, _income_stmt([end, end * 0.9, start * 1.05, start]))
        # Only the earnings component is exercised (no revenue row, no cashflow).
        assert result.growth_score == expected_points

    def test_label_names_the_window(self):
        """And names the series, since U3-5 made the two distinguishable.

        Calling a net-income rate "EPS CAGR" is the U3-5 defect surviving in the
        one case where per-share data genuinely is not available.
        """
        statements = _analyze({}, _income_stmt([90.0, 80.0, 65.0, 50.0]))
        assert eps_growth_label(statements) == "Crec. ganancia neta 3Y"


# --------------------------------------------------------------------------- #
#  Half 2: Graham's g                                                         #
# --------------------------------------------------------------------------- #

class TestGrahamGrowthCap:
    def test_matches_the_oracle_below_the_cap(self):
        result = _analyze(
            {"trailingEps": 10.0},
            _income_stmt([133.1, 121.0, 110.0, 100.0]),   # exactly 10%/yr
        )
        expected = oracle_graham(10.0, 10.0, T.graham_aaa_yield_pct, T.graham_max_growth_pct)
        assert result.graham_value == pytest.approx(expected, rel=1e-3)

    def test_saturates_at_the_cap(self):
        """VLO shape: a quarterly spike must not buy an intrinsic value in the thousands."""
        spike = _analyze({"trailingEps": 10.0, "earningsGrowth": 4.535}, _income_stmt(None))
        capped = oracle_graham(10.0, T.graham_max_growth_pct,
                               T.graham_aaa_yield_pct, T.graham_max_growth_pct)

        assert spike.eps_cagr_5y == pytest.approx(453.5)        # reported honestly…
        assert spike.graham_value == pytest.approx(capped, rel=1e-3)  # …but not projected
        assert spike.graham_value < 1000

    def test_the_margin_of_safety_shrinks_to_something_defensible(self):
        """VLO shape at $300: the discount was ~98% and is now the ~20% it earns.

        Uncapped, g=453.5 gives V≈$4,000 and a margin of safety near 98% — a number
        that says "buy at almost any price". Capped, V≈$376 and the discount is the
        real one, still above `min_margin_of_safety_pct` at this price, which is the
        point: the gate now depends on the price, not on a quarterly artifact.
        """
        spike = _analyze(
            {"trailingEps": 10.0, "earningsGrowth": 4.535, "currentPrice": 300.0,
             "regularMarketPrice": 300.0},
            _income_stmt(None),
        )
        capped_value = oracle_graham(10.0, T.graham_max_growth_pct,
                                     T.graham_aaa_yield_pct, T.graham_max_growth_pct)
        expected_mos = (capped_value - 300.0) / capped_value * 100

        assert spike.margin_of_safety_pct == pytest.approx(expected_mos, abs=0.2)
        assert spike.margin_of_safety_pct < 30

        uncapped_value = oracle_graham(10.0, 453.5, T.graham_aaa_yield_pct, 10_000)
        uncapped_mos = (uncapped_value - 300.0) / uncapped_value * 100
        assert uncapped_mos > 90  # what the shipped code used to report

    def test_a_price_above_the_capped_value_is_no_longer_a_value_stock(self):
        """Uncapped, $900 still showed a ~78% discount. It should show none."""
        pricey = _analyze(
            {"trailingEps": 10.0, "earningsGrowth": 4.535, "currentPrice": 900.0,
             "regularMarketPrice": 900.0},
            _income_stmt(None),
        )
        assert pricey.is_value_stock() is False
        assert pricey.margin_of_safety_pct < 0

    def test_a_real_discount_still_registers(self):
        """No regression: genuine value must keep its margin of safety."""
        cheap = _analyze(
            {"trailingEps": 10.0, "currentPrice": 50.0, "regularMarketPrice": 50.0},
            _income_stmt([133.1, 121.0, 110.0, 100.0]),
        )
        assert cheap.is_value_stock() is True
        assert cheap.margin_of_safety_pct > STRATEGY.min_margin_of_safety_pct

    def test_growth_is_reported_uncapped(self):
        """The cap belongs to the formula, not to the number shown to the user."""
        spike = _analyze({"trailingEps": 10.0, "earningsGrowth": 4.535}, _income_stmt(None))
        assert spike.eps_cagr_5y > T.graham_max_growth_pct

    def test_no_growth_means_no_graham_value(self):
        flat = _analyze({"trailingEps": 10.0}, _income_stmt([100.0, 110.0, 120.0, 130.0]))
        assert flat.eps_cagr_5y < 0
        assert flat.graham_value is None

    def test_cap_is_config_driven(self):
        assert hasattr(T, "graham_max_growth_pct")
        with patch.object(T, "graham_max_growth_pct", 30.0):
            wide = _analyze({"trailingEps": 10.0, "earningsGrowth": 4.535}, _income_stmt(None))
        tight = _analyze({"trailingEps": 10.0, "earningsGrowth": 4.535}, _income_stmt(None))
        assert wide.graham_value > tight.graham_value
