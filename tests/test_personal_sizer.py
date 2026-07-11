"""
Tests del motor de sizing del Libro Personal (``portfolio.personal_sizer``).

Todo determinístico vía ``enrich_fn`` mock — sin red, sin yfinance, sin Streamlit.
Cubren: cada acción soportada, gates de concentración, manejo de convicciones,
presencia de la tesis de "libro personal vs fondo", y edge cases.
"""

from __future__ import annotations

import pytest

from config import PERSONAL_BOOK
from portfolio.personal_sizer import (
    ACUMULAR_AGRESIVO,
    ACUMULAR_MODERADO,
    AGREGAR_EN_DEBILIDAD,
    HOLDEAR,
    TRIM_PARCIAL,
    VENDER_PARTE,
    VENDER_TODO,
    PersonalBookAnalysis,
    SizingRecommendation,
    analyze_personal_book,
)

# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #


def _pos(symbol: str, weight: float, market_value: float = 10_000.0) -> dict:
    return {
        "symbol": symbol,
        "shares": 10.0,
        "avg_cost": 100.0,
        "current_price": market_value / 10.0,
        "market_value": market_value,
        "weight_pct": weight,
        "sector": "Technology",
        "purchase_date": "2025-01-01",
    }


def _view(
    score: float = 78.0,
    moat: str = "Wide",
    tailwind: str = "Moderate",
    has_mos: bool = False,
    mos_pct: float | None = None,
    dq: str = "good",
    rsi: float | None = 55.0,
    above_sma200: bool = True,
    p52: float = -3.0,
) -> dict:
    return {
        "adjusted_score": score,
        "moat_classification": moat,
        "tailwind_classification": tailwind,
        "has_margin_of_safety": has_mos,
        "margin_of_safety_pct": mos_pct,
        "data_quality_level": dq,
        "rsi_weekly": rsi,
        "above_sma200": above_sma200,
        "price_vs_52w_high_pct": p52,
    }


def _enricher(mapping: dict) -> callable:
    return lambda sym: mapping[sym]


def _rec_for(analysis: PersonalBookAnalysis, symbol: str) -> SizingRecommendation:
    return next(r for r in analysis.recommendations if r.symbol == symbol)


# ------------------------------------------------------------------ #
#  1. Libro de 2 posiciones con datos buenos → recs sensatas         #
# ------------------------------------------------------------------ #


def test_two_position_book_produces_sensible_recs():
    positions = {"AAA": _pos("AAA", 14.0), "BBB": _pos("BBB", 9.0)}
    enr = _enricher({"AAA": _view(), "BBB": _view(score=80, tailwind="Strong")})
    a = analyze_personal_book(positions, {"AAA": "HIGH", "BBB": "HIGH"}, enrich_fn=enr)

    assert a.num_positions == 2
    assert len(a.recommendations) == 2
    assert a.overall_summary
    # cada rec tiene acción válida y tesis de concentración no vacía
    for r in a.recommendations:
        assert r.action
        assert r.concentration_thesis
        assert r.justification_bullets


# ------------------------------------------------------------------ #
#  2. Ganador >25% con tesis intacta + HIGH → TRIM_PARCIAL           #
# ------------------------------------------------------------------ #


def test_winner_over_threshold_high_conviction_trims():
    positions = {"WIN": _pos("WIN", 27.0), "OTH": _pos("OTH", 6.0)}
    enr = _enricher({
        "WIN": _view(score=81, moat="Wide", tailwind="Strong"),
        "OTH": _view(score=70),
    })
    a = analyze_personal_book(positions, {"WIN": "HIGH", "OTH": "MEDIUM"}, enrich_fn=enr)
    rec = _rec_for(a, "WIN")
    assert rec.action == TRIM_PARCIAL
    assert rec.suggested_target_weight_pct is not None
    # debe quedar claro que es re-allocación, no salida de tesis
    assert "no es salida de tesis" in rec.suggested_action_detail.lower()


# ------------------------------------------------------------------ #
#  3. Alta calidad + bajo peso + HIGH → ACUMULAR_AGRESIVO + tesis    #
# ------------------------------------------------------------------ #


