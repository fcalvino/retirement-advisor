"""Oráculo: el camino AI no puede salir mejor parado que el rule-based.

`apply_safety_overlay` es el único punto donde el veredicto del LLM se vuelve a
someter a las reglas del motor, y existe justamente para eso (P0 D1). El contrato
que fija este archivo es una igualdad, no una lista de casos: **para el mismo
`(fundamental, technical)`, la acción del camino AI no puede ser mejor que la del
camino rule-based cuando la diferencia la produce una regla del motor** — un block
duro, el cap por patrimonio negativo o la política de data quality.

La rama equity del overlay cumple eso (`strategy.py:132-145`). La rama crypto
(`strategy.py:113-130`) sólo re-aplica el block parabólico: no llama a
`apply_negative_equity_policy` ni a `apply_data_quality_policy`, que `decide()` sí
aplica para crypto (`strategy.py:434-435`). Ver SIGNAL-2.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from analysis.strategy import (
    Decision,
    RetirementStrategy,
    apply_safety_overlay,
    effective_decision_score,
)
from config import STRATEGY as S

_RANK = {"AVOID": -1, "SELL": 0, "REDUCE": 1, "HOLD": 2, "BUY": 3, "STRONG BUY": 4}
_CONF = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _fund(
    score: float,
    *,
    is_crypto: bool = False,
    dq: dict | None = None,
    negative_equity: bool = False,
    debt_equity: float | None = 0.5,
    warnings: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol="TEST",
        total_score=score,
        adjusted_score=score,
        is_crypto=is_crypto,
        debt_equity=debt_equity,
        pb_ratio=2.0,
        negative_equity=negative_equity,
        margin_of_safety_pct=25.0,
        graham_value=100.0,
        is_value_stock=lambda: True,
        roe=20.0,
        revenue_cagr_5y=10.0,
        fcf_yield=4.0,
        payout_ratio=40.0,
        warnings=list(warnings or []),
        data_quality=dq,
        tailwind_classification="Neutral",
        tailwind_detail=None,
    )


def _tech(
    signal: str = "BULLISH",
    *,
    rsi_weekly: float | None = 55.0,
    price_vs_52w_low_pct: float = 20.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        signal=signal,
        above_sma200=True,
        price_vs_52w_low_pct=price_vs_52w_low_pct,
        rsi_weekly=rsi_weekly,
        golden_cross=False,
        sma200_slope_pct=2.0,
        warnings=[],
    )


def _llm(action: str, score: float, signal: str = "BULLISH") -> Decision:
    """Lo que `AIAnalyzer._parse_response` entrega al overlay."""
    return Decision(
        symbol="TEST", action=action, ai_confidence="HIGH",
        fundamental_score=score, technical_signal=signal, has_margin_of_safety=True,
    )


STRONG = S.strong_buy_score + 5


# --------------------------------------------------------------------------- #
#  Defecto #2 — la rama crypto del overlay saltea las políticas blandas        #
# --------------------------------------------------------------------------- #

class TestElOverlayCryptoAplicaLasMismasPoliticas:

    @pytest.mark.xfail(strict=True, reason="SIGNAL-2: la rama crypto del overlay no llama apply_data_quality_policy")
    @pytest.mark.parametrize("level,accion_maxima", [("poor", "HOLD"), ("partial", "BUY")])
    def test_data_quality_degrada_igual_que_en_el_camino_rule_based(self, level, accion_maxima):
        fund = _fund(STRONG, is_crypto=True, dq={"level": level, "missing_fields": ["roe"]})
        tech = _tech()
        rule = RetirementStrategy().decide(fund, tech)
        ai = apply_safety_overlay(_llm("STRONG BUY", STRONG), fund, tech)
        assert _RANK[ai.action] <= _RANK[rule.action], (
            f"crypto dq={level}: el camino AI salió {ai.action} y el rule-based "
            f"{rule.action} — el LLM se salteó la política de data quality"
        )
        assert _RANK[ai.action] <= _RANK[accion_maxima]

    @pytest.mark.xfail(strict=True, reason="SIGNAL-2: la rama crypto del overlay no llama apply_negative_equity_policy")
    def test_patrimonio_negativo_capa_igual_que_en_el_camino_rule_based(self):
        fund = _fund(STRONG, is_crypto=True, negative_equity=True, dq={"level": "good"})
        tech = _tech()
        rule = RetirementStrategy().decide(fund, tech)
        ai = apply_safety_overlay(_llm("STRONG BUY", STRONG), fund, tech)
        assert _RANK[ai.action] <= _RANK[rule.action]

    @pytest.mark.xfail(strict=True, reason="SIGNAL-2: acción y confianza apuntan en direcciones opuestas")
    def test_no_puede_quedar_una_compra_con_confianza_low(self):
        """El síntoma visible en la tabla: STRONG BUY con «Conf. LOW».

        La confianza sí ve la data quality (`confidence_for` la lee) y la acción no,
        así que la fila se contradice sola.
        """
        fund = _fund(STRONG, is_crypto=True, dq={"level": "poor", "missing_fields": ["roe"]})
        ai = apply_safety_overlay(_llm("STRONG BUY", STRONG), fund, _tech())
        assert not (ai.action in ("STRONG BUY", "BUY") and ai.confidence == "LOW")

    def test_el_block_parabolico_crypto_si_se_re_aplica(self):
        """Lo que la rama crypto sí hace — sin esto el defecto sería otro."""
        fund = _fund(STRONG, is_crypto=True, dq={"level": "good"})
        tech = _tech(rsi_weekly=85.0, price_vs_52w_low_pct=200.0)
        ai = apply_safety_overlay(_llm("STRONG BUY", STRONG), fund, tech)
        assert ai.action == "AVOID" and ai.blocked is True
        assert ai.decisive_reason.startswith("Bloqueado")

    def test_el_umbral_parabolico_crypto_es_mas_alto_que_el_de_equity(self):
        """120 % vs 100 %: un crypto +110 % con RSI 85 no se bloquea."""
        tech = _tech(rsi_weekly=85.0, price_vs_52w_low_pct=110.0)
        crypto = apply_safety_overlay(
            _llm("BUY", STRONG), _fund(STRONG, is_crypto=True, dq={"level": "good"}), tech
        )
        equity = apply_safety_overlay(_llm("BUY", STRONG), _fund(STRONG, dq={"level": "good"}), tech)
        assert crypto.blocked is False
        assert equity.blocked is True


# --------------------------------------------------------------------------- #
#  Equivalencia y no-mejora, como propiedad                                    #
# --------------------------------------------------------------------------- #

GRID = [
    (score, signal, dq, neg)
    for score in (STRONG, S.buy_score + 1, S.hold_score + 1, S.reduce_score - 5)
    for signal in ("BULLISH", "NEUTRAL", "BEARISH")
    for dq in ("good", "partial", "poor")
    for neg in (False, True)
]


@pytest.mark.parametrize("score,signal,dq,neg", GRID)
def test_el_camino_ai_nunca_mejora_la_accion_del_rule_based_en_equity(score, signal, dq, neg):
    """Sobre 72 combinaciones: partiendo de la misma acción, el overlay no puede
    dejar al camino AI por encima del rule-based.

    El pipeline real corre el overlay en las dos ramas (`strategy.py:569-578`), así
    que el rule-based se compara *después* del overlay — `decide()` sola deja la
    confianza en el default del dataclass.

    El eje de la confianza está cubierto por
    `test_confidence_deterministic_oracle.py::test_rule_and_ai_paths_same_confidence`
    (con una salvedad: ese test le copia el `decisive_reason` al Decision del LLM;
    ver `test_el_motivo_del_motor_no_viaja_por_el_camino_ai` más abajo). Acá se fija
    el eje que faltaba: la acción."""
    fund = _fund(score, dq={"level": dq, "missing_fields": ["roe"]}, negative_equity=neg)
    tech = _tech(signal)
    rule = apply_safety_overlay(RetirementStrategy().decide(fund, tech), fund, tech)
    ai = apply_safety_overlay(_llm(rule.action, score, signal), fund, tech)
    assert _RANK[ai.action] <= _RANK[rule.action]


# --------------------------------------------------------------------------- #
#  Defecto #4 — el motivo del motor no existe en el camino AI                  #
# --------------------------------------------------------------------------- #

class TestElMotivoEnElCaminoAI:
    """`_parse_response` nunca escribe `decisive_reason` (`ai_analyzer.py:490-502`).

    Dos consecuencias, porque ese campo tiene dos usos: es el texto de la celda
    «Motivo» y es el `downgraded` que capa la confianza a MEDIUM
    (`strategy.py:152`). Ver SIGNAL-4.
    """

    #: Fundamentales de STRONG BUY sin margen de seguridad: el rule-based emite BUY
    #: y explica por qué (`strategy.py:376-380`). Mismo input, misma acción — la
    #: única diferencia entre las dos ramas es quién la eligió.
    def _fund_sin_margen(self):
        fund = _fund(STRONG, dq={"level": "good"})
        fund.margin_of_safety_pct = None
        fund.is_value_stock = lambda: False
        return fund

    @pytest.mark.xfail(strict=True, reason="SIGNAL-4: el camino AI no capa la confianza porque no tiene decisive_reason")
    def test_la_misma_accion_no_puede_salir_con_mas_confianza_por_el_camino_ai(self):
        fund, tech = self._fund_sin_margen(), _tech("BULLISH")
        rule = apply_safety_overlay(RetirementStrategy().decide(fund, tech), fund, tech)
        ai = apply_safety_overlay(_llm(rule.action, STRONG), fund, tech)
        assert rule.action == ai.action == "BUY"      # precondición del caso
        assert _CONF[ai.confidence] <= _CONF[rule.confidence], (
            f"misma acción ({rule.action}) sobre el mismo input: rule={rule.confidence}, "
            f"ai={ai.confidence} — el cap `downgraded` no llega al camino AI"
        )

    @pytest.mark.xfail(strict=True, reason="SIGNAL-4: la celda Motivo del camino AI no nombra la causa")
    def test_el_motivo_del_motor_no_viaja_por_el_camino_ai(self):
        from data.product_ux import decision_explanation

        fund, tech = self._fund_sin_margen(), _tech("BULLISH")
        ai = apply_safety_overlay(_llm("BUY", STRONG), fund, tech)
        assert decision_explanation(ai)["is_downgrade"] is True, (
            "el motor bajó STRONG BUY a BUY por falta de margen de seguridad y la "
            f"celda dice {decision_explanation(ai)['full_headline']!r}"
        )


# --------------------------------------------------------------------------- #
#  Idempotencia — el camino AI corre el overlay dos veces                      #
# --------------------------------------------------------------------------- #

class TestIdempotencia:
    """`AIAnalyzer.analyze` lo llama (`ai_analyzer.py:80`) y `full_analysis` lo
    vuelve a llamar sobre el mismo objeto (`strategy.py:578`). La segunda pasada
    tiene que ser un no-op."""

    def _dos_pasadas(self, decision, fund, tech):
        una = apply_safety_overlay(decision, fund, tech)
        estado_1 = (una.action, una.confidence, list(una.rationale), list(una.risks),
                    una.blocked, una.decisive_reason)
        dos = apply_safety_overlay(una, fund, tech)
        estado_2 = (dos.action, dos.confidence, list(dos.rationale), list(dos.risks),
                    dos.blocked, dos.decisive_reason)
        return estado_1, estado_2

    def test_equity_bloqueado_por_leverage(self):
        fund = _fund(STRONG, debt_equity=S.max_debt_equity + 1, dq={"level": "good"})
        uno, dos = self._dos_pasadas(_llm("BUY", STRONG), fund, _tech())
        assert uno == dos

    def test_crypto_bloqueado_por_parabolico(self):
        fund = _fund(STRONG, is_crypto=True, dq={"level": "good"})
        tech = _tech(rsi_weekly=85.0, price_vs_52w_low_pct=200.0)
        uno, dos = self._dos_pasadas(_llm("STRONG BUY", STRONG), fund, tech)
        assert uno == dos

    def test_equity_capado_por_data_quality(self):
        fund = _fund(STRONG, dq={"level": "partial", "missing_fields": ["roe"]})
        uno, dos = self._dos_pasadas(_llm("STRONG BUY", STRONG), fund, _tech())
        assert uno == dos

    def test_equity_capado_por_patrimonio_negativo(self):
        fund = _fund(STRONG, negative_equity=True, dq={"level": "good"})
        uno, dos = self._dos_pasadas(_llm("STRONG BUY", STRONG), fund, _tech())
        assert uno == dos

    def test_decision_limpia(self):
        fund = _fund(STRONG, dq={"level": "good"})
        uno, dos = self._dos_pasadas(_llm("STRONG BUY", STRONG), fund, _tech())
        assert uno == dos


# --------------------------------------------------------------------------- #
#  Score efectivo: crypto no depende del flag                                  #
# --------------------------------------------------------------------------- #

def test_crypto_siempre_usa_adjusted_score():
    """`total_score` es 0 por diseño en crypto: si el flag lo desviara al legacy,
    todo crypto caería en banda SELL."""
    fund = _fund(0.0, is_crypto=True)
    fund.total_score = 0.0
    fund.adjusted_score = STRONG
    with patch.object(S, "use_adjusted_score_for_decision", False):
        assert effective_decision_score(fund) == STRONG
        assert RetirementStrategy().decide(fund, _tech()).fundamental_score == STRONG
