"""
Living-plan context — bridge between a saved PlanSnapshot and "today" (Fase C).

This module turns "Mi Plan de Retiro" from a static snapshot into a living
retirement target. It is intentionally **Streamlit-free** and **import-light**
so it can be reused by both the dashboard (with an ``@st.cache_data`` wrapper)
and the background scheduler.

Responsibilities:
  - Resolve / activate / deactivate the user's active plan (persisted in prefs).
  - Compute "plan vs reality": current prices vs the prices captured at save
    time, weighted price drift of the plan and per-ticker deltas.

Network access is injected via a ``price_lookup`` callable so this module never
imports yfinance directly (keeps unit tests offline and fast).

Usage:
    from data.plan_context import get_active_plan, compute_plan_vs_reality
    snap = get_active_plan()
    if snap:
        health = compute_plan_vs_reality(snap, price_lookup=my_price_fn)
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional

from loguru import logger

from data.plan_store import PlanSnapshot, plan_store

PriceLookup = Callable[[str], Optional[float]]


# ------------------------------------------------------------------ #
#  Active-plan resolution                                             #
# ------------------------------------------------------------------ #

def _load_prefs(prefs=None):
    """Return the given prefs or load them from disk (lazy import to stay light)."""
    if prefs is not None:
        return prefs
    from data.preferences import UserPreferences
    return UserPreferences.load()


def get_active_plan(prefs=None) -> Optional[PlanSnapshot]:
    """Return the user's active retirement plan snapshot, or None.

    Self-healing: if ``active_plan_id`` points at a plan that was deleted, the
    stale id is cleared so the app never gets stuck on a missing target.
    """
    prefs = _load_prefs(prefs)
    plan_id = (getattr(prefs, "active_plan_id", "") or "").strip()
    if not plan_id:
        return None
    snap = plan_store.get(plan_id)
    if snap is None:
        logger.info(f"Active plan '{plan_id}' no longer exists — clearing.")
        try:
            prefs.clear_active_plan()
        except Exception:
            pass
        return None
    return snap


def activate_plan(plan_id: str, prefs=None) -> bool:
    """Mark a saved plan as the active retirement target. Returns True on success."""
    prefs = _load_prefs(prefs)
    if plan_store.get(plan_id) is None:
        logger.warning(f"Cannot activate unknown plan '{plan_id}'.")
        return False
    prefs.set_active_plan(plan_id)
    logger.info(f"Active retirement plan set to '{plan_id}'.")
    return True


def deactivate_plan(prefs=None) -> None:
    """Clear the active retirement target."""
    prefs = _load_prefs(prefs)
    prefs.clear_active_plan()


# ------------------------------------------------------------------ #
#  Plan portability (Item 2) — pure import helper                      #
# ------------------------------------------------------------------ #

def import_plan_from_dict(data: dict) -> PlanSnapshot:
    """Rebuild a PlanSnapshot from an exported bundle dict (Item 2).

    Streamlit-free + defensive so it can be unit-tested offline and reused by
    the dashboard's file uploader. Accepts either a raw snapshot dict or an
    export bundle ``{"snapshot": {...}, ...}``. Unknown keys are dropped
    (forward/backward compatible, mirrors ``PlanStore.list``) and the required
    identity fields are validated.

    Raises ``ValueError`` on structurally invalid input.
    """
    if not isinstance(data, dict):
        raise ValueError("El archivo de plan no tiene el formato esperado (no es un objeto JSON).")

    # Allow both a bare snapshot and a wrapped bundle.
    snap_dict = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else data

    if not snap_dict.get("id") or not snap_dict.get("name"):
        raise ValueError("El plan importado no tiene 'id' o 'name' — archivo inválido o corrupto.")

    known = set(PlanSnapshot.__dataclass_fields__)
    clean = {k: v for k, v in snap_dict.items() if k in known}
    # Ensure the required positional-ish fields exist (timestamps optional).
    clean.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    clean.setdefault("updated_at", datetime.now().isoformat(timespec="seconds"))
    try:
        return PlanSnapshot(**clean)
    except TypeError as exc:
        raise ValueError(f"No se pudo reconstruir el plan: {exc}") from exc


# ------------------------------------------------------------------ #
#  Bundled sample plans (Fase H.4 — adoption / demo mode)             #
# ------------------------------------------------------------------ #

import json as _json  # noqa: E402  (local-ish std import kept near its only users)
from pathlib import Path as _Path  # noqa: E402

_SAMPLE_DIR = _Path(__file__).parent / "sample_plans"


def list_sample_plans() -> List[dict]:
    """Return metadata for the bundled example plans (Fase H.4).

    Each entry: ``{key, name, description, n_positions, profile_name}``. ``key``
    is the file stem, used by ``load_sample_plan``. Missing/corrupt files are
    skipped so a bad bundle never breaks the UI. Sorted by name for stability.
    """
    out: List[dict] = []
    if not _SAMPLE_DIR.exists():
        return out
    for path in sorted(_SAMPLE_DIR.glob("*.json")):
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            snap_dict = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else data
            out.append({
                "key": path.stem,
                "name": snap_dict.get("name", path.stem),
                "description": snap_dict.get("export_notes", ""),
                "n_positions": int(snap_dict.get("n_positions", len(snap_dict.get("allocation", []) or []))),
                "profile_name": snap_dict.get("profile_name", ""),
            })
        except Exception as exc:
            logger.warning(f"Sample plan '{path.name}' could not be read: {exc}")
    return sorted(out, key=lambda d: d["name"])


def load_sample_plan(key: str) -> PlanSnapshot:
    """Load a bundled sample plan by key into a PlanSnapshot (Fase H.4).

    Reuses ``import_plan_from_dict`` so samples follow the exact same
    validation/forward-compat path as user imports. Raises ``ValueError`` if the
    key is unknown or the file is invalid.
    """
    path = _SAMPLE_DIR / f"{key}.json"
    if not path.exists():
        raise ValueError(f"Plan de ejemplo desconocido: '{key}'.")
    data = _json.loads(path.read_text(encoding="utf-8"))
    return import_plan_from_dict(data)


def is_active(plan_id: str, prefs=None) -> bool:
    """True if ``plan_id`` is the currently active plan."""
    prefs = _load_prefs(prefs)
    return (getattr(prefs, "active_plan_id", "") or "").strip() == plan_id


# ------------------------------------------------------------------ #
#  Plan vs. reality (market delta + health)                          #
# ------------------------------------------------------------------ #

def compute_plan_vs_reality(
    snap: PlanSnapshot,
    price_lookup: PriceLookup,
    *,
    core_only: bool = False,
) -> dict:
    """Compare a saved plan against today's market.

    Parameters
    ----------
    snap : PlanSnapshot
        The plan to evaluate.
    price_lookup : callable
        ``symbol -> current_price`` (or None). Network/cache access is the
        caller's concern; failures per-ticker are tolerated.
    core_only : bool
        When True, only the core holdings are priced (cheaper; used for a
        quick "core health" check). Otherwise the full allocation is priced.

    Returns
    -------
    dict with:
        rows : list of per-ticker dicts
            {symbol, weight_pct, score_then, price_then, price_now, delta_pct}
        summary : dict
            {weighted_delta_pct, n_priced, n_total, n_with_baseline,
             avg_score_then, gainers, losers}
        refreshed_at : ISO timestamp
    """
    if core_only and snap.core_holdings:
        items = [
            {
                "symbol": c.get("symbol", ""),
                "weight_pct": float(c.get("suggested_weight_pct", 0.0)),
                "adjusted_score": None,
                "price_at_save": None,
            }
            for c in snap.core_holdings
            if c.get("symbol")
        ]
    else:
        items = [
            {
                "symbol": a.get("symbol", ""),
                "weight_pct": float(a.get("weight_pct", 0.0)),
                "adjusted_score": a.get("adjusted_score"),
                "price_at_save": a.get("price_at_save"),
            }
            for a in snap.allocation
            if a.get("symbol")
        ]

    rows: List[dict] = []
    weighted_delta_num = 0.0
    weighted_delta_den = 0.0
    n_priced = 0
    n_with_baseline = 0
    score_sum = 0.0
    score_n = 0

    for it in items:
        sym = it["symbol"]
        weight = it["weight_pct"]
        score_then = it.get("adjusted_score")
        price_then = it.get("price_at_save")

        try:
            raw = price_lookup(sym)
            price_now = float(raw) if raw and float(raw) > 0 else None
        except Exception as exc:
            logger.debug(f"plan refresh: price lookup failed for {sym} — {exc}")
            price_now = None

        if price_now is not None:
            n_priced += 1

        delta_pct: Optional[float] = None
        if price_then and price_then > 0 and price_now is not None:
            delta_pct = (price_now - price_then) / price_then * 100.0
            n_with_baseline += 1
            weighted_delta_num += weight * delta_pct
            weighted_delta_den += weight

        if score_then is not None:
            score_sum += float(score_then)
            score_n += 1

        rows.append({
            "symbol": sym,
            "weight_pct": round(weight, 2),
            "score_then": round(float(score_then), 1) if score_then is not None else None,
            "price_then": round(float(price_then), 2) if price_then else None,
            "price_now": round(price_now, 2) if price_now is not None else None,
            "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
        })

    rows.sort(key=lambda r: r["weight_pct"], reverse=True)

    weighted_delta = (
        round(weighted_delta_num / weighted_delta_den, 1)
        if weighted_delta_den > 0 else None
    )
    gainers = sum(1 for r in rows if r["delta_pct"] is not None and r["delta_pct"] > 0)
    losers = sum(1 for r in rows if r["delta_pct"] is not None and r["delta_pct"] < 0)

    return {
        "rows": rows,
        "summary": {
            "weighted_delta_pct": weighted_delta,
            "n_priced": n_priced,
            "n_total": len(items),
            "n_with_baseline": n_with_baseline,
            "avg_score_then": round(score_sum / score_n, 1) if score_n else None,
            "gainers": gainers,
            "losers": losers,
        },
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
    }


# ------------------------------------------------------------------ #
#  Longitudinal plan-health history (Fase H.2)                         #
# ------------------------------------------------------------------ #

def record_plan_health(
    snap: PlanSnapshot,
    price_lookup: PriceLookup,
    *,
    source: str = "manual",
    refreshed: Optional[dict] = None,
    min_days_between: int = 0,
):
    """Capture a longitudinal health record for a plan (Fase H.2).

    Computes plan-vs-reality (unless ``refreshed`` is supplied to avoid a second
    price fetch) and appends a lightweight ``PlanHealthRecord`` to the store.
    Returns the record, or None when skipped by the dedup window. Pure w.r.t.
    Streamlit; network access is injected via ``price_lookup``.
    """
    from config import HEALTH
    from data.plan_health import PlanHealthRecord, plan_health_store

    if refreshed is None:
        refreshed = compute_plan_vs_reality(snap, price_lookup)
    record = PlanHealthRecord.from_plan(snap, refreshed, source=source)
    return plan_health_store.append(
        record,
        min_days_between=min_days_between,
        max_records=HEALTH.max_records,
    )


def get_plan_health_history(plan_id: str) -> List[dict]:
    """Return a plan's health records (oldest first) as plain dicts for the UI."""
    from data.plan_health import plan_health_store

    return [r.to_dict() for r in plan_health_store.history(plan_id)]