def test_core_low_weight_high_conviction_accumulates_aggressively():
    positions = {"CORE": _pos("CORE", 7.0)}
    enr = _enricher({"CORE": _view(score=79, moat="Wide", tailwind="Strong")})
    a = analyze_personal_book(positions, {"CORE": "HIGH"}, enrich_fn=enr)
    rec = _rec_for(a, "CORE")
    assert rec.action == ACUMULAR_AGRESIVO
    assert rec.suggested_target_weight_pct is not None
    assert rec.suggested_target_weight_pct > 7.0
    # tesis de concentración debe mencionar la ventaja personal vs fondo
    thesis = rec.concentration_thesis.lower()
    assert "a diferencia de un fondo" in thesis
    assert "libro personal" in thesis or "lps" in thesis


# ------------------------------------------------------------------ #
#  4. Calidad marginal + HIGH → no permite concentración extrema     #
# ------------------------------------------------------------------ #


def test_marginal_quality_high_conviction_does_not_allow_extreme_concentration():
    positions = {"MID": _pos("MID", 9.0)}
    # score 62 (debajo de core 72), narrow moat, neutral tailwind
    enr = _enricher({"MID": _view(score=62, moat="Narrow", tailwind="Neutral", rsi=55)})
    a = analyze_personal_book(positions, {"MID": "HIGH"}, enrich_fn=enr)
    rec = _rec_for(a, "MID")
    # nunca acumular agresivo sin gates de core
    assert rec.action != ACUMULAR_AGRESIVO
    assert rec.action in (ACUMULAR_MODERADO, HOLDEAR, AGREGAR_EN_DEBILIDAD)
    # debe avisar que faltan gates objetivos ("apuesta" vs "edge documentado")
    joined = " ".join(rec.justification_bullets).lower()
    assert "apuesta" in joined or "edge" in joined


# ------------------------------------------------------------------ #
#  5. Data quality poor → sesga conservador (no acumular agresivo)   #
# ------------------------------------------------------------------ #


def test_poor_data_quality_biases_conservative():
    positions = {"POOR": _pos("POOR", 8.0)}
    enr = _enricher({"POOR": _view(score=80, moat="Wide", tailwind="Strong", dq="poor")})
    a = analyze_personal_book(positions, {"POOR": "HIGH"}, enrich_fn=enr)
    rec = _rec_for(a, "POOR")
    assert rec.action != ACUMULAR_AGRESIVO
    assert any("calidad de datos" in n.lower() for n in rec.risk_notes)


# ------------------------------------------------------------------ #
#  6. Tesis rota (score bajo / moat None) → VENDER                   #
# ------------------------------------------------------------------ #


def test_broken_thesis_sells():
    positions = {"BAD": _pos("BAD", 22.0)}
    enr = _enricher({"BAD": _view(score=35, moat="None", tailwind="Headwind")})
    a = analyze_personal_book(positions, {"BAD": "HIGH"}, enrich_fn=enr)
    rec = _rec_for(a, "BAD")
    assert rec.action in (VENDER_TODO, VENDER_PARTE)
    # debe recordar impuestos en cualquier venta
    assert any("impuesto" in n.lower() for n in rec.risk_notes)


# ------------------------------------------------------------------ #
#  7. Sobre-concentración riesgosa (38%, baja calidad) → vender/trim #
# ------------------------------------------------------------------ #


def test_risky_over_concentration_reduces():
    positions = {"BIG": _pos("BIG", 38.0)}
    enr = _enricher({"BIG": _view(score=55, moat="Minimal", tailwind="Neutral")})
    a = analyze_personal_book(positions, {"BIG": "HIGH"}, enrich_fn=enr)
    rec = _rec_for(a, "BIG")
    assert rec.action in (VENDER_PARTE, TRIM_PARCIAL, VENDER_TODO)
    # nota de riesgo de concentración por peso alto
    assert any("libro completo" in n.lower() for n in rec.risk_notes)


# ------------------------------------------------------------------ #
#  8. Hard ceiling: > max_practical → reduce sí o sí                 #
# ------------------------------------------------------------------ #


def test_hard_ceiling_forces_reduction_even_with_quality():
    over = PERSONAL_BOOK.max_practical_concentration_single_name + 5
    positions = {"MAX": _pos("MAX", over)}
    enr = _enricher({"MAX": _view(score=85, moat="Wide", tailwind="Strong")})
    a = analyze_personal_book(positions, {"MAX": "HIGH"}, enrich_fn=enr)
    rec = _rec_for(a, "MAX")
    assert rec.action in (VENDER_PARTE, TRIM_PARCIAL)


# ------------------------------------------------------------------ #
#  9. Add on weakness: core con RSI bajo / pullback                 #
# ------------------------------------------------------------------ #


