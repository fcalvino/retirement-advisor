"""Each Piotroski check compares the same fiscal years (audit 2026-10-26).

``_piotroski_score`` read each statement row with its own ``dropna()`` and then
indexed ``iloc[0]`` / ``iloc[1]``. When a row is blank in the newest column, its
``iloc[0]`` is *last* year's figure while another row's ``iloc[0]`` is *this*
year's — so a ratio divided two periods, and a "year over year" comparison
compared a year against a different pair of years. Nothing marked the result:

    Total Assets        2025: 2000   2024: 1000   2023: 1000
    Long Term Debt      2025:  --    2024:  300   2023:  250      (leverage is RISING)

    old  F4: 300 / 2000 = 0.15  <  250 / 1000 = 0.25   -> "leverage fell"  (point awarded)
    true F4: 300 / 1000 = 0.30  <  250 / 1000 = 0.25   -> False

It is the defect U3-9 / U3-10 fixed for the ratios of ``fundamental.py`` with
``aligned_latest`` (anchor on the newest period where every row reported, do not
discard); the Piotroski never got it.

**Criterion, stated because the classic F-Score is one fiscal year:** each check
anchors on its *own* rows — the newest pair of consecutive fiscal years on which
every row *that check reads* reported both. Two checks can therefore anchor on
different years when a blank column hits only one of them; each is true on its
own terms. A check with no such pair has no answer and loses the point, as it
always did (``_safe``).

The reference below is written from what each check *asks* — loops over the
statement's own columns and the raw cells — and shares nothing with
``aligned_window``.

No network, no Streamlit.
"""

from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

from analysis.scoring import EnhancedScoring
from config import PIOTROSKI

COLS = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]  # newest first, yfinance

INCOME = ["Net Income", "Total Revenue", "Gross Profit"]
BALANCE = ["Total Assets", "Long Term Debt", "Current Assets", "Current Liabilities",
           "Ordinary Shares Number"]
CASHFLOW = ["Operating Cash Flow"]


def _frame(rows: dict) -> pd.DataFrame:
    return pd.DataFrame({k: dict(zip(COLS, v)) for k, v in rows.items()}).T[COLS]


def _score(income, balance, cashflow):
    return EnhancedScoring()._piotroski_score({}, income, balance, cashflow)


# --------------------------------------------------------------------------- #
#  Reference: straight from what each check asks                               #
# --------------------------------------------------------------------------- #

def _cell(frame: pd.DataFrame, row: str, col: str):
    if row not in frame.index:
        return None
    v = frame.loc[row, col]
    return None if pd.isna(v) else float(v)


def _years(spec, span):
    """First ``span`` consecutive columns where every (frame, row) in ``spec`` has a value."""
    for k in range(len(COLS) - span + 1):
        window = COLS[k:k + span]
        grid = [[_cell(f, r, c) for (f, r) in spec] for c in window]
        if all(v is not None for line in grid for v in line):
            return grid
    return None


def reference(income, balance, cashflow) -> dict:
    out = {}
    w = _years([(income, "Net Income"), (balance, "Total Assets")], 1)
    out["f1_roa_positive"] = bool(w and w[0][1] > 0 and w[0][0] / w[0][1] > 0)

    ocf_vals = [v for c in COLS if (v := _cell(cashflow, "Operating Cash Flow", c)) is not None]
    out["f2_ocf_positive"] = bool(ocf_vals and ocf_vals[0] > 0)

    w = _years([(income, "Net Income"), (balance, "Total Assets")], 2)
    out["f3_roa_improving"] = bool(
        w and w[0][1] > 0 and w[1][1] > 0 and w[0][0] / w[0][1] > w[1][0] / w[1][1]
    )

    w = _years([(balance, "Long Term Debt"), (balance, "Total Assets")], 2)
    out["f4_leverage_decreasing"] = bool(
        w and w[0][1] > 0 and w[1][1] > 0
        and (w[0][0] / w[0][1] < w[1][0] / w[1][1] or (w[0][0] == 0 and w[1][0] == 0))
    )

    w = _years([(balance, "Current Assets"), (balance, "Current Liabilities")], 2)
    out["f5_liquidity_improving"] = bool(
        w and w[0][1] > 0 and w[1][1] > 0 and w[0][0] / w[0][1] > w[1][0] / w[1][1]
    )

    w = _years([(balance, "Ordinary Shares Number")], 2)
    cap = 1.0 + PIOTROSKI.max_dilution_pct / 100.0
    out["f6_no_dilution"] = bool(w and w[1][0] > 0 and w[0][0] <= w[1][0] * cap)

    w = _years([(income, "Gross Profit"), (income, "Total Revenue")], 2)
    out["f7_gross_margin_improving"] = bool(
        w and w[0][1] > 0 and w[1][1] > 0 and w[0][0] / w[0][1] > w[1][0] / w[1][1]
    )

    w = _years([(income, "Total Revenue"), (balance, "Total Assets")], 2)
    out["f8_asset_turnover_improving"] = bool(
        w and w[0][1] > 0 and w[1][1] > 0 and w[0][0] / w[0][1] > w[1][0] / w[1][1]
    )

    w = _years([(cashflow, "Operating Cash Flow"), (income, "Net Income")], 1)
    out["f9_accruals_quality"] = bool(w and w[0][0] > w[0][1])
    return out


