"""AUDIT-UI-VERDAD (B) — un Backtesting negativo se pintaba de verde y un margen de 0 % volvía al del perfil.

1. ``6_Backtesting.py`` ponía ``delta_color="inverse"`` cuando el exceso era negativo: Streamlit pinta
   de verde un delta negativo con ``inverse``, así que un portafolio por debajo del benchmark salía en
   verde. Un exceso positivo ya salía verde y un negativo debe salir rojo.
2. El margen de seguridad que el inversor pide antes de comprar tiene ``min_value=0`` en Settings, pero
   ``profile_margin_pct`` hacía ``if override:`` y Settings ``int(_prefs.margin_pct or ...)``: un 0 %
   guardado se leía como «no elegido» y volvía al del perfil (Conservador: 20 %).

Sin red: el backtest guardado se arma a mano y el resultado se carga por el selector real de la página.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_eo1c_exigencia_perfil_oracle import _prefs, _settings

BACKTESTING = str(Path(__file__).resolve().parents[1] / "dashboard" / "views" / "6_Backtesting.py")


# --------------------------------------------------------------------------- #
#  1 — el color del retorno frente al benchmark                                 #
# --------------------------------------------------------------------------- #

def _backtest_page(monkeypatch, excess: float) -> AppTest:
    from analysis.backtesting import BacktestEngine, BacktestResult

    result = BacktestResult(
        run_date="2026-10-28", period_years=5, start_date="2021-10-28", end_date="2026-10-28",
        benchmark="SPY", top_n=10, universe_size=20,
        portfolio_cagr_pct=10.0 + excess, benchmark_cagr_pct=10.0, excess_return_pct=excess,
    )
    monkeypatch.setattr(BacktestEngine, "list_saved", staticmethod(lambda: [Path("bt_2026.json")]))
    monkeypatch.setattr(BacktestEngine, "load", staticmethod(lambda path: result))
    at = AppTest.from_file(BACKTESTING, default_timeout=60)
    at.session_state["universe"] = ["AAPL", "MSFT"]
    at.session_state["active_universe_key"] = "default"
    at.run()
    next(b for b in at.selectbox if b.label == "Cargar resultado guardado").select("bt_2026.json").run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def _cagr_metric(at: AppTest):
    return next(m for m in at.metric if m.label == "Portfolio CAGR")


def test_a_portfolio_below_its_benchmark_is_shown_red(monkeypatch):
    m = _cagr_metric(_backtest_page(monkeypatch, excess=-3.0))
    assert m.delta.startswith("-3.0%")
    assert m.proto.color == m.proto.MetricColor.RED


def test_a_portfolio_above_its_benchmark_is_shown_green(monkeypatch):
    m = _cagr_metric(_backtest_page(monkeypatch, excess=2.5))
    assert m.delta.startswith("+2.5%")
    assert m.proto.color == m.proto.MetricColor.GREEN


# --------------------------------------------------------------------------- #
#  2 — un margen de 0 % es una respuesta                                        #
# --------------------------------------------------------------------------- #

def test_a_zero_margin_overrides_the_profile_margin():
    from data.product_ux import profile_margin_pct

    assert profile_margin_pct("conservative", override=0.0) == 0.0     # Conservador pide 20 %
    assert profile_margin_pct("conservative", override=None) == 20.0   # sin override, el del perfil
    assert profile_margin_pct("conservative", override=12.0) == 12.0


def test_the_committee_postura_carries_a_zero_margin():
    from data.product_ux import committee_postura

    postura = committee_postura(_prefs("Conservador", margin_pct=0.0))
    assert postura["margin_pct"] == 0.0


def test_settings_shows_a_saved_zero_margin_not_the_profiles(tmp_path, monkeypatch):
    prefs = _prefs("Conservador", onboarded=True, age=36, risk_tolerance="conservadora", margin_pct=0.0)
    at = _settings(prefs, tmp_path, monkeypatch)
    assert at.number_input(key="settings_margin").value == 0


def test_a_zero_margin_chosen_in_settings_is_saved_and_read_back(tmp_path, monkeypatch):
    prefs = _prefs("Conservador", onboarded=True, age=36, risk_tolerance="conservadora")
    at = _settings(prefs, tmp_path, monkeypatch)
    at.number_input(key="settings_margin").set_value(0)
    at.button(key="settings_postura_save").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert at.session_state["user_prefs"].margin_pct == 0.0
    assert at.number_input(key="settings_margin").value == 0


@pytest.mark.parametrize("value", [None, 12.0])
def test_the_other_margins_keep_working(tmp_path, monkeypatch, value):
    prefs = _prefs("Conservador", onboarded=True, age=36, risk_tolerance="conservadora", margin_pct=value)
    at = _settings(prefs, tmp_path, monkeypatch)
    assert at.number_input(key="settings_margin").value == (20 if value is None else 12)


def test_a_zero_margin_survives_the_trip_to_disk(tmp_path, monkeypatch):
    from data import preferences as prefs_mod

    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "prefs.json")
    _prefs("Conservador", margin_pct=0.0).save()
    assert prefs_mod.UserPreferences.load().margin_pct == 0.0
