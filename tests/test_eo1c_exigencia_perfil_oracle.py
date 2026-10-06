"""Oráculo EO-1c: la Exigencia y el margen de seguridad son Postura del Perfil (ADR 0001).

Hasta EO-1c, «Mis Metas» juzgaba toda meta contra 80 % (`GOAL_CARD.success_target_pct`)
fuera cual fuera el perfil, y el margen de seguridad sólo existía como regla de la
Señal (10 %, igual para todos). Decisiones del usuario (2026-10-04):

* **Exigencia por perfil:** Conservador 90 %, Moderado 80 %, Agresivo 70 %, editable
  en Settings («Mi Perfil»): el valor del usuario gana sobre el del perfil.
* **Sin perfil elegido**, «Mis Metas» muestra la probabilidad sin juzgarla —ni
  KPI contra una Exigencia ni consejo de ahorro— y pide elegir perfil.
* **Margen del Perfil:** Conservador 20 %, Moderado 10 %, Agresivo 5 %, sólo en la
  ficha de Análisis. La Señal conserva `STRATEGY.min_margin_of_safety_pct` (10 %).

Los números esperados son los literales de esas decisiones, no los que lee el código.
"""

from __future__ import annotations

import pytest

# --------------------------------------------------------------------------- #
#  Los valores del Perfil y el override del usuario                           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("profile, expected", [
    ("conservative", 90.0), ("moderate", 80.0), ("aggressive", 70.0),
])
def test_each_profile_has_its_exigencia(profile, expected):
    from data.product_ux import profile_exigencia_pct

    assert profile_exigencia_pct(profile) == expected


@pytest.mark.parametrize("profile, expected", [
    ("conservative", 20.0), ("moderate", 10.0), ("aggressive", 5.0),
])
def test_each_profile_has_its_margin(profile, expected):
    from data.product_ux import profile_margin_pct

    assert profile_margin_pct(profile) == expected


def test_the_users_value_beats_the_profiles():
    from data.product_ux import profile_exigencia_pct, profile_margin_pct

    assert profile_exigencia_pct("aggressive", override=85.0) == 85.0
    assert profile_margin_pct("conservative", override=12.0) == 12.0


def test_without_a_profile_there_is_no_exigencia_nor_margin():
    from data.product_ux import profile_exigencia_pct, profile_margin_pct

    assert profile_exigencia_pct(None) is None
    assert profile_margin_pct(None) is None


def test_the_signal_keeps_its_own_fixed_margin():
    """Decisión del 2026-10-04 (opción a): el margen del Perfil no toca la Señal."""
    from config import STRATEGY

    assert STRATEGY.min_margin_of_safety_pct == 10.0


# --------------------------------------------------------------------------- #
#  «Mis Metas» juzga contra la Exigencia del perfil                            #
# --------------------------------------------------------------------------- #

GOAL = {
    "name": "Retiro", "goal_type": "retirement", "target_amount_today": 500_000.0,
    "horizon_years": 15, "priority": 1, "expected_inflation": 3.0,
    "annual_contribution": 0.0, "allocated_capital": 0.0, "notes": "",
}
PROB = 75.0   # entre la Exigencia de Agresivo (70) y la de Conservador (90)


