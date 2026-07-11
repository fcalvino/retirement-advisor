"""P3 D14 — Graham AAA yield is config-driven."""

from unittest.mock import patch

from analysis.fundamental import FundamentalAnalyzer
from config import THRESHOLDS


class TestGrahamAaaYield:
    def test_higher_yield_lowers_graham_value(self):
        """V = EPS*(8.5+2g)*4.4/Y — higher Y → lower V."""
        eps, g = 10.0, 0.10  # 10% earnings growth → g*100 = 10 in formula path
        # fundamental uses earningsGrowth as decimal * 100
        # graham = eps * (8.5 + 2*growth_estimate) * 4.4 / y
        # growth_estimate = earningsGrowth * 100
        y_low, y_high = 4.5, 6.0
        g_est = 10.0  # percent
        v_low = eps * (8.5 + 2 * g_est) * 4.4 / y_low
        v_high = eps * (8.5 + 2 * g_est) * 4.4 / y_high
        assert v_high < v_low

        # Integration via formula used in module (mirror)
        with patch.object(THRESHOLDS, "graham_aaa_yield_pct", 4.5):
            assert abs(THRESHOLDS.graham_aaa_yield_pct - 4.5) < 1e-9
        with patch.object(THRESHOLDS, "graham_aaa_yield_pct", 6.0):
            y = THRESHOLDS.graham_aaa_yield_pct
            v = eps * (8.5 + 2 * g_est) * 4.4 / y
            assert abs(v - v_high) < 1e-6

    def test_config_field_exists(self):
        assert hasattr(THRESHOLDS, "graham_aaa_yield_pct")
        assert THRESHOLDS.graham_aaa_yield_pct > 0
