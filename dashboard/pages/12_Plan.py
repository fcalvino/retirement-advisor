"""
Mi Plan de Retiro — orquestación + persistencia de escenarios (Fase B).

Consolida en un solo lugar el trabajo que hoy vive fragmentado en
Optimizer (cartera + núcleo + narrativa Grok), Simulaciones (Monte Carlo +
Mis Metas) y el perfil personal. Permite:
  - Ver el "plan actual" de la sesión (cartera + núcleo + métricas + metas + MC + narrativa).
  - Guardar el escenario como un plan nombrado (persistente).
  - Cargar / comparar / borrar planes guardados.
  - Generar el PDF del plan y una "lista de compra" accionable del núcleo.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from loguru import logger

from config import AR_FX
from dashboard.onboarding import render_profile_summary
from dashboard.shared import (
    _get_ai_config,
    _snap_sim_horizon,
    compute_plan_health,
    escape_dollars,
    export_plan_bundle,
    format_withdrawal_badge,
    get_economic_drags,
    get_user_prefs,
    get_withdrawal_strategy,
    plan_health_history,
    plan_price_lookup,
    record_plan_health_now,
    render_ai_badge,
    render_assumptions_disclaimer,
    track_record_home_line,
)
from data.env_provenance import format_drift
from data.plan_context import activate_plan, compute_alignment_trades, deactivate_plan
from data.plan_store import PlanSnapshot, _slugify, plan_store
from data.product_ux import (
    MAX_DD_ESTIMATE_SHORT,
    PROXY_RATIO_HELP,
    PROXY_RATIO_LABEL,
    PROXY_RETURN_HELP,
    PROXY_RETURN_SHORT,
    max_dd_estimate_help,
)
from data.universe_loader import UNIVERSE_META

# Map a saved plan's profile name back to an optimizer profile key (for "load plan").
_PROFILE_NAME_TO_KEY = {"Conservador": "conservative", "Moderado": "moderate", "Agresivo": "aggressive"}
_SEVERITY_BADGE = {
    "alta":  ("#ff4444", "🔴"),
    "media": ("#ff8800", "🟠"),
    "baja":  ("#39b54a", "🟢"),
}

st.title("🗺️ Mi Plan de Retiro")
st.caption(
    "Tu plan consolidado: cartera optimizada + núcleo manejable + metas + proyección "
    "Monte Carlo + narrativa, todo guardable como un escenario nombrado. "
    "💵 Valores en USD. Esta herramienta es educativa, no es asesoramiento financiero."
)
render_assumptions_disclaimer()   # Item 1: radical transparency of assumptions
st.caption(f"📒 {track_record_home_line()}")  # backlog 15

prefs = get_user_prefs()

# ------------------------------------------------------------------ #
#  Perfil personal                                                    #
# ------------------------------------------------------------------ #

if prefs.is_onboarded:
    with st.container(border=True):
        st.markdown("##### 🧭 Tu perfil")
        render_profile_summary(prefs)
else:
    st.info(
        "💡 Definí tu **perfil de retiro** en 🏠 Inicio o ⚙️ Settings para que el plan "
        "use tu edad, horizonte y capital automáticamente.",
        icon="🧭",
    )

# ------------------------------------------------------------------ #
#  Resolver el plan actual de la sesión                               #
# ------------------------------------------------------------------ #

opt_result = st.session_state.get("optimizer_result") or st.session_state.get("optimizer_prev_result")
goals_list = st.session_state.get("goals_list", [])
mc_result  = st.session_state.get("mc_result")

_active_key  = st.session_state.get("active_universe_key", getattr(prefs, "active_universe", "default") or "default")
_active_name = UNIVERSE_META.get(_active_key, {}).get("name", _active_key)


def _session_mc_params() -> dict:
    """Assemble MC params for PDF/plan from session widgets + user prefs.

    Uses the shipped pure helper so savings from the profile are never dropped
    when Simulaciones was never opened (backlog 11 skeptic fix).
    """
    from data.product_ux import assemble_plan_pdf_mc_params

    return assemble_plan_pdf_mc_params(
        session=dict(st.session_state),
        prefs=prefs,
        profile_name=str(getattr(opt_result, "profile_name", "") or ""),
        personal={
            "monthly_savings": getattr(prefs, "monthly_savings", None),
            "annual_savings": getattr(prefs, "annual_savings", None),
            "current_capital": getattr(prefs, "current_capital", None),
            "primary_horizon_years": getattr(prefs, "primary_horizon_years", None),
        },
    )


def _metrics_row(metrics: dict) -> None:
    c = st.columns(6)
    c[0].metric(PROXY_RETURN_SHORT, f"{metrics.get('expected_return_pct', 0):.1f}%",
                help=PROXY_RETURN_HELP)
    c[1].metric("Volatilidad", f"{metrics.get('volatility_pct', 0):.1f}%")
    c[2].metric(PROXY_RATIO_LABEL, f"{metrics.get('sharpe_ratio', 0):.2f}",
                help=PROXY_RATIO_HELP)
    c[3].metric("Div. Yield", f"{metrics.get('dividend_yield_pct', 0):.2f}%")
    c[4].metric("Score prom.", f"{metrics.get('adjusted_score_avg', 0):.0f}/100")
    c[5].metric(MAX_DD_ESTIMATE_SHORT, f"{metrics.get('max_drawdown_estimate_pct', 0):.1f}%",
                help=max_dd_estimate_help())


def _core_table(core_holdings: list, from_ai: bool) -> None:
    if not core_holdings:
        return
    label = "🤖 Cartera núcleo (Grok)" if from_ai else "🧠 Cartera núcleo (determinístico)"
    st.markdown(f"**{label}** — {len(core_holdings)} posiciones para gestión activa")
    df = pd.DataFrame([
        {
            "Ticker": c.get("symbol", ""),
            "Peso %": round(float(c.get("suggested_weight_pct", 0)), 1),
            "Justificación": (c.get("why", "") or "")[:140],
        }
        for c in core_holdings
    ])
    st.dataframe(
        df, width="stretch", hide_index=True,
        column_config={"Peso %": st.column_config.NumberColumn("Peso %", format="%.1f%%")},
    )


# ------------------------------------------------------------------ #
#  Plan actual (sesión)                                               #
# ------------------------------------------------------------------ #

st.divider()
st.subheader("📍 Plan actual (esta sesión)")

if not (opt_result and getattr(opt_result, "tickers", [])):
    # Guided empty state (Fase E): show the journey instead of a dead end.
    from dashboard.shared import plan_journey_status

    st.warning(
        "Todavía no hay una cartera optimizada en esta sesión — tu plan se arma a partir "
        "de una optimización. Seguí estos pasos:",
        icon="🗺️",
    )
    _steps = plan_journey_status(prefs)
    _next_step = next((s for s in _steps if not s["done"]), None)
    for _i, _s in enumerate(_steps, start=1):
        _mark = "✅" if _s["done"] else ("👉" if _s is _next_step else "⬜")
        st.markdown(f"{_mark} **{_i}. {_s['label']}** — {_s['hint']}")

    _ec1, _ec2 = st.columns(2)
    if _ec1.button("📈 Ir al Optimizer", type="primary", width="stretch", key="plan_empty_opt"):
        st.switch_page(str(Path(__file__).parent / "5_Optimizer.py"))
    if _ec2.button("🎲 Ir a Simulaciones (metas + MC)", width="stretch", key="plan_empty_sim"):
        st.switch_page(str(Path(__file__).parent / "7_Simulaciones.py"))
    if prefs.is_onboarded:
        st.caption(
            "✨ El Optimizer ya abre con tu capital y perfil de riesgo pre-cargados desde tu "
            "perfil personal — solo elegí universo y ejecutá."
        )

    # Fase H.4 — demo mode: let a brand-new user load a ready-made example plan
    # to explore the living-plan features (salud, decumulación, sensibilidad)
    # without running an optimization first.
    from dashboard.shared import load_sample_plan_into_store
    from data.plan_context import list_sample_plans

    _samples = list_sample_plans()
    if _samples:
        with st.container(border=True):
            st.markdown("##### 🎁 ¿Querés probar con un plan de ejemplo?")
            st.caption(
                "Cargá un plan armado para explorar todo el flujo (guardar, activar, salud, "
                "estrategia de retiro, sensibilidad) sin optimizar primero. Después podés borrarlo."
            )
            _opts = {s["key"]: s for s in _samples}
            _choice = st.selectbox(
                "Plan de ejemplo",
                options=list(_opts.keys()),
                format_func=lambda k: f"{_opts[k]['name']} · {_opts[k]['profile_name']} ({_opts[k]['n_positions']} pos.)",
                key="sample_plan_choice",
            )
            st.caption(_opts[_choice]["description"])
            _b1, _b2 = st.columns(2)
            if _b1.button("📥 Cargar ejemplo", type="primary", width="stretch", key="load_sample_btn"):
                try:
                    _snap = load_sample_plan_into_store(_choice)
                    st.toast(f"✅ Ejemplo cargado: {_snap.name}", icon="🎁")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo cargar el ejemplo: {exc}")
            if _b2.button("📥➕ Cargar y activar", width="stretch", key="load_activate_sample_btn"):
                try:
                    _snap = load_sample_plan_into_store(_choice)
                    activate_plan(_snap.id, prefs)
                    st.toast(f"✅ Ejemplo cargado y activado: {_snap.name}", icon="🎯")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo cargar el ejemplo: {exc}")
else:
    _live_metrics = {
        "expected_return_pct":       getattr(opt_result, "expected_return_pct", 0.0),
        "volatility_pct":            getattr(opt_result, "volatility_pct", 0.0),
        "sharpe_ratio":              getattr(opt_result, "sharpe_ratio", 0.0),
        "dividend_yield_pct":        getattr(opt_result, "dividend_yield_pct", 0.0),
        "adjusted_score_avg":        getattr(opt_result, "adjusted_score_avg", 0.0),
        "max_drawdown_estimate_pct": getattr(opt_result, "max_drawdown_estimate_pct", 0.0),
    }
    st.caption(
        f"Universo **{_active_name}** · perfil **{getattr(opt_result, 'profile_name', '—')}** · "
        f"{len(opt_result.tickers)} posiciones"
    )
    _metrics_row(_live_metrics)

    _grok_core = getattr(opt_result, "grok_core_holdings", []) or []
    _det_core  = getattr(opt_result, "profile_core_holdings", []) or []
    _core_table(_grok_core or _det_core, bool(_grok_core))

    # Narrative
    _live_narrative = getattr(opt_result, "ai_grok_narrative", "") or st.session_state.get("last_plan_narrative", "")
    if _live_narrative:
        with st.expander("📝 Narrativa del plan", expanded=False):
            render_ai_badge("interpretación del modelo; las métricas del plan son cálculos")
            st.markdown(_live_narrative)

    # Goals + MC summary
    _gc1, _gc2 = st.columns(2)
    with _gc1:
        if goals_list:
            st.markdown(f"**🎯 Metas ({len(goals_list)})**")
            for g in goals_list:
                st.caption(
                    f"• {g.get('name', 'meta')} — \\${g.get('target_amount_today', 0):,.0f} hoy "
                    f"· {g.get('horizon_years', 0)} años"
                )
        else:
            st.caption("🎯 Sin metas definidas (agregalas en 🎲 Simulaciones → Mis Metas).")
    with _gc2:
        if mc_result is not None:
            st.markdown("**🎲 Proyección Monte Carlo**")
            st.caption(
                f"Mediana \\${getattr(mc_result, 'median_terminal', 0):,.0f} · "
                f"P10 \\${getattr(mc_result, 'p10_terminal', 0):,.0f} · "
                f"P90 \\${getattr(mc_result, 'p90_terminal', 0):,.0f}"
            )
            if getattr(mc_result, "realistic_reference_applied", False):
                st.caption(
                    f"📊 Conservador (piso prudente) vs realista: mediana realista "
                    f"\\${getattr(mc_result, 'realistic_median_terminal', 0):,.0f}."
                )
        else:
            st.caption("🎲 Sin simulación Monte Carlo en esta sesión (corré una en 🎲 Simulaciones).")

    # -------------------------------------------------------------- #
    #  Guardar plan                                                   #
    # -------------------------------------------------------------- #
    st.markdown("")
    with st.container(border=True):
        st.markdown("##### 💾 Guardar este plan")
        _default_name = f"Plan {getattr(opt_result, 'profile_name', '')} {datetime.now().strftime('%Y-%m')}".strip()
        _sc1, _sc2 = st.columns([3, 1])
        plan_name = _sc1.text_input(
            "Nombre del plan", value=st.session_state.get("plan_save_name", _default_name),
            key="plan_save_name",
            help="Guardar con un nombre existente actualiza ese plan.",
        )
        _existing = plan_store.get(_slugify(plan_name))
        with _sc2:
            st.markdown("&nbsp;")
            if st.button("💾 Guardar", type="primary", width="stretch", key="plan_save_btn"):
                snap = PlanSnapshot.from_session(
                    name=plan_name,
                    opt_result=opt_result,
                    goals=goals_list,
                    mc_result=mc_result,
                    mc_params=_session_mc_params(),
                    prefs=prefs,
                    universe_key=_active_key,
                    universe_name=_active_name,
                    narrative=_live_narrative,
                    existing_id=_existing.id if _existing else None,
                    existing_created_at=_existing.created_at if _existing else None,
                    price_lookup=plan_price_lookup,
                    drags=get_economic_drags(),   # Item 1: persist active assumptions
                    withdrawal_strategy=get_withdrawal_strategy(   # Fase H.1
                        float(getattr(prefs, "current_capital", 0)) or 100_000.0
                    ),
                )
                plan_store.upsert(snap)
                st.toast(f"✅ Plan guardado: {snap.name}", icon="🗺️")
                st.rerun()
        if _existing:
            st.caption(f"⚠️ Ya existe un plan **{_existing.name}** — guardar lo **actualiza**.")

    # -------------------------------------------------------------- #
    #  Acciones: lista de compra + PDF                               #
    # -------------------------------------------------------------- #
    _ac1, _ac2 = st.columns(2)

    with _ac1:
        with st.expander("🧺 Lista de compra del núcleo", expanded=False):
            _core = _grok_core or _det_core
            if not _core:
                st.caption("No hay núcleo disponible para este plan.")
            else:
                _cap_default = int(getattr(prefs, "current_capital", 0)) or int(
                    st.session_state.get("optimizer_total_capital", 0)
                ) or 100_000
                buy_capital = st.number_input(
                    "Capital a invertir (USD)", min_value=0, value=_cap_default, step=1_000,
                    format="%d", key="plan_buy_capital",
                )
                _total_w = sum(float(c.get("suggested_weight_pct", 0)) for c in _core) or 1.0
                buy_rows = [
                    {
                        "Ticker": c.get("symbol", ""),
                        "Peso %": round(float(c.get("suggested_weight_pct", 0)) / _total_w * 100, 1),
                        "USD a invertir": round(float(c.get("suggested_weight_pct", 0)) / _total_w * buy_capital),
                    }
                    for c in _core
                ]
                _buy_df = pd.DataFrame(buy_rows)
                st.dataframe(
                    _buy_df, width="stretch", hide_index=True,
                    column_config={
                        "Peso %": st.column_config.NumberColumn("Peso %", format="%.1f%%"),
                        "USD a invertir": st.column_config.NumberColumn("USD a invertir", format="$%d"),
                    },
                )
                _buy_csv = io.StringIO()
                _buy_df.to_csv(_buy_csv, index=False)
                st.download_button(
                    "⬇️ Exportar lista de compra (CSV)", _buy_csv.getvalue(),
                    file_name="lista_compra_nucleo.csv", mime="text/csv",
                    key="plan_buy_csv",
                )
                st.caption(
                    "Repartición proporcional al peso del núcleo. Orientativo — "
                    "no constituye asesoramiento financiero ni una orden de compra."
                )

    with _ac2:
        with st.expander("📄 Generar PDF del plan", expanded=False):
            _pdf_ai = st.checkbox("Incluir narrativa IA", value=bool(_live_narrative), key="plan_pdf_ai")
            if st.button("📄 Generar PDF", type="primary", key="plan_pdf_btn"):
                with st.spinner("Generando reporte…"):
                    try:
                        from reports.investment_plan import InvestmentPlanReport, ReportOptions
                        _opts = ReportOptions(
                            user_name=getattr(prefs, "user_name", "") if hasattr(prefs, "user_name") else "",
                            version="completo",
                            include_ai_narrative=_pdf_ai,
                            include_charts=True,
                            include_risk_section=mc_result is not None,
                            include_recommendations=True,
                        )
                        _pdf_bytes = InvestmentPlanReport().generate(
                            goal_plan=None,
                            opt_result=opt_result,
                            mc_result=mc_result,
                            mc_params=_session_mc_params(),
                            ai_config=_get_ai_config() if _pdf_ai else None,
                            options=_opts,
                        )
                        st.session_state["plan_pdf_bytes"] = _pdf_bytes
                    except Exception as exc:
                        st.error(f"Error generando el PDF: {exc}")
            if "plan_pdf_bytes" in st.session_state:
                st.download_button(
                    "⬇️ Descargar PDF", st.session_state["plan_pdf_bytes"],
                    file_name=f"mi_plan_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf", key="plan_pdf_dl",
                )


# ------------------------------------------------------------------ #
#  Read-only snapshot renderer                                        #
# ------------------------------------------------------------------ #

def _render_env_provenance(snap: PlanSnapshot) -> None:
    """Show which numeric libraries produced this plan, and whether they moved.

    Audit D5: scipy/numpy/pandas bumps can shift SLSQP optima and percentiles,
    so a saved plan is only reproducible if we know — and can check — the build
    that computed it.
    """
    if not getattr(snap, "has_sealed_env", None) or not snap.has_sealed_env():
        st.caption(
            "🔎 Este plan no registró las versiones de las librerías numéricas "
            "(se guardó antes del sellado). No se puede verificar si sus números "
            "se reproducen en el entorno actual."
        )
        return

    drift = snap.numeric_env_drift()
    sealed = ", ".join(f"{k} {v}" for k, v in sorted(snap.lib_versions.items()))
    if drift:
        st.caption(
            f"🔎 Calculado con: {sealed}. **Cambió desde entonces: "
            f"{format_drift(drift)}** — los números pueden no reproducirse exactamente."
        )
    else:
        st.caption(f"🔎 Calculado con: {sealed} — entorno numérico sin cambios.")


def _render_engine_staleness(snap: PlanSnapshot) -> None:
    """Warn when a saved plan's numbers predate the 2026-08 Tier 0 engine fix."""
    _render_env_provenance(snap)
    if not getattr(snap, "is_engine_stale", None) or not snap.is_engine_stale():
        return

    st.warning(
        "⚠️ **Este plan se calculó con el motor anterior a la corrección de agosto 2026.** "
        "Las cifras de retiro (cuánto dura el ingreso, herencia, probabilidad de ruina) "
        "sobrestimaban el capital final: los retiros descontaban un monto fijo en vez de "
        "capital, así que el dinero retirado seguía creciendo. Volvé a simular para ver "
        "los números corregidos."
    )
    if st.button("🔄 Recalcular con el motor corregido", key=f"recalc_{snap.id}"):
        st.session_state["_plan_recalc_target"] = snap.id
        st.session_state["mc_initial_capital"] = float(
            (snap.personal or {}).get("current_capital", 0) or 0
        ) or st.session_state.get("mc_initial_capital", 0)
        st.switch_page("pages/7_Simulaciones.py")


