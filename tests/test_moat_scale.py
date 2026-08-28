"""Contract of the moat scale (backlog U3-7).

There are two scales and the code used to have one set of thresholds. With the
AI layer a moat total runs 0–20; without it the total *is* the quantitative
tramo, which caps at 12 — against a `wide_threshold` of 14. So **Wide Moat was
unreachable by construction** in quant-only mode. Measured with
`scripts/measure_score_impact.py --matrix` over the 164 cached tickers: 0 Wide
without AI, 22 with it.

That produced the compound defect: the same ticker showed a different moat
depending on the screen, and no screen said which mode it had used. The
Optimizer was the worst offender because it did not read the engine's label at
all — it re-derived one from a bare score with a hardcoded `>= 14`, on rows that
in that path usually have no AI behind them.

These tests pin the scale, the mode-awareness, and the fact that nothing
re-implements the mapping. They do not pin the *values* of the quant-only
thresholds beyond the properties that make them defensible — those were fitted
against the AI-on label and are config, not doctrine.

No network, no Streamlit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analysis.moat import MoatAnalyzer, MoatDetail, classify_moat
from config import MOAT

ROOT = Path(__file__).resolve().parents[1]

QUANT_MAX = 12.0   # 6 dimensions × 2.0 (analysis.moat._score_quant)
AI_MAX = 8.0       # 4 dimensions × 2.0


# ================================================================== #
#  1. The defect: a label you cannot reach                             #
# ================================================================== #

class TestWideIsReachableInBothModes:
    def test_the_quantitative_tramo_cannot_reach_the_ai_scale_threshold(self):
        """The premise of U3-7, stated as an assertion rather than a memory."""
        assert QUANT_MAX < MOAT.wide_threshold

    def test_a_perfect_quantitative_moat_is_wide(self):
        """Without this, the best possible quant-only company is still Narrow."""
        assert classify_moat(QUANT_MAX, ai_available=False) == "Wide"

    def test_a_perfect_combined_moat_is_wide(self):
        assert classify_moat(QUANT_MAX + AI_MAX, ai_available=True) == "Wide"

    def test_every_label_is_reachable_in_quant_only_mode(self):
        reachable = {
            classify_moat(total / 2, ai_available=False)
            for total in range(0, int(QUANT_MAX * 2) + 1)
        }
        assert reachable == {"Wide", "Narrow", "Minimal", "None"}


class TestTheTwoScalesAreOrdered:
    """Whatever the fitted values, these relations must hold to make sense."""

    def test_quant_only_thresholds_sit_below_their_ai_counterparts(self):
        assert MOAT.quant_only_wide_threshold < MOAT.wide_threshold
        assert MOAT.quant_only_narrow_threshold < MOAT.narrow_threshold
        assert MOAT.quant_only_minimal_threshold < MOAT.minimal_threshold

    def test_the_quant_only_thresholds_are_ordered_and_reachable(self):
        assert (
            0
            < MOAT.quant_only_minimal_threshold
            < MOAT.quant_only_narrow_threshold
            < MOAT.quant_only_wide_threshold
            <= QUANT_MAX
        )

    def test_the_ai_thresholds_were_not_touched(self):
        """U3-7 explicitly forbids lowering Wide on the AI scale."""
        assert MOAT.wide_threshold == 14.0
        assert MOAT.narrow_threshold == 8.0
        assert MOAT.minimal_threshold == 4.0

    @pytest.mark.parametrize("total", [0.0, 3.0, 6.0, 9.0, 12.0])
    def test_the_same_total_never_scores_lower_without_ai(self, total):
        """A shorter ruler cannot make the same evidence look weaker."""
        rank = {"None": 0, "Minimal": 1, "Narrow": 2, "Wide": 3}
        quant = rank[classify_moat(total, ai_available=False)]
        combined = rank[classify_moat(total, ai_available=True)]
        assert quant >= combined


# ================================================================== #
#  2. Mode-awareness at every site that classifies                     #
# ================================================================== #

class TestTheModeTravelsWithTheScore:
    def test_quant_only_analysis_classifies_on_the_short_scale(self, monkeypatch):
        analyzer = MoatAnalyzer()
        detail = MoatDetail(quant_total=11.5)
        detail.total = detail.quant_total
        assert analyzer._classify(detail.total, ai_available=False) == "Wide"

    def test_a_failed_ai_call_is_not_a_demotion(self):
        """When the provider fails, ai_total is 0 and the total IS the quant tramo.

        Judging that against the 0–20 thresholds would downgrade a company for a
        provider outage rather than for anything about the company.
        """
        analyzer = MoatAnalyzer()
        assert analyzer._classify(11.5, ai_available=False) == "Wide"
        assert analyzer._classify(11.5, ai_available=True) == "Narrow"

    def test_the_detail_reports_the_ceiling_it_was_measured_against(self):
        assert MoatDetail(ai_available=False).scale_max == QUANT_MAX
        assert MoatDetail(ai_available=True).scale_max == QUANT_MAX + AI_MAX

    def test_the_detail_names_its_mode(self):
        assert "solo cuantitativo" in MoatDetail(ai_available=False).mode_label
        assert "IA" in MoatDetail(ai_available=True).mode_label


# ================================================================== #
#  3. Nobody re-implements the mapping                                 #
# ================================================================== #

class TestNoSurfaceReDerivesTheLabel:
    def test_the_optimizer_no_longer_hardcodes_the_ai_scale_threshold(self):
        src = (ROOT / "portfolio" / "optimizer.py").read_text(encoding="utf-8")
        assert "a.moat_score >= 14" not in src
        assert "classify_moat" in src

    def test_the_optimizer_prefers_the_label_the_engine_computed(self):
        """Re-deriving is the fallback, not the path."""
        from portfolio.optimizer import TickerAllocation

        alloc = TickerAllocation(
            symbol="X", weight_pct=10.0, expected_return_pct=8.0,
            volatility_pct=15.0, dividend_yield_pct=1.0, adjusted_score=80.0,
            moat_score=9.0, sector="Tech", moat_classification="Narrow",
        )
        assert alloc.moat_classification == "Narrow"

    def test_the_bonus_ceiling_is_documented_per_mode(self):
        """moat.py promised +10; quant-only can only ever pay +6."""
        analyzer = MoatAnalyzer()
        assert analyzer._bonus(QUANT_MAX) == 6.0
        assert analyzer._bonus(QUANT_MAX + AI_MAX) == MOAT.max_bonus

        doc = (ROOT / "analysis" / "moat.py").read_text(encoding="utf-8")
        assert "+6" in doc

    def test_the_crypto_scale_is_untouched(self):
        """CryptoMoatConfig shares the field names on a 0–8 scale."""
        from config import CRYPTO_MOAT

        assert CRYPTO_MOAT.wide_threshold == 6.0
        assert CRYPTO_MOAT.max_bonus == 8.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
