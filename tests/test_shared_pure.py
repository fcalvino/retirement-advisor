"""Unit coverage for the pure / near-pure helpers in ``dashboard/shared.py`` (backlog T1).

These functions carry real contracts that nothing else pins:

* ``drags_to_tuple`` / ``withdrawal_to_tuple`` produce the hashable cache keys that
  ``@st.cache_data`` uses for the Monte-Carlo layer — an unstable ordering or a
  leaked non-scalar would silently bust (or wrongly share) the sim cache.
* ``export_plan_bundle`` is the only path that serializes a plan for off-machine
  backup; a dropped field is silent data loss the user only discovers on restore.
* ``plan_journey_status`` / ``next_priority_action`` drive the Home "do this next"
  CTA; the branch order is the product behaviour.

They are exercised without a Streamlit runtime: ``st.session_state`` is swapped for
a plain dict and the cheap I/O collaborators are monkeypatched.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from dashboard import shared
from data.plan_store import PlanSnapshot

# --------------------------------------------------------------------------- #
#  drags_to_tuple                                                              #
# --------------------------------------------------------------------------- #

class TestDragsToTuple:
    def test_none_and_empty_map_to_none(self):
        assert shared.drags_to_tuple(None) is None
        assert shared.drags_to_tuple({}) is None

    def test_total_annual_drag_pct_is_excluded(self):
        drags = {"enabled": True, "annual_fee_pct": 0.5, "total_annual_drag_pct": 1.2}
        out = shared.drags_to_tuple(drags)
        assert ("total_annual_drag_pct", 1.2) not in out
        assert ("annual_fee_pct", 0.5) in out

    def test_key_order_is_stable_regardless_of_dict_insertion_order(self):
        a = {"b": 2, "a": 1, "c": 3}
        b = {"c": 3, "a": 1, "b": 2}
        assert shared.drags_to_tuple(a) == shared.drags_to_tuple(b)
        assert shared.drags_to_tuple(a) == (("a", 1), ("b", 2), ("c", 3))

    def test_result_is_hashable(self):
        hash(shared.drags_to_tuple({"annual_fee_pct": 0.3, "ar_buffer_pct": 0.1}))

    def test_equal_inputs_produce_equal_keys(self):
        d1 = {"enabled": True, "annual_fee_pct": 0.5, "total_annual_drag_pct": 9.9}
        d2 = {"enabled": True, "annual_fee_pct": 0.5, "total_annual_drag_pct": 0.0}
        # The excluded field differs but the cache key must not.
        assert shared.drags_to_tuple(d1) == shared.drags_to_tuple(d2)


# --------------------------------------------------------------------------- #
#  withdrawal_to_tuple                                                         #
# --------------------------------------------------------------------------- #

class TestWithdrawalToTuple:
    def test_none_and_empty_map_to_none(self):
        assert shared.withdrawal_to_tuple(None) is None
        assert shared.withdrawal_to_tuple({}) is None

    def test_label_is_excluded_scalars_are_kept(self):
        strat = {"kind": "fixed_real", "annual_amount": 40000.0, "label": "Retiro fijo real"}
        out = shared.withdrawal_to_tuple(strat)
        assert ("label", "Retiro fijo real") not in out
        assert ("kind", "fixed_real") in out
        assert ("annual_amount", 40000.0) in out

    def test_non_scalar_values_are_dropped(self):
        strat = {"kind": "constant_pct", "pct": 0.04, "history": [1, 2, 3], "meta": {"x": 1}}
        out = shared.withdrawal_to_tuple(strat)
        keys = {k for k, _ in out}
        assert keys == {"kind", "pct"}

    def test_key_order_is_stable_and_hashable(self):
        a = {"pct": 0.04, "kind": "constant_pct", "base": 0.03}
        b = {"base": 0.03, "kind": "constant_pct", "pct": 0.04}
        assert shared.withdrawal_to_tuple(a) == shared.withdrawal_to_tuple(b)
        hash(shared.withdrawal_to_tuple(a))

    def test_bool_is_kept_as_scalar(self):
        # bool is a subclass of int — deliberately kept.
        out = shared.withdrawal_to_tuple({"kind": "guardrails", "enabled": True})
        assert ("enabled", True) in out


# --------------------------------------------------------------------------- #
#  Session-state harness for the journey/CTA helpers                           #
# --------------------------------------------------------------------------- #

@pytest.fixture
def fake_session(monkeypatch):
    """Swap ``shared.st`` for a stub exposing only ``session_state`` (a dict)."""
    state: dict = {}
    monkeypatch.setattr(shared, "st", SimpleNamespace(session_state=state))
    return state


@pytest.fixture
def stub_plan_store(monkeypatch):
    saved: list = []
    monkeypatch.setattr("data.plan_store.plan_store.list", lambda: saved)
    return saved


def _prefs(**kw):
    base = dict(is_onboarded=False, active_plan_id="", plan_exported_at="")
    base.update(kw)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
#  plan_journey_status                                                         #
# --------------------------------------------------------------------------- #

class TestPlanJourneyStatus:
    def test_fresh_user_has_five_steps_all_undone_except_backup(self, fake_session, stub_plan_store):
        steps = shared.plan_journey_status(_prefs())
        assert [s["label"] for s in steps][:2] == [
            "Definí tu perfil de retiro", "Optimizá tu cartera"
        ]
        assert len(steps) == 5
        assert [s["done"] for s in steps] == [False, False, False, False, True]

    def test_backup_step_is_done_when_there_is_nothing_to_back_up(self, fake_session, stub_plan_store):
        # not has_saved -> backup step "done" (nothing to protect yet)
        steps = shared.plan_journey_status(_prefs())
        assert steps[4]["done"] is True

    def test_backup_step_becomes_pending_once_a_plan_is_saved(self, fake_session, stub_plan_store):
        stub_plan_store.append(object())
        steps = shared.plan_journey_status(_prefs())
        assert steps[2]["done"] is True          # "Guardá tu plan"
        assert steps[4]["done"] is False         # now there IS something to back up

    def test_export_session_flag_marks_backup_done(self, fake_session, stub_plan_store):
        stub_plan_store.append(object())
        fake_session["plan_exported"] = True
        steps = shared.plan_journey_status(_prefs())
        assert steps[4]["done"] is True

    def test_prefs_exported_at_marks_backup_done(self, fake_session, stub_plan_store):
        stub_plan_store.append(object())
        steps = shared.plan_journey_status(_prefs(plan_exported_at="2026-09-01T00:00:00"))
        assert steps[4]["done"] is True

    def test_optimizer_step_reads_either_session_key(self, fake_session, stub_plan_store):
        fake_session["optimizer_prev_result"] = {"weights": {}}
        steps = shared.plan_journey_status(_prefs())
        assert steps[1]["done"] is True

    def test_active_plan_id_whitespace_only_is_not_active(self, fake_session, stub_plan_store):
        steps = shared.plan_journey_status(_prefs(active_plan_id="   "))
        assert steps[3]["done"] is False

    def test_all_done_when_profile_opt_saved_and_active(self, fake_session, stub_plan_store):
        stub_plan_store.append(object())
        fake_session["optimizer_result"] = {"weights": {}}
        fake_session["plan_exported"] = True
        steps = shared.plan_journey_status(
            _prefs(is_onboarded=True, active_plan_id="plan-1")
        )
        assert all(s["done"] for s in steps)


# --------------------------------------------------------------------------- #
#  next_priority_action                                                        #
# --------------------------------------------------------------------------- #

class TestNextPriorityAction:
    def test_incomplete_journey_points_at_first_undone_step(self, fake_session, stub_plan_store):
        action = shared.next_priority_action(_prefs())
        assert action["tone"] == "primary"
        assert action["label"] == "Definí tu perfil de retiro"

    def _complete_journey(self, session, store, monkeypatch):
        store.append(object())
        session["optimizer_result"] = {"weights": {}}
        session["plan_exported"] = True
        monkeypatch.setattr(shared, "unread_alert_count", lambda: 0)

    def test_unread_alerts_win_once_journey_is_complete(
        self, fake_session, stub_plan_store, monkeypatch
    ):
        self._complete_journey(fake_session, stub_plan_store, monkeypatch)
        monkeypatch.setattr(shared, "unread_alert_count", lambda: 3)
        # A stale plan is *also* actionable — the alert branch must still win,
        # so this pins the precedence, not just "alerts beat nothing".
        stale = SimpleNamespace(last_refreshed_at="2020-01-01T00:00:00")
        monkeypatch.setattr("data.plan_context.get_active_plan", lambda _p: stale)
        action = shared.next_priority_action(_prefs(is_onboarded=True, active_plan_id="p1"))
        assert action["tone"] == "warning"
        assert action["page"] == "8_Alertas.py"
        assert "3" in action["label"]

    def test_stale_active_plan_triggers_health_check(
        self, fake_session, stub_plan_store, monkeypatch
    ):
        self._complete_journey(fake_session, stub_plan_store, monkeypatch)
        stale = SimpleNamespace(last_refreshed_at="2020-01-01T00:00:00")
        monkeypatch.setattr("data.plan_context.get_active_plan", lambda _p: stale)
        action = shared.next_priority_action(_prefs(is_onboarded=True, active_plan_id="p1"))
        assert action["tone"] == "warning"
        assert action["page"] == "12_Plan.py"
        assert "salud" in action["label"].lower()

    def test_never_refreshed_active_plan_also_triggers_health_check(
        self, fake_session, stub_plan_store, monkeypatch
    ):
        self._complete_journey(fake_session, stub_plan_store, monkeypatch)
        never = SimpleNamespace(last_refreshed_at="")
        monkeypatch.setattr("data.plan_context.get_active_plan", lambda _p: never)
        action = shared.next_priority_action(_prefs(is_onboarded=True, active_plan_id="p1"))
        assert action["tone"] == "warning"

    def test_fresh_plan_and_no_alerts_reports_all_clear(
        self, fake_session, stub_plan_store, monkeypatch
    ):
        self._complete_journey(fake_session, stub_plan_store, monkeypatch)
        from datetime import datetime, timezone
        fresh = SimpleNamespace(last_refreshed_at=datetime.now(timezone.utc).isoformat())
        monkeypatch.setattr("data.plan_context.get_active_plan", lambda _p: fresh)
        action = shared.next_priority_action(_prefs(is_onboarded=True, active_plan_id="p1"))
        assert action["tone"] == "ok"
        assert action["icon"] == "✅"

    def test_get_active_plan_failure_is_swallowed_and_returns_ok(
        self, fake_session, stub_plan_store, monkeypatch
    ):
        self._complete_journey(fake_session, stub_plan_store, monkeypatch)

        def _boom(_p):
            raise RuntimeError("plan context unavailable")

        monkeypatch.setattr("data.plan_context.get_active_plan", _boom)
        action = shared.next_priority_action(_prefs(is_onboarded=True, active_plan_id="p1"))
        assert action["tone"] == "ok"


# --------------------------------------------------------------------------- #
#  export_plan_bundle                                                          #
# --------------------------------------------------------------------------- #

def _snapshot(**kw):
    base = dict(
        id="my-plan-01",
        name="Plan Retiro 2050",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-06-01T00:00:00",
        n_positions=7,
        allocation=[{"symbol": "VTI", "weight_pct": 60.0}],
        metrics={"cagr": 0.07},
    )
    base.update(kw)
    return PlanSnapshot(**base)


class TestExportPlanBundle:
    def test_returns_bytes_filename_and_instructions(self):
        json_bytes, filename, instructions = shared.export_plan_bundle(_snapshot())
        assert isinstance(json_bytes, bytes)
        assert filename.startswith("plan_my-plan-01_") and filename.endswith(".json")
        assert "## Cómo restaurar" in instructions

    def test_bundle_carries_the_full_snapshot_dict(self):
        snap = _snapshot()
        json_bytes, _, _ = shared.export_plan_bundle(snap)
        bundle = json.loads(json_bytes)
        assert bundle["schema"] == "retirement_advisor.plan_bundle"
        assert bundle["snapshot"] == snap.to_dict()          # no field dropped
        assert bundle["schema_version"] == snap.export_version

    def test_personal_block_only_when_prefs_onboarded(self):
        snap = _snapshot()
        b_no = json.loads(shared.export_plan_bundle(snap, _prefs(is_onboarded=False))[0])
        assert "personal" not in b_no
        assert "personal" not in json.loads(shared.export_plan_bundle(snap)[0])

        prefs = _prefs(
            is_onboarded=True, age=40, retirement_age=65,
            primary_horizon_years=25, current_capital=100000.0,
            monthly_savings=1500.0, profile_key="moderate",
        )
        b_yes = json.loads(shared.export_plan_bundle(snap, prefs)[0])
        assert b_yes["personal"]["age"] == 40
        assert b_yes["personal"]["profile_key"] == "moderate"

    def test_filename_sanitizes_unsafe_snapshot_id(self):
        snap = _snapshot(id="../../etc/passwd plan!")
        _, filename, _ = shared.export_plan_bundle(snap)
        stem = filename[len("plan_"):-len(".json")]
        safe_id, _, date = stem.rpartition("_")
        assert all(c.isalnum() or c in "-_" for c in safe_id)
        assert date.isdigit() and len(date) == 8

    def test_empty_snapshot_id_falls_back_to_plan(self):
        snap = _snapshot(id="")
        _, filename, _ = shared.export_plan_bundle(snap)
        assert filename.startswith("plan_plan_")

    def test_drag_note_present_only_when_drags_were_saved(self):
        without = shared.export_plan_bundle(_snapshot())[2]
        assert "Supuestos (drags) al guardar" not in without

        with_drags = shared.export_plan_bundle(
            _snapshot(drags_at_save={"enabled": True, "total_annual_drag_pct": 1.35})
        )[2]
        assert "1.35%/año" in with_drags

    def test_json_is_utf8_and_round_trips(self):
        json_bytes, _, _ = shared.export_plan_bundle(_snapshot(name="Jubilación Ñoño €"))
        bundle = json.loads(json_bytes.decode("utf-8"))
        assert bundle["snapshot"]["name"] == "Jubilación Ñoño €"