def _render_snapshot(snap: PlanSnapshot) -> None:
    st.caption(
        f"Universo **{snap.universe_name or snap.universe_key or '—'}** · "
        f"perfil **{snap.profile_name or '—'}** · {snap.n_positions} posiciones · "
        f"guardado {snap.updated_at[:16].replace('T', ' ')}"
    )
    _render_engine_staleness(snap)
    _metrics_row(snap.metrics)
    _core_table(snap.core_holdings, snap.core_from_ai)

    if snap.allocation:
        with st.expander(f"🧺 Cartera completa ({len(snap.allocation)} posiciones)"):
            _df = pd.DataFrame(snap.allocation).sort_values("weight_pct", ascending=False)
            st.dataframe(
                _df, width="stretch", hide_index=True,
                column_config={
                    "weight_pct": st.column_config.ProgressColumn("Peso %", min_value=0, max_value=100, format="%.1f%%"),
                    "dividend_yield_pct": st.column_config.NumberColumn("Div %", format="%.2f%%"),
                    "adjusted_score": st.column_config.NumberColumn("Score", format="%.0f"),
                },
            )

    if snap.goals:
        st.markdown(f"**🎯 Metas ({len(snap.goals)})**")
        for g in snap.goals:
            st.caption(f"• {g.get('name', 'meta')} — \\${g.get('target_amount_today', 0):,.0f} hoy · {g.get('horizon_years', 0)} años")

    if snap.mc_summary:
        m = snap.mc_summary
        st.markdown("**🎲 Monte Carlo**")
        st.caption(
            f"Horizonte {m.get('horizon_years', '—')}a · Mediana \\${m.get('median_terminal', 0):,.0f} · "
            f"P10 \\${m.get('p10_terminal', 0):,.0f} · P90 \\${m.get('p90_terminal', 0):,.0f}"
            + (f" · Prob. meta {m.get('prob_target_pct', 0):.0f}%" if m.get("target_value") else "")
        )
        # Item 1 — show the assumptions this plan was generated under.
        _drag_total = float(m.get("total_annual_drag_pct", 0.0) or 0.0)
        if _drag_total > 0:
            st.caption(
                f"📊 Generado con drags **{_drag_total:.2f}%/año** · "
                f"base sin drags: mediana \\${m.get('base_median_terminal', 0):,.0f} · "
                f"P10 \\${m.get('base_p10_terminal', 0):,.0f}"
            )
        else:
            st.caption("📊 Generado **sin drags** (caso base: 0% fees/impuestos/fricciones).")

        # Fase H.1 — decumulation strategy + retirement-income outcomes.
        _wd = getattr(snap, "withdrawal_strategy", None)
        if _wd:
            st.markdown("**🏖️ Estrategia de retiro**")
            st.caption(format_withdrawal_badge(_wd))
            if m.get("prob_sustain_real_pct") is not None and "prob_sustain_real_pct" in m:
                _ly = m.get("longevity_years", m.get("horizon_years", "—"))
                _dep = m.get("expected_depletion_year", 0) or 0
                _dep_txt = f"se agota típicamente en año {_dep:.0f}" if _dep > 0 else "no se agota en el horizonte"
                st.caption(
                    f"Prob. de que el ingreso dure {_ly} años: **{m.get('prob_sustain_real_pct', 0):.0f}%** · "
                    f"herencia mediana \\${m.get('median_legacy', 0):,.0f} · {_dep_txt}."
                )

    _render_structural_tailwinds(snap)
    _render_plan_ai(snap)
    _render_plan_health(snap)
    _render_plan_health_history(snap)
    _render_alignment_trades(snap)
    _render_load_plan(snap)


