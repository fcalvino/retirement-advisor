"""COMMITTEE-PROMPTS (2026-10-18): lo que el bloque común le muestra a cada voz
coincide con lo que el motor sabe y decidió.

Auditoría del 2026-10-18 sobre prompts renderizados de TSM, BSBR, MSFT, O, YPF, KO,
0700.HK y SAP.DE:

- **D1.** Macro, Abogado del Diablo, PM, Coach y Dividendo veían ``total_score``
  (MSFT 68) mientras la matriz decidía con el ajustado (96,7): 103 de 131 tickers en
  otra banda, y el bloque de cola de viento les decía «bonus ya incluido en el score
  ajustado».
- **D3.** El P/FFO de un REIT, el múltiplo que el motor puntúa, sólo le llegaba al
  Fundamental; las demás voces juzgaban a O por su P/E de 40,6.
- **D4.** P/B, EV/EBITDA, PEG y FCF yield no tenían línea; un «no medible» por
  moneda llegaba como texto crudo en las alertas, y el del FCF dos veces.
- **D5.** El alcance de la verificación cruzada no es una alerta: va en «Calidad de
  datos». «Solo una fuente» sigue siendo alerta (decisión de producto).
- **D6.** Ninguna voz inclina su stance por instrucción: el disenso fuerte baja la
  confianza en la agregación (EO-5b, decisión del usuario 2026-10-18).
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from analysis.committee_prompts import (
    behavioral_coach_prompt,
    committee_context_block,
    devils_advocate_prompt,
    dividend_capital_prompt,
    macro_strategist_prompt,
    portfolio_manager_prompt,
)
from analysis.data_reconciliation import CROSS_CHECK_SCOPE_NOTE
from analysis.eval_cases import golden_cases
from config import COMMITTEE

SINGLE_SOURCE = "Solo una fuente de datos disponible — sin verificación cruzada."
# Textos literales del motor para TSM (2026-10-18): la alerta es la misma cadena que la nota.
PB_NOTE = (
    "P/B no medible: el del feed (78.65) no cierra con P/E × ROE (11.2) y los estados vienen "
    "en otra moneda que la cotización; un múltiplo sólo está definido si ambas patas "
    "comparten unidad."
)
EV_NOTE = (
    "EV/EBITDA no medible: el del feed (3.855) no cierra con el reconstruido desde P/E × ROE "
    "(21.2) y los estados vienen en otra moneda que la cotización; un múltiplo sólo está "
    "definido si ambas patas comparten unidad."
)
FCF_NOTE = (
    "FCF yield no medible: el free cash flow viene en TWD y el market cap en USD; un yield "
    "sólo está definido si ambas patas comparten moneda."
)

VOICES = {
    "macro": lambda f, t: macro_strategist_prompt(f, t, "macro de prueba"),
    "devil": devils_advocate_prompt,
    "pm": portfolio_manager_prompt,
    "coach": behavioral_coach_prompt,
    "dividend": dividend_capital_prompt,
}


def _fund(**overrides):
    case = golden_cases()[0]  # quality_compounder_buy (MSFT-like)
    fund, tech = copy.deepcopy(case.fund), case.tech
    for k, v in overrides.items():
        setattr(fund, k, v)
    return fund, tech


def _line(block: str, prefix: str) -> str:
    hits = [ln for ln in block.splitlines() if ln.startswith(prefix)]
    assert len(hits) == 1, (prefix, block)
    return hits[0]


# --------------------------------------------------------------------------- #
#  D1 — el score que usa la decisión                                           #
# --------------------------------------------------------------------------- #

def test_las_voces_ven_el_score_con_el_que_decide_el_motor():
    fund, tech = _fund(total_score=68.0, adjusted_score=96.7)
    line = _line(committee_context_block(fund, tech), "Score del motor")
    assert line.startswith("Score del motor (determinista): 96.7/100")
    assert "base sin ajustes: 68.0" in line


def test_con_la_decision_por_score_base_se_ve_el_base(monkeypatch):
    import analysis.committee_prompts as cp
    import analysis.strategy as strategy

    for mod, attr in ((strategy, "CFG"), (cp, "STRATEGY")):
        cfg = copy.copy(getattr(mod, attr))
        object.__setattr__(cfg, "use_adjusted_score_for_decision", False)
        monkeypatch.setattr(mod, attr, cfg)
    fund, tech = _fund(total_score=68.0, adjusted_score=96.7)
    line = _line(committee_context_block(fund, tech), "Score del motor")
    assert line == "Score del motor (determinista): 68.0/100"


def test_la_cola_de_viento_incluida_en_el_ajustado_viene_con_el_ajustado():
    """El bloque de cola de viento dice «ya incluido en el score ajustado»: el score de
    ese mismo prompt tiene que ser el ajustado, no el base que no lo incluye."""
    tailwind = SimpleNamespace(tailwind_score=4.0, bonus=3.2, durability_years=6,
                               last_reviewed="2026-06", explanation="capex en IA")
    fund, tech = _fund(total_score=68.0, adjusted_score=96.7,
                       tailwind_detail=tailwind, tailwind_classification="Moderate")
    for name, build in VOICES.items():
        prompt = build(fund, tech)
        assert "incluido en el score ajustado" in prompt, name
        assert "Score del motor (determinista): 96.7/100" in prompt, name


# --------------------------------------------------------------------------- #
#  D3 / D4 — la línea de valuación                                             #
# --------------------------------------------------------------------------- #

def test_las_voces_ven_los_multiplos_medidos():
    fund, tech = _fund(pb_ratio=11.4, ev_ebitda=22.3, peg_ratio=1.8, fcf_yield=2.6, notes={})
    line = _line(committee_context_block(fund, tech), "Valuación:")
    assert line == "Valuación: P/B: 11.4x | EV/EBITDA: 22.3x | PEG: 1.8 | FCF yield: 2.6%"


def test_un_reit_muestra_su_p_ffo_en_todas_las_voces():
    fund, tech = _fund(sector="Real Estate", industry="REIT - Retail", p_ffo=14.81,
                       pe_ratio=40.6, notes={})
    for name, build in VOICES.items():
        assert "P/FFO: 14.8x" in build(fund, tech), name


def test_un_no_reit_no_muestra_p_ffo():
    fund, tech = _fund(p_ffo=None, notes={})
    assert "P/FFO" not in committee_context_block(fund, tech)


def test_un_multiplo_no_medible_aparece_una_sola_vez_y_en_la_linea_de_valuacion():
    """TSM: las tres notas de moneda eran también alertas; la del FCF llegaba dos veces."""
    notes = {"pb_ratio_currency": PB_NOTE, "ev_ebitda_currency": EV_NOTE,
             "fcf_yield_currency": FCF_NOTE}
    fund, tech = _fund(
        notes=notes, pb_ratio=None, ev_ebitda=None, fcf_yield=None,
        warnings=[EV_NOTE, PB_NOTE, FCF_NOTE, SINGLE_SOURCE],
    )
    prompt = devils_advocate_prompt(fund, tech)
    block = committee_context_block(fund, tech)
    valuation = _line(block, "Valuación:")
    for label in ("P/B", "EV/EBITDA", "FCF yield"):
        assert f"{label}: no medible (" in valuation, label
        # Ni la nota larga en las alertas ni la línea vieja «Moneda de estados».
        assert f"{label} no medible" not in prompt, label
    assert "Moneda de estados" not in prompt
    assert _line(block, "Alertas del motor:") == "Alertas del motor: " + SINGLE_SOURCE


# --------------------------------------------------------------------------- #
#  D5 — el alcance de la verificación cruzada                                  #
# --------------------------------------------------------------------------- #

def test_el_alcance_de_la_verificacion_va_en_calidad_de_datos():
    fund, tech = _fund(warnings=["Current ratio low: 1.23", CROSS_CHECK_SCOPE_NOTE])
    block = committee_context_block(fund, tech)
    assert block.count(CROSS_CHECK_SCOPE_NOTE) == 1
    assert _line(block, "Calidad de datos:") == "Calidad de datos: " + CROSS_CHECK_SCOPE_NOTE
    assert _line(block, "Alertas del motor:") == "Alertas del motor: Current ratio low: 1.23"


def test_solo_una_fuente_sigue_siendo_alerta():
    fund, tech = _fund(warnings=[SINGLE_SOURCE])
    block = committee_context_block(fund, tech)
    assert _line(block, "Alertas del motor:") == "Alertas del motor: " + SINGLE_SOURCE
    assert "Calidad de datos" not in block


def test_sin_la_nota_no_hay_linea_de_calidad():
    fund, tech = _fund(warnings=[])
    block = committee_context_block(fund, tech)
    assert "Calidad de datos" not in block and "Alertas del motor" not in block


# --------------------------------------------------------------------------- #
#  D6 — ningún rol inclina su stance                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tilt", ["inclinarse a la cautela", "sesgo a HOLD"])
def test_ninguna_voz_del_comite_tiene_un_sesgo_de_stance(tilt):
    fund, tech = _fund()
    for name, build in VOICES.items():
        assert tilt not in build(fund, tech), name


def test_el_cambio_de_prompt_subio_la_version_del_cache():
    assert COMMITTEE.prompt_version == "2026-10-18a"


def test_cripto_no_pierde_una_alerta_de_moneda():
    """Sin línea de valuación (cripto), una nota de moneda sigue siendo alerta."""
    fund, tech = _fund(is_crypto=True, notes={"fcf_yield_currency": FCF_NOTE},
                       warnings=[FCF_NOTE])
    assert _line(committee_context_block(fund, tech), "Alertas del motor:") == (
        "Alertas del motor: " + FCF_NOTE
    )


def test_el_abogado_del_diablo_conserva_su_mandato():
    fund, tech = _fund()
    prompt = devils_advocate_prompt(fund, tech)
    assert "CONSTRUIR EL BEAR CASE" in prompt
    assert "núcleo del disenso del comité" in prompt
