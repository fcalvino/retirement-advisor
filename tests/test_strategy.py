"""Tests for RetirementStrategy decision matrix + config-driven guards."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from analysis.strategy import (
    Decision,
    RetirementStrategy,
    apply_data_quality_policy,
    apply_safety_overlay,
    effective_decision_score,
    full_analysis,
)
from config import DATA_QUALITY, STRATEGY


def _fund(
    *,
    score: float = 70.0,
    symbol: str = "TEST",
    mos: float | None = 15.0,
    is_crypto: bool = False,
    debt_equity: float | None = 0.5,
    pb_ratio: float | None = 2.0,
    total_score: float | None = None,
    adjusted_score: float | None = None,
    warnings: list | None = None,
    data_quality: dict | None = None,
) -> SimpleNamespace:
    """Minimal stand-in for FundamentalResult."""
    def is_value_stock():
        return mos is not None and mos >= STRATEGY.min_margin_of_safety_pct

    base = score if total_score is None else total_score
    adj = score if adjusted_score is None else adjusted_score

    return SimpleNamespace(
        symbol=symbol,
        total_score=base,
        adjusted_score=adj,
        is_crypto=is_crypto,
        debt_equity=debt_equity,
        pb_ratio=pb_ratio,
        margin_of_safety_pct=mos,
        graham_value=100.0 if mos else None,
        is_value_stock=is_value_stock,
        roe=20.0,
        revenue_cagr_5y=10.0,
        fcf_yield=4.0,
        payout_ratio=40.0,
        warnings=list(warnings or []),
        data_quality=data_quality,
        tailwind_classification="Neutral",
        tailwind_detail=None,
    )


def _tech(
    *,
    signal: str = "BULLISH",
    above_sma200: bool = True,
    price_vs_52w_low_pct: float = 20.0,
    rsi_weekly: float | None = 55.0,
    golden_cross: bool = False,
    sma200_slope_pct: float = 2.0,
    warnings: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        signal=signal,
        above_sma200=above_sma200,
        price_vs_52w_low_pct=price_vs_52w_low_pct,
        rsi_weekly=rsi_weekly,
        golden_cross=golden_cross,
        sma200_slope_pct=sma200_slope_pct,
        warnings=warnings or [],
    )


class TestRequireTechnicalUptrend:
    def test_buy_without_uptrend_downgrades_to_hold_when_flag_true(self):
        """High score + NEUTRAL + no SMA200 → HOLD when require_technical_uptrend."""
        eng = RetirementStrategy()
        fund = _fund(score=70.0)
        tech = _tech(signal="NEUTRAL", above_sma200=False)
        with patch.object(STRATEGY, "require_technical_uptrend", True):
            d = eng.decide(fund, tech)
        assert d.action == "HOLD"
        assert any("require_technical_uptrend" in r for r in d.rationale)

    def test_buy_with_bullish_allowed(self):
        eng = RetirementStrategy()
        fund = _fund(score=70.0)
        tech = _tech(signal="BULLISH", above_sma200=True)
        with patch.object(STRATEGY, "require_technical_uptrend", True):
            d = eng.decide(fund, tech)
        assert d.action == "BUY"

    def test_buy_with_sma200_counts_as_uptrend(self):
        """NEUTRAL signal but price above SMA200 still counts as uptrend."""
        eng = RetirementStrategy()
        fund = _fund(score=70.0)
        tech = _tech(signal="NEUTRAL", above_sma200=True)
        with patch.object(STRATEGY, "require_technical_uptrend", True):
            d = eng.decide(fund, tech)
        assert d.action == "BUY"

    def test_flag_false_allows_neutral_without_sma200(self):
        eng = RetirementStrategy()
        fund = _fund(score=70.0)
        tech = _tech(signal="NEUTRAL", above_sma200=False)
        with patch.object(STRATEGY, "require_technical_uptrend", False):
            d = eng.decide(fund, tech)
        assert d.action == "BUY"

    def test_strong_buy_without_uptrend_becomes_hold(self):
        eng = RetirementStrategy()
        fund = _fund(score=80.0, mos=20.0)
        tech = _tech(signal="NEUTRAL", above_sma200=False)
        with patch.object(STRATEGY, "require_technical_uptrend", True):
            d = eng.decide(fund, tech)
        assert d.action == "HOLD"


class TestMarginOfSafetyConfig:
    def test_is_value_stock_uses_strategy_threshold(self):
        from analysis.fundamental import FundamentalResult

        r = FundamentalResult(symbol="X", margin_of_safety_pct=12.0)
        with patch.object(STRATEGY, "min_margin_of_safety_pct", 10.0):
            assert r.is_value_stock() is True
        with patch.object(STRATEGY, "min_margin_of_safety_pct", 15.0):
            assert r.is_value_stock() is False


# ------------------------------------------------------------------ #
#  P0 audit — D1 safety overlay, D2 adjusted score, D3 max_debt_equity
# ------------------------------------------------------------------ #


class TestMaxDebtEquity:
    def test_de_above_default_blocks(self):
        eng = RetirementStrategy()
        fund = _fund(score=80.0, debt_equity=4.0)
        tech = _tech(signal="BULLISH", above_sma200=True)
        d = eng.decide(fund, tech)
        assert d.action == "AVOID"
        assert d.blocked is True
        assert "leverage" in d.block_reason.lower() or "D/E" in d.block_reason

    def test_max_debt_equity_config_override(self):
        eng = RetirementStrategy()
        fund = _fund(score=80.0, debt_equity=2.5)
        tech = _tech(signal="BULLISH", above_sma200=True)
        with patch.object(STRATEGY, "max_debt_equity", 2.0):
            d = eng.decide(fund, tech)
        assert d.action == "AVOID"
        assert d.blocked is True

    def test_de_at_threshold_not_blocked(self):
        eng = RetirementStrategy()
        fund = _fund(score=70.0, debt_equity=3.0)
        tech = _tech(signal="BULLISH", above_sma200=True)
        with patch.object(STRATEGY, "max_debt_equity", 3.0):
            with patch.object(STRATEGY, "require_technical_uptrend", True):
                d = eng.decide(fund, tech)
        assert d.action != "AVOID"
        assert d.blocked is False


class TestAdjustedScoreForDecision:
    # Derived from the ladder rather than literals: 66 used to sit above buy=60
    # and now sits below buy=68, so a hardcoded fixture silently became HOLD.
    ADJ_IN_BUY_BAND = STRATEGY.buy_score + 5      # comfortably a BUY
    BASE_BELOW_HOLD = STRATEGY.hold_score - 10    # comfortably not a BUY

    def test_adjusted_score_drives_buy_when_flag_true(self):
        """MELI-like: weak base score, strong adjusted → BUY (P0 D2)."""
        eng = RetirementStrategy()
        fund = _fund(total_score=self.BASE_BELOW_HOLD,
                     adjusted_score=self.ADJ_IN_BUY_BAND, mos=15.0)
        tech = _tech(signal="BULLISH", above_sma200=True)
        with patch.object(STRATEGY, "use_adjusted_score_for_decision", True):
            with patch.object(STRATEGY, "require_technical_uptrend", True):
                d = eng.decide(fund, tech)
        assert d.action == "BUY"
        assert d.fundamental_score == self.ADJ_IN_BUY_BAND

    def test_legacy_total_score_when_flag_false(self):
        eng = RetirementStrategy()
        fund = _fund(total_score=self.BASE_BELOW_HOLD,
                     adjusted_score=self.ADJ_IN_BUY_BAND, mos=15.0)
        tech = _tech(signal="BULLISH", above_sma200=True)
        with patch.object(STRATEGY, "use_adjusted_score_for_decision", False):
            with patch.object(STRATEGY, "require_technical_uptrend", True):
                d = eng.decide(fund, tech)
        assert d.action in ("REDUCE", "SELL", "HOLD")
        assert d.action not in ("BUY", "STRONG BUY")
        assert d.fundamental_score == self.BASE_BELOW_HOLD

    def test_effective_decision_score_helper(self):
        fund = _fund(total_score=self.BASE_BELOW_HOLD,
                     adjusted_score=self.ADJ_IN_BUY_BAND)
        with patch.object(STRATEGY, "use_adjusted_score_for_decision", True):
            assert effective_decision_score(fund) == self.ADJ_IN_BUY_BAND
        with patch.object(STRATEGY, "use_adjusted_score_for_decision", False):
            assert effective_decision_score(fund) == self.BASE_BELOW_HOLD


class TestSafetyOverlay:
    def test_safety_overlay_blocks_ai_buy(self):
        fund = _fund(score=80.0, debt_equity=4.0)
        tech = _tech(signal="BULLISH", above_sma200=True)
        decision = Decision(symbol="TEST", action="BUY", confidence="HIGH")
        out = apply_safety_overlay(decision, fund, tech)
        assert out.action == "AVOID"
        assert out.blocked is True
        assert any("safety overlay" in r.lower() for r in out.rationale)

    def test_safety_overlay_noop_when_safe(self):
        fund = _fund(score=80.0, debt_equity=0.5)
        tech = _tech(signal="BULLISH", above_sma200=True)
        decision = Decision(symbol="TEST", action="BUY", confidence="HIGH")
        out = apply_safety_overlay(decision, fund, tech)
        assert out.action == "BUY"
        assert out.blocked is False

    def test_full_analysis_applies_overlay_with_mocked_ai(self):
        fund = _fund(score=80.0, debt_equity=4.0, symbol="LEVERED")
        tech = _tech(signal="BULLISH", above_sma200=True)
        mock_ai_decision = Decision(
            symbol="LEVERED",
            action="BUY",
            confidence="HIGH",
            fundamental_score=80.0,
            ai_reasoning="LLM ignores leverage",
        )
        ai_cfg = SimpleNamespace(enabled=True, provider="xai", model="test", api_key="x")

        with patch("analysis.fundamental.FundamentalAnalyzer") as FA, \
             patch("analysis.technical.TechnicalAnalyzer") as TA, \
             patch("analysis.ai_analyzer.AIAnalyzer") as AI:
            FA.return_value.analyze.return_value = fund
            TA.return_value.analyze.return_value = tech
            # Simulate AI that does NOT apply overlay (old behavior) — full_analysis must still block
            ai_inst = MagicMock()
            ai_inst.analyze.return_value = mock_ai_decision
            AI.return_value = ai_inst

            _f, _t, decision = full_analysis("LEVERED", ai_config=ai_cfg)

        assert decision.action == "AVOID"
        assert decision.blocked is True


class TestDataQualityAndCryptoVol:
    def test_poor_data_quality_degrades_buy_to_hold(self):
        eng = RetirementStrategy()
        fund = _fund(
            score=80.0, mos=20.0,
            data_quality={"level": "poor", "missing_fields": ["roe", "pe_ratio"]},
        )
        tech = _tech(signal="BULLISH", above_sma200=True)
        with patch.object(STRATEGY, "require_technical_uptrend", True):
            with patch.object(STRATEGY, "require_margin_of_safety", False):
                d = eng.decide(fund, tech)
        assert d.action == "HOLD"
        assert any("data quality" in r.lower() or "calidad de datos" in r.lower() for r in d.rationale + d.risks)

    def test_partial_caps_strong_buy_to_buy(self):
        eng = RetirementStrategy()
        fund = _fund(
            score=90.0, mos=25.0,
            data_quality={"level": "partial", "missing_fields": ["roe", "roic", "net_margin"]},
        )
        tech = _tech(signal="BULLISH", above_sma200=True)
        with patch.object(STRATEGY, "require_technical_uptrend", True):
            with patch.object(STRATEGY, "require_margin_of_safety", False):
                d = eng.decide(fund, tech)
        assert d.action == "BUY"
        assert d.confidence in ("LOW", "MEDIUM")
        assert any("partial" in r.lower() for r in d.rationale)

    def test_apply_data_quality_policy_partial_caps_confidence(self):
        fund = _fund(data_quality={"level": "partial", "missing_fields": ["roe"]})
        d = Decision(symbol="X", action="BUY", confidence="HIGH")
        apply_data_quality_policy(d, fund, config=DATA_QUALITY)
        assert d.action == "BUY"
        assert d.confidence == DATA_QUALITY.partial_max_confidence

    def test_apply_data_quality_policy_on_ai_overlay(self):
        fund = _fund(
            score=80.0,
            data_quality={"level": "partial", "missing_fields": ["roe", "pe_ratio", "pb_ratio"]},
        )
        tech = _tech(signal="BULLISH", above_sma200=True)
        d = Decision(symbol="X", action="STRONG BUY", confidence="HIGH")
        d = apply_safety_overlay(d, fund, tech)
        assert d.action == "BUY"
        assert d.confidence == "MEDIUM"

    def test_crypto_extreme_vol_caps_buy(self):
        eng = RetirementStrategy()
        fund = _fund(
            score=70.0, is_crypto=True, mos=None,
            warnings=["⚠️ Volatilidad extrema (85% anualizada) — inadecuado"],
        )
        tech = _tech(signal="BULLISH", above_sma200=True)
        with patch.object(STRATEGY, "require_technical_uptrend", True):
            d = eng.decide(fund, tech)
        assert d.action == "HOLD"
        assert any("volatilidad" in r.lower() for r in d.rationale)


class TestPayoutRiskUsesEffectiveBasis:
    """U2-6: the decision risk must judge the same payout the scorer judged.

    ``_score_dividends`` grades REITs on FFO and persists that as
    ``payout_ratio_effective``. Reading ``payout_ratio > 80`` instead flagged 12
    of 13 cached REITs as about to cut a dividend the dividend dimension had
    just called healthy.
    """

    def _risks(self, **attrs):
        fund = _fund()
        for key, value in attrs.items():
            setattr(fund, key, value)
        decision = Decision(symbol="O", action="HOLD", confidence="MEDIUM")
        RetirementStrategy()._build_rationale(decision, fund, _tech())
        return decision.risks

    def test_healthy_ffo_payout_does_not_flag_accounting_ratio(self):
        risks = self._risks(
            payout_ratio=236.0,
            ffo_payout_pct=70.0,
            payout_ratio_effective=70.0,
            payout_basis="ffo",
        )
        assert not any("may cut dividend" in r for r in risks)

    def test_high_ffo_payout_flags_naming_the_basis(self):
        from config import THRESHOLDS as T

        risks = self._risks(
            payout_ratio=50.0,
            ffo_payout_pct=T.max_payout_ratio + 10,
            payout_ratio_effective=T.max_payout_ratio + 10,
            payout_basis="ffo",
        )
        assert any("may cut dividend" in r and "FFO" in r for r in risks)
