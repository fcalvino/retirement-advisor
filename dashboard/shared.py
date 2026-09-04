"""
Shared helpers, constants and cached functions used by every dashboard page.

Import pattern in each page:
    from dashboard.shared import (
        cached_full_analysis, _analyse_universe_parallel,
        _fetch_universe_parallel, _get_ai_config,
        score_bar, _MOAT_EMOJI, ACTION_COLOR, ...
    )
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Seed repo root so first-party imports work when this module loads first.
_sys_root = Path(__file__).resolve().parent.parent
if str(_sys_root) not in sys.path:
    sys.path.insert(0, str(_sys_root))
from bootstrap import ensure_project_root

ensure_project_root()

import streamlit as st
from loguru import logger

from analysis.strategy import full_analysis
from config import ENGINE_VERSION, AIConfig
from data.product_ux import (
    GUARDRAILS_LABEL,
    GUARDRAILS_OMISSIONS,
    decision_explanation,
    guardrails_help,
)
from data.screener_store import format_eta

# ------------------------------------------------------------------ #
#  .env helpers                                                        #
# ------------------------------------------------------------------ #

_ENV_PATH = Path(__file__).parent.parent / ".env"


def _load_env_vars() -> dict:
    """Read key=value pairs from .env file."""
    env: dict[str, str] = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _save_ai_config_to_env(
    provider: str,
    model: str,
    api_key: str,
    enabled: bool,
    use_in_screener: bool = False,
) -> None:
    """Persist AI settings into .env without touching other keys."""
    env = _load_env_vars()
    env["AI_PROVIDER"] = provider
    env["AI_MODEL"] = model
    env["AI_ENABLED"] = "true" if enabled else "false"
    env["AI_USE_IN_SCREENER"] = "true" if use_in_screener else "false"
    if api_key:
        env["AI_API_KEY"] = api_key
    elif "AI_API_KEY" in env:
        del env["AI_API_KEY"]
    _ENV_PATH.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")


def is_dev_mode() -> bool:
    """Whether developer/admin tools (Eval IA, Calidad de Datos, Macro RAG) are visible.

    True when the ``DEV_MODE`` env var is truthy *or* the user enabled the toggle
    in Settings (stored in ``session_state["dev_mode"]``). Keeps the everyday menu
    clean for regular use while leaving the technical pages one switch away.
    """
    if str(os.getenv("DEV_MODE", "")).lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        return bool(st.session_state.get("dev_mode", False))
    except Exception:  # pragma: no cover - no session context
        return False


# ------------------------------------------------------------------ #
#  Calculado vs IA — etiquetas de procedencia del dato                #
# ------------------------------------------------------------------ #
#  Make it explicit what is a deterministic calculation vs what is an
#  AI interpretation, so a model's prose is never read as a hard number.

CALC_BADGE = "📊 Calculado"
AI_BADGE = "🤖 Interpretación IA"


def render_calc_badge(detail: str = "sale de una fórmula, no de la IA") -> None:
    """Caption marking a value as a deterministic calculation."""
    st.caption(f"{CALC_BADGE} · {detail}")


def render_ai_badge(detail: str = "lo dijo el modelo — es una opinión, no un cálculo") -> None:
    """Caption marking content as an AI interpretation."""
    st.caption(f"{AI_BADGE} · {detail}")


# ------------------------------------------------------------------ #
#  Visual constants                                                    #
# ------------------------------------------------------------------ #

ACTION_COLOR: dict[str, str] = {
    "STRONG BUY": "#00C851",
    "BUY":        "#39b54a",
    "HOLD":       "#ffbb33",
    "REDUCE":     "#ff8800",
    "SELL":       "#ff4444",
    "AVOID":      "#cc0000",
}

_MOAT_COLOR: dict[str, str] = {
    "Wide":    "#00C851",
    "Narrow":  "#39b54a",
    "Minimal": "#ffbb33",
    "None":    "#888888",
}

_MOAT_EMOJI: dict[str, str] = {
    "Wide":    "🏰",
    "Narrow":  "🟢",
    "Minimal": "🟡",
    "None":    "⚪",
}

_MOAT_DESCRIPTION: dict[str, str] = {
    "Wide":    "Ventaja duradera 20+ años — protección estructural fuerte (ej: MSFT, AAPL, V)",
    "Narrow":  "Ventaja sólida ~10 años — más vulnerable a disrupción (ej: MELI, HD)",
    "Minimal": "Protección limitada o erosionándose — monitorear cada año",
    "None":    "Sin ventaja competitiva identificable — sensible a precios y competencia",
}

# ------------------------------------------------------------------ #
#  Formatting helpers                                                  #
# ------------------------------------------------------------------ #

def escape_dollars(text: str) -> str:
    """Escape ``$`` so Streamlit's markdown does not read amounts as LaTeX.

    Streamlit turns ``$100 ... $200`` into a KaTeX span (CONTEXT.md §8). Any
    string built elsewhere and rendered with `st.markdown` has to come through
    here — an f-string cannot hold the backslash on Python 3.11.
    """
    return str(text).replace("$", "\\$")


def score_bar(score: float) -> str:
    """ASCII score bar. Superseded on the Screener by `st.column_config.ProgressColumn`.

    Kept for callers that need a plain string (PDF, plain-text contexts). Do not
    put it in a dataframe: sorting on the header sorts the *text*, which produces
    a plausible and wrong ordering (audit item 08).
    """
    filled = int(score / 10)
    return "█" * filled + "░" * (10 - filled) + f"  {score:.0f}/100"


def screener_column_config(columns) -> dict:
    """Build `st.column_config` for the Screener tables (audit items 08 + 18).

    Reads the plain-data specs in ``data.product_ux.SCREENER_COLUMN_SPECS`` and
    returns only the entries for columns actually displayed, so the same helper
    serves the shortlist and the full table without either carrying config for
    columns it does not show.
    """
    from data.product_ux import screener_column_spec

    config: dict = {}
    for col in columns:
        spec = screener_column_spec(col)
        if not spec:
            continue
        kind = spec.get("kind", "text")
        help_text = spec.get("help")
        if kind == "progress":
            config[col] = st.column_config.ProgressColumn(
                col, help=help_text, format=spec.get("format", "%.1f"),
                min_value=spec.get("min", 0), max_value=spec.get("max", 100),
            )
        elif kind == "number":
            config[col] = st.column_config.NumberColumn(
                col, help=help_text, format=spec.get("format"),
            )
        else:
            config[col] = st.column_config.TextColumn(col, help=help_text)
    return config


_DQ_EMOJI = {"good": "🟢", "partial": "🟡", "poor": "🔴"}
_DQ_LABEL = {"good": "OK", "partial": "Parcial", "poor": "Pobre"}

# Sector-country structural tailwind (Idea 2)
_TAILWIND_EMOJI: dict[str, str] = {
    "Strong":   "🌬️",
    "Moderate": "🍃",
    "Neutral":  "⚪",
    "Headwind": "🌪️",
}

_TAILWIND_COLOR: dict[str, str] = {
    "Strong":   "#00C851",
    "Moderate": "#39b54a",
    "Neutral":  "#888888",
    "Headwind": "#ff4444",
}

_TAILWIND_LABEL_ES: dict[str, str] = {
    "Strong":   "Fuerte",
    "Moderate": "Moderada",
    "Neutral":  "—",
    "Headwind": "En contra",
}


def tailwind_badge(classification: str | None, score: float = 0.0) -> str:
    """Compact table-cell badge for a sector-country tailwind (Idea 2).

    Neutral / missing → "—" so untouched tickers stay visually quiet.
    """
    cls = classification or "Neutral"
    if cls == "Neutral":
        return "—"
    emoji = _TAILWIND_EMOJI.get(cls, "⚪")
    label = _TAILWIND_LABEL_ES.get(cls, cls)
    return f"{emoji} {label} ({score:+.0f})"


def _tailwind_badge_html(classification: str, score: float, bonus: float) -> str:
    """HTML badge colored by tailwind classification for st.markdown()."""
    color = _TAILWIND_COLOR.get(classification, "#888")
    emoji = _TAILWIND_EMOJI.get(classification, "⚪")
    label = {
        "Strong":   "Cola de viento fuerte",
        "Moderate": "Cola de viento moderada",
        "Neutral":  "Neutral",
        "Headwind": "Viento de frente",
    }.get(classification, classification)
    return (
        f'<span style="background:{color}22;border:1px solid {color};color:{color};'
        f'padding:3px 12px;border-radius:14px;font-weight:700;font-size:0.9em;">'
        f'{emoji} {label} &nbsp;·&nbsp; {score:+.1f} &nbsp;·&nbsp; {bonus:+.1f} pts</span>'
    )


def data_quality_badge(dq: dict | None) -> str:
    """Compact table-cell badge for a FundamentalResult.data_quality dict (Fase E)."""
    if not dq:
        return "—"
    level = dq.get("level", "")
    label = f"{_DQ_EMOJI.get(level, '⚪')} {_DQ_LABEL.get(level, '—')}"
    if dq.get("stale"):
        label += " ⏳"
    return label


def _moat_badge_html(
    classification: str, score: float, bonus: float, scale_max: float = 20.0
) -> str:
    """HTML badge colored by moat classification for st.markdown().

    ``scale_max`` is 20 with the AI layer and 12 without it (U3-7). A quant-only
    score printed as "/20" reads as a weak result rather than a short ruler.
    """
    color = _MOAT_COLOR.get(classification, "#888")
    emoji = _MOAT_EMOJI.get(classification, "⚪")
    return (
        f'<span style="background:{color}22;border:1px solid {color};color:{color};'
        f'padding:3px 12px;border-radius:14px;font-weight:700;font-size:0.9em;">'
        f'{emoji} {classification} Moat &nbsp;·&nbsp; {score:.1f}/{scale_max:.0f} '
        f'&nbsp;·&nbsp; +{bonus:.1f} pts</span>'
    )


def _dim_bar_html(score: float, max_score: float = 2.0) -> str:
    """Inline HTML progress bar for a moat dimension (0–2 scale)."""
    pct = score / max_score * 100
    if pct >= 75:
        color = "#00C851"
    elif pct >= 40:
        color = "#ffbb33"
    elif pct > 0:
        color = "#ff8800"
    else:
        color = "#dddddd"
    return (
        f'<div style="background:#e8e8e8;border-radius:4px;height:7px;margin-top:2px;">'
        f'<div style="width:{pct:.0f}%;background:{color};height:7px;border-radius:4px;"></div>'
        f'</div>'
    )


# ------------------------------------------------------------------ #
#  User-profile helpers (onboarding — Fase A)                          #
# ------------------------------------------------------------------ #

# Horizon options offered by the Monte Carlo selectbox in Simulaciones.
_SIM_HORIZON_OPTIONS = (5, 10, 15, 20, 25, 30)


def get_user_prefs():
    """Return the session UserPreferences, loading + caching it on first use.

    Safe to call from pages reached via direct st.navigation() access where
    app.py's startup block may not have run yet.
    """
    prefs = st.session_state.get("user_prefs")
    if prefs is None or not hasattr(prefs, "is_onboarded"):
        from data.preferences import UserPreferences
        prefs = UserPreferences.load()
        st.session_state.user_prefs = prefs
    return prefs


def _snap_sim_horizon(years: int) -> int:
    """Snap an arbitrary horizon to the nearest Monte Carlo selectbox option."""
    if not years or years <= 0:
        return 20
    return min(_SIM_HORIZON_OPTIONS, key=lambda o: abs(o - years))


def seed_session_defaults_from_profile(prefs, *, force: bool = False) -> None:
    """Seed Optimizer/Simulaciones widget defaults from the personal profile.

    Idempotent per session: runs once at startup for onboarded users so the
    Optimizer opens with their capital and Simulaciones with a realistic
    horizon. ``force=True`` is used right after the wizard saves, refreshing
    the defaults and letting the Optimizer re-derive its profile from
    ``default_profile`` (we pop its widget-state keys instead of duplicating
    the emoji labels here).
    """
    if not getattr(prefs, "is_onboarded", False):
        return
    if st.session_state.get("_profile_defaults_seeded") and not force:
        return

    capital = int(max(0.0, getattr(prefs, "current_capital", 0.0)))
    if capital > 0 and (force or "optimizer_total_capital" not in st.session_state):
        st.session_state["optimizer_total_capital"] = capital

    horizon = _snap_sim_horizon(getattr(prefs, "primary_horizon_years", 0))
    sim_capital = min(max(capital or 100_000, 1_000), 10_000_000)
    if force or "horizon_years" not in st.session_state:
        st.session_state["horizon_years"] = horizon
    if force or "initial_value" not in st.session_state:
        st.session_state["initial_value"] = sim_capital

    if force:
        # Let Optimizer re-derive its profile radio from the updated default_profile.
        st.session_state.pop("optimizer_profile_label", None)
        st.session_state.pop("optimizer_last_saved_profile", None)

    st.session_state["_profile_defaults_seeded"] = True


# ------------------------------------------------------------------ #
#  Mi Plan de Retiro — living-plan helpers (Fase C)                    #
# ------------------------------------------------------------------ #

from data.plan_context import (
    plan_price_lookup as plan_price_lookup,  # re-export; impl lives in data layer (S19)
)


def compute_plan_health(snap, *, core_only: bool = False) -> dict:
    """Compute a saved plan's market delta / health vs today (Fase C).

    Thin wrapper injecting the cached price lookup. Run behind an explicit
    "Refrescar" button so the (controlled) price fetch is user-initiated, not
    automatic on page load.

    The full refresh goes through ``refresh_plan_against_market``, which also
    seals ``refreshed_metrics`` / ``last_refreshed_at`` onto the snapshot and
    persists it — otherwise the result would die with the session and every
    consumer of those two fields stays blind. ``core_only`` stays on the pure
    path: it prices only the core holdings, which carry no ``price_at_save``
    baseline, so it must never overwrite a full refresh.
    """
    if core_only:
        from data.plan_context import compute_plan_vs_reality
        return compute_plan_vs_reality(snap, plan_price_lookup, core_only=True)

    from data.plan_context import refresh_plan_against_market
    return refresh_plan_against_market(snap, plan_price_lookup)


def record_plan_health_now(
    snap,
    *,
    source: str = "manual",
    refreshed: dict | None = None,
    min_days_between: int | None = None,
):
    """Record a longitudinal health snapshot for a plan (Fase H.2).

    Thin wrapper over ``data.plan_context.record_plan_health`` injecting the
    cached price lookup. ``refreshed`` reuses an existing plan-vs-reality result
    to avoid a second price fetch. Returns the new record (or None if deduped).

    ``min_days_between=None`` lets ``record_plan_health`` resolve the window from
    ``HEALTH.min_days_between_records``, the same value the scheduler passes.
    This wrapper used to omit the argument entirely, which meant the UI button
    ran with no dedup at all.
    """
    from data.plan_context import record_plan_health
    return record_plan_health(
        snap, plan_price_lookup, source=source, refreshed=refreshed,
        min_days_between=min_days_between,
    )


def plan_health_history(plan_id: str):
    """Chronological health records + a longitudinal-drift summary (Fase H.2)."""
    from data.plan_context import compute_longitudinal_drift, get_plan_health_history
    history = get_plan_health_history(plan_id)
    return history, compute_longitudinal_drift(history)


def load_sample_plan_into_store(key: str):
    """Import a bundled sample plan and persist it (Fase H.4).

    Reuses ``data.plan_context.load_sample_plan`` (which goes through the same
    import/validation path as user uploads) and upserts it into the plan store
    so it appears in "Planes guardados" and can be activated immediately.
    Returns the saved PlanSnapshot.
    """
    from data.plan_context import load_sample_plan
    from data.plan_store import plan_store

    snap = load_sample_plan(key)
    plan_store.upsert(snap)
    return snap


# ------------------------------------------------------------------ #
#  Sensitivity / scenario lab (Fase H.3)                               #
# ------------------------------------------------------------------ #

def _sensitivity_run_fn(params: dict):
    """Map a sensitivity params dict to a (cached) Monte Carlo run.

    Bridges ``portfolio.sensitivity`` (which speaks a neutral params dict) to
    ``cached_monte_carlo``. Economic drags are passed as a single annual total
    (``drags_total_pct``) so the lab can perturb them with one knob.
    """
    drag_total = float(params.get("drags_total_pct", 0.0) or 0.0)
    drags_tuple = (("enabled", True), ("total_annual_drag_pct", round(drag_total, 4))) if drag_total > 0 else None
    return cached_monte_carlo(
        symbols=tuple(params["symbols"]),
        weights_tuple=tuple(params["weights"]) if params.get("weights") else None,
        horizon_years=int(params.get("horizon_years", 20)),
        n_sims=int(params.get("n_sims", 2_000)),
        initial_value=float(params.get("initial_value", 100_000)),
        annual_withdrawal=float(params.get("annual_withdrawal", 0.0)),
        annual_contribution=float(params.get("annual_contribution", 0.0)),
        target_value=float(params.get("target_value", 0.0)),
        withdrawal_growth_rate=float(params.get("withdrawal_growth_rate", 0.0)),
        vol_scale=float(params.get("vol_scale", 1.0)),
        return_scale=float(params.get("return_scale", 1.0)),
        drags_tuple=drags_tuple,
        withdrawal_tuple=params.get("withdrawal_tuple"),
        longevity_years=params.get("longevity_years"),
    )


def run_plan_sensitivity(base_params: dict, *, primary_metric: str = "p10_terminal"):
    """Run the sensitivity lab for the given base params (Fase H.3).

    Returns a ``SensitivityResult``. ``base_params`` mirrors ``cached_monte_carlo``
    inputs plus ``drags_total_pct`` and ``withdrawal_tuple``. Uses the lighter
    ``SENSITIVITY.n_sims`` for speed unless ``n_sims`` is already set.
    """
    from config import SENSITIVITY
    from portfolio.sensitivity import run_sensitivity

    params = dict(base_params)
    params.setdefault("n_sims", SENSITIVITY.n_sims)
    return run_sensitivity(_sensitivity_run_fn, params, primary_metric=primary_metric)


def plan_journey_status(prefs) -> list[dict]:
    """Status of the guided "from zero to active plan" flow (Fase E).

    Returns the 4 canonical steps with a ``done`` flag each, so Home and
    Mi Plan can render progress + the next-step CTA consistently:
      1. Personal profile (onboarding wizard)
      2. Optimized portfolio in session (Optimizer)
      3. At least one saved plan (Mi Plan → Guardar)
      4. An active plan (Mi Plan → Activar)
    """
    from data.plan_store import plan_store

    has_profile = bool(getattr(prefs, "is_onboarded", False))
    has_opt = bool(
        st.session_state.get("optimizer_result")
        or st.session_state.get("optimizer_prev_result")
    )
    has_saved = bool(plan_store.list())
    has_active = bool((getattr(prefs, "active_plan_id", "") or "").strip())

    return [
        {
            "label": "Definí tu perfil de retiro",
            "done": has_profile,
            "page": None,  # wizard lives on Home/Settings
            "hint": "1 minuto: edad, capital, ahorro y tolerancia al riesgo.",
        },
        {
            "label": "Optimizá tu cartera",
            "done": has_opt,
            "page": "5_Optimizer.py",
            "hint": "El Optimizer ya usa tu perfil y capital como defaults.",
        },
        {
            "label": "Guardá tu plan",
            "done": has_saved,
            "page": "12_Plan.py",
            "hint": "Consolidá cartera + metas + Monte Carlo con un nombre.",
        },
        {
            "label": "Activalo como objetivo vivo",
            "done": has_active,
            "page": "12_Plan.py",
            "hint": "El tracker y las alertas de drift lo usan como tu meta.",
        },
        {
            # Item 2 — protect the plan once it exists. "done" is best-effort:
            # set when the user exports a plan (session flag, or a prefs flag if
            # the model exposes one). Only nudged once there is a plan to back up.
            "label": "Respaldá tu plan",
            "done": bool(
                st.session_state.get("plan_exported")
                or getattr(prefs, "plan_exported_at", "")
            ) or not has_saved,
            "page": "12_Plan.py",
            "hint": "Exportá a JSON y guardalo en tu nube/USB: sobrevive reinstalaciones.",
        },
    ]


def _days_since_iso(ts: str) -> int | None:
    """Whole days since an ISO timestamp, or None if missing/unparseable."""
    if not ts:
        return None
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(ts))
        return max(0, (datetime.now(dt.tzinfo) - dt).days)
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def unread_alert_count() -> int:
    """Unread-alert count for the sidebar badge and the home hub.

    ``@st.cache_data`` collapses the two-to-three SQLite reads a single home
    render used to do (P2), and keeps ``alerts.store`` out of ``app.py`` (O6).
    """
    try:
        from alerts.store import alert_store

        return int(alert_store.get_unread_count() or 0)
    except Exception:
        return 0


# ------------------------------------------------------------------ #
#  Data-layer wrappers for pages (O9) — pages must not import from     #
#  ``data.*`` directly (CONTEXT §5).                                   #
# ------------------------------------------------------------------ #

def cache_stats() -> dict:
    """Data-cache stats for the Settings page."""
    from data.cache import cache

    return cache.get_stats()


def clear_data_cache() -> None:
    """Clear the whole data cache from the Settings page."""
    from data.cache import cache

    cache.clear_all()


def usd_ars_quote(symbol: str = "ARS=X"):
    """USD/ARS market quote wrapper so Settings need not import ``data.fetcher``."""
    from data.fetcher import usd_ars_quote as _usd_ars_quote

    return _usd_ars_quote(symbol)


def get_price_history(symbol: str, period: str = "10y", interval: str = "1wk"):
    """Price history for a chart, so Stock Analysis need not import ``data.fetcher``
    directly (O7).

    Deliberately *not* ``@st.cache_data``: ``get_history`` already has its own
    disk cache for successful fetches, and it returns an empty frame (never
    raises) on a transient outage. Memoizing that empty frame for an hour would
    keep the chart broken long after the network recovered — the old direct call
    re-fetched every rerun.
    """
    from data.fetcher import get_history

    return get_history(symbol, period=period, interval=interval)


@st.cache_data(ttl=3600, show_spinner=False)
def cross_source_check(symbol: str) -> "dict | None":
    """Cross-source reconciliation for the data-quality panel (Fase 3A).

    Moved out of ``2_Stock_Analysis.py`` (O7) so the page holds no ``data.*``
    imports. Cached an hour so it never slows reruns; the screener never calls it.
    """
    from analysis.data_reconciliation import reconcile_sources
    from data.data_sources import default_fundamental_sources

    report = reconcile_sources(symbol, default_fundamental_sources())
    return report.as_dict()


# ------------------------------------------------------------------ #
#  Alert-engine wrappers for the Alertas page (O5) — the page holds    #
#  no ``alerts.engine`` / ``alerts.reporter`` import.                  #
# ------------------------------------------------------------------ #

def run_alert_engine(
    scored,
    *,
    active_profile,
    positions=None,
    current_prices=None,
    optimizer_weights=None,
):
    """Build and run the alert engine. When ``positions`` is given, runs the
    portfolio-aware path; otherwise the universe-only path."""
    from alerts.engine import AlertEngine

    engine = AlertEngine(active_profile=active_profile)
    if positions is not None:
        return engine.run_with_portfolio(
            scored, positions, current_prices or {}, optimizer_weights
        )
    return engine.run(scored)


def generate_alert_report(scored, *, period) -> str:
    """Generate the alerts PDF and return its path."""
    from alerts.reporter import ReportGenerator

    return ReportGenerator().generate(scored, period=period)


def next_priority_action(prefs) -> dict:
    """The single most urgent thing to do right now ("Hoy hacé esto").

    Cheap by design — no live price fetches on home load. Looks at the journey
    state, unread alerts and plan freshness, and returns one action dict:
    ``{icon, label, hint, page, tone}`` where tone is ``primary``/``warning``/``ok``.
    A single action (not a list) keeps the cognitive load low.
    """
    # 1. Journey incomplete → the next step is the priority.
    steps = plan_journey_status(prefs)
    next_undone = next((s for s in steps if not s["done"]), None)
    if next_undone is not None:
        return {
            "icon": "🚀", "label": next_undone["label"], "hint": next_undone["hint"],
            "page": next_undone["page"], "tone": "primary",
        }

    # 2. Active plan exists — operational signals (all cheap, no price fetch).
    n_unread = unread_alert_count()
    if n_unread > 0:
        return {
            "icon": "🔔", "label": f"Revisá {n_unread} alerta(s) sin leer",
            "hint": "Cambios de señal o de salud del plan que esperan tu atención.",
            "page": "8_Alertas.py", "tone": "warning",
        }

    try:
        from data.plan_context import get_active_plan
        snap = get_active_plan(prefs)
    except Exception:
        snap = None
    if snap is not None:
        _age = _days_since_iso(getattr(snap, "last_refreshed_at", "") or "")
        if _age is None or _age > 30:
            return {
                "icon": "🩺", "label": "Revisá la salud de tu plan",
                "hint": "Hace más de un mes (o nunca) que no comparás tu plan con el mercado.",
                "page": "12_Plan.py", "tone": "warning",
            }

    # 3. Nothing urgent.
    return {
        "icon": "✅", "label": "Tu plan está en línea",
        "hint": "No hay nada urgente — el tracker y las alertas lo siguen monitoreando.",
        "page": "12_Plan.py", "tone": "ok",
    }


def track_record_home_line() -> str:
    """Honest one-liner for Home / Mi Plan (backlog 15). Cheap: scored rows only."""
    try:
        from analysis.track_record import track_record_store
        from analysis.track_record_scorer import hit_rate_by_action, summary_stats
        from config import TRACK_RECORD
        from data.product_ux import track_record_one_liner

        horizon = list(TRACK_RECORD.horizons_days)[0] if TRACK_RECORD.horizons_days else 365
        rows = track_record_store.get_scored_rows(horizon) or []
        stats = summary_stats(rows)
        by_act = hit_rate_by_action(rows) if rows else {}
        return track_record_one_liner(
            stats,
            by_action=by_act,
            horizon_label=f"{horizon}d",
            benchmark_label=str(getattr(TRACK_RECORD, "benchmark", "SPY") or "SPY"),
        )
    except Exception:
        from data.product_ux import track_record_one_liner

        return track_record_one_liner({"n": 0})


def build_home_hub_for_prefs(prefs) -> dict:
    """Home plan hub payload (backlog 1) — pure core + cheap I/O wrappers."""
    from data.plan_context import get_active_plan, list_sample_plans
    from data.product_ux import build_home_plan_hub

    unread = unread_alert_count()

    snap = None
    try:
        snap = get_active_plan(prefs)
    except Exception:
        snap = None

    age = None
    if snap is not None:
        age = _days_since_iso(getattr(snap, "last_refreshed_at", "") or "")

    samples = []
    try:
        samples = list_sample_plans() or []
    except Exception:
        samples = []

    action = next_priority_action(prefs)
    hub = build_home_plan_hub(
        plan_snapshot=snap,
        primary_action=action,
        unread_alerts=unread,
        sample_plan_available=bool(samples),
        track_record_line=track_record_home_line(),
        data_age_days=age,
    )
    return hub.as_dict()


# ------------------------------------------------------------------ #
#  Plan portability — export bundle (Item 2)                          #
# ------------------------------------------------------------------ #

def export_plan_bundle(snap, prefs=None) -> tuple[bytes, str, str]:
    """Build a portable, self-contained export of a saved plan (Item 2).

    Returns ``(json_bytes, filename, instructions_md)``:
      - json_bytes: a versioned bundle ``{schema, exported_at, app, snapshot,
        personal?}`` ready to download and re-import on any machine.
      - filename: a safe, dated filename.
      - instructions_md: human-readable "how to restore" notes.

    Reuses ``PlanSnapshot.to_dict()`` entirely — no new serialization logic.
    """
    import json as _json
    from datetime import datetime as _dt

    bundle = {
        "schema": "retirement_advisor.plan_bundle",
        "schema_version": getattr(snap, "export_version", "1.0") or "1.0",
        "exported_at": _dt.now().isoformat(timespec="seconds"),
        "snapshot": snap.to_dict(),
    }
    # Optionally include a light personal-profile copy for full portability.
    if prefs is not None and getattr(prefs, "is_onboarded", False):
        bundle["personal"] = {
            "age": getattr(prefs, "age", None),
            "retirement_age": getattr(prefs, "retirement_age", None),
            "primary_horizon_years": getattr(prefs, "primary_horizon_years", None),
            "current_capital": getattr(prefs, "current_capital", None),
            "monthly_savings": getattr(prefs, "monthly_savings", None),
            "profile_key": getattr(prefs, "profile_key", ""),
        }

    json_bytes = _json.dumps(bundle, indent=2, ensure_ascii=False).encode("utf-8")
    safe_id = "".join(c for c in (snap.id or "plan") if c.isalnum() or c in "-_") or "plan"
    filename = f"plan_{safe_id}_{_dt.now().strftime('%Y%m%d')}.json"

    drag_note = ""
    if getattr(snap, "drags_at_save", None):
        drag_note = (
            f"\n- **Supuestos (drags) al guardar:** "
            f"{snap.drags_at_save.get('total_annual_drag_pct', 0):.2f}%/año.\n"
        )

    instructions_md = (
        f"# Backup de tu plan de retiro — {snap.name}\n\n"
        f"Exportado el {bundle['exported_at']} · esquema v{bundle['schema_version']}.\n\n"
        f"## Cómo restaurar\n"
        f"1. Abrí **Retirement Advisor → 🗺️ Mi Plan**.\n"
        f"2. En **«📦 Importar / Restaurar plan»**, subí el archivo `{filename}`.\n"
        f"3. Revisá la vista previa y, si querés, **activalo** como objetivo vivo.\n\n"
        f"## Qué contiene\n"
        f"- Cartera objetivo ({snap.n_positions} posiciones), núcleo, métricas, metas y "
        f"resumen Monte Carlo.{drag_note}\n"
        f"- Este JSON es autocontenido y versionado: podés guardarlo en tu nube/USB y "
        f"restaurarlo en cualquier máquina, incluso tras reinstalar.\n\n"
        f"> Recomendación: guardá una copia cada vez que actualices el plan de forma "
        f"importante.\n"
    )
    return json_bytes, filename, instructions_md


# ------------------------------------------------------------------ #
#  Custom tickers + effective universe (Item 3)                        #
# ------------------------------------------------------------------ #

def load_universe_with_customs(key: str, prefs=None) -> list[str]:
    """Load a curated universe and append the user's custom tickers (Item 3).

    Thin wrapper over ``data.universe_loader.get_effective_universe`` that pulls
    the custom symbols from prefs and records which customs were actually merged
    in ``st.session_state['custom_tickers_in_universe']`` so Screener/Optimizer
    can badge them. With no custom tickers this equals ``load_universe(key)``.
    """
    from data.universe_loader import get_effective_universe

    prefs = prefs if prefs is not None else get_user_prefs()
    customs = prefs.custom_symbols() if hasattr(prefs, "custom_symbols") else []
    tickers, custom_used = get_effective_universe(key, customs)
    st.session_state["custom_tickers_in_universe"] = custom_used
    return tickers


def ensure_session_defaults() -> None:
    """Seed ``user_prefs`` / ``universe`` / ``portfolio`` into ``st.session_state``.

    The same initialization ``app.py`` runs on entry, extracted so a page reached
    by a direct ``st.navigation`` link (fresh session, ``app.py``'s startup block
    never ran) falls back to one implementation instead of re-declaring the guard
    in each page (S18). Idempotent — every branch is a "not set yet" check.
    """
    prefs = get_user_prefs()
    if "universe" not in st.session_state:
        key = getattr(prefs, "active_universe", "default") or "default"
        st.session_state.universe = load_universe_with_customs(key, prefs)
        st.session_state.active_universe_key = key
    if "portfolio" not in st.session_state:
        from portfolio.tracker import Portfolio

        st.session_state.portfolio = Portfolio()


def is_custom_ticker(symbol: str) -> bool:
    """True if ``symbol`` is one of the customs merged into the active universe."""
    used = st.session_state.get("custom_tickers_in_universe", []) or []
    return str(symbol).upper().strip() in {s.upper() for s in used}


def custom_source_badge(symbol: str) -> str:
    """Table-cell badge marking a ticker's source: user-added vs curated universe."""
    return "⚠️ Propio" if is_custom_ticker(symbol) else "Curado"