# ------------------------------------------------------------------ #
#  Trades sugeridos para alinear (Fase E)                              #
# ------------------------------------------------------------------ #

def _render_alignment_trades(snap: PlanSnapshot) -> None:
    """Suggested buy/sell list to move the real tracker toward this plan.

    Only rendered for the *active* plan (it is the drift target) and when
    the tracker has positions. The price fetch runs behind an explicit
    button, mirroring the "Refrescar" pattern of plan health.
    """
    if snap.id != (getattr(prefs, "active_plan_id", "") or "").strip():
        return
    _portfolio = st.session_state.get("portfolio")
    if _portfolio is None:
        from portfolio.tracker import Portfolio
        _portfolio = Portfolio()
        st.session_state.portfolio = _portfolio
    if not _portfolio.positions:
        st.caption(
            "🛒 Sin posiciones en 💼 Portfolio — cargá tus tenencias reales para ver "
            "los trades sugeridos que te acercan a este plan."
        )
        return

    st.markdown("**🛒 Acciones sugeridas para alinear tu portfolio**")
    _trades_key = f"plan_trades_{snap.id}"
    if st.button("🧮 Calcular trades sugeridos", key=f"trades_{snap.id}",
                 help="Compara tus posiciones reales con los pesos objetivo del plan"):
        with st.spinner("Comparando posiciones reales vs plan…"):
            _actual = _portfolio.get_position_weights()
            _total = sum(v["market_value"] for v in _portfolio.get_current_values().values())
            st.session_state[_trades_key] = compute_alignment_trades(
                snap, _actual, _total, price_lookup=plan_price_lookup,
            )

    _align = st.session_state.get(_trades_key)
    if not _align:
        return
    _trades, _as = _align["trades"], _align["summary"]
    if not _trades:
        st.success(
            f"Estás alineado: ningún desvío supera {_as['threshold_pct']:.0f}% "
            f"(deriva total {_as['total_drift_pct']:.1f}%).",
            icon="✅",
        )
        return
    _tdf = pd.DataFrame([
        {
            "Acción": ("🟢 Comprar" if t["action"] == "comprar" else "🔴 Vender"),
            "Ticker": t["symbol"] + (" ⭐" if t["is_core"] else ""),
            "Objetivo %": t["target_pct"],
            "Actual %": t["actual_pct"],
            "Drift %": t["drift_pct"],
            "Monto (USD)": t["amount_usd"],
            "≈ Shares": t["est_shares"],
        }
        for t in _trades
    ])
    st.dataframe(
        _tdf, width="stretch", hide_index=True,
        column_config={
            "Objetivo %": st.column_config.NumberColumn("Objetivo %", format="%.1f%%"),
            "Actual %": st.column_config.NumberColumn("Actual %", format="%.1f%%"),
            "Drift %": st.column_config.NumberColumn("Drift %", format="%.1f%%"),
            "Monto (USD)": st.column_config.NumberColumn("Monto (USD)", format="$%d"),
        },
    )
    st.caption(
        f"⭐ = núcleo del plan (priorizado) · comprar \\${_as['buy_usd']:,.0f} · "
        f"vender \\${_as['sell_usd']:,.0f} · deriva total {_as['total_drift_pct']:.1f}%. "
        "**Orientativo — no es asesoramiento financiero ni una orden.** "
        "También disponible en 💼 Portfolio → Alineación con tu Plan."
    )


