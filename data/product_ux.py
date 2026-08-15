"""
Product UX helpers — pure, Streamlit-free functions for the backlog 1–15 surface.

These powers Home hub, gap-to-goal levers, annual checklist, deep plan compare,
track-record one-liner, market-drop coach predicate, AR dual-currency display,
chat missing-context copy, and decision-quality labels.

All thresholds that are product knobs live in ``config`` (CoachConfig, ArFxConfig).
No network. Fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


# --------------------------------------------------------------------------- #
#  Future-value primitives (used by gap-to-goal)                              #
# --------------------------------------------------------------------------- #

def _fv_lump_and_annuity(
    capital: float,
    annual_contribution: float,
    years: float,
    annual_return: float,
) -> float:
    """End value of capital compounded + end-of-year contributions (simple annuity)."""
    r = float(annual_return)
    t = max(float(years), 0.0)
    c = max(float(capital), 0.0)
    a = max(float(annual_contribution), 0.0)
    if t <= 0:
        return c
    if abs(r) < 1e-12:
        return c + a * t
    growth = (1.0 + r) ** t
    return c * growth + a * (growth - 1.0) / r


def _years_to_reach(
    capital: float,
    annual_contribution: float,
    annual_return: float,
    target: float,
    max_years: int = 80,
) -> Optional[int]:
    """Smallest whole years so FV >= target, or None if unreachable within max_years."""
    if target <= capital:
        return 0
    for y in range(1, max_years + 1):
        if _fv_lump_and_annuity(capital, annual_contribution, y, annual_return) >= target:
            return y
    return None


def _extra_annual_needed(
    capital: float,
    annual_contribution: float,
    years: float,
    annual_return: float,
    target: float,
) -> float:
    """Additional annual contribution so FV hits target (0 if already there)."""
    base = _fv_lump_and_annuity(capital, annual_contribution, years, annual_return)
    if base >= target:
        return 0.0
    r = float(annual_return)
    t = max(float(years), 0.0)
    if t <= 0:
        return max(target - capital, 0.0)
    if abs(r) < 1e-12:
        gap = target - capital - annual_contribution * t
        return max(gap / t, 0.0)
    growth = (1.0 + r) ** t
    # Solve: C*g + (A+X)*(g-1)/r >= T  →  X >= (T - C*g)*r/(g-1) - A
    needed_total_annuity = (target - capital * growth) * r / (growth - 1.0)
    return max(needed_total_annuity - annual_contribution, 0.0)


# --------------------------------------------------------------------------- #
#  1 — Home plan hub payload                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class HomePlanHub:
    """What Home needs to answer “¿cómo viene tu plan?” without a live fetch."""

    has_plan: bool
    plan_name: str = ""
    prob_target_pct: Optional[float] = None
    median_terminal: Optional[float] = None
    expected_return_pct: Optional[float] = None
    drift_pct: Optional[float] = None  # weighted_delta from last refresh, if any
    data_age_days: Optional[int] = None
    unread_alerts: int = 0
    primary_action: Dict[str, str] = field(default_factory=dict)
    sample_plan_available: bool = False
    track_record_line: str = ""
    empty_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "has_plan": self.has_plan,
            "plan_name": self.plan_name,
            "prob_target_pct": self.prob_target_pct,
            "median_terminal": self.median_terminal,
            "expected_return_pct": self.expected_return_pct,
            "drift_pct": self.drift_pct,
            "data_age_days": self.data_age_days,
            "unread_alerts": self.unread_alerts,
            "primary_action": dict(self.primary_action),
            "sample_plan_available": self.sample_plan_available,
            "track_record_line": self.track_record_line,
            "empty_reason": self.empty_reason,
        }


def build_home_plan_hub(
    *,
    plan_snapshot: Any = None,
    primary_action: Optional[Mapping[str, str]] = None,
    unread_alerts: int = 0,
    sample_plan_available: bool = False,
    track_record_line: str = "",
    data_age_days: Optional[int] = None,
) -> HomePlanHub:
    """Assemble Home hub fields from an optional PlanSnapshot-like object."""
    action = dict(primary_action or {})
    if plan_snapshot is None:
        return HomePlanHub(
            has_plan=False,
            primary_action=action,
            sample_plan_available=sample_plan_available,
            track_record_line=track_record_line or "",
            unread_alerts=int(unread_alerts or 0),
            empty_reason="Todavía no tenés un plan activo. Probá un plan de ejemplo o completá el camino guiado.",
        )

    mc = getattr(plan_snapshot, "mc_summary", None) or {}
    metrics = getattr(plan_snapshot, "metrics", None) or {}
    refreshed = getattr(plan_snapshot, "refreshed_metrics", None) or {}
    summary = refreshed.get("summary") if isinstance(refreshed, dict) else None
    if not isinstance(summary, dict):
        summary = {}

    drift = summary.get("weighted_delta_pct")
    if drift is not None:
        try:
            drift = float(drift)
        except (TypeError, ValueError):
            drift = None

    prob = mc.get("prob_target_pct")
    if prob is not None:
        try:
            prob = float(prob)
        except (TypeError, ValueError):
            prob = None

    median = mc.get("median_terminal")
    if median is not None:
        try:
            median = float(median)
        except (TypeError, ValueError):
            median = None

    exp_ret = metrics.get("expected_return_pct")
    if exp_ret is not None:
        try:
            exp_ret = float(exp_ret)
        except (TypeError, ValueError):
            exp_ret = None

    return HomePlanHub(
        has_plan=True,
        plan_name=str(getattr(plan_snapshot, "name", "") or ""),
        prob_target_pct=prob,
        median_terminal=median,
        expected_return_pct=exp_ret,
        drift_pct=drift,
        data_age_days=data_age_days,
        unread_alerts=int(unread_alerts or 0),
        primary_action=action,
        sample_plan_available=sample_plan_available,
        track_record_line=track_record_line or "",
    )


# --------------------------------------------------------------------------- #
#  3 — Gap-to-goal levers                                                     #
# --------------------------------------------------------------------------- #

@dataclass
class GapLever:
    kind: str           # more_savings | more_years | lower_target | higher_return
    label: str
    detail: str
    value: float        # magnitude (USD/year, years, target USD, return delta pp)
    unit: str
    cta_hint: str       # where to act in the product

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "detail": self.detail,
            "value": self.value,
            "unit": self.unit,
            "cta_hint": self.cta_hint,
        }


def compute_gap_to_goal_levers(
    *,
    capital: float,
    annual_contribution: float,
    years: float,
    annual_return: float,
    target: float,
    prob_achieve_pct: Optional[float] = None,
    soft_threshold_pct: float = 70.0,
) -> List[dict]:
    """Concrete levers when the projection is unlikely to hit the goal.

    Uses closed-form FV (not Monte Carlo) so the UI can show *numbers* instantly.
    Returns [] when target is missing, already reachable under the simple model,
    or when probability (if provided) is already comfortable.
    """
    if target is None or float(target) <= 0:
        return []
    if prob_achieve_pct is not None and float(prob_achieve_pct) >= soft_threshold_pct:
        # Still offer levers if the simple FV is short of target (conservative floor).
        fv = _fv_lump_and_annuity(capital, annual_contribution, years, annual_return)
        if fv >= float(target):
            return []

    capital = max(float(capital), 0.0)
    annual_contribution = max(float(annual_contribution), 0.0)
    years = max(float(years), 1.0)
    annual_return = float(annual_return)
    target = float(target)

    fv = _fv_lump_and_annuity(capital, annual_contribution, years, annual_return)
    levers: List[GapLever] = []

    extra_annual = _extra_annual_needed(capital, annual_contribution, years, annual_return, target)
    if extra_annual > 0:
        monthly = extra_annual / 12.0
        levers.append(GapLever(
            kind="more_savings",
            label="Aportar más por mes",
            detail=(
                f"Sumá ~${monthly:,.0f}/mes (${extra_annual:,.0f}/año) para llegar a "
                f"${target:,.0f} en {years:.0f} años con retorno ~{annual_return*100:.1f}%."
            ),
            value=round(monthly, 2),
            unit="usd_per_month",
            cta_hint="Simulaciones → Mis Metas / perfil de ahorro · Mi Plan",
        ))

    need_years = _years_to_reach(capital, annual_contribution, annual_return, target)
    if need_years is not None and need_years > years:
        extra_y = int(need_years - years)
        levers.append(GapLever(
            kind="more_years",
            label="Extender el horizonte",
            detail=(
                f"Con el aporte actual, la meta se alcanza en ~{need_years} años "
                f"(+{extra_y} vs los {years:.0f} planificados)."
            ),
            value=float(extra_y),
            unit="years",
            cta_hint="Simulaciones → horizonte · Mi Plan",
        ))

    # Lower target to what is achievable at current path (median-style FV).
    if fv > 0 and fv < target:
        cut_pct = (1.0 - fv / target) * 100.0
        levers.append(GapLever(
            kind="lower_target",
            label="Ajustar la meta",
            detail=(
                f"Con el camino actual el valor proyectado es ~${fv:,.0f}. "
                f"Bajar la meta un ~{cut_pct:.0f}% la pone al alcance."
            ),
            value=round(fv, 0),
            unit="usd_achievable",
            cta_hint="Simulaciones → meta de capital",
        ))

    # Higher return: how many extra pp of annual return close the gap (capped search).
    if fv < target:
        for extra_pp in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0):
            r2 = annual_return + extra_pp / 100.0
            if _fv_lump_and_annuity(capital, annual_contribution, years, r2) >= target:
                levers.append(GapLever(
                    kind="higher_return",
                    label="Más retorno (más riesgo)",
                    detail=(
                        f"Un retorno ~{extra_pp:.1f} pp mayor al actual "
                        f"({annual_return*100:.1f}% → {(annual_return + extra_pp/100)*100:.1f}%) "
                        "alcanzaría la meta en el mismo horizonte — implica más volatilidad."
                    ),
                    value=float(extra_pp),
                    unit="return_pp",
                    cta_hint="Optimizer → perfil de riesgo · Portfolio",
                ))
                break

    return [lv.as_dict() for lv in levers]


# --------------------------------------------------------------------------- #
#  8 — Annual “qué hacer este año” checklist                                  #
# --------------------------------------------------------------------------- #

def build_annual_action_list(
    *,
    plan_snapshot: Any = None,
    monthly_savings: float = 0.0,
    has_portfolio_positions: bool = False,
    drift_pct: Optional[float] = None,
    drift_threshold_pct: float = 5.0,
    last_backup_days: Optional[int] = None,
    review_every_months: int = 6,
) -> List[dict]:
    """Actionable checklist for the next 12 months from plan + optional drift."""
    actions: List[dict] = []
    personal = {}
    if plan_snapshot is not None:
        personal = getattr(plan_snapshot, "personal", None) or {}
        name = str(getattr(plan_snapshot, "name", "") or "tu plan")
    else:
        name = "tu plan"

    annual = float(monthly_savings or 0.0) * 12.0
    if annual <= 0 and personal:
        try:
            annual = float(personal.get("annual_savings") or 0.0)
        except (TypeError, ValueError):
            annual = 0.0
        if annual <= 0:
            try:
                annual = float(personal.get("monthly_savings") or 0.0) * 12.0
            except (TypeError, ValueError):
                annual = 0.0

    if annual > 0:
        actions.append({
            "id": "contribute",
            "priority": 1,
            "title": f"Aportar ~${annual/12:,.0f}/mes a {name}",
            "detail": f"Meta de aporte anual: ${annual:,.0f} (según tu perfil/plan).",
            "when": "mensual",
            "cta_page": "12_Plan.py",
        })
    else:
        actions.append({
            "id": "define_savings",
            "priority": 1,
            "title": "Definí cuánto podés aportar este año",
            "detail": "Sin un aporte planificado la proyección es solo teórica.",
            "when": "esta semana",
            "cta_page": "9_Settings.py",
        })

    if has_portfolio_positions:
        rebalance_due = (
            drift_pct is not None and abs(float(drift_pct)) >= float(drift_threshold_pct)
        )
        actions.append({
            "id": "rebalance",
            "priority": 2 if rebalance_due else 3,
            "title": (
                "Rebalanceá hacia el plan (desvío material)"
                if rebalance_due
                else "Revisá alineación plan vs cartera"
            ),
            "detail": (
                f"Deriva ponderada ~{float(drift_pct):+.1f}% vs umbral {drift_threshold_pct:.0f}%."
                if drift_pct is not None
                else "Compará pesos objetivo del plan con tus posiciones reales."
            ),
            "when": "ahora" if rebalance_due else f"cada {review_every_months} meses",
            "cta_page": "3_Portfolio.py",
        })
    else:
        actions.append({
            "id": "fund_core",
            "priority": 2,
            "title": "Cargá o ejecutá la lista de compra del núcleo",
            "detail": "Sin posiciones reales el plan no se puede monitorear.",
            "when": "este mes",
            "cta_page": "12_Plan.py",
        })

    actions.append({
        "id": "review_plan",
        "priority": 3,
        "title": "Revisión de salud del plan",
        "detail": "Refrescá precios, registrá evolución y regenerá la narrativa si cambió el mercado.",
        "when": f"cada {review_every_months} meses",
        "cta_page": "12_Plan.py",
    })

    if last_backup_days is None or last_backup_days > 90:
        actions.append({
            "id": "backup",
            "priority": 2,
            "title": "Exportá un respaldo del plan (JSON)",
            "detail": "Los datos viven en tu máquina: un backup evita perder el trabajo.",
            "when": "esta semana" if last_backup_days is None else "pronto",
            "cta_page": "12_Plan.py",
        })

    actions.append({
        "id": "stress_check",
        "priority": 4,
        "title": "Corré un stress test o sensibilidad",
        "detail": "Confirmá que un mal año no rompe el plan de retiro.",
        "when": "1–2 veces al año",
        "cta_page": "7_Simulaciones.py",
    })

    actions.sort(key=lambda a: a["priority"])
    return actions


# --------------------------------------------------------------------------- #
#  7 — Deep plan compare                                                      #
# --------------------------------------------------------------------------- #

def _safe_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _plan_field_map(snap: Any) -> Dict[str, Any]:
    """Normalize a PlanSnapshot (or duck-type) into comparable scalar fields."""
    if snap is None:
        return {}
    mc = getattr(snap, "mc_summary", None) or {}
    metrics = getattr(snap, "metrics", None) or {}
    personal = getattr(snap, "personal", None) or {}
    drags = getattr(snap, "drags_at_save", None) or {}
    wd = getattr(snap, "withdrawal_strategy", None) or {}
    alloc = getattr(snap, "allocation", None) or []
    top = []
    if isinstance(alloc, list):
        ranked = sorted(
            [a for a in alloc if isinstance(a, dict)],
            key=lambda a: float(a.get("weight_pct") or 0),
            reverse=True,
        )
        top = [f"{a.get('symbol', '?')} {float(a.get('weight_pct') or 0):.1f}%" for a in ranked[:5]]

    return {
        "name": str(getattr(snap, "name", "") or ""),
        "profile": str(getattr(snap, "profile_name", "") or getattr(snap, "profile_key", "") or ""),
        "n_positions": int(getattr(snap, "n_positions", 0) or 0),
        "expected_return_pct": _safe_float(metrics.get("expected_return_pct")),
        "volatility_pct": _safe_float(metrics.get("volatility_pct")),
        "sharpe_ratio": _safe_float(metrics.get("sharpe_ratio")),
        "dividend_yield_pct": _safe_float(metrics.get("dividend_yield_pct")),
        "adjusted_score_avg": _safe_float(metrics.get("adjusted_score_avg")),
        "median_terminal": _safe_float(mc.get("median_terminal")),
        "p10_terminal": _safe_float(mc.get("p10_terminal")),
        "prob_target_pct": _safe_float(mc.get("prob_target_pct")),
        "horizon_years": _safe_float(personal.get("primary_horizon_years") or personal.get("horizon_years")),
        "current_capital": _safe_float(personal.get("current_capital")),
        "monthly_savings": _safe_float(personal.get("monthly_savings")),
        "drag_total_pct": _safe_float(drags.get("total_annual_drag_pct") or drags.get("annual_fee_pct")),
        "withdrawal_strategy": str(wd.get("strategy") or wd.get("name") or "") if isinstance(wd, dict) else "",
        "top_holdings": ", ".join(top) if top else "",
        "narrative_len": len(str(getattr(snap, "narrative", "") or "")),
    }


_COMPARE_LABELS = {
    "profile": "Perfil de riesgo",
    "n_positions": "Posiciones",
    "expected_return_pct": "Retorno esperado %",
    "volatility_pct": "Volatilidad %",
    "sharpe_ratio": "Sharpe",
    "dividend_yield_pct": "Div. yield %",
    "adjusted_score_avg": "Score promedio",
    "median_terminal": "Mediana final ($)",
    "p10_terminal": "Pesimista p10 ($)",
    "prob_target_pct": "Prob. de meta %",
    "horizon_years": "Horizonte (años)",
    "current_capital": "Capital actual ($)",
    "monthly_savings": "Ahorro mensual ($)",
    "drag_total_pct": "Drags anuales %",
    "withdrawal_strategy": "Estrategia de retiro",
    "top_holdings": "Top 5 holdings",
}


def deep_compare_plans(plan_a: Any, plan_b: Any) -> dict:
    """Side-by-side assumptions + outcomes. Pure; works with PlanSnapshot or dicts."""
    a = _plan_field_map(plan_a)
    b = _plan_field_map(plan_b)
    rows: List[dict] = []
    diffs: List[str] = []

    for key, label in _COMPARE_LABELS.items():
        va, vb = a.get(key), b.get(key)
        row = {
            "field": key,
            "label": label,
            "a": va if va is not None else "—",
            "b": vb if vb is not None else "—",
            "differs": va != vb and not (va is None and vb is None),
        }
        # numeric delta when both numbers
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            row["delta"] = round(float(vb) - float(va), 4)
            if abs(row["delta"]) > 1e-9:
                diffs.append(f"{label}: {va} → {vb} (Δ {row['delta']:+g})")
        elif row["differs"]:
            diffs.append(f"{label}: «{va}» vs «{vb}»")
            row["delta"] = None
        else:
            row["delta"] = 0 if isinstance(va, (int, float)) else None
        rows.append(row)

    return {
        "name_a": a.get("name") or "Plan A",
        "name_b": b.get("name") or "Plan B",
        "rows": rows,
        "n_differences": sum(1 for r in rows if r["differs"]),
        "highlights": diffs[:12],
    }


# --------------------------------------------------------------------------- #
#  15 — Track record one-liner                                                #
# --------------------------------------------------------------------------- #

def track_record_one_liner(
    summary: Optional[Mapping[str, Any]] = None,
    *,
    by_action: Optional[Mapping[str, Any]] = None,
    horizon_label: str = "12m",
    benchmark_label: str = "SPY",
) -> str:
    """Honest one-line summary for Home / Mi Plan. Empty → no history yet."""
    summary = summary or {}
    n = int(summary.get("n") or 0)
    if n <= 0:
        return "Track record: todavía no hay señales puntuadas — se va llenando con el uso."

    hit = summary.get("overall_hit_rate")
    excess = summary.get("mean_excess_pct")
    parts = [f"Track record ({n} señales, {horizon_label})"]
    if hit is not None:
        parts.append(f"acierto direccional {float(hit)*100:.0f}%")
    if excess is not None:
        parts.append(f"exceso medio vs {benchmark_label} {float(excess):+.1f} pp")

    # Optional BUY-focused honesty
    if by_action:
        for key in ("BUY", "STRONG BUY", "STRONG_BUY"):
            block = by_action.get(key) or by_action.get(key.replace(" ", "_"))
            if block and block.get("n"):
                hr = block.get("hit_rate")
                if hr is not None:
                    parts.append(f"{key} {float(hr)*100:.0f}% hit (n={block['n']})")
                break

    return " · ".join(parts) + "."


# --------------------------------------------------------------------------- #
#  12 — Coach: market drop + plan still OK                                    #
# --------------------------------------------------------------------------- #

def coach_should_fire_on_drop(
    *,
    portfolio_return_pct: float,
    drop_threshold_pct: float = 8.0,
    plan_prob_target_pct: Optional[float] = None,
    plan_prob_floor_pct: float = 40.0,
    already_on_cooldown: bool = False,
) -> dict:
    """Predicate for a proactive “plan sigue OK” coach after a market/portfolio drop.

    Returns ``{should_fire, severity, message, context}``. Pure — the alert engine
    owns persistence/cooldown; pass ``already_on_cooldown=True`` to suppress.
    """
    ret = float(portfolio_return_pct)
    thr = -abs(float(drop_threshold_pct))
    if already_on_cooldown or ret > thr:
        return {
            "should_fire": False,
            "severity": "info",
            "message": "",
            "context": {
                "portfolio_return_pct": ret,
                "threshold_pct": thr,
            },
        }

    plan_ok = True
    plan_note = "No hay probabilidad de meta guardada; el desvío de corto plazo no invalida un plan de largo plazo por sí solo."
    if plan_prob_target_pct is not None:
        plan_ok = float(plan_prob_target_pct) >= float(plan_prob_floor_pct)
        plan_note = (
            f"Tu plan sigue con ~{float(plan_prob_target_pct):.0f}% de probabilidad de meta "
            f"(piso de confort {plan_prob_floor_pct:.0f}%)."
            if plan_ok
            else (
                f"La cartera cayó y la prob. de meta (~{float(plan_prob_target_pct):.0f}%) "
                f"está bajo el piso {plan_prob_floor_pct:.0f}% — revisá aportes u horizonte."
            )
        )

    if plan_ok:
        msg = (
            f"📉 Caída de cartera {ret:.1f}% (umbral {thr:.0f}%). "
            f"Respirá: {plan_note} "
            "Los planes de retiro se miden en años, no en semanas. Revisá Mi Plan antes de vender por pánico."
        )
        severity = "info"
    else:
        msg = (
            f"📉 Caída de cartera {ret:.1f}% y el plan necesita atención. {plan_note}"
        )
        severity = "warning"

    return {
        "should_fire": True,
        "severity": severity,
        "message": msg,
        "context": {
            "portfolio_return_pct": ret,
            "threshold_pct": thr,
            "plan_prob_target_pct": plan_prob_target_pct,
            "plan_ok": plan_ok,
        },
    }


# --------------------------------------------------------------------------- #
#  10 — Argentina dual-currency presentation                                  #
# --------------------------------------------------------------------------- #

def ar_dual_amounts(
    usd_amount: float,
    *,
    usd_ars_oficial: float,
    usd_ars_parallel: Optional[float] = None,
    label: str = "monto",
) -> dict:
    """Present a USD amount in ARS with official + optional parallel (brecha).

    Product context only — not a tax or compliance engine.
    ``usd_ars_*`` = pesos per 1 USD.
    """
    usd = float(usd_amount)
    oficial = float(usd_ars_oficial)
    if oficial <= 0:
        raise ValueError("usd_ars_oficial must be > 0")
    parallel = float(usd_ars_parallel) if usd_ars_parallel is not None else None
    out = {
        "label": label,
        "usd": round(usd, 2),
        "ars_oficial": round(usd * oficial, 0),
        "rate_oficial": oficial,
        "ars_parallel": None,
        "rate_parallel": parallel,
        "brecha_pct": None,
    }
    if parallel is not None and parallel > 0:
        out["ars_parallel"] = round(usd * parallel, 0)
        out["brecha_pct"] = round((parallel / oficial - 1.0) * 100.0, 1)
    return out


def format_ar_dual_line(dual: Mapping[str, Any]) -> str:
    """One human-readable line for UI captions."""
    parts = [f"USD ${float(dual['usd']):,.0f}", f"ARS oficial ${float(dual['ars_oficial']):,.0f}"]
    if dual.get("ars_parallel") is not None:
        parts.append(f"ARS paralelo ${float(dual['ars_parallel']):,.0f}")
        if dual.get("brecha_pct") is not None:
            parts.append(f"brecha {float(dual['brecha_pct']):+.1f}%")
    return " · ".join(parts)


# --------------------------------------------------------------------------- #
#  4 / 9 — Decision transparency + second-source signal                       #
# --------------------------------------------------------------------------- #

def decision_provenance_labels(*, has_ai: bool, has_calc: bool = True) -> List[dict]:
    """Badges for decision surfaces: calculado vs interpretación IA."""
    labels = []
    if has_calc:
        labels.append({
            "kind": "calc",
            "emoji": "📊",
            "title": "Calculado",
            "detail": "Sale de una fórmula o del motor numérico — no de la IA.",
        })
    if has_ai:
        labels.append({
            "kind": "ai",
            "emoji": "🤖",
            "title": "Interpretación IA",
            "detail": "Opinión del modelo sobre los números; no reemplaza el cálculo.",
        })
    return labels


def second_source_quality_signal(
    reconciliation: Optional[Mapping[str, Any]] = None,
    *,
    data_quality: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Compact signal for Screener/Optimizer/Plan decision path.

    Extends existing multi-source reconciliation + data_quality badge — does not
    invent a second price stack.
    """
    dq_level = "unknown"
    stale = False
    if data_quality:
        dq_level = str(data_quality.get("level") or "unknown")
        stale = bool(data_quality.get("stale"))

    n_conflicts = 0
    agreement = None
    sources: List[str] = []
    if reconciliation:
        n_conflicts = int(reconciliation.get("n_conflicts") or 0)
        if reconciliation.get("agreement_pct") is not None:
            agreement = float(reconciliation["agreement_pct"])
        sources = list(reconciliation.get("sources_used") or [])

    if n_conflicts > 0:
        status = "conflict"
        message = (
            f"⚠️ {n_conflicts} campo(s) en conflicto entre fuentes"
            + (f" (acuerdo {agreement:.0f}%)" if agreement is not None else "")
            + ". Revisá antes de decidir."
        )
    elif sources and len(sources) >= 2:
        status = "cross_checked"
        message = (
            f"✅ Cruzado entre {len(sources)} fuentes"
            + (f" · acuerdo {agreement:.0f}%" if agreement is not None else "")
            + f" · calidad {dq_level}"
            + (" · datos viejos" if stale else "")
        )
    elif dq_level in ("good", "partial", "poor"):
        status = "single_source"
        message = (
            f"Fuente principal · calidad {dq_level}"
            + (" · datos viejos" if stale else "")
            + ". Activá reconciliación multi-fuente para más confianza."
        )
    else:
        status = "unknown"
        message = "Sin señal de calidad todavía — corré un análisis."

    return {
        "status": status,
        "message": message,
        "dq_level": dq_level,
        "stale": stale,
        "n_conflicts": n_conflicts,
        "agreement_pct": agreement,
        "sources": sources,
    }