# ------------------------------------------------------------------ #
#  Row selection → next action (audit item 10)                        #
# ------------------------------------------------------------------ #


def selected_ticker(df, event, *, column: str = "Ticker") -> str | None:
    """Resolve the ticker behind a ``st.dataframe(on_select=...)`` event.

    Pure lookup: takes the selected positional row index and reads ``column``
    off the same dataframe that was rendered. ``None`` when nothing is selected
    or the index no longer exists (the table can be re-sorted between reruns).
    """
    try:
        rows = list(getattr(event, "selection", {}).get("rows", []))
    except Exception:
        rows = []
    if not rows:
        return None
    idx = rows[0]
    if idx < 0 or idx >= len(df):
        return None
    value = df.iloc[idx].get(column)
    return str(value) if value is not None else None


def render_decision_detail(df, event) -> None:
    """Full reasoning behind the selected row's signal (audit item 04).

    The table cell carries one line; a decision usually has more, plus its risks.
    Both already exist on every ``Decision`` and were discarded by the row builder,
    so this is surfacing work, not new analysis.
    """
    try:
        rows = list(getattr(event, "selection", {}).get("rows", []))
    except Exception:
        rows = []
    if not rows or rows[0] >= len(df):
        return
    row = df.iloc[rows[0]]

    headline = str(row.get("_why_headline") or row.get("Motivo") or "").strip()
    why = list(row.get("_why") or [])
    risks = list(row.get("_risks") or [])
    if not (headline or why or risks):
        return

    with st.container(border=True):
        if headline:
            st.markdown(f"**Por qué {row.get('Ticker', '')} es {row.get('Signal', '')}** — {headline}")
        _d1, _d2 = st.columns(2)
        if why:
            _d1.caption("Razonamiento")
            for line in why[:6]:
                _d1.markdown(f"- {line}")
        if risks:
            _d2.caption("Riesgos anotados")
            for line in risks[:6]:
                _d2.markdown(f"- {line}")
        render_calc_badge("sale del motor de decisión — reglas, no IA (salvo que la actives)")


