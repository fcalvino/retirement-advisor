"""AUDIT-ALERTAS-DESPACHO — las alertas del plan llegan al canal, y la severidad se configura.

Tres defectos de la misma familia (el producto promete algo que el motor no hace):

1. ``AlertEngine.run`` despacha un resumen, pero ``check_sorr``, ``check_goal_risk``,
   ``check_plan_health_degradation`` y ``check_market_drop_coach`` sólo registraban
   (``_fire``) y ponían el cooldown: el scheduler logueaba «alert fired» y nada salía
   por email ni Telegram. Una alerta SORR CRÍTICA quedaba en la base y nadie se enteraba.
2. ``AlertConfig.min_severity_{conservador,moderado,agresivo}`` no los leía nadie:
   ``_min_severity_for_profile`` hardcodeaba «conservador → WARNING».
3. ``ALERT_AI_MIN_SEVERITY=WARNING`` (mayúsculas) lanzaba ``ValueError`` desde
   ``AlertSeverity(...)`` y abortaba ``AlertEngine.run`` entero.

El oráculo de (1) corre el job real del scheduler sobre un ``AlertEngine`` real con un
store en memoria y un notificador que sólo graba; no mira cómo se llama a las funciones
sino qué texto llegaría al canal.
"""

from __future__ import annotations

import sys
import types

import pytest

import scripts.run_scheduler as sched
from alerts.engine import AlertEngine, _get_ai_explanation, _min_severity_for_profile
from alerts.store import AlertSeverity
from config import ALERTS
from tests.test_alert_engine import FakeAlertStore


class _RecordingNotifier:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, message: str, title: str = "") -> None:
        self.sent.append((title, message))


class _Plan:
    id = "retiro-2045"
    name = "Retiro 2045"
    refreshed_metrics = None

    def __init__(self, mc_summary):
        self.mc_summary = mc_summary

    def target_weights(self):
        return {"AAPL": 100.0}


@pytest.fixture
def channel(monkeypatch):
    """Un AlertEngine real, un store en memoria y un canal que graba."""
    notifier = _RecordingNotifier()
    engine = AlertEngine(store=FakeAlertStore())
    engine._notifier = notifier
    monkeypatch.setattr(ALERTS, "alerts_enabled", True)
    monkeypatch.setattr(ALERTS, "telegram_enabled", True)
    monkeypatch.setattr(ALERTS, "ai_explanations_enabled", False)
    monkeypatch.setattr(sched, "AlertEngine", lambda: engine)
    monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [])  # sin tickers: sólo el plan
    return notifier, engine


@pytest.fixture
def active_plan(monkeypatch):
    mod = types.ModuleType("data.plan_context")
    mod.get_active_plan = lambda: None
    mod.record_plan_health = lambda *a, **k: None
    mod.get_plan_health_history = lambda pid: []
    mod.compute_longitudinal_drift = lambda hist: {}
    mod.plan_price_lookup = lambda sym: 100.0
    monkeypatch.setitem(sys.modules, "data.plan_context", mod)
    return mod


# --------------------------------------------------------------------------- #
#  1 — despacho                                                               #
# --------------------------------------------------------------------------- #

def test_a_sorr_alert_from_the_plan_reaches_the_channel(channel, active_plan, monkeypatch):
    notifier, engine = channel
    active_plan.get_active_plan = lambda: _Plan(
        {"sorr_early_drawdown_pct": 45.0, "horizon_years": 30, "initial_value": 250_000.0}
    )
    # job_alert_check sale temprano si el screener no devuelve nada; el plan se evalúa igual.
    monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [{"symbol": "AAPL"}])
    sched.job_alert_check()

    assert [m for _t, m in notifier.sent if "SORR" in m], "la alerta SORR no salió por el canal"
    assert len(engine._store.recorded) == 1       # se registró una sola vez, no por canal