def _flags(detail) -> dict:
    return {k: bool(getattr(detail, k)) for k in reference(
        _frame({"Net Income": [1] * 4}), _frame({"Total Assets": [1] * 4}),
        _frame({"Operating Cash Flow": [1] * 4})).keys()}


# --------------------------------------------------------------------------- #
#  The named case                                                              #
# --------------------------------------------------------------------------- #

class TestMixedYearsAreNotCompared:
    def test_leverage_rising_is_not_read_as_falling_when_the_newest_debt_is_blank(self):
        balance = _frame({
            "Total Assets": [2000.0, 1000.0, 1000.0, 900.0],
            "Long Term Debt": [np.nan, 300.0, 250.0, 200.0],
        })
        d = _score(_frame({"Net Income": [1.0] * 4}), balance, _frame({"Operating Cash Flow": [1.0] * 4}))
        assert d.f4_leverage_decreasing is False

    def test_a_blank_newest_column_in_one_row_does_not_shift_the_other(self):
        """F3: ROA 2024 vs 2023 on both rows, not net income 2024 over assets 2025."""
        income = _frame({"Net Income": [np.nan, 100.0, 150.0, 90.0]})
        balance = _frame({"Total Assets": [4000.0, 1000.0, 1000.0, 900.0]})
        d = _score(income, balance, _frame({"Operating Cash Flow": [1.0] * 4}))
        # true: 100/1000 = 0.10 > 150/1000 = 0.15 -> False.  Old: 100/4000 = 0.025 vs 150/1000 -> False too,
        # so also pin the opposite direction below.
        assert d.f3_roa_improving is False

    def test_roa_improvement_is_found_on_the_aligned_pair(self):
        income = _frame({"Net Income": [np.nan, 200.0, 150.0, 90.0]})
        balance = _frame({"Total Assets": [4000.0, 1000.0, 1000.0, 900.0]})
        d = _score(income, balance, _frame({"Operating Cash Flow": [1.0] * 4}))
        # true: 200/1000 = 0.20 > 150/1000 = 0.15 -> True.  Old: 200/4000 = 0.05 < 0.15 -> False.
        assert d.f3_roa_improving is True

    def test_a_gap_year_is_not_read_as_a_year_over_year(self):
        """Shares reported 2025 and 2023 only: that is two years apart, not one."""
        balance = _frame({"Ordinary Shares Number": [100.0, np.nan, 100.0, np.nan]})
        d = _score(_frame({"Net Income": [1.0] * 4}), balance, _frame({"Operating Cash Flow": [1.0] * 4}))
        assert d.f6_no_dilution is False

    def test_accruals_compare_the_same_year(self):
        """F9: cash flow 2025 against net income 2024 is not an accrual comparison."""
        income = _frame({"Net Income": [np.nan, 500.0, 400.0, 300.0]})
        cashflow = _frame({"Operating Cash Flow": [450.0, 400.0, 350.0, 300.0]})
        d = _score(income, _frame({"Total Assets": [1.0] * 4}), cashflow)
        # true (2024): 400 > 500 -> False.  Old: ocf 450 > ni 500 -> False; flip the direction:
        assert d.f9_accruals_quality is False
        cashflow = _frame({"Operating Cash Flow": [600.0, 450.0, 350.0, 300.0]})
        d = _score(income, _frame({"Total Assets": [1.0] * 4}), cashflow)
        # true (2024): 450 > 500 -> False.  Old: 600 > 500 -> True.
        assert d.f9_accruals_quality is False


# --------------------------------------------------------------------------- #
#  Sweep against the reference                                                 #
# --------------------------------------------------------------------------- #

def _random_statements(rng: random.Random):
    def row(kind: str):
        r = rng.random()
        if r < 0.05:
            return None                                   # the row is not in the statement at all
        if r < 0.08:
            return [np.nan] * len(COLS)                   # the row is there, blank in every year
        vals = []
        for _ in COLS:
            if rng.random() < 0.28:
                vals.append(np.nan)
            elif kind == "signed":
                vals.append(rng.choice([-1, 1]) * rng.uniform(1, 500))
            elif kind == "debt":
                vals.append(rng.choice([0.0, rng.uniform(1, 400)]))
            elif kind == "pos" and rng.random() < 0.06:
                vals.append(rng.choice([0.0, -rng.uniform(1, 50)]))   # a zero or negative denominator
            else:
                vals.append(rng.uniform(1, 1000))
        return vals

    def build(spec):
        rows = {name: v for name, kind in spec.items() if (v := row(kind)) is not None}
        return _frame(rows) if rows else pd.DataFrame()

    income = build({"Net Income": "signed", "Total Revenue": "pos", "Gross Profit": "pos"})
    balance = build({"Total Assets": "pos", "Long Term Debt": "debt", "Current Assets": "pos",
                     "Current Liabilities": "pos", "Ordinary Shares Number": "pos"})
    cashflow = build({"Operating Cash Flow": "signed"})
    return income, balance, cashflow