def compute_longitudinal_drift(history: List[dict]) -> dict:
    """Summarize a plan's health trend + flag structural degradation (Fase H.2).

    ``history`` is the chronological list of record dicts from
    ``get_plan_health_history``. Returns a dict with the trend series (for
    charting) and a ``degraded`` flag driven by ``config.HEALTH`` thresholds:
    a sustained high weighted drift across the most recent records marks the
    plan as "aged / degraded".
    """
    from config import HEALTH

    n = len(history)
    base = {
        "n_records": n,
        "first_recorded_at": history[0]["recorded_at"] if n else None,
        "last_recorded_at": history[-1]["recorded_at"] if n else None,
        "latest_drift_pct": None,
        "min_drift_pct": None,
        "max_drift_pct": None,
        "latest_data_quality_pct": None,
        "degraded": False,
        "degraded_reason": "",
    }
    if n == 0:
        return base

    drifts = [float(r["weighted_delta_pct"]) for r in history
              if r.get("weighted_delta_pct") is not None]
    latest = history[-1]
    base["latest_drift_pct"] = latest.get("weighted_delta_pct")
    base["latest_data_quality_pct"] = latest.get("data_quality_pct")
    if drifts:
        base["min_drift_pct"] = round(min(drifts), 1)
        base["max_drift_pct"] = round(max(drifts), 1)

    # Degradation: the most recent ``degradation_min_records`` records all show
    # |weighted drift| ≥ threshold → sustained structural drift, not noise.
    need = max(1, int(HEALTH.degradation_min_records))
    if n >= need:
        recent = history[-need:]
        recent_drifts = [r.get("weighted_delta_pct") for r in recent]
        if all(d is not None and abs(float(d)) >= HEALTH.degradation_drift_pct
               for d in recent_drifts):
            base["degraded"] = True
            base["degraded_reason"] = (
                f"Deriva ponderada sostenida ≥{HEALTH.degradation_drift_pct:.0f}% en "
                f"los últimos {need} registros (último {float(recent_drifts[-1]):+.1f}%)."
            )
    return base


