"""
Retirement-plan persistence (Fase B).

Persists named "plan snapshots" so the user's work in Optimizer + Mis Metas +
Monte Carlo stops living only in ephemeral session_state. A snapshot is a
lightweight, JSON-serializable summary of a plan — it does NOT store the full
OptimizationResult object (heavy + non-portable); instead it captures the
human-relevant artifacts: target allocation, deterministic/Grok core holdings,
portfolio metrics, goals, Monte Carlo summary and the AI narrative.

Mirrors the load/save pattern of data.preferences.UserPreferences.

Usage:
    from data.plan_store import PlanSnapshot, plan_store
    snap = PlanSnapshot.from_session(opt_result, goals, mc_result, mc_params, prefs, name="Retiro 2045")
    plan_store.upsert(snap)
    plans = plan_store.list()          # newest first
    plan_store.delete(snap.id)
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger

from config import ENGINE_VERSION
from data.env_provenance import env_drift, numeric_env
from data.product_ux import mc_has_cash_flows

_PLANS_PATH = Path(__file__).parent / "retirement_plans.json"


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    return s or "plan"


def unique_plan_id(base_id: str, taken: Callable[[str], bool]) -> str:
    """Return ``base_id``, or ``base_id-2`` / ``-3`` … when it is already taken.

    Plan ids are derived from the name (``_slugify``), so two unrelated plans can
    claim the same id — and ``PlanStore.upsert`` replaces by id. That is the
    intended behaviour when *saving* (the UI warns first), but importing a backup
    must never silently destroy a homonymous local plan. ``taken`` is injected
    (``lambda pid: plan_store.get(pid) is not None``) so this stays pure.
    """
    base = (base_id or "").strip() or "plan"
    if not taken(base):
        return base
    n = 2
    while taken(f"{base}-{n}"):
        n += 1
    return f"{base}-{n}"


# ------------------------------------------------------------------ #
#  PlanSnapshot                                                        #
# ------------------------------------------------------------------ #

@dataclass
class PlanSnapshot:
    """A persisted, JSON-serializable summary of a retirement plan."""

    id: str
    name: str
    created_at: str
    updated_at: str

    # Profile / universe context
    profile_name: str = ""
    profile_key: str = ""
    universe_key: str = ""
    universe_name: str = ""
    n_positions: int = 0

    # Target allocation (full optimized portfolio)
    allocation: List[dict] = field(default_factory=list)      # [{symbol, weight_pct, sector, dividend_yield_pct, adjusted_score}]
    sector_weights: Dict[str, float] = field(default_factory=dict)

    # Human-scale core (deterministic, or Grok if available)
    core_holdings: List[dict] = field(default_factory=list)   # [{symbol, suggested_weight_pct, why}]
    core_from_ai: bool = False

    # Portfolio-level metrics
    metrics: Dict[str, float] = field(default_factory=dict)

    # Goals (serialized) + Monte Carlo summary
    goals: List[dict] = field(default_factory=list)
    mc_summary: Optional[dict] = None

    # AI narrative + personal-profile snapshot
    narrative: str = ""
    personal: Optional[dict] = None

    # ------------------------------------------------------------------ #
    #  Living-plan fields (Fase C) — all optional, backward-compatible.   #
    #  Populated when the user "refreshes" a saved plan against today's   #
    #  market. Kept lightweight: prices + a small re-computed metrics map.#
    # ------------------------------------------------------------------ #
    last_refreshed_at: str = ""                                  # ISO ts of last market refresh ("" = never)
    refreshed_metrics: Optional[dict] = None                    # {symbol: {price_then, price_now, delta_pct}, ...} + summary
    macro_risks: List[dict] = field(default_factory=list)       # top 1-2 portfolio-level macro factors (Fase D enrichment)

    # ------------------------------------------------------------------ #
    #  Item 1 — economic drags active when the plan was generated, so an  #
    #  old plan "remembers" under which assumptions it was built. None /   #
    #  empty for plans saved before the feature (backward-compatible).     #
    # ------------------------------------------------------------------ #
    drags_at_save: Optional[dict] = None

    # ------------------------------------------------------------------ #
    #  Item 2 — portability metadata. export_version lets imported bundles #
    #  stay forward-compatible; export_notes is a free-text user note.     #
    # ------------------------------------------------------------------ #
    export_version: str = "1.0"
    export_notes: str = ""

    # ------------------------------------------------------------------ #
    #  Numeric-engine provenance. Distinct from export_version (that is    #
    #  the FILE format; this is the MATHS). Empty for plans saved before   #
    #  the 2026-08 Tier 0 fix — those carry decumulation figures that      #
    #  overstated terminal wealth, so the UI flags them as stale and       #
    #  offers to re-simulate. See docs/AUDITORIA_2026-08.md.               #
    # ------------------------------------------------------------------ #
    engine_version: str = ""

    # ------------------------------------------------------------------ #
    #  Numeric-environment provenance (audit D5). engine_version says which #
    #  of OUR maths produced the figures; this says which build of numpy /  #
    #  scipy / pandas executed them. A scipy bump can move SLSQP to a       #
    #  different optimum and a numpy bump can move percentiles, so without  #
    #  this a saved plan cannot be reproduced, only believed. Empty for     #
    #  plans saved before sealing — unknown, not "same".                    #
    # ------------------------------------------------------------------ #
    lib_versions: Optional[dict] = None

    # ------------------------------------------------------------------ #
    #  Fase H.1 — decumulation strategy active when the plan was built,   #
    #  so an activated plan "remembers" how it intends to spend down.     #
    #  None for plans saved before the feature (backward-compatible).     #
    # ------------------------------------------------------------------ #
    withdrawal_strategy: Optional[dict] = None

    # ------------------------------------------------------------------ #

    def target_weights(self) -> Dict[str, float]:
        """Return {symbol: target_weight_pct (0–100)} from the saved allocation.

        This is the plan's allocation used as the drift target by the alerts
        engine and the Portfolio alignment view. Falls back to the core
        holdings when no full allocation was persisted.
        """
        if self.allocation:
            return {
                a.get("symbol", ""): float(a.get("weight_pct", 0.0))
                for a in self.allocation
                if a.get("symbol")
            }
        return {
            c.get("symbol", ""): float(c.get("suggested_weight_pct", 0.0))
            for c in self.core_holdings
            if c.get("symbol")
        }

    @classmethod
    def from_session(
        cls,
        *,
        name: str,
        opt_result,
        goals: Optional[List[dict]] = None,
        mc_result=None,
        mc_params: Optional[dict] = None,
        prefs=None,
        universe_key: str = "",
        universe_name: str = "",
        narrative: str = "",
        existing_id: Optional[str] = None,
        existing_created_at: Optional[str] = None,
        price_lookup: Optional[Callable[[str], Optional[float]]] = None,
        drags: Optional[dict] = None,
        withdrawal_strategy: Optional[dict] = None,
    ) -> "PlanSnapshot":
        """Build a snapshot from the live optimizer/goals/MC objects + prefs.

        ``price_lookup`` (Fase C): optional ``symbol -> price`` callable. When
        provided, the per-ticker market price at save time is captured into
        each allocation entry as ``price_at_save`` so that loading the plan
        later can show a true "price then vs now" delta. The callable is wrapped
        defensively — any failure simply omits the price for that ticker.
        """
        now = datetime.now().isoformat(timespec="seconds")
        goals = goals or []
        mc_params = mc_params or {}

        def _price_at_save(symbol: str) -> Optional[float]:
            if price_lookup is None:
                return None
            try:
                p = price_lookup(symbol)
                return round(float(p), 4) if p and float(p) > 0 else None
            except Exception:
                return None

        allocation = []
        for a in getattr(opt_result, "tickers", []):
            entry = {
                "symbol":             a.symbol,
                "weight_pct":         round(float(a.weight_pct), 2),
                "sector":             getattr(a, "sector", "") or "",
                "dividend_yield_pct": round(float(getattr(a, "dividend_yield_pct", 0.0)), 2),
                "adjusted_score":     round(float(getattr(a, "adjusted_score", 0.0)), 1),
            }
            _p = _price_at_save(a.symbol)
            if _p is not None:
                entry["price_at_save"] = _p
            # Sector-country structural tailwind (Idea 2): persisted only when
            # material so older snapshots and Neutral tickers stay byte-identical.
            _twc = str(getattr(a, "tailwind_classification", "") or "")
            if _twc and _twc != "Neutral":
                entry["tailwind_classification"] = _twc
                entry["tailwind_score"] = round(float(getattr(a, "tailwind_score", 0.0) or 0.0), 1)
            allocation.append(entry)

        # Prefer Grok core when present, else the deterministic profile core.
        grok_core = getattr(opt_result, "grok_core_holdings", []) or []
        det_core = getattr(opt_result, "profile_core_holdings", []) or []
        core_from_ai = bool(grok_core)
        core_src = grok_core or det_core
        core_holdings = [
            {
                "symbol":              c.get("symbol", ""),
                "suggested_weight_pct": round(float(c.get("suggested_weight_pct", 0.0)), 2),
                "why":                 (c.get("why", "") or "")[:240],
            }
            for c in core_src
        ]

        metrics = {
            "expected_return_pct":       round(float(getattr(opt_result, "expected_return_pct", 0.0)), 2),
            "volatility_pct":            round(float(getattr(opt_result, "volatility_pct", 0.0)), 2),
            "sharpe_ratio":              round(float(getattr(opt_result, "sharpe_ratio", 0.0)), 3),
            "dividend_yield_pct":        round(float(getattr(opt_result, "dividend_yield_pct", 0.0)), 2),
            "adjusted_score_avg":        round(float(getattr(opt_result, "adjusted_score_avg", 0.0)), 1),
            "moat_score_avg":            round(float(getattr(opt_result, "moat_score_avg", 0.0)), 2),
            "max_drawdown_estimate_pct": round(float(getattr(opt_result, "max_drawdown_estimate_pct", 0.0)), 2),
        }

        mc_summary = None
        if mc_result is not None:
            mc_summary = {
                "horizon_years":    mc_params.get("horizon_years"),
                "initial_value":    mc_params.get("initial_value"),
                "inflation_rate":   mc_params.get("inflation_rate"),
                "target_value":     mc_params.get("target_value"),
                "median_terminal":  round(float(getattr(mc_result, "median_terminal", 0.0)), 0),
                "p10_terminal":     round(float(getattr(mc_result, "p10_terminal", 0.0)), 0),
                "p90_terminal":     round(float(getattr(mc_result, "p90_terminal", 0.0)), 0),
                "prob_target_pct":  round(float(getattr(mc_result, "prob_achieve_target_pct", 0.0)), 1),
                "prob_ruin_pct":    round(float(getattr(mc_result, "prob_ruin_pct", 0.0)), 1),
                "median_cagr_pct":  round(float(getattr(mc_result, "median_cagr_pct", 0.0)), 2),
                # U1-7: el bundle se exporta, así que la cifra viaja con el dato
                # que decide qué es. Con flujos `median_cagr_pct` no es un
                # retorno (el capital aportado/retirado mueve el terminal sin
                # mover el inicial). Clave **aditiva**: los planes ya guardados
                # siguen cargando sin ella.
                "mc_has_cash_flows": mc_has_cash_flows(mc_result),
                "sorr_early_drawdown_pct": round(
                    float(getattr(mc_result, "sorr_early_drawdown_pct", 0.0)), 1
                ),
            }
            # Item 1 — persist base (no-drag) reference + the active drag total
            # so a loaded plan can show "base vs con drags" exactly as generated.
            _drag_total = float(getattr(mc_result, "total_annual_drag_pct", 0.0))
            if _drag_total > 0:
                mc_summary["total_annual_drag_pct"] = round(_drag_total, 4)
                mc_summary["base_median_terminal"] = round(float(getattr(mc_result, "base_median_terminal", 0.0)), 0)
                mc_summary["base_p10_terminal"]    = round(float(getattr(mc_result, "base_p10_terminal", 0.0)), 0)
                mc_summary["base_p90_terminal"]    = round(float(getattr(mc_result, "base_p90_terminal", 0.0)), 0)

            # Fase H.1 — persist decumulation outcomes when a withdrawal
            # strategy was simulated, so a loaded plan shows "will my income
            # last?" exactly as generated.
            if getattr(mc_result, "withdrawal_strategy_applied", None):
                mc_summary["prob_sustain_real_pct"]   = round(float(getattr(mc_result, "prob_sustain_real_pct", 0.0)), 1)
                mc_summary["prob_legacy_pct"]         = round(float(getattr(mc_result, "prob_legacy_pct", 0.0)), 1)
                mc_summary["median_legacy"]           = round(float(getattr(mc_result, "median_legacy", 0.0)), 0)
                mc_summary["expected_depletion_year"] = round(float(getattr(mc_result, "expected_depletion_year", 0.0)), 2)
                mc_summary["longevity_years"]         = int(getattr(mc_result, "longevity_years", 0))

        personal = None
        if prefs is not None and getattr(prefs, "is_onboarded", False):
            personal = {
                "age":                  prefs.age,
                "retirement_age":       prefs.retirement_age,
                "primary_horizon_years": prefs.primary_horizon_years,
                "current_capital":      prefs.current_capital,
                "monthly_savings":      prefs.monthly_savings,
                "primary_goal_type":    prefs.primary_goal_type,
            }

        return cls(
            id=existing_id or f"{_slugify(name)}",
            name=name.strip() or "Plan sin nombre",
            created_at=existing_created_at or now,
            updated_at=now,
            profile_name=getattr(opt_result, "profile_name", ""),
            profile_key=getattr(prefs, "profile_key", "") if prefs is not None else "",
            universe_key=universe_key,
            universe_name=universe_name,
            n_positions=len(allocation),
            allocation=allocation,
            sector_weights={k: round(float(v), 2) for k, v in getattr(opt_result, "sector_weights", {}).items()},
            core_holdings=core_holdings,
            core_from_ai=core_from_ai,
            metrics=metrics,
            goals=list(goals),
            mc_summary=mc_summary,
            narrative=narrative or getattr(opt_result, "ai_grok_narrative", "") or "",
            personal=personal,
            drags_at_save=(dict(drags) if drags and drags.get("enabled", True)
                           and (drags.get("total_annual_drag_pct") or 0) > 0 else None),
            withdrawal_strategy=(
                dict(withdrawal_strategy) if withdrawal_strategy
                else (dict(getattr(mc_result, "withdrawal_strategy_applied", None))
                      if getattr(mc_result, "withdrawal_strategy_applied", None) else None)
            ),
            engine_version=ENGINE_VERSION,
            lib_versions=numeric_env(),
        )

    # ------------------------------------------------------------------ #
    #  Reproducibility (audit D5)                                          #
    # ------------------------------------------------------------------ #

    def has_sealed_env(self) -> bool:
        """True when this snapshot recorded the numeric environment it ran in."""
        return bool(self.lib_versions)

    def numeric_env_drift(self) -> Dict[str, tuple]:
        """Return ``{lib: (then, now)}`` for numeric libs that changed since save.

        Empty when nothing moved *or* when the plan predates sealing — use
        :meth:`has_sealed_env` to tell those two apart. This is deliberately
        separate from :meth:`is_engine_stale`: our formulas changing and the
        libraries under them changing are different reasons to re-simulate.
        """
        return env_drift(self.lib_versions)

    def is_engine_stale(self) -> bool:
        """True when this snapshot's figures predate the current numeric engine.

        Plans saved before the 2026-08 Tier 0 fix carry no ``engine_version``
        and their decumulation figures overstated terminal wealth, so the UI
        offers to re-simulate rather than silently showing stale numbers.
        """
        return (self.engine_version or "") != ENGINE_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ #
#  PlanStore                                                           #
# ------------------------------------------------------------------ #

class PlanStore:
    """JSON-backed store of PlanSnapshots (newest first)."""

    def __init__(self, path: Path = _PLANS_PATH) -> None:
        self.path = path

    def _read_raw(self) -> List[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning(f"Could not load plans ({exc}) — starting empty")
            return []

    def _write_raw(self, items: List[dict]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            logger.error(f"Could not save plans: {exc}")

    def list(self) -> List[PlanSnapshot]:
        """Return all snapshots, newest updated first."""
        items = self._read_raw()
        known = {f for f in PlanSnapshot.__dataclass_fields__}
        snaps = [PlanSnapshot(**{k: v for k, v in d.items() if k in known}) for d in items]
        return sorted(snaps, key=lambda s: s.updated_at, reverse=True)

    def get(self, plan_id: str) -> Optional[PlanSnapshot]:
        for s in self.list():
            if s.id == plan_id:
                return s
        return None

    def upsert(self, snapshot: PlanSnapshot) -> None:
        """Insert or replace a snapshot by id."""
        items = [d for d in self._read_raw() if d.get("id") != snapshot.id]
        items.append(snapshot.to_dict())
        self._write_raw(items)
        logger.info(f"Plan saved: {snapshot.name} ({snapshot.id})")

    def delete(self, plan_id: str) -> bool:
        items = self._read_raw()
        remaining = [d for d in items if d.get("id") != plan_id]
        if len(remaining) == len(items):
            return False
        self._write_raw(remaining)
        return True


# Module-level singleton (mirrors data.preferences pattern)
plan_store = PlanStore()
