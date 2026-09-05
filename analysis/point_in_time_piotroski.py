"""
Point-in-time Piotroski F-Score (PR 2/N, Idea 2 — "Backtesting point-in-time").

Second slice of ``docs/DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md`` §2/§4. Scoped to
Piotroski specifically, not the full 25-ratio fundamental score, because
Piotroski is the concrete thing ``config.PiotroskiConfig`` names as blocked
(U5-1b: "cannot ground it yet ... a one-year improvement signal cannot be
judged on 30 days") and its 9 checks (``analysis/scoring.py::_piotroski_score``)
read entirely from income statement / balance sheet / cashflow line items —
no market price, market cap, EPS or dividends, unlike the rest of the
fundamental scorer (``analysis/fundamental.py`` uses ``market_cap``/
``current_price`` for P/FFO, Graham margin of safety and FCF yield — a
materially harder point-in-time problem deferred to a later PR).

Still nothing persisted, no scorer output written anywhere, no
``analysis/track_record.py`` involved — this module only reconstructs the
inputs and can hand them to the *existing*, unmodified
``analysis.scoring.EnhancedScoring._piotroski_score`` so the scoring logic
itself never gets a backtesting-only copy to drift from the live one.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List

import pandas as pd

from analysis.point_in_time import annual_period_ends_as_of, latest_annual_at_period
from analysis.scoring import EnhancedScoring, PiotroskiDetail
from data.data_sources import SecEdgarSource

# The 3 concepts SecEdgarSource already resolves for "now" (reconciliation);
# reused as-is so the two call sites never disagree on which us-gaap tags mean
# "revenue" or "net income".
_REUSED_CONCEPTS = {
    "total_revenue": SecEdgarSource._CONCEPTS["total_revenue"],
    "net_income": SecEdgarSource._CONCEPTS["net_income"],
    "total_assets": SecEdgarSource._CONCEPTS["total_assets"],
}

# The 6 concepts Piotroski needs that reconciliation never fetches (it does
# not cross-check them against yfinance). Candidate tags are a best-effort
# reading of the common us-gaap taxonomy, generous with fallbacks the same way
# SecEdgarSource._CONCEPTS already is for net_income (NetIncomeLoss/ProfitLoss)
# — **not verified against a live companyfacts payload in this session**; a
# tag missing from a real filing surfaces as a dropped check (F-score checks
# already degrade to ``False`` on missing data, never guess), not a crash.
_NEW_CONCEPTS: Dict[str, List[str]] = {
    "gross_profit": ["GrossProfit"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "shares_outstanding": ["CommonStockSharesOutstanding", "CommonStockSharesIssued"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
}

_ALL_CONCEPTS: Dict[str, List[str]] = {**_REUSED_CONCEPTS, **_NEW_CONCEPTS}

# Row label each concept must carry so analysis.scoring.EnhancedScoring's
# candidate lists (``_piotroski_score``'s calls to ``self._extract``) find it —
# this is the one place that couples this module to those exact strings.
_ROW_LABELS = {
    "total_revenue": "Total Revenue",
    "net_income": "Net Income",
    "gross_profit": "Gross Profit",
    "total_assets": "Total Assets",
    "long_term_debt": "Long Term Debt",
    "current_assets": "Current Assets",
    "current_liabilities": "Current Liabilities",
    "shares_outstanding": "Ordinary Shares Number",
    "operating_cash_flow": "Operating Cash Flow",
}

_INCOME_STMT_CONCEPTS = ("total_revenue", "net_income", "gross_profit")
_BALANCE_SHEET_CONCEPTS = (
    "total_assets", "long_term_debt", "current_assets",
    "current_liabilities", "shares_outstanding",
)
_CASHFLOW_CONCEPTS = ("operating_cash_flow",)


def _build_statement(
    us_gaap: dict, concepts: tuple, cutoff: date, period_ends: List[str]
) -> pd.DataFrame:
    """One yfinance-shaped statement DataFrame (rows = line items, columns =
    fiscal period-end dates) built from point-in-time reconstructed facts.

    Every row is looked up against the *same* ``period_ends`` — computed once
    in :func:`piotroski_statements_as_of` from the whole payload, not derived
    independently per concept here. ``EnhancedScoring._piotroski_score``
    compares rows positionally (``ni.iloc[0] / total_assets.iloc[0]``, across
    *different* DataFrames too — income_stmt vs balance_sheet), so a shared
    axis is what keeps ``iloc[0]`` meaning the same fiscal year everywhere;
    letting each concept pick its own most-recent-available dates would let a
    company that omits one tag for a single year (routine — e.g. no reported
    long-term debt) silently misalign two same-length rows onto different
    years. A concept missing at a given period is simply absent from that
    column (dropped by ``extract_financial_row``'s own ``.dropna()``), never
    backfilled from a different period.
    """
    rows: Dict[str, Dict[str, float]] = {}
    for concept in concepts:
        tags = _ALL_CONCEPTS[concept]
        values = {}
        for period_end in period_ends:
            fact = latest_annual_at_period(us_gaap, tags, cutoff, period_end)
            if fact is not None:
                values[period_end] = fact.value
        if values:
            rows[_ROW_LABELS[concept]] = values
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame.from_dict(rows, orient="index")


def piotroski_statements_as_of(
    us_gaap: dict, cutoff: date, n_years: int = 2
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """``(income_stmt, balance_sheet, cashflow)`` as they were known on
    ``cutoff`` — the exact shape ``EnhancedScoring._piotroski_score`` expects
    from a live yfinance fetch, built here from reconstructed XBRL facts
    instead.
    """
    period_ends = annual_period_ends_as_of(us_gaap, list(_ALL_CONCEPTS.values()), cutoff, n_years)
    income_stmt = _build_statement(us_gaap, _INCOME_STMT_CONCEPTS, cutoff, period_ends)
    balance_sheet = _build_statement(us_gaap, _BALANCE_SHEET_CONCEPTS, cutoff, period_ends)
    cashflow = _build_statement(us_gaap, _CASHFLOW_CONCEPTS, cutoff, period_ends)
    return income_stmt, balance_sheet, cashflow


def piotroski_as_of(us_gaap: dict, cutoff: date) -> PiotroskiDetail:
    """The Piotroski F-Score as it would have scored on ``cutoff``, computed
    by the *same*, unmodified ``EnhancedScoring._piotroski_score`` production
    code runs against reconstructed statements — no scoring logic duplicated
    or forked for backtesting. ``info={}`` throughout: the only production
    fallback that reads ``info`` (F2/F9's ``operatingCashflow``) is a
    "now" snapshot field with no point-in-time equivalent, so it is left
    unknown rather than guessed, same principle the F-checks already apply to
    every other missing input.

    F9 needs an extra guard the F2 fallback does not: with ``info={}``,
    ``_piotroski_score``'s F9 else-branch computes ``0 > ni_val``. For F2 that
    is always ``False`` (safe), but for F9 a real, reconstructed net *loss*
    (``ni_val < 0``) makes ``0 > ni_val`` evaluate ``True`` — accrual quality
    "passed" from cash flow data that was never actually available, and wrong
    in exactly the loss-making population this check exists to flag. A live
    yfinance fetch rarely hits this branch with a real ``info`` dict backing
    it; reconstructed backtesting data always would when the OCF tag is
    simply missing. There is no "unknown" state to fall back to here, so the
    check is withheld outright rather than answered from a fabricated zero.
    """
    income_stmt, balance_sheet, cashflow = piotroski_statements_as_of(us_gaap, cutoff)
    detail = EnhancedScoring()._piotroski_score(
        info={}, income_stmt=income_stmt, balance_sheet=balance_sheet, cashflow=cashflow
    )
    ocf_row = cashflow.loc["Operating Cash Flow"].dropna() if "Operating Cash Flow" in cashflow.index else None
    if ocf_row is None or ocf_row.empty:
        detail.f9_accruals_quality = False
    return detail