# --------------------------------------------------------------------------- #
#  5 — Chat suggested questions + missing context                             #
# --------------------------------------------------------------------------- #

DEFAULT_CHAT_SUGGESTIONS = (
    "¿Conviene comprar AAPL?",
    "¿Cómo viene mi plan?",
    "¿Me alcanza si me jubilo en 15 años?",
    "¿Qué riesgos tiene mi cartera?",
    "¿Qué debo hacer este año en mi plan?",
)


def chat_suggested_questions(
    *,
    has_active_plan: bool = False,
    has_portfolio: bool = False,
) -> List[str]:
    qs = list(DEFAULT_CHAT_SUGGESTIONS)
    if has_active_plan:
        qs = [
            "¿Cómo viene mi plan vs el mercado?",
            "¿Cuál es la probabilidad de alcanzar mi meta?",
            "¿Qué pasa si aporte un 20% más?",
        ] + [q for q in qs if q not in (
            "¿Cómo viene mi plan?",
            "¿Me alcanza si me jubilo en 15 años?",
        )]
    if has_portfolio:
        qs.insert(0, "¿Estoy muy concentrado en una sola acción?")
    # unique preserve order
    seen = set()
    out = []
    for q in qs:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:6]


def chat_missing_context_message(
    *,
    has_active_plan: bool,
    has_goal_target: bool,
    tool_name: str = "",
) -> Optional[str]:
    """Human copy when chat would otherwise report a misleading empty/zero result."""
    if tool_name in ("plan_status", "retirement_projection") and not has_active_plan:
        return (
            "Todavía no tenés un **plan activo**. "
            "Andá a 🗺️ **Mi Plan**, cargá un plan de ejemplo o guardá el tuyo, y volvé a preguntar. "
            "No hay un 0% real: falta el plan."
        )
    if tool_name == "retirement_projection" and has_active_plan and not has_goal_target:
        return (
            "Tu plan existe, pero **no hay una meta de capital definida**, "
            "así que no se puede calcular una probabilidad de alcanzarla. "
            "Definí la meta en 🎲 **Simulaciones → Mis Metas** o en el plan — "
            "no interpretes la ausencia como 0%."
        )
    if not has_active_plan and not tool_name:
        return (
            "Tip: sin plan activo las preguntas de proyección y estado del plan "
            "no tienen base. Usá 🎁 un plan de ejemplo en Mi Plan o Inicio."
        )
    return None


