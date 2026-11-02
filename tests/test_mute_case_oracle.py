"""AUDIT-COACH-SILENCIO — silenciar un símbolo no depende de las mayúsculas.

El formulario de la pestaña Silenciados guarda el ticker con ``.strip().upper()``; el coach de cartera avisa con
el símbolo ``COACH:<nombre del plan>``, que conserva las mayúsculas del plan. ``is_muted`` comparaba con
distinción de mayúsculas, así que silenciar «Retiro 2045» (guardado como ``COACH:RETIRO 2045``) no tenía
efecto y el aviso seguía llegando. Reproducido con un ``AlertStore`` real antes del arreglo.
"""

from __future__ import annotations

import datetime as dt

import pytest

import alerts.store as store_mod
from alerts.engine import AlertEngine
from alerts.store import AlertStore, AlertType
from config import ALERTS

COACH = AlertType.MARKET_DROP_COACH.value


@pytest.fixture
def store(tmp_path):
    return AlertStore(db_path=tmp_path / "alerts.db")


def test_a_mute_saved_in_upper_case_silences_the_coach_of_a_mixed_case_plan(store):
    store.add_mute(symbol="COACH:RETIRO 2045", alert_type=COACH)         # what the form stores
    assert store.is_muted("COACH:Retiro 2045", COACH)                    # before: False


def test_the_match_ignores_case_in_both_directions(store):
    store.add_mute(symbol="coach:retiro 2045", alert_type="*")           # written by hand / an older version
    assert store.is_muted("COACH:RETIRO 2045", COACH)
    assert store.is_muted("Coach:Retiro 2045", COACH)


def test_a_different_symbol_is_still_not_muted(store):
    store.add_mute(symbol="AAPL", alert_type="*")
    assert store.is_muted("aapl", "signal_change")
    assert not store.is_muted("AAPLX", "signal_change")
    assert not store.is_muted("COACH:AAPL", COACH)


def test_the_wildcard_and_the_alert_type_keep_working(store):
    store.add_mute(symbol="*", alert_type=COACH)
    assert store.is_muted("COACH:Cualquiera", COACH)
    assert not store.is_muted("COACH:Cualquiera", "signal_change")


def test_an_expired_mute_does_not_silence_whatever_the_case(store, monkeypatch):
    start = dt.datetime(2026, 1, 1, 8, 0)
    monkeypatch.setattr(store_mod, "utc_now", lambda: start)
    store.add_mute(symbol="COACH:RETIRO 2045", alert_type=COACH, days=7)
    monkeypatch.setattr(store_mod, "utc_now", lambda: start + dt.timedelta(days=8))
    assert not store.is_muted("COACH:Retiro 2045", COACH)


def test_the_engine_does_not_announce_a_muted_plan_named_in_mixed_case(store, monkeypatch):
    """End to end: the form's mute and the coach's own symbol, through the real engine."""
    monkeypatch.setattr(ALERTS, "ai_explanations_enabled", False)
    engine = AlertEngine(store=store)
    store.add_mute(symbol="COACH:RETIRO 2045", alert_type=COACH)
    alert = engine.check_market_drop_coach(
        portfolio_return_pct=-12.0, plan_name="Retiro 2045", plan_prob_target_pct=65.0, basis="cost"
    )
    assert alert is None                                                  # before: an alert
