"""
Oracle tests for ``analysis/point_in_time_piotroski.py`` — offline fixtures,
no network, no persistence.

The central oracle (``test_matches_a_hand_built_yfinance_style_statement``)
does not re-derive Piotroski's math: it feeds the *same* two years of numbers
through two paths — (a) point-in-time reconstruction from synthetic XBRL
facts, and (b) a hand-built yfinance-shaped DataFrame, the way
``EnhancedScoring._piotroski_score`` is fed in production — and asserts both
produce a byte-identical ``PiotroskiDetail``. That is the property this module
exists for: reconstructing inputs, never re-implementing the scoring.
"""

from datetime import date

import pandas as pd

from analysis.point_in_time_piotroski import piotroski_as_of, piotroski_statements_as_of
from analysis.scoring import EnhancedScoring


def _fact(val, end, filed):
    return {"val": val, "start": f"{int(end[:4]) - 1}-{end[5:]}", "end": end, "filed": filed, "form": "10-K", "fp": "FY"}


def _concept(rows):
    return {"units": {"USD": rows}}


def _two_year_us_gaap():
    """FY2020 (improving on every axis vs FY2019) filed 2021-02-01; FY2019
    filed 2020-02-01. Cutoff dates in the tests below sit relative to those
    two filing dates.
    """
    return {
        "Revenues": _concept([
            _fact(900.0, "2019-12-31", "2020-02-01"),
            _fact(1000.0, "2020-12-31", "2021-02-01"),
        ]),
        "NetIncomeLoss": _concept([
            _fact(80.0, "2019-12-31", "2020-02-01"),
            _fact(100.0, "2020-12-31", "2021-02-01"),
        ]),
        "GrossProfit": _concept([
            _fact(300.0, "2019-12-31", "2020-02-01"),   # margin 33.3%
            _fact(400.0, "2020-12-31", "2021-02-01"),   # margin 40.0% — improved
        ]),
        "Assets": _concept([
            _fact(1000.0, "2019-12-31", "2020-02-01"),
            _fact(1100.0, "2020-12-31", "2021-02-01"),
        ]),
        "LongTermDebtNoncurrent": _concept([
            _fact(300.0, "2019-12-31", "2020-02-01"),   # 30% of assets
            _fact(220.0, "2020-12-31", "2021-02-01"),   # 20% of assets — improved
        ]),
        "AssetsCurrent": _concept([
            _fact(400.0, "2019-12-31", "2020-02-01"),
            _fact(500.0, "2020-12-31", "2021-02-01"),
        ]),
        "LiabilitiesCurrent": _concept([
            _fact(200.0, "2019-12-31", "2020-02-01"),   # current ratio 2.0
            _fact(200.0, "2020-12-31", "2021-02-01"),   # current ratio 2.5 — improved
        ]),
        "CommonStockSharesOutstanding": _concept([
            _fact(100.0, "2019-12-31", "2020-02-01"),
            _fact(100.0, "2020-12-31", "2021-02-01"),   # no dilution
        ]),
        "NetCashProvidedByUsedInOperatingActivities": _concept([
            _fact(90.0, "2019-12-31", "2020-02-01"),
            _fact(120.0, "2020-12-31", "2021-02-01"),   # > net income (100) — accruals pass
        ]),
    }


def test_matches_a_hand_built_yfinance_style_statement():
    """Same numbers, two construction paths, must score identically."""
    us_gaap = _two_year_us_gaap()
    got = piotroski_as_of(us_gaap, cutoff=date(2021, 6, 1))

    hand_income = pd.DataFrame({
        pd.Timestamp("2020-12-31"): {"Total Revenue": 1000.0, "Net Income": 100.0, "Gross Profit": 400.0},
        pd.Timestamp("2019-12-31"): {"Total Revenue": 900.0, "Net Income": 80.0, "Gross Profit": 300.0},
    })
    hand_balance = pd.DataFrame({
        pd.Timestamp("2020-12-31"): {
            "Total Assets": 1100.0, "Long Term Debt": 220.0,
            "Current Assets": 500.0, "Current Liabilities": 200.0,
            "Ordinary Shares Number": 100.0,
        },
        pd.Timestamp("2019-12-31"): {
            "Total Assets": 1000.0, "Long Term Debt": 300.0,
            "Current Assets": 400.0, "Current Liabilities": 200.0,
            "Ordinary Shares Number": 100.0,
        },
    })
    hand_cashflow = pd.DataFrame({
        pd.Timestamp("2020-12-31"): {"Operating Cash Flow": 120.0},
        pd.Timestamp("2019-12-31"): {"Operating Cash Flow": 90.0},
    })
    expected = EnhancedScoring()._piotroski_score(
        info={}, income_stmt=hand_income, balance_sheet=hand_balance, cashflow=hand_cashflow
    )

    assert got == expected
    # Every check improves in this fixture by construction.
    assert got.score == 9