# ------------------------------------------------------------------ #
#  Salud del plan vs mercado actual (Fase C)                          #
# ------------------------------------------------------------------ #

def _render_plan_health(snap: PlanSnapshot) -> None:
    """Show price deltas (today vs save time) + a refresh button for a plan."""
    st.markdown("**📈 Salud vs mercado actual**")
    _has_baseline = any(a.get("price_at_save") for a in snap.allocation)
    if not _has_baseline:
        st.caption(
            "Este plan se guardó sin precios de referencia. Volvé a guardarlo "
            "(arriba) para capturar los precios de hoy y habilitar el delta de mercado."
        )

    _health_key = f"plan_health_{snap.id}"
    if st.button("🔄 Refrescar con datos de hoy", key=f"refresh_{snap.id}"):
        with st.spinner("Consultando precios actuales…"):
            st.session_state[_health_key] = compute_plan_health(snap)

    health = st.session_state.get(_health_key)
    if not health:
        st.caption("Tocá «Refrescar» para traer los precios de hoy y ver cómo se movió tu plan.")
        return

    s = health["summary"]
    _hc = st.columns(3)
    _wd = s.get("weighted_delta_pct")
    _hc[0].metric(
        "Δ ponderado del plan",
        f"{_wd:+.1f}%" if _wd is not None else "—",
        help="Cambio de precio promedio (ponderado por peso) desde que guardaste el plan.",
    )
    _hc[1].metric("Subieron / Bajaron", f"{s.get('gainers', 0)} / {s.get('losers', 0)}")
    _hc[2].metric(
        "Score prom. (al guardar)",
        f"{s.get('avg_score_then'):.0f}/100" if s.get("avg_score_then") is not None else "—",
    )

    _rows = [
        {
            "Ticker": r["symbol"],
            "Peso %": r["weight_pct"],
            "Precio guardado": r["price_then"],
            "Precio hoy": r["price_now"],
            "Δ %": r["delta_pct"],
        }
        for r in health["rows"]
    ]
    st.dataframe(
        pd.DataFrame(_rows),
        width="stretch", hide_index=True,
        column_config={
            "Peso %": st.column_config.NumberColumn("Peso %", format="%.1f%%"),
            "Precio guardado": st.column_config.NumberColumn("Precio guardado", format="$%.2f"),
            "Precio hoy": st.column_config.NumberColumn("Precio hoy", format="$%.2f"),
            "Δ %": st.column_config.NumberColumn("Δ %", format="%.1f%%"),
        },
    )
    st.caption(
        f"Precios obtenidos para {s.get('n_priced', 0)}/{s.get('n_total', 0)} posiciones · "
        f"{s.get('n_with_baseline', 0)} con precio de referencia · "
        f"actualizado {health['refreshed_at'][11:16]}. "
        "Orientativo — no es asesoramiento financiero."
    )

    # Data-quality transparency (Fase E)
    _n_missing_price = int(s.get("n_total", 0)) - int(s.get("n_priced", 0))
    if _n_missing_price > 0:
        _missing_syms = [r["symbol"] for r in health["rows"] if r.get("price_now") is None]
        st.warning(
            f"🧪 **Calidad de datos:** {_n_missing_price} posición(es) sin precio hoy "
            f"({', '.join(_missing_syms[:8])}{'…' if len(_missing_syms) > 8 else ''}). "
            "El Δ ponderado y los trades sugeridos pueden estar incompletos — "
            "yfinance no devolvió datos para esos tickers.",
            icon="🧪",
        )


