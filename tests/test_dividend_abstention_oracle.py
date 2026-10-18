"""Oráculo DIV-ABSTAIN: la voz de Dividendo que no se convoca se anota como abstención.

``_pays_dividend`` deja afuera a la voz de Dividendo en un cripto y en una acción sin
dividendo, pero ``CommitteeAnalyzer.analyze`` no lo anotaba en ``abstentions``, así
que ``committee_abstention_caption`` no tenía qué decir y el panel de cinco voces se
leía como completo. Pasó con NFLX (2026-10-18) y con BRK-B (2026-10-03).

Abstenerse no es fallar, igual que el Estratega Macro sin hechos (MACRO-SEED): el
dictamen sigue ``complete``, con quórum pleno, y el motivo dice cuál de las causas fue.

Independiente del código bajo prueba: los fondos salen del banco dorado y los roles
se leen de los prompts que el ``call_fn`` falso ve pasar.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from analysis.committee import CommitteeAnalyzer
from analysis.eval_cases import golden_cases
from dashboard.shared import committee_abstention_caption

DIVIDEND = "Analista de Dividendo"
DIVIDEND_ROLE_TITLE = "Analista de Dividendo y Asignación de Capital"
MACRO_BLOCK = "=== CONTEXTO MACRO RECIENTE ===\n- [2026-10-18] (FRED) Tasa: 4.0"


def _agent(stance: str) -> str:
    return json.dumps({"stance": stance, "confidence": "MEDIUM",
                       "key_points": ["punto"], "concerns": ["riesgo"]})


def _fundamental(action: str) -> str:
    return json.dumps({"action": action, "confidence": "HIGH", "rationale": ["ok"],
                       "risks": ["valuación"], "reasoning": "x" * 120,
                       "recommended_max_allocation": 5, "macro_factors": []})


def _run(fund, tech, seen: list):
    def call_fn(prompt: str) -> str:
        seen.append(prompt)
        if '"recommended_max_allocation"' in prompt:
            return _fundamental("BUY")
        return _agent("HOLD")

    # Con hechos macro el Macro vota: la única abstención posible es la de Dividendo.
    analyzer = CommitteeAnalyzer(call_fn=call_fn, use_cache=False,
                                 news_fn=lambda s: [], drawdowns_fn=lambda s: {},
                                 macro_fn=lambda f: MACRO_BLOCK)
    return analyzer.analyze(fund, tech)


def _case(symbol: str):
    case = next(c for c in golden_cases() if c.fund.symbol == symbol)
    return case.fund, case.tech


@pytest.mark.parametrize("dividend_yield", [None, 0.0])
def test_non_payer_equity_abstains_and_the_caption_names_it(dividend_yield):
    fund, tech = _case("MSFT")
    fund = dataclasses.replace(fund, dividend_yield=dividend_yield)
    seen: list = []
    verdict = _run(fund, tech, seen)

    assert not any(DIVIDEND_ROLE_TITLE in p for p in seen), "una voz abstenida no se paga"
    assert DIVIDEND not in {o.role for o in verdict.opinions}
    assert DIVIDEND in verdict.abstentions
    assert "dividendo" in verdict.abstentions[DIVIDEND].lower()
    assert "cripto" not in verdict.abstentions[DIVIDEND].lower()
    caption = committee_abstention_caption(verdict)
    assert DIVIDEND in caption and "se abstuvo" in caption
    # Abstenerse no es fallar: panel completo, quórum pleno, dictamen registrable.
    assert verdict.complete is True
    assert verdict.quorum_pct == 100.0
    assert verdict.to_decision(fund, tech).action


def test_an_unreadable_yield_is_no_data_not_a_non_payer():
    """«n/d» no prueba que no pague: el motivo no puede decir que no paga.

    Se prueba sobre la compuerta y no sobre ``analyze``: ``equity_decision_prompt``
    formatea el yield como número, así que un texto no llega entero al comité.
    """
    from analysis.committee import _dividend_abstain_reason

    fund, _tech = _case("MSFT")
    reason = _dividend_abstain_reason(dataclasses.replace(fund, dividend_yield="n/d"))
    assert reason is not None and "dividendo" in reason.lower()
    assert "no paga" not in reason.lower()
    assert reason == _dividend_abstain_reason(dataclasses.replace(fund, dividend_yield=None))
    # NaN tampoco es una medición: «nan %» se leería como un rendimiento bajo medido.
    assert _dividend_abstain_reason(dataclasses.replace(fund, dividend_yield=float("nan"))) == reason


def test_crypto_abstains_with_its_own_reason():
    fund, tech = _case("BTC-USD")
    assert fund.dividend_yield, "el caso tiene yield: la causa tiene que ser la clase de activo"
    verdict = _run(fund, tech, [])

    assert DIVIDEND in verdict.abstentions
    assert "cripto" in verdict.abstentions[DIVIDEND].lower()
    assert verdict.complete is True


def test_payer_convenes_the_voice_and_has_no_abstention():
    fund, tech = _case("KO")
    seen: list = []
    verdict = _run(fund, tech, seen)

    assert any(DIVIDEND_ROLE_TITLE in p for p in seen)
    assert DIVIDEND in {o.role for o in verdict.opinions}
    assert DIVIDEND not in verdict.abstentions
    assert committee_abstention_caption(verdict) == ""


def test_the_abstention_does_not_move_the_lean():
    """Anotarla no la convoca: el lean es el de las cinco voces que votaron."""
    fund, tech = _case("MSFT")
    payer = _run(fund, tech, [])
    non_payer = _run(dataclasses.replace(fund, dividend_yield=None), tech, [])
    # Fundamental BUY (1.0) y el resto HOLD: con o sin la voz de Dividendo (HOLD) el
    # lean sale de los pesos de config, y la abstención lo deja en 1.0 / 3.8.
    from config import COMMITTEE

    w = COMMITTEE.vote_weights
    five = sum(w[r] for r in ("Analista Fundamental", "Estratega Macro", "Abogado del Diablo",
                              "Portfolio Manager", "Behavioral Coach"))
    assert non_payer.lean == round(w["Analista Fundamental"] * 1.0 / five, 4)
    assert payer.lean == round(w["Analista Fundamental"] * 1.0 / (five + w[DIVIDEND]), 4)