# --------------------------------------------------------------------------- #
#  Empty-state helpers (backlog 2)                                            #
# --------------------------------------------------------------------------- #

def guided_empty_state(
    page: str,
    *,
    has_last_result: bool = False,
    last_result_caption: str = "",
) -> dict:
    """Copy + suggested demo for pages that used to open blank."""
    catalog = {
        "screener": {
            "title": "Aún no corriste el screener",
            "body": "Analizá el universo para ver ranking, señales y calidad de datos.",
            "demo_hint": "Tocá Refresh Analysis (o dejá que cargue con el universo actual).",
            "demo_ticker": "AAPL",
        },
        "simulaciones": {
            "title": "Todavía no hay una proyección en esta sesión",
            "body": "Necesitás una cartera del Optimizer (o un plan cargado) para simular.",
            "demo_hint": "Andá a Optimizer, o cargá un plan de ejemplo en Mi Plan y volvé.",
            "demo_ticker": "",
        },
        "comite": {
            "title": "El comité espera un ticker",
            "body": "Convocá el panel multi-agente con disenso explícito (Abogado del Diablo incluido).",
            "demo_hint": "Probá con MSFT o AAPL para ver un dictamen de ejemplo.",
            "demo_ticker": "MSFT",
        },
        "chat": {
            "title": "Empezá con una pregunta",
            "body": "El asesor elige la herramienta y responde con números reales (sin inventar).",
            "demo_hint": "Usá las preguntas sugeridas de abajo.",
            "demo_ticker": "",
        },
    }
    base = dict(catalog.get(page, {
        "title": "Nada que mostrar todavía",
        "body": "Completá el paso anterior del camino de retiro.",
        "demo_hint": "",
        "demo_ticker": "",
    }))
    base["has_last_result"] = has_last_result
    base["last_result_caption"] = last_result_caption
    return base


