"""Oráculo de #149: la escalera de acción de un cripto no es la de equity.

La escala cripto topea en ``CRYPTO_MOAT.max_achievable_score()`` (66) y BTC paga
siempre 15 de drawdown (su −83 % es el mínimo de toda la serie). Leída con la
escalera de equity (82/68/55/45), BTC salía SELL en cualquier mercado: no era un
juicio sobre el activo sino aritmética.

La referencia de abajo está escrita desde la tabla de escenarios del plan, con la
acción esperada como literal. No lee los umbrales de config: si alguien los mueve,
este test tiene que enterarse.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from analysis.crypto_analyzer import CryptoAnalyzer
from analysis.strategy import Decision, RetirementStrategy, apply_safety_overlay
from config import CRYPTO_MOAT, STRATEGY
from data.product_ux import decision_explanation
from tests.test_strategy import _fund

_analyzer = CryptoAnalyzer()

# (señal, strength) de cada fila de la tabla de escenarios.
_TECH = {
    "BULLISH fuerte": ("BULLISH", 75.0),
    "BULLISH": ("BULLISH", 30.0),
    "NEUTRAL": ("NEUTRAL", 0.0),
    "BEARISH": ("BEARISH", -20.0),
    "BEARISH fuerte": ("BEARISH", -80.0),
}

# BTC real: drawdown −83 %, volatilidad 60–80 %. (sin IA, moat Wide +8)
_BTC_TABLE = {
    "BULLISH fuerte": ((28.0, "HOLD"), (36.0, "HOLD")),
    "BULLISH": ((22.0, "REDUCE"), (30.0, "HOLD")),
    "NEUTRAL": ((14.0, "REDUCE"), (22.0, "REDUCE")),
    "BEARISH": ((6.0, "SELL"), (14.0, "REDUCE")),
    "BEARISH fuerte": ((2.0, "SELL"), (10.0, "SELL")),
}


def _ref_action(score: float) -> str:
    """La escalera cripto, escrita a mano: techo HOLD, 28 / 12."""
    if score >= 28.0:
        return "HOLD"
    if score >= 12.0:
        return "REDUCE"
    return "SELL"


def _tech(signal: str, strength: float) -> SimpleNamespace:
    return SimpleNamespace(
        signal=signal,
        signal_strength=strength,
        above_sma200=signal == "BULLISH",
        price_vs_52w_low_pct=20.0,
        rsi_weekly=55.0,
        golden_cross=False,
        sma200_slope_pct=2.0,
        warnings=[],
    )


def _crypto(score: float, symbol: str = "BTC-USD") -> SimpleNamespace:
    return _fund(score=score, symbol=symbol, is_crypto=True, mos=None, debt_equity=None, pb_ratio=None)


def _score(label: str, vol: float, moat: float, dd: float = -83.0) -> float:
    signal, strength = _TECH[label]
    return _analyzer._compute_score(
        tech=_tech(signal, strength), vol=vol, max_drawdown=dd, moat_bonus=moat
    )


@pytest.mark.parametrize("label", list(_BTC_TABLE))
@pytest.mark.parametrize("moat_idx", [0, 1])
def test_btc_scenario_table(label, moat_idx):
    expected_score, expected_action = _BTC_TABLE[label][moat_idx]
    score = _score(label, vol=70.0, moat=(0.0, 8.0)[moat_idx])
    assert score == expected_score
    signal, strength = _TECH[label]
    decision = RetirementStrategy().decide(_crypto(score), _tech(signal, strength))
    assert decision.action == expected_action


def test_btc_extreme_vol_bear_is_sell():
    score = _score("BEARISH fuerte", vol=120.0, moat=0.0)
    assert score == 0.0
    decision = RetirementStrategy().decide(_crypto(score), _tech("BEARISH", -80.0))
    assert decision.action == "SELL"


@pytest.mark.parametrize("label", list(_TECH))
@pytest.mark.parametrize("vol", [35.0, 50.0, 70.0, 90.0, 120.0])
@pytest.mark.parametrize("moat", [0.0, 8.0])
@pytest.mark.parametrize("dd", [-20.0, -83.0])
def test_sweep_matches_reference(label, vol, moat, dd):
    score = _score(label, vol=vol, moat=moat, dd=dd)
    signal, strength = _TECH[label]
    decision = RetirementStrategy().decide(_crypto(score), _tech(signal, strength))
    assert decision.action == _ref_action(score), (label, vol, moat, dd, score)


def test_a_no_crypto_score_reaches_buy():
    strategy = RetirementStrategy()
    top = int(CRYPTO_MOAT.max_achievable_score())
    for score in range(0, top + 1):
        action = strategy.decide(_crypto(float(score)), _tech("BULLISH", 75.0)).action
        assert action not in ("BUY", "STRONG BUY"), (score, action)


def test_b_hold_is_reachable():
    assert CRYPTO_MOAT.ladder_hold_score <= CRYPTO_MOAT.max_achievable_score()


def test_c_btc_best_real_case_is_hold():
    score = _score("BULLISH fuerte", vol=50.0, moat=8.0)
    assert score == 43.0
    decision = RetirementStrategy().decide(_crypto(score), _tech("BULLISH", 75.0))
    assert decision.action == "HOLD"


def test_d_ai_buy_on_btc_is_floored_to_hold_not_sell():
    score = 43.0
    fund, tech = _crypto(score), _tech("BULLISH", 75.0)
    ai = Decision(symbol="BTC-USD", action="BUY", fundamental_score=score, technical_signal="BULLISH")
    out = apply_safety_overlay(ai, fund, tech)
    assert out.action == "HOLD"


def test_e_crypto_sell_reason_does_not_claim_fundamentals():
    decision = RetirementStrategy().decide(_crypto(2.0), _tech("BEARISH", -80.0))
    assert decision.action == "SELL"
    text = " ".join([decision.decisive_reason, *decision.rationale])
    assert "Fundamental" not in text
    assert "fundamental" not in decision.decisive_reason


def test_f_equity_ladder_is_strategy():
    from analysis.strategy import ladder_for

    ladder = ladder_for(False)
    assert (ladder.strong_buy, ladder.buy, ladder.hold, ladder.reduce) == (
        STRATEGY.strong_buy_score,
        STRATEGY.buy_score,
        STRATEGY.hold_score,
        STRATEGY.reduce_score,
    )


def test_g_crypto_surfaces_quote_the_crypto_scale():
    decision = RetirementStrategy().decide(_crypto(30.0), _tech("BULLISH", 30.0))
    assert decision.action == "HOLD"
    # 30 es HOLD en la escalera cripto: el badge no puede decir «Weak».
    assert decision.score_badge == "🟡 Fair"
    ai = Decision(symbol="BTC-USD", action="SELL", fundamental_score=6.0, is_crypto=True)
    assert "/66" in decision_explanation(ai)["full_headline"]