def _goals_tab(prefs, monkeypatch):
    """Simula el plan con la página real y fija la probabilidad de la meta en 75 %."""
    from pathlib import Path
    from unittest.mock import patch

    from streamlit.testing.v1 import AppTest

    from dashboard import shared
    from tests.test_cash_flow_oracle import _flat_history

    real_sim = shared.cached_goal_simulation
    advice: list[dict] = []

    def _sim(**kwargs):
        result = real_sim(**kwargs)
        for gr in result.goal_results:
            gr.mc_result.prob_achieve_target_pct = PROB   # prob_success_pct lee esto
        return result

    def _advice(**kwargs):
        advice.append(kwargs)
        return 1_500.0

    monkeypatch.setattr(shared, "cached_goal_simulation", _sim)
    monkeypatch.setattr(shared, "cached_goal_savings_target", _advice)
    monkeypatch.setattr(shared, "get_user_prefs", lambda: prefs)
    monkeypatch.setattr(shared, "seed_session_defaults_from_profile", lambda *a, **k: None)
    # EO-4a: las simulaciones piden la ficha de cada ticker para saber su Clase;
    # sin red, ningún ticker tiene Clase y el MC proyecta con el ajuste histórico.
    monkeypatch.setattr("analysis.estimacion.classes_for", lambda syms: {s: None for s in syms})
    page = Path(__file__).resolve().parents[1] / "dashboard/views/7_Simulaciones.py"
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda *a, **k: _flat_history(0.06)):
        at = AppTest.from_file(str(page), default_timeout=180)
        at.session_state["universe"] = ["AAPL", "MSFT"]
        at.session_state["plan_n_sims"] = 1_000
        at.session_state["goals_list"] = [dict(GOAL)]
        at.run()
        at.button(key="run_goal_plan").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at, advice


def _kpi(at):
    [m] = [m for m in at.metric if m.label.startswith("Metas ")]
    return m.label, m.value


def _prefs(profile=None, **kw):
    from data.preferences import UserPreferences

    if profile is None:
        return UserPreferences(**kw)
    return UserPreferences(default_profile=profile, profile_chosen=True, **kw)


def test_an_aggressive_investor_meets_70_and_gets_no_savings_advice(monkeypatch):
    at, advice = _goals_tab(_prefs("Agresivo"), monkeypatch)
    assert _kpi(at) == ("Metas con >70% prob. éxito", "1/1")    # main: >80%, 0/1
    assert advice == []                                          # main: pide ahorro hasta 80


def test_a_conservative_investor_does_not_meet_90_and_is_told_what_to_save(monkeypatch):
    at, advice = _goals_tab(_prefs("Conservador"), monkeypatch)
    assert _kpi(at) == ("Metas con >90% prob. éxito", "0/1")
    assert [a["target_prob_pct"] for a in advice] == [90.0]      # main: 80
    assert any("al 90% de probabilidad" in (i.value or "") for i in at.info)


def test_the_users_exigencia_beats_the_profiles(monkeypatch):
    at, advice = _goals_tab(_prefs("Agresivo", exigencia_pct=85.0), monkeypatch)
    assert _kpi(at) == ("Metas con >85% prob. éxito", "0/1")
    assert [a["target_prob_pct"] for a in advice] == [85.0]


def test_without_a_profile_the_probability_is_shown_but_not_judged(monkeypatch):
    at, advice = _goals_tab(_prefs(), monkeypatch)
    assert advice == []                                          # main: consejo contra 80
    label, value = _kpi(at)
    assert "Exigencia" in label and value == "—"                 # main: «>80%», «0/1»
    assert any("Elegí tu perfil" in (i.value or "") for i in at.info)


# --------------------------------------------------------------------------- #
#  La ficha muestra el margen del perfil                                       #
# --------------------------------------------------------------------------- #

