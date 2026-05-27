"""
Tests for CryptoAnalyzer scoring methods.

All tests are pure-logic — no network calls, no yfinance, no AI API.
Methods tested:
  _vol_penalty()      — annualized volatility → 0–25 pts penalty
  _drawdown_penalty() — max drawdown → 0–15 pts penalty
  _tech_pts()         — TechnicalResult signal/strength → 0–45 pts
  _compute_score()    — full scoring formula → 0–100
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from analysis.crypto_analyzer import CryptoAnalyzer, CryptoMoatDetail


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _tech(signal: str = "NEUTRAL", strength: float = 0.0) -> MagicMock:
    """Create a fake TechnicalResult with given signal and strength."""
    t = MagicMock()
    t.signal = signal
    t.signal_strength = strength
    return t


def _moat(total: float = 0.0) -> CryptoMoatDetail:
    """Create a CryptoMoatDetail with a given total moat score."""
    from config import CRYPTO_MOAT
    bonus = round(min(total * CRYPTO_MOAT.bonus_factor, CRYPTO_MOAT.max_bonus), 2)
    if total >= CRYPTO_MOAT.wide_threshold:
        classification = "Wide"
    elif total >= CRYPTO_MOAT.narrow_threshold:
        classification = "Narrow"
    elif total >= CRYPTO_MOAT.minimal_threshold:
        classification = "Minimal"
    else:
        classification = "None"
    return CryptoMoatDetail(total=total, bonus=bonus, classification=classification)


_analyzer = CryptoAnalyzer()


# ------------------------------------------------------------------ #
#  Vol Penalty                                                         #
# ------------------------------------------------------------------ #

class TestCryptoVolPenalty:
    def test_low_vol_no_penalty(self):
        """Volatility < 40% → 0 pts penalty (impossible for BTC, future-proofs ETH)."""
        assert CryptoAnalyzer._vol_penalty(35.0) == 0.0

    def test_medium_vol_penalty(self):
        """60–80% volatility → 15 pts penalty."""
        assert CryptoAnalyzer._vol_penalty(70.0) == 15.0

    def test_high_vol_penalty(self):
        """40–60% volatility → 8 pts penalty."""
        assert CryptoAnalyzer._vol_penalty(50.0) == 8.0

    def test_extreme_vol_max_penalty(self):
        """Volatility > 100% → maximum 25 pts penalty."""
        assert CryptoAnalyzer._vol_penalty(120.0) == 25.0

    def test_none_vol_returns_conservative_default(self):
        """Unknown volatility → 15 pts (conservative default, not 0)."""
        assert CryptoAnalyzer._vol_penalty(None) == 15.0

    def test_boundary_80_pct(self):
        """Exactly 80% → 80–100% bracket = 20 pts."""
        assert CryptoAnalyzer._vol_penalty(80.0) == 20.0


# ------------------------------------------------------------------ #
#  Drawdown Penalty                                                    #
# ------------------------------------------------------------------ #

class TestCryptoDrawdownPenalty:
    def test_low_drawdown_no_penalty(self):
        """Drawdown > -30% → 0 pts penalty."""
        assert CryptoAnalyzer._drawdown_penalty(-20.0) == 0.0

    def test_medium_drawdown_penalty(self):
        """-50% to -70% drawdown → 10 pts penalty."""
        assert CryptoAnalyzer._drawdown_penalty(-60.0) == 10.0

    def test_severe_drawdown_max_penalty(self):
        """Drawdown < -70% → maximum 15 pts penalty (BTC 2018: -83%, 2022: -77%)."""
        assert CryptoAnalyzer._drawdown_penalty(-83.0) == 15.0

    def test_moderate_drawdown_penalty(self):
        """-30% to -50% → 5 pts penalty."""
        assert CryptoAnalyzer._drawdown_penalty(-40.0) == 5.0

    def test_none_drawdown_returns_conservative_default(self):
        """Unknown drawdown → 10 pts (conservative default)."""
        assert CryptoAnalyzer._drawdown_penalty(None) == 10.0


# ------------------------------------------------------------------ #
#  Tech Points                                                         #
# ------------------------------------------------------------------ #

class TestCryptoTechPts:
    def test_bullish_strong_signal(self):
        """BULLISH + strength > 50 → 45 pts (maximum)."""
        assert CryptoAnalyzer._tech_pts(_tech("BULLISH", 75)) == 45.0

    def test_bullish_moderate_signal(self):
        """BULLISH + strength ≤ 50 → 35 pts."""
        assert CryptoAnalyzer._tech_pts(_tech("BULLISH", 30)) == 35.0

    def test_neutral_signal(self):
        """NEUTRAL → 22 pts."""
        assert CryptoAnalyzer._tech_pts(_tech("NEUTRAL")) == 22.0

    def test_bearish_moderate_signal(self):
        """BEARISH + strength ≥ -50 → 10 pts."""
        assert CryptoAnalyzer._tech_pts(_tech("BEARISH", -20)) == 10.0

    def test_bearish_strong_signal(self):
        """BEARISH + strength < -50 → 5 pts (minimum)."""
        assert CryptoAnalyzer._tech_pts(_tech("BEARISH", -80)) == 5.0


# ------------------------------------------------------------------ #
#  Full Score (end-to-end formula)                                     #
# ------------------------------------------------------------------ #

class TestCryptoScoreRange:
    def test_bullish_low_vol_score_in_grok_approved_range(self):
        """
        Bull market, Wide Moat, moderate vol → Grok-approved 55–70 range.
        base(35) + tech(35) - vol(8) - dd(10) + moat(5) = 57
        """
        score = _analyzer._compute_score(
            tech=_tech("BULLISH", 30),
            vol=50.0,
            max_drawdown=-55.0,
            moat_bonus=5.0,
        )
        assert 50 <= score <= 70, f"Expected 50–70 for bull market, got {score}"

    def test_bearish_high_vol_score_lower(self):
        """Bear market + extreme vol → lower score than bullish scenario."""
        bearish_score = _analyzer._compute_score(
            tech=_tech("BEARISH", -70),
            vol=90.0,
            max_drawdown=-80.0,
            moat_bonus=0.0,
        )
        bullish_score = _analyzer._compute_score(
            tech=_tech("BULLISH", 70),
            vol=40.0,
            max_drawdown=-30.0,
            moat_bonus=5.0,
        )
        assert bearish_score < bullish_score

    def test_score_never_exceeds_100(self):
        """Optimal inputs (BULLISH+, zero vol, no drawdown, max moat) → capped at 100."""
        score = _analyzer._compute_score(
            tech=_tech("BULLISH", 100),
            vol=0.0,
            max_drawdown=0.0,
            moat_bonus=5.0,
        )
        assert score <= 100.0

    def test_score_never_below_zero(self):
        """Worst-case inputs → floored at 0."""
        score = _analyzer._compute_score(
            tech=_tech("BEARISH", -100),
            vol=200.0,
            max_drawdown=-100.0,
            moat_bonus=0.0,
        )
        assert score >= 0.0

    def test_btc_typical_bull_market(self):
        """
        Approximate BTC bull market profile:
          BULLISH (strong), vol=65%, max_dd=-77%, no moat
          = base(35) + tech(45) - vol(15) - dd(15) + moat(0) = 50
        Conservative but not SELL — correct for retirement profile.
        """
        score = _analyzer._compute_score(
            tech=_tech("BULLISH", 70),
            vol=65.0,
            max_drawdown=-77.0,
            moat_bonus=0.0,
        )
        assert 40 <= score <= 65, f"Expected 40–65 for typical BTC bull, got {score}"

    def test_wide_moat_bonus_adds_to_score(self):
        """Wide Moat (total=7.0) adds moat_bonus > 0 vs no moat."""
        moat_wide = _moat(7.0)
        moat_none = _moat(0.0)

        score_with_moat = _analyzer._compute_score(
            tech=_tech("NEUTRAL"),
            vol=65.0,
            max_drawdown=-77.0,
            moat_bonus=moat_wide.bonus,
        )
        score_no_moat = _analyzer._compute_score(
            tech=_tech("NEUTRAL"),
            vol=65.0,
            max_drawdown=-77.0,
            moat_bonus=moat_none.bonus,
        )
        assert score_with_moat > score_no_moat