def _render_plan_health_history(snap: PlanSnapshot) -> None:
    """Longitudinal health timeline for a plan (Fase H.2).

    Lets the user record point-in-time health snapshots and see the trend
    (weighted drift since save + data quality) over months, plus a structural
    degradation warning when the plan has been drifting persistently.
    """
    st.markdown("**📊 Evolución de tu plan**")
    st.caption(
        "Registrá la salud de tu plan cada cierto tiempo para ver si se mantiene "
        "alineado o si derivó silenciosamente. Cada registro es liviano (deriva "
        "ponderada, score al guardar, P50 Monte Carlo, calidad de datos)."
    )

    if st.button("📍 Registrar salud ahora", key=f"record_health_{snap.id}"):
        with st.spinner("Calculando y guardando la salud del plan…"):
            # Reuse the just-refreshed market data if available (no extra fetch).
            _refreshed = st.session_state.get(f"plan_health_{snap.id}")
            rec = record_plan_health_now(snap, refreshed=_refreshed)
        if rec is not None:
            st.toast("✅ Salud registrada", icon="📊")
        else:
            st.toast("Ya habías registrado la salud hoy.", icon="ℹ️")
        st.rerun()

    history, drift = plan_health_history(snap.id)
    if not history:
        st.caption("Todavía no hay registros. Tocá «Registrar salud ahora» para empezar la línea de tiempo.")
        return

    # Trend summary KPIs.
    _c = st.columns(3)
    _c[0].metric("Registros", drift["n_records"])
    _latest = drift.get("latest_drift_pct")
    _c[1].metric(
        "Deriva actual del plan",
        f"{_latest:+.1f}%" if _latest is not None else "—",
        help="Movimiento ponderado de precios desde que guardaste el plan, en el último registro.",
    )
    _dq = drift.get("latest_data_quality_pct")
    _c[2].metric("Calidad de datos", f"{_dq:.0f}%" if _dq is not None else "—")

    # Trend chart: weighted drift over time (+ data quality).
    _chart_rows = [
        {
            "Fecha": r["recorded_at"][:10],
            "Deriva % vs guardado": r.get("weighted_delta_pct"),
            "Calidad datos %": r.get("data_quality_pct"),
        }
        for r in history
    ]
    _df = pd.DataFrame(_chart_rows).set_index("Fecha")
    st.line_chart(_df, height=220)

    if drift.get("degraded"):
        st.warning(
            f"📉 **Plan envejecido:** {drift.get('degraded_reason', '')} "
            "Considerá rebalancear hacia el objetivo, regenerar la narrativa o revisar si el plan "
            "sigue reflejando tu situación.",
            icon="📉",
        )
    else:
        st.caption(
            f"Tendencia entre {drift['first_recorded_at'][:10]} y {drift['last_recorded_at'][:10]}: "
            f"deriva en rango [{drift.get('min_drift_pct')}, {drift.get('max_drift_pct')}]%. "
            "Sin degradación estructural sostenida por ahora."
        )

    with st.expander("📋 Ver registros", expanded=False):
        _rows = [
            {
                "Fecha": r["recorded_at"][:16].replace("T", " "),
                "Deriva %": r.get("weighted_delta_pct"),
                "Score guardado": r.get("avg_score_then"),
                "P50 MC": r.get("mc_p50"),
                "Núcleo": r.get("n_core"),
                "Calidad %": r.get("data_quality_pct"),
                "Origen": r.get("source"),
            }
            for r in reversed(history)
        ]
        st.dataframe(
            pd.DataFrame(_rows), width="stretch", hide_index=True,
            column_config={
                "Deriva %": st.column_config.NumberColumn("Deriva %", format="%.1f%%"),
                "P50 MC": st.column_config.NumberColumn("P50 MC", format="$%.0f"),
                "Calidad %": st.column_config.NumberColumn("Calidad %", format="%.0f%%"),
            },
        )


