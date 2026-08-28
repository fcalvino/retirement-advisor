"""Growth CAGR over the window the data actually supports (oracle-first, CONTEXT §5).

The defect: `_score_growth` called `compute_cagr(series, years=5)`, which requires
6 annual data points (`len(series) < years + 1 → None`). yfinance's statements
return **4** annual periods, so the condition was unsatisfiable and
`revenue_cagr_5y` came back `None` for **78 of 78** companies in the US Quality
universe — measured 2026-08-17. Consequences:

  * the 7 revenue-growth points inside the 20-point growth dimension were
    unreachable for every company, so every score in the product was deflated by
    the same amount against thresholds calibrated on 100;
  * `revenue_cagr_5y` is one of the 10 `_QUALITY_KEY_FIELDS`, and "partial" needs
    only 3 missing, so every ticker started one strike down — the single largest
    contributor to the "82% con datos incompletos" headline;
  * the Screener's "Rev CAGR 5Y" column was empty in all 78 rows.

The data was never missing. MSFT's four periods give a perfectly good 3-year
CAGR of 16.1%/yr. The fix computes over the longest window available and reports
which window it used, instead of demanding a 5-year window nobody can supply.

Per CONTEXT §5 the oracle below is derived from the definition of compound
growth — compound the start value forward n times and check it lands on the end
value — never from the production source.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from config import THRESHOLDS, FundamentalThresholds
from data.fetcher import compute_cagr, compute_cagr_available

# --------------------------------------------------------------------------- #
#  Oracle                                                                     #
# --------------------------------------------------------------------------- #


def oracle_cagr(start_value: float, end_value: float, n_years: int) -> float:
    """The rate r such that compounding start_value n times lands on end_value.

    Solved by bisection on a forward-compounding loop, so it derives from the
    definition of compound growth rather than from the closed-form the engine
    uses.
    """
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


def _series(values_recent_first):
    """yfinance orders annual statements most-recent-first."""
    return pd.Series(list(values_recent_first), dtype=float)


def test_oracle_agrees_with_the_closed_form_on_known_growth():
    """Sanity-check the oracle itself before trusting it as a reference."""
    # 100 → 200 over 3 years is 2^(1/3)-1 = 25.99%/yr.
    assert oracle_cagr(100.0, 200.0, 3) == pytest.approx(0.259921, abs=1e-5)
    # Flat series grows at zero.
    assert oracle_cagr(500.0, 500.0, 4) == pytest.approx(0.0, abs=1e-6)
    # Exact doubling every year.
    assert oracle_cagr(10.0, 80.0, 3) == pytest.approx(1.0, abs=1e-6)


# --------------------------------------------------------------------------- #
#  The window the data supports                                               #
# --------------------------------------------------------------------------- #


def test_four_periods_yield_a_three_year_cagr_matching_the_oracle():
    """The production case: 4 annual statements → a 3-year window, not None."""
    msft = _series([331839000000.0, 281724000000.0, 245122000000.0, 211915000000.0])

    cagr, years = compute_cagr_available(msft, target_years=5, min_years=3)

    assert years == 3
    assert cagr == pytest.approx(oracle_cagr(211915000000.0, 331839000000.0, 3), rel=1e-9)
    assert cagr == pytest.approx(0.16124, abs=1e-4)   # 16.1%/yr — the real number


@pytest.mark.parametrize(
    "values,expected_years",
    [
        ([200.0, 150.0, 120.0, 100.0], 3),                       # 4 points → 3y
        ([200.0, 180.0, 150.0, 120.0, 100.0], 4),                # 5 points → 4y
        ([200.0, 190.0, 180.0, 150.0, 120.0, 100.0], 5),         # 6 points → capped at target
        ([250.0, 200.0, 190.0, 180.0, 150.0, 120.0, 100.0], 5),  # 7 points → still 5
    ],
)
def test_uses_longest_window_available_capped_at_target(values, expected_years):
    cagr, years = compute_cagr_available(_series(values), target_years=5, min_years=3)
    assert years == expected_years
    assert cagr == pytest.approx(
        oracle_cagr(values[expected_years], values[0], expected_years), rel=1e-9
    )


def test_below_the_minimum_window_returns_nothing():
    """Two points is a one-year change, not a growth *rate* worth scoring."""
    cagr, years = compute_cagr_available(_series([120.0, 100.0]), target_years=5, min_years=3)
    assert cagr is None and years == 0
    cagr, years = compute_cagr_available(_series([120.0, 110.0, 100.0]), target_years=5, min_years=3)
    assert cagr is None and years == 0   # 3 points = 2 years, below min


def test_nan_and_nonpositive_values_are_handled():
    assert compute_cagr_available(_series([]), target_years=5, min_years=3) == (None, 0)
    # A NaN in the middle shortens the usable window rather than poisoning it.
    with_nan = pd.Series([200.0, float("nan"), 150.0, 120.0, 100.0])
    cagr, years = compute_cagr_available(with_nan, target_years=5, min_years=3)
    assert years == 3 and cagr is not None
    # Negative or zero start (a loss-making year) is not a valid CAGR base.
    cagr, years = compute_cagr_available(_series([200.0, 150.0, 120.0, -5.0]), target_years=5, min_years=3)
    assert cagr is None and years == 0


def test_shrinking_revenue_gives_a_negative_rate():
    values = [80.0, 90.0, 95.0, 100.0]
    cagr, years = compute_cagr_available(_series(values), target_years=5, min_years=3)
    assert years == 3
    assert cagr < 0
    assert cagr == pytest.approx(oracle_cagr(100.0, 80.0, 3), rel=1e-9)


# --------------------------------------------------------------------------- #
#  The old fixed-window helper is untouched                                   #
# --------------------------------------------------------------------------- #


def test_compute_cagr_keeps_its_contract_for_the_other_call_sites():
    """FCF (years=3) and crypto (years=4) must not move."""
    four = _series([200.0, 150.0, 120.0, 100.0])
    assert compute_cagr(four, years=3) == pytest.approx(oracle_cagr(100.0, 200.0, 3), rel=1e-9)
    assert compute_cagr(four, years=5) is None      # still None — unchanged contract
    five = _series([200.0, 180.0, 150.0, 120.0, 100.0])
    assert compute_cagr(five, years=4) == pytest.approx(oracle_cagr(100.0, 200.0, 4), rel=1e-9)


# --------------------------------------------------------------------------- #
#  Scoring consequence                                                        #
# --------------------------------------------------------------------------- #


def _income_stmt(revenue_recent_first, net_income_recent_first=None):
    cols = [f"{2026 - i}-06-30" for i in range(len(revenue_recent_first))]
    data = {"Total Revenue": revenue_recent_first}
    if net_income_recent_first:
        data["Net Income"] = net_income_recent_first
    return pd.DataFrame(data, index=cols).T


def test_revenue_growth_points_are_now_reachable():
    """The 7-point revenue branch used to be dead code for every company."""
    analyzer = FundamentalAnalyzer()
    result = FundamentalResult(symbol="MSFT")
    inc = _income_stmt([331839e6, 281724e6, 245122e6, 211915e6])

    score = analyzer._score_growth({}, inc, pd.DataFrame(), result)

    assert result.revenue_cagr_5y is not None
    assert result.revenue_cagr_5y == pytest.approx(16.1, abs=0.1)
    assert result.revenue_cagr_years == 3
    # 16.1% clears "excellent", which is worth the full 7 points.
    assert result.revenue_cagr_5y >= THRESHOLDS.revenue_cagr_excellent
    assert score >= 7


def test_the_window_used_is_reported_not_assumed():
    """The UI must be able to say '3 años', not hardcode '5Y'."""
    analyzer = FundamentalAnalyzer()
    result = FundamentalResult(symbol="X")
    analyzer._score_growth(
        {}, _income_stmt([200.0, 180.0, 150.0, 120.0, 100.0]), pd.DataFrame(), result
    )
    assert result.revenue_cagr_years == 4

    short = FundamentalResult(symbol="Y")
    analyzer._score_growth({}, _income_stmt([120.0, 100.0]), pd.DataFrame(), short)
    assert short.revenue_cagr_5y is None
    assert short.revenue_cagr_years == 0


def test_net_income_fallback_also_uses_the_available_window():
    """eps_cagr's fallback had the same dead `years=5` condition."""
    analyzer = FundamentalAnalyzer()
    result = FundamentalResult(symbol="Z")
    inc = _income_stmt([200.0, 180.0, 150.0, 120.0], [90.0, 70.0, 60.0, 50.0])

    analyzer._score_growth({}, inc, pd.DataFrame(), result)   # no earningsGrowth in info

    assert result.eps_cagr_5y is not None
    assert result.eps_cagr_years == 3
    assert result.eps_cagr_5y == pytest.approx(oracle_cagr(50.0, 90.0, 3) * 100, abs=0.1)


