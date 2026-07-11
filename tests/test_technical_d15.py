"""P3 D15 — RSI oversold only rewards when long-term trend intact."""

from analysis.technical import TechnicalAnalyzer, TechnicalResult


def _base_result(**kwargs) -> TechnicalResult:
    r = TechnicalResult(symbol="TEST")
    r.above_sma200 = False
    r.above_sma100 = False
    r.above_sma50 = False
    r.sma200_slope_pct = -3.0
    r.golden_cross = False
    r.death_cross = False
    r.rsi_weekly = 25.0
    r.macd_bullish = None
    r.adx = None
    r.near_bb_upper = False
    r.near_bb_lower = False
    r.volume_trend = "NEUTRAL"
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


class TestOversoldConditional:
    def test_oversold_downtrend_weaker_than_uptrend(self):
        ta = TechnicalAnalyzer()
        down = _base_result(rsi_weekly=25.0, above_sma200=False, sma200_slope_pct=-5.0)
        up = _base_result(rsi_weekly=25.0, above_sma200=True, sma200_slope_pct=2.0)
        ta._derive_signal(down)
        ta._derive_signal(up)
        assert up.signal_strength > down.signal_strength

    def test_oversold_downtrend_not_bullish_alone(self):
        """RSI oversold in downtrend should not flip to BULLISH by itself."""
        ta = TechnicalAnalyzer()
        r = _base_result(
            rsi_weekly=25.0,
            above_sma200=False,
            above_sma100=False,
            above_sma50=False,
            sma200_slope_pct=-4.0,
            macd_bullish=False,
        )
        ta._derive_signal(r)
        assert r.signal != "BULLISH"