def render_row_actions(df, event, *, prefix: str = "row") -> str | None:
    """Turn a table selection into the actions the page promised.

    Audit item 10: the Screener's footer told the user to "click any ticker and
    then open Stock Analysis", but the table had no selection API and the click
    did nothing — the caption described a feature that was never wired. This is
    the wiring: pick a row, get the handoff.

    ``analysis_target`` is the key Stock Analysis already reads, so the deep link
    needs no change on the receiving side.
    """
    symbol = selected_ticker(df, event)
    if not symbol:
        st.caption("👆 Tocá una fila para analizar ese ticker, seguirlo o llevarlo al comité.")
        return None

    render_decision_detail(df, event)

    st.markdown(f"**{symbol}** seleccionado — ¿qué querés hacer?")
    c1, c2, c3 = st.columns(3)

    if c1.button(f"🔍 Analizar {symbol}", key=f"{prefix}_analyze", type="primary",
                 width="stretch"):
        st.session_state.analysis_target = symbol
        st.switch_page(str(Path(__file__).parent / "pages" / "2_Stock_Analysis.py"))

    if c2.button(f"📋 Seguir {symbol}", key=f"{prefix}_watch", width="stretch"):
        prefs = get_user_prefs()
        if prefs.watch(symbol):
            st.session_state.user_prefs = prefs
            st.success(f"✓ {symbol} agregado a la watchlist")
        else:
            st.info(f"{symbol} ya estaba en la watchlist")

    # `comite_last_symbol` is the key that page already seeds its input from.
    if c3.button(f"🏛️ Comité sobre {symbol}", key=f"{prefix}_committee", width="stretch"):
        st.session_state["comite_last_symbol"] = symbol
        st.switch_page(str(Path(__file__).parent / "pages" / "15_Comite.py"))

    return symbol