def test_no_scoring_branch_demands_a_window_the_feed_cannot_supply():
    """Guard: a fixed `years=N` needs N+1 points, and yfinance ships 4.

    This is the shape of the original bug — a threshold nobody could meet, failing
    silently as `None` instead of loudly. Any future fixed-window call in the
    scoring engine must stay inside what the data can actually cover.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "analysis" / "fundamental.py").read_text()
    YFINANCE_ANNUAL_PERIODS = 4   # measured on MSFT/KO/AAPL, yfinance 1.4.0

    for match in re.finditer(r"compute_cagr\([^)]*years=(\d+)", src):
        years = int(match.group(1))
        assert years + 1 <= YFINANCE_ANNUAL_PERIODS, (
            f"compute_cagr(years={years}) needs {years + 1} annual points but the feed "
            f"provides {YFINANCE_ANNUAL_PERIODS} — this branch can never fire. "
            "Use compute_cagr_available() instead."
        )


def test_ui_labels_report_the_window_instead_of_hardcoding_5y():
    """The Screener column and Stock Analysis metric must not claim '5Y'."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    screener = (root / "dashboard" / "pages" / "1_Screener.py").read_text()
    shared = (root / "dashboard" / "shared.py").read_text()
    stock = (root / "dashboard" / "pages" / "2_Stock_Analysis.py").read_text()

    assert "Rev CAGR 5Y" not in screener and "Rev CAGR 5Y" not in shared
    assert '"Rev CAGR %"' in screener and '"CAGR años"' in screener
    assert "revenue_cagr_years" in shared
    # Stock Analysis builds its label from the measured window.
    assert '"Revenue CAGR 5Y"' not in stock
    assert "fund.revenue_cagr_years" in stock


def test_windows_come_from_config():
    cfg = FundamentalThresholds(cagr_target_years=3, cagr_min_years=2)
    cagr, years = compute_cagr_available(
        _series([200.0, 150.0, 120.0, 100.0]), target_years=cfg.cagr_target_years,
        min_years=cfg.cagr_min_years,
    )
    assert years == 3
    assert THRESHOLDS.cagr_target_years == 5
    assert THRESHOLDS.cagr_min_years == 3
