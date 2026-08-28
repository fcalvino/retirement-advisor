"""Dividend-yield unit normalization — oracle + regression (CONTEXT §5).

The defect: yfinance reports its three dividend fields in three different units,
and `_score_dividends` multiplied the wrong one by 100. Measured on the live feed
(yfinance 1.4.0, 2026-08-17):

    field                        SCHD      BND       VGT      SPY       KO
    trailingAnnualDividendRate   0.0       None      None     5.6620    2.0800
    trailingAnnualDividendYield  0.0       None      None     0.0073    0.0237
    dividendYield                3.1300    4.0300    0.3800   1.0100    2.4200

`(trailingAnnualDividendYield or dividendYield) * 100` fell through to
`dividendYield` — already a percent — for every ticker whose first two fields
were empty, and multiplied it by 100 again: SCHD 313%, BND 403%, VGT 38%.

That is a scoring bug, not a display bug: `_score_dividends` grades against
`THRESHOLDS.div_yield_sweet_spot_high` (4%), so a healthy 3.13% payer was booked
as a distressed 313% one and lost points.

Per CONTEXT §5 the oracle below is written from the *definition* of a trailing
yield — dividends paid per share over the last year, divided by the price — not
from the production source.
"""

from __future__ import annotations

import pytest

from analysis.fundamental import (
    FundamentalAnalyzer,
    FundamentalResult,
    normalize_dividend_yield_pct,
)
from config import THRESHOLDS, FundamentalThresholds

# --------------------------------------------------------------------------- #
#  Oracle: yield = dividends per share over one year / price, in percent       #
# --------------------------------------------------------------------------- #


def oracle_yield_pct(dividends_per_share_last_year: float, price_per_share: float) -> float:
    """Reference implementation, straight from the definition. Deliberately naive."""
    if price_per_share <= 0:
        raise ValueError("price must be positive")
    total = 0.0
    for payment in dividends_per_share_last_year if isinstance(
        dividends_per_share_last_year, (list, tuple)
    ) else [dividends_per_share_last_year]:
        total += float(payment)
    return total / float(price_per_share) * 100.0


@pytest.mark.parametrize(
    "quarterly,price,expected",
    [
        ([0.52, 0.52, 0.52, 0.52], 87.03, 2.390),    # KO-shaped: 4 equal payments
        ([1.31, 1.31, 1.31, 1.31], 263.52, 1.988),   # JNJ-shaped
        ([0.25, 0.25, 0.25, 0.30], 303.20, 0.346),   # AAPL-shaped, one raise
        ([0.27, 0.27, 0.27, 0.27], 34.265, 3.152),   # SCHD-shaped — the bug case
    ],
)
def test_oracle_matches_the_normalizer_via_rate_and_price(quarterly, price, expected):
    """Feed the rate/price path and check it reproduces the definition."""
    annual_rate = sum(quarterly)
    assert oracle_yield_pct(quarterly, price) == pytest.approx(expected, abs=0.01)

    got = normalize_dividend_yield_pct(
        {"trailingAnnualDividendRate": annual_rate, "currentPrice": price}
    )
    assert got == pytest.approx(oracle_yield_pct(quarterly, price), rel=1e-9)


# --------------------------------------------------------------------------- #
#  Each field is read in its own unit                                         #
# --------------------------------------------------------------------------- #


def test_dividend_yield_field_is_a_percent_and_is_not_rescaled():
    """The actual bug: `dividendYield` must be used as-is, never ×100."""
    assert normalize_dividend_yield_pct({"dividendYield": 3.13}) == pytest.approx(3.13)
    assert normalize_dividend_yield_pct({"dividendYield": 4.03}) == pytest.approx(4.03)
    assert normalize_dividend_yield_pct({"dividendYield": 0.38}) == pytest.approx(0.38)


def test_trailing_annual_dividend_yield_field_is_a_fraction_and_is_rescaled():
    assert normalize_dividend_yield_pct(
        {"trailingAnnualDividendYield": 0.0237}
    ) == pytest.approx(2.37)


def test_rate_over_price_wins_so_working_tickers_do_not_move():
    """Step 1 stays first: anything that already resolved keeps its exact value."""
    spy = {
        "trailingAnnualDividendRate": 5.6620,
        "trailingAnnualDividendYield": 0.0073,
        "dividendYield": 1.0100,
        "currentPrice": 775.37,
    }
    assert normalize_dividend_yield_pct(spy) == pytest.approx(5.6620 / 775.37 * 100)
    assert normalize_dividend_yield_pct(spy) == pytest.approx(0.7302, abs=0.001)


# --------------------------------------------------------------------------- #
#  The measured production cases                                              #
# --------------------------------------------------------------------------- #

