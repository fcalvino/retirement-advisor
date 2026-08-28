"""Tests for the longitudinal plan-health history (Fase H.2).

Covers the PlanHealthStore (append/history/dedup/cap), PlanHealthRecord
construction, the plan_context helpers (record/history/longitudinal drift +
degradation), and the AlertEngine degradation check. No network, no Streamlit.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import data.plan_context as pc
import data.plan_health as ph
from data.plan_health import PlanHealthRecord, PlanHealthStore
from data.plan_store import PlanSnapshot

# ------------------------------------------------------------------ #
#  Fixtures / helpers                                                 #
# ------------------------------------------------------------------ #

def _snap(plan_id="retiro-2045", name="Retiro 2045"):
    return PlanSnapshot(
        id=plan_id, name=name, created_at="", updated_at="",
        allocation=[
            {"symbol": "AAPL", "weight_pct": 40.0, "adjusted_score": 82.0, "price_at_save": 100.0},
            {"symbol": "KO", "weight_pct": 60.0, "adjusted_score": 70.0, "price_at_save": 50.0},
        ],
        core_holdings=[{"symbol": "KO", "suggested_weight_pct": 60.0, "why": "income"}],
        mc_summary={"horizon_years": 20, "median_terminal": 500_000.0},
        narrative="Cartera conservadora.",
    )


@pytest.fixture
def health_store(tmp_path, monkeypatch):
    s = PlanHealthStore(path=tmp_path / "health.json")
    monkeypatch.setattr(ph, "plan_health_store", s)
    return s


def _flat_price_lookup(delta_pct: float):
    """Return a price_lookup that moves every ticker by delta_pct from save."""
    def _lookup(sym: str):
        base = {"AAPL": 100.0, "KO": 50.0}.get(sym)
        return base * (1 + delta_pct / 100.0) if base else None
    return _lookup


# ------------------------------------------------------------------ #
#  PlanHealthRecord                                                    #
# ------------------------------------------------------------------ #

class TestPlanHealthRecord:
    def test_from_plan_extracts_summary(self):
        refreshed = {"summary": {"weighted_delta_pct": -12.5, "avg_score_then": 75.0,
                                 "n_priced": 2, "n_total": 2}}
        rec = PlanHealthRecord.from_plan(_snap(), refreshed, source="scheduler")
        assert rec.plan_id == "retiro-2045"
        assert rec.weighted_delta_pct == -12.5
        assert rec.data_quality_pct == 100.0
        assert rec.mc_p50 == 500_000.0
        assert rec.n_core == 1
        assert rec.narrative_hash  # non-empty hash
        assert rec.source == "scheduler"

    def test_data_quality_partial(self):
        refreshed = {"summary": {"n_priced": 1, "n_total": 2}}
        rec = PlanHealthRecord.from_plan(_snap(), refreshed)
        assert rec.data_quality_pct == 50.0


# ------------------------------------------------------------------ #
#  PlanHealthStore                                                     #
# ------------------------------------------------------------------ #

class TestPlanHealthStore:
    def test_append_and_history_chronological(self, health_store):
        health_store.append(PlanHealthRecord("p1", "2026-01-01T10:00:00", weighted_delta_pct=1.0))
        health_store.append(PlanHealthRecord("p1", "2026-02-01T10:00:00", weighted_delta_pct=2.0))
        hist = health_store.history("p1")
        assert [r.weighted_delta_pct for r in hist] == [1.0, 2.0]

    def test_history_filters_by_plan(self, health_store):
        health_store.append(PlanHealthRecord("p1", "2026-01-01T10:00:00"))
        health_store.append(PlanHealthRecord("p2", "2026-01-01T10:00:00"))
        assert len(health_store.history("p1")) == 1
        assert len(health_store.history("p2")) == 1

    def test_dedup_same_day(self, health_store):
        r1 = PlanHealthRecord("p1", "2026-03-01T09:00:00")
        r2 = PlanHealthRecord("p1", "2026-03-01T18:00:00")
        assert health_store.append(r1, min_days_between=1) is not None
        assert health_store.append(r2, min_days_between=1) is None   # skipped same day
        assert len(health_store.history("p1")) == 1

    def test_max_records_trims_oldest(self, health_store):
        for i in range(5):
            health_store.append(
                PlanHealthRecord("p1", f"2026-01-0{i + 1}T10:00:00", weighted_delta_pct=float(i)),
                max_records=3,
            )
        hist = health_store.history("p1")
        assert len(hist) == 3
        # Oldest (0,1) trimmed; newest kept.
        assert [r.weighted_delta_pct for r in hist] == [2.0, 3.0, 4.0]

    def test_clear(self, health_store):
        health_store.append(PlanHealthRecord("p1", "2026-01-01T10:00:00"))
        assert health_store.clear("p1") == 1
        assert health_store.history("p1") == []


# ------------------------------------------------------------------ #
#  plan_context helpers                                               #
# ------------------------------------------------------------------ #

class TestRecordPlanHealth:
    def test_record_then_history(self, health_store):
        rec = pc.record_plan_health(_snap(), _flat_price_lookup(-5.0))
        assert rec is not None
        hist = pc.get_plan_health_history("retiro-2045")
        assert len(hist) == 1
        assert hist[0]["weighted_delta_pct"] == pytest.approx(-5.0, abs=0.1)

    def test_record_reuses_refreshed_without_lookup(self, health_store):
        refreshed = {"summary": {"weighted_delta_pct": 3.3, "avg_score_then": 80,
                                 "n_priced": 2, "n_total": 2}}

        def _boom(_sym):
            raise AssertionError("price_lookup should not be called when refreshed is given")

        rec = pc.record_plan_health(_snap(), _boom, refreshed=refreshed)
        assert rec.weighted_delta_pct == 3.3


def _rec(day: str, drift: float, quality: float = 100.0) -> dict:
    """A history record dict as ``get_plan_health_history`` returns them."""
    return {
        "plan_id": "retiro-2045",
        "recorded_at": f"{day}T09:00:00",
        "weighted_delta_pct": drift,
        "avg_score_then": 75.0,
        "data_quality_pct": quality,
        "source": "manual",
    }


class TestLongitudinalDrift:
    def test_empty_history(self):
        d = pc.compute_longitudinal_drift([])
        assert d["n_records"] == 0
        assert d["degraded"] is False

    def test_not_degraded_small_drift(self):
        d = pc.compute_longitudinal_drift([
            _rec("2026-06-01", -3.0), _rec("2026-07-01", -4.0),
        ])
        assert d["n_records"] == 2
        assert d["degraded"] is False

    def test_degraded_when_sustained_large_drift(self):
        # Two records on different days, both -20% → ≥15% sustained → degraded.
        d = pc.compute_longitudinal_drift([
            _rec("2026-06-01", -20.0), _rec("2026-07-01", -20.0),
        ])
        assert d["degraded"] is True
        assert "sostenida" in d["degraded_reason"].lower()
        assert d["latest_drift_pct"] == pytest.approx(-20.0, abs=0.1)

    def test_same_day_records_are_not_sustained_drift(self):
        """Regression: "sostenida" must mean over time, not over clicks.

        The UI button appended a record per click with no dedup, so two taps a
        second apart satisfied ``degradation_min_records`` and raised the "plan
        envejecido" warning. Histories written by that code still exist on disk,
        so the guard lives here too, not only in the dedup window.
        """
        d = pc.compute_longitudinal_drift([
            _rec("2026-07-01", -20.0), _rec("2026-07-01", -20.0),
        ])
        assert d["n_records"] == 2
        assert d["degraded"] is False
        assert d["degraded_reason"] == ""

    def test_single_large_drift_not_degraded(self, health_store):
        # Only one record → below degradation_min_records → not yet degraded.
        pc.record_plan_health(_snap(), _flat_price_lookup(-25.0))
        d = pc.compute_longitudinal_drift(pc.get_plan_health_history("retiro-2045"))
        assert d["n_records"] == 1
        assert d["degraded"] is False


class TestRecordDedupWindow:
    """The dashboard button called ``record_plan_health`` without a dedup window.

    ``min_days_between`` defaulted to a hardcoded 0, so every click appended a
    record: the "Ya habías registrado la salud hoy" branch in the page was
    unreachable, and ``max_records=60`` meant a long clicking session could evict
    a plan's real history. The scheduler always passed the config value.
    """

    def test_second_record_the_same_day_is_deduped_by_default(self, health_store):
        from config import HEALTH

        assert HEALTH.min_days_between_records >= 1, "config drives the window"

        first = pc.record_plan_health(_snap(), _flat_price_lookup(-20.0))
        second = pc.record_plan_health(_snap(), _flat_price_lookup(-20.0))

        assert first is not None
        assert second is None, "same-day re-record must be skipped, not appended"
        assert len(pc.get_plan_health_history("retiro-2045")) == 1

    def test_explicit_zero_still_allows_back_to_back_records(self, health_store):
        """Callers can still opt out — the default is a policy, not a lock."""
        pc.record_plan_health(_snap(), _flat_price_lookup(-5.0), min_days_between=0)
        pc.record_plan_health(_snap(), _flat_price_lookup(-6.0), min_days_between=0)
        assert len(pc.get_plan_health_history("retiro-2045")) == 2

    def test_clicking_all_day_cannot_evict_the_real_history(self, health_store):
        from config import HEALTH

        for _ in range(HEALTH.max_records + 5):
            pc.record_plan_health(_snap(), _flat_price_lookup(-20.0))

        history = pc.get_plan_health_history("retiro-2045")
        assert len(history) == 1
        assert not pc.compute_longitudinal_drift(history)["degraded"]


# ------------------------------------------------------------------ #
#  AlertEngine.check_plan_health_degradation                          #
# ------------------------------------------------------------------ #

class TestDegradationAlert:
    def _engine(self):
        from alerts.engine import AlertEngine
        from alerts.store import AlertSeverity

        eng = AlertEngine.__new__(AlertEngine)
        eng._store = MagicMock()
        eng._store.is_on_cooldown.return_value = False
        eng._store.is_muted.return_value = False
        eng._notifier = MagicMock()
        eng._min_severity = AlertSeverity.INFO
        return eng

    def test_no_fire_when_not_degraded(self):
        out = self._engine().check_plan_health_degradation(
            "Retiro 2045", {"degraded": False}
        )
        assert out is None

    def test_fires_when_degraded(self):
        from alerts.store import AlertType

        drift = {"degraded": True, "degraded_reason": "Deriva sostenida ≥15%.",
                 "latest_drift_pct": -22.0, "n_records": 3}
        out = self._engine().check_plan_health_degradation("Retiro 2045", drift)
        assert out is not None
        assert out.alert_type == AlertType.PLAN_HEALTH_DEGRADATION
        assert "Retiro 2045" in out.message

    def test_no_fire_on_empty_summary(self):
        assert self._engine().check_plan_health_degradation("X", {}) is None
