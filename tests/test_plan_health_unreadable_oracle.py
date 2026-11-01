"""AUDIT-AIIO-2 — el historial de salud del plan ilegible se aparta, no se pisa.

``PlanHealthStore._read_raw`` leía un archivo ilegible como ``[]`` y lo dejaba donde estaba. ``append`` y
``clear`` reescriben el archivo entero a partir de esa lectura: un JSON truncado (corte de luz, disco lleno)
borraba **todo el historial longitudinal de todos los planes** en el siguiente registro del scheduler, que
escribe sin que nadie lo mire. Es el defecto de AUDIT-AIIO-1 (preferencias) y el que ``PlanStore`` ya corrigió.

Regla: un archivo ilegible (no es JSON, no es una lista de objetos, no es UTF-8) se mueve a
``plan_health_history.corrupt-<fecha>.json`` con sus bytes intactos y el historial arranca vacío; si no se puede
mover, queda donde está y ``append`` / ``clear`` no escriben encima. Vacío: nada que conservar. Rutas en tmp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.plan_health import PlanHealthRecord, PlanHealthStore, PlanHealthUnavailable
from tests.test_plan_page_runtime import (  # noqa: F401  (fixture)
    _app,
    _FakePrefs,
    _open_snapshot,
    _snap,
    stores,
)

TRUNCATED = b'[{"plan_id": "p1", "recorded_at": "2026-08-01T10:00:00", "weighted_delta_pct": -3.2}, {"plan_id": "p1", "rec'


@pytest.fixture
def store(tmp_path) -> PlanHealthStore:
    return PlanHealthStore(path=tmp_path / "plan_health_history.json")


def _asides(store: PlanHealthStore) -> list[Path]:
    return sorted(store.path.parent.glob("plan_health_history.corrupt-*.json"))


def _record(plan_id="p1", at="2026-11-01T09:00:00") -> PlanHealthRecord:
    return PlanHealthRecord(plan_id=plan_id, recorded_at=at, weighted_delta_pct=1.5)


@pytest.mark.parametrize("content", [
    TRUNCATED,
    b'{"plan_id": "p1"}',                 # JSON, but not a list
    b"[1, 2, 3]",                         # a list, but not of records
    b'[{"plan_id": "p1", "recorded_at": "2026-08-01T10:00:00"}, 1]',   # records and a stray value
    b"\xff\xfe\x00 not utf-8",
])
def test_an_unreadable_history_is_set_aside_with_its_bytes_intact(store, content):
    store.path.write_bytes(content)
    assert store.history("p1") == []                      # reading must not crash either
    [aside] = _asides(store)
    assert aside.read_bytes() == content
    assert not store.path.exists()


def test_the_next_record_no_longer_destroys_the_history_that_was_there(store):
    store.path.write_bytes(TRUNCATED)
    assert store.append(_record()) is not None
    saved = json.loads(store.path.read_text(encoding="utf-8"))
    assert [d["plan_id"] for d in saved] == ["p1"] and len(saved) == 1   # a clean file with the new record
    [aside] = _asides(store)
    assert aside.read_bytes() == TRUNCATED                # before the fix: gone after this append


def test_clearing_a_plan_does_not_wipe_an_unreadable_file(store):
    store.path.write_bytes(TRUNCATED)
    assert store.clear("p1") == 0
    [aside] = _asides(store)
    assert aside.read_bytes() == TRUNCATED


def test_a_readable_history_is_untouched(store):
    store.append(_record(at="2026-10-01T09:00:00"))
    store.append(_record(at="2026-11-01T09:00:00"))
    before = store.path.read_bytes()
    assert [r.recorded_at for r in store.history("p1")] == ["2026-10-01T09:00:00", "2026-11-01T09:00:00"]
    assert store.path.read_bytes() == before
    assert _asides(store) == []


def test_an_empty_file_has_nothing_to_keep(store):
    store.path.write_bytes(b"  \n")
    assert store.history("p1") == []
    assert store.append(_record()) is not None
    assert _asides(store) == []


def test_when_the_file_cannot_be_moved_nothing_is_written_over_it(store, monkeypatch):
    store.path.write_bytes(TRUNCATED)

    def refuse(self, target):
        raise OSError("disco de solo lectura")

    monkeypatch.setattr(Path, "replace", refuse)
    assert store.history("p1") == []
    with pytest.raises(PlanHealthUnavailable):             # refuses, like PlanStore — and says so
        store.append(_record())
    assert store.clear("p1") == 0
    assert store.path.read_bytes() == TRUNCATED
    assert _asides(store) == []


def test_the_dedup_and_the_cap_still_work_on_a_readable_file(store):
    assert store.append(_record(), min_days_between=1) is not None
    assert store.append(_record(), min_days_between=1) is None      # same day: skipped
    for day in range(2, 6):
        store.append(_record(at=f"2026-11-0{day}T09:00:00"), max_records=3)
    assert len(store.history("p1")) == 3


# --- las superficies: «no se pudo» no es «ya registraste hoy» -----------------------------------------

def test_the_scheduler_keeps_evaluating_the_history_when_it_cannot_record(monkeypatch):
    import types

    import config
    import scripts.run_scheduler as sched

    mod = types.ModuleType("data.plan_context")
    mod.get_active_plan = lambda: types.SimpleNamespace(id="p1", name="Demo")
    mod.plan_price_lookup = lambda s: None

    def cannot_record(*a, **k):
        raise PlanHealthUnavailable("ilegible")

    mod.record_plan_health = cannot_record
    mod.get_plan_health_history = lambda pid: []
    mod.compute_longitudinal_drift = lambda hist: {"degraded": False}
    monkeypatch.setitem(__import__("sys").modules, "data.plan_context", mod)
    monkeypatch.setattr(config.HEALTH, "enabled", True)
    monkeypatch.setattr(config.HEALTH, "auto_record", True)

    class Engine:
        def check_plan_health_degradation(self, name, drift):
            self.seen = drift
            return None

    engine = Engine()
    assert sched._check_plan_health(engine) == []        # no exception out of the job
    assert engine.seen == {"degraded": False}            # and the check still ran


def test_the_page_says_the_record_was_not_saved_instead_of_already_recorded_today(stores, monkeypatch):  # noqa: F811
    stores.plans.upsert(_snap())
    stores.health.path.write_bytes(TRUNCATED)

    def refuse(self, target):
        raise OSError("disco de solo lectura")

    monkeypatch.setattr(Path, "replace", refuse)
    at = _open_snapshot(_app(_FakePrefs()), "retiro-2045")
    at.button(key="record_health_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("No se pudo registrar la salud" in e.value for e in at.error)
    assert not any("Ya habías registrado" in (t.value or "") for t in at.toast)
    assert stores.health.path.read_bytes() == TRUNCATED


def test_the_page_records_after_setting_the_unreadable_file_aside(stores):  # noqa: F811
    stores.plans.upsert(_snap())
    stores.health.path.write_bytes(TRUNCATED)
    at = _open_snapshot(_app(_FakePrefs()), "retiro-2045")
    at.button(key="record_health_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(stores.health.history("retiro-2045")) == 1
    [aside] = sorted(stores.health.path.parent.glob("*.corrupt-*.json"))
    assert aside.read_bytes() == TRUNCATED


def test_the_set_aside_copies_are_never_committed_by_a_git_add():
    """They hold the investor's plans, profile or convictions: ``git check-ignore`` must cover each store."""
    import subprocess

    root = Path(__file__).resolve().parents[1]
    names = [
        "data/plan_health_history.corrupt-20261101T120000000000.json",
        "data/user_preferences.corrupt-20261101T120000000000.json",
        "data/personal_book_convictions.corrupt-20261101T120000000000.json",
        "data/retirement_plans.corrupt-20261101T120000000000.json",
    ]
    for name in names:
        r = subprocess.run(["git", "check-ignore", "-q", name], cwd=root)
        assert r.returncode == 0, f"{name} no está en .gitignore"