# ------------------------------------------------------------------ #
#  Colas de viento estructurales sector-país del plan (Idea 2)         #
# ------------------------------------------------------------------ #

_TAILWIND_PLAN_BADGE = {
    "Strong":   ("#00C851", "🌬️", "Cola de viento fuerte"),
    "Moderate": ("#39b54a", "🍃", "Cola de viento moderada"),
    "Headwind": ("#ff4444", "🌪️", "Viento de frente"),
}


def _render_structural_tailwinds(snap: PlanSnapshot) -> None:
    """Surface the curated sector-country tailwinds captured in the snapshot."""
    _tw = [
        a for a in (snap.allocation or [])
        if (a.get("tailwind_classification") or "") not in ("", "Neutral")
    ]
    if not _tw:
        return
    st.markdown("**🌬️ Factores estructurales de sector-país en este plan**")
    for a in sorted(_tw, key=lambda x: -float(x.get("weight_pct", 0.0) or 0.0)):
        cls = a.get("tailwind_classification", "")
        color, emoji, label = _TAILWIND_PLAN_BADGE.get(cls, ("#888888", "⚪", cls))
        st.markdown(
            f'<div style="border-left:4px solid {color};padding:4px 10px;margin:4px 0;">'
            f'{emoji} <b>{a.get("symbol", "?")}</b> ({float(a.get("weight_pct", 0.0) or 0.0):.1f}%) '
            f'<span style="color:{color};font-size:0.85em;">· {label} '
            f'(score {float(a.get("tailwind_score", 0.0) or 0.0):+.1f})</span></div>',
            unsafe_allow_html=True,
        )
    st.caption(
        "Outlook estructural curado al momento de guardar el plan (ya incluido en los scores) — "
        "no es garantía de retornos."
    )


# ------------------------------------------------------------------ #
#  Narrativa IA + factores macro del plan (Fase D)                    #
# ------------------------------------------------------------------ #

def _render_macro_risks(macro_risks: list) -> None:
    if not macro_risks:
        return
    st.markdown("**🌍 Factores macro que más impactan tu plan**")
    for m in macro_risks:
        color, emoji = _SEVERITY_BADGE.get(str(m.get("severity", "media")).lower(), ("#ff8800", "🟠"))
        st.markdown(
            f'<div style="border-left:4px solid {color};padding:4px 10px;margin:4px 0;">'
            f'{emoji} <b>{m.get("factor", "")}</b> '
            f'<span style="color:{color};font-size:0.85em;">· {m.get("severity", "media")}</span><br>'
            f'<span style="font-size:0.9em;">{m.get("why", "")}</span></div>',
            unsafe_allow_html=True,
        )


def _render_plan_ai(snap: PlanSnapshot) -> None:
    """Show the saved narrative + macro risks and a regenerate-with-AI button."""
    if snap.narrative:
        with st.expander("📝 Narrativa del plan", expanded=False):
            render_ai_badge("interpretación del modelo; las métricas del plan son cálculos")
            st.markdown(snap.narrative)
    _render_macro_risks(getattr(snap, "macro_risks", []) or [])

    _ai_cfg = _get_ai_config()
    _label = "🧠 Regenerar narrativa IA" if snap.narrative else "🧠 Generar narrativa IA del plan"
    if st.button(_label, key=f"ai_narr_{snap.id}", help="Usa tu proveedor de IA configurado en Settings"):
        if not getattr(_ai_cfg, "enabled", False) or not getattr(_ai_cfg, "api_key", ""):
            st.info("Activá la IA en ⚙️ Settings (con una API key válida) para generar la narrativa del plan.")
        else:
            with st.spinner("Generando explicación y factores macro…"):
                try:
                    from analysis.ai_analyzer import AIAnalyzer
                    _refreshed = st.session_state.get(f"plan_health_{snap.id}")
                    _result = AIAnalyzer(_ai_cfg).generate_plan_narrative(snap, refreshed=_refreshed)
                    snap.narrative = _result.get("narrative", "") or snap.narrative
                    snap.macro_risks = _result.get("macro_risks", []) or []
                    snap.last_refreshed_at = datetime.now().isoformat(timespec="seconds")
                    plan_store.upsert(snap)
                    st.toast("🧠 Narrativa del plan actualizada", icon="✅")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo generar la narrativa: {exc}")


