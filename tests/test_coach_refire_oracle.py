"""AUDIT-NUMB-4 (PR-2) — el coach de cartera no repite el aviso si nada empeoró.

``check_market_drop_coach`` solo miraba un cooldown de 72 h: una cartera clavada en −9 % recibía el
mismo aviso cada 3-4 días (reproducido con un ``AlertStore`` real y un reloj simulado: 10 avisos en 30
días con chequeos diarios; el scheduler real corre una vez al día por ``launchd`` y la hora del chequeo
cambia con la duración del job, así que el cooldown efectivo es de 3 o 4 días).

Regla: dentro de un episodio (la cartera sigue bajo el umbral) el coach vuelve a avisar sólo si el retorno
empeora ``ALERTS.coach_refire_extra_drop_pp`` puntos más allá del último nivel avisado, o si la severidad
sube (de «respirá» a «el plan necesita atención»). Mientras el retorno se recupera, el nivel de
referencia sube con él (una caída que parte de lo recuperado es noticia; una cartera que oscila en −8 % no
es un aviso por cada cruce). Un episodio cuya base dejó de medirse `coach_episode_max_gap_days` vence. Cada base
(costo ↔ precios del plan) lleva su propio episodio: el scheduler alterna entre las dos cuando fallan las
cotizaciones. El cooldown de 72 h es un piso entre avisos y vive en ``ALERTS.coach_cooldown_hours``. El
nivel avisado se guarda en ``alert_snapshots`` (``COACH:<plan>:<base>``), como ``GOAL:<plan>``: sin cambio
de esquema.
"""

from __future__ import annotations

import datetime as dt

import pytest

import alerts.store as store_mod
from alerts.engine import AlertEngine
from alerts.store import AlertStore
from config import ALERTS

START = dt.datetime(2026, 1, 1, 8, 0)


@pytest.fixture
def clock(monkeypatch):
    now = [START]
    monkeypatch.setattr(store_mod, "utc_now", lambda: now[0])
    monkeypatch.setattr(ALERTS, "ai_explanations_enabled", False)
    return now


@pytest.fixture
def engine(tmp_path, clock):
    return AlertEngine(store=AlertStore(db_path=tmp_path / "alerts.db"))


def _check(engine, ret, *, basis="cost", prob=65.0):
    return engine.check_market_drop_coach(
        portfolio_return_pct=ret, plan_name="Demo", plan_prob_target_pct=prob, basis=basis
    )


def _days(clock, n):
    clock[0] += dt.timedelta(days=n)


def test_a_flat_return_is_announced_once_not_every_few_days(engine, clock):
    fires = []
    for day in range(30):
        if _check(engine, -9.0):
            fires.append(day)
        _days(clock, 1)
    assert fires == [0]                                  # before the fix: [0, 3, 6, 9, ..., 27]


def test_it_announces_again_only_when_it_got_worse_by_the_configured_points(engine, clock):
    assert _check(engine, -9.0)
    _days(clock, 4)
    assert _check(engine, -10.9) is None                 # 1.9 pp worse: not enough
    assert _check(engine, -11.0) is not None             # 2.0 pp: the configured step


def test_the_next_step_is_measured_from_the_last_announced_level_not_from_the_last_check(engine, clock):
    assert _check(engine, -9.0)
    _days(clock, 4)
    assert _check(engine, -10.0) is None                 # drifting down 1 pp at a time ...
    _days(clock, 4)
    assert _check(engine, -10.9) is None
    _days(clock, 4)
    assert _check(engine, -11.0) is not None             # ... still triggers once 2 pp past -9


def test_the_cooldown_stays_as_a_floor_even_for_a_big_worsening(engine, clock):
    assert _check(engine, -9.0)
    _days(clock, 2)
    assert _check(engine, -20.0) is None                 # 48 h < 72 h
    _days(clock, 1)
    assert _check(engine, -20.0) is not None