# --------------------------------------------------------------------------- #
#  PDF partner blurb (backlog 11) — pure text blocks                          #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  PDF mc_params assembly (backlog 11) — real call-path helper                #
# --------------------------------------------------------------------------- #

def enrich_pdf_mc_params(
    mc_params: Optional[Mapping[str, Any]] = None,
    *,
    prefs: Any = None,
    personal: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Fill savings / capital / horizon on PDF mc_params from prefs or personal.

    Call sites historically only passed simulation widget keys (often empty).
    Without this, the shareable "Qué hacer este año" block always said
    "Definí cuánto podés aportar…" even when the user had monthly_savings set.
    """
    out: Dict[str, Any] = dict(mc_params or {})
    personal = dict(personal or {})

    def _pos(key: str) -> Optional[float]:
        v = out.get(key)
        if v is None:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    # --- monthly / annual savings ---
    monthly = _pos("monthly_savings") or _pos("monthly_contribution") or _pos("monthly_contrib")
    if monthly is None and _pos("annual_contribution") is not None:
        monthly = float(out["annual_contribution"]) / 12.0
    if monthly is None and _pos("annual_savings") is not None:
        monthly = float(out["annual_savings"]) / 12.0

    if monthly is None and personal:
        for k in ("monthly_savings", "monthly_contribution"):
            if personal.get(k) is not None:
                try:
                    m = float(personal[k])
                    if m > 0:
                        monthly = m
                        break
                except (TypeError, ValueError):
                    pass
        if monthly is None and personal.get("annual_savings") is not None:
            try:
                a = float(personal["annual_savings"])
                if a > 0:
                    monthly = a / 12.0
            except (TypeError, ValueError):
                pass

    if monthly is None and prefs is not None:
        try:
            m = float(getattr(prefs, "monthly_savings", 0) or 0)
            if m > 0:
                monthly = m
        except (TypeError, ValueError):
            pass
        if monthly is None:
            try:
                a = float(getattr(prefs, "annual_savings", 0) or 0)
                if a > 0:
                    monthly = a / 12.0
            except (TypeError, ValueError):
                pass

    if monthly is not None and monthly > 0:
        out["monthly_savings"] = float(monthly)
        if _pos("annual_savings") is None and _pos("annual_contribution") is None:
            out["annual_savings"] = float(monthly) * 12.0

    # --- capital ---
    if _pos("initial_value") is None:
        for src in (
            personal.get("current_capital"),
            getattr(prefs, "current_capital", None) if prefs is not None else None,
        ):
            if src is None:
                continue
            try:
                c = float(src)
                if c > 0:
                    out["initial_value"] = c
                    break
            except (TypeError, ValueError):
                pass

    # --- horizon ---
    if _pos("horizon_years") is None:
        for src in (
            personal.get("primary_horizon_years"),
            personal.get("horizon_years"),
            getattr(prefs, "primary_horizon_years", None) if prefs is not None else None,
        ):
            if src is None:
                continue
            try:
                h = float(src)
                if h > 0:
                    out["horizon_years"] = h
                    break
            except (TypeError, ValueError):
                pass

    return out


def assemble_plan_pdf_mc_params(
    *,
    session: Optional[Mapping[str, Any]] = None,
    prefs: Any = None,
    profile_name: str = "",
    personal: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Real Plan-page PDF param assembly (mirrors dashboard/pages/12_Plan path).

    ``session`` is a mapping of Streamlit session_state-like keys from Simulaciones.
    ``prefs`` is UserPreferences (or duck-type). Pure — no Streamlit import.
    """
    session = dict(session or {})
    base = {
        "horizon_years": session.get("horizon_years"),
        "initial_value": session.get("initial_value"),
        "inflation_rate": session.get("inflation_rate"),
        "target_value": session.get("target_value"),
        "annual_withdrawal": session.get("annual_withdrawal"),
        "profile_name": profile_name or session.get("profile_name") or "",
        "monthly_savings": session.get("monthly_savings"),
        "annual_contribution": (
            session.get("annual_contribution")
            or session.get("annual_savings")
            or session.get("new_goal_contribution")
        ),
        "annual_savings": session.get("annual_savings"),
    }
    return enrich_pdf_mc_params(base, prefs=prefs, personal=personal)


def shareable_report_narrative_blocks(
    *,
    plan_name: str,
    prob_target_pct: Optional[float],
    median_terminal: Optional[float],
    horizon_years: Optional[float],
    profile: str = "",
    annual_actions: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[dict]:
    """Narrative sections oriented to partner/advisor (not a technical dump)."""
    blocks = [
        {
            "heading": "Para quién es este documento",
            "body": (
                f"Resumen del plan de retiro «{plan_name or 'sin nombre'}» "
                "pensado para compartir con tu pareja o un asesor. "
                "Es educativo: no constituye asesoramiento financiero regulado."
            ),
        },
        {
            "heading": "En una mirada",
            "body": (
                f"Perfil: {profile or '—'}. "
                + (f"Horizonte ~{horizon_years:.0f} años. " if horizon_years else "")
                + (f"Probabilidad de meta ~{prob_target_pct:.0f}%. " if prob_target_pct is not None else "Sin probabilidad de meta cargada. ")
                + (f"Resultado mediano proyectado ~${median_terminal:,.0f}." if median_terminal else "")
            ),
        },
        {
            "heading": "Qué hacer este año",
            "body": (
                " · ".join(
                    f"{a.get('title', '')}" for a in (annual_actions or [])[:5]
                )
                or "Definí aportes, revisá alineación y respaldá el plan."
            ),
        },
        {
            "heading": "Cómo leer los números",
            "body": (
                "Las proyecciones usan un sesgo conservador a propósito (más volatilidad, "
                "menor retorno esperado). Cuando veas «realista vs conservador», planificá "
                "con el conservador. Los sellos 📊 son cálculos; 🤖 es interpretación de IA."
            ),
        },
    ]
    return blocks
