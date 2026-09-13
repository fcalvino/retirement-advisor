"""Oracle: confidence label is pure, deterministic and decoupled from the LLM.

Covers three claims:
1. ``confidence_for`` is a pure function — same inputs → same output for every
   rung and every cap (poor, partial, negative_equity, blocked, downgraded).
2. The rule-based path and the AI path produce the **same** ``confidence`` for
   the same (action, score, technical, dq) inputs. The LLM's own confidence lives
   in ``ai_confidence`` and never leaks into ``confidence``.
3. ``ai_confidence`` never appears in ``confidence``.
"""

from __future__ import annotations

import pytest

from analysis.strategy import _CONFIDENCE_RANK, confidence_for
from config import STRATEGY as S

# --------------------------------------------------------------------------- #
#  1. Pure function — each rung and each cap                                   #
# --------------------------------------------------------------------------- #

# (score, signal, blocked, downgraded, dq_level, neg_equity, expected)
ORACLE_CASES = [
    # STRONG BUY band (score >= 82)
    (85.0, "BULLISH",  False, False, "",        False, "HIGH"),
    (85.0, "NEUTRAL",  False, False, "",        False, "MEDIUM"),
    # BUY band (score >= 68, < 82)
    (70.0, "BULLISH",  False, False, "",        False, "HIGH"),
    (70.0, "NEUTRAL",  False, False, "",        False, "MEDIUM"),
    # HOLD band (score >= 55, < 68)
    (60.0, "BULLISH",  False, False, "",        False, "MEDIUM"),
    (60.0, "BEARISH",  False, False, "",        False, "MEDIUM"),
    # REDUCE band (score >= 45, < 55)
    (50.0, "NEUTRAL",  False, False, "",        False, "MEDIUM"),
    # SELL band (score < 45)
    (30.0, "BEARISH",  False, False, "",        False, "HIGH"),
    (30.0, "BULLISH",  False, False, "",        False, "HIGH"),
    # blocked → always HIGH regardless of score/signal
    (85.0, "BULLISH",  True,  False, "",        False, "HIGH"),
    (30.0, "BEARISH",  True,  False, "",        False, "HIGH"),
    # poor DQ → always LOW (after blocked check)
    (85.0, "BULLISH",  False, False, "poor",    False, "LOW"),
    (60.0, "NEUTRAL",  False, False, "poor",    False, "LOW"),
    # partial DQ → cap at MEDIUM
    (85.0, "BULLISH",  False, False, "partial", False, "MEDIUM"),
    (70.0, "BULLISH",  False, False, "partial", False, "MEDIUM"),
    # downgraded → cap at MEDIUM
    (85.0, "BULLISH",  False, True,  "",        False, "MEDIUM"),
    # negative_equity → cap at MEDIUM
    (85.0, "BULLISH",  False, False, "",        True,  "MEDIUM"),
    # combined: downgraded + partial (cap still MEDIUM)
    (85.0, "BULLISH",  False, True,  "partial", False, "MEDIUM"),
    # SELL + downgraded cap: base HIGH, cap to MEDIUM
    (30.0, "BEARISH",  False, True,  "",        False, "MEDIUM"),
]


@pytest.mark.parametrize(
    "score,signal,blocked,downgraded,dq,neg_equity,expected",
    ORACLE_CASES,
    ids=[f"case_{i}" for i in range(len(ORACLE_CASES))],
)
def test_confidence_for_pure(score, signal, blocked, downgraded, dq, neg_equity, expected):
    result = confidence_for(
        # HOLD: ninguna de estas filas juzga el cap por acción (ver la tabla de
        # abajo), así que la acción se mantiene fuera de la variable observada.
        "HOLD",
        score,
        signal,
        blocked=blocked,
        downgraded=downgraded,
        data_quality_level=dq,
        negative_equity=neg_equity,
    )
    assert result == expected, (
        f"confidence_for({score}, {signal!r}, blocked={blocked}, downgraded={downgraded}, "
        f"dq={dq!r}, neg_equity={neg_equity}) → {result!r}, expected {expected!r}"
    )


# --------------------------------------------------------------------------- #
#  1b. La acción emitida entra en la cuenta (SIGNAL-3)                          #
# --------------------------------------------------------------------------- #
#
# `confidence_for` recibía `action` y no lo usaba: derivaba todo de la banda del
# score. La rama de abajo emite HIGH a propósito —"alta certeza de que hay que
# salir"—, y acompañando a un BUY afirmaba lo contrario de lo que la evidencia
# sostiene. Las bandas se leen de `STRATEGY`, no se escriben a mano: la tabla se
# mueve con la escalera.