def test_recovering_above_the_threshold_and_dropping_again_announces_again(engine, clock):
    assert _check(engine, -12.0)
    _days(clock, 4)
    assert _check(engine, -3.0) is None                  # recovered
    _days(clock, 40)
    assert _check(engine, -8.5) is not None              # a new episode, although -12 was announced before


def test_each_basis_has_its_own_episode(engine, clock):
    assert _check(engine, -9.0, basis="cost")
    _days(clock, 4)
    assert _check(engine, -9.0, basis="plan_saved") is not None   # the two figures are not comparable
    _days(clock, 4)
    assert _check(engine, -9.0, basis="cost") is None             # already announced on that basis


def test_a_basis_that_flips_back_and_forth_does_not_announce_every_time(engine, clock):
    """The scheduler falls back to the plan's prices when the quotes fail: that must not be spam."""
    fires = 0
    for day in range(30):
        basis = "cost" if (day // 2) % 2 == 0 else "plan_saved"
        fires += 1 if _check(engine, -9.0, basis=basis) else 0
        _days(clock, 1)
    assert fires == 2                                              # one per basis (before: 8)


def test_a_return_wobbling_around_the_threshold_is_one_episode(engine, clock):
    fires = 0
    for day in range(30):
        fires += 1 if _check(engine, -8.3 if day % 2 == 0 else -7.7) else 0
        _days(clock, 1)
    assert fires == 1                                              # before: 8 (every crossing reopened it)


def test_the_reference_follows_the_recovery_and_never_goes_down_by_itself(engine, clock):
    assert _check(engine, -12.0)
    _days(clock, 4)
    assert _check(engine, -6.0) is None            # recovered: the reference is now -6
    _days(clock, 4)
    assert _check(engine, -7.5) is None            # only 1.5 pp below that reference: not news
    assert _check(engine, -5.9) is None            # keeps following the recovery (reference -5.9)
    _days(clock, 4)
    assert _check(engine, -8.5) is not None        # 2.6 pp below the recovered level


def test_a_recovery_inside_the_band_moves_the_reference_so_a_new_drop_is_news(engine, clock):
    assert _check(engine, -12.0)
    _days(clock, 4)
    assert _check(engine, -7.0) is None            # recovered 5 pp, still above the threshold
    _days(clock, 1)
    assert _check(engine, -9.5) is not None        # measured from -7, not from the -12 announced (before: needs -14)


def test_a_rise_in_severity_announces_even_without_two_points(engine, clock):
    first = _check(engine, -9.0, prob=65.0)
    assert first is not None and first.severity.value == "info"
    _days(clock, 4)
    second = _check(engine, -9.0, prob=30.0)             # the plan fell under the comfort floor
    assert second is not None and second.severity.value == "warning"


def test_a_stale_episode_on_a_basis_that_stopped_being_measured_does_not_hide_a_new_drop(engine, clock):
    assert _check(engine, -12.0, basis="plan_saved")
    for _ in range(180):                           # six months on the other basis
        _days(clock, 1)
        _check(engine, 3.0, basis="cost")
    assert _check(engine, -9.5, basis="plan_saved") is not None   # before: suppressed (needs -14)


def test_an_episode_observed_every_day_never_goes_stale(engine, clock):
    fires = 0
    for day in range(120):
        fires += 1 if _check(engine, -12.0) else 0
        _days(clock, 1)
    assert fires == 1


def test_the_staleness_window_is_read_from_the_config(engine, clock, monkeypatch):
    monkeypatch.setattr(ALERTS, "coach_episode_max_gap_days", 5)
    assert _check(engine, -12.0, basis="plan_saved")
    _days(clock, 6)
    assert _check(engine, -12.0, basis="plan_saved") is not None


def test_a_drop_in_severity_does_not_announce_by_itself(engine, clock):
    assert _check(engine, -9.0, prob=30.0)
    _days(clock, 4)
    assert _check(engine, -9.0, prob=65.0) is None


def test_the_step_and_the_cooldown_are_read_from_the_config(engine, clock, monkeypatch):
    monkeypatch.setattr(ALERTS, "coach_refire_extra_drop_pp", 5.0)
    monkeypatch.setattr(ALERTS, "coach_cooldown_hours", 24)
    assert _check(engine, -9.0)
    _days(clock, 1)
    assert _check(engine, -13.9) is None                 # cooldown over (24 h) but 4.9 pp < 5
    assert _check(engine, -14.0) is not None


def test_a_user_with_a_cooldown_but_no_saved_level_is_announced_once_then_tracked(engine, clock):
    """The state of a database written before this change: a cooldown and no ``COACH:`` snapshot."""
    from alerts.store import AlertType

    engine._store.set_cooldown(AlertType.MARKET_DROP_COACH, "COACH:Demo")
    _days(clock, 4)
    assert _check(engine, -9.0) is not None
    _days(clock, 4)
    assert _check(engine, -9.0) is None


def test_a_nan_return_neither_announces_nor_moves_the_reference(engine, clock):
    assert _check(engine, -9.0)
    _days(clock, 4)
    assert _check(engine, float("nan")) is None
    assert _check(engine, -9.0) is None                  # still the same episode


def test_a_muted_coach_does_not_record_a_level(engine, clock):
    engine._store.add_mute(symbol="*", alert_type="market_drop_coach")
    assert _check(engine, -12.0) is None
    engine._store.remove_mute(engine._store.get_mutes()[0].id)
    assert _check(engine, -12.0) is not None             # nothing was "already announced"


# The cooldown table as it was before the coach's moved to the config: the oracle for «no other type changed».
_OLD_COOLDOWN_HOURS = {
    "SIGNAL_CHANGE": 24, "SCORE_DROP": 168, "SCORE_SURGE": 168, "OPPORTUNITY": 72, "MOAT_CHANGE": 336,
    "PORTFOLIO_LOSS": 72, "PORTFOLIO_DRIFT": 168, "PORTFOLIO_REBALANCE": 168, "SORR_HIGH": 336,
    "GOAL_RISK": 168, "PLAN_HEALTH_DEGRADATION": 168,
}


def test_the_coach_cooldown_comes_from_the_config_and_no_other_type_changed(clock, monkeypatch, tmp_path):
    from alerts.store import AlertType

    store = AlertStore(db_path=tmp_path / "x.db")
    monkeypatch.setattr(ALERTS, "coach_cooldown_hours", 48)
    store.set_cooldown(AlertType.MARKET_DROP_COACH, "COACH:Demo")
    clock[0] += dt.timedelta(hours=30)
    assert store.is_on_cooldown(AlertType.MARKET_DROP_COACH, "COACH:Demo")
    monkeypatch.setattr(ALERTS, "coach_cooldown_hours", 24)
    assert not store.is_on_cooldown(AlertType.MARKET_DROP_COACH, "COACH:Demo")

    assert {t.name for t in AlertType} == set(_OLD_COOLDOWN_HOURS) | {"MARKET_DROP_COACH"}, "a new alert type: add its cooldown here"
    monkeypatch.setattr(ALERTS, "coach_cooldown_hours", 1)       # a different value must not leak into the others
    for name, hours in _OLD_COOLDOWN_HOURS.items():
        t = AlertType[name]
        s2 = AlertStore(db_path=tmp_path / f"{name}.db")
        s2.set_cooldown(t, "X")
        base = clock[0]
        clock[0] = base + dt.timedelta(hours=hours - 1)
        assert s2.is_on_cooldown(t, "X"), name
        clock[0] = base + dt.timedelta(hours=hours + 1)
        assert not s2.is_on_cooldown(t, "X"), name
        clock[0] = base


def test_a_failure_saving_the_level_does_not_lose_the_alert(engine, clock, monkeypatch):
    """The alert is already in the history with its cooldown set; raising here would drop it from the dispatch."""
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(engine._store, "save_snapshot", boom)
    assert _check(engine, -9.0) is not None
