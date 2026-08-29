"""A ratio is two numbers from the same year (backlog U3-9 / U3-10).

Each side of a ratio was fetched independently, with its own ``dropna()``, so
whichever fiscal year that row last reported is the year that side came from.
Nothing checked they matched, and nothing marked the result when they did not:

  * **U3-10** — interest coverage is ``EBIT / Interest Expense``, both from the
    income statement. Measured on the cache, **AAPL divides EBIT from 2025 by
    interest from 2023**, a two-year gap, and **LLY reports 38.0× where the
    aligned figure is 21.8×** — a 74 % overstatement presented as a fact. It
    feeds a 5-point health band.
  * **U3-9** — FFO is ``net income + D&A``, and those come from *different
    statements*, so the gap can be wider still: GOOGL pairs 2025 net income with
    2022 D&A. The FFO payout picks Cash Dividends Paid a third time. It feeds an
    8-point P/FFO band and the dividend-cut risk.

**The fix anchors rather than discards.** Returning ``None`` on a mismatch would
undo an earlier fix: the ``dropna()`` in ``_row`` exists precisely so AAPL and
LLY do not *lose* interest coverage to a blank latest column (its docstring says
so). Anchoring on the most recent period where **both** sides reported keeps the
metric and makes it true — AAPL becomes 29.1× from 2023, LLY 21.8× from 2024.
Only when no shared period exists is there no ratio.

Measured consequence today: **no score moves.** Both AAPL and LLY stay in the
"excelente" band either way, and 0 of the 13 cached REITs have a mixed-year FFO.
That is the honest size of it — the defect is a number being wrong on screen and
a trap waiting for any company whose ratio sits near a threshold, not a live
mis-scoring.

No network, no Streamlit.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.utils import aligned_latest

COLS = ["2025-12-31", "2024-12-31", "2023-12-31"]


def _frame(**rows) -> pd.DataFrame:
    """Statement in the yfinance shape: rows are metrics, columns descending dates."""
    return pd.DataFrame(rows, index=COLS).T


def oracle_latest_common_period(frames_rows) -> str | None:
    """Reference: the newest date on which every requested row reported a value.

    Written from what a ratio *is* — a comparison of quantities measured over the
    same span — rather than from the source.
    """
    dated = []
    for df, names in frames_rows:
        found = None
        for name in names:
            if name in df.index:
                found = {c for c, v in df.loc[name].items() if pd.notna(v)}
                break
        if not found:
            return None
        dated.append(found)
    common = set.intersection(*dated)
    return max(common) if common else None


# ================================================================== #
#  1. The primitive                                                    #
# ================================================================== #

class TestAlignedLatest:
    def test_picks_the_newest_year_both_sides_reported(self):
        income = _frame(EBIT=[1000.0, 900.0, 800.0],
                        **{"Interest Expense": [float("nan"), 45.0, 40.0]})
        values, period = aligned_latest([(income, ["EBIT"]),
                                         (income, ["Interest Expense"])])
        assert period == "2024-12-31"
        assert values == [900.0, 45.0]
        assert period == oracle_latest_common_period(
            [(income, ["EBIT"]), (income, ["Interest Expense"])]
        )

    def test_the_two_year_gap_that_motivated_this(self):
        """AAPL's shape: the newest interest figure is two years behind EBIT."""
        income = _frame(EBIT=[1000.0, 900.0, 800.0],
                        **{"Interest Expense": [float("nan"), float("nan"), 40.0]})
        values, period = aligned_latest([(income, ["EBIT"]),
                                         (income, ["Interest Expense"])])
        assert period == "2023-12-31"
        assert values == [800.0, 40.0]      # not 1000/40, which mixes years

    def test_no_shared_period_yields_nothing(self):
        income = _frame(EBIT=[1000.0, float("nan"), float("nan")],
                        **{"Interest Expense": [float("nan"), 45.0, 40.0]})
        values, period = aligned_latest([(income, ["EBIT"]),
                                         (income, ["Interest Expense"])])
        assert values is None and period is None

    def test_it_spans_separate_statements(self):
        """FFO's two halves live in different frames, which is why it drifts most."""
        income = _frame(**{"Net Income": [500.0, 450.0, 400.0]})
        cashflow = _frame(**{"Depreciation And Amortization":
                             [float("nan"), 120.0, 110.0]})
        values, period = aligned_latest([(income, ["Net Income"]),
                                         (cashflow, ["Depreciation And Amortization"])])
        assert period == "2024-12-31"
        assert values == [450.0, 120.0]

    def test_alternative_row_names_are_honoured(self):
        income = _frame(**{"Operating Income": [1000.0, 900.0, 800.0]})
        values, period = aligned_latest([(income, ["EBIT", "Operating Income"])])
        assert values == [1000.0] and period == "2025-12-31"

    def test_a_missing_row_is_not_a_shared_period(self):
        income = _frame(EBIT=[1000.0, 900.0, 800.0])
        values, period = aligned_latest([(income, ["EBIT"]),
                                         (income, ["Interest Expense"])])
        assert values is None and period is None

    def test_an_empty_frame_yields_nothing(self):
        assert aligned_latest([(pd.DataFrame(), ["EBIT"])]) == (None, None)