def _card(prefs, monkeypatch, tmp_path):
    """Ficha de un activo con 12 % de margen de seguridad (Graham 224 vs precio 200)."""
    from dataclasses import replace
    from pathlib import Path

    import pandas as pd
    from streamlit.testing.v1 import AppTest

    import portfolio.tracker as tracker_mod
    from analysis import track_record
    from analysis.eval_cases import golden_cases
    from analysis.strategy import RetirementStrategy
    from analysis.track_record import TrackRecordStore
    from dashboard import shared
    from portfolio.tracker import Portfolio

    case = golden_cases()[0]
    fund = replace(case.fund, symbol="AAPL", currency="USD", current_price=200.0,
                   graham_value=224.0, margin_of_safety_pct=12.0)
    decision = RetirementStrategy().decide(fund, case.tech)
    monkeypatch.setattr(shared, "cached_full_analysis", lambda *a, **k: (fund, case.tech, decision))
    monkeypatch.setattr(track_record, "track_record_store", TrackRecordStore(db_path=str(tmp_path / "tr.db")))
    monkeypatch.setattr(tracker_mod, "get_info", lambda s: {"currentPrice": 200.0, "currency": "USD"})
    monkeypatch.setattr(shared, "get_price_history", lambda *a, **k: pd.DataFrame())
    page = Path(__file__).resolve().parents[1] / "dashboard/views/2_Stock_Analysis.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.session_state["analysis_target"] = "AAPL"
    at.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
    at.session_state["user_prefs"] = prefs
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    lines = [c.value for c in at.caption if "margen" in (c.value or "").lower()
             and "perfil" in (c.value or "").lower()]
    assert len(lines) == 1, [c.value for c in at.caption]
    return lines[0]


def test_a_moderate_investor_reads_that_12_percent_is_enough(monkeypatch, tmp_path):
    line = _card(_prefs("Moderado"), monkeypatch, tmp_path)
    assert "10%" in line and "alcanza" in line                   # main: no había línea


def test_a_conservative_investor_reads_wait_for_a_pullback(monkeypatch, tmp_path):
    line = _card(_prefs("Conservador"), monkeypatch, tmp_path)
    assert "20%" in line and "esperá una baja" in line


def test_the_users_margin_beats_the_profiles_in_the_card(monkeypatch, tmp_path):
    line = _card(_prefs("Conservador", margin_pct=12.0), monkeypatch, tmp_path)
    assert "12%" in line and "alcanza" in line


def test_without_a_profile_the_card_asks_for_one(monkeypatch, tmp_path):
    line = _card(_prefs(), monkeypatch, tmp_path)
    assert "Elegí tu perfil" in line


# --------------------------------------------------------------------------- #
#  Settings: la Exigencia y el margen se editan                                #
# --------------------------------------------------------------------------- #

def _settings(prefs, tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dashboard import shared
    from data import preferences as prefs_mod

    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(shared, "usd_ars_quote", lambda *a, **k: None)   # sin red
    page = Path(__file__).resolve().parents[1] / "dashboard/views/9_Settings.py"
    at = AppTest.from_file(str(page), default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["universe"] = ["AAPL"]
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def test_settings_starts_on_the_profiles_values_and_saves_the_users(tmp_path, monkeypatch):
    prefs = _prefs("Agresivo", onboarded=True, age=36, risk_tolerance="agresiva")
    at = _settings(prefs, tmp_path, monkeypatch)
    assert at.number_input(key="settings_exigencia").value == 70     # main: no existía
    assert at.number_input(key="settings_margin").value == 5
    at.number_input(key="settings_exigencia").set_value(85)
    at.number_input(key="settings_margin").set_value(12)
    at.button(key="settings_postura_save").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    saved = at.session_state["user_prefs"]
    assert (saved.exigencia_pct, saved.margin_pct) == (85.0, 12.0)


def test_saving_the_profiles_own_value_keeps_following_the_profile(tmp_path, monkeypatch):
    """Guardar el mismo número que el perfil no fija un override: si mañana cambia de
    perfil, la Exigencia lo sigue."""
    prefs = _prefs("Agresivo", onboarded=True, age=36, risk_tolerance="agresiva")
    at = _settings(prefs, tmp_path, monkeypatch)
    at.button(key="settings_postura_save").click().run()
    saved = at.session_state["user_prefs"]
    assert (saved.exigencia_pct, saved.margin_pct) == (None, None)


def test_without_a_profile_settings_does_not_offer_a_postura(tmp_path, monkeypatch):
    at = _settings(_prefs(), tmp_path, monkeypatch)
    assert not [w for w in at.number_input if w.key == "settings_exigencia"]
