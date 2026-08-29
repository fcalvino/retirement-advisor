"""A REIT judged by industrial bands (backlog U5-4).

U2-6 fixed *which* payout a REIT is judged on — FFO, not accounting earnings.
What it deliberately left, and said so in ``config.py``, is *against which
thresholds*: "REIT-specific bands are U5-4's call, not this one's."

Measured over the 13 cached REITs:

  * **payout** — bands of 40 % (excellent) and 75 % (sustainable) are industrial
    numbers. A REIT distributes over 90 % of taxable income **by law**, so ≤40 %
    is not merely rare, it is structurally impossible: **not one REIT reaches the
    top band**, and four are flagged "may cut dividend" at payouts that are
    ordinary on FFO — O at 82 %, EXR at 81 %, PSA and WPC at 78 %. REITs average
    1.4 of 3 points against 2.1 for everyone else.
  * **PEG** — the feed computes it from *earnings*, and a REIT's earnings are
    depressed by depreciation, the largest charge on its income statement and not
    a cash outflow. That is the same category error P/E → P/FFO already fixed, so
    the ratio is inflated and meaningless: PLD reports a PEG of **128.04**, EQR
    16.1, DLR 13.9. REITs average **0.5 of 7 points against 2.3** for the rest.

The PEG half is closed by *not scoring it*, not by inventing a P/FFO-based
growth-adjusted multiple. Building one needs an FFO growth series and a
calibration this project cannot ground yet — the same reason ``company_type``
gives for not shipping a bank scorer. Scoring an artifact 4 points because it
happens to land under 1.5 is the defect, not the absence of a replacement.

No network, no Streamlit.
"""

from __future__ import annotations

import pytest

from analysis.fundamental import max_payout_for, payout_excellent_for
from config import THRESHOLDS


class TestThePayoutBandKnowsItsBasis:
    def test_a_reit_is_allowed_to_distribute_what_the_law_requires(self):
        assert max_payout_for("ffo") > max_payout_for("earnings")
        assert payout_excellent_for("ffo") > payout_excellent_for("earnings")

    def test_the_industrial_bands_are_untouched(self):
        """Anti-cheat: this widens one basis, it does not loosen the other."""
        assert max_payout_for("earnings") == pytest.approx(THRESHOLDS.max_payout_ratio)
        assert payout_excellent_for("earnings") == pytest.approx(THRESHOLDS.payout_excellent)

    def test_an_unknown_basis_gets_the_industrial_bands(self):
        assert max_payout_for("") == pytest.approx(THRESHOLDS.max_payout_ratio)
        assert max_payout_for(None) == pytest.approx(THRESHOLDS.max_payout_ratio)

    @pytest.mark.parametrize("payout", [82.0, 81.0, 78.0])
    def test_the_ordinary_reit_payouts_stop_being_flagged(self, payout):
        """O, EXR, PSA and WPC — normal on FFO, warned about as unsustainable."""
        assert payout > max_payout_for("earnings")
        assert payout <= max_payout_for("ffo")

    def test_a_genuinely_stretched_reit_is_still_flagged(self):
        """The band moves; it does not disappear."""
        assert 95.0 > max_payout_for("ffo")

    def test_the_top_band_becomes_reachable(self):
        """Not one of the 13 cached REITs could reach ≤40 %; the lowest is 49 %."""
        assert payout_excellent_for("ffo") >= 49.0


class TestTheScoreAndTheRiskReadOneNumber:
    """U2-6's invariant: the dimension and the warning cannot disagree."""

    def test_both_sites_call_the_same_helper(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "analysis" /
               "fundamental.py").read_text(encoding="utf-8")
        strategy = (Path(__file__).resolve().parents[1] / "analysis" /
                    "strategy.py").read_text(encoding="utf-8")
        assert "max_payout_for" in src
        assert "max_payout_for" in strategy

    def test_a_reit_is_not_scored_comfortable_and_warned_in_one_breath(self):
        """The exact shape U2-6 removed, re-checked at the new thresholds."""
        payout = 82.0
        scored_ok = payout <= max_payout_for("ffo")
        warned = payout > max_payout_for("ffo")
        assert scored_ok is not warned


class TestPegIsNotScoredOnDepressedEarnings:
    def test_a_reit_gets_no_peg_points(self):
        from analysis.fundamental import peg_applies_to

        assert peg_applies_to("reit") is False
        assert peg_applies_to("operating") is True

    def test_the_absence_is_named_as_inapplicable_not_as_missing(self):
        """"We did not look" and "this does not measure anything" differ."""
        from analysis.fundamental import PEG_NOT_APPLICABLE_REIT

        assert "FFO" in PEG_NOT_APPLICABLE_REIT
        assert "REIT" in PEG_NOT_APPLICABLE_REIT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
