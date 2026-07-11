"""
Longitudinal plan-health history (Fase H.2).

Persists lightweight, periodic "health records" for saved plans so the user can
see how a plan holds up over months — weighted price drift since save, score at
save, Monte Carlo P50, core size and data quality — and so the app can detect
silent structural drift ("plan envejecido") before it gets expensive.

Mirrors the load/save pattern of ``data.plan_store.PlanStore``: a single JSON
file holding a flat list of records (newest appended last), filtered by
``plan_id``. Intentionally Streamlit-free and import-light so the dashboard and
the background scheduler can both use it.

Usage:
    from data.plan_health import PlanHealthRecord, plan_health_store
    rec = PlanHealthRecord.from_plan(snap, refreshed, source="manual")
    plan_health_store.append(rec)
    history = plan_health_store.history(snap.id)   # chronological
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger

_HEALTH_PATH = Path(__file__).parent / "plan_health_history.json"


def _narrative_hash(text: str) -> str:
    """Short, stable hash of the plan narrative — lets us detect when it changed."""
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


# ------------------------------------------------------------------ #
#  PlanHealthRecord                                                    #
# ------------------------------------------------------------------ #

@dataclass
class PlanHealthRecord:
    """A single point-in-time health reading for a plan."""

    plan_id: str
    recorded_at: str                       # ISO timestamp
    weighted_delta_pct: Optional[float] = None   # weighted price drift since save
    avg_score_then: Optional[float] = None       # avg adjusted score at save time
    n_priced: int = 0                      # tickers priced today
    n_total: int = 0                       # tickers in the plan
    data_quality_pct: float = 0.0          # n_priced / n_total * 100
    mc_p50: Optional[float] = None         # Monte Carlo median terminal (at save)
    n_core: int = 0                        # core-holdings count
    narrative_hash: str = ""               # detects narrative changes across records
    source: str = "manual"                 # "manual" | "scheduler"

    @classmethod
    def from_plan(cls, snap, refreshed: dict, *, source: str = "manual") -> "PlanHealthRecord":
        """Build a record from a PlanSnapshot + a ``compute_plan_vs_reality`` result."""
        summary = (refreshed or {}).get("summary", {}) or {}
        n_priced = int(summary.get("n_priced", 0) or 0)
        n_total = int(summary.get("n_total", 0) or 0)
        mc = getattr(snap, "mc_summary", None) or {}
        return cls(
            plan_id=getattr(snap, "id", ""),
            recorded_at=datetime.now().isoformat(timespec="seconds"),
            weighted_delta_pct=summary.get("weighted_delta_pct"),
            avg_score_then=summary.get("avg_score_then"),
            n_priced=n_priced,
            n_total=n_total,
            data_quality_pct=round(n_priced / n_total * 100, 1) if n_total else 0.0,
            mc_p50=(round(float(mc.get("median_terminal")), 0)
                    if mc.get("median_terminal") is not None else None),
            n_core=len(getattr(snap, "core_holdings", []) or []),
            narrative_hash=_narrative_hash(getattr(snap, "narrative", "") or ""),
            source=source,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def day(self) -> str:
        """Calendar day (YYYY-MM-DD) of this record."""
        return (self.recorded_at or "")[:10]


# ------------------------------------------------------------------ #
#  PlanHealthStore                                                     #
# ------------------------------------------------------------------ #

class PlanHealthStore:
    """JSON-backed flat list of PlanHealthRecords (chronological)."""

    def __init__(self, path: Path = _HEALTH_PATH) -> None:
        self.path = path

    def _read_raw(self) -> List[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning(f"Could not load plan-health history ({exc}) — starting empty")
            return []

    def _write_raw(self, items: List[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            logger.error(f"Could not save plan-health history: {exc}")

    def history(self, plan_id: str) -> List[PlanHealthRecord]:
        """All records for a plan, oldest first."""
        known = {f for f in PlanHealthRecord.__dataclass_fields__}
        out = [
            PlanHealthRecord(**{k: v for k, v in d.items() if k in known})
            for d in self._read_raw()
            if d.get("plan_id") == plan_id
        ]
        return sorted(out, key=lambda r: r.recorded_at)

    def append(
        self,
        record: PlanHealthRecord,
        *,
        min_days_between: int = 0,
        max_records: int = 0,
    ) -> Optional[PlanHealthRecord]:
        """Append a record. Returns the record, or None if skipped by dedup.

        ``min_days_between`` > 0 skips the append when the plan already has a
        record on the same calendar day (or within the window). ``max_records``
        > 0 trims the oldest records for that plan beyond the cap.
        """
        items = self._read_raw()

        if min_days_between > 0:
            existing = [d for d in items if d.get("plan_id") == record.plan_id]
            if existing:
                last_day = max((d.get("recorded_at", "")[:10] for d in existing), default="")
                if last_day and last_day == record.day():
                    logger.info(f"Plan-health record skipped (already recorded {last_day}).")
                    return None

        items.append(record.to_dict())

        if max_records and max_records > 0:
            plan_items = [d for d in items if d.get("plan_id") == record.plan_id]
            if len(plan_items) > max_records:
                # Keep only the most recent ``max_records`` for this plan.
                plan_items_sorted = sorted(plan_items, key=lambda d: d.get("recorded_at", ""))
                drop = set(id(d) for d in plan_items_sorted[:-max_records])
                items = [d for d in items if id(d) not in drop]

        self._write_raw(items)
        logger.info(f"Plan-health recorded for '{record.plan_id}' ({record.source}).")
        return record

    def clear(self, plan_id: str) -> int:
        """Delete all records for a plan. Returns the number removed."""
        items = self._read_raw()
        remaining = [d for d in items if d.get("plan_id") != plan_id]
        removed = len(items) - len(remaining)
        if removed:
            self._write_raw(remaining)
        return removed


# Module-level singleton (mirrors data.plan_store pattern)
plan_health_store = PlanHealthStore()