_EN_BANDA_STRONG = S.strong_buy_score + 1
_EN_BANDA_BUY = S.buy_score + 1
_ZONA_SELL = S.reduce_score - 10

# (action, score, signal, expected, por qué)
ACTION_AWARE_CASES = [
    # Una compra sin la banda que afirma: el HIGH de la banda SELL no se hereda.
    ("BUY",        _ZONA_SELL,        "BEARISH", "MEDIUM", "BUY sin banda"),
    ("STRONG BUY", _ZONA_SELL,        "BEARISH", "MEDIUM", "STRONG BUY sin banda"),
    ("STRONG BUY", _EN_BANDA_BUY,     "BULLISH", "MEDIUM", "STRONG BUY con banda de BUY"),
    # SELL en su banda conserva el HIGH: la certeza es sobre salir, y es real.
    ("SELL",       _ZONA_SELL,        "BEARISH", "HIGH",   "SELL en banda SELL"),
    ("REDUCE",     _ZONA_SELL,        "BEARISH", "HIGH",   "no es una compra"),
    # El cap no es un MEDIUM universal: una compra en su banda sigue en HIGH.
    ("BUY",        _EN_BANDA_BUY,     "BULLISH", "HIGH",   "BUY con banda de BUY"),
    ("STRONG BUY", _EN_BANDA_STRONG,  "BULLISH", "HIGH",   "STRONG BUY con su banda"),
    ("BUY",        _EN_BANDA_STRONG,  "BULLISH", "HIGH",   "BUY por debajo de su techo"),
]


@pytest.mark.parametrize("action,score,signal,expected,motivo", ACTION_AWARE_CASES)
def test_la_accion_entra_en_la_confianza(action, score, signal, expected, motivo):
    result = confidence_for(
        action, score, signal,
        blocked=False, downgraded=False, data_quality_level="", negative_equity=False,
    )
    assert result == expected, (
        f"{motivo}: confidence_for({action!r}, {score}, {signal!r}) → {result!r}, "
        f"esperado {expected!r}"
    )


def test_el_cap_por_accion_no_desplaza_a_los_que_ya_estaban():
    """`blocked` y `poor` siguen resolviendo antes que el cap nuevo."""
    kw = dict(downgraded=False, negative_equity=False)
    assert confidence_for(
        "BUY", _ZONA_SELL, "BEARISH", blocked=True, data_quality_level="", **kw
    ) == "HIGH"
    assert confidence_for(
        "BUY", _EN_BANDA_BUY, "BULLISH", blocked=False, data_quality_level="poor", **kw
    ) == "LOW"


def test_confidence_for_idempotent():
    """Same call twice → same result (pure function)."""
    args = dict(
        action="BUY", effective_score=75.0, technical_signal="BULLISH",
        blocked=False, downgraded=False, data_quality_level="", negative_equity=False,
    )
    r1 = confidence_for(**args)
    r2 = confidence_for(**args)
    assert r1 == r2


def test_confidence_rank_total_order():
    """_CONFIDENCE_RANK covers all valid labels and forms a total order."""
    assert _CONFIDENCE_RANK["LOW"] < _CONFIDENCE_RANK["MEDIUM"] < _CONFIDENCE_RANK["HIGH"]


# --------------------------------------------------------------------------- #
#  2. AI path and rule-based path produce the same confidence                  #
# --------------------------------------------------------------------------- #

def _make_fund(score: float, signal: str = "BULLISH", dq_level: str = "good", neg_eq: bool = False):
    """Minimal FundamentalResult duck-type for testing."""
    from types import SimpleNamespace
    return SimpleNamespace(
        symbol="TEST",
        adjusted_score=score,
        total_score=score,
        is_crypto=False,
        negative_equity=neg_eq,
        data_quality={"level": dq_level, "missing_fields": []} if dq_level else {},
        # No MoS so STRONG BUY score → BUY (decisive_reason set), which tests the downgraded cap.
        is_value_stock=lambda: False,
        warnings=[],
        company_name="Test Corp",
        sector="Technology",
        asset_class="equity",
        moat_score=0.0,
        moat_classification="None",
        tailwind_score=0.0,
        tailwind_classification="Neutral",
        tailwind_detail=None,
        pe_ratio=None,
        roe=None,
        revenue_cagr_5y=None,
        revenue_cagr_years=None,
        dividend_yield=None,
        margin_of_safety_pct=None,
        graham_value=None,
        current_price=100.0,
        consistency_score=0.0,
        piotroski_score=0,
        raw_adjusted_score=score,
        country=None,
        debt_equity=None,
        pb_ratio=None,
        fcf_yield=None,
        payout_ratio=None,
        ffo_payout_pct=None,
    )