# ================================================================== #
#  2. The ratios that were mixing years                                #
# ================================================================== #

class TestInterestCoverageIsOneYear:
    def _coverage(self, income: pd.DataFrame) -> float | None:
        from analysis.fundamental import FundamentalAnalyzer, FundamentalResult

        result = FundamentalResult(symbol="TEST")
        FundamentalAnalyzer()._score_financial_health(
            {"country": "United States"}, pd.DataFrame(), income, result
        )
        return result.interest_coverage

    def test_the_ratio_comes_from_a_single_year(self):
        """LLY's shape: aligned is 20×, mixing years would read 25×."""
        income = _frame(EBIT=[1000.0, 800.0, 700.0],
                        **{"Interest Expense": [float("nan"), 40.0, 35.0]})
        assert self._coverage(income) == pytest.approx(800.0 / 40.0)

    def test_no_shared_year_means_no_coverage_rather_than_a_mixed_one(self):
        income = _frame(EBIT=[1000.0, float("nan"), float("nan")],
                        **{"Interest Expense": [float("nan"), 40.0, 35.0]})
        assert self._coverage(income) is None


class TestFfoIsOneYear:
    def test_net_income_and_da_come_from_the_same_period(self):
        from analysis.fundamental import compute_ffo

        income = _frame(**{"Net Income": [500.0, 450.0, 400.0]})
        cashflow = _frame(**{"Depreciation And Amortization":
                             [float("nan"), 120.0, 110.0]})
        assert compute_ffo(income, cashflow) == pytest.approx(450.0 + 120.0)

    def test_no_shared_period_means_no_ffo(self):
        from analysis.fundamental import compute_ffo

        income = _frame(**{"Net Income": [500.0, float("nan"), float("nan")]})
        cashflow = _frame(**{"Depreciation And Amortization":
                             [float("nan"), 120.0, 110.0]})
        assert compute_ffo(income, cashflow) is None

    def test_the_payout_uses_the_dividends_of_the_ffo_year(self):
        from analysis.fundamental import compute_ffo, compute_ffo_payout_pct

        income = _frame(**{"Net Income": [500.0, 450.0, 400.0]})
        cashflow = _frame(
            **{"Depreciation And Amortization": [float("nan"), 120.0, 110.0],
               "Cash Dividends Paid": [-300.0, -280.0, -260.0]},
        )
        ffo = compute_ffo(income, cashflow)          # anchored on 2024
        payout = compute_ffo_payout_pct(cashflow, ffo, income_stmt=income)
        assert payout == pytest.approx(280.0 / ffo * 100)    # 2024 dividends, not 2025


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
