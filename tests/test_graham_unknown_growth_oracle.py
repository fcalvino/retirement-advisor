"""Graham does not price a company whose growth is unknown (audit 2026-10-26).

``growth_estimate = float(result.eps_cagr_5y or 0.0)`` turned *no measurement*
into *no growth*. ``eps_cagr_5y`` is ``None`` in three situations — the statements
are too short for a CAGR, the quarterly ``earningsGrowth`` is missing, **or it is
negative**: the yoy fallback only records a rate when it is positive, so a company
whose earnings just fell 50% and has no multi-year history arrives here as ``None``
too. All three were priced as ``g = 0``:

    EPS 5, Y 4.5 %:  V = 5 × 8.5 × 4.4 / 4.5 = 41.56

U3-3 made ``g = 0`` an ordinary case with a defined value **because it is a measured
zero**, and kept "a DECLINING company still gets no value" because the formula is not
a valuation there. A company with no growth figure is exactly the one we cannot say is
not declining, and the margin of safety that comes out of it is the number that
unlocks STRONG BUY (``require_margin_of_safety``). A missing figure must not price as
if it were a flat one — the same rule P1-2 applied to the scoring bands.

References are Graham's 1974 formula spelled out, as in ``test_graham_chain_oracle``.

No network, no Streamlit.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import patch

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer
from config import THRESHOLDS


def oracle_graham(eps: float, growth_pct: Optional[float], yield_pct: float, cap_pct: float):
    """Graham's value, or ``None`` when there is nothing to price.

    No value when EPS is not positive, when growth was never measured, or when the
    measured growth is negative (the multiple 8.5 + 2g turns negative below -4.25).
    Growth above the cap is cut to the cap.
    """
    if eps <= 0 or growth_pct is None or growth_pct < 0:
        return None
    g = min(growth_pct, cap_pct)
    return eps * (8.5 + 2 * g) * 4.4 / yield_pct


def _statement(eps_by_year) -> pd.DataFrame:
    if not eps_by_year:
        return pd.DataFrame()
    cols = [f"{2025 - i}-12-31 00:00:00" for i in range(len(eps_by_year))]
    return pd.DataFrame({"Diluted EPS": list(eps_by_year)}, index=cols).T


def _analyze(*, eps: float, eps_by_year=None, earnings_growth=None, price: float = 30.0):
    info = {
        "longName": "Test Co", "sector": "Technology", "industry": "Software",
        "country": "United States", "trailingEps": eps,
        "currentPrice": price, "regularMarketPrice": price, "marketCap": 1e10,
    }
    if earnings_growth is not None:
        info["earningsGrowth"] = earnings_growth
    financials = {"income_stmt": _statement(eps_by_year), "balance_sheet": pd.DataFrame(),
                  "cashflow": pd.DataFrame()}
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=financials),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze("TEST")


class TestUnknownGrowthIsNotFlatGrowth:
    def test_no_statements_and_no_quarterly_figure(self):
        r = _analyze(eps=5.0)
        assert r.eps_cagr_5y is None
        assert r.graham_value is None
        assert r.margin_of_safety_pct is None

    def test_falling_earnings_with_no_history_are_not_priced_as_flat(self):
        """The yoy fallback drops a negative rate, so this arrives as ``None`` growth."""
        r = _analyze(eps=5.0, earnings_growth=-0.50)
        assert r.eps_cagr_5y is None
        assert r.graham_value is None
        assert r.margin_of_safety_pct is None

    def test_it_would_have_looked_like_a_bargain(self):
        """The reason it matters: at P/E 5 the g = 0 value shows a ~40 % margin of safety."""
        r = _analyze(eps=5.0, price=25.0)
        flat_value = oracle_graham(5.0, 0.0, THRESHOLDS.graham_aaa_yield_pct, THRESHOLDS.graham_max_growth_pct)
        assert (flat_value - 25.0) / flat_value * 100 > 35     # the number the old code produced
        assert r.margin_of_safety_pct is None                   # and must not


def oracle_cagr_pct(series_newest_first) -> float:
    """Compound annual rate (%) of an EPS series, written from the definition.

    Rounded to one decimal because that is the rate the engine publishes as
    ``eps_cagr_5y`` and the one it feeds the formula (a 0.3 % effect on the value).
    """
    last, first = series_newest_first[0], series_newest_first[-1]
    years = len(series_newest_first) - 1
    return round(((last / first) ** (1.0 / years) - 1.0) * 100.0, 1)


class TestMeasuredGrowthIsStillPriced:
    @pytest.mark.parametrize("eps_by_year", [
        [5.0, 5.0, 5.0, 5.0, 5.0],        # measured flat: U3-3, g = 0
        [5.0, 4.6, 4.2, 3.9, 3.6],        # measured growth
    ])
    def test_a_measured_rate_is_priced_as_the_oracle_says(self, eps_by_year):
        r = _analyze(eps=eps_by_year[0], eps_by_year=eps_by_year)
        want = oracle_graham(eps_by_year[0], oracle_cagr_pct(eps_by_year),
                             THRESHOLDS.graham_aaa_yield_pct, THRESHOLDS.graham_max_growth_pct)
        assert want is not None            # the case itself is priceable: a None here would pass vacuously
        assert r.graham_value == pytest.approx(want, abs=0.01)

    def test_a_measured_decline_gets_no_value(self):
        eps_by_year = [3.0, 4.0, 5.0, 6.0, 7.0]
        assert oracle_cagr_pct(eps_by_year) < 0
        assert _analyze(eps=3.0, eps_by_year=eps_by_year).graham_value is None

    def test_a_turnaround_has_no_measurable_rate_and_no_value(self):
        """The base is not positive, so there is no CAGR: unknown, not zero."""
        r = _analyze(eps=5.0, eps_by_year=[5.0, 3.0, 1.0, -2.0, -4.0])
        assert r.eps_cagr_5y is None
        assert r.graham_value is None

    def test_the_net_income_fallback_is_a_measurement(self):
        """No per-share row, but net income compounds: that is the labelled source."""
        income = pd.DataFrame(
            {"Net Income": [130.0, 120.0, 110.0, 100.0]},
            index=[f"{2025 - i}-12-31 00:00:00" for i in range(4)],
        ).T
        info = {"longName": "Test Co", "sector": "Technology", "industry": "Software",
                "country": "United States", "trailingEps": 5.0, "currentPrice": 30.0,
                "regularMarketPrice": 30.0, "marketCap": 1e10}
        with (
            patch("analysis.fundamental.get_info", return_value=info),
            patch("analysis.fundamental.get_financials", return_value={
                "income_stmt": income, "balance_sheet": pd.DataFrame(), "cashflow": pd.DataFrame()}),
            patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
            patch("data.fetcher.get_info_age_hours", return_value=1.0),
        ):
            r = FundamentalAnalyzer().analyze("TEST")
        assert r.eps_growth_source == "net_income_cagr"
        want = oracle_graham(5.0, oracle_cagr_pct([130.0, 120.0, 110.0, 100.0]),
                             THRESHOLDS.graham_aaa_yield_pct, THRESHOLDS.graham_max_growth_pct)
        assert r.graham_value == pytest.approx(want, abs=0.01)

    def test_growth_above_the_cap_is_cut_to_the_cap(self):
        eps_by_year = [20.0, 10.0, 5.0, 2.5, 1.25]          # doubles every year: +100 %
        assert oracle_cagr_pct(eps_by_year) > THRESHOLDS.graham_max_growth_pct
        r = _analyze(eps=20.0, eps_by_year=eps_by_year)
        want = oracle_graham(20.0, oracle_cagr_pct(eps_by_year),
                             THRESHOLDS.graham_aaa_yield_pct, THRESHOLDS.graham_max_growth_pct)
        assert r.graham_value == pytest.approx(want, abs=0.01)

    def test_the_labelled_quarterly_fallback_still_prices(self):
        """A positive yoy with no statements is a (weak, labelled) measurement, not an absence."""
        r = _analyze(eps=5.0, earnings_growth=0.12)
        assert r.eps_growth_source == "yoy"
        want = oracle_graham(5.0, 12.0, THRESHOLDS.graham_aaa_yield_pct, THRESHOLDS.graham_max_growth_pct)
        assert r.graham_value == pytest.approx(want, abs=0.01)

    def test_no_earnings_still_no_value(self):
        assert _analyze(eps=-1.0, eps_by_year=[5.0] * 5).graham_value is None


class TestUnknownGrowthInOtherUnits:
    def test_a_london_quote_with_unknown_growth_has_no_value_either(self):
        """The pence conversion must not resurrect a value the growth check removed."""
        info = {"longName": "Shell", "sector": "Energy", "industry": "Oil", "country": "United Kingdom",
                "trailingEps": 3.0, "currency": "GBp", "currentPrice": 1500.0,
                "regularMarketPrice": 1500.0, "marketCap": 1e11}
        with (
            patch("analysis.fundamental.get_info", return_value=info),
            patch("analysis.fundamental.get_financials", return_value={
                "income_stmt": pd.DataFrame(), "balance_sheet": pd.DataFrame(), "cashflow": pd.DataFrame()}),
            patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
            patch("data.fetcher.get_info_age_hours", return_value=1.0),
        ):
            r = FundamentalAnalyzer().analyze("SHEL.L")
        assert r.graham_value is None and r.margin_of_safety_pct is None


class TestWhatTheUserIsTold:
    def test_a_strong_buy_with_no_measurable_margin_does_not_say_wait_for_a_pullback(self):
        """Absence is not a market reading: «esperá una baja» is for a margin that was computed."""
        from types import SimpleNamespace

        from analysis.strategy import RetirementStrategy
        from config import STRATEGY

        def fund(mos):
            return SimpleNamespace(
                symbol="T", total_score=95.0, adjusted_score=95.0, is_crypto=False,
                debt_equity=0.5, pb_ratio=2.0, margin_of_safety_pct=mos,
                graham_value=100.0 if mos else None,
                is_value_stock=lambda: mos is not None and mos >= STRATEGY.min_margin_of_safety_pct,
                roe=20.0, revenue_cagr_5y=10.0, fcf_yield=4.0, payout_ratio=40.0, warnings=[],
                data_quality={"level": "good"}, tailwind_classification="Neutral", tailwind_detail=None,
            )

        tech = SimpleNamespace(
            signal="BULLISH", above_sma200=True, price_vs_52w_low_pct=20.0, rsi_weekly=55.0,
            golden_cross=False, sma200_slope_pct=2.0, warnings=[], price_vs_52w_high_pct=-3.0,
            price=100.0, atr_pct=2.0, adx=30.0,
        )
        unmeasured = RetirementStrategy().decide(fund(None), tech)
        too_thin = RetirementStrategy().decide(fund(5.0), tech)
        assert unmeasured.action == too_thin.action == "BUY"
        assert "no medible" in unmeasured.decisive_reason
        assert "esperar una baja" not in unmeasured.decisive_reason
        assert "esperar una baja" in too_thin.decisive_reason       # a computed, thin margin still says it

    def test_the_help_says_a_missing_rate_is_not_a_published_value(self):
        from data.product_ux import graham_value_help

        assert "Sin g medido" in graham_value_help()