# ------------------------------------------------------------------ #
#  Canonical drift math (U2-3)                                         #
# ------------------------------------------------------------------ #

def drift_breakdown(
    target_weights: Dict[str, float],
    actual_weights: Dict[str, float],
) -> dict:
    """Canonical plan-vs-reality drift math — the only implementation (U2-3).

    Three surfaces report drift: the alert detector
    (``alerts/portfolio_alerts.py``), the suggested alignment trades
    (``compute_alignment_trades`` below) and the Portfolio page. Each used to
    re-derive the arithmetic, and the detector iterated **only the target**, so
    a position held outside the plan contributed ``0`` to the aggregate: the UI
    said "rebalance" while the alert never fired. Everything now goes through
    here so they cannot disagree again.

    Parameters
    ----------
    target_weights : dict
        ``{symbol: target_weight_pct (0-100)}`` — what the plan asks for.
    actual_weights : dict
        ``{symbol: actual_weight_pct (0-100)}`` — what the tracker holds.
        Symbols priced as *unknown* must be left out entirely; a missing price
        is not a 0 % weight (that is the caller's job — see the detector).

    Returns
    -------
    dict with:
        symbols : sorted union of both sides
        rows    : [{symbol, target_pct, actual_pct, drift_pct}] — ``drift_pct``
                  is signed (``actual - target``): positive = over the target.
        total_drift_pct : aggregate drift, **unrounded** so callers keep their
                  own rounding. Each deviation is counted twice (one symbol
                  over, another under), hence the halving.
        n_evaluated : ``len(symbols)``
    """
    target = target_weights or {}
    actual = actual_weights or {}
    symbols = sorted(set(target) | set(actual))

    rows: List[dict] = []
    total_abs_drift = 0.0
    for sym in symbols:
        t = float(target.get(sym, 0.0) or 0.0)
        a = float(actual.get(sym, 0.0) or 0.0)
        d = a - t
        total_abs_drift += abs(d)
        rows.append({
            "symbol": sym,
            "target_pct": t,
            "actual_pct": a,
            "drift_pct": d,
        })

    return {
        "symbols": symbols,
        "rows": rows,
        "total_drift_pct": total_abs_drift / 2.0,
        "n_evaluated": len(symbols),
    }


