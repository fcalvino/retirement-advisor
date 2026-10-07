"""Oráculo EVAL-GROQ-1: salir de una posición no admite un tope de asignación > 0.

En las dos corridas en vivo del banco (Groq `gpt-oss-120b`, 2026-09-27) el caso
`high_leverage_caution` salió SELL con `recommended_max_allocation_conservative`
= 4 %, y Stock Analysis lo pintaba como «🎯 La IA sugiere máximo 4 % de
asignación» en una caja verde. Decisión del usuario (2026-09-28): una guarda
determinista en `apply_safety_overlay`, sin tocar el prompt, para SELL y AVOID.

La fila sólo nombraba el SELL del modelo. El overlay también **produce** SELL y
AVOID —el piso `min(LLM, motor)` y los bloqueos— y en los dos casos el tope que
el modelo había pensado para una compra sobrevivía a la acción que lo contradice.

Invariantes:

1. Acción final SELL o AVOID ⇒ asignación 0, venga de donde venga la acción.
2. REDUCE y las compras conservan el tope del modelo.
3. ``None`` («el modelo no sugirió») sigue ``None``: no se inventa un 0.
4. Idempotente: el overlay corre dos veces sobre el mismo objeto.
5. El parser acota con `STRATEGY.ai_max_allocation_pct`, no con un literal.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from analysis.ai_analyzer import AIAnalyzer
from analysis.committee import CommitteeAnalyzer
from analysis.strategy import apply_safety_overlay
from config import STRATEGY as S
from config import AIConfig
from tests.test_ai_path_equivalence_oracle import STRONG, _fund, _llm, _tech
from tests.test_committee_overlay_oracle import _all_buy, _base

SELL_ZONE = S.reduce_score - 10


def _with_alloc(action: str, score: float, alloc):
    d = _llm(action, score)
    d.recommended_max_allocation_pct = alloc
    return d


class TestSalirEsCero:

    def test_sell_del_modelo_con_tope(self):
        """El caso del banco: SELL con 4 %."""
        d = apply_safety_overlay(_with_alloc("SELL", SELL_ZONE, 4.0),
                                 _fund(SELL_ZONE, dq={"level": "good"}), _tech("BEARISH"))
        assert (d.action, d.recommended_max_allocation_pct) == ("SELL", 0.0)

    def test_compra_que_el_tope_baja_a_reduce_conserva_el_tope_del_modelo(self):
        """EO-6b-1: el modelo pensó el 8 % para un BUY; el tope lo baja a REDUCE (un
        escalón sobre el SELL del motor). REDUCE no es una salida: reducir no es salir,
        así que el tope del modelo no se pone en 0 (`ai_allocation_zero_actions`)."""
        d = apply_safety_overlay(_with_alloc("BUY", SELL_ZONE, 8.0),
                                 _fund(SELL_ZONE, dq={"level": "good"}), _tech())
        assert d.action == "REDUCE"
        assert d.recommended_max_allocation_pct == 8.0

    def test_compra_bloqueada_a_avoid(self):
        fund = _fund(STRONG, debt_equity=S.max_debt_equity + 1, dq={"level": "good"})
        d = apply_safety_overlay(_with_alloc("BUY", STRONG, 5.0), fund, _tech())
        assert (d.action, d.blocked) == ("AVOID", True)
        assert d.recommended_max_allocation_pct == 0.0

    def test_cripto_parabolico_bloqueado(self):
        fund = _fund(STRONG, is_crypto=True, dq={"level": "good"})
        tech = _tech(rsi_weekly=85.0, price_vs_52w_low_pct=200.0)
        d = apply_safety_overlay(_with_alloc("HOLD", STRONG, 3.0), fund, tech)
        assert d.action == "AVOID"
        assert d.recommended_max_allocation_pct == 0.0


class TestLoQueNoEsSalirSeConserva:

    def test_reduce_conserva_su_tope(self):
        score = S.reduce_score + 1
        d = apply_safety_overlay(_with_alloc("REDUCE", score, 6.0),
                                 _fund(score, dq={"level": "good"}), _tech())
        assert (d.action, d.recommended_max_allocation_pct) == ("REDUCE", 6.0)

    def test_compra_que_queda_compra(self):
        d = apply_safety_overlay(_with_alloc("STRONG BUY", STRONG, 8.0),
                                 _fund(STRONG, dq={"level": "good"}), _tech())
        assert d.action in ("BUY", "STRONG BUY")
        assert d.recommended_max_allocation_pct == 8.0

    def test_sin_sugerencia_no_se_inventa_un_cero(self):
        d = apply_safety_overlay(_with_alloc("SELL", SELL_ZONE, None),
                                 _fund(SELL_ZONE, dq={"level": "good"}), _tech("BEARISH"))
        assert d.action == "SELL"
        assert d.recommended_max_allocation_pct is None

    def test_el_comite_no_tiene_asignacion_y_sigue_sin_tenerla(self):
        fund, tech = _base()
        fund = replace(fund, debt_equity=S.max_debt_equity + 1.0)
        verdict = CommitteeAnalyzer(call_fn=_all_buy(), use_cache=False).analyze(fund, tech)
        logged = verdict.to_decision(fund, tech)
        assert logged.action == "AVOID"
        assert logged.recommended_max_allocation_pct is None


def test_idempotente():
    fund = _fund(SELL_ZONE, dq={"level": "good"})
    una = apply_safety_overlay(_with_alloc("BUY", SELL_ZONE, 8.0), fund, _tech())
    estado = (una.action, una.recommended_max_allocation_pct, una.confidence, una.decisive_reason)
    dos = apply_safety_overlay(una, fund, _tech())
    assert (dos.action, dos.recommended_max_allocation_pct, dos.confidence,
            dos.decisive_reason) == estado


def test_las_acciones_de_salida_viven_en_config():
    assert set(S.ai_allocation_zero_actions) == {"SELL", "AVOID"}


@pytest.mark.parametrize("raw_alloc, expected", [(40, "techo"), (-3, 0.0), (6, 6.0)])
def test_el_parser_acota_con_config(raw_alloc, expected):
    if expected == "techo":
        expected = S.ai_max_allocation_pct
    raw = json.dumps({"action": "BUY", "confidence": "HIGH",
                      "recommended_max_allocation_conservative": raw_alloc})
    d = AIAnalyzer(AIConfig(provider="groq", model="m", api_key="k"))._parse_response(
        raw, _fund(STRONG, dq={"level": "good"}), _tech())
    assert d.recommended_max_allocation_pct == expected