def test_cutoff_before_the_second_year_was_filed_only_sees_one_year():
    """Between the two filing dates: YoY checks (F3/F4/F5/F7/F8) cannot
    resolve on one year of data and must come back False, not crash or guess.
    """
    us_gaap = _two_year_us_gaap()
    got = piotroski_as_of(us_gaap, cutoff=date(2020, 6, 1))

    assert got.f1_roa_positive is True     # FY2019 alone: NI>0, assets>0
    assert got.f3_roa_improving is False
    assert got.f4_leverage_decreasing is False
    assert got.f5_liquidity_improving is False
    assert got.f6_no_dilution is False     # needs 2 years of shares
    assert got.f7_gross_margin_improving is False
    assert got.f8_asset_turnover_improving is False


def test_missing_concept_drops_only_its_own_checks():
    """No GrossProfit tag at all: F7 cannot resolve, everything else is
    unaffected — a missing input degrades one check, not the whole score.
    """
    us_gaap = _two_year_us_gaap()
    del us_gaap["GrossProfit"]
    got = piotroski_as_of(us_gaap, cutoff=date(2021, 6, 1))

    assert got.f7_gross_margin_improving is False
    assert got.f1_roa_positive is True
    assert got.f3_roa_improving is True
    assert got.f4_leverage_decreasing is True


def test_a_gap_year_in_one_concept_does_not_misalign_against_another():
    """The regression this module exists to prevent: LongTermDebtNoncurrent
    has no fact for FY2019 (routine — some filers omit the tag when reporting
    would otherwise duplicate a zero), but FY2018 is present. A per-concept
    "give me this row's own N most recent dates" walk would silently pair
    FY2020 debt against FY2019 assets in position 0, and FY2018 debt against
    FY2019 assets in position 1 — two different fiscal years compared as if
    adjacent, *fabricating* a "leverage decreased" signal from years that were
    never actually compared. Anchoring every row to the same period-end axis
    must instead leave FY2019 debt genuinely absent, so F4 abstains (False)
    rather than answering from misaligned data.
    """
    us_gaap = _two_year_us_gaap()
    # FY2018 debt=300 (present, but three years back), FY2019 debt absent
    # entirely (the gap), FY2020 debt=220 (present) — total_assets keeps its
    # normal FY2020/FY2019 values from _two_year_us_gaap().
    us_gaap["LongTermDebtNoncurrent"] = _concept([
        _fact(300.0, "2018-12-31", "2019-02-01"),
        _fact(220.0, "2020-12-31", "2021-02-01"),
    ])

    got = piotroski_as_of(us_gaap, cutoff=date(2021, 6, 1))

    assert got.f4_leverage_decreasing is False


def test_statements_as_of_returns_the_shape_piotroski_expects():
    us_gaap = _two_year_us_gaap()
    income_stmt, balance_sheet, cashflow = piotroski_statements_as_of(us_gaap, cutoff=date(2021, 6, 1))

    assert "Net Income" in income_stmt.index
    assert "Total Assets" in balance_sheet.index
    assert "Operating Cash Flow" in cashflow.index
    assert income_stmt.shape[1] == 2   # two fiscal years visible


def test_empty_facts_return_an_all_false_detail_not_a_crash():
    got = piotroski_as_of({}, cutoff=date(2021, 6, 1))
    assert got.score == 0


def test_missing_ocf_never_passes_accruals_quality_for_a_loss_making_company():
    """``EnhancedScoring._piotroski_score``'s F9 fallback (analysis/scoring.py)
    computes ``info.get("operatingCashflow", 0) > net_income`` when the OCF row
    is absent — safe with a live yfinance ``info`` dict, but with the
    ``info={}`` this module always passes, a reconstructed net *loss* would
    make ``0 > negative_number`` evaluate True: "accrual quality passed" from
    cash flow data that was never actually available, for exactly the
    loss-making companies this check exists to catch.
    """
    us_gaap = _two_year_us_gaap()
    del us_gaap["NetCashProvidedByUsedInOperatingActivities"]   # OCF tag entirely absent
    us_gaap["NetIncomeLoss"] = _concept([
        _fact(-80.0, "2019-12-31", "2020-02-01"),
        _fact(-50.0, "2020-12-31", "2021-02-01"),   # a real net loss, improving YoY
    ])

    got = piotroski_as_of(us_gaap, cutoff=date(2021, 6, 1))

    assert got.f9_accruals_quality is False


def test_unrelated_instant_fact_does_not_pollute_the_period_axis():
    """A companyfacts payload carries every us-gaap tag a company has ever
    reported, most of them irrelevant to Piotroski. An unrelated tag with an
    instant fact (no ``start``, so the duration guard in
    ``SecEdgarSource._annual_rows`` never applies to it) dated after the real
    fiscal year-end and filed under a 10-K must not be allowed to outrank the
    real year-end on the shared period axis — it belongs to a concept nobody
    asked for.
    """
    us_gaap = _two_year_us_gaap()
    us_gaap["UnrelatedDisclosureAmount"] = _concept([
        {"val": 42.0, "end": "2021-03-15", "filed": "2021-03-20", "form": "10-K", "fp": "FY"},
    ])

    got = piotroski_as_of(us_gaap, cutoff=date(2021, 6, 1))

    # Unaffected: still two full, correctly-anchored fiscal years, exactly as
    # in the baseline fixture.
    assert got.score == 9
