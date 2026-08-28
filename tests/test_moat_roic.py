"""P2 audit D5 — ROIC spread scoring for moat quant.

The hurdle the spread is measured against is a **cost-of-equity proxy**
(rf + sector ERP), not a WACC — see U1-4 and ``analysis/moat.py._wacc_proxy``.
The identifiers here keep the legacy ``wacc`` spelling on purpose; only the
prose was corrected.
"""

from __future__ import annotations

from analysis.moat import MoatAnalyzer, MoatDetail
from config import MOAT


class TestRoicWaccSpread:  # noqa: N801 — legacy name, the hurdle is Ke (U1-4)
    def test_higher_spread_scores_higher(self):
        """Same ROIC, cheaper equity (lower ERP sector) → higher score in spread mode."""
        ma = MoatAnalyzer()
        # Force known rf/erp
        # Technology ERP default 5 → Ke = 4+5 = 9; ROIC 15 → spread 6 → 1.0
        # With patched excellent threshold still 10, good 4
        assert ma._score_roic_sustained(15.0, sector="Technology") == 1.0
        # Utilities ERP 4 → Ke 8; ROIC 15 → spread 7 → 1.0
        # Energy ERP 6 → Ke 10; ROIC 15 → spread 5 → 1.0
        # ROIC 20, Tech Ke 9 → spread 11 → 2.0
        assert ma._score_roic_sustained(20.0, sector="Technology") == 2.0
        # ROIC 9, Tech Ke 9 → spread 0 → 0.5
        assert ma._score_roic_sustained(9.0, sector="Technology") == 0.5
        # ROIC 5, Tech Ke 9 → spread -4 → 0.0
        assert ma._score_roic_sustained(5.0, sector="Technology") == 0.0

    def test_high_roic_low_spread_not_full_points(self):
        """A ROIC that clears the absolute band still loses points to a pricey sector."""
        ma = MoatAnalyzer()
        # Ke = 4 + 6 = 10 for Energy; ROIC 12 → spread 2 → 0.5 (not 1.0 from absolute ≥12)
        score = ma._score_roic_sustained(12.0, sector="Energy")
        assert score == 0.5

    def test_legacy_absolute_mode(self, monkeypatch):
        monkeypatch.setattr(MOAT, "use_roic_wacc_spread", False)
        ma = MoatAnalyzer()
        assert ma._score_roic_sustained(20.0, sector="Energy") == 2.0
        assert ma._score_roic_sustained(12.0, sector="Energy") == 1.0
        assert ma._score_roic_sustained(8.0, sector="Energy") == 0.5
        assert ma._score_roic_sustained(5.0, sector="Energy") == 0.0

    def test_wacc_proxy_uses_sector_erp(self):
        ma = MoatAnalyzer()
        w_tech = ma._wacc_proxy("Technology")
        w_energy = ma._wacc_proxy("Energy")
        assert w_energy > w_tech  # higher ERP
        assert abs(w_tech - (MOAT.risk_free_proxy_pct + MOAT.sector_erp_pct["Technology"])) < 1e-9


class TestMoatDetailPercentages:
    """Stock Analysis reads these properties for the subtotal % labels."""

    def test_quant_pct_scales_with_quant_total(self):
        low = MoatDetail(quant_total=3.0)
        high = MoatDetail(quant_total=9.0)
        full = MoatDetail(quant_total=12.0)
        assert low.quant_pct < high.quant_pct
        assert high.quant_pct < full.quant_pct
        assert full.quant_pct == MoatDetail(quant_total=12.0).quant_pct

    def test_ai_pct_zero_when_ai_unavailable(self):
        detail = MoatDetail(ai_total=8.0, ai_available=False)
        assert detail.ai_pct == 0.0

    def test_ai_pct_scales_when_available(self):
        low = MoatDetail(ai_total=2.0, ai_available=True)
        high = MoatDetail(ai_total=6.0, ai_available=True)
        assert low.ai_pct > 0
        assert high.ai_pct > low.ai_pct

    def test_stock_analysis_page_uses_moat_pct_properties(self):
        from pathlib import Path

        page = Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "2_Stock_Analysis.py"
        text = page.read_text(encoding="utf-8")
        assert "_moat_detail.quant_pct" in text
        assert "_moat_detail.ai_pct" in text
        assert "quant_total / 12 * 100" not in text
        assert "ai_total / 8 * 100" not in text