# ------------------------------------------------------------------ #
#  Economic drags + assumptions transparency (Item 1)                  #
# ------------------------------------------------------------------ #

# Session keys used to override the config defaults for the current session.
_DRAG_KEYS = (
    "annual_fee_pct",
    "dividend_tax_drag_pct",
    "rebalance_cost_annual_pct",
    "ar_buffer_pct",
)


def _build_economic_drags(enabled: bool, component_pcts: dict) -> dict:
    """Assemble the drags dict from resolved values — no ``st.session_state`` reads (S17).

    ``component_pcts`` maps each ``_DRAG_KEYS`` entry to its annual %. Shared by
    ``get_economic_drags`` (reads from session state) and ``render_drags_controls``
    (passes fresh widget values).
    """
    out = {"enabled": bool(enabled)}
    for k in _DRAG_KEYS:
        out[k] = float(component_pcts[k])
    out["total_annual_drag_pct"] = round(sum(out[k] for k in _DRAG_KEYS), 4)
    return out


def get_economic_drags() -> dict:
    """Resolve the active economic drags (Item 1) for this session.

    Mirrors ``_get_ai_config`` / profile-seeding: config.DRAGS is the source of
    truth for defaults, but the user can tune the components for the current
    session via the "Supuestos y drags" UI (stored in ``st.session_state`` under
    ``drag_<field>`` / ``drags_enabled``). Returns a plain dict ready to pass to
    ``MonteCarloSimulator.run(drags=...)`` and to persist in a PlanSnapshot.
    """
    from config import DRAGS

    return _build_economic_drags(
        bool(st.session_state.get("drags_enabled", DRAGS.enabled)),
        {k: st.session_state.get(f"drag_{k}", getattr(DRAGS, k)) for k in _DRAG_KEYS},
    )


def drags_to_tuple(drags: dict | None) -> tuple | None:
    """Hashable form of a drags dict for ``@st.cache_data`` keys."""
    if not drags:
        return None
    return tuple(sorted((k, v) for k, v in drags.items() if k != "total_annual_drag_pct"))


def format_drags_badge(drags: dict | None) -> str:
    """One-line caption summarizing the active drags (Item 1)."""
    if not drags or not drags.get("enabled", True):
        return "🟢 Sin drags — números base (sin fees/impuestos/fricciones)."
    total = drags.get("total_annual_drag_pct") or sum(
        float(drags.get(k, 0.0)) for k in _DRAG_KEYS
    )
    if total <= 0:
        return "🟢 Sin drags — números base (sin fees/impuestos/fricciones)."
    parts = []
    if drags.get("annual_fee_pct"):
        parts.append(f"fee {drags['annual_fee_pct']:.2f}%")
    if drags.get("dividend_tax_drag_pct"):
        parts.append(f"tax div {drags['dividend_tax_drag_pct']:.2f}%")
    if drags.get("rebalance_cost_annual_pct"):
        parts.append(f"rebal {drags['rebalance_cost_annual_pct']:.2f}%")
    if drags.get("ar_buffer_pct"):
        parts.append(f"buffer AR {drags['ar_buffer_pct']:.2f}%")
    detail = " + ".join(parts) if parts else "—"
    return f"🟠 Drags activos: {detail} = **{total:.2f}%/año** sobre el crecimiento."