# ------------------------------------------------------------------ #
#  Cargar plan en Optimizer / Simulaciones (Fase D)                   #
# ------------------------------------------------------------------ #

def _render_load_plan(snap: PlanSnapshot) -> None:
    """Seed session_state from a saved plan so the user can do what-if iterations."""
    if st.button("📥 Cargar plan en Optimizer / Simulaciones", key=f"load_{snap.id}",
                 help="Usa el perfil, capital, horizonte y metas de este plan como punto de partida"):
        _mc = snap.mc_summary or {}
        _personal = snap.personal or {}
        _capital = int(
            float(_personal.get("current_capital", 0) or 0)
            or float(_mc.get("initial_value", 0) or 0)
            or 100_000
        )
        _horizon = _snap_sim_horizon(
            int(_mc.get("horizon_years", 0) or _personal.get("primary_horizon_years", 0) or 0)
        )

        # Optimizer: profile + capital (profile consumed via the preset hook on its page)
        _pkey = snap.profile_key or _PROFILE_NAME_TO_KEY.get(snap.profile_name, "")
        if _pkey:
            st.session_state["_preset_profile_key"] = _pkey
        st.session_state["optimizer_total_capital"] = _capital

        # Simulaciones: horizon + capital + target + inflation + goals
        st.session_state["horizon_years"] = _horizon
        st.session_state["initial_value"] = min(max(_capital, 1_000), 10_000_000)
        st.session_state["target_value"] = int(float(_mc.get("target_value", 0) or 0))
        if _mc.get("inflation_rate") is not None:
            st.session_state["inflation_rate"] = float(_mc.get("inflation_rate"))
        if snap.goals:
            st.session_state["goals_list"] = list(snap.goals)

        st.toast(f"📥 Plan «{snap.name}» cargado — andá a 📈 Optimizer o 🎲 Simulaciones y ejecutá.", icon="✅")


# ------------------------------------------------------------------ #
#  Planes guardados                                                   #
# ------------------------------------------------------------------ #

st.divider()
st.subheader("📚 Planes guardados")

# ------------------------------------------------------------------ #
#  Importar / Restaurar desde backup (Item 2)                         #
# ------------------------------------------------------------------ #
with st.expander("📦 Importar / Restaurar plan desde backup", expanded=False):
    st.caption(
        "Subí un archivo de plan exportado (JSON) para restaurarlo en esta máquina. "
        "Útil tras una reinstalación, para mover tu plan a otra computadora o para "
        "recibir el plan de tu asesor/pareja."
    )
    _up = st.file_uploader("Archivo de plan (.json)", type=["json"], key="plan_import_file")
    if _up is not None:
        import json as _json

        from data.plan_context import import_plan_from_dict
        try:
            _data = _json.loads(_up.getvalue().decode("utf-8"))
            _imported = import_plan_from_dict(_data)
        except Exception as _exc:  # noqa: BLE001
            st.error(f"No se pudo leer el plan: {_exc}")
        else:
            st.success(f"Plan válido: **{_imported.name}** · {_imported.n_positions} posiciones.")
            _ic1, _ic2 = st.columns(2)
            with _ic1:
                if st.button("📥 Importar plan", type="primary", key="plan_import_btn"):
                    plan_store.upsert(_imported)
                    st.toast(f"✅ Plan importado: {_imported.name}", icon="📦")
                    st.rerun()
            with _ic2:
                if st.button("📥 Importar y activar", key="plan_import_activate_btn"):
                    plan_store.upsert(_imported)
                    activate_plan(_imported.id, prefs)
                    st.toast(f"🎯 Plan importado y activado: {_imported.name}", icon="📦")
                    st.rerun()

_plans = plan_store.list()

if not _plans:
    st.caption("Todavía no guardaste ningún plan. Generá una cartera en el Optimizer y guardala arriba.")
