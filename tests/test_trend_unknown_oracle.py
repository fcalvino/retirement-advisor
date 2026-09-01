"""Not knowing the trend is not the same as knowing it is down (backlog U3-1).

``TechnicalResult.above_sma200`` was a plain ``bool`` defaulting to ``False``,
and ``_compute_trend`` fell back to ``False`` whenever the 200-week mean was NaN.
So a company with less than ~3.8 years of listed history reported *exactly* the
same value as one trading genuinely below its long-term average — and every
consumer downstream read the second meaning:

  * ``strategy`` filed "Price below the moving average — long-term downtrend
    caution" as a risk;
  * ``personal_sizer._is_technical_weakness`` opened an "add on weakness" window;
  * the LLM prompts stated "precio DEBAJO de la media" as fact;
  * the ticker page showed ❌.

None of those were conclusions about the company. They were conclusions about
the length of its price series.

The engine already had the right idiom one field away: ``macd_bullish`` is
``Optional[bool]`` and every reader tests it with ``is True`` / ``is False``, so
an unknown contributes nothing in either direction. This applies that convention
to the three trend flags.

**A ``None`` alone does not fix anything**, which is why the consumer tests below
carry as much weight as the producer ones: ``not None`` is ``True``, so a naive
change would have kept flagging weakness, and ``bool(None)`` is ``False``, so it
would have flipped the sizer's deliberately optimistic default.

Measured against the cached universe, one ticker is affected today (LTM, 108
weekly bars). The defect is not sized by that: every newly listed company, every
recent ADR and every custom ticker a user adds enters through the same door.

No network — ``TechnicalAnalyzer.analyze`` takes a DataFrame directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis.technical import TechnicalAnalyzer

SMA200_WINDOW = 200


def _series(n_bars: int, *, drift: float) -> pd.DataFrame:
    """A deterministic weekly price series of ``n_bars`` with a steady drift."""
    prices = 100.0 * np.cumprod(np.full(n_bars, 1.0 + drift))
    return pd.DataFrame(
        {"close": prices},
        index=pd.date_range("2014-01-05", periods=n_bars, freq="W"),
    )


def _v_shaped(n_bars: int) -> pd.DataFrame:
    """Long history that fell hard and has not recovered: genuinely below trend."""
    half = n_bars // 2
    up = 100.0 * np.cumprod(np.full(half, 1.004))
    down = up[-1] * np.cumprod(np.full(n_bars - half, 0.995))
    return pd.DataFrame(
        {"close": np.concatenate([up, down])},
        index=pd.date_range("2014-01-05", periods=n_bars, freq="W"),
    )


# ================================================================== #
#  1. The producer: unknown is None, not False                         #
# ================================================================== #

class TestShortHistoryIsUnknownNotBelow:
    def test_a_series_shorter_than_the_window_reports_unknown(self):
        """The backlog's oracle, verbatim: 108 weeks → None, not False."""
        result = TechnicalAnalyzer().analyze("SHORT", _series(108, drift=0.004))
        assert result.above_sma200 is None

    def test_a_long_series_above_its_average_reports_true(self):
        result = TechnicalAnalyzer().analyze("UP", _series(400, drift=0.003))
        assert result.above_sma200 is True

    def test_a_long_series_below_its_average_reports_false(self):
        """Anti-cheat: the fix must not turn every answer into "unknown"."""
        result = TechnicalAnalyzer().analyze("DOWN", _v_shaped(400))
        assert result.above_sma200 is False

    def test_each_average_is_unknown_only_while_its_own_window_is_short(self):
        result = TechnicalAnalyzer().analyze("MID", _series(120, drift=0.002))
        assert result.above_sma50 is True       # 120 ≥ 50
        assert result.above_sma100 is True      # 120 ≥ 100
        assert result.above_sma200 is None      # 120 < 200

    def test_a_series_too_short_for_the_slope_reports_unknown(self):
        """U3-1b: 108 weeks cannot produce a 26-week change of a 200-week mean."""
        result = TechnicalAnalyzer().analyze("SHORT", _series(108, drift=0.004))
        assert result.sma200_slope_pct is None

    def test_above_the_mean_does_not_imply_the_slope_was_measured(self):
        """200 bars give ``above_sma200``; the slope still needs 26 more of that mean."""
        result = TechnicalAnalyzer().analyze("EDGE", _series(200, drift=0.003))
        assert result.above_sma200 is True
        assert result.sma200_slope_pct is None

    def test_a_long_series_reports_a_real_slope(self):
        result = TechnicalAnalyzer().analyze("UP", _series(400, drift=0.003))
        assert result.sma200_slope_pct is not None
        assert result.sma200_slope_pct > 0

    def test_an_unknown_trend_is_worth_neither_points_nor_a_penalty(self):
        """The convention ``macd_bullish`` already follows.

        The short series is built to rise, so every other component scores the
        same in both runs; the only difference is the trend flag being unknown
        rather than known-true.
        """
        short = TechnicalAnalyzer().analyze("SHORT", _series(108, drift=0.004))
        assert short.signal_strength < 100
        assert short.above_sma200 is None
        # Not penalised INTO bearish territory for the missing window either.
        assert short.signal != "BEARISH"