# Exactly what yfinance 1.4.0 returned on 2026-08-17.
_LIVE_SHAPES = {
    "SCHD": ({"trailingAnnualDividendRate": 0.0, "trailingAnnualDividendYield": 0.0,
              "dividendYield": 3.13, "currentPrice": 34.2650}, 3.13),
    "BND":  ({"dividendYield": 4.03, "currentPrice": 72.2448}, 4.03),
    "VGT":  ({"dividendYield": 0.38, "currentPrice": 123.2290}, 0.38),
    "SPY":  ({"trailingAnnualDividendRate": 5.6620, "trailingAnnualDividendYield": 0.0073,
              "dividendYield": 1.01, "currentPrice": 775.37}, 0.7302),
    "QQQ":  ({"trailingAnnualDividendRate": 1.7700, "trailingAnnualDividendYield": 0.0024,
              "dividendYield": 0.44, "currentPrice": 733.60}, 0.2413),
    "KO":   ({"trailingAnnualDividendRate": 2.0800, "trailingAnnualDividendYield": 0.0237,
              "dividendYield": 2.42, "currentPrice": 87.0250}, 2.3901),
    "AAPL": ({"trailingAnnualDividendRate": 1.0500, "trailingAnnualDividendYield": 0.0034,
              "dividendYield": 0.35, "currentPrice": 303.2050}, 0.3463),
}


@pytest.mark.parametrize("symbol", sorted(_LIVE_SHAPES))
def test_live_feed_shapes_resolve_to_a_plausible_percent(symbol):
    info, expected = _LIVE_SHAPES[symbol]
    got = normalize_dividend_yield_pct(info)
    assert got == pytest.approx(expected, abs=0.01)
    # Every one of them is a believable yield now.
    assert 0 < got < THRESHOLDS.max_plausible_dividend_yield_pct


def test_the_three_broken_tickers_are_no_longer_off_by_100x():
    """SCHD 313 → 3.13, BND 403 → 4.03, VGT 38 → 0.38."""
    for symbol, shipped_wrong in (("SCHD", 313.0), ("BND", 403.0), ("VGT", 38.0)):
        info, expected = _LIVE_SHAPES[symbol]
        got = normalize_dividend_yield_pct(info)
        assert got == pytest.approx(shipped_wrong / 100.0, abs=0.01)
        assert got == pytest.approx(expected, abs=0.01)


# --------------------------------------------------------------------------- #
#  Plausibility guard                                                         #
# --------------------------------------------------------------------------- #


def test_implausible_yield_is_rejected_not_published():
    """If the feed flips conventions again, return None rather than a wrong number."""
    warnings: list = []
    got = normalize_dividend_yield_pct({"dividendYield": 313.0}, warnings=warnings)
    assert got is None
    assert warnings and "implausible" in warnings[0]
    assert "313" in warnings[0]


def test_plausibility_ceiling_comes_from_config():
    cfg = FundamentalThresholds(max_plausible_dividend_yield_pct=500.0)
    assert normalize_dividend_yield_pct({"dividendYield": 313.0}, config=cfg) == pytest.approx(313.0)
    assert normalize_dividend_yield_pct({"dividendYield": 313.0}) is None


def test_no_dividend_returns_none():
    assert normalize_dividend_yield_pct({}) is None
    assert normalize_dividend_yield_pct({"dividendYield": 0.0}) is None
    assert normalize_dividend_yield_pct({"trailingAnnualDividendRate": 2.0}) is None  # no price
    assert normalize_dividend_yield_pct({"currentPrice": 100.0}) is None


def test_zero_price_does_not_divide_by_zero():
    assert normalize_dividend_yield_pct(
        {"trailingAnnualDividendRate": 2.0, "currentPrice": 0.0, "dividendYield": 2.5}
    ) == pytest.approx(2.5)


# --------------------------------------------------------------------------- #
#  Scoring consequence — the reason this was not merely cosmetic              #
# --------------------------------------------------------------------------- #


def test_schd_is_scored_as_a_healthy_payer_not_a_distressed_one():
    """3.13% sits inside the sweet spot; 313% used to land in the risky branch."""
    analyzer = FundamentalAnalyzer()
    result = FundamentalResult(symbol="SCHD")
    info, _ = _LIVE_SHAPES["SCHD"]

    score = analyzer._score_dividends({**info, "payoutRatio": 0.45}, result)

    assert result.dividend_yield == pytest.approx(3.13, abs=0.01)
    assert THRESHOLDS.div_yield_sweet_spot_low <= result.dividend_yield <= THRESHOLDS.div_yield_sweet_spot_high
    assert not any("High yield may signal risk" in w for w in result.warnings)
    # Sweet-spot credit (4) beats the 1 point the risky branch used to give.
    assert score >= 4


def test_a_genuinely_high_yield_still_warns():
    """The guard must not swallow real distress signals."""
    analyzer = FundamentalAnalyzer()
    result = FundamentalResult(symbol="RISKY")
    analyzer._score_dividends(
        {"trailingAnnualDividendRate": 9.0, "currentPrice": 100.0}, result
    )
    assert result.dividend_yield == pytest.approx(9.0)
    assert any("High yield may signal risk" in w for w in result.warnings)