def test_a_goal_risk_alert_reaches_the_channel(channel, active_plan, monkeypatch):
    notifier, engine = channel
    active_plan.get_active_plan = lambda: _Plan({"prob_target_pct": 50.0, "horizon_years": 25})
    engine._store.save_snapshot("GOAL:Retiro 2045", 80.0, "GOAL", "")     # corrida previa
    monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [{"symbol": "AAPL"}])
    sched.job_alert_check()
    assert [m for _t, m in notifier.sent if "Meta en riesgo" in m]


def test_nothing_is_sent_when_no_plan_alert_fires(channel, active_plan, monkeypatch):
    notifier, _engine = channel
    active_plan.get_active_plan = lambda: _Plan({"sorr_early_drawdown_pct": 5.0})
    monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [{"symbol": "AAPL"}])
    sched.job_alert_check()
    assert notifier.sent == []


def test_the_master_switch_silences_plan_alerts_too(channel, active_plan, monkeypatch):
    """``ALERTS.alerts_enabled=False`` apaga todo canal: antes sólo apagaba ``run``."""
    notifier, _engine = channel
    monkeypatch.setattr(ALERTS, "alerts_enabled", False)
    active_plan.get_active_plan = lambda: _Plan({"sorr_early_drawdown_pct": 45.0})
    monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [{"symbol": "AAPL"}])
    sched.job_alert_check()
    assert notifier.sent == []


def test_a_failing_goal_check_does_not_lose_the_sorr_alert(channel, active_plan, monkeypatch):
    """El SORR ya quedó registrado y con cooldown de 14 días: si no sale ahora, no sale nunca."""
    notifier, engine = channel
    active_plan.get_active_plan = lambda: _Plan(
        {"sorr_early_drawdown_pct": 45.0, "prob_target_pct": 50.0, "horizon_years": 30}
    )
    real_get = engine._store.get_snapshot

    def flaky(symbol):
        if symbol.startswith("GOAL:"):
            raise RuntimeError("db locked")
        return real_get(symbol)

    engine._store.get_snapshot = flaky
    monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [{"symbol": "AAPL"}])
    sched.job_alert_check()
    assert [m for _t, m in notifier.sent if "SORR" in m]


# --------------------------------------------------------------------------- #
#  2 — severidad mínima por perfil, de la config                              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("profile, field", [
    ("Conservador", "min_severity_conservador"),
    ("Moderado", "min_severity_moderado"),
    ("Agresivo", "min_severity_agresivo"),
])
@pytest.mark.parametrize("level", ["info", "warning", "critical"])
def test_the_profile_floor_comes_from_the_config(monkeypatch, profile, field, level):
    monkeypatch.setattr(ALERTS, field, level)
    assert _min_severity_for_profile(profile) == AlertSeverity(level)


def test_defaults_keep_the_old_behaviour():
    assert _min_severity_for_profile("Conservador") == AlertSeverity.WARNING
    assert _min_severity_for_profile("Moderado") == AlertSeverity.INFO
    assert _min_severity_for_profile("Agresivo") == AlertSeverity.INFO
    assert _min_severity_for_profile("") == AlertSeverity.INFO


def test_a_misspelt_floor_does_not_break_the_engine(monkeypatch):
    monkeypatch.setattr(ALERTS, "min_severity_moderado", "WARNING ")
    assert _min_severity_for_profile("Moderado") == AlertSeverity.WARNING
    monkeypatch.setattr(ALERTS, "min_severity_moderado", "alta")
    assert _min_severity_for_profile("Moderado") == AlertSeverity.INFO


# --------------------------------------------------------------------------- #
#  3 — ALERT_AI_MIN_SEVERITY en mayúsculas                                     #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw", ["WARNING", " Warning ", "bogus"])
def test_the_ai_threshold_never_raises(monkeypatch, raw):
    monkeypatch.setattr(ALERTS, "ai_explanations_enabled", True)
    monkeypatch.setattr(ALERTS, "ai_explanations_min_severity", raw)
    # La IA está apagada en los tests (TEST-ENV-KEY): llega al final y devuelve "".
    assert _get_ai_explanation("SCORE_DROP", "AAPL", {}, AlertSeverity.INFO) == ""