# ================================================================== #
#  2. The consumers: `not None` is True, and that is the trap          #
# ================================================================== #

class TestNoConsumerReadsUnknownAsBelow:
    def _decide(self, df):
        from analysis.fundamental import FundamentalResult
        from analysis.strategy import RetirementStrategy

        tech = TechnicalAnalyzer().analyze("X", df)
        fund = FundamentalResult(symbol="X")
        fund.adjusted_score = 78.0
        return RetirementStrategy().decide(fund, tech), tech

    def test_an_unknown_trend_is_not_filed_as_a_downtrend_risk(self):
        decision, tech = self._decide(_series(108, drift=0.004))
        assert tech.above_sma200 is None
        assert not [r for r in decision.risks if "below" in r.lower()]

    def test_a_real_downtrend_is_still_filed_as_one(self):
        decision, tech = self._decide(_v_shaped(400))
        assert tech.above_sma200 is False
        assert [r for r in decision.risks if "below" in r.lower()]

    def test_the_sizer_does_not_call_missing_history_a_weakness(self):
        """``below_trend = not view.above_sma200`` — the ``not None`` trap."""
        from portfolio.personal_sizer import AnalysisView, _is_technical_weakness

        unknown = AnalysisView(symbol="X", above_sma200=None, rsi_weekly=55.0,
                               price_vs_52w_high_pct=-2.0)
        below = AnalysisView(symbol="Y", above_sma200=False, rsi_weekly=55.0,
                             price_vs_52w_high_pct=-2.0)
        assert _is_technical_weakness(unknown) is False
        assert _is_technical_weakness(below) is True

    def test_the_sizer_keeps_its_optimistic_default_through_a_dict(self):
        """``bool(None)`` is False — a coercion would flip the default silently."""
        from portfolio.personal_sizer import AnalysisView

        assert AnalysisView.from_enrich("X", {}).above_sma200 is True
        assert AnalysisView.from_enrich("X", {"above_sma200": None}).above_sma200 is None

    def test_the_prompt_does_not_tell_the_model_the_price_is_below(self):
        from pathlib import Path

        src = Path("analysis/prompts.py").read_text(encoding="utf-8")
        assert 'if tech.above_sma200 else "DEBAJO"' not in src

    def test_the_prompt_does_not_print_unknown_slope_as_plus_zero(self):
        from pathlib import Path

        src = Path("analysis/prompts.py").read_text(encoding="utf-8")
        assert "tech.sma200_slope_pct:+.1f" not in src
        assert "_slope_pct(tech.sma200_slope_pct)" in src

    def test_the_sizer_does_not_coerce_a_missing_slope_to_flat(self):
        from portfolio.personal_sizer import AnalysisView

        assert AnalysisView.from_enrich("X", {}).sma200_slope_pct is None
        assert AnalysisView.from_enrich("X", {"sma200_slope_pct": None}).sma200_slope_pct is None
        assert AnalysisView.from_enrich("X", {"sma200_slope_pct": 0.0}).sma200_slope_pct == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