# Canonical "what we model / what we don't" text — single source of truth for
# the assumptions disclaimer shown across pages (Plan, About, Home, PDF).
ASSUMPTIONS_TEXT = (
    "**Qué modela esta herramienta y qué no.** Las proyecciones (Optimizer, "
    "Monte Carlo, Plan) parten de historia de precios **pura** de yfinance, con "
    "ajustes conservadores (+10% volatilidad, −20% retorno histórico). Salvo que "
    "actives la capa de *drags económicos*, los números asumen **0% de fees, 0% "
    "de impuestos sobre dividendos, 0% de costo de rebalanceo** y **no** modelan "
    "fricciones locales argentinas (cepo, brecha cambiaria, diferencial de "
    "inflación). No es asesoramiento financiero ni fiscal. Activá los drags para "
    "ver un escenario más realista; el caso base se conserva siempre como "
    "referencia."
)


def render_assumptions_disclaimer(*, expander: bool = True) -> None:
    """Render the canonical assumptions disclaimer (Item 1).

    ``expander=True`` shows it as a collapsible block (Plan/Home); ``False``
    renders inline (About). Imposible de pasar por alto en pantallas clave.
    """
    if expander:
        with st.expander("ℹ️ Supuestos y limitaciones del modelo", expanded=False):
            st.markdown(ASSUMPTIONS_TEXT)
    else:
        st.markdown(ASSUMPTIONS_TEXT)


def render_drags_controls(*, key_prefix: str = "") -> dict:
    """Render the 'Supuestos y drags económicos' control block (Item 1).

    Persistent expander used by Plan + Simulaciones. Lets the user toggle and
    tune the drag components for the current session, seeding from config.DRAGS.
    Returns the active drags dict (also retrievable via ``get_economic_drags``).
    """
    from config import DRAGS, OPTIMIZER

    with st.expander("📊 Supuestos y drags económicos aplicados", expanded=False):
        st.caption(
            "Por defecto las proyecciones asumen cero fees/impuestos/fricciones. "
            "Activá drags realistas para ver el impacto. El caso base se conserva "
            "como referencia."
        )
        enabled = st.toggle(
            "Aplicar drags económicos a las simulaciones",
            value=bool(st.session_state.get("drags_enabled", DRAGS.enabled)),
            key=f"{key_prefix}drags_enabled_toggle",
            help="Off = números base idénticos al estado sin esta capa.",
        )
        st.session_state["drags_enabled"] = enabled
        c1, c2 = st.columns(2)
        with c1:
            _fee = st.number_input(
                "Fee anual % (TER + advisory)", min_value=0.0, max_value=5.0,
                value=float(st.session_state.get("drag_annual_fee_pct", DRAGS.annual_fee_pct)),
                step=0.05, disabled=not enabled, key=f"{key_prefix}drag_fee",
            )
            st.session_state["drag_annual_fee_pct"] = _fee
            _tax = st.number_input(
                "Drag por impuesto a dividendos % anual", min_value=0.0, max_value=5.0,
                value=float(st.session_state.get("drag_dividend_tax_drag_pct", DRAGS.dividend_tax_drag_pct)),
                step=0.05, disabled=not enabled, key=f"{key_prefix}drag_tax",
                help="No-residente US: ~15-30% del yield bruto, expresado como % anual del NAV.",
            )
            st.session_state["drag_dividend_tax_drag_pct"] = _tax
        with c2:
            _rebal = st.number_input(
                "Costo de rebalanceo % anual", min_value=0.0, max_value=5.0,
                value=float(st.session_state.get("drag_rebalance_cost_annual_pct", DRAGS.rebalance_cost_annual_pct)),
                step=0.05, disabled=not enabled, key=f"{key_prefix}drag_rebal",
            )
            st.session_state["drag_rebalance_cost_annual_pct"] = _rebal
            _ar = st.number_input(
                "Buffer AR % anual (cepo / FX / inflación)", min_value=0.0, max_value=10.0,
                value=float(st.session_state.get("drag_ar_buffer_pct", DRAGS.ar_buffer_pct)),
                step=0.10, disabled=not enabled, key=f"{key_prefix}drag_ar",
                help="⚠️ Evitá doble conteo: el Optimizer ya descuenta el riesgo argentino "
                     f"(−{(1 - OPTIMIZER.ars_risk_discount) * 100:.0f}% al score de ADRs AR en "
                     "perfiles Conservador/Moderado). Usá este buffer solo para el riesgo país "
                     "que NO esté ya reflejado en cómo elegiste la cartera (ej. inflación/FX a "
                     "nivel de todo el plan). Si ya ponderaste por ARS, dejalo en 0.",
            )
            st.session_state["drag_ar_buffer_pct"] = _ar
        # S17: build from the fresh widget values, not from the session_state
        # keys we just wrote.
        drags = _build_economic_drags(enabled, {
            "annual_fee_pct": _fee,
            "dividend_tax_drag_pct": _tax,
            "rebalance_cost_annual_pct": _rebal,
            "ar_buffer_pct": _ar,
        })
        st.caption(format_drags_badge(drags))
    return drags


# ------------------------------------------------------------------ #
#  Withdrawal / decumulation strategies (Fase H.1)                     #
# ------------------------------------------------------------------ #

# Human-readable labels for the strategy selector.
_WITHDRAWAL_LABELS = {
    "none":         "Acumulación (sin retiros)",
    "fixed_real":   "Retiro fijo real (regla del 4%)",
    "constant_pct": "% constante del valor actual",
    "guardrails":   GUARDRAILS_LABEL,
}


def _build_withdrawal_strategy(kind, *, amount: float, pct: float, base: float) -> dict | None:
    """Build a strategy dict from resolved values — no ``st.session_state`` reads (S17).

    ``amount`` (USD), ``pct`` and ``base`` (both whole-percent) are only used for
    the branch matching ``kind``. Shared by ``get_withdrawal_strategy`` (reads
    from session state) and ``render_withdrawal_controls`` (passes fresh widget
    values, so it never re-reads what it just wrote).
    """
    from config import WITHDRAWAL

    if kind in (None, "", "none"):
        return None

    if kind == "fixed_real":
        if amount <= 0:
            return None
        return {
            "kind": "fixed_real",
            "annual_amount": amount,
            "label": f"Retiro fijo real ${amount:,.0f}/año",
        }

    if kind == "constant_pct":
        p = pct / 100.0
        if p <= 0:
            return None
        return {
            "kind": "constant_pct",
            "pct": p,
            "label": f"{p * 100:.1f}% del valor actual",
        }

    if kind == "guardrails":
        b = base / 100.0
        if b <= 0:
            return None
        return {
            "kind": "guardrails",
            "pct": b,
            "guardrail_ceiling_band": WITHDRAWAL.guardrail_ceiling_band,
            "guardrail_floor_band": WITHDRAWAL.guardrail_floor_band,
            "guardrail_cut_pct": WITHDRAWAL.guardrail_cut_pct,
            "guardrail_raise_pct": WITHDRAWAL.guardrail_raise_pct,
            "label": f"Guardrails simplificado {b * 100:.1f}%",
        }
    return None


def get_withdrawal_strategy(initial_value: float | None = None) -> dict | None:
    """Resolve the active decumulation strategy for this session (Fase H.1).

    Returns a strategy dict ready for
    ``MonteCarloSimulator.run(withdrawal_strategy=...)`` / ``PlanSnapshot``,
    or ``None`` in accumulation mode (no strategy). Mirrors
    ``get_economic_drags``: config.WITHDRAWAL is the source of truth for
    defaults, overridden per-session by ``render_withdrawal_controls``.
    ``None`` keeps the Monte Carlo result byte-identical to the base engine.
    """
    from config import WITHDRAWAL

    return _build_withdrawal_strategy(
        st.session_state.get("withdrawal_kind", "none"),
        amount=float(st.session_state.get("withdrawal_amount", 0.0)),
        pct=float(st.session_state.get("withdrawal_pct", WITHDRAWAL.constant_pct)),
        base=float(st.session_state.get("withdrawal_base_pct", WITHDRAWAL.base_withdrawal_pct)),
    )


def get_longevity_years() -> int:
    """Planning horizon (years) the 'income lasts' metric refers to."""
    from config import WITHDRAWAL

    return int(st.session_state.get("withdrawal_longevity_years", WITHDRAWAL.default_longevity_years))


def withdrawal_to_tuple(strategy: dict | None) -> tuple | None:
    """Hashable form of a withdrawal-strategy dict for ``@st.cache_data`` keys."""
    if not strategy:
        return None
    return tuple(sorted(
        (k, v) for k, v in strategy.items()
        if k != "label" and isinstance(v, (int, float, str))
    ))


def format_withdrawal_badge(strategy: dict | None) -> str:
    """One-line caption summarizing the active decumulation strategy."""
    if not strategy:
        return "🟢 Modo acumulación — sin estrategia de retiro (números base)."
    kind = strategy.get("kind")
    if kind == "fixed_real":
        return (f"🏖️ **Retiro fijo real**: ${strategy.get('annual_amount', 0):,.0f}/año, "
                "ajustado por inflación (estilo regla del 4%).")
    if kind == "constant_pct":
        return (f"🏖️ **% constante**: {strategy.get('pct', 0) * 100:.1f}% del valor *actual* "
                "cada año (el ingreso varía con el mercado, nunca se agota del todo).")
    if kind == "guardrails":
        # U1-6: the badge names the two rules that run and the three that do not,
        # so the simplified method never borrows the name of the full one.
        return (f"🏖️ **{GUARDRAILS_LABEL}**: tasa base {strategy.get('pct', 0) * 100:.1f}%, "
                "recorta el gasto en caídas y lo sube en mercados buenos. "
                + GUARDRAILS_OMISSIONS)
    return "🟢 Modo acumulación."


