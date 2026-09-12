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

    def test_unknown_slope_does_not_grant_the_oversold_bonus(self):
        """U3-1b: ``None >= 0`` would TypeError; the old default 0.0 granted the bonus."""
        ta = TechnicalAnalyzer()
        unknown = _base_result(
            rsi_weekly=25.0, above_sma200=False, sma200_slope_pct=None,
        )
        # −1 is below the D15 gate but above the −2 penalty band, so the only
        # difference vs None is "was the slope measured".
        mild_down = _base_result(
            rsi_weekly=25.0, above_sma200=False, sma200_slope_pct=-1.0,
        )
        flat = _base_result(
            rsi_weekly=25.0, above_sma200=False, sma200_slope_pct=0.0,
        )
        ta._derive_signal(unknown)
        ta._derive_signal(mild_down)
        ta._derive_signal(flat)
        assert unknown.signal_strength == mild_down.signal_strength
        assert flat.signal_strength > unknown.signal_strength

    def test_d15_gate_does_not_compare_none_to_zero(self):
        from pathlib import Path

        src = Path("analysis/technical.py").read_text(encoding="utf-8")
        assert "result.sma200_slope_pct >= 0" in src
        assert "result.sma200_slope_pct is not None" in src


# ------------------------------------------------------------------ #
#  La señal como entrada de la decisión (Signal → Motivo → Confidence) #
# ------------------------------------------------------------------ #
#
# `_derive_signal` sale de pesos y umbrales de `TECHNICAL`, y su salida es una de
# las dos entradas de la matriz de `decide()`. Lo que sigue fija dos cosas que
# ningún test cubría: que los umbrales salen de config, y que una señal que el
# motor **no pudo medir** viaja como el literal "NEUTRAL", indistinguible de un
# neutral medido — la misma clase de defecto que U3-1 cerró para `above_sma200`.

import pandas as pd
import pytest

from analysis.technical import TechnicalAnalyzer as _TA
from config import TECHNICAL


class TestUmbralesDeSenalDesdeConfig:
    def test_mover_el_umbral_de_compra_mueve_la_frontera(self):
        ta = _TA()
        r = _base_result(rsi_weekly=55.0, above_sma200=True, above_sma100=True,
                         above_sma50=True, sma200_slope_pct=5.0, macd_bullish=True)
        ta._derive_signal(r)
        fuerza = r.signal_strength
        assert r.signal == "BULLISH"
        from unittest.mock import patch
        with patch.object(TECHNICAL, "buy_signal_threshold", fuerza + 1):
            ta._derive_signal(r)
            assert r.signal == "NEUTRAL"

    def test_mover_el_umbral_de_venta_mueve_la_frontera(self):
        ta = _TA()
        r = _base_result(rsi_weekly=85.0, macd_bullish=False)
        ta._derive_signal(r)
        fuerza = r.signal_strength
        from unittest.mock import patch
        with patch.object(TECHNICAL, "sell_signal_threshold", fuerza - 1):
            ta._derive_signal(r)
            assert r.signal != "BEARISH"
        with patch.object(TECHNICAL, "sell_signal_threshold", fuerza):
            ta._derive_signal(r)
            assert r.signal == "BEARISH"

    def test_la_fuerza_queda_acotada_a_mas_menos_cien(self):
        ta = _TA()
        r = _base_result(rsi_weekly=55.0, above_sma200=True, above_sma100=True,
                         above_sma50=True, sma200_slope_pct=50.0, macd_bullish=True,
                         golden_cross=True, adx=40.0, volume_trend="INCREASING")
        ta._derive_signal(r)
        assert -100 <= r.signal_strength <= 100


def _historia_corta(n: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2025-01-05", periods=n, freq="W")
    return pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1_000},
        index=idx,
    )


class TestSenalNoMedible:
    """Una empresa listada hace seis meses no tiene señal técnica; tiene *ninguna*."""

    def test_historia_insuficiente_devuelve_el_default_neutral(self):
        r = _TA().analyze("NUEVA", df=_historia_corta())
        assert any("Insufficient price history" in w for w in r.warnings)
        # El estado observable: lo mismo que un NEUTRAL medido.
        assert r.signal == "NEUTRAL"
        assert r.signal_strength == 0
        assert r.above_sma200 is None      # acá sí se distingue (U3-1)

    @pytest.mark.xfail(
        strict=True,
        reason="SIGNAL-5: la matriz acepta el NEUTRAL por default como confirmación técnica",
    )
    def test_una_senal_no_medible_no_deberia_habilitar_la_banda_strong_buy(self):
        """`decide()` exige `tech in ("BULLISH", "NEUTRAL")` para STRONG BUY
        (`strategy.py:371`). Con `require_technical_uptrend` en True el gate de
        `above_sma200` tapa el agujero; apagado —es config— el motor emite su
        veredicto de máxima convicción sin un solo dato técnico.
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        from analysis.strategy import RetirementStrategy
        from config import STRATEGY

        tech = _TA().analyze("NUEVA", df=_historia_corta())
        fund = SimpleNamespace(
            symbol="NUEVA", total_score=STRATEGY.strong_buy_score + 5,
            adjusted_score=STRATEGY.strong_buy_score + 5, is_crypto=False,
            debt_equity=0.5, pb_ratio=2.0, negative_equity=False,
            margin_of_safety_pct=25.0, graham_value=100.0, is_value_stock=lambda: True,
            roe=20.0, revenue_cagr_5y=10.0, fcf_yield=4.0, payout_ratio=40.0,
            warnings=[], data_quality={"level": "good"},
            tailwind_classification="Neutral", tailwind_detail=None,
        )
        with patch.object(STRATEGY, "require_technical_uptrend", False):
            d = RetirementStrategy().decide(fund, tech)
        assert d.action != "STRONG BUY"