def test_core_in_weakness_suggests_add_on_weakness():
    # peso entre aggressive y trim threshold, core, con debilidad técnica
    w = (PERSONAL_BOOK.aggressive_accumulate_weight_pct + PERSONAL_BOOK.trim_concentration_threshold_pct) / 2
    positions = {"DIP": _pos("DIP", w)}
    enr = _enricher({"DIP": _view(score=80, moat="Wide", tailwind="Strong", rsi=32, p52=-15)})
    a = analyze_personal_book(positions, {"DIP": "HIGH"}, enrich_fn=enr)
    rec = _rec_for(a, "DIP")
    assert rec.action == AGREGAR_EN_DEBILIDAD


# ------------------------------------------------------------------ #
#  10. Libro vacío → manejo gracioso                                 #
# ------------------------------------------------------------------ #


def test_empty_book_handled_gracefully():
    a = analyze_personal_book({}, {}, enrich_fn=lambda s: _view())
    assert a.num_positions == 0
    assert a.recommendations == []
    assert "no tiene posiciones" in a.overall_summary.lower()
    assert "vacío" in a.concentration_risk_note.lower()
    assert a.concentration_justification_overall  # sigue explicando la filosofía


# ------------------------------------------------------------------ #
#  11. Convicción faltante → default config (MEDIUM)                 #
# ------------------------------------------------------------------ #


def test_missing_conviction_defaults_to_config():
    positions = {"NOCONV": _pos("NOCONV", 8.0)}
    enr = _enricher({"NOCONV": _view(score=78, moat="Wide", tailwind="Strong")})
    a = analyze_personal_book(positions, {}, enrich_fn=enr)
    rec = _rec_for(a, "NOCONV")
    assert rec.conviction_used == PERSONAL_BOOK.default_conviction
    # sin HIGH no debe acumular agresivo
    assert rec.action != ACUMULAR_AGRESIVO


# ------------------------------------------------------------------ #
#  12. Weight derivado de market_value cuando falta weight_pct       #
# ------------------------------------------------------------------ #


def test_weight_derived_from_market_value_when_missing():
    p1 = _pos("X", 0.0, market_value=30_000.0)
    p2 = _pos("Y", 0.0, market_value=10_000.0)
    del p1["weight_pct"]
    del p2["weight_pct"]
    enr = _enricher({"X": _view(), "Y": _view()})
    a = analyze_personal_book({"X": p1, "Y": p2}, {"X": "MEDIUM", "Y": "MEDIUM"}, enrich_fn=enr)
    rec_x = _rec_for(a, "X")
    assert rec_x.current_weight_pct == pytest.approx(75.0, abs=0.5)


# ------------------------------------------------------------------ #
#  13. Convicción inflada en todo el libro → nota en summary         #
# ------------------------------------------------------------------ #


def test_inflated_conviction_flagged_in_summary():
    positions = {f"T{i}": _pos(f"T{i}", 10.0) for i in range(5)}
    enr = _enricher({f"T{i}": _view(score=55, moat="Narrow", tailwind="Neutral") for i in range(5)})
    convs = {f"T{i}": "HIGH" for i in range(5)}
    a = analyze_personal_book(positions, convs, enrich_fn=enr)
    assert "sesgo de convicción inflada" in a.overall_summary.lower()


# ------------------------------------------------------------------ #
#  14. enrich_fn que falla → degrada a poor sin crashear             #
# ------------------------------------------------------------------ #


def test_enrich_failure_degrades_gracefully():
    def boom(sym):
        raise RuntimeError("network down")

    positions = {"NET": _pos("NET", 12.0)}
    a = analyze_personal_book(positions, {"NET": "HIGH"}, enrich_fn=boom)
    rec = _rec_for(a, "NET")
    assert rec.data_quality_level == "poor"
    assert rec.action  # produjo algo válido


# ------------------------------------------------------------------ #
#  15. Serialización a dict (export JSON)                            #
# ------------------------------------------------------------------ #


def test_analysis_serializes_to_dict():
    positions = {"S": _pos("S", 10.0)}
    enr = _enricher({"S": _view()})
    a = analyze_personal_book(positions, {"S": "HIGH"}, enrich_fn=enr)
    d = a.to_dict()
    assert isinstance(d, dict)
    assert d["recommendations"]
    assert "action_label" in d["recommendations"][0]
    import json
    json.dumps(d)  # no debe lanzar