def render_withdrawal_controls(*, key_prefix: str = "", initial_value: float = 100_000.0) -> dict | None:
    """Render the 'Estrategia de retiro' control block (Fase H.1).

    Persistent expander used by Simulaciones + Plan. Lets the user choose how
    they will *spend down* the portfolio in retirement, seeding from
    config.WITHDRAWAL. Returns the active strategy dict (or None in accumulation
    mode), also retrievable via ``get_withdrawal_strategy``.
    """
    from config import WITHDRAWAL

    # Seeded from session state; overridden by the active branch's widget below.
    # The strategy dict is then built from these locals — S17: this function
    # never re-reads the session_state keys it just wrote.
    amount = float(st.session_state.get("withdrawal_amount", 0.0))
    pct = float(st.session_state.get("withdrawal_pct", WITHDRAWAL.constant_pct))
    base = float(st.session_state.get("withdrawal_base_pct", WITHDRAWAL.base_withdrawal_pct))

    with st.expander("🏖️ Estrategia de retiro (decumulación)", expanded=False):
        st.caption(
            "Define cómo vas a *gastar* la cartera en la fase de retiro. Por defecto "
            "estás en **acumulación** (sin retiros) y los números son los base. "
            "Elegí una estrategia para ver cuánto dura tu ingreso."
        )
        kinds = list(_WITHDRAWAL_LABELS.keys())
        cur = st.session_state.get("withdrawal_kind", "none")
        kind = st.selectbox(
            "Estrategia de gasto",
            options=kinds,
            index=kinds.index(cur) if cur in kinds else 0,
            format_func=lambda k: _WITHDRAWAL_LABELS[k],
            key=f"{key_prefix}wd_kind",
            help="Off (acumulación) = números base idénticos al estado sin esta capa.",
        )
        st.session_state["withdrawal_kind"] = kind

        if kind == "fixed_real":
            amount = st.number_input(
                "Retiro anual (USD, ajustado por inflación)",
                min_value=0.0, max_value=5_000_000.0,
                value=float(st.session_state.get("withdrawal_amount",
                            round(initial_value * WITHDRAWAL.base_withdrawal_pct / 100.0, -2))),
                step=1_000.0, format="%.0f", key=f"{key_prefix}wd_amount",
                help="Monto fijo que retirás el primer año; crece cada año con la inflación.",
            )
            st.session_state["withdrawal_amount"] = amount
        elif kind == "constant_pct":
            pct = st.number_input(
                "% del valor actual a retirar cada año",
                min_value=0.5, max_value=15.0,
                value=float(st.session_state.get("withdrawal_pct", WITHDRAWAL.constant_pct)),
                step=0.25, format="%.2f", key=f"{key_prefix}wd_pct",
                help="Se recalcula sobre el saldo de cada año: el ingreso varía pero la cartera no se agota del todo.",
            )
            st.session_state["withdrawal_pct"] = pct
        elif kind == "guardrails":
            base = st.number_input(
                "Tasa de retiro base %",
                min_value=0.5, max_value=12.0,
                value=float(st.session_state.get("withdrawal_base_pct", WITHDRAWAL.base_withdrawal_pct)),
                step=0.25, format="%.2f", key=f"{key_prefix}wd_base_pct",
                help=guardrails_help(WITHDRAWAL),
            )
            st.session_state["withdrawal_base_pct"] = base

        if kind != "none":
            longevity = st.number_input(
                "Duración del retiro (años) para medir longevidad",
                min_value=5, max_value=60,
                value=int(st.session_state.get("withdrawal_longevity_years", WITHDRAWAL.default_longevity_years)),
                step=1, key=f"{key_prefix}wd_longevity",
                help="Horizonte sobre el que se calcula 'probabilidad de que el ingreso dure'.",
            )
            st.session_state["withdrawal_longevity_years"] = longevity

        strategy = _build_withdrawal_strategy(kind, amount=amount, pct=pct, base=base)
        st.caption(format_withdrawal_badge(strategy))
    return strategy


# ------------------------------------------------------------------ #
#  AI config helper                                                    #
# ------------------------------------------------------------------ #

def _get_ai_config(context: str = "detailed_analysis") -> AIConfig:
    enabled = st.session_state.get("ai_enabled", False)
    use_in_screener = st.session_state.get("ai_use_in_screener", False)
    effective_enabled = enabled and (context != "screener" or use_in_screener)
    return AIConfig(
        provider=st.session_state.get("ai_provider", "claude"),
        model=st.session_state.get("ai_model", "claude-sonnet-4-6"),
        api_key=st.session_state.get("ai_api_key", ""),
        enabled=effective_enabled,
        use_in_screener=use_in_screener,
    )


# ------------------------------------------------------------------ #
#  Cached analysis                                                     #
# ------------------------------------------------------------------ #

@st.cache_data(ttl=3600, show_spinner=False)
def cached_full_analysis(
    symbol: str,
    ai_provider: str = "",
    ai_model: str = "",
    ai_enabled: bool = False,
    ai_api_key: str = "",
    engine_version: str = ENGINE_VERSION,
):
    # `engine_version` is part of the cache key so a scoring rewrite (U2-2,
    # missing-metric, FFO, yield units) cannot keep serving the previous
    # FundamentalResult for the remaining TTL of a long-lived process.
    _ = engine_version
    ai_cfg = AIConfig(
        provider=ai_provider,
        model=ai_model,
        api_key=ai_api_key,
        enabled=ai_enabled,
    )
    fund, tech, decision = full_analysis(symbol, ai_config=ai_cfg)
    return fund, tech, decision


@st.cache_data(ttl=1800, show_spinner=False)
def cached_personal_book_analysis(
    positions_tuple: tuple,
    convictions_tuple: tuple,
    ai_provider: str = "",
    ai_model: str = "",
    ai_enabled: bool = False,
    ai_api_key: str = "",
    engine_version: str = ENGINE_VERSION,
):
    """
    Wrapper cacheado del motor de sizing del Libro Personal.

    Params como tuplas para hashability de ``@st.cache_data``:
      positions_tuple   — ((symbol, market_value, weight_pct, shares, avg_cost,
                            purchase_date, sector), ...)
      convictions_tuple — ((symbol, level), ...)

    El enrichment reutiliza ``cached_full_analysis`` (mismo cache TTL por ticker),
    de modo que no se re-fetchea fundamental/técnico/moat por cada análisis de libro.
    La acción de sizing es 100% rule-based; el AIConfig sólo afecta el análisis
    fundamental subyacente (no la decisión de tamaño).
    """
    # Same key as `cached_full_analysis`: a scoring rewrite must not keep
    # serving a stale personal-book result for the remaining 30m TTL.
    _ = engine_version
    from portfolio.personal_sizer import analyze_personal_book

    positions = {
        p[0]: {
            "symbol": p[0],
            "market_value": p[1],
            "weight_pct": p[2],
            "shares": p[3],
            "avg_cost": p[4],
            "purchase_date": p[5],
            "sector": p[6],
        }
        for p in positions_tuple
    }
    convictions = {c[0]: c[1] for c in convictions_tuple}

    def _enrich(symbol: str) -> dict:
        fund, tech, decision = cached_full_analysis(
            symbol, ai_provider, ai_model, ai_enabled, ai_api_key
        )
        dq = getattr(fund, "data_quality", None) or {}
        return {
            "adjusted_score": getattr(fund, "adjusted_score", 0.0) or getattr(fund, "total_score", 0.0),
            "moat_classification": getattr(fund, "moat_classification", "None"),
            "tailwind_classification": getattr(fund, "tailwind_classification", "Neutral"),
            "has_margin_of_safety": bool(getattr(decision, "has_margin_of_safety", False)),
            "margin_of_safety_pct": getattr(fund, "margin_of_safety_pct", None),
            "data_quality_level": (dq.get("level") if isinstance(dq, dict) else "good") or "good",
            "rsi_weekly": getattr(tech, "rsi_weekly", None),
            # Sin bool(): None significa "sin historial", y coercionarlo lo
            # convertiría en "debajo de la media" (U3-1).
            "above_sma200": getattr(tech, "above_sma200", True),
            "sma200_slope_pct": getattr(tech, "sma200_slope_pct", None),
            "price_vs_52w_high_pct": getattr(tech, "price_vs_52w_high_pct", 0.0),
            "retirement_action": getattr(decision, "action", "HOLD"),
        }

    return analyze_personal_book(positions, convictions, enrich_fn=_enrich)


