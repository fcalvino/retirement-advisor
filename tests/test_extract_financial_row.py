"""``analysis.utils.extract_financial_row`` — the three flavours S26 consolidated.

Each of ``_extract_annual_series`` (fundamental), ``_row_series`` (moat) and
``_extract`` (scoring) is now a one-line wrapper over this helper. These tests
pin the four behavioural axes so a future edit cannot silently re-merge them
into one behaviour.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.utils import extract_financial_row

COLS = [pd.Timestamp("2022-12-31"), pd.Timestamp("2024-12-31"), pd.Timestamp("2023-12-31")]


@pytest.fixture
def stmt() -> pd.DataFrame:
    return pd.DataFrame(
        {
            COLS[0]: [7.0, np.nan, 70.0],
            COLS[1]: [10.0, np.nan, 100.0],
            COLS[2]: [8.0, np.nan, 80.0],
        },
        index=["Total Revenue", "All NaN Row", "Net Income"],
    )


def test_fundamental_flavour_newest_first_no_cast(stmt):
    s = extract_financial_row(stmt, ["Total Revenue"], ascending=False, as_float=False)
    assert list(s.index) == [pd.Timestamp("2024-12-31"), pd.Timestamp("2023-12-31"), pd.Timestamp("2022-12-31")]
    assert list(s) == [10.0, 8.0, 7.0]


def test_moat_flavour_oldest_first_cast_float(stmt):
    s = extract_financial_row(stmt, ["Total Revenue"], ascending=True, as_float=True)
    assert list(s.index) == sorted(s.index)
    assert s.dtype == float


def test_scoring_flavour_skips_all_nan_match_and_falls_through(stmt):
    # "All NaN Row" matches by name but is empty after dropna → keep scanning.
    s = extract_financial_row(
        stmt, ["All NaN Row", "Net Income"],
        ascending=False, as_float=True, require_nonempty=True, missing=None,
    )
    assert s is not None
    assert list(s) == [100.0, 80.0, 70.0]


def test_non_scoring_flavour_returns_empty_match_without_falling_through(stmt):
    # Without require_nonempty the all-NaN match wins and later candidates are ignored.
    s = extract_financial_row(stmt, ["All NaN Row", "Net Income"], ascending=False, as_float=False)
    assert s.empty


@pytest.mark.parametrize("df", [None, pd.DataFrame()])
def test_missing_sentinel(df):
    assert extract_financial_row(df, ["x"]).empty
    assert extract_financial_row(df, ["x"], missing=None) is None


def test_no_candidate_matches(stmt):
    assert extract_financial_row(stmt, ["Nope"]).empty
    assert extract_financial_row(stmt, ["Nope"], missing=None) is None


def test_missing_sentinel_returns_fresh_series_each_call():
    a = extract_financial_row(None, ["x"])
    a["injected"] = 1.0
    b = extract_financial_row(None, ["x"])
    assert b.empty