@pytest.mark.parametrize("seed", range(40))
def test_every_check_matches_the_reference_on_random_statements(seed):
    rng = random.Random(20261026 + seed)
    for _ in range(25):
        income, balance, cashflow = _random_statements(rng)
        got = _flags(_score(income, balance, cashflow))
        want = reference(
            income if not income.empty else _frame({"Net Income": [np.nan] * 4}),
            balance if not balance.empty else _frame({"Total Assets": [np.nan] * 4}),
            cashflow if not cashflow.empty else _frame({"Operating Cash Flow": [np.nan] * 4}),
        )
        assert got == want, (seed, got, want)


def test_a_fully_reported_company_scores_exactly_as_before():
    income = _frame({"Net Income": [120.0, 100.0, 90.0, 80.0], "Total Revenue": [1100.0, 1000.0, 900.0, 800.0],
                     "Gross Profit": [440.0, 380.0, 330.0, 300.0]})
    balance = _frame({"Total Assets": [1500.0, 1400.0, 1300.0, 1200.0],
                      "Long Term Debt": [200.0, 250.0, 300.0, 300.0],
                      "Current Assets": [600.0, 550.0, 500.0, 480.0],
                      "Current Liabilities": [300.0, 300.0, 290.0, 280.0],
                      "Ordinary Shares Number": [100.0, 100.0, 101.0, 102.0]})
    cashflow = _frame({"Operating Cash Flow": [150.0, 120.0, 100.0, 90.0]})
    d = _score(income, balance, cashflow)
    assert d.score == 9
    assert _flags(d) == reference(income, balance, cashflow)


# --------------------------------------------------------------------------- #
#  Named edges the sweep does not guarantee                                    #
# --------------------------------------------------------------------------- #

class TestEdges:
    def test_statements_closing_a_day_apart_share_no_period(self):
        """Periods match by exact date: 12-30 against 12-31 is no shared year (by design)."""
        income = _frame({"Net Income": [100.0, 90.0, 80.0, 70.0], "Total Revenue": [1.0] * 4})
        balance = _frame({"Total Assets": [1000.0, 1000.0, 1000.0, 1000.0]})
        balance.columns = [c.replace("12-31", "12-30") for c in balance.columns]
        d = _score(income, balance, _frame({"Operating Cash Flow": [1.0] * 4}))
        assert d.f1_roa_positive is False
        assert d.f3_roa_improving is False
        assert d.f8_asset_turnover_improving is False

    def test_a_row_blank_in_every_year_is_absent(self):
        balance = _frame({"Total Assets": [np.nan] * 4})
        d = _score(_frame({"Net Income": [100.0] * 4, "Total Revenue": [10.0] * 4}),
                   balance, _frame({"Operating Cash Flow": [1.0] * 4}))
        assert (d.f1_roa_positive, d.f3_roa_improving, d.f8_asset_turnover_improving) == (False, False, False)

    @pytest.mark.parametrize("assets", [0.0, -5.0])
    def test_a_zero_or_negative_denominator_has_no_answer(self, assets):
        income = _frame({"Net Income": [100.0, 90.0, 80.0, 70.0], "Total Revenue": [10.0] * 4})
        balance = _frame({"Total Assets": [assets, 1000.0, 1000.0, 1000.0]})
        d = _score(income, balance, _frame({"Operating Cash Flow": [1.0] * 4}))
        assert d.f1_roa_positive is False    # newest shared year is 2025, whose assets are not > 0 ...
        # ... and it does NOT step back to 2024: only blank cells step back, not invalid ones.

    def test_alternative_row_names_are_read(self):
        """``Revenue`` / ``Share Issued`` / ``Long-Term Debt`` are the fallbacks the old code read."""
        income = _frame({"Net Income": [10.0] * 4, "Revenue": [1100.0, 1000.0, 900.0, 800.0],
                         "Gross Profit": [440.0, 380.0, 330.0, 300.0]})
        balance = _frame({"Total Assets": [1500.0, 1400.0, 1300.0, 1200.0],
                          "Long-Term Debt": [200.0, 250.0, 300.0, 300.0],
                          "Share Issued": [100.0, 100.0, 101.0, 102.0]})
        d = _score(income, balance, _frame({"Operating Cash Flow": [1.0] * 4}))
        assert d.f7_gross_margin_improving is True
        assert d.f4_leverage_decreasing is True
        assert d.f6_no_dilution is True

    def test_without_cashflow_f2_and_f9_use_the_info_fallback(self):
        income = _frame({"Net Income": [100.0] * 4})
        d = EnhancedScoring()._piotroski_score(
            {"operatingCashflow": 250.0}, income, _frame({"Total Assets": [1.0] * 4}), None)
        assert d.f2_ocf_positive is True
        assert d.f9_accruals_quality is True          # 250 > 100
        d = EnhancedScoring()._piotroski_score({}, income, _frame({"Total Assets": [1.0] * 4}), None)
        assert (d.f2_ocf_positive, d.f9_accruals_quality) == (False, False)
