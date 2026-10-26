"""A year without earnings does not convert earnings into cash (audit 2026-10-26).

``_fcf_conversion`` averaged ``OCF / Net Income`` over the years both rows reported,
dropping only the years whose net income was exactly 0. The ratio of two numbers is
only a measure of "earnings backed by cash" when the earnings are positive; with a
loss it is something else entirely:

    NI -100, OCF -130   ->  +1.30   (a company burning MORE cash than it loses)
                                     scored as excellent conversion: the full 2 points
    NI  -50, OCF +40    ->  -0.80   (a loss year with positive cash, read as a failure)

The first is the defect: two negatives make a positive ratio, so a cash-burning loss-maker
sat above ``fcf_conversion_excellent`` (1.2) and collected the maximum, in a score that
reads "moat" and feeds the adjusted score. The second shows the metric was not measuring
anything on those years either — and fixing it moves a score UP, not only down.

**Rule, stated:** a year with no positive net income has no earnings for cash to back, so its
conversion is **0** — it counts in the average, and it adds nothing. It does not drop out
(excluding it would hand a company with one profitable year the points of that year alone),
and it does not become a ratio of signs. Years with positive earnings are unchanged, so a
company that earns money every year scores exactly as before.

The reference below is written from that definition with plain loops, not from the source.
Not changed here, and said so: a tiny positive net income still makes a huge ratio.

No network.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.moat import MoatAnalyzer, MoatDetail
from config import MOAT

YEARS = ["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]


def _stmt(**rows) -> pd.DataFrame:
    n = len(next(iter(rows.values())))
    return pd.DataFrame({k: dict(zip(YEARS[-n:], v)) for k, v in rows.items()}).T[YEARS[-n:]]


def oracle_conversion(net_income, operating_cash_flow):
    """Mean over the years of: OCF / NI when NI > 0 (at most the per-year cap), else 0. None if no year."""
    years = list(zip(net_income, operating_cash_flow))
    if not years:
        return None
    total = 0.0
    for ni, ocf in years:
        total += min(ocf / ni, MOAT.fcf_conversion_year_cap) if ni > 0 else 0.0
    return total / len(years)


def _engine(ni, ocf):
    income = _stmt(**{"Net Income": ni})
    cash = _stmt(**{"Operating Cash Flow": ocf})
    return MoatAnalyzer()._fcf_conversion(income, cash)


def _points(ni, ocf) -> float:
    d = MoatDetail()
    income = _stmt(**{"Net Income": ni})
    cash = _stmt(**{"Operating Cash Flow": ocf})
    MoatAnalyzer()._score_quant(d, {}, income, pd.DataFrame(), cash)
    return d.fcf_conversion


class TestALossIsNotConversion:
    def test_two_negatives_do_not_make_an_excellent_conversion(self):
        """The finding: -130 / -100 = +1.30 used to clear the 1.2 bar and earn the 2 points."""
        ni, ocf = [-100.0] * 4, [-130.0] * 4
        assert _engine(ni, ocf) == pytest.approx(oracle_conversion(ni, ocf)) == pytest.approx(0.0)
        assert _points(ni, ocf) == 0.0

    def test_the_old_reading_would_have_given_the_maximum(self):
        """Anti-cheat on the test itself: the case really did clear the bar by sign alone."""
        assert (-130.0 / -100.0) >= MOAT.fcf_conversion_excellent

    def test_a_loss_year_counts_as_zero_in_the_average(self):
        ni, ocf = [100.0, -50.0, 120.0, 110.0], [130.0, 40.0, 150.0, 120.0]
        assert _engine(ni, ocf) == pytest.approx(oracle_conversion(ni, ocf))

    def test_a_loss_year_with_positive_cash_is_no_longer_read_as_a_failure(self):
        """It moves the other way too. [1.3, loss, 1.25, 1.09]: the ratio of signs read the loss year
        as -0.8 (mean 0.71, half a point); as «no earnings, conversion 0» the mean is 0.91, one point."""
        ni, ocf = [100.0, -50.0, 120.0, 110.0], [130.0, 40.0, 150.0, 120.0]
        assert _engine(ni, ocf) >= MOAT.fcf_conversion_good
        assert _points(ni, ocf) == 1.0

    def test_zero_net_income_is_also_nothing_to_back(self):
        ni, ocf = [0.0, 100.0], [50.0, 120.0]
        assert _engine(ni, ocf) == pytest.approx(oracle_conversion(ni, ocf))


class TestProfitableYearsAreUnchanged:
    @pytest.mark.parametrize("ni,ocf", [
        ([100.0, 110.0, 120.0, 130.0], [130.0, 140.0, 150.0, 160.0]),       # strong conversion
        ([100.0, 110.0, 120.0], [95.0, 100.0, 110.0]),                      # about 0.9
        ([100.0, 110.0, 120.0, 130.0], [40.0, 50.0, 55.0, 60.0]),           # weak
        ([100.0, 100.0], [-20.0, 150.0]),                                   # a cash-negative profit year
    ])
    def test_it_matches_the_oracle_and_the_old_mean_of_ratios(self, ni, ocf):
        old = sum(o / n for n, o in zip(ni, ocf)) / len(ni)     # what the engine returned before
        assert _engine(ni, ocf) == pytest.approx(oracle_conversion(ni, ocf)) == pytest.approx(old)

    def test_a_company_that_earns_every_year_keeps_its_points(self):
        assert _points([100.0] * 4, [130.0] * 4) == 2.0
        assert _points([100.0] * 4, [95.0] * 4) == 1.0
        assert _points([100.0] * 4, [65.0] * 4) == 0.5
        assert _points([100.0] * 4, [30.0] * 4) == 0.0


class TestASliverOfEarningsDoesNotDecideTheMean:
    def test_three_loss_years_and_one_near_breakeven_year_do_not_earn_the_maximum(self):
        """NI [-50, -50, -50, 5], OCF [40, 40, 40, 30]: the last year is a ratio of 6. Uncapped, the
        mean is 1.5 and the company takes 2 points on one year; capped at 2.4 it is 0.6, half a point."""
        ni, ocf = [-50.0, -50.0, -50.0, 5.0], [40.0, 40.0, 40.0, 30.0]
        assert 30.0 / 5.0 > MOAT.fcf_conversion_year_cap
        assert _engine(ni, ocf) == pytest.approx(oracle_conversion(ni, ocf)) == pytest.approx(
            MOAT.fcf_conversion_year_cap / 4)
        assert _points(ni, ocf) == 0.5                     # 0.6 just reaches the lowest band
        assert _engine(ni, ocf) < MOAT.fcf_conversion_excellent

    def test_a_ratio_under_the_cap_is_untouched(self):
        ni, ocf = [100.0, 100.0], [220.0, 230.0]           # 2.2 and 2.3, both under 2.4
        assert _engine(ni, ocf) == pytest.approx((2.2 + 2.3) / 2)

    def test_the_cap_comes_from_config(self):
        from unittest.mock import patch

        ni, ocf = [10.0, 10.0], [100.0, 100.0]             # ratio 10
        with patch.object(MOAT, "fcf_conversion_year_cap", 1.5):
            assert _engine(ni, ocf) == pytest.approx(1.5)
        assert _engine(ni, ocf) == pytest.approx(MOAT.fcf_conversion_year_cap)


class TestTheRowsTheEngineActuallyReads:
    def test_the_alternative_cash_flow_row_name_is_read(self):
        income = _stmt(**{"Net Income": [100.0, 100.0]})
        cash = _stmt(**{"Cash Flow From Continuing Operating Activities": [130.0, 130.0]})
        assert MoatAnalyzer()._fcf_conversion(income, cash) == pytest.approx(1.3)

    def test_only_the_years_both_rows_report_count(self):
        """NI has four years, OCF three: the earliest year has no cash flow, so it is not an average term."""
        income = _stmt(**{"Net Income": [100.0, 100.0, 100.0, 100.0]})
        cash = _stmt(**{"Operating Cash Flow": [120.0, 120.0, 120.0]})
        assert MoatAnalyzer()._fcf_conversion(income, cash) == pytest.approx(1.2)

    def test_a_blank_cell_is_not_a_year(self):
        income = _stmt(**{"Net Income": [100.0, float("nan"), 100.0, 100.0]})
        cash = _stmt(**{"Operating Cash Flow": [120.0, 999.0, 120.0, 120.0]})
        assert MoatAnalyzer()._fcf_conversion(income, cash) == pytest.approx(1.2)


class TestNothingToMeasure:
    def test_no_shared_year_is_none(self):
        income = pd.DataFrame({"Net Income": {"2022-12-31": 100.0}}).T
        cash = pd.DataFrame({"Operating Cash Flow": {"2025-12-31": 120.0}}).T
        assert MoatAnalyzer()._fcf_conversion(income, cash) is None

    def test_missing_rows_are_none(self):
        assert MoatAnalyzer()._fcf_conversion(pd.DataFrame(), pd.DataFrame()) is None
