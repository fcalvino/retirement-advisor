"""Tests for RetirementStrategy decision matrix + config-driven guards."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from analysis.strategy import RetirementStrategy
from config import STRATEGY


def _fund(
    *,
    score: float = 70.0,
    symbol: str = "TEST",
    mos: float | None = 15.0,
    is_crypto: bool = False,
    debt_equity: float | None = 0.5,
    pb_ratio: float | None = 2.0,
) -> SimpleNamespace:
    """Minimal stand-in for FundamentalResult."""
    def is_value_stock():
        return mos is not None and mos >= STRATEGY.min_margin_of_safety_pct

    return SimpleNamespace(
        symbol=symbol,
        total_score=score,
        adjusted_score=score,
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
        warnings=[],
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