# ------------------------------------------------------------------ #
#  Suggested alignment trades (Fase E)                                 #
# ------------------------------------------------------------------ #

def compute_alignment_trades(
    snap: PlanSnapshot,
    current_weights: Dict[str, float],
    total_value: float,
    *,
    price_lookup: Optional[PriceLookup] = None,
    drift_threshold_pct: Optional[float] = None,
    min_trade_usd: Optional[float] = None,
    max_trades: Optional[int] = None,
) -> dict:
    """Suggest concrete, prioritized trades that move the real portfolio
    toward the plan's target weights.

    Closes the "living plan" action loop: from *"I can see I drifted"* to
    *"these are the N trades (with USD amounts) that re-align me"*.
    Pure + injectable (no Streamlit, optional ``price_lookup``) so it is
    unit-testable offline and reusable by the dashboard and the scheduler.

    Parameters
    ----------
    snap : PlanSnapshot
        The (active) plan — its ``target_weights()`` are the goal.
    current_weights : dict
        ``{symbol: actual_weight_pct (0–100)}`` from the tracker.
    total_value : float
        Current total portfolio market value in USD (sizes the trades).
    price_lookup : callable, optional
        ``symbol -> price``; when given, an estimated share count is added.
    drift_threshold_pct / min_trade_usd / max_trades :
        Default to ``ALERTS.portfolio_drift_threshold_pct``,
        ``ALERTS.alignment_min_trade_usd`` and ``ALERTS.alignment_max_trades``
        from config — never hardcoded here.

    Returns
    -------
    dict with:
        trades : list of dicts, prioritized (core first, then by USD size)
            {symbol, action ("comprar"|"vender"), is_core,
             target_pct, actual_pct, drift_pct, amount_usd,
             price_now, est_shares}
        summary : {total_drift_pct, n_evaluated, n_suggested, n_skipped_small,
                   buy_usd, sell_usd, threshold_pct, min_trade_usd}
    """
    from config import ALERTS

    if drift_threshold_pct is None:
        drift_threshold_pct = ALERTS.portfolio_drift_threshold_pct
    if min_trade_usd is None:
        min_trade_usd = ALERTS.alignment_min_trade_usd
    if max_trades is None:
        max_trades = ALERTS.alignment_max_trades

    target = snap.target_weights()
    core_symbols = {c.get("symbol", "") for c in snap.core_holdings if c.get("symbol")}
    breakdown = drift_breakdown(target, current_weights)

    candidates: List[dict] = []
    n_skipped_small = 0

    for row in breakdown["rows"]:
        sym = row["symbol"]
        t = row["target_pct"]
        a = row["actual_pct"]
        drift = row["drift_pct"]

        if abs(drift) < drift_threshold_pct:
            continue

        amount_usd = abs(drift) / 100.0 * max(total_value, 0.0)
        if amount_usd < min_trade_usd:
            n_skipped_small += 1
            continue

        price_now: Optional[float] = None
        if price_lookup is not None:
            try:
                raw = price_lookup(sym)
                price_now = float(raw) if raw and float(raw) > 0 else None
            except Exception as exc:
                logger.debug(f"alignment trades: price lookup failed for {sym} — {exc}")

        candidates.append({
            "symbol": sym,
            "action": "vender" if drift > 0 else "comprar",
            "is_core": sym in core_symbols,
            "target_pct": round(t, 1),
            "actual_pct": round(a, 1),
            "drift_pct": round(drift, 1),
            "amount_usd": round(amount_usd),
            "price_now": round(price_now, 2) if price_now is not None else None,
            "est_shares": round(amount_usd / price_now, 2) if price_now else None,
        })

    # Prioritize: core positions first, then by trade size (descending).
    candidates.sort(key=lambda c: (not c["is_core"], -c["amount_usd"]))
    trades = candidates[: max(int(max_trades), 0)]

    return {
        "trades": trades,
        "summary": {
            # Canonical drift math lives in drift_breakdown() (U2-3): union of
            # target and actual, each deviation counted twice (over + under).
            "total_drift_pct": round(breakdown["total_drift_pct"], 1),
            "n_evaluated": breakdown["n_evaluated"],
            "n_suggested": len(trades),
            "n_skipped_small": n_skipped_small,
            "buy_usd": round(sum(t["amount_usd"] for t in trades if t["action"] == "comprar")),
            "sell_usd": round(sum(t["amount_usd"] for t in trades if t["action"] == "vender")),
            "threshold_pct": float(drift_threshold_pct),
            "min_trade_usd": float(min_trade_usd),
        },
    }
