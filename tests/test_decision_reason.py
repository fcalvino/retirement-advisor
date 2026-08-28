"""Why a signal says what it says (audit item 04).

The Screener put a score and an action side by side and let them contradict each
other in silence. Measured on US Quality (2026-08-17):

    ADBE 95.7/100 → HOLD      ACN 91.8/100 → HOLD      CRM 84.7/100 → HOLD

The engine writes the reconciling sentence on every decision — "los fundamentales
dan para comprar pero no hay tendencia alcista confirmada", "STRONG BUY capado a
BUY por data quality partial" — and the row builder discarded it. Seeing 95.7 next
to HOLD with no explanation teaches the user to distrust the score.

`rationale` is a descriptive list whose order is an implementation detail, so the
fix is not "show rationale[0]": it is `decisive_reason`, set explicitly at each of
the eight places where the engine blocks or downgrades an action.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.strategy import Decision
from data.product_ux import decision_explanation

ROOT = Path(__file__).resolve().parents[1]
SCREENER = (ROOT / "dashboard" / "pages" / "1_Screener.py").read_text(encoding="utf-8")
SHARED = (ROOT / "dashboard" / "shared.py").read_text(encoding="utf-8")
STRATEGY = (ROOT / "analysis" / "strategy.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  The engine records the decisive reason                                     #
# --------------------------------------------------------------------------- #


def test_decision_carries_a_decisive_reason_field():
    d = Decision(symbol="X")
    assert d.decisive_reason == ""


def test_every_downgrade_site_sets_it():
    """Eight places change the action after the score; each must say why.

    Counting them in the source is crude but it is the property that matters: a
    new downgrade branch that forgets to set `decisive_reason` reintroduces
    exactly the silent contradiction this item is about.
    """
    # Blocks (rule path + AI safety overlay, equity and crypto) + matrix
    # downgrades + technical gate + crypto vol cap + the two data-quality
    # demotions. The overlay sites were missed on the first pass and only showed
    # up in the live table, as MA → AVOID with an unexplained cell.
    assert STRATEGY.count("decision.decisive_reason") >= 10


def test_data_quality_demotion_is_the_reason_the_user_sees():
    """The most common downgrade of all — it removed the whole STRONG BUY tier."""
    from analysis.strategy import apply_data_quality_policy

    d = Decision(symbol="MSFT", action="STRONG BUY", confidence="HIGH")
    fund = SimpleNamespace(data_quality={"level": "partial", "missing_fields": ["roe"]})
    apply_data_quality_policy(d, fund)

    assert d.action == "BUY"
    assert "STRONG BUY capado a BUY" in d.decisive_reason
    assert decision_explanation(d)["is_downgrade"] is True


def test_poor_quality_demotion_to_hold():
    from analysis.strategy import apply_data_quality_policy

    d = Decision(symbol="X", action="BUY", confidence="HIGH")
    fund = SimpleNamespace(data_quality={"level": "poor", "missing_fields": []})
    apply_data_quality_policy(d, fund)

    assert d.action == "HOLD"
    assert "degradado a HOLD" in d.decisive_reason
    assert d.confidence == "LOW"


def test_a_clean_decision_has_no_decisive_reason():
    """Nothing overrode the score, so there is nothing to reconcile."""
    from analysis.strategy import apply_data_quality_policy

    d = Decision(symbol="X", action="BUY", confidence="HIGH")
    apply_data_quality_policy(d, SimpleNamespace(data_quality={"level": "good"}))
    assert d.decisive_reason == ""
    assert decision_explanation(d)["is_downgrade"] is False


# --------------------------------------------------------------------------- #
#  The presentation helper                                                    #
# --------------------------------------------------------------------------- #


def test_headline_prefers_the_decisive_reason_over_the_rationale_list():
    """rationale ordering is an implementation detail; decisive_reason is not."""
    d = Decision(symbol="ADBE", action="HOLD")
    d.rationale = ["ROE alto", "Margen estable"]
    d.decisive_reason = "No hay tendencia alcista confirmada — mantener"

    out = decision_explanation(d)
    assert out["headline"] == "No hay tendencia alcista confirmada — mantener"
    assert out["why"] == ["ROE alto", "Margen estable"]


def test_headline_never_quotes_a_positive_fact_to_explain_a_cautious_action():
    """The defect found in the live app, one iteration into this item.

    PG came out HOLD with the cell reading "ROE de 30,3 % y moat Wide sustentan
    rentabilidad estructural" — a *positive* line lifted from `rationale`. That is
    the same score-vs-signal contradiction the item exists to remove, just with
    more words. With nothing overriding the score, the honest answer is the band.
    """
    d = Decision(symbol="PG", action="HOLD", fundamental_score=62.3)
    d.rationale = ["ROE de 30.3% y moat Wide sustentan rentabilidad estructural"]

    out = decision_explanation(d)
    assert "ROE" not in out["headline"]
    assert "62/100" in out["headline"]
    assert "no alcanza para comprar" in out["headline"]
    # The descriptive line still reaches the detail panel.
    assert out["why"] == ["ROE de 30.3% y moat Wide sustentan rentabilidad estructural"]


def test_score_band_phrasing_survives_a_missing_score():
    out = decision_explanation(Decision(symbol="X", action="HOLD"))
    assert out["headline"].startswith("El score")
    assert "None" not in out["headline"]


@pytest.mark.parametrize("action,fragment", [
    ("STRONG BUY", "compra fuerte"), ("BUY", "zona de compra"),
    ("HOLD", "no alcanza"), ("REDUCE", "deterioro"), ("SELL", "zona de venta"),
])
def test_each_action_gets_a_band_phrase_that_matches_it(action, fragment):
    out = decision_explanation(Decision(symbol="X", action=action, fundamental_score=70.0))
    assert fragment in out["headline"]
    assert "70/100" in out["headline"]


def test_headline_is_never_empty():
    """An empty cell reads as 'no reason', not as 'follows from the score'."""
    for action in ("STRONG BUY", "BUY", "HOLD", "SELL", "REDUCE", "AVOID", ""):
        out = decision_explanation(Decision(symbol="X", action=action))
        assert out["headline"], action
        assert out["headline"].strip() == out["headline"]


def test_long_headlines_are_truncated_for_the_cell_but_kept_whole():
    long = "x" * 200
    d = Decision(symbol="X", action="HOLD")
    d.decisive_reason = long

    out = decision_explanation(d, max_headline=40)
    assert len(out["headline"]) <= 40
    assert out["headline"].endswith("…")
    assert out["full_headline"] == long        # the panel shows all of it


def test_blank_and_whitespace_entries_are_dropped():
    d = Decision(symbol="X", action="HOLD")
    d.rationale = ["  ", "", "real"]
    d.risks = ["", "  riesgo real  "]
    out = decision_explanation(d)
    assert out["why"] == ["real"]
    assert out["risks"] == ["riesgo real"]


def test_risks_and_confidence_travel_with_the_explanation():
    d = Decision(symbol="X", action="HOLD", confidence="LOW")
    d.risks = ["Calidad de datos partial: faltan roe, roic"]
    out = decision_explanation(d)
    assert out["confidence"] == "LOW"
    assert out["risks"] == ["Calidad de datos partial: faltan roe, roic"]


def test_blocked_decisions_are_flagged():
    d = Decision(symbol="X", action="AVOID")
    d.blocked = True
    d.block_reason = "Deuda insostenible"
    d.decisive_reason = "Bloqueado: Deuda insostenible"
    out = decision_explanation(d)
    assert out["blocked"] is True
    assert out["headline"].startswith("Bloqueado")


def test_helper_tolerates_a_non_decision_object():
    """Rows can come from a stored run written by an older version."""
    out = decision_explanation(SimpleNamespace(action="HOLD"))
    assert out["headline"]
    assert out["why"] == [] and out["risks"] == []


# --------------------------------------------------------------------------- #
#  It reaches the page                                                        #
# --------------------------------------------------------------------------- #


def test_row_builder_stops_discarding_the_reasoning():
    assert "decision_explanation(decision)" in SHARED
    for key in ('"Motivo"', '"Conf."', '"_why"', '"_risks"', '"_why_headline"'):
        assert key in SHARED, key


def test_motivo_sits_next_to_the_signal_it_explains():
    """The contradiction is between neighbouring cells; the reason belongs there."""
    for marker in ("_short_cols = [", "_all_cols = ["):
        start = SCREENER.index(marker)
        block = SCREENER[start : SCREENER.index("]", SCREENER.index('"Datos",', start))]
        assert '"Motivo"' in block, marker
        assert block.index('"Motivo"') > block.index('"Signal"'), marker
        assert block.index('"Motivo"') < block.index('"Adj. Score"'), marker


def test_selecting_a_row_shows_the_full_reasoning():
    assert "def render_decision_detail(" in SHARED
    assert "render_decision_detail(df, event)" in SHARED
    assert "Razonamiento" in SHARED
    assert "Riesgos anotados" in SHARED


def test_both_new_columns_are_specced():
    from data.product_ux import SCREENER_COLUMN_SPECS

    for col in ("Motivo", "Conf."):
        assert col in SCREENER_COLUMN_SPECS
        assert SCREENER_COLUMN_SPECS[col]["help"]
