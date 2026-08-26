"""Company-type classification — *how* a company must be measured.

Pure module: no network, no Streamlit, no dataframe. Companion to
``analysis/asset_class.py``, which answers the prior question — *is this thing a
company at all?* — and sends ETFs, bond funds and coins out of the equity scorer.
This one starts from a yes and asks what kind.

Why this exists
---------------
The scorer applies one set of 18 ratios to every company. Measured across the
149 cached equities (2026-08-22), that holds for most of them: outside financials,
every input the scorer needs is available in ~100 % of tickers.

Real Estate is the counterexample that motivated this module, and it is a subtle
one — it has **100 % availability and the worst score in the universe**: 60.0
average, zero BUY in 13 names, and 3.5 of 10 on dividends for the asset class that
pays the most dividends in the market. Nothing is missing. The wrong ratio is being
applied. A REIT distributes over 90 % of taxable income by law and pays it out of
funds from operations, not out of accounting profit, because depreciation — the
largest charge on its income statement — is not a cash outflow. Measured on the
same universe:

    12 of 13 REITs tripped the "unsustainable payout" warning
    O:   P/E 45.7 → P/FFO 16.5   ·   payout 236 % → 70 %
    EQR: P/E 28.5 → P/FFO 11.8   ·   payout 121 % → 63 %

Scope, deliberately
-------------------
Only ``REIT`` and ``OPERATING`` ship here, because REITs are the only consumer
today. Banks are the next one — 37 of their 100 points are structurally
unreachable, the whole Financial Health dimension included — but that needs a
scorer of its own (equity/assets, ROA, net interest margin) and calibration this
project cannot yet ground, since ``recommendation_outcome`` is still empty.

Note that ``_derive_debt_equity`` in ``analysis/fundamental.py`` deliberately does
**not** use this module to exclude banks. It keys off the absence of
``Current Assets`` on the balance sheet instead: that is the structural reason the
working-capital bands are meaningless there, and unlike an industry string it
cannot drift with how a feed spells things.
"""

from __future__ import annotations

from typing import Any, Optional

REIT = "reit"
OPERATING = "operating"

#: Every type this module can return.
ALL_TYPES = (REIT, OPERATING)

#: yfinance labels every REIT's sector this way; measured 13/13 on the universe.
_REIT_SECTOR = "real estate"

#: Secondary confirmation — the six REIT industries all start with this prefix.
_REIT_INDUSTRY_PREFIX = "reit"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def classify_company(
    symbol: str = "",
    *,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
) -> str:
    """Return ``REIT`` or ``OPERATING`` for one company.

    When *industry* is present it wins: CBRE/JLL/CWK are Real Estate *services*
    and must not inherit FFO scoring just because the sector string matches.
    ``sector == "Real Estate"`` is the path for feeds that omit industry —
    every REIT in the shipped universe carries that sector.
    """
    industry_n = _norm(industry)
    if industry_n:
        return REIT if industry_n.startswith(_REIT_INDUSTRY_PREFIX) else OPERATING
    if _norm(sector) == _REIT_SECTOR:
        return REIT
    return OPERATING


def classify_company_result(result: Any) -> str:
    """``classify_company`` for a ``FundamentalResult``-shaped object."""
    return classify_company(
        getattr(result, "symbol", ""),
        sector=getattr(result, "sector", ""),
        industry=getattr(result, "industry", ""),
    )


def is_reit(result: Any) -> bool:
    """True when funds-from-operations metrics replace the accounting ones."""
    return classify_company_result(result) == REIT