def _make_tech(signal: str = "BULLISH"):
    from types import SimpleNamespace
    return SimpleNamespace(
        signal=signal,
        rsi_weekly=50.0,
        price_vs_52w_low_pct=10.0,
        above_sma200=True,
        golden_cross=False,
        sma200_slope_pct=1.0,
        warnings=[],
    )


@pytest.mark.parametrize("score,signal,dq,neg_eq", [
    (85.0, "BULLISH", "", False),
    (85.0, "NEUTRAL", "", False),
    (70.0, "BULLISH", "", False),
    (70.0, "NEUTRAL", "", False),
    (60.0, "NEUTRAL", "", False),
    (50.0, "NEUTRAL", "", False),
    (30.0, "BEARISH", "", False),
    (85.0, "BULLISH", "poor", False),
    (85.0, "BULLISH", "partial", False),
    (85.0, "BULLISH", "", True),
])
def test_rule_and_ai_paths_same_confidence(score, signal, dq, neg_eq):
    """Both paths must emit the same deterministic confidence for identical inputs."""
    from analysis.strategy import Decision, RetirementStrategy, apply_safety_overlay

    fund = _make_fund(score, signal, dq or "good", neg_eq)
    tech = _make_tech(signal)

    # Rule-based path
    rule_decision = RetirementStrategy().decide(fund, tech)
    rule_decision = apply_safety_overlay(rule_decision, fund, tech)

    # Simulated AI path: start from a Decision with the same action, but a
    # *different* ai_confidence, to prove the operative label isn't the LLM's.
    ai_decision = Decision(
        symbol="TEST",
        action=rule_decision.action,
        ai_confidence="LOW",   # deliberately wrong — should not affect confidence
        fundamental_score=score,
        technical_signal=signal,
        has_margin_of_safety=True,
        # Sin `decisive_reason`: es exactamente lo que `_parse_response` entrega.
        # Copiarlo fabricaba la precondición que el camino real no tenía — el
        # overlay lo deriva ahora del motor (SIGNAL-4).
        blocked=rule_decision.blocked,
        block_reason=rule_decision.block_reason,
    )
    ai_decision = apply_safety_overlay(ai_decision, fund, tech)

    assert rule_decision.confidence == ai_decision.confidence, (
        f"score={score}, signal={signal!r}, dq={dq!r}, neg_eq={neg_eq}: "
        f"rule={rule_decision.confidence!r} != ai={ai_decision.confidence!r}"
    )


# --------------------------------------------------------------------------- #
#  3. ai_confidence never leaks into the operative confidence field             #
# --------------------------------------------------------------------------- #

def test_ai_confidence_does_not_set_operative_confidence():
    """The LLM's ai_confidence is never used as the operative confidence."""
    from analysis.strategy import Decision, apply_safety_overlay

    fund = _make_fund(85.0, "BULLISH")
    tech = _make_tech("BULLISH")

    # Construct a Decision as _parse_response would (ai_confidence set, confidence default)
    d = Decision(
        symbol="TEST",
        action="BUY",
        ai_confidence="LOW",  # LLM said LOW
        fundamental_score=85.0,
        technical_signal="BULLISH",
        has_margin_of_safety=True,
    )
    d = apply_safety_overlay(d, fund, tech)

    assert d.confidence != "LOW", (
        f"ai_confidence='LOW' leaked into confidence={d.confidence!r}; "
        "operative confidence must be deterministic"
    )
    assert d.ai_confidence == "LOW"   # preserved as explanation


def test_default_decision_confidence_is_overwritten():
    """The default confidence='MEDIUM' on Decision is always overwritten by apply_safety_overlay."""
    from analysis.strategy import Decision, apply_safety_overlay

    fund = _make_fund(30.0, "BEARISH")   # SELL territory → should be HIGH
    tech = _make_tech("BEARISH")

    d = Decision(symbol="TEST", action="SELL", fundamental_score=30.0, technical_signal="BEARISH")
    assert d.confidence == "MEDIUM"   # default
    d = apply_safety_overlay(d, fund, tech)
    assert d.confidence == "HIGH"     # SELL → HIGH, not the default