@st.cache_data(ttl=1800, show_spinner=False)
def cached_monte_carlo(
    symbols: tuple[str, ...],
    weights_tuple: tuple[float, ...] | None,
    horizon_years: int,
    n_sims: int,
    initial_value: float,
    annual_withdrawal: float,
    target_value: float,
    annual_contribution: float = 0.0,      # savings per year, deposited monthly (U4-1)
    withdrawal_growth_rate: float = 0.0,   # inflation adjustment on withdrawals (Phase 0)
    seed: int = 42,
    vol_scale: float = 1.0,
    return_scale: float = 1.0,
    drags_tuple: tuple | None = None,      # Item 1: hashable drags (None = base behavior)
    withdrawal_tuple: tuple | None = None, # Fase H.1: hashable withdrawal strategy (None = base)
    longevity_years: int | None = None,    # Fase H.1: horizon for "income lasts" metric
    include_realistic_reference: bool = True,  # show realistic (no-haircut) next to conservative
):
    """Cache Monte Carlo runs for 30 min — same params = instant re-render.

    vol_scale / return_scale: applied on top of the global conservative adjustment.
    Used by the profile-comparison tab to show Conservador/Moderado/Agresivo on one chart.
    drags_tuple: hashable form of the economic-drags dict (see ``drags_to_tuple``).
    withdrawal_tuple: hashable form of the withdrawal-strategy dict (see
    ``withdrawal_to_tuple``). When given it REPLACES ``annual_withdrawal`` and
    populates the decumulation metrics. None for both keeps the result
    byte-identical to the pre-feature engine.
    """
    import numpy as np

    from portfolio.monte_carlo import MonteCarloSimulator

    w_np = np.array(weights_tuple) if weights_tuple else None
    sim  = MonteCarloSimulator(list(symbols), w_np, seed=seed,
                               vol_scale=vol_scale, return_scale=return_scale)
    drags = dict(drags_tuple) if drags_tuple else None
    withdrawal_strategy = dict(withdrawal_tuple) if withdrawal_tuple else None
    return sim.run(
        horizon_years=horizon_years,
        n_sims=n_sims,
        initial_value=initial_value,
        annual_withdrawal=annual_withdrawal,
        annual_contribution=annual_contribution,
        target_value=target_value,
        withdrawal_growth_rate=withdrawal_growth_rate,
        drags=drags,
        withdrawal_strategy=withdrawal_strategy,
        longevity_years=longevity_years,
        include_realistic_reference=include_realistic_reference,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def cached_goal_simulation(
    symbols: tuple,
    weights_tuple: tuple | None,
    goals_serialized: tuple,   # tuple of dicts for hashability
    total_capital: float,
    n_sims: int,
    vol_scale: float = 1.0,
    return_scale: float = 1.0,
    seed: int = 42,
    engine_version: str = ENGINE_VERSION,
):
    """Cache multi-goal simulation results for 30 min.

    ``engine_version`` is a cache key, not an argument anyone passes: without it
    a bump to the maths would keep serving pre-bump numbers for up to half an
    hour after deploy, which is exactly when a user is most likely to re-check
    a plan the release just changed.
    """
    import numpy as np

    from portfolio.goals import Goal, GoalPlanner

    w_np = np.array(weights_tuple) if weights_tuple else None
    planner = GoalPlanner(list(symbols), w_np, seed=seed)

    goals = [
        Goal(
            name=g["name"],
            target_amount_today=g["target_amount_today"],
            horizon_years=g["horizon_years"],
            priority=g["priority"],
            expected_inflation=g["expected_inflation"],
            annual_contribution=g["annual_contribution"],
            allocated_capital=g["allocated_capital"],
            notes=g.get("notes", ""),
            goal_type=g.get("goal_type", "otro"),
        )
        for g in goals_serialized
    ]

    return planner.run(
        goals=goals,
        total_capital=total_capital,
        n_sims=n_sims,
        vol_scale=vol_scale,
        return_scale=return_scale,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def cached_goal_savings_target(
    symbols: tuple,
    weights_tuple: tuple | None,
    goal_serialized: tuple,    # tuple of (key, value) pairs for hashability
    allocated_capital: float,
    target_prob_pct: float,
    n_sims: int,
    vol_scale: float = 1.0,
    return_scale: float = 1.0,
    seed: int = 42,
    engine_version: str = ENGINE_VERSION,
):
    """TOTAL monthly contribution that lifts a goal to ``target_prob_pct``.

    Thin cached wrapper over :func:`portfolio.goals.monthly_savings_for_probability`.
    Returns ``float`` or ``None`` when saving alone cannot get there.

    Pass the SAME ``vol_scale``/``return_scale`` used by ``cached_goal_simulation``
    for this profile — otherwise the advice answers a different model than the
    probability shown on the card, which is the whole defect being fixed.
    """
    import numpy as np

    from portfolio.goals import Goal, GoalPlanner, monthly_savings_for_probability

    w_np = np.array(weights_tuple) if weights_tuple else None
    planner = GoalPlanner(list(symbols), w_np, seed=seed)
    g = dict(goal_serialized)

    goal = Goal(
        name=g["name"],
        target_amount_today=g["target_amount_today"],
        horizon_years=g["horizon_years"],
        priority=g["priority"],
        expected_inflation=g["expected_inflation"],
        annual_contribution=g["annual_contribution"],
        allocated_capital=g["allocated_capital"],
        notes=g.get("notes", ""),
        goal_type=g.get("goal_type", "otro"),
    )

    return monthly_savings_for_probability(
        planner,
        goal,
        allocated_capital=allocated_capital,
        target_prob_pct=target_prob_pct,
        n_sims=n_sims,
        vol_scale=vol_scale,
        return_scale=return_scale,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def cached_goal_optimization(
    scored_tickers_tuple: tuple,        # tuple of dicts (hashable)
    goals_serialized: tuple,            # tuple of dicts (same format as cached_goal_simulation)
    profile_key: str,
    current_weights_tuple: tuple | None,
) -> tuple:
    """Cache goal-aware optimization results for 30 min. Returns (OptimizationResult, explanation_str)."""
    from portfolio.optimizer import PortfolioOptimizer

    scored_tickers = list(scored_tickers_tuple)
    current_weights = dict(current_weights_tuple) if current_weights_tuple else None
    goals = list(goals_serialized)

    optimizer = PortfolioOptimizer(profile=profile_key)
    return optimizer.optimize_for_goals(scored_tickers, goals, current_weights)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_stress_test(
    sector_weights_tuple: tuple,
    initial_value: float,
):
    """Cache stress test results per sector allocation — recomputes only when weights change."""
    from portfolio.stress_test import StressTester

    sector_weights = dict(sector_weights_tuple)
    tester = StressTester()
    return tester.run(sector_weights, initial_value=initial_value)


def run_holdings_committee(
    *,
    metrics,
    sector_weights: dict[str, float],
    position_weights: dict[str, float],
    total_value: float,
    active_plan=None,
):
    """Convene the committee over the ACTUAL portfolio (real holdings). → CommitteeVerdict.

    O4: the orchestration lives in ``analysis.committee.run_holdings_committee``
    (a free function, no ``st.*``). This wrapper only resolves the AI config and
    the ``@st.cache_data`` stress test from the Streamlit layer and delegates.
    Returns ``None`` when AI is disabled.
    """
    from analysis.committee import run_holdings_committee as _run_holdings_committee

    ai_cfg = _get_ai_config()
    if not getattr(ai_cfg, "enabled", False):
        return None

    sw = dict(sector_weights or {})
    stress_results = cached_stress_test(tuple(sorted(sw.items())), 100_000.0) if sw else []

    return _run_holdings_committee(
        metrics=metrics,
        sector_weights=sw,
        position_weights=position_weights,
        total_value=total_value,
        ai_config=ai_cfg,
        stress_results=stress_results,
        active_plan=active_plan,
    )


def render_committee_verdict(verdict, *, footer_facts: str = "") -> None:
    """Render a portfolio committee verdict: plan-health banner + consensus/dissent.

    Reused by the Portfolio page. ``footer_facts`` is an optional pre-formatted
    "hard numbers" string shown under a 📊 Calculado badge.
    """
    from config import COMMITTEE

    label = COMMITTEE.portfolio_action_labels.get(verdict.action, verdict.action)
    color = ACTION_COLOR.get(verdict.action, "#888")
    n_total = len(verdict.opinions)
    n_agree = sum(
        1 for o in verdict.opinions
        if o.ok and ((o.stance in ("STRONG BUY", "BUY") and verdict.action in ("STRONG BUY", "BUY"))
                     or (o.stance == verdict.action))
    )

    st.markdown(
        f"""<div style="background:{color}22;border-left:4px solid {color};
        padding:12px;border-radius:4px;margin:8px 0">
        <b style="color:{color};font-size:1.2em">🏛️ Veredicto: {label}</b>
        &nbsp;|&nbsp; Confianza: {verdict.confidence}
        &nbsp;|&nbsp; Acuerdo: {n_agree}/{n_total} agentes
        </div>""",
        unsafe_allow_html=True,
    )
    render_ai_badge("dictamen del comité; se apoya en los cálculos, no los reemplaza")

    _c1, _c2 = st.columns(2)
    with _c1:
        st.markdown("**✅ Consenso**")
        if verdict.consensus_points:
            for _p in verdict.consensus_points:
                st.success(_p)
        else:
            st.caption("Sin puntos de consenso claros.")
    with _c2:
        st.markdown("**⚖️ Disenso (bear case)**")
        if verdict.dissent:
            for _d in verdict.dissent:
                st.warning(_d)
        else:
            st.caption("Sin disenso registrado.")

    with st.expander("👥 Ver cada agente"):
        for o in verdict.opinions:
            if o.error:
                st.caption(f"⚠️ **{o.role}** — no disponible ({o.error})")
                continue
            _lbl = COMMITTEE.portfolio_action_labels.get(o.stance, o.stance)
            st.markdown(f"**{o.role}** — {_lbl} ({o.confidence})")
            for _kp in o.key_points:
                st.caption(f"• {_kp}")
            for _cn in o.concerns:
                st.caption(f"⚠️ {_cn}")
            st.divider()

    if footer_facts:
        render_calc_badge("base del dictamen · " + footer_facts)


def _track_payload(fund, decision) -> dict:
    """Flatten what the track record needs from one analysed ticker.

    Plain JSON-serializable primitives, so it survives being persisted with the run
    and can be logged later from the page instead of from inside the thread pool.
    """
    from analysis.track_record import snapshot_calibration_inputs

    return {
        "symbol": getattr(fund, "symbol", ""),
        "action": getattr(decision, "action", ""),
        "confidence": getattr(decision, "confidence", "MEDIUM"),
        "fundamental_score": float(getattr(decision, "fundamental_score", 0.0) or 0.0),
        "technical_signal": getattr(decision, "technical_signal", "") or "",
        "rationale": list(getattr(decision, "rationale", []) or [])[:4],
        "price_at_rec": getattr(fund, "current_price", None) or None,
        "asset_class": getattr(fund, "asset_class", "equity") or "equity",
        "inputs": snapshot_calibration_inputs(fund),
    }


def log_screener_run(rows: list) -> int:
    """Record a finished screener run as recommendations. Returns rows written.

    Why the Screener logs at all: capture used to happen only when a person opened a
    ticker, ran the committee, or an alert fired — 57 recommendations over two months
    across **15 of 149 tickers**, with 36 BUY, 12 STRONG BUY, 1 REDUCE and **zero
    SELL**. You cannot calibrate where to draw a line when one side of it has no
    observations. A full run is the unbiased sample: every ticker, every verdict,
    including the ones nobody would have clicked on.

    These carry ``source="screener"`` so they never masquerade as recommendations the
    user actually saw — the Track Record page filters on it.

    Non-scorable assets are skipped: an ETF's "SELL" is an artifact of scoring it with
    machinery built for companies, which is exactly what ``asset_class.py`` settled.

    Best-effort throughout: the store already guarantees a logging failure cannot
    break its caller, and same-day duplicates are deduped there by symbol and action.
    """
    from types import SimpleNamespace

    from analysis.asset_class import is_fundamentally_scorable
    from analysis.track_record import track_record_store

    written = 0
    for row in rows or []:
        payload = row.get("_track") if isinstance(row, dict) else None
        if not payload or not payload.get("action"):
            continue
        if not is_fundamentally_scorable(payload.get("asset_class", "equity")):
            continue
        try:
            decision = SimpleNamespace(
                symbol=payload.get("symbol", ""),
                action=payload.get("action", ""),
                confidence=payload.get("confidence", "MEDIUM"),
                fundamental_score=payload.get("fundamental_score", 0.0),
                technical_signal=payload.get("technical_signal", ""),
                rationale=payload.get("rationale", []),
            )
            rec_id = track_record_store.log_recommendation(
                decision,
                source="screener",
                price_at_rec=payload.get("price_at_rec"),
                fundamental=SimpleNamespace(**(payload.get("inputs") or {})),
            )
            if rec_id:
                written += 1
        except Exception as exc:  # never let capture break the page
            logger.debug(f"screener track-record log skipped for {payload.get('symbol')} — {exc}")
    if written:
        logger.info(f"track_record: logged {written} screener recommendations")
    return written


def _extract_row_data(sym: str, fund, tech, decision) -> dict:
    """Raw screener-row data — no UI strings, badges or truncation (S22).

    Runs inside the thread pool. ``_format_row_for_display`` turns this into the
    table dict on the main thread, so the worker no longer mixes presentation
    with extraction.
    """
    from datetime import datetime

    why = decision_explanation(decision)
    return {
        "sym": sym,
        "company_name": fund.company_name,
        "sector": fund.sector,
        "asset_class": getattr(fund, "asset_class", "equity") or "equity",
        "action": decision.action,
        "action_emoji": decision.action_emoji,
        "why_headline": why["headline"],
        "why_confidence": why["confidence"],
        "why": why["why"],
        "why_risks": why["risks"],
        "why_full_headline": why["full_headline"],
        "adjusted_score": fund.adjusted_score,
        # Uncapped twin (audit item 11) — falls back to the capped score when 0.
        "raw_adjusted_score": getattr(fund, "raw_adjusted_score", None) or fund.adjusted_score,
        "total_score": fund.total_score,
        "consistency_score": fund.consistency_score,
        "piotroski_score": fund.piotroski_score,
        "moat_score": getattr(fund, "moat_score", 0.0),
        "moat_classification": getattr(fund, "moat_classification", ""),
        "tailwind_classification": getattr(fund, "tailwind_classification", "Neutral"),
        "tailwind_score": getattr(fund, "tailwind_score", 0.0),
        "technical_signal": tech.signal,
        "pe_ratio": fund.pe_ratio,
        "roe": fund.roe,
        # Window is whatever the statements supported (typically 3y). Never "5Y".
        "revenue_cagr_5y": fund.revenue_cagr_5y,
        "revenue_cagr_years": getattr(fund, "revenue_cagr_years", 0) or None,
        "dividend_yield": fund.dividend_yield,
        "margin_of_safety_pct": fund.margin_of_safety_pct,
        "current_price": fund.current_price,
        "data_quality": getattr(fund, "data_quality", None),
        # When this row was measured — enables "refresh only the stale ones" (item 16).
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        # Flattened here because this is the only place with fund + decision in
        # hand; the page logs these to SQLite sequentially after the run.
        "track": _track_payload(fund, decision),
    }


def _format_row_for_display(d: dict) -> dict:
    """Screener-row table dict — badges, emoji, truncation (S22). Main-thread only."""
    mc = d["moat_classification"]
    return {
        "Ticker": d["sym"],
        "Company": d["company_name"][:25],
        "Sector": ("🪙 Crypto" if d["sector"] == "Crypto" else d["sector"]),
        # Audit item 01 — funds/crypto have no statements; carried so the page
        # can segment instead of ranking them against companies.
        "Clase": d["asset_class"],
        "Signal": f"{d['action_emoji']} {d['action']}",
        # Audit item 04 — the sentence that reconciles a high score with a
        # cautious action; this used to be discarded.
        "Motivo": d["why_headline"],
        "Conf.": d["why_confidence"],
        "_why": d["why"],
        "_risks": d["why_risks"],
        "_why_headline": d["why_full_headline"],
        "Adj. Score": d["adjusted_score"],
        # Uncapped twin (audit item 11) — for sorting, not judging.
        "Score bruto": d["raw_adjusted_score"],
        "Base Score": d["total_score"],
        "Consistency": d["consistency_score"],
        "Piotroski": d["piotroski_score"],
        "Moat Score": d["moat_score"],
        "Moat": f"{_MOAT_EMOJI.get(mc, '⚪')} {mc}",
        "Viento": tailwind_badge(d["tailwind_classification"], d["tailwind_score"]),
        "Technical": d["technical_signal"],
        "P/E": d["pe_ratio"],
        "ROE %": d["roe"],
        "Rev CAGR %": d["revenue_cagr_5y"],
        "CAGR años": d["revenue_cagr_years"],
        "Div Yield %": d["dividend_yield"],
        "MoS %": d["margin_of_safety_pct"],
        "Price": d["current_price"],
        "Datos": data_quality_badge(d["data_quality"]),
        "_measured_at": d["measured_at"],
        # Raw quality dict — the page rolls these up instead of parsing the badge.
        "_dq": d["data_quality"],
        "_track": d["track"],
    }


def _analyse_universe_parallel(
    symbols: list[str],
    ai_cfg: AIConfig,
    progress_bar,
    status_text,
    eta_per_ticker: float | None = None,
) -> tuple[list[dict], list[dict], float]:
    """
    Run cached_full_analysis for each symbol in a thread pool.
    Workers capped at min(6, cpu_count) to stay within macOS FD limits.
    A per-ticker exception never aborts the whole run.

    Returns ``(rows, failures, elapsed_seconds)``. Failures used to be swallowed —
    the ticker simply never appeared and "Stocks screened" counted the survivors,
    so a run that lost three symbols to a yfinance hiccup was indistinguishable
    from a complete one (audit item 05). Each failure is
    ``{"Ticker", "Error", "Tipo"}`` so the page can name what is missing and offer
    a retry.

    ``eta_per_ticker`` (seconds, measured on a previous run) turns the progress
    line into a countdown instead of a bare fraction. The elapsed time comes back
    so the caller can store it and give the *next* run an honest estimate —
    audit item 13, where a caption promised "~15s" for a five-minute job.
    """
    import time

    started = time.monotonic()
    max_workers = min(6, os.cpu_count() or 4)
    total = len(symbols)
    completed = 0
    rows: list[dict] = []
    failures: list[dict] = []

    def _analyse_one(sym: str) -> tuple[dict | None, dict | None]:
        try:
            fund, tech, decision = cached_full_analysis(
                sym, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
            )
            # Extraction only — the display dict (badges, emoji, truncation) is
            # built on the main thread by _format_row_for_display (S22).
            return _extract_row_data(sym, fund, tech, decision), None
        except Exception as exc:
            logger.error(f"Screener: {sym} failed — {exc}")
            return None, {
                "Ticker": sym,
                "Tipo": type(exc).__name__,
                "Error": str(exc)[:160] or "sin detalle",
            }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_analyse_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            completed += 1
            sym = futures[future]
            elapsed = time.monotonic() - started
            # Prefer the throughput we are actually seeing; fall back to the
            # previous run's measurement until we have a couple of samples.
            rate = (elapsed / completed) if completed >= 3 else (eta_per_ticker or 0.0)
            remaining = rate * (total - completed)
            eta = f" · quedan {format_eta(remaining)}" if rate > 0 and completed < total else ""
            status_text.text(f"Analizando… {completed}/{total} listos (último: {sym}){eta}")
            progress_bar.progress(completed / total)
            result, failure = future.result()
            if result is not None:
                # Formatting moved out of the worker (S22) but the per-ticker
                # error-isolation guarantee has not: a bad row (e.g. a null
                # company_name) becomes a failure entry, not an aborted run.
                try:
                    rows.append(_format_row_for_display(result))
                except Exception as exc:
                    _sym = result.get("sym", "?")
                    logger.error(f"Screener: formatting {_sym} failed — {exc}")
                    failures.append({
                        "Ticker": _sym,
                        "Tipo": type(exc).__name__,
                        "Error": str(exc)[:160] or "sin detalle",
                    })
            if failure is not None:
                failures.append(failure)

    failures.sort(key=lambda f: f["Ticker"])
    return rows, failures, time.monotonic() - started


def _fetch_universe_parallel(
    symbols: list[str],
    ai_cfg: AIConfig,
    progress_bar,
    status_text,
    label: str = "Analizando",
) -> list[tuple]:
    """
    Generic parallel fetcher — returns (symbol, fund, tech, decision) tuples.
    Callers build their own output dicts from the raw analysis results.
    Workers capped at min(6, cpu_count) to stay within macOS FD limits.
    Per-ticker exceptions are logged and that ticker is silently dropped.
    """
    max_workers = min(6, os.cpu_count() or 4)
    total     = len(symbols)
    completed = 0
    results: list[tuple] = []

    def _fetch_one(sym: str) -> tuple | None:
        try:
            fund, tech, decision = cached_full_analysis(
                sym, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
            )
            return (sym, fund, tech, decision)
        except Exception as exc:
            logger.error(f"{label}: {sym} failed — {exc}")
            return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            completed += 1
            sym = futures[future]
            status_text.text(f"{label}… {completed}/{total} (último: {sym})")
            progress_bar.progress(completed / total)
            result = future.result()
            if result is not None:
                results.append(result)

    return results
