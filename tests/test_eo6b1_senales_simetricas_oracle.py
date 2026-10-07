"""Oráculo EO-6b-1: las señales dejan de ser asimétricas (ADR 0001, bloque 6 del BACKLOG).

Decisiones del usuario (2026-10-07):

- el tope de la IA contra la escalera es simétrico, un escalón (``STRATEGY.ai_ladder_step_tolerance``);
- con datos parciales la señal se atenúa hacia HOLD en las dos direcciones: STRONG BUY → BUY
  (ya estaba) y SELL → REDUCE (``DATA_QUALITY.partial_lifts_sell``); AVOID no se toca;
- los umbrales 82/68/55/45 se rotulan «ranking relativo, no calibrado»;
- ``SIGNAL_METHOD_VERSION`` sube (EO-6a lo guarda en el track record).

El rango que permite el tope está probado a mano en ``test_ai_path_equivalence_oracle``
(`test_la_accion_del_llm_queda_a_un_escalon_del_motor`). Acá: la atenuación, la tolerancia
en config y el rótulo. Sin red.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.strategy import (
    Decision,
    RetirementStrategy,
    apply_data_quality_policy,
    apply_safety_overlay,
)
from config import DATA_QUALITY, ENGINE_VERSION, SIGNAL_METHOD_VERSION, STRATEGY

ROOT = Path(__file__).resolve().parents[1]


def _fund(level: str) -> SimpleNamespace:
    return SimpleNamespace(data_quality={"level": level})


def _d(action: str) -> Decision:
    return Decision(symbol="X", action=action)


# --------------------------------------------------------------------------- #
#  Atenuación con datos parciales: el espejo                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("entrada,esperado", [
    ("STRONG BUY", "BUY"),        # ya estaba
    ("SELL", "REDUCE"),           # el espejo, EO-6b-1
    ("BUY", "BUY"), ("HOLD", "HOLD"), ("REDUCE", "REDUCE"),
    ("AVOID", "AVOID"),           # un bloqueo duro no es una señal
])
def test_partial_attenuates_one_step_toward_hold_on_both_sides(entrada, esperado):
    d = apply_data_quality_policy(_d(entrada), _fund("partial"))
    assert d.action == esperado


def test_a_sell_with_good_data_is_untouched_and_the_note_names_the_cause():
    assert apply_data_quality_policy(_d("SELL"), _fund("good")).action == "SELL"
    d = apply_data_quality_policy(_d("SELL"), _fund("partial"))
    assert d.decisive_reason == "SELL atenuado a REDUCE: data quality partial"
    assert d.rationale[0] == d.decisive_reason


def test_the_mirror_has_its_own_switch():
    class _Off:
        partial_caps_strong_buy = True
        partial_lifts_sell = False

    assert apply_data_quality_policy(_d("SELL"), _fund("partial"), config=_Off()).action == "SELL"
    assert apply_data_quality_policy(_d("STRONG BUY"), _fund("partial"), config=_Off()).action == "BUY"
    assert DATA_QUALITY.partial_lifts_sell is True


def test_the_rule_path_attenuates_too():
    """`decide()` corre la misma política: un score de SELL con datos parciales emite REDUCE."""
    from tests.test_ai_path_equivalence_oracle import _fund as full_fund
    from tests.test_ai_path_equivalence_oracle import _tech

    score = STRATEGY.reduce_score - 10
    rule = RetirementStrategy().decide(
        full_fund(score, dq={"level": "partial", "missing_fields": ["roe"]}), _tech("BULLISH"))
    assert rule.action == "REDUCE"
    good = RetirementStrategy().decide(full_fund(score, dq={"level": "good"}), _tech("BULLISH"))
    assert good.action == "SELL"


# --------------------------------------------------------------------------- #
#  La tolerancia vive en config                                                #
# --------------------------------------------------------------------------- #

def test_the_tolerance_is_one_step_and_zero_pins_the_ai_to_the_engine(monkeypatch):
    from tests.test_ai_path_equivalence_oracle import _fund as full_fund
    from tests.test_ai_path_equivalence_oracle import _llm, _tech

    assert STRATEGY.ai_ladder_step_tolerance == 1
    score = STRATEGY.hold_score + 1               # el motor da HOLD
    fund, tech = full_fund(score, dq={"level": "good"}), _tech("BULLISH")
    assert apply_safety_overlay(_llm("BUY", score), fund, tech).action == "BUY"
    monkeypatch.setattr(STRATEGY, "ai_ladder_step_tolerance", 0)
    assert apply_safety_overlay(_llm("BUY", score), fund, tech).action == "HOLD"
    assert apply_safety_overlay(_llm("SELL", score), fund, tech).action == "HOLD"


# --------------------------------------------------------------------------- #
#  El rótulo de los umbrales y la versión                                      #
# --------------------------------------------------------------------------- #

def test_the_threshold_note_reads_the_ladder_and_says_not_calibrated():
    from data.product_ux import signal_thresholds_note

    s = STRATEGY
    text = signal_thresholds_note()
    assert f"{s.strong_buy_score:.0f}/{s.buy_score:.0f}/{s.hold_score:.0f}/{s.reduce_score:.0f}" in text
    assert "ranking relativo, no calibrado" in text and "365 días" in text
    crypto = signal_thresholds_note(is_crypto=True)               # cripto lee su propia escalera
    assert crypto != text and "inf" not in crypto
    assert crypto.startswith("Umbrales de señal —/—/")            # sus peldaños de compra no se alcanzan


def test_the_stock_analysis_ficha_shows_the_note():
    tree = ast.parse((ROOT / "dashboard/views/2_Stock_Analysis.py").read_text(encoding="utf-8"))
    names = {n.func.id for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "signal_thresholds_note" in names


def test_the_signal_method_version_moves_and_the_engine_does_not():
    assert SIGNAL_METHOD_VERSION == "2026.10-senales2"
    assert ENGINE_VERSION == "2026.10-tier23"
