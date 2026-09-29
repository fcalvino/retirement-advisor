"""#151 — el Comité avisa que el dictamen es frágil sólo cuando el lean está al borde.

Oráculo: el umbral más cercano se calcula acá a mano sobre la escalera de
``COMMITTEE`` (no con ``_lean_to_action``), y los casos reproducen los leans que
midió la corrida de estabilidad del 2026-09-29 (MSFT +0.43, BTC −0.45).
"""

from dataclasses import replace

import pytest

from analysis.committee import AgentOpinion, CommitteeVerdict, nearest_lean_threshold
from config import COMMITTEE
from dashboard import shared


def _verdict(lean, action, available=True):
    ops = [AgentOpinion("Analista Fundamental", action, "MEDIUM", ["a"], ["r"])] if available else []
    return CommitteeVerdict("X", action, "MEDIUM", [], [], ops, lean=lean)


def _by_hand(lean):
    ladder = [COMMITTEE.sell_lean, COMMITTEE.reduce_lean, COMMITTEE.buy_lean, COMMITTEE.strong_buy_lean]
    t = min(ladder, key=lambda x: abs(lean - x))
    return t, abs(lean - t)


@pytest.mark.parametrize("lean,across", [
    (0.43, "BUY"), (0.5, "HOLD"), (-0.447, "REDUCE"), (-0.5, "HOLD"),
    (-0.8, "HOLD"), (-1.4, "SELL"), (1.6, "BUY"), (0.1, "BUY"), (-2.0, "REDUCE"),
])
def test_nearest_threshold_matches_the_ladder(lean, across):
    threshold, got_across, distance = nearest_lean_threshold(lean)
    t, d = _by_hand(lean)
    assert threshold == t and distance == pytest.approx(d)
    assert got_across == across


def test_msft_near_buy_gets_the_note():
    note = shared.lean_near_threshold_note(_verdict(0.432, "HOLD"), "HOLD")
    assert "a 0.07 del umbral de BUY (+0.50)" in note
    assert "otra corrida podría dar BUY" in note
    assert f"{COMMITTEE.lean_run_to_run_stdev:.2f}" in note


def test_btc_near_reduce_gets_the_note_even_if_the_engine_capped():
    # downward crossings always matter: the overlay only lowers
    note = shared.lean_near_threshold_note(_verdict(-0.447, "HOLD"), "REDUCE")
    assert "umbral de REDUCE (-0.50)" in note


def test_upward_crossing_hidden_when_the_engine_already_capped_the_vote():
    assert shared.lean_near_threshold_note(_verdict(0.45, "HOLD"), "REDUCE") is None


def test_far_from_every_threshold_no_note():
    assert shared.lean_near_threshold_note(_verdict(-0.159, "HOLD"), "HOLD") is None
    assert shared.lean_near_threshold_note(_verdict(-0.836, "REDUCE"), "SELL") is None


def test_margin_is_read_from_config(monkeypatch):
    m = COMMITTEE.lean_near_threshold_margin
    assert shared.lean_near_threshold_note(_verdict(0.5 - 1.5 * m, "HOLD"), "HOLD") is None
    assert shared.lean_near_threshold_note(_verdict(0.5 - m / 2, "HOLD"), "HOLD") is not None
    import config
    monkeypatch.setattr(config, "COMMITTEE", replace(COMMITTEE, lean_near_threshold_margin=0.0))
    assert shared.lean_near_threshold_note(_verdict(0.49, "HOLD"), "HOLD") is None


def test_unavailable_verdict_no_note():
    assert shared.lean_near_threshold_note(_verdict(0.45, "HOLD", available=False)) is None
