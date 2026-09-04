"""
Oracle tests for ``analysis/point_in_time.py`` — offline fixtures, no network.

Fixture values/dates are synthetic (chosen to demonstrate the property under
test), not literal figures pulled from EDGAR — same convention as the existing
``SecEdgarSource`` fixtures in ``tests/test_data_reconciliation.py`` (the KLAC
and MA cases use hand-built numbers, not live payloads). Verifying the real
``companyfacts`` field shape (``filed`` included on every annual row) against a
live payload is a followup, not assumed here.

Each test is an oracle against the *definition* of look-ahead bias — "a fact is
visible on date X only if it was filed by date X" — not a copy of the
implementation under test.
"""

from datetime import date

from analysis.point_in_time import annual_fact_as_of, latest_annual_as_of


def _row(val, start, end, filed, form="10-K", fp="FY"):
    return {"val": val, "start": start, "end": end, "filed": filed, "form": form, "fp": fp}


def _usd(rows):
    return {"units": {"USD": rows}}


def test_cutoff_before_the_fiscal_year_was_filed_falls_back_to_the_prior_year():
    """The core look-ahead-bias case: FY2020 closed but was not filed yet."""
    facts = _usd([
        _row(100.0, "2019-01-01", "2019-12-31", filed="2020-02-15"),
        _row(120.0, "2020-01-01", "2020-12-31", filed="2021-02-15"),
    ])
    # Between fiscal year-end and the actual filing date: FY2020 existed but
    # nobody could have read it yet.
    got = annual_fact_as_of(facts, cutoff=date(2021, 1, 15))
    assert got is not None
    assert got.period_end == "2019-12-31"
    assert got.value == 100.0


def test_cutoff_after_filing_sees_the_new_year():
    facts = _usd([
        _row(100.0, "2019-01-01", "2019-12-31", filed="2020-02-15"),
        _row(120.0, "2020-01-01", "2020-12-31", filed="2021-02-15"),
    ])
    got = annual_fact_as_of(facts, cutoff=date(2021, 3, 1))
    assert got is not None
    assert got.period_end == "2020-12-31"
    assert got.value == 120.0


def test_cutoff_before_any_filing_returns_none():
    facts = _usd([_row(100.0, "2019-01-01", "2019-12-31", filed="2020-02-15")])
    assert annual_fact_as_of(facts, cutoff=date(2019, 6, 1)) is None


def test_restatement_filed_after_cutoff_does_not_leak_in():
    """Same fiscal period, two rows: the original filing and a later
    restatement (e.g. a 10-K/A, or a subsequent 10-K re-reporting the prior
    year under a new revenue standard). The restatement must stay invisible
    until its own ``filed`` date, even though it describes an *older* period
    than one already visible.
    """
    facts = _usd([
        _row(100.0, "2019-01-01", "2019-12-31", filed="2020-02-15"),   # original
        _row(90.0, "2019-01-01", "2019-12-31", filed="2021-03-01"),    # restated, filed later
    ])
    # Before the restatement was filed: only the original figure is visible.
    before = annual_fact_as_of(facts, cutoff=date(2020, 6, 1))
    assert before is not None
    assert before.value == 100.0
    assert before.filed == "2020-02-15"

    # After the restatement was filed: the restated figure is what a reader
    # would see, even though the fiscal period itself did not change.
    after = annual_fact_as_of(facts, cutoff=date(2021, 4, 1))
    assert after is not None
    assert after.value == 90.0
    assert after.filed == "2021-03-01"


def test_naive_max_end_tie_break_would_get_this_wrong():
    """Guards the exact defect this module exists to avoid: picking by ``end``
    alone (what ``SecEdgarSource._latest_annual`` does for "now") is not
    equivalent to picking by ``(end, filed)`` for a point-in-time cutoff. Both
    rows here share the same ``end`` and are both visible by the cutoff, so
    only a ``filed`` tie-break can tell them apart; falling back to "whichever
    row appears first for this end" would silently reintroduce the ordering
    bug this module replaces.
    """
    facts = _usd([
        _row(90.0, "2019-01-01", "2019-12-31", filed="2020-02-15"),
        _row(95.0, "2019-01-01", "2019-12-31", filed="2020-08-01"),
    ])
    got = annual_fact_as_of(facts, cutoff=date(2025, 1, 1))
    assert got is not None
    assert got.value == 95.0
    assert got.filed == "2020-08-01"


def test_rejects_quarterly_rows_inside_a_10k_same_as_reconciliation():
    """The KLAC guard (``SecEdgarSource._annual_rows``) applies here too — a
    10-Q half-year duration must not pass as an annual fact even if it is
    tagged ``form=10-K``.
    """
    facts = {"units": {"USD": [
        {"val": 1.45e9, "start": "2010-07-01", "end": "2010-12-31",
         "filed": "2011-01-15", "form": "10-Q", "fp": "Q2"},
    ]}}
    assert annual_fact_as_of(facts, cutoff=date(2020, 1, 1)) is None


def test_rows_without_filed_are_never_visible():
    """A row that (for whatever reason) carries no ``filed`` date cannot be
    reasoned about as "known by cutoff X" — dropped rather than guessed, same
    principle ``_annual_rows`` already applies to undated facts.
    """
    facts = _usd([{"val": 100.0, "start": "2019-01-01", "end": "2019-12-31", "form": "10-K"}])
    assert annual_fact_as_of(facts, cutoff=date(2025, 1, 1)) is None


def test_latest_annual_as_of_scans_every_tag():
    """Mirrors ``SecEdgarSource._latest_annual``'s multi-tag scan (the MA
    case: a company retires a tag and a later one carries the current figure)
    — but anchored to a cutoff instead of "now".
    """
    us_gaap = {
        "NetIncomeLoss": _usd([_row(10.0, "2019-01-01", "2019-12-31", filed="2020-02-01")]),
        "ProfitLoss": _usd([_row(20.0, "2024-01-01", "2024-12-31", filed="2025-02-01")]),
    }
    got = latest_annual_as_of(us_gaap, ["NetIncomeLoss", "ProfitLoss"], cutoff=date(2025, 6, 1))
    assert got is not None
    assert got.value == 20.0

    # Before ProfitLoss was filed, only the older tag's figure is visible.
    earlier = latest_annual_as_of(us_gaap, ["NetIncomeLoss", "ProfitLoss"], cutoff=date(2021, 1, 1))
    assert earlier is not None
    assert earlier.value == 10.0


def test_latest_annual_as_of_returns_none_when_no_tag_has_data_yet():
    us_gaap = {"NetIncomeLoss": _usd([_row(10.0, "2019-01-01", "2019-12-31", filed="2020-02-01")])}
    assert latest_annual_as_of(us_gaap, ["NetIncomeLoss"], cutoff=date(2019, 1, 1)) is None
