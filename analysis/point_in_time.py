"""
Point-in-time reconstruction of SEC fundamentals.

First slice of Idea 2 ("Backtesting point-in-time", ``docs/DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md``
§2/§4). Pure functions only — no network, no DB, no Streamlit, nothing persisted.
Given a company's raw ``companyfacts`` payload (already fetched by
:class:`data.data_sources.SecEdgarSource`) and a cutoff date, reconstructs the
annual fundamentals *as they were actually known* on that date.

SEC's ``companyfacts`` endpoint already returns a company's entire historical
annual series per tag in one payload — the "frames" API the original idea
mentions is not needed, filtering what's already fetched is enough.
``SecEdgarSource._latest_annual`` always wants the freshest value available
*now* (it's built for reconciliation against yfinance's current numbers) and
never reads ``filed`` at all — confirmed by its existing test fixtures
(``tests/test_data_reconciliation.py``), which don't carry that field either.
Point-in-time asks a different question — "what was believed true on date X" —
which needs two keys, not one: the fiscal period (``end``, prefer the latest
one that had already been filed) and, within a restated period, filing
recency (``filed``, prefer the latest one still <= cutoff) so a restatement
filed after the cutoff — a 10-K/A or a later 10-K re-reporting a prior year
under ASC 606, say — can never leak into a reconstruction of "as of" that date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from data.data_sources import SecEdgarSource, _f


@dataclass
class PointInTimeFact:
    value: float
    period_end: str   # fiscal period this value covers (ISO date)
    filed: str         # when this value was actually filed with the SEC (ISO date)


def annual_fact_as_of(concept_facts: dict, cutoff: date) -> Optional[PointInTimeFact]:
    """The annual fact for *one* XBRL tag as it was known on ``cutoff``.

    Reuses :meth:`SecEdgarSource._annual_rows` for the annual-duration filter
    (10-K, 330-400 day span) — the same guard that keeps a 10-Q half-year from
    posing as an annual figure (the KLAC case). A row is visible only if it had
    already been filed by ``cutoff``; among rows covering the same fiscal
    period (a restatement), the most recently filed one still <= cutoff wins —
    that is the figure a reader would have actually seen on that date.
    """
    cutoff_iso = cutoff.isoformat()
    rows = [
        r for r in SecEdgarSource._annual_rows(concept_facts)
        if r.get("filed") and r["filed"] <= cutoff_iso
    ]
    best: Optional[dict] = None
    for row in rows:
        key = (row["end"], row["filed"])
        if best is None or key > (best["end"], best["filed"]):
            best = row
    if best is None:
        return None
    value = _f(best.get("val"))
    if value is None:
        return None
    return PointInTimeFact(value=value, period_end=best["end"], filed=best["filed"])


def latest_annual_as_of(
    us_gaap: dict, tags: List[str], cutoff: date
) -> Optional[PointInTimeFact]:
    """Scans every candidate *tag* the way :meth:`SecEdgarSource._latest_annual`
    does for "now", but anchored to ``cutoff``. Ties across tags for the same
    ``(period_end, filed)`` go to the earlier tag in *tags*, mirroring the
    existing reconciliation convention (a company's current tag is listed
    first; a retired one is only a fallback).
    """
    best: Optional[PointInTimeFact] = None
    for tag in tags:
        facts = (us_gaap or {}).get(tag)
        if not facts:
            continue
        candidate = annual_fact_as_of(facts, cutoff)
        if candidate is None:
            continue
        key = (candidate.period_end, candidate.filed)
        if best is None or key > (best.period_end, best.filed):
            best = candidate
    return best
