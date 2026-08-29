"""A ratio a bank cannot have is not a ratio a bank is missing (backlog U5-5).

``_QUALITY_KEY_FIELDS`` demanded ``debt_equity`` and ``current_ratio`` from every
company, with no awareness of what kind of company it was. A deposit-taking bank
has neither in the sense those bands mean: it has no working-capital structure,
and ``Total Debt / Equity`` omits deposits, which are its main funding.

**The backlog states this as "un banco no puede alcanzar calidad de datos
buena". Measured, that is not what happens** — 9 of the 11 cached banks *do*
reach "good", because ``partial_missing_fields`` is 3 and they are missing 2.
The real shape is worse in a quieter way:

  * every bank permanently spends **2 of its 3-field budget** on ratios it
    structurally cannot have, so **one genuine gap tips it to "partial"** where
    an industrial company would need three. BSAC is the live case: missing
    ``revenue_cagr_5y`` — a real gap — plus the two phantoms, and it is graded
    "partial" for it;
  * ``missing_fields`` is rendered to the user, so the app reports two metrics as
    missing for a bank when nothing is missing at all.

The marker is **structural, not a label**: the absence of ``Current Assets`` on
the balance sheet. That is the precedent ``_derive_debt_equity`` already set and
documented — "unlike an industry string it cannot drift with how a feed spells
things" — and on the cached universe it selects exactly the nine banks and nobody
else. Insurers have no current assets either but do report ``debtToEquity``, so
they are unaffected.

This does **not** build a bank scorer. That is X-01, explicitly out of scope, and
nothing here changes a single score: it changes which fields are counted as
absent.

No network, no Streamlit.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.fundamental import (
    _QUALITY_KEY_FIELDS,
    FundamentalResult,
    compute_data_quality,
    inapplicable_quality_fields,
)
from config import DATA_QUALITY

BANK_ONLY_FIELDS = ("debt_equity", "current_ratio")


def _balance(*, with_current_assets: bool) -> pd.DataFrame:
    rows = {"Stockholders Equity": [1000.0], "Total Debt": [500.0]}
    if with_current_assets:
        rows["Current Assets"] = [800.0]
    return pd.DataFrame(rows, index=["2025-12-31"]).T


def _result(**present) -> FundamentalResult:
    """A result with every quality field populated except the ones named absent."""
    r = FundamentalResult(symbol="TEST")
    for f in _QUALITY_KEY_FIELDS:
        setattr(r, f, present.get(f, 1.0))
    for f, v in present.items():
        setattr(r, f, v)
    return r


class TestTheMarkerIsStructural:
    def test_a_balance_sheet_without_current_assets_marks_the_two_ratios(self):
        assert inapplicable_quality_fields(_balance(with_current_assets=False)) == BANK_ONLY_FIELDS

    def test_an_ordinary_balance_sheet_marks_nothing(self):
        assert inapplicable_quality_fields(_balance(with_current_assets=True)) == ()

    def test_an_absent_balance_sheet_marks_nothing(self):
        """Unknown is not the same as inapplicable — no statement, no claim."""
        assert inapplicable_quality_fields(pd.DataFrame()) == ()
        assert inapplicable_quality_fields(None) == ()


class TestABankIsNotMissingWhatItCannotHave:
    def _quality(self, result, not_applicable=()):
        return compute_data_quality(result, not_applicable=not_applicable)

    def test_the_two_ratios_are_not_reported_as_missing(self):
        bank = _result(debt_equity=None, current_ratio=None)
        dq = self._quality(bank, BANK_ONLY_FIELDS)
        assert dq["missing_fields"] == []
        assert dq["n_missing"] == 0

    def test_they_leave_the_denominator_too(self):
        """A field that does not apply is not a field that was checked."""
        bank = _result(debt_equity=None, current_ratio=None)
        dq = self._quality(bank, BANK_ONLY_FIELDS)
        assert dq["n_checked"] == len(_QUALITY_KEY_FIELDS) - 2

    def test_one_real_gap_no_longer_tips_a_bank_to_partial(self):
        """BSAC's live case: two phantoms plus one true gap graded it 'partial'."""
        bsac = _result(debt_equity=None, current_ratio=None, revenue_cagr_5y=None)

        before = compute_data_quality(bsac)
        after = self._quality(bsac, BANK_ONLY_FIELDS)

        assert before["level"] == "partial"
        assert after["level"] == "good"
        assert after["missing_fields"] == ["revenue_cagr_5y"]

    def test_a_bank_with_real_gaps_is_still_downgraded(self):
        """Anti-cheat: the budget is relieved, not removed."""
        bank = _result(debt_equity=None, current_ratio=None,
                       roe=None, roic=None, pe_ratio=None)
        dq = self._quality(bank, BANK_ONLY_FIELDS)
        assert dq["n_missing"] == 3
        assert dq["level"] in ("partial", "poor")

    def test_an_industrial_missing_the_same_two_is_still_missing_them(self):
        """The exemption is the balance sheet's shape, not the field's name."""
        industrial = _result(debt_equity=None, current_ratio=None)
        dq = self._quality(industrial)          # nothing marked inapplicable
        assert sorted(dq["missing_fields"]) == sorted(BANK_ONLY_FIELDS)
        assert dq["n_missing"] == 2

    def test_the_thresholds_are_untouched(self):
        """No score and no band moved: only the count of absent fields did."""
        assert DATA_QUALITY.partial_missing_fields == 3


class TestTheScorerIsUnchanged:
    def test_this_does_not_build_a_bank_scorer(self):
        """X-01 is out of scope and must stay that way.

        The exemption lives in the data-quality layer only. If it ever reaches
        the scoring dimensions, that is a different row with its own calibration.
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "analysis" /
               "fundamental.py").read_text(encoding="utf-8")
        body = src.split("def inapplicable_quality_fields")[1].split("\ndef ")[0]
        assert "score" not in body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