else:
    # Compare
    if len(_plans) >= 2:
        with st.expander("⚖️ Comparar planes (supuestos + resultados)", expanded=False):
            from data.product_ux import deep_compare_plans

            _by_id = {p.id: p for p in _plans}
            _sel = st.multiselect(
                "Elegí 2 planes para comparar",
                options=[p.id for p in _plans],
                format_func=lambda pid: _by_id[pid].name,
                max_selections=2,
                key="plan_compare_sel",
            )
            if len(_sel) == 2:
                a, b = _by_id[_sel[0]], _by_id[_sel[1]]
                _cmp = deep_compare_plans(a, b)
                st.caption(
                    f"📊 Calculado · {_cmp['n_differences']} diferencia(s) entre "
                    f"**{_cmp['name_a']}** y **{_cmp['name_b']}**"
                )
                if _cmp.get("highlights"):
                    st.markdown("**Diferencias clave:**")
                    for _h in _cmp["highlights"][:8]:
                        st.markdown(f"- {_h}")
                _df_rows = []
                for _r in _cmp["rows"]:
                    _df_rows.append({
                        "Campo": _r["label"],
                        _cmp["name_a"]: _r["a"],
                        _cmp["name_b"]: _r["b"],
                        "Δ": _r["delta"] if _r["delta"] is not None else ("≠" if _r["differs"] else "—"),
                    })
                st.dataframe(pd.DataFrame(_df_rows), width="stretch", hide_index=True)

    _active_plan_id = (getattr(prefs, "active_plan_id", "") or "").strip()
    if _active_plan_id and any(p.id == _active_plan_id for p in _plans):
        _active_name = next(p.name for p in _plans if p.id == _active_plan_id)
        st.success(
            f"🎯 Plan activo: **{_active_name}** — el tracker y las alertas de drift "
            "lo usan como tu objetivo de retiro.",
            icon="🎯",
        )
        # Backlog 8 — qué hacer este año
        from data.product_ux import ar_dual_context, build_annual_action_list

        _active_snap = next(p for p in _plans if p.id == _active_plan_id)
        _port = st.session_state.get("portfolio")
        _has_pos = bool(getattr(_port, "positions", None))
        _drift = None
        _rm = getattr(_active_snap, "refreshed_metrics", None) or {}
        if isinstance(_rm, dict):
            _drift = (_rm.get("summary") or {}).get("weighted_delta_pct")
        _actions = build_annual_action_list(
            plan_snapshot=_active_snap,
            monthly_savings=float(getattr(prefs, "monthly_savings", 0) or 0),
            has_portfolio_positions=_has_pos,
            drift_pct=float(_drift) if _drift is not None else None,
            last_backup_days=None if not st.session_state.get("plan_exported") else 0,
        )
        with st.container(border=True):
            st.markdown("#### ✅ Qué hacer este año")
            st.caption("📊 Calculado · checklist a partir de tu plan y perfil (no es IA).")
            for _a in _actions:
                st.markdown(
                    f"- **{_a['title']}** · _{_a.get('when', '')}_  \n"
                    f"  {_a.get('detail', '')}"
                )

        # Backlog 10 — AR dual on plan capital/median.
        #
        # Audit U2-5: `median_terminal` is USD nominal at the plan's horizon, so
        # it needs the plan's own inflation assumption before it can be spoken
        # about in pesos. Snapshots saved without one (or without a horizon)
        # cannot be converted honestly and say so instead.
        _mc = getattr(_active_snap, "mc_summary", None) or {}
        _med = _mc.get("median_terminal")
        if _med:
            try:
                _fx_plan = ar_dual_context(
                    float(_med),
                    fx_config=AR_FX,
                    label="mediana del plan",
                    # None, not 0: a plan saved without a horizon has an
                    # *unknown* basis, and reading that as "today's money"
                    # would convert the nominal terminal at spot all over again.
                    horizon_years=(
                        float(_mc["horizon_years"])
                        if _mc.get("horizon_years") not in (None, "")
                        else None
                    ),
                    usd_inflation_pct=(
                        float(_mc["inflation_rate"])
                        if _mc.get("inflation_rate") not in (None, "")
                        else None
                    ),
                )
                with st.expander("🇦🇷 Equivalente en pesos de hoy (supuesto, no cotización)", expanded=False):
                    if _fx_plan["available"]:
                        st.markdown(escape_dollars(_fx_plan["line"]))
                    else:
                        st.info(_fx_plan["reason"], icon="ℹ️")
                    st.caption(
                        f"Tasas de config/env — origen: **{AR_FX.rate_source}**. "
                        "Contexto de producto, no cotización en vivo."
                    )
            except Exception as exc:  # the FX block only — logged, never swallowed (U2-5)
                logger.warning("AR dual-currency block failed to render: {}", exc)
                st.caption("⚠️ La vista en pesos no se pudo mostrar.")

    for p in _plans:
        _is_active = p.id == _active_plan_id
        with st.container(border=True):
            _c1, _c2, _c3, _c4 = st.columns([5, 2, 2, 2])
            with _c1:
                st.markdown(f"**🗺️ {p.name}**" + ("  🎯 _Activo_" if _is_active else ""))
                st.caption(
                    f"{p.profile_name or '—'} · {p.n_positions} pos · "
                    f"Atractivo {p.metrics.get('expected_return_pct', 0):.1f}% · "
                    f"Ratio {p.metrics.get('sharpe_ratio', 0):.2f} · "
                    f"{p.updated_at[:10]}"
                )
            with _c2:
                if _is_active:
                    if st.button("🎯 Desactivar", key=f"deact_{p.id}", width="stretch",
                                 help="Dejar de usar este plan como objetivo de retiro"):
                        deactivate_plan(prefs)
                        st.toast(f"Plan '{p.name}' desactivado", icon="🎯")
                        st.rerun()
                else:
                    if st.button("🎯 Activar", key=f"act_{p.id}", width="stretch", type="primary",
                                 help="Usar este plan como tu objetivo de retiro (drift + alertas)"):
                        activate_plan(p.id, prefs)
                        st.toast(f"🎯 Plan activo: {p.name}", icon="🎯")
                        st.rerun()
            with _c3:
                if st.button("👁️ Ver", key=f"view_{p.id}", width="stretch"):
                    st.session_state["plan_view_id"] = (
                        None if st.session_state.get("plan_view_id") == p.id else p.id
                    )
                    st.rerun()
            with _c4:
                if st.button("🗑️ Borrar", key=f"del_{p.id}", width="stretch"):
                    plan_store.delete(p.id)
                    if _is_active:
                        deactivate_plan(prefs)
                    if st.session_state.get("plan_view_id") == p.id:
                        st.session_state.pop("plan_view_id", None)
                    st.toast(f"Plan '{p.name}' borrado", icon="🗑️")
                    st.rerun()

            # Item 2 — export this plan (JSON bundle + restore instructions).
            with st.expander("📥 Exportar / Respaldar este plan", expanded=False):
                _json_bytes, _fname, _instr_md = export_plan_bundle(p, prefs)
                _ec1, _ec2 = st.columns(2)
                with _ec1:
                    if st.download_button(
                        "📥 Descargar plan (JSON)", data=_json_bytes, file_name=_fname,
                        mime="application/json", key=f"exp_json_{p.id}", width="stretch",
                    ):
                        st.session_state["plan_exported"] = True
                with _ec2:
                    st.download_button(
                        "📄 Instrucciones de restauración", data=_instr_md.encode("utf-8"),
                        file_name=f"{_fname.rsplit('.', 1)[0]}_LEEME.md",
                        mime="text/markdown", key=f"exp_md_{p.id}", width="stretch",
                    )
                st.caption(
                    "Guardá el JSON en tu nube/USB. Restaurá desde «📦 Importar / "
                    "Restaurar plan» arriba — sobrevive reinstalaciones y cambios de máquina."
                )

            if st.session_state.get("plan_view_id") == p.id:
                st.divider()
                _render_snapshot(p)
