"""P2 audit D5 — ROIC vs WACC spread scoring for moat quant."""

from __future__ import annotations

from analysis.moat import MoatAnalyzer
from config import MOAT


class TestRoicWaccSpread:
    def test_higher_spread_scores_higher(self):
        """Same ROIC, lower WACC (via lower ERP sector) → higher score when spread mode on."""
        ma = MoatAnalyzer()
        # Force known rf/erp
        # Technology ERP default 5 → WACC = 4+5 = 9; ROIC 15 → spread 6 → 1.0
        # With patched excellent threshold still 10, good 4
        assert ma._score_roic_sustained(15.0, sector="Technology") == 1.0
        # Utilities ERP 4 → WACC 8; ROIC 15 → spread 7 → 1.0
        # Energy ERP 6 → WACC 10; ROIC 15 → spread 5 → 1.0
        # ROIC 20, Tech WACC 9 → spread 11 → 2.0
        assert ma._score_roic_sustained(20.0, sector="Technology") == 2.0
        # ROIC 9, Tech WACC 9 → spread 0 → 0.5
        assert ma._score_roic_sustained(9.0, sector="Technology") == 0.5
        # ROIC 5, Tech WACC 9 → spread -4 → 0.0
        assert ma._score_roic_sustained(5.0, sector="Technology") == 0.0

    def test_high_roic_low_spread_not_full_points(self):
        """Absolute ROIC 15% with high WACC does not get full points under spread mode."""
        ma = MoatAnalyzer()
        # WACC = 4 + 6 = 10 for Energy; ROIC 12 → spread 2 → 0.5 (not 1.0 from absolute ≥12)
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
