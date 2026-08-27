"""Dividend growth streak over complete years (oracle-first, CONTEXT §5).

The defect: ``_score_dividends`` summed dividends with ``divs.resample("YE")`` and
walked the result newest-first looking for consecutive growth. The newest bucket is
the calendar year *in progress*, which holds two or three payments where the prior
full year holds four — so the very first comparison failed and the streak came back
0 for any normal quarterly payer.

Measured on the cached universe (2026-08-22): 134 of 141 dividend payers scored a
streak of 0. JNJ, with 63 consecutive years of raises, scored 0. MCD 0 against 50,
XOM 0 against 42. Excluding the partial year drops the "no streak" count to 22 of
141. The three points gated behind ``streak >= 10`` were unreachable across the
product and the "Dividend Aristocrat" note could never fire.

Per CONTEXT §5 the oracle below is written from the *definition* of the metric —
"how many complete calendar years in a row did the total paid rise?" — counted with
a plain loop over a hand-built {year: total} mapping. It never calls ``resample``
and never imports the production path, so it cannot inherit the production bug.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, annual_dividend_totals

# --------------------------------------------------------------------------- #
#  Oracle                                                                     #
# --------------------------------------------------------------------------- #

def oracle_streak(payments: List[Tuple[str, float]], today: date) -> int:
    """Consecutive complete calendar years of dividend growth, counted by hand.

    Derived from the definition: bucket every payment into its calendar year,
    throw away any year that has not finished yet, then walk backwards from the
    newest surviving year counting how many times the total rose year over year.
    """
    totals: Dict[int, float] = {}
    for iso_date, amount in payments:
        year = int(iso_date[:4])
        totals[year] = totals.get(year, 0.0) + amount

    complete = {y: t for y, t in totals.items() if date(y, 12, 31) <= today and t > 0}

    years = sorted(complete, reverse=True)
    streak = 0
    for newer, older in zip(years, years[1:]):
        if complete[newer] > complete[older]:
            streak += 1
        else:
            break
    return streak


def _payments(
    start_year: int,
    yearly_totals: List[float],
    *,
    quarters_in_last_year: int = 4,
) -> List[Tuple[str, float]]:
    """Quarterly payments that sum to each requested annual total."""
    months = ("03-15", "06-15", "09-15", "12-15")
    out: List[Tuple[str, float]] = []
    for offset, total in enumerate(yearly_totals):
        year = start_year + offset
        n = quarters_in_last_year if offset == len(yearly_totals) - 1 else 4
        for month_day in months[:n]:
            out.append((f"{year}-{month_day}", total / 4.0))
    return out


def _series(payments: List[Tuple[str, float]]) -> pd.Series:
    s = pd.Series({pd.Timestamp(d): v for d, v in payments}, dtype=float)
    return s.sort_index()


def _engine_streak(payments: List[Tuple[str, float]], today: Optional[date]) -> int:
    annual = annual_dividend_totals(_series(payments), today=today)
    return FundamentalAnalyzer()._consecutive_growth_streak(annual)


# --------------------------------------------------------------------------- #
#  Oracle self-check                                                          #
# --------------------------------------------------------------------------- #

class TestOracle:
    def test_oracle_counts_a_simple_rising_run(self):
        pays = _payments(2020, [1.0, 2.0, 3.0, 4.0])
        assert oracle_streak(pays, date(2026, 8, 22)) == 3

    def test_oracle_stops_at_a_cut(self):
        pays = _payments(2020, [1.0, 2.0, 1.5, 4.0])
        # 2023 > 2022 counts, 2022 < 2021 stops it.
        assert oracle_streak(pays, date(2026, 8, 22)) == 1

    def test_oracle_ignores_the_year_in_progress(self):
        pays = _payments(2020, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])  # last = 2026
        assert oracle_streak(pays, date(2026, 8, 22)) == 5  # 2020..2025 → 5 rises


# --------------------------------------------------------------------------- #
#  The defect itself                                                          #
# --------------------------------------------------------------------------- #

class TestPartialYearDoesNotBreakTheStreak:
    def test_jnj_shaped_aristocrat_keeps_its_streak(self):
        """12 full rising years + a half-finished current year → 11, not 0."""
        totals = [1.0 + 0.1 * i for i in range(13)]          # 2014..2026
        pays = _payments(2014, totals, quarters_in_last_year=2)
        today = date(2026, 8, 22)

        expected = oracle_streak(pays, today)
        assert expected == 11
        assert _engine_streak(pays, today) == expected

    def test_the_old_behaviour_is_what_the_oracle_rejects(self):
        """Including the partial year is exactly the bug: it reads as a cut."""
        totals = [1.0 + 0.1 * i for i in range(13)]
        pays = _payments(2014, totals, quarters_in_last_year=2)

        with_partial = _series(pays).resample("YE").sum()
        naive = FundamentalAnalyzer()._consecutive_growth_streak(with_partial[with_partial > 0])

        assert naive == 0                                    # the shipped bug
        assert _engine_streak(pays, date(2026, 8, 22)) == 11  # the fix

    def test_streak_scores_the_aristocrat_points(self):
        """The 3 points behind `streak >= 10` become reachable again."""
        totals = [1.0 + 0.1 * i for i in range(13)]
        pays = _payments(2014, totals, quarters_in_last_year=2)
        assert _engine_streak(pays, date(2026, 8, 22)) >= 10


# --------------------------------------------------------------------------- #
#  Engine agrees with the oracle across shapes                                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "totals,quarters_last,today,label",
    [
        ([1.0, 1.1, 1.2, 1.3, 1.4], 4, date(2026, 8, 22), "all years closed"),
        ([1.0, 1.1, 1.2, 1.3, 0.4], 1, date(2026, 8, 22), "current year barely started"),
        ([1.0, 1.1, 1.05, 1.2, 1.3], 2, date(2026, 8, 22), "a cut in the middle"),
        ([2.0, 1.9, 1.8, 1.7, 1.6], 3, date(2026, 8, 22), "declining payer"),
        ([1.0, 1.0, 1.0, 1.0, 1.0], 4, date(2026, 8, 22), "flat payer — no growth"),
        ([1.0], 4, date(2026, 8, 22), "single year of history"),
    ],
)
def test_engine_matches_oracle(totals, quarters_last, today, label):
    start = today.year - len(totals) + 1
    pays = _payments(start, totals, quarters_in_last_year=quarters_last)
    assert _engine_streak(pays, today) == oracle_streak(pays, today), label


def test_monthly_payer_is_bucketed_by_year_not_by_payment():
    """Monthly REIT-style payers (O, NNN) must not be read as 12 tiny years."""
    pays: List[Tuple[str, float]] = []
    for offset, total in enumerate([1.0, 1.2, 1.4, 1.6]):
        year = 2022 + offset
        for month in range(1, 13):
            pays.append((f"{year}-{month:02d}-10", total / 12.0))
    today = date(2026, 8, 22)
    assert _engine_streak(pays, today) == oracle_streak(pays, today) == 3


# --------------------------------------------------------------------------- #
#  Helper contract                                                            #
# --------------------------------------------------------------------------- #

class TestAnnualDividendTotals:
    def test_empty_input_is_survivable(self):
        assert annual_dividend_totals(pd.Series(dtype=float)).empty
        assert annual_dividend_totals(None).empty

    def test_returns_most_recent_first(self):
        pays = _payments(2021, [1.0, 2.0, 3.0])
        out = annual_dividend_totals(_series(pays), today=date(2026, 8, 22))
        assert list(out.index.year) == [2023, 2022, 2021]

    def test_drops_only_the_unfinished_year(self):
        pays = _payments(2023, [1.0, 2.0, 3.0, 4.0])  # 2023..2026
        out = annual_dividend_totals(_series(pays), today=date(2026, 8, 22))
        assert list(out.index.year) == [2025, 2024, 2023]

    def test_a_year_that_just_closed_is_kept(self):
        pays = _payments(2024, [1.0, 2.0])  # 2024, 2025
        out = annual_dividend_totals(_series(pays), today=date(2026, 1, 1))
        assert 2025 in list(out.index.year)

    def test_string_index_is_coerced(self):
        raw = pd.Series({"2023-03-15": 1.0, "2024-03-15": 2.0}, dtype=float)
        out = annual_dividend_totals(raw, today=date(2026, 8, 22))
        assert list(out.index.year) == [2024, 2023]
