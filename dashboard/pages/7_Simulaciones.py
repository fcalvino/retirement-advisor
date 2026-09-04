"""Monte Carlo simulation and stress testing for the portfolio."""

from __future__ import annotations

import io
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from loguru import logger

from config import AR_FX, GOAL_CARD, MONTE_CARLO, SECTOR_MAP, WITHDRAWAL
from dashboard.shared import (
    _get_ai_config,
    cached_goal_optimization,
    cached_goal_savings_target,
    cached_goal_simulation,
    cached_monte_carlo,
    cached_stress_test,
    drags_to_tuple,
    escape_dollars,
    format_drags_badge,
    format_withdrawal_badge,
    get_economic_drags,
    get_longevity_years,
    get_user_prefs,
    get_withdrawal_strategy,
    render_drags_controls,
    render_withdrawal_controls,
    run_plan_sensitivity,
    seed_session_defaults_from_profile,
    withdrawal_to_tuple,
)
from data.product_ux import (
    PROXY_INDEX_LABEL,
    PROXY_RATIO_HELP,
    PROXY_RATIO_LABEL,
    PROXY_RETURN_HELP,
    ar_dual_context,
    contribution_inputs,
    fmt_attractiveness_index,
    indexation_help,
    mc_has_cash_flows,
    pot_growth_column_label,
    pot_growth_delta,
    pot_growth_help,
    pot_growth_pct,
    proxy_attractiveness_index,
)
from portfolio.goals import (
    GOAL_TYPE_ICONS,
    GOAL_TYPE_LABELS,
    GOAL_TYPE_PLACEHOLDERS,
    PRIORITY_COLORS,
    PRIORITY_EMOJIS,
    PRIORITY_LABELS,
    sorr_badge_tooltip,
    sorr_risk_badge,
)
from portfolio.sensitivity import tornado_rows

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("🎲 Simulaciones & Stress Testing")
st.caption(
    "Proyectá tu portafolio a largo plazo con simulación Monte Carlo y evaluá "
    "su resistencia ante crisis históricas. "
    "💵 Valores en USD. Esta simulación es orientativa, no una garantía de resultados."
)



def _fmt_idx_delta(a, b) -> str | None:
    """Delta entre dos índices de atractivo, en puntos de índice."""
    ia, ib = proxy_attractiveness_index(a), proxy_attractiveness_index(b)
    if ia is None or ib is None:
        return None
    return f"{ia - ib:+.0f} vs base"

# ------------------------------------------------------------------ #
#  Personal profile → smart defaults (onboarding — Fase A)            #
#  Seeds Monte Carlo horizon + initial capital, and pre-fills the     #
#  "Mis Metas" goal form, before any widget is instantiated.          #
# ------------------------------------------------------------------ #

_prefs_sim = get_user_prefs()
seed_session_defaults_from_profile(_prefs_sim)  # direct-nav safe
if _prefs_sim.is_onboarded and not st.session_state.get("_goal_form_seeded"):
    if _prefs_sim.primary_goal_type in GOAL_TYPE_ICONS:
        st.session_state.setdefault("new_goal_type", _prefs_sim.primary_goal_type)
    st.session_state.setdefault("new_goal_horizon", min(max(_prefs_sim.primary_horizon_years or 5, 1), 40))
    _seed_savings = contribution_inputs(prefs=_prefs_sim)["annual"]
    st.session_state.setdefault("new_goal_contribution", int(min(max(_seed_savings, 0), 500_000)))
    st.session_state.setdefault("new_goal_allocated", int(min(max(_prefs_sim.current_capital, 0), 10_000_000)))
    st.session_state["_goal_form_seeded"] = True
if _prefs_sim.is_onboarded:
    st.caption(
        f"📋 Defaults tomados de **Mi Perfil**: horizonte ~{_prefs_sim.primary_horizon_years} años "
        f"· capital \\${_prefs_sim.current_capital:,.0f}. Editá en ⚙️ Settings."
    )

# ------------------------------------------------------------------ #
#  Profile comparison scales (vol_scale, return_scale over global cfg) #
# Conservative = extra caution; Aggressive = higher return assumption  #
# ------------------------------------------------------------------ #

_PROFILE_MC_SCALES = {
    "conservative": {"vol_scale": 1.15, "return_scale": 0.70},
    "moderate":     {"vol_scale": 1.10, "return_scale": 0.80},
    "aggressive":   {"vol_scale": 1.00, "return_scale": 0.95},
}
_PROFILE_COLORS_MC = {
    "conservative": "#28A745",
    "moderate":     "#17A2B8",
    "aggressive":   "#DC3545",
}
_PROFILE_NAMES_MC = {
    "conservative": "🛡️ Conservador",
    "moderate":     "⚖️ Moderado",
    "aggressive":   "🚀 Agresivo",
}

# ------------------------------------------------------------------ #
#  Sidebar controls                                                    #
# ------------------------------------------------------------------ #

st.sidebar.subheader("⚙️ Parámetros de simulación")

# --- Phase 0: Improved Presets (clear selection + direct widget control) ---
st.sidebar.markdown("**🚀 Escenarios rápidos de largo plazo**")

preset_choice = st.sidebar.selectbox(
    "Elegir preset",
    [
        "— Ninguno —",
        "Acumulación pura (20 años)",
        "FIRE / Independencia Financiera (25 años)",
        "Meta importante (casa / gasto grande)",
        "Retiro clásico 30 años (4% rule + inflación)",
    ],
    key="preset_choice",
    help="Seleccioná un escenario típico. Los valores de los controles de abajo se actualizarán automáticamente."
)

if st.sidebar.button("Aplicar preset", type="primary", width="stretch"):
    if preset_choice == "Acumulación pura (20 años)":
        st.session_state["horizon_years"] = MONTE_CARLO.default_horizon_years
        st.session_state["initial_value"] = 100_000
        st.session_state["annual_withdrawal"] = 0
        st.session_state["target_value"] = 800_000
        st.session_state["inflation_rate"] = 3.0
        st.session_state["last_preset"] = "Acumulación pura"
    elif preset_choice == "FIRE / Independencia Financiera (25 años)":
        st.session_state["horizon_years"] = 25
        st.session_state["initial_value"] = 1_000_000
        st.session_state["annual_withdrawal"] = 35_000
        st.session_state["target_value"] = 0
        st.session_state["inflation_rate"] = 3.0
        st.session_state["last_preset"] = "FIRE / Indep. Fin."
    elif preset_choice == "Meta importante (casa / gasto grande)":
        st.session_state["horizon_years"] = 8
        st.session_state["initial_value"] = 150_000
        st.session_state["annual_withdrawal"] = 0
        st.session_state["target_value"] = 300_000
        st.session_state["inflation_rate"] = 4.0
        st.session_state["last_preset"] = "Meta casa / gasto"
    elif preset_choice == "Retiro clásico 30 años (4% rule + inflación)":
        st.session_state["horizon_years"] = WITHDRAWAL.default_longevity_years
        st.session_state["initial_value"] = 1_000_000
        st.session_state["annual_withdrawal"] = 40_000
        st.session_state["target_value"] = 0
        st.session_state["inflation_rate"] = 3.0
        st.session_state["last_preset"] = "Retiro clásico 30y"
    else:
        st.sidebar.warning("Elegí un escenario antes de aplicar.")
        st.stop()

    st.session_state["preset_applied"] = True
    st.rerun()

if st.session_state.get("preset_applied"):
    last = st.session_state.get("last_preset", "")
    st.sidebar.success(f"✅ Preset aplicado: **{last}**", icon="🚀")
    # Clear the flag after showing once
    st.session_state.pop("preset_applied", None)

# The widgets now use explicit keys so presets can control them directly
horizon_years = st.sidebar.selectbox(
    "Horizonte de proyección",
    [5, 10, 15, 20, 25, 30],
    index=3,
    format_func=lambda y: f"{y} años",
    help="Años desde hoy hasta la meta de retiro.",
    key="horizon_years",
)
initial_value = st.sidebar.number_input(
    "Capital inicial (USD)",
    min_value=1_000,
    max_value=10_000_000,
    value=100_000,
    step=5_000,
    format="%d",
    key="initial_value",
)
# U4-5: la palanca que faltaba. El único input de flujo era el retiro de abajo,
# con piso en cero, así que la pantalla que contesta «¿llego?» no podía
# representar que alguien ahorre — y sin embargo el consejo de «cuánto te falta»
# más abajo YA resolvía el ahorro del perfil y lo usaba. El consejo asumía que el
# usuario ahorra y la simulación que lo producía, no.
#
# La clave es `monthly_savings` a propósito: es la primera que
# `contribution_inputs` mira, y es la unidad en la que el perfil pregunta. Lo
# que se tipea acá pisa al perfil, que es lo correcto — un valor puesto en esta
# pantalla gana sobre uno heredado.
st.sidebar.number_input(
    "Ahorro mensual (USD, 0 = no aporto)",
    min_value=0,
    max_value=100_000,
    value=int(min(max(contribution_inputs(prefs=_prefs_sim)["monthly"], 0), 100_000)),
    step=100,
    format="%d",
    help=(
        "Cuánto ponés por mes durante el horizonte. El motor lo deposita "
        "**mensualmente**, no una vez al año (U4-1). Se siembra con el ahorro de "
        "tu perfil; si lo cambiás acá, manda este."
    ),
    key="monthly_savings",
)

annual_withdrawal = st.sidebar.number_input(
    "Retiro anual (USD, 0 = acumulación)",
    min_value=0,
    max_value=500_000,
    value=0,
    step=1_000,
    format="%d",
    help="Cuánto retirás cada año (fase de desacumulación). 0 si todavía estás acumulando.",
    key="annual_withdrawal",
)

# El número que va al motor sale del helper, nunca de un ×12 local: es lo que
# impide que dos pantallas le coticen plata distinta al mismo ahorrista (U4-1).
_contrib = contribution_inputs(st.session_state, prefs=_prefs_sim)
annual_contribution = _contrib["annual"]
if annual_contribution > 0:
    st.sidebar.caption(
        f"≈ \\${annual_contribution:,.0f}/año, en doce depósitos"
        + (" · viene de tu perfil" if _contrib["source"] == "perfil" else "")
    )
target_value = st.sidebar.number_input(
    "Meta de retiro (USD)",
    min_value=0,
    max_value=20_000_000,
    value=500_000,
    step=10_000,
    format="%d",
    help="Valor objetivo del portafolio al final del horizonte.",
    key="target_value",
)
inflation_rate = st.sidebar.slider(
    "Inflación esperada (%/año)",
    min_value=0.0,
    max_value=8.0,
    value=3.0,
    step=0.5,
    help="Ajusta tanto la línea de 'valor real' en el gráfico como el crecimiento anual del retiro "
         "(si tenés retiro > 0). Esto es clave para simulaciones realistas de largo plazo.",
    key="inflation_rate",
)
n_sims = st.sidebar.select_slider(
    "Número de simulaciones",
    options=[1_000, 2_000, 5_000, 10_000],
    value=MONTE_CARLO.default_n_sims,
    help="Más simulaciones = más precisión. 10 000 tarda < 3s.",
    key="n_sims",
)

# ------------------------------------------------------------------ #
#  Resolve portfolio from session state                                #
# Try optimizer_result first (current run), fall back to prev         #
# ------------------------------------------------------------------ #

opt_result = (
    st.session_state.get("optimizer_result")
    or st.session_state.get("optimizer_prev_result")
)

if opt_result and opt_result.tickers:
    symbols        = [a.symbol for a in opt_result.tickers]
    weights        = [a.weight_pct / 100 for a in opt_result.tickers]
    sector_weights = opt_result.sector_weights
    data_source    = f"Portafolio optimizado ({opt_result.profile_name}) — {len(symbols)} posiciones"
else:
    universe       = st.session_state.get("universe", ["SPY"])
    symbols        = [s for s in universe if s not in {"SPY", "QQQ", "VTI", "BND"}][:20]
    weights        = None
    sector_weights = {}
    for sect, tickers in SECTOR_MAP.items():
        count = sum(1 for t in symbols if t in tickers)
        if count > 0:
            sector_weights[sect] = count / len(symbols) * 100
    data_source = f"Universo equal-weight ({len(symbols)} tickers)"

st.info(
    f"📊 **Fuente de la simulación:** {data_source}. "
    "Usar un portafolio optimizado (en lugar de equal-weight del universo) produce proyecciones mucho más realistas "
    "para horizontes de 10-30 años, porque respeta tus límites de riesgo y dividendos por perfil.",
    icon="ℹ️",
)

if not (opt_result and opt_result.tickers):
    st.caption(
        "💡 **Recomendación para largo plazo:** Andá a **📈 Optimizer**, elegí tu perfil de riesgo (Conservador/Moderado/Agresivo) "
        "y generá una cartera. Volvé acá y las simulaciones usarán automáticamente esos pesos y sectores optimizados."
    )

# ------------------------------------------------------------------ #
#  Tabs                                                                #
# ------------------------------------------------------------------ #

tab_mc, tab_stress, tab_custom, tab_compare, tab_goals = st.tabs(
    ["📈 Monte Carlo", "🌪️ Stress Test", "🎯 Escenario personalizado", "🔀 Comparar Perfiles", "🏆 Mis Metas"]
)

# ================================================================== #
#  Tab 1: Monte Carlo                                                 #
# ================================================================== #


def _tab_mc_content():
    # Item 1 — economic drags / assumptions control (persistent, opt-in).
    render_drags_controls(key_prefix="sim_")
    # Fase H.1 — decumulation / withdrawal strategy (persistent, opt-in).
    render_withdrawal_controls(key_prefix="sim_", initial_value=float(initial_value))
    run_mc = st.button("▶ Ejecutar simulación Monte Carlo", type="primary")

    if not run_mc and "mc_result" not in st.session_state:
        st.info(
            "Configurá los parámetros en el sidebar (horizonte, capital inicial, retiro anual, meta, inflación) "
            "y hacé clic en **▶ Ejecutar simulación Monte Carlo** para comenzar.\n\n"
            "Las simulaciones usan block-bootstrap sobre historia real de 10 años con ajustes conservadores "
            "— ideales para evaluar planes de inversión a 10-30 años.",
            icon="🎲",
        )
        return

    if run_mc:
        drags = get_economic_drags()
        wd_strategy = get_withdrawal_strategy(float(initial_value))   # Fase H.1
        longevity = get_longevity_years() if wd_strategy else None
        with st.spinner(f"Ejecutando {n_sims:,} simulaciones × {horizon_years} años…"):
            mc = cached_monte_carlo(
                symbols=tuple(symbols),
                weights_tuple=tuple(weights) if weights else None,
                horizon_years=horizon_years,
                n_sims=n_sims,
                initial_value=float(initial_value),
                annual_withdrawal=float(annual_withdrawal),
                annual_contribution=float(annual_contribution),   # U4-5
                target_value=float(target_value),
                withdrawal_growth_rate=float(inflation_rate) / 100.0,   # Phase 0: growing withdrawals
                drags_tuple=drags_to_tuple(drags),                      # Item 1
                withdrawal_tuple=withdrawal_to_tuple(wd_strategy),      # Fase H.1
                longevity_years=longevity,                              # Fase H.1
            )
        st.session_state["mc_result"] = mc
        st.session_state["mc_params"] = {
            "horizon_years": horizon_years,
            "initial_value": initial_value,
            "inflation_rate": inflation_rate,
            "n_sims": n_sims,
            "drags": drags,   # Item 1: remember the assumptions used
            "withdrawal_strategy": wd_strategy,   # Fase H.1: remember the strategy used
        }
        if getattr(mc, "total_annual_drag_pct", 0.0) > 0:
            st.info(
                f"{format_drags_badge(drags)}  \n"
                f"Mediana **con drags**: ${mc.median_terminal:,.0f} · "
                f"**base** (sin drags): ${mc.base_median_terminal:,.0f}.",
                icon="📊",
            )
        # Next step in the recommended flow (Fase E): consolidate into Mi Plan
        st.caption(
            "💡 **Siguiente paso:** con tu cartera optimizada + esta proyección, andá a "
            "🗺️ **Mi Plan** para consolidar, guardar y activar tu plan de retiro."
        )

    mc = st.session_state.get("mc_result")
    if mc is None:
        from data.product_ux import guided_empty_state

        _es = guided_empty_state("simulaciones")
        st.warning(f"**{_es['title']}** — {_es['body']}", icon="🎲")
        st.info(_es["demo_hint"], icon="💡")
        _e1, _e2 = st.columns(2)
        if _e1.button("📈 Ir al Optimizer", key="sim_empty_opt", width="stretch"):
            st.switch_page(str(Path(__file__).parent / "5_Optimizer.py"))
        if _e2.button("🗺️ Mi Plan (ejemplo)", key="sim_empty_plan", width="stretch"):
            st.switch_page(str(Path(__file__).parent / "12_Plan.py"))
        return

    for w in mc.warnings:
        st.warning(w)

    # ---- KPI row (improved clarity for long-term investors) ----
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Capital inicial", f"${initial_value:,.0f}")

    # U1-7: con retiros (o aportes) la tasa anualizada del pozo deja de ser un
    # retorno — el capital que entra/sale mueve el terminal sin mover el
    # inicial. El vocabulario lo decide el flag, no la página.
    _mc_flows = mc_has_cash_flows(mc)
    _growth_help = pot_growth_help(_mc_flows)

    k2.metric(
        "Valor más probable (mediana)",
        f"${mc.median_terminal:,.0f}",
        delta=pot_growth_delta(mc.median_cagr_pct, _mc_flows),
        delta_color="off",
        delta_arrow="off",
        help="En la mitad de las simulaciones terminás por encima de este número, "
             "y en la mitad por debajo.\n\n" + _growth_help,
    )

    k3.metric(
        "⚠️ Escenario pesimista (peor 10%)",
        f"${mc.p10_terminal:,.0f}",
        delta=pot_growth_delta(mc.p10_cagr_pct, _mc_flows),
        # "off", no "inverse": teñir de rojo una tasa positiva confunde. Lo malo
        # acá es el escenario, y eso ya lo dice la etiqueta "pesimista".
        delta_color="off",
        delta_arrow="off",
        help="En 1 de cada 10 simulaciones terminás con este valor o menos. Este es "
             "el caso 'malo' que debés estar dispuesto a aceptar.\n\n" + _growth_help,
    )

    k4.metric(
        "Escenario optimista (mejor 10%)",
        f"${mc.p90_terminal:,.0f}",
        help="Solo en 1 de cada 10 simulaciones terminás por encima de este valor (caso muy favorable).",
    )

    if target_value > 0:
        k5.metric(
            "Probabilidad de alcanzar tu meta",
            f"{mc.prob_achieve_target_pct:.1f}%",
            delta=f"de llegar a ${target_value:,.0f}",
            delta_color="off",
            delta_arrow="off",
            help="Porcentaje de las 10.000 simulaciones que superaron o igualaron tu objetivo.",
        )
    else:
        k5.metric(
            "Probabilidad de quedarte en 0",
            f"{mc.prob_ruin_pct:.1f}%",
            delta_color="inverse",
            help="Casos en los que el portafolio llega a cero o negativo antes del final del horizonte.",
        )

    # ---- Realista vs Conservador: no engañar con un solo número ----
    if getattr(mc, "realistic_reference_applied", False) and mc.realistic_median_terminal > 0:
        _gap_pct = (mc.realistic_median_terminal / mc.median_terminal - 1) * 100 if mc.median_terminal else 0
        st.info(
            "📊 **Dos escenarios para no engañarte con un solo número:**  \n"
            f"• **Realista** (si el futuro se parece al historial): mediana **${mc.realistic_median_terminal:,.0f}** "
            f"· pesimista ${mc.realistic_p10_terminal:,.0f}  \n"
            f"• **Conservador** (piso prudente, los números de arriba): mediana **${mc.median_terminal:,.0f}** "
            f"· pesimista ${mc.p10_terminal:,.0f}  \n"
            f"Planificá con el conservador (mediana ~{_gap_pct:.0f}% más baja que el realista a propósito): "
            "asume rendimientos futuros más bajos y más volatilidad, así que también baja el piso pesimista. "
            "El realista es la referencia de cuánto podrías terminar si todo sale como el pasado reciente.",
            icon="📊",
        )

    # From "no llegás" to "hacé esto" with *numbers* (backlog 3).
    if target_value > 0 and mc.prob_achieve_target_pct < 70:
        from data.product_ux import compute_gap_to_goal_levers

        # U4-1: one helper owns the monthly→annual conversion, so this screen
        # and Metas cannot quote the same saver different money. It also
        # replaces a read of a session key that no widget ever wrote — a
        # fallback dressed up as a user input.
        _ann_contrib = contribution_inputs(st.session_state, prefs=_prefs_sim)["annual"]
        # U1-7: `median_cagr_pct` NO puede alimentar `annual_return` cuando la
        # simulación tuvo flujos. `compute_gap_to_goal_levers` capitaliza los
        # aportes por su cuenta, así que pasarle una tasa que ya los contiene
        # los cuenta dos veces; con retiros pasa lo inverso y la palanca
        # subestima el faltante. Sin flujos la tasa sí es un retorno y se usa.
        _er = 0.0 if mc_has_cash_flows(mc) else (
            float(getattr(mc, "median_cagr_pct", 0) or 0) / 100.0
        )
        if _er <= 0:
            _er = 0.05
        _levers = compute_gap_to_goal_levers(
            capital=float(initial_value),
            annual_contribution=_ann_contrib,
            years=float(horizon_years),
            annual_return=_er,
            target=float(target_value),
            prob_achieve_pct=float(mc.prob_achieve_target_pct),
        )
        st.warning(
            f"🎯 **Con holgura no llegás** (probabilidad {mc.prob_achieve_target_pct:.0f}%). "
            "Palancas concretas (modelo simple de capitalización — orientativo):",
            icon="🧭",
        )
        if _levers:
            for _lv in _levers:
                st.markdown(f"- **{_lv['label']}:** {_lv['detail']}  \n  → _{_lv['cta_hint']}_")
        else:
            st.markdown(
                "- 💵 Aportar más · ⏳ más años · 🎯 bajar meta · ⚖️ más riesgo (Optimizer)"
            )
        _lc1, _lc2 = st.columns(2)
        if _lc1.button("🗺️ Ir a Mi Plan", key="sim_gap_plan", width="stretch"):
            st.switch_page(str(Path(__file__).parent / "12_Plan.py"))
        if _lc2.button("💼 Ir a Portfolio", key="sim_gap_port", width="stretch"):
            st.switch_page(str(Path(__file__).parent / "3_Portfolio.py"))
        st.caption(
            "📊 Calculado · palancas con fórmula de valor futuro (no IA). "
            "Bajá a **🔬 Sensibilidad** para el impacto estocástico de cada factor."
        )

    # AR dual-currency context (backlog 10) — product presentation, not tax advice.
    #
    # Audit U2-5: the median terminal is USD *nominal at the horizon*, and so is
    # the target — the sidebar defines it as "valor objetivo del portafolio al
    # final del horizonte" and the engine scores it against the nominal
    # terminals (`prob_achieve_target_pct`). Both used to be multiplied by
    # today's spot rate; both are now deflated on the same basis, so the two
    # lines stay comparable with each other and with the probability above.
    #
    # `inflation_rate` is always an answer, 0 % included — the slider starts
    # there — so it is passed through as the assumption it is.
    if mc.median_terminal:
        try:
            _fx_median = ar_dual_context(
                float(mc.median_terminal),
                fx_config=AR_FX,
                label="mediana final",
                horizon_years=horizon_years,
                usd_inflation_pct=float(inflation_rate),
            )
            _fx_target = (
                ar_dual_context(
                    float(target_value),
                    fx_config=AR_FX,
                    label="meta",
                    horizon_years=horizon_years,
                    usd_inflation_pct=float(inflation_rate),
                )
                if target_value > 0
                else None
            )
            with st.expander("🇦🇷 Equivalente en pesos de hoy (supuesto, no cotización)", expanded=False):
                st.caption(
                    f"Tasas de referencia — origen: **{AR_FX.rate_source}**"
                    + (f" · al {AR_FX.rate_asof}" if AR_FX.rate_asof else "")
                    + ". Configurables (`AR_FX` / env `USD_ARS_*`). No es cotización en "
                    "vivo ni asesoramiento cambiario."
                )
                if _fx_median["available"]:
                    st.markdown(f"**Mediana proyectada:** {escape_dollars(_fx_median['line'])}")
                else:
                    st.info(_fx_median["reason"], icon="ℹ️")
                if _fx_target is not None:
                    if _fx_target["available"]:
                        st.markdown(f"**Tu meta:** {escape_dollars(_fx_target['line'])}")
                    else:
                        st.info(_fx_target["reason"], icon="ℹ️")
        except Exception as exc:  # the FX block only — logged, never swallowed (U2-5)
            logger.warning("AR dual-currency block failed to render: {}", exc)
            st.caption("⚠️ La vista en pesos no se pudo mostrar.")

    # ---- Fase H.1: decumulation / retirement-income metrics ----
    _wd = getattr(mc, "withdrawal_strategy_applied", None)
    if _wd:
        st.divider()
        st.markdown("#### 🏖️ ¿Cuánto dura tu ingreso de retiro?")
        st.caption(format_withdrawal_badge(_wd))
        d1, d2, d3 = st.columns(3)
        _longevity = getattr(mc, "longevity_years", 0) or horizon_years
        d1.metric(
            f"Prob. de que dure {_longevity} años",
            f"{mc.prob_sustain_real_pct:.0f}%",
            help="Porcentaje de simulaciones en las que el ingreso NUNCA se agotó durante el horizonte de retiro.",
        )
        d2.metric(
            "Herencia mediana",
            f"${mc.median_legacy:,.0f}",
            help="Valor final mediano (lo que típicamente queda al final).",
        )
        if mc.expected_depletion_year > 0:
            d3.metric(
                "Si se agota, año típico",
                f"Año {mc.expected_depletion_year:.0f}",
                delta_color="off",
                help="Entre las simulaciones que SÍ se quedaron sin fondos, el año mediano en que ocurrió.",
            )
        else:
            d3.metric(
                "Si se agota, año típico",
                "Nunca",
                delta_color="off",
                help="Ninguna simulación se quedó sin fondos en este horizonte.",
            )
        if mc.prob_sustain_real_pct >= 90:
            st.success(f"✅ Estrategia robusta: tu ingreso dura los {_longevity} años en {mc.prob_sustain_real_pct:.0f}% de los escenarios.")
        elif mc.prob_sustain_real_pct >= 75:
            st.warning(f"⚠️ Probabilidad razonable ({mc.prob_sustain_real_pct:.0f}%) pero no altísima. Considerá una estrategia con guardrails, retirar menos, o más capital.")
        else:
            st.error(f"❌ Riesgo de quedarte sin fondos: el ingreso solo dura los {_longevity} años en {mc.prob_sustain_real_pct:.0f}% de los casos. Reducí el retiro o ajustá la estrategia.")
        st.divider()

    # ---- Quick interpretation (Fase 0 improvement) ----
    with st.expander("📊 ¿Qué significan estos números para tu plan?", expanded=True):
        # Calculate real (inflation-adjusted) terminal values
        real_p10 = real_median = real_p90 = None
        if inflation_rate > 0:
            real_p10 = mc.p10_terminal / ((1 + inflation_rate / 100) ** horizon_years)
            real_median = mc.median_terminal / ((1 + inflation_rate / 100) ** horizon_years)
            real_p90 = mc.p90_terminal / ((1 + inflation_rate / 100) ** horizon_years)

            st.markdown(f"**En poder de compra de hoy (después de {inflation_rate:.1f}% inflación anual):**")
            st.markdown(f"- Caso más probable: tus \\${initial_value:,.0f} de hoy tendrían el poder de compra de **\\${real_median:,.0f}**")
            st.markdown(f"- Escenario pesimista (1 de cada 10 casos): **\\${real_p10:,.0f}**")
            st.markdown(f"- Escenario muy bueno (1 de cada 10 casos): **\\${real_p90:,.0f}**")
        else:
            st.markdown("**Valores en dólares de hoy:**")

        st.markdown(f"""
**Valores nominales (sin ajustar por inflación):**
- Caso más probable: **\\${mc.median_terminal:,.0f}** ({mc.median_terminal/initial_value:.1f}x)
- Escenario pesimista: **\\${mc.p10_terminal:,.0f}** o menos
- Escenario optimista: **\\${mc.p90_terminal:,.0f}** o más
""")

        # Much more direct reality check
        st.markdown("**⚠️ Por qué estos números pueden engañarte (importante leer):**")
        if real_p10 is not None:
            st.markdown(f"""
Aunque el escenario pesimista nominal (\\${mc.p10_terminal:,.0f}) parece "ganar", tené en cuenta:

- En **poder de compra real** (después de inflación), en el peor 10% de los casos solo terminás con **\\${real_p10:,.0f}** de los dólares de hoy. Eso es un crecimiento real bastante modesto en {horizon_years} años.
- El modelo ya está siendo conservador (le saca 20% al retorno histórico). Aun así, el período que usamos como base fue bueno. El futuro puede ser peor.
- Estos son solo valores **al final** de los {horizon_years} años. Durante el camino podés haber tenido caídas del 50% o más. Si en ese momento sacás plata o te asustás y vendés, el resultado final puede ser mucho peor que el P10 que ves acá.
- Si en algún momento empezás a retirar plata (aunque sea poco), el riesgo de que el "caso malo" sea realmente malo sube mucho (riesgo de secuencia de retornos).

En resumen: el modelo no está diciendo "siempre vas a ganar mucho". Está diciendo que, **incluso en un escenario malo pero no catastrófico**, todavía terminás con más capital del que empezaste en términos reales. Casos peores que los históricos (o errores de comportamiento) no están totalmente capturados.
""")
        else:
            st.markdown(f"""
- El modelo ya está siendo conservador (le saca 20% al retorno histórico). Aun así, el futuro puede ser peor que el pasado reciente.
- Estos son solo valores **al final** de los {horizon_years} años. Durante el camino podés haber tenido caídas del 50% o más.
- Si en algún momento empezás a retirar plata, el riesgo de que el "caso malo" sea realmente malo sube mucho (riesgo de secuencia de retornos).
""")

        if target_value > 0:
            if mc.prob_achieve_target_pct >= 85:
                st.success(f"✅ Con este plan tenés **muy buena probabilidad ({mc.prob_achieve_target_pct:.0f}%)** de alcanzar tu meta de \\${target_value:,.0f}.")
            elif mc.prob_achieve_target_pct >= 60:
                st.warning(f"⚠️ Tenés una probabilidad razonable ({mc.prob_achieve_target_pct:.0f}%), pero no es altísima. Considerá ajustar aportes, reducir la meta o asumir un poco más de riesgo.")
            else:
                st.error(f"❌ La probabilidad de alcanzar \\${target_value:,.0f} es baja ({mc.prob_achieve_target_pct:.0f}%). Este plan probablemente necesite cambios (más ahorro, más horizonte, o menos retiro).")

        if annual_withdrawal > 0 and inflation_rate > 0:
            st.info("ℹ️ Recordá que el retiro que estás simulando **crece cada año** con la inflación que elegiste. Esto hace que el escenario pesimista sea más exigente.")

    st.divider()

    # ---- Phase 0: Narrative AI explanation (quick win) ----
    try:
        ai_cfg = _get_ai_config("plan_narrative")
    except Exception:
        ai_cfg = None

    if ai_cfg and ai_cfg.enabled and ai_cfg.api_key:
        if st.button("🧠 Explicame este plan en lenguaje humano (IA)", type="secondary", key="narrative_btn"):
            with st.spinner("Generando explicación conservadora con IA..."):
                from analysis.ai_analyzer import AIAnalyzer

                # Build rich context from current optimizer + MC result
                opt_for_narrative = opt_result or st.session_state.get("optimizer_prev_result")
                tickers = [a.symbol for a in opt_for_narrative.tickers] if opt_for_narrative and opt_for_narrative.tickers else symbols
                narrative_weights = [a.weight_pct/100 for a in opt_for_narrative.tickers] if opt_for_narrative and opt_for_narrative.tickers else ([1.0/len(symbols)]*len(symbols) if symbols else [])

                narrative_context = {
                    "profile_name": getattr(opt_for_narrative, "profile_name", "Moderado"),
                    "tickers": tickers,
                    "weights": narrative_weights,
                    "expected_return": getattr(opt_for_narrative, "expected_return_pct", 0.0) if opt_for_narrative else 0.0,
                    "volatility": getattr(opt_for_narrative, "volatility_pct", 0.0) if opt_for_narrative else 0.0,
                    "sharpe": getattr(opt_for_narrative, "sharpe_ratio", 0.0) if opt_for_narrative else 0.0,
                    "dividend_yield": getattr(opt_for_narrative, "dividend_yield_pct", 0.0) if opt_for_narrative else 0.0,
                    "horizon_years": horizon_years,
                    "initial_value": float(initial_value),
                    "annual_withdrawal": float(annual_withdrawal),
                    "inflation_rate": float(inflation_rate),
                    "median_terminal": mc.median_terminal,
                    "p10_terminal": mc.p10_terminal,
                    "p90_terminal": mc.p90_terminal,
                    "prob_ruin": mc.prob_ruin_pct,
                    "prob_target": mc.prob_achieve_target_pct,
                    "target_value": float(target_value),
                }

                analyzer = AIAnalyzer(ai_cfg)
                narrative = analyzer.generate_long_term_narrative(narrative_context)
                st.session_state["last_plan_narrative"] = narrative

        if "last_plan_narrative" in st.session_state:
            with st.expander("📝 Explicación del plan (generada por IA)", expanded=True):
                st.markdown(st.session_state["last_plan_narrative"])
                st.caption("⚠️ Esta explicación es generada por IA y tiene fines educativos. Siempre contrastá con un asesor financiero certificado.")
    else:
        st.caption("💡 Habilita IA en ⚙️ Settings (con API key) para obtener una explicación en lenguaje humano de tu plan de largo plazo.")

    # ---- Fan chart ----
    if mc.fan_paths:
        years_list = mc.years

        _BAND_COLORS = {
            5:  "rgba(220,53,69,0.12)",
            10: "rgba(255,193,7,0.12)",
            25: "rgba(40,167,69,0.12)",
        }
        fan_chart = go.Figure()

        # Shaded bands
        for lo, hi in [(5, 95), (10, 90), (25, 75)]:
            lo_vals = [mc.fan_paths[y][lo] for y in years_list]
            hi_vals = [mc.fan_paths[y][hi] for y in years_list]
            fan_chart.add_trace(go.Scatter(
                x=years_list + years_list[::-1],
                y=hi_vals + lo_vals[::-1],
                fill="toself",
                fillcolor=_BAND_COLORS[lo],
                line=dict(color="rgba(0,0,0,0)"),
                name=f"P{lo}–P{hi}",
                hoverinfo="skip",
            ))

        # Percentile lines
        fan_chart.add_trace(go.Scatter(
            x=years_list,
            y=[mc.fan_paths[y][50] for y in years_list],
            mode="lines",
            line=dict(color="#17A2B8", width=2.5),
            name="Mediana (P50)",
        ))
        fan_chart.add_trace(go.Scatter(
            x=years_list,
            y=[mc.fan_paths[y][10] for y in years_list],
            mode="lines",
            line=dict(color="#DC3545", width=1.5, dash="dot"),
            name="Pesimista (P10)",
        ))
        fan_chart.add_trace(go.Scatter(
            x=years_list,
            y=[mc.fan_paths[y][90] for y in years_list],
            mode="lines",
            line=dict(color="#28A745", width=1.5, dash="dot"),
            name="Optimista (P90)",
        ))

        # Inflation-adjusted real value line
        if inflation_rate > 0:
            real_median = [
                mc.fan_paths[y][50] / (1 + inflation_rate / 100) ** y
                for y in years_list
            ]
            fan_chart.add_trace(go.Scatter(
                x=years_list,
                y=real_median,
                mode="lines",
                line=dict(color="#FF8C00", width=2, dash="dash"),
                name=f"Mediana real ({inflation_rate:.1f}% inf.)",
            ))

        # Goal line
        if target_value > 0:
            fan_chart.add_hline(
                y=target_value,
                line_dash="dash", line_color="gold", line_width=2,
                annotation_text=f"Meta: ${target_value:,.0f}",
                annotation_position="right",
            )

        fan_chart.update_layout(
            title=f"Fan Chart — {n_sims:,} simulaciones × {horizon_years} años",
            xaxis_title="Años desde hoy",
            yaxis_title="Valor del portafolio (USD)",
            yaxis_tickformat="$,.0f",
            height=520,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
            hovermode="x unified",
        )
        st.plotly_chart(fan_chart, width="stretch")
        _real_note = (
            f" La línea naranja punteada muestra el poder adquisitivo real "
            f"(descontando {inflation_rate:.1f}% de inflación anual)."
            if inflation_rate > 0 else ""
        )
        st.caption(
            "Las bandas muestran el rango de resultados posibles según la historia real de los mercados. "
            "Azul = caso más probable | Rojo = mal caso (1 de cada 10) | Verde = muy buen caso (1 de cada 10). "
            + _real_note
            + " Los números usan un ajuste conservador (+10% volatilidad y −20% retorno histórico respecto al pasado)."
        )

    # ---- Histogram of terminal values ----
    if mc.fan_paths and horizon_years in mc.fan_paths:
        st.subheader(f"Distribución de valores finales a {horizon_years} años")

        # Reconstruct approximate terminal distribution from percentiles
        pcts = [5, 10, 25, 50, 75, 90, 95]
        vals = [mc.fan_paths[horizon_years][p] for p in pcts]

        # Build interpolated histogram via synthetic sample (for smooth display)
        # We show bars at key percentile breakpoints with annotation
        fig_hist = go.Figure()
        fig_hist.add_trace(go.Bar(
            x=[f"P{p}" for p in pcts],
            y=vals,
            marker_color=[
                "#DC3545" if p <= 10 else
                "#FFC107" if p <= 25 else
                "#17A2B8" if p == 50 else
                "#28A745"
                for p in pcts
            ],
            text=[f"${v:,.0f}" for v in vals],
            textposition="outside",
        ))
        if target_value > 0:
            fig_hist.add_hline(
                y=target_value,
                line_dash="dash", line_color="gold", line_width=2,
                annotation_text=f"Meta ${target_value:,.0f}",
                annotation_position="right",
            )
        fig_hist.update_layout(
            title=f"Valor del portafolio por percentil — año {horizon_years}",
            xaxis_title="Percentil",
            yaxis_title="Valor (USD)",
            yaxis_tickformat="$,.0f",
            height=380,
            showlegend=False,
        )
        st.plotly_chart(fig_hist, width="stretch")

    # ---- Terminal distribution table ----
    if mc.fan_paths:
        # U1-7: una sola implementación de (terminal/inicial)^(1/años)−1, y el
        # rótulo lo elige el flag de flujos. `pot_growth_pct` devuelve None para
        # un pozo agotado — se muestra vacío, no 0 %, que se leería "plano".
        _growth_col = pot_growth_column_label(_mc_flows)
        pct_rows = []
        for p in [5, 10, 25, 50, 75, 90, 95]:
            v = mc.fan_paths[horizon_years][p]
            real_v = v / (1 + inflation_rate / 100) ** horizon_years if inflation_rate > 0 else None
            _g = pot_growth_pct(v, initial_value, horizon_years)
            row = {
                "Percentil": f"P{p}",
                "Valor nominal": v,
                _growth_col: round(_g, 1) if _g is not None else None,
            }
            if real_v is not None:
                row["Valor real"] = round(real_v)
            pct_rows.append(row)

        df_terminal = pd.DataFrame(pct_rows)
        _col_cfg = {
            "Valor nominal": st.column_config.NumberColumn("Valor nominal", format="$%,.0f"),
            _growth_col:     st.column_config.NumberColumn(
                _growth_col, format="%.1f%%", help=_growth_help
            ),
        }
        if inflation_rate > 0:
            _col_cfg["Valor real"] = st.column_config.NumberColumn(
                f"Valor real ({inflation_rate:.1f}% inf.)", format="$%,.0f"
            )
        st.dataframe(df_terminal, width="stretch", hide_index=True, column_config=_col_cfg)

        # Export
        _csv_buf = io.StringIO()
        df_terminal.to_csv(_csv_buf, index=False)
        st.download_button(
            label="⬇️ Exportar distribución a CSV",
            data=_csv_buf.getvalue(),
            file_name=f"montecarlo_{horizon_years}y_{n_sims}sims.csv",
            mime="text/csv",
        )

    # ---- Fase H.3: sensitivity & scenario lab ----
    _render_sensitivity_lab()

    with st.expander("ℹ️ Metodología y limitaciones"):
        st.markdown(f"""
**Metodología:** Block Bootstrap ({mc.n_weeks_history} semanas de historia real, bloques de 4 semanas).
No asume distribución normal — captura fat tails y autocorrelación de corto plazo.

**Ajuste conservador aplicado:**
- Volatilidad histórica × **{MONTE_CARLO.vol_adjustment:.0%}** (+10%)
- Retorno histórico × **{MONTE_CARLO.mean_haircut:.0%}** (−20%)

**Por qué ser conservador:** Los retornos de 2010-2024 fueron excepcionales.
La prima de riesgo histórica del S&P 500 (~7% real) probablemente no se repita a la misma tasa.

**Sobre la inflación:** El ajuste de inflación ({inflation_rate:.1f}%) ahora tiene dos efectos:
1. Visual: muestra el poder adquisitivo real (línea naranja punteada).
2. En retiros: si tenés un retiro anual > 0, el monto retirado crece cada año a esa tasa (simula retiros ajustados por inflación — fundamental para planes de 15-30 años).
Esto es un cambio de Fase 0 para modelado más realista de largo plazo.

**Limitaciones:** Esta simulación no predice el futuro. Los retornos pasados no garantizan resultados futuros.
No considera impuestos, cambios en la asignación de activos, ni eventos imprevisibles.
Consultá con un asesor financiero certificado antes de tomar decisiones de inversión.
        """)


def _render_sensitivity_lab():
    """Fase H.3 — what-if workbench: tornado + predefined retirement scenarios."""
    st.divider()
    st.markdown("#### 🔬 Sensibilidad del plan (laboratorio de supuestos)")
    st.caption(
        "Mové un supuesto por vez para ver a qué es más sensible tu plan (tornado), "
        "y probá escenarios de retiro completos. Usa una simulación más liviana para ir rápido; "
        "el caso base es siempre tu corrida actual."
    )

    _metric_label = {
        "p10_terminal": "Escenario pesimista (P10)",
        "median_terminal": "Caso más probable (mediana)",
        "prob_ruin_pct": "Probabilidad de ruina",
    }
    metric = st.selectbox(
        "Métrica a analizar",
        options=["p10_terminal", "median_terminal", "prob_ruin_pct"],
        format_func=lambda k: _metric_label[k],
        key="sens_metric",
    )

    if not st.button("🔬 Ejecutar análisis de sensibilidad", key="run_sensitivity"):
        st.caption("Tocá el botón para correr el laboratorio (varias mini-simulaciones).")
        return

    _wd = get_withdrawal_strategy(float(initial_value))
    base_params = {
        "symbols": tuple(symbols),
        "weights": tuple(weights) if weights else None,
        "horizon_years": int(horizon_years),
        "initial_value": float(initial_value),
        "annual_withdrawal": float(annual_withdrawal),
        # U4-3: el laboratorio corría el plan del usuario sin sus ahorros. La
        # pestaña de arriba ya lo pasaba (U4-5) y acá se perdía, así que el caso
        # base del tornado era otro plan — 490.275 contra 1.234.907 sobre el
        # mismo ahorrista— y las cuatro palancas y los cuatro escenarios se
        # medían contra ese. Sale del mismo `contribution_inputs`, sin ×12 local.
        "annual_contribution": float(annual_contribution),
        "target_value": float(target_value),
        "withdrawal_growth_rate": float(inflation_rate) / 100.0,
        "vol_scale": 1.0,
        "return_scale": 1.0,
        "drags_total_pct": float(get_economic_drags().get("total_annual_drag_pct", 0.0)),
        "withdrawal_tuple": withdrawal_to_tuple(_wd),
        "longevity_years": get_longevity_years() if _wd else None,
    }

    with st.spinner("Corriendo el laboratorio de sensibilidad…"):
        res = run_plan_sensitivity(base_params, primary_metric=metric)

    _is_money = metric != "prob_ruin_pct"
    _fmt = (lambda v: f"${v:,.0f}") if _is_money else (lambda v: f"{v:.1f}%")
    base_val = res.base.get(metric, 0.0)
    st.caption(f"**Caso base — {_metric_label[metric]}: {_fmt(base_val)}**")

    # --- Tornado ---
    # U4-3: una palanca que no toca este plan se rotula, no se dibuja en cero.
    # `x=[hi - lo]` con hi == lo es una barra invisible junto a su etiqueta, y el
    # pie dice "la barra más larga = el supuesto que más mueve tu resultado": el
    # usuario lee "la indexación no mueve mi plan", que es una afirmación y no la
    # ausencia de una. Quién no aplica lo decide el motor (`sensitivity._applies`),
    # que lo mide sobre las cuatro métricas; la pantalla sólo lo presenta.
    _NO_APLICA = "no aplica a este plan"
    rows = tornado_rows(res, metric=metric)
    _hay_inaplicables = any(not r["applies"] for r in rows)
    fig = go.Figure()
    for r in rows:
        _label = r["label"] if r["applies"] else f"{r['label']} ({_NO_APLICA})"
        if not r["applies"]:
            # Marca de posición: la fila sigue en el eje —sacarla escondería que
            # el motor consideró el supuesto— pero sin barra que leer.
            fig.add_trace(go.Bar(
                y=[_label], x=[0], base=base_val, orientation="h",
                marker_color="rgba(0,0,0,0)", showlegend=False,
                hovertemplate=(
                    f"{r['label']}<br>{_NO_APLICA}: mover este supuesto no cambió "
                    f"ninguna métrica de tu plan<extra></extra>"
                ),
            ))
            continue
        lo, hi = min(r["low"], r["high"]), max(r["low"], r["high"])
        fig.add_trace(go.Bar(
            y=[_label], x=[hi - lo], base=lo, orientation="h",
            marker_color="#17A2B8", showlegend=False,
            hovertemplate=(
                f"{r['label']}<br>{r['low_label']}: {_fmt(r['low'])}"
                f"<br>{r['high_label']}: {_fmt(r['high'])}<extra></extra>"
            ),
        ))
    fig.add_vline(x=base_val, line_dash="dash", line_color="gold",
                  annotation_text="base", annotation_position="top")
    fig.update_layout(
        title=f"Tornado — impacto en {_metric_label[metric]}",
        xaxis_title=_metric_label[metric],
        xaxis_tickformat="$,.0f" if _is_money else ".1f",
        height=300, barmode="overlay", margin=dict(l=10, r=10, t=40, b=10),
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig, width="stretch")
    _pie = (
        "Cada barra es el rango de la métrica cuando ese supuesto se mueve a su valor bajo/alto "
        "(todo lo demás fijo). La barra más larga = el supuesto que más mueve tu resultado."
    )
    if _hay_inaplicables:
        _pie += (
            f" Una palanca marcada «{_NO_APLICA}» **no se midió en cero**: moverla no "
            "entra en tu plan tal como está configurado — por ejemplo, la indexación "
            "del gasto no toca un retiro que ya se calcula como % del capital actual."
        )
    st.caption(_pie)
    st.caption(
        indexation_help(
            has_contribution=float(annual_contribution) > 0,
            has_withdrawal=float(annual_withdrawal) > 0,
        )
    )

    # --- Scenario table ---
    st.markdown("**Escenarios de retiro predefinidos**")
    _scn_rows = []
    for s in res.scenarios:
        _d = s.deltas.get(metric, 0.0)
        _scn_rows.append({
            "Escenario": s.label,
            "Qué cambia": s.description,
            _metric_label[metric]: _fmt(s.metrics.get(metric, 0.0)),
            # U4-3: mismo criterio que el tornado. Un escenario que no tocó
            # ninguna métrica reportaba "Δ vs base $0", que es un cero medido.
            "Δ vs base": (
                f"{'+' if _d >= 0 else ''}{_fmt(_d)}" if s.applies else _NO_APLICA
            ),
        })
    st.dataframe(pd.DataFrame(_scn_rows), width="stretch", hide_index=True)
    st.caption(
        "Orientativo — combina supuestos realistas usando tu propia cartera. No es asesoramiento financiero."
    )


# ================================================================== #
#  Tab 2: Stress Test                                                 #


with tab_mc:
    _tab_mc_content()

# ================================================================== #

def _tab_stress_content():
    st.subheader("Simulación de crisis históricas")
    st.caption(
        "Impacto estimado sobre el portafolio actual en cada crisis, "
        "calculado desde los pesos por sector del optimizador."
    )

    if not sector_weights:
        st.info("Ejecutá el Optimizer primero para obtener pesos por sector.", icon="⚠️")
    else:
        stress_results = cached_stress_test(
            sector_weights_tuple=tuple(sorted(dict(sector_weights).items())),
            initial_value=float(initial_value),
        )

        stress_data = []
        for r in stress_results:
            color_rel = "🟢" if r.better_than_spy else "🔴"
            stress_data.append({
                "Escenario":         r.scenario.name,
                "Caída cartera %":   r.portfolio_drawdown_pct,
                "Caída SPY %":       r.benchmark_drawdown_pct,
                "vs SPY":            f"{color_rel} {r.relative_performance_pct:+.1f}%",
                "Pérdida USD":       r.portfolio_loss_usd,
                "Valor mínimo":      r.portfolio_trough_value,
                "Recuperación est.": f"{r.recovery_years_est:.1f} años",
            })

        df_stress = pd.DataFrame(stress_data)
        st.dataframe(
            df_stress,
            width="stretch",
            hide_index=True,
            column_config={
                "Caída cartera %": st.column_config.NumberColumn("Caída cartera %", format="%.1f%%"),
                "Caída SPY %":     st.column_config.NumberColumn("Caída SPY %",     format="%.1f%%"),
                "Pérdida USD":     st.column_config.NumberColumn("Pérdida USD",     format="$%,.0f"),
                "Valor mínimo":    st.column_config.NumberColumn("Valor mínimo",    format="$%,.0f"),
            },
        )

        # Bar chart: cartera vs SPY
        fig_stress = go.Figure()
        names   = [r.scenario.name.split("—")[0].strip() for r in stress_results]
        port_dd = [r.portfolio_drawdown_pct for r in stress_results]
        spy_dd  = [r.benchmark_drawdown_pct  for r in stress_results]
        fig_stress.add_trace(go.Bar(
            name="Cartera actual", x=names, y=port_dd,
            marker_color="#17A2B8",
            text=[f"{v:.1f}%" for v in port_dd], textposition="outside",
        ))
        fig_stress.add_trace(go.Bar(
            name="SPY (benchmark)", x=names, y=spy_dd,
            marker_color="#DC3545",
            text=[f"{v:.1f}%" for v in spy_dd], textposition="outside",
        ))
        fig_stress.update_layout(
            barmode="group",
            title="Caída máxima por escenario: Cartera vs SPY",
            yaxis_title="Caída % (negativo = pérdida)",
            yaxis_tickformat=".0f%",
            height=440,
            legend=dict(yanchor="bottom", y=0.01, xanchor="right", x=0.99),
        )
        st.plotly_chart(fig_stress, width="stretch")

        # Recovery timeline bar chart
        fig_recov = go.Figure()
        fig_recov.add_trace(go.Bar(
            x=names,
            y=[r.recovery_years_est for r in stress_results],
            marker_color=[
                "#DC3545" if r.recovery_years_est >= 5 else
                "#FFC107" if r.recovery_years_est >= 2 else
                "#28A745"
                for r in stress_results
            ],
            text=[f"{r.recovery_years_est:.1f}a" for r in stress_results],
            textposition="outside",
        ))
        fig_recov.update_layout(
            title="Tiempo estimado de recuperación al pico anterior",
            yaxis_title="Años",
            height=320,
            showlegend=False,
        )
        st.plotly_chart(fig_recov, width="stretch")

        # Sector detail for worst scenario
        worst = stress_results[0]
        with st.expander(f"📊 Detalle por sector — {worst.scenario.name}"):
            st.markdown(f"**Descripción:** {worst.scenario.description}")
            sec_df = pd.DataFrame([
                {
                    "Sector":         s,
                    "Shock %":        v,
                    "Peso cartera %": round(sector_weights.get(s, 0), 1),
                    "Impacto %":      round(v * sector_weights.get(s, 0) / 100, 1),
                }
                for s, v in sorted(worst.sector_impact.items(), key=lambda x: x[1])
            ])
            st.dataframe(
                sec_df, width="stretch", hide_index=True,
                column_config={
                    "Shock %":        st.column_config.NumberColumn("Shock %",        format="%.1f%%"),
                    "Peso cartera %": st.column_config.NumberColumn("Peso cartera %", format="%.1f%%"),
                    "Impacto %":      st.column_config.NumberColumn("Impacto %",      format="%.1f%%"),
                },
            )

        # Export stress test
        _stress_csv = io.StringIO()
        df_stress.to_csv(_stress_csv, index=False)
        st.download_button(
            label="⬇️ Exportar stress test a CSV",
            data=_stress_csv.getvalue(),
            file_name="stress_test.csv",
            mime="text/csv",
        )
        st.caption(
            "Los shocks son estimaciones calibradas con datos históricos reales. "
            "⚠️ No constituye asesoramiento financiero."
        )

# ================================================================== #
#  Tab 3: Escenario personalizado                                     #
# ================================================================== #

def _tab_custom_content():
    st.subheader("Crear escenario personalizado")
    st.caption("Definí una caída uniforme y calculá el impacto sobre tu portafolio.")

    c1, c2, c3 = st.columns(3)
    custom_drop     = c1.slider("Caída del mercado (%)", min_value=-80, max_value=-5, value=-30, step=5)
    custom_months   = c2.slider("Duración (meses)",              min_value=1,  max_value=36,  value=12)
    custom_recovery = c3.slider("Recuperación estimada (meses)", min_value=6,  max_value=120, value=36)

    if st.button("📊 Calcular impacto", type="primary"):
        if not sector_weights:
            st.warning("Necesitás pesos por sector. Ejecuta el Optimizer primero.")
        else:
            from portfolio.stress_test import StressTester
            r = StressTester.custom_scenario(
                name="Escenario personalizado",
                equity_shock_pct=float(custom_drop),
                duration_months=custom_months,
                recovery_months=custom_recovery,
                sector_weights=sector_weights,
                initial_value=float(initial_value),
            )
            cc1, cc2, cc3, cc4 = st.columns(4)
            cc1.metric("Caída cartera",     f"{r.portfolio_drawdown_pct:.1f}%",   delta_color="inverse")
            cc2.metric("Pérdida USD",       f"${abs(r.portfolio_loss_usd):,.0f}", delta_color="inverse")
            cc3.metric("Valor mínimo",      f"${r.portfolio_trough_value:,.0f}")
            cc4.metric("Recuperación est.", f"{r.recovery_years_est:.1f} años")

            st.progress(
                min(int(abs(r.portfolio_drawdown_pct)), 100),
                text=f"Severidad: {abs(r.portfolio_drawdown_pct):.1f}% de caída",
            )

            # Mini fan chart post-crash recovery
            _recovery_years = [0, 1, 2, 3, int(r.recovery_years_est) + 1]
            _values = [
                r.portfolio_trough_value,
                r.portfolio_trough_value * 1.08,
                r.portfolio_trough_value * 1.08**2,
                r.portfolio_trough_value * 1.08**3,
                float(initial_value),
            ]
            fig_recov_path = go.Figure()
            fig_recov_path.add_trace(go.Scatter(
                x=_recovery_years, y=_values,
                mode="lines+markers",
                line=dict(color="#17A2B8", width=2),
                name="Recuperación estimada (8% p.a.)",
            ))
            fig_recov_path.add_hline(
                y=initial_value, line_dash="dash", line_color="gold",
                annotation_text="Capital original", annotation_position="right",
            )
            fig_recov_path.update_layout(
                title="Camino de recuperación estimado (8% anual desde el piso)",
                xaxis_title="Años desde el piso",
                yaxis_tickformat="$,.0f",
                height=300,
            )
            st.plotly_chart(fig_recov_path, width="stretch")

# ================================================================== #
#  Tab dispatch: Stress + Escenario personalizado                     #
# ================================================================== #

with tab_stress:
    _tab_stress_content()

with tab_custom:
    _tab_custom_content()

# ================================================================== #
#  Tab 4: Comparar Perfiles                                           #
# ================================================================== #


def _tab_compare_content():
    st.subheader("🔀 Cómo afecta el perfil de riesgo a las proyecciones")
    st.caption(
        "Compara Conservador / Moderado / Agresivo usando los **mismos activos** "
        "pero con distintos supuestos de retorno y volatilidad. "
        "Conservador = más haircut al retorno histórico y más volatilidad simulada; "
        "Agresivo = menos penalización."
    )

    run_compare = st.button("▶ Comparar los 3 perfiles", type="primary", key="run_compare_profiles")

    if not run_compare and "mc_compare_results" not in st.session_state:
        st.info(
            "Presioná **▶ Comparar los 3 perfiles** para ver cómo cambian las "
            "proyecciones según el perfil de riesgo.",
            icon="🔀",
        )
        return

    if run_compare:
        _compare_mc: dict = {}
        _compare_prog = st.progress(0.0)
        for _ci, (_pk, _scales) in enumerate(_PROFILE_MC_SCALES.items()):
            _compare_prog.progress((_ci + 1) / 3, text=f"Simulando perfil {_pk}…")
            _compare_mc[_pk] = cached_monte_carlo(
                symbols=tuple(symbols),
                weights_tuple=tuple(weights) if weights else None,
                horizon_years=horizon_years,
                n_sims=n_sims,
                initial_value=float(initial_value),
                annual_withdrawal=float(annual_withdrawal),
                target_value=float(target_value),
                withdrawal_growth_rate=float(inflation_rate) / 100.0,
                vol_scale=_scales["vol_scale"],
                return_scale=_scales["return_scale"],
            )
        _compare_prog.empty()
        st.session_state["mc_compare_results"] = _compare_mc
        st.session_state["mc_compare_horizon"]  = horizon_years

    compare_mc = st.session_state.get("mc_compare_results", {})
    if not compare_mc:
        return

    _stored_horizon = st.session_state.get("mc_compare_horizon", horizon_years)
    if _stored_horizon != horizon_years:
        st.warning(
            f"Los resultados de comparación son para {_stored_horizon} años. "
            "Presioná **Comparar** para actualizar."
        )

    # ---- KPI comparison table ----
    # U1-7: los tres perfiles comparten el mismo esquema de flujos (sale del
    # mismo sidebar), así que la columna tiene un solo rótulo para las 3 filas.
    _cmp_flows = any(mc_has_cash_flows(_mc) for _mc in compare_mc.values())
    _cmp_growth_col = f"{pot_growth_column_label(_cmp_flows)} (P50)"
    cmp_rows = []
    for _pk, _mc in compare_mc.items():
        _pname = _PROFILE_NAMES_MC[_pk]
        cmp_rows.append({
            "Perfil":     _pname,
            "P10 (USD)":  _mc.p10_terminal,
            "P50 (USD)":  _mc.median_terminal,
            "P90 (USD)":  _mc.p90_terminal,
            _cmp_growth_col: _mc.median_cagr_pct,
            "Prob. ruina %": _mc.prob_ruin_pct,
            "Prob. meta %":  _mc.prob_achieve_target_pct if target_value > 0 else None,
        })
    _cmp_df = pd.DataFrame(cmp_rows)
    _cmp_col_cfg = {
        "P10 (USD)":     st.column_config.NumberColumn("P10 (USD)",     format="$%,.0f"),
        "P50 (USD)":     st.column_config.NumberColumn("P50 (USD)",     format="$%,.0f"),
        "P90 (USD)":     st.column_config.NumberColumn("P90 (USD)",     format="$%,.0f"),
        _cmp_growth_col: st.column_config.NumberColumn(
            _cmp_growth_col, format="%.1f%%", help=pot_growth_help(_cmp_flows)
        ),
        "Prob. ruina %": st.column_config.NumberColumn("Prob. ruina %", format="%.1f%%"),
    }
    if target_value > 0:
        _cmp_col_cfg["Prob. meta %"] = st.column_config.NumberColumn(
            f"Prob. meta ${target_value:,.0f}", format="%.1f%%"
        )
    st.dataframe(_cmp_df, width="stretch", hide_index=True, column_config=_cmp_col_cfg)

    # ---- Fan chart overlay: median + P10/P90 per profile ----
    _years = list(range(0, horizon_years + 1))

    fig_cmp = go.Figure()
    for _pk, _mc in compare_mc.items():
        if not _mc.fan_paths:
            continue
        _color = _PROFILE_COLORS_MC[_pk]
        _name  = _PROFILE_NAMES_MC[_pk]

        # Shaded P25-P75 band
        _lo = [_mc.fan_paths[y].get(25, 0) for y in _years]
        _hi = [_mc.fan_paths[y].get(75, 0) for y in _years]
        fig_cmp.add_trace(go.Scatter(
            x=_years + _years[::-1],
            y=_hi + _lo[::-1],
            fill="toself",
            fillcolor=_color.replace(")", ", 0.12)").replace("rgb", "rgba") if "rgb" in _color else f"rgba({int(_color[1:3],16)},{int(_color[3:5],16)},{int(_color[5:7],16)},0.10)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip",
            showlegend=False,
        ))
        # Median line
        fig_cmp.add_trace(go.Scatter(
            x=_years,
            y=[_mc.fan_paths[y][50] for y in _years],
            mode="lines",
            line=dict(color=_color, width=2.5),
            name=f"{_name} (P50)",
        ))

    if target_value > 0:
        fig_cmp.add_hline(
            y=target_value, line_dash="dash", line_color="gold", line_width=2,
            annotation_text=f"Meta ${target_value:,.0f}",
            annotation_position="right",
        )
    fig_cmp.update_layout(
        title=f"Proyección mediana por perfil — {horizon_years} años ({n_sims:,} sims)",
        xaxis_title="Años desde hoy",
        yaxis_title="Valor del portafolio (USD)",
        yaxis_tickformat="$,.0f",
        height=500,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        hovermode="x unified",
    )
    st.plotly_chart(fig_cmp, width="stretch")

    # ---- P10 comparison (downside risk) ----
    fig_p10 = go.Figure()
    for _pk, _mc in compare_mc.items():
        if not _mc.fan_paths:
            continue
        fig_p10.add_trace(go.Scatter(
            x=_years,
            y=[_mc.fan_paths[y][10] for y in _years],
            mode="lines",
            line=dict(color=_PROFILE_COLORS_MC[_pk], width=2, dash="dot"),
            name=f"{_PROFILE_NAMES_MC[_pk]} (P10)",
        ))
    fig_p10.update_layout(
        title="Escenario pesimista (P10) por perfil — riesgo de baja",
        xaxis_title="Años",
        yaxis_title="USD",
        yaxis_tickformat="$,.0f",
        height=350,
        hovermode="x unified",
    )
    st.plotly_chart(fig_p10, width="stretch")

    st.caption(
        "⚠️ Los perfiles NO cambian los activos ni los pesos — solo ajustan los supuestos "
        "de retorno y volatilidad. Para comparar con pesos distintos, ejecutá el Optimizer "
        "con cada perfil y volvé a correr la simulación."
    )

    # Export
    _cmp_csv = io.StringIO()
    _cmp_df.to_csv(_cmp_csv, index=False)
    st.download_button(
        label="⬇️ Exportar comparación a CSV",
        data=_cmp_csv.getvalue(),
        file_name=f"perfil_comparison_{horizon_years}y.csv",
        mime="text/csv",
    )

# ================================================================== #
#  Tab 5: Mis Metas (Multi-Goal Planner)                              #


with tab_compare:
    _tab_compare_content()

# ================================================================== #

def _tab_goals_content():
    st.subheader("🏆 Planificador de Metas Financieras")
    st.caption(
        "Definí múltiples metas de inversión (casa, independencia financiera, retiro) "
        "y simulá el plan completo con Monte Carlo independiente por meta. "
        "El capital se asigna automáticamente según prioridad, o podés definirlo manualmente."
    )

    # ---- Session state init for goals list ----
    if "goals_list" not in st.session_state:
        st.session_state["goals_list"] = []

    # ---- Goal form defaults (state-controlled widgets) ----
    # These keys may already be seeded from the personal profile (top of file,
    # onboarded users only). Ensure a sensible value exists for everyone so the
    # keyed widgets below can be declared WITHOUT a `value=` arg — declaring both
    # `value=` and a pre-set session_state value triggers Streamlit's widget
    # policy warning ("created with a default value but also had its value set
    # via the Session State API"). See plan_mode fix 2026-06-13.
    st.session_state.setdefault("new_goal_horizon", 5)
    st.session_state.setdefault("new_goal_contribution", 0)
    st.session_state.setdefault("new_goal_allocated", 0)

    # ---------------------------------------------------------------- #
    #  Goal editor                                                       #
    # ---------------------------------------------------------------- #

    with st.expander("➕ Agregar nueva meta", expanded=len(st.session_state["goals_list"]) == 0):
        # Row 1: Tipo de meta (first) + Nombre + Prioridad
        gr1, gr2, gr3 = st.columns([2, 3, 2])
        new_goal_type = gr1.selectbox(
            "Tipo de meta",
            options=list(GOAL_TYPE_ICONS.keys()),
            format_func=lambda k: f"{GOAL_TYPE_ICONS[k]} {GOAL_TYPE_LABELS[k]}",
            key="new_goal_type",
        )
        _placeholder = GOAL_TYPE_PLACEHOLDERS.get(new_goal_type, "ej: Meta personalizada")
        new_name = gr2.text_input(
            "Nombre de la meta",
            placeholder=_placeholder,
            key="new_goal_name",
        )
        new_priority = gr3.selectbox(
            "Prioridad",
            options=[1, 2, 3],
            format_func=lambda p: f"{PRIORITY_EMOJIS[p]} {PRIORITY_LABELS[p]}",
            key="new_goal_priority",
        )

        # Row 2: Monto + Horizonte + Inflación
        gc3, gc4, gc5 = st.columns(3)
        new_target = gc3.number_input(
            "Meta (USD de hoy)",
            min_value=1_000, max_value=10_000_000, value=300_000, step=10_000,
            format="%d",
            help="Cuánto necesitás en dólares de HOY. Se ajusta automáticamente por inflación.",
            key="new_goal_target",
        )
        new_horizon = gc4.number_input(
            "Horizonte (años)",
            min_value=1, max_value=40, step=1,
            key="new_goal_horizon",
        )
        new_inflation = gc5.slider(
            "Inflación esperada (%/año)",
            min_value=0.0, max_value=8.0, value=3.0, step=0.5,
            key="new_goal_inflation",
        )

        # Row 3: Avanzado (expandible para no abrumar al usuario)
        with st.expander("⚙️ Configuración avanzada (aportes, capital asignado, notas)"):
            gc6, gc7, gc8 = st.columns(3)
            new_contribution = gc6.number_input(
                "Aporte anual hacia esta meta (USD)",
                min_value=0, max_value=500_000, step=1_000,
                format="%d",
                help="Cuánto ahorrás por año específicamente para esta meta. 0 = solo crece el capital inicial.",
                key="new_goal_contribution",
            )
            new_allocated = gc7.number_input(
                "Capital asignado (USD, 0 = auto)",
                min_value=0, max_value=10_000_000, step=5_000,
                format="%d",
                help="Capital inicial para esta meta. 0 = se asigna automáticamente proporcional a prioridad.",
                key="new_goal_allocated",
            )
            new_notes = gc8.text_input(
                "Notas (opcional)",
                placeholder="ej: Para dar el down payment",
                key="new_goal_notes",
            )

        # Live preview with icon
        _icon = GOAL_TYPE_ICONS.get(new_goal_type, "💼")
        if new_target > 0 and new_horizon > 0:
            nominal_preview = new_target * (1 + new_inflation / 100) ** new_horizon
            _display_name = new_name.strip() or _placeholder
            st.info(
                f"{_icon} **{_display_name}** — "
                f"\\${new_target:,.0f} hoy → **\\${nominal_preview:,.0f} nominal** "
                f"en {new_horizon} año{'s' if new_horizon != 1 else ''} "
                f"({new_inflation:.1f}% inf./año)",
                icon="📊",
            )

        if st.button("✅ Agregar meta al plan", type="primary", key="add_goal_btn"):
            _final_name = new_name.strip() or _placeholder
            new_goal = {
                "name": _final_name,
                "goal_type": new_goal_type,
                "target_amount_today": float(new_target),
                "horizon_years": int(new_horizon),
                "priority": int(new_priority),
                "expected_inflation": float(new_inflation),
                "annual_contribution": float(new_contribution),
                "allocated_capital": float(new_allocated),
                "notes": new_notes.strip(),
            }
            st.session_state["goals_list"].append(new_goal)
            st.success(f"✅ Meta **{_icon} {_final_name}** agregada al plan.")
            st.rerun()

    # ---- Display current goals with reorder buttons ----
    goals_list = st.session_state["goals_list"]

    if not goals_list:
        st.info(
            "Todavía no tenés metas definidas. Usá el formulario de arriba para agregar tu primera meta.\n\n"
            "**Ejemplos de metas típicas:**\n"
            "- 🏠 Casa en 2028 — $300.000 (hoy), horizonte 3 años, prioridad alta\n"
            "- 💸 FIRE 2035 — $1.500.000 (hoy), horizonte 9 años, prioridad alta\n"
            "- 🌴 Retiro a los 65 — $2.000.000 (hoy), horizonte 20 años, prioridad media",
            icon="🎯",
        )
    else:
        st.markdown(f"**{len(goals_list)} meta(s) definida(s):**")

        for i, g in enumerate(goals_list):
            g_icon  = GOAL_TYPE_ICONS.get(g.get("goal_type", "otro"), "💼")
            p_emoji = PRIORITY_EMOJIS.get(g["priority"], "🟡")
            p_label = PRIORITY_LABELS.get(g["priority"], "Media")
            p_color = PRIORITY_COLORS.get(g["priority"], "#FFC107")
            nominal = g["target_amount_today"] * (1 + g["expected_inflation"] / 100) ** g["horizon_years"]

            with st.container(border=True):
                # Barra lateral de color según prioridad + contenido
                st.markdown(
                    f"<div style='border-left:5px solid {p_color};padding-left:10px;'>",
                    unsafe_allow_html=True,
                )
                c_icon, c_info, c_btns = st.columns([1, 9, 2])
                with c_icon:
                    st.markdown(
                        f"<div style='font-size:2.2em;text-align:center;line-height:1.2'>{g_icon}</div>",
                        unsafe_allow_html=True,
                    )
                with c_info:
                    st.markdown(
                        f"**{g['name']}** &nbsp;"
                        f"<span style='background:{p_color}22;border:1px solid {p_color};color:{p_color};"
                        f"padding:2px 8px;border-radius:10px;font-size:0.75em;font-weight:700'>"
                        f"{p_emoji} {p_label}</span>",
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"\\${g['target_amount_today']:,.0f} hoy → \\${nominal:,.0f} nominal "
                        f"· {g['horizon_years']} años · aporte \\${g['annual_contribution']:,.0f}/año"
                        + (f" · _{g['notes']}_" if g.get("notes") else "")
                    )
                with c_btns:
                    _b1, _b2, _b3 = st.columns(3)
                    if i > 0:
                        if _b1.button("⬆️", key=f"up_{i}", help="Subir prioridad"):
                            goals_list[i - 1], goals_list[i] = goals_list[i], goals_list[i - 1]
                            st.rerun()
                    if i < len(goals_list) - 1:
                        if _b2.button("⬇️", key=f"dn_{i}", help="Bajar prioridad"):
                            goals_list[i], goals_list[i + 1] = goals_list[i + 1], goals_list[i]
                            st.rerun()
                    if _b3.button("🗑️", key=f"del_goal_{i}", help=f"Eliminar '{g['name']}'"):
                        st.session_state["goals_list"].pop(i)
                        st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

        _col_clear, _col_opt = st.columns([1, 2])
        if _col_clear.button("🗑️ Limpiar todas las metas", key="clear_all_goals"):
            st.session_state["goals_list"] = []
            st.session_state.pop("goal_optimizer_result", None)
            st.session_state.pop("goal_optimizer_explanation", None)
            st.rerun()

        _has_scored = bool(st.session_state.get("optimizer_scored"))
        _opt_btn = _col_opt.button(
            "🔬 Optimizar para mis metas",
            key="optimize_for_goals_btn",
            disabled=not _has_scored,
            help=(
                "Optimiza el portafolio considerando el horizonte de cada meta (Glide Path automático)."
                if _has_scored
                else "Para optimizar con metas, primero ejecutá el Optimizer en la pestaña 📈 Optimizer."
            ),
        )

        if _opt_btn and _has_scored:
            _scored = st.session_state["optimizer_scored"]
            _profile = st.session_state.get("plan_profile", "conservative")
            _opt_current = st.session_state.get("optimizer_result") or st.session_state.get("optimizer_prev_result")
            _cur_w = (
                tuple((t.symbol, t.weight_pct) for t in _opt_current.tickers)
                if _opt_current and _opt_current.tickers else None
            )
            with st.spinner("Optimizando portafolio para tus metas…"):
                _goal_result, _goal_explanation = cached_goal_optimization(
                    scored_tickers_tuple=tuple(
                        {k: v for k, v in s.items()} for s in _scored
                    ),
                    goals_serialized=tuple({k: v for k, v in g.items()} for g in goals_list),
                    profile_key=_profile,
                    current_weights_tuple=_cur_w,
                )
            st.session_state["goal_optimizer_result"] = _goal_result
            st.session_state["goal_optimizer_explanation"] = _goal_explanation
            st.rerun()

        # ---- Goal optimizer comparison UI ----
        if "goal_optimizer_result" in st.session_state:
            _goal_res = st.session_state["goal_optimizer_result"]
            _goal_exp = st.session_state.get("goal_optimizer_explanation", "")
            _base_res = st.session_state.get("optimizer_result") or st.session_state.get("optimizer_prev_result")

            st.divider()
            st.subheader("🎯 Portafolio optimizado para tus metas")
            st.info(_goal_exp, icon="🛡️")

            # Key metrics comparison
            _mc1, _mc2, _mc3, _mc4 = st.columns(4)
            _mc1.metric(
                "Volatilidad esperada",
                f"{_goal_res.volatility_pct:.1f}%",
                delta=f"{_goal_res.volatility_pct - _base_res.volatility_pct:+.1f}% vs base" if _base_res else None,
                delta_color="inverse",
            )
            _mc2.metric(
                PROXY_INDEX_LABEL,
                fmt_attractiveness_index(_goal_res.expected_return_pct),
                delta=_fmt_idx_delta(_goal_res.expected_return_pct, _base_res.expected_return_pct) if _base_res else None,
                help=PROXY_RETURN_HELP,
            )
            _mc3.metric(
                PROXY_RATIO_LABEL,
                f"{_goal_res.sharpe_ratio:.2f}",
                delta=f"{_goal_res.sharpe_ratio - _base_res.sharpe_ratio:+.2f} vs base" if _base_res else None,
                help=PROXY_RATIO_HELP,
            )
            _mc4.metric(
                "Div Yield",
                f"{_goal_res.dividend_yield_pct:.1f}%",
                delta=f"{_goal_res.dividend_yield_pct - _base_res.dividend_yield_pct:+.1f}% vs base" if _base_res else None,
            )

            # Allocation comparison table
            st.markdown("**Comparación de asignación**")
            _base_weights = (
                {t.symbol: t.weight_pct for t in _base_res.tickers} if _base_res else {}
            )
            _goal_weights = {t.symbol: t.weight_pct for t in _goal_res.tickers}
            _all_symbols = sorted(
                set(_base_weights) | set(_goal_weights),
                key=lambda s: -_goal_weights.get(s, 0),
            )

            _rows = []
            for sym in _all_symbols:
                base_w = _base_weights.get(sym, 0.0)
                goal_w = _goal_weights.get(sym, 0.0)
                delta = goal_w - base_w
                if abs(delta) >= 0.05 or goal_w > 0:
                    arrow = "↑" if delta > 0.5 else ("↓" if delta < -0.5 else "→")
                    _rows.append({
                        "Ticker": sym,
                        "Base %": f"{base_w:.1f}%" if base_w else "—",
                        "Metas %": f"{goal_w:.1f}%" if goal_w else "—",
                        "Cambio": f"{arrow} {delta:+.1f}%",
                    })

            if _rows:
                _df_cmp = pd.DataFrame(_rows)
                st.dataframe(_df_cmp, width="stretch", hide_index=True)

            # Apply button
            st.divider()
            _a1, _a2 = st.columns([2, 1])
            with _a1:
                st.caption(
                    "Al aplicar, este portafolio reemplaza el resultado del Optimizer "
                    "y se usa en todas las simulaciones de esta sesión."
                )
            with _a2:
                if st.button("✅ Aplicar portafolio para mis metas", type="primary", key="apply_goal_optimizer"):
                    if _base_res:
                        st.session_state["optimizer_prev_result"] = _base_res
                    st.session_state["optimizer_result"] = _goal_res
                    st.toast("✅ Portafolio optimizado para tus metas aplicado", icon="🎯")
                    st.rerun()

    # ---------------------------------------------------------------- #
    #  Simulation controls                                               #
    # ---------------------------------------------------------------- #
    if goals_list:
        st.divider()
        st.subheader("⚙️ Parámetros del plan")

        gp1, gp2, gp3 = st.columns(3)
        plan_total_capital = gp1.number_input(
            "Capital total disponible para el plan (USD)",
            min_value=1_000, max_value=20_000_000, value=500_000, step=10_000,
            format="%d",
            help="Capital total que se distribuirá entre todas las metas según prioridad.",
            key="plan_total_capital",
        )
        plan_n_sims = gp2.select_slider(
            "Simulaciones por meta",
            options=[1_000, 2_000, 5_000, 10_000],
            value=5_000,
            key="plan_n_sims",
        )
        plan_profile = gp3.selectbox(
            "Perfil de riesgo",
            options=["conservative", "moderate", "aggressive"],
            format_func=lambda p: {"conservative": "🛡️ Conservador", "moderate": "⚖️ Moderado", "aggressive": "🚀 Agresivo"}[p],
            key="plan_profile",
        )

        _PLAN_MC_SCALES = {
            "conservative": {"vol_scale": 1.15, "return_scale": 0.70},
            "moderate":     {"vol_scale": 1.10, "return_scale": 0.80},
            "aggressive":   {"vol_scale": 1.00, "return_scale": 0.95},
        }
        plan_scales = _PLAN_MC_SCALES[plan_profile]

        # ---- Run simulation ----
        run_plan = st.button("▶ Simular plan completo", type="primary", key="run_goal_plan")

        if run_plan or "goal_plan_result" in st.session_state:
            if run_plan:
                if not (opt_result and opt_result.tickers):
                    st.warning(
                        "⚠️ No hay portafolio optimizado en sesión. El plan usará el universo equal-weight. "
                        "Para resultados más precisos, generá un portafolio en 📈 Optimizer primero.",
                        icon="⚠️",
                    )
                with st.spinner(f"Simulando {len(goals_list)} meta(s) con {plan_n_sims:,} simulaciones c/u…"):
                    goals_serialized = tuple(
                        {k: v for k, v in g.items()} for g in goals_list
                    )
                    plan_result = cached_goal_simulation(
                        symbols=tuple(symbols),
                        weights_tuple=tuple(weights) if weights else None,
                        goals_serialized=goals_serialized,
                        total_capital=float(plan_total_capital),
                        n_sims=plan_n_sims,
                        vol_scale=plan_scales["vol_scale"],
                        return_scale=plan_scales["return_scale"],
                    )
                st.session_state["goal_plan_result"] = plan_result

            plan_result = st.session_state.get("goal_plan_result")
            if plan_result is None:
                pass  # unreachable guard

            # ---------------------------------------------------------------- #
            #  Plan summary KPIs                                                #
            # ---------------------------------------------------------------- #
            st.divider()
            st.subheader("📊 Resumen del plan")

            pk1, pk2, pk3, pk4 = st.columns(4)
            pk1.metric(
                "Capital total asignado",
                f"${plan_result.total_capital_allocated:,.0f}",
                help="Suma del capital asignado a todas las metas.",
            )
            pk2.metric(
                "Viabilidad del plan",
                f"{plan_result.plan_feasibility_score:.0f}/100",
                delta=plan_result.feasibility_label,
                delta_color="off",
                delta_arrow="off",
                help="Score ponderado por prioridad: P(éxito) × peso de prioridad.",
            )
            _success_target = GOAL_CARD.success_target_pct
            pk3.metric(
                f"Metas con >{_success_target:.0f}% prob. éxito",
                f"{sum(1 for gr in plan_result.goal_results if gr.prob_success_pct >= _success_target)}"
                f"/{len(plan_result.goal_results)}",
            )
            capital_gap = plan_result.capital_gap_today
            pk4.metric(
                "Gap de capital (en USD de hoy)",
                f"${capital_gap:,.0f}" if capital_gap > 0 else "✅ Sin gap",
                delta="déficit proyectado" if capital_gap > 0 else None,
                delta_color="inverse" if capital_gap > 0 else "off",
                delta_arrow="off",
                help=(
                    "Lo que falta para alcanzar cada meta, medido contra la mediana "
                    "proyectada y traído a **dólares de hoy** con la inflación de cada "
                    "meta.\n\nSe deflacta meta por meta *antes* de sumar: una meta a 25 "
                    "años y otra a 5 años están en años distintos, y sumar sus montos "
                    "nominales no da una cifra (U5-13)."
                ),
            )

            # Plan-level warnings
            for w in plan_result.warnings:
                st.warning(w)

            # ---------------------------------------------------------------- #
            #  Per-goal results cards                                           #
            # ---------------------------------------------------------------- #
            st.subheader("🎯 Resultados por meta")

            for gr in plan_result.goal_results:
                goal = gr.goal
                mc = gr.mc_result
                p_color = goal.priority_color
                p_emoji = goal.priority_emoji
                p_label = goal.priority_label
                g_icon  = goal.icon

                # SORR Risk Score — regla y tooltip salen de la misma fuente
                # (portfolio/goals.py + GOAL_CARD), así no pueden divergir.
                sorr_badge, sorr_color = sorr_risk_badge(
                    mc.sorr_early_drawdown_pct, mc.median_max_drawdown_pct
                )

                # Una meta que solo recibe aportes no tiene retiros con los que
                # colisionar, y su "CAGR" no es un retorno: el capital aportado
                # entra en el terminal pero no en el inicial.
                _aporte_mensual = goal.annual_contribution / 12.0
                _con_aportes = _aporte_mensual > 0
                _total_aportado = goal.annual_contribution * goal.horizon_years

                with st.container(border=True):
                    # Header: icon + name + priority badge + horizon
                    h1, h2 = st.columns([4, 1])
                    h1.markdown(
                        f"### {g_icon} {goal.name} &nbsp;"
                        f"<span style='background:{p_color}22;border:1px solid {p_color};color:{p_color};"
                        f"padding:2px 10px;border-radius:12px;font-size:0.75em;font-weight:700;'>"
                        f"{p_emoji} {p_label}</span>",
                        unsafe_allow_html=True,
                    )
                    h2.markdown(f"**{goal.horizon_years} años** · {goal.type_label}")

                    # KPI row
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Capital asignado", f"${gr.allocated_capital:,.0f}")
                    m2.metric(
                        "Meta nominal",
                        f"${gr.target_nominal:,.0f}",
                        delta=f"${goal.target_amount_today:,.0f} hoy + {goal.expected_inflation:.1f}% inf.",
                        delta_color="off",
                        delta_arrow="off",
                    )
                    m3.metric(
                        "Prob. éxito",
                        f"{gr.prob_success_pct:.1f}%",
                        delta=gr.feasibility_label,
                        delta_color="off",
                        delta_arrow="off",
                    )
                    # Con aportes, `median_cagr_pct` deja de ser un retorno (el
                    # capital aportado infla el terminal sin estar en el inicial),
                    # así que ahí se informa cuánto se aportó, no un "CAGR".
                    m4.metric(
                        "Mediana proyectada",
                        f"${gr.median_terminal:,.0f}",
                        delta=(
                            f"incl. ${_total_aportado:,.0f} aportados"
                            if _con_aportes else
                            pot_growth_delta(mc.median_cagr_pct, False)
                        ),
                        delta_color="off",
                        delta_arrow="off",
                        help=(
                            "Aportás "
                            f"${_aporte_mensual:,.0f}/mes durante {goal.horizon_years} años.\n\n"
                            + pot_growth_help(True)
                        ) if _con_aportes else pot_growth_help(False),
                    )
                    m5.metric(
                        "Pesimista (P10)",
                        f"${mc.p10_terminal:,.0f}",
                        delta=(
                            "peor 10% de las simulaciones"
                            if _con_aportes else
                            pot_growth_delta(mc.p10_cagr_pct, False)
                        ),
                        delta_color="off",
                        delta_arrow="off",
                    )

                    # Progreso estimado (si hay valor del portfolio actual en sesión)
                    _port_val = st.session_state.get("portfolio_current_value", 0.0)
                    if _port_val > 0 and gr.target_nominal > 0:
                        _pct_prog = min(_port_val / gr.target_nominal * 100, 100)
                        _prog_col1, _prog_col2 = st.columns([1, 5])
                        _prog_col1.metric(
                            "Progreso actual",
                            f"{_pct_prog:.0f}%",
                            help="Portfolio actual vs. meta nominal ajustada por inflación.",
                        )
                        with _prog_col2:
                            st.caption("📈 Avance hacia la meta nominal")
                            st.progress(
                                _pct_prog / 100,
                                text=f"\\${_port_val:,.0f} de \\${gr.target_nominal:,.0f}",
                            )

                    st.divider()

                    # SORR section header with badge
                    _sorr_col_badge, _sorr_col_title = st.columns([1.5, 4.5])
                    # NUNCA combinar unsafe_allow_html=True con help= en el mismo
                    # st.markdown: Streamlit concatena " :help[]" al final del
                    # markdown y el bloque HTML se lo traga como texto crudo
                    # (CommonMark: un bloque HTML tipo 6 corre hasta una línea en
                    # blanco). El tooltip va en su propio elemento.
                    _sorr_col_badge.markdown(
                        f"<div style='background:{sorr_color}22;border:2px solid {sorr_color};"
                        f"border-radius:12px;padding:14px 8px;text-align:center;"
                        f"font-weight:700;font-size:1.8em;color:{sorr_color};line-height:1.3'>"
                        f"SORR<br>{sorr_badge}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    _sorr_col_badge.caption(
                        "¿Qué es SORR?",
                        help=sorr_badge_tooltip(is_accumulation=_con_aportes),
                    )
                    with _sorr_col_title:
                        ds1, ds2, ds3, ds4 = st.columns(4)
                        ds1.metric(
                            "Drawdown máx. mediano",
                            f"{mc.median_max_drawdown_pct:.1f}%",
                            delta=f"peor momento: años {mc.p25_year_of_max_dd:.0f}–{mc.p75_year_of_max_dd:.0f}",
                            delta_color="off",
                            delta_arrow="off",
                            help="Caída pico-a-valle mediana **del mercado** durante todo el "
                                 "horizonte: no incluye aportes ni retiros. "
                                 "El rango marca dónde cae el 50% central de los peores drawdowns: "
                                 "si es ancho, el momento del golpe es esencialmente impredecible.",
                        )
                        ds2.metric(
                            "Riesgo SORR (5a)",
                            f"{mc.sorr_early_drawdown_pct:.1f}%",
                            help="% de simulaciones con caída de **mercado** >30% en los "
                                 "**primeros 5 años** (sin contar aportes ni retiros). "
                                 + (
                                     "En una meta de acumulación, aportar caro justo antes de la "
                                     "caída deja capital que tarda años en recuperarse."
                                     if _con_aportes else
                                     "Una secuencia negativa temprana puede ser devastadora si "
                                     "coincide con retiros."
                                 ),
                        )
                        ds3.metric(
                            "Paths caída ≥50%",
                            f"{mc.pct_paths_severe_drawdown:.1f}%",
                            help="% de simulaciones que en algún momento caen 50% o más desde su pico. "
                                 "Mide la cola extrema del riesgo.",
                            delta_color="inverse",
                        )
                        ds4.metric(
                            "Mínimo P10 intra-horizonte",
                            f"${mc.p10_intra_min:,.0f}",
                            help="En el peor 10% de simulaciones, el portafolio llega a este valor "
                                 "mínimo en algún momento del horizonte. A diferencia de las métricas "
                                 "de drawdown, éste **sí** descuenta retiros y costos: es el piso real "
                                 "de tu plata.",
                        )

                    # Mini fan chart with P5-P10 highlight + vertical line of max drawdown year
                    if mc.fan_paths and len(mc.years) > 1:
                        _yrs = mc.years
                        fig_g = go.Figure()

                        # Worst-10% band: P5–P10 (más opaco, rojo)
                        if 5 in mc.fan_paths[_yrs[0]]:
                            fig_g.add_trace(go.Scatter(
                                x=_yrs + _yrs[::-1],
                                y=[mc.fan_paths[y][10] for y in _yrs] + [mc.fan_paths[y][5] for y in _yrs[::-1]],
                                fill="toself",
                                fillcolor="rgba(220,53,69,0.40)",
                                line=dict(color="rgba(0,0,0,0)"),
                                hoverinfo="skip",
                                name="Peor 10% (P5–P10)",
                            ))

                        # Main P25-P75 band
                        fig_g.add_trace(go.Scatter(
                            x=_yrs + _yrs[::-1],
                            y=[mc.fan_paths[y][75] for y in _yrs] + [mc.fan_paths[y][25] for y in _yrs[::-1]],
                            fill="toself",
                            fillcolor="rgba(23,162,184,0.10)",
                            line=dict(color="rgba(0,0,0,0)"),
                            hoverinfo="skip",
                            name="P25–P75",
                        ))
                        fig_g.add_trace(go.Scatter(
                            x=_yrs,
                            y=[mc.fan_paths[y][50] for y in _yrs],
                            mode="lines",
                            line=dict(color="#17A2B8", width=2),
                            name="Mediana (P50)",
                        ))
                        fig_g.add_trace(go.Scatter(
                            x=_yrs,
                            y=[mc.fan_paths[y][10] for y in _yrs],
                            mode="lines",
                            line=dict(color="#DC3545", width=1.5, dash="dot"),
                            name="P10",
                            showlegend=False,   # ya está en la leyenda vía la banda P5–P10
                        ))
                        fig_g.add_hline(
                            y=gr.target_nominal,
                            line_dash="dash", line_color="gold", line_width=2,
                            annotation_text=f"Meta ${gr.target_nominal:,.0f}",
                            annotation_position="top right",
                        )
                        # Banda del peor drawdown, NO una línea: la distribución
                        # del año del peor drawdown es casi uniforme, así que su
                        # mediana tiende a horizonte/2 para cualquier cartera.
                        # Un punto preciso comunicaría una certeza que la
                        # simulación no respalda; el rango P25–P75 dice la verdad.
                        if 0 <= mc.p25_year_of_max_dd < mc.p75_year_of_max_dd:
                            fig_g.add_vrect(
                                x0=mc.p25_year_of_max_dd, x1=mc.p75_year_of_max_dd,
                                fillcolor="rgba(220,53,69,0.07)", line_width=0, layer="below",
                                annotation_text="50% central de los peores drawdowns",
                                annotation_position="bottom right",
                                annotation_font_size=10,
                            )

                        # La meta se dibuja en coordenadas de datos, así que entra
                        # en el autorange: si está muy por encima del escenario
                        # optimista, aplasta toda la proyección contra el $0 y el
                        # gráfico deja de informar. En ese caso, escala log.
                        # Contra P75/P5, que son las series efectivamente
                        # dibujadas. Medir contra P95 (que no se traza) haría que
                        # el rango lineal estirara el eje para incluir una cola
                        # invisible, aplastando igual lo que sí se ve.
                        _fan_hi = max(mc.fan_paths[y][75] for y in _yrs)
                        _fan_lo = min(mc.fan_paths[y][5] for y in _yrs)
                        if gr.target_nominal > GOAL_CARD.chart_log_scale_ratio * _fan_hi:
                            fig_g.update_yaxes(
                                type="log",
                                range=[
                                    math.log10(max(_fan_lo * 0.7, 1.0)),
                                    math.log10(max(gr.target_nominal * 1.3, 10.0)),
                                ],
                                # Rotularlo es obligatorio: en log, la pendiente
                                # no se lee como en escala lineal.
                                title_text="USD (escala logarítmica)",
                            )
                        else:
                            fig_g.update_yaxes(
                                range=[0, max(gr.target_nominal, _fan_hi) * 1.10],
                                title_text="USD",
                            )

                        fig_g.update_layout(
                            title=f"{g_icon} {goal.name} — Proyección Monte Carlo",
                            title_y=0.97, title_yanchor="top",
                            xaxis_title="Años",
                            yaxis_tickformat="$,.0f",
                            height=360,
                            # t=86 deja lugar real para título + leyenda: con
                            # t=45 la leyenda horizontal se montaba sobre el título.
                            margin=dict(l=0, r=90, t=86, b=30),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                            hovermode="x unified",
                        )
                        st.plotly_chart(fig_g, width="stretch")

                    # Monthly savings advice. Se resuelve contra la MISMA métrica
                    # que muestra la card (prob_achieve_target_pct del motor MC),
                    # no contra una anualidad determinística con la CAGR mediana:
                    # un cálculo sin volatilidad al retorno mediano da ~50% de
                    # éxito por construcción, nunca el objetivo que se promete.
                    if gr.prob_success_pct < GOAL_CARD.success_target_pct:
                        with st.spinner(f"Calculando el ahorro necesario para {goal.name}…"):
                            _total_mensual = cached_goal_savings_target(
                                symbols=tuple(symbols),
                                weights_tuple=tuple(weights) if weights else None,
                                # Reconstruido desde gr.goal (no desde
                                # goals_serialized, que solo existe en la rama
                                # que corre la simulación). Tupla de pares para
                                # que st.cache_data pueda hashearlo.
                                goal_serialized=(
                                    ("name", goal.name),
                                    ("target_amount_today", float(goal.target_amount_today)),
                                    ("horizon_years", int(goal.horizon_years)),
                                    ("priority", int(goal.priority)),
                                    ("expected_inflation", float(goal.expected_inflation)),
                                    ("annual_contribution", float(goal.annual_contribution)),
                                    ("allocated_capital", float(goal.allocated_capital)),
                                    ("goal_type", goal.goal_type),
                                ),
                                allocated_capital=float(gr.allocated_capital),
                                target_prob_pct=GOAL_CARD.success_target_pct,
                                n_sims=GOAL_CARD.advice_n_sims,
                                vol_scale=plan_scales["vol_scale"],
                                return_scale=plan_scales["return_scale"],
                            )

                        _obj = f"{GOAL_CARD.success_target_pct:.0f}%"
                        if _total_mensual is None:
                            st.warning(
                                f"⚠️ **{g_icon} {goal.name}** no llega al {_obj} de probabilidad "
                                "solo con más ahorro. Hay que bajar la meta, estirar el plazo "
                                "o asignarle más capital."
                            )
                        elif _total_mensual <= 0:
                            pass  # ya está en el objetivo sin aportes extra
                        else:
                            _adicional = max(0.0, _total_mensual - _aporte_mensual)
                            _extra = (
                                f" (**\\${_adicional:,.0f}/mes** más de lo que ya aportás)"
                                if _aporte_mensual > 0 else ""
                            )
                            st.info(
                                f"💡 Para llevar **{g_icon} {goal.name}** al {_obj} de probabilidad: "
                                f"**\\${_total_mensual:,.0f}/mes** en total{_extra}."
                            )

            # ---------------------------------------------------------------- #
            #  Timeline overview chart                                          #
            # ---------------------------------------------------------------- #
            st.subheader("📅 Timeline del plan")
            fig_timeline = go.Figure()

            sorted_results = sorted(plan_result.goal_results, key=lambda gr: gr.goal.horizon_years)
            for gr in sorted_results:
                prob = gr.prob_success_pct
                bar_color = (
                    "#28A745" if prob >= 80
                    else "#FFC107" if prob >= 55
                    else "#DC3545"
                )
                _tl_name = f"{gr.goal.icon} {gr.goal.name}"
                fig_timeline.add_trace(go.Bar(
                    x=[_tl_name],
                    y=[gr.target_nominal],
                    name=_tl_name,
                    marker_color=bar_color,
                    text=f"{prob:.0f}%<br>${gr.target_nominal/1e6:.2f}M",
                    textposition="outside",
                    customdata=[[gr.goal.horizon_years, gr.median_terminal, gr.allocated_capital]],
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Meta nominal: $%{y:,.0f}<br>"
                        "Horizonte: %{customdata[0]} años<br>"
                        "Mediana proyectada: $%{customdata[1]:,.0f}<br>"
                        "Capital asignado: $%{customdata[2]:,.0f}<br>"
                        "<extra></extra>"
                    ),
                ))

            fig_timeline.update_layout(
                title="Metas por valor nominal — color = probabilidad de éxito",
                yaxis_title="USD (valor nominal futuro)",
                yaxis_tickformat="$,.0f",
                height=400,
                showlegend=False,
                xaxis_tickangle=-15,
            )
            fig_timeline.add_annotation(
                text="🟢 ≥80%  🟡 55-79%  🔴 <55%",
                xref="paper", yref="paper",
                x=1, y=1.05,
                showarrow=False,
                font=dict(size=11),
            )
            st.plotly_chart(fig_timeline, width="stretch")

            # ---------------------------------------------------------------- #
            #  Summary table + export                                           #
            # ---------------------------------------------------------------- #
            # U1-7: esta tabla se exporta a CSV. Una meta con aportes publica un
            # crecimiento del pozo, no un retorno; una sin aportes sí publica un
            # CAGR. Con las dos clases en la misma columna manda el rótulo
            # prudente y el tooltip explica las dos lecturas — mismo criterio que
            # las columnas mixtas de "vs Benchmarks" (U1-1/U1-2/U1-10).
            _goals_flows = any(
                mc_has_cash_flows(_gr.mc_result) for _gr in plan_result.goal_results
            )
            _goals_growth_col = pot_growth_column_label(_goals_flows)
            _goals_growth_help = pot_growth_help(_goals_flows) + (
                "\n\nLas metas sin aportes de esta tabla sí son un CAGR."
                if _goals_flows else ""
            )
            summary_rows = []
            for gr in plan_result.goal_results:
                mc = gr.mc_result
                summary_rows.append({
                    "Meta": gr.goal.name,
                    "Prioridad": gr.goal.priority_label,
                    "Horizonte (años)": gr.goal.horizon_years,
                    "Meta hoy (USD)": gr.goal.target_amount_today,
                    "Meta nominal (USD)": gr.target_nominal,
                    "Capital asignado (USD)": gr.allocated_capital,
                    "Mediana proyectada (USD)": gr.median_terminal,
                    "Prob. éxito (%)": round(gr.prob_success_pct, 1),
                    "P10 (USD)": mc.p10_terminal,
                    "P90 (USD)": mc.p90_terminal,
                    _goals_growth_col: round(mc.median_cagr_pct, 1),
                    "Drawdown máx. med. (%)": round(mc.median_max_drawdown_pct, 1),
                    "Riesgo SORR (%)": round(mc.sorr_early_drawdown_pct, 1),
                })

            df_summary = pd.DataFrame(summary_rows)
            st.dataframe(
                df_summary,
                width="stretch",
                hide_index=True,
                column_config={
                    "Meta hoy (USD)":          st.column_config.NumberColumn(format="$%,.0f"),
                    "Meta nominal (USD)":       st.column_config.NumberColumn(format="$%,.0f"),
                    "Capital asignado (USD)":   st.column_config.NumberColumn(format="$%,.0f"),
                    "Mediana proyectada (USD)": st.column_config.NumberColumn(format="$%,.0f"),
                    "Prob. éxito (%)":          st.column_config.NumberColumn(format="%.1f%%"),
                    "P10 (USD)":                st.column_config.NumberColumn(format="$%,.0f"),
                    "P90 (USD)":                st.column_config.NumberColumn(format="$%,.0f"),
                    _goals_growth_col:          st.column_config.NumberColumn(
                        _goals_growth_col, format="%.1f%%", help=_goals_growth_help
                    ),
                    "Drawdown máx. med. (%)":   st.column_config.NumberColumn(format="%.1f%%"),
                    "Riesgo SORR (%)":          st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

            _goals_csv = io.StringIO()
            df_summary.to_csv(_goals_csv, index=False)
            st.download_button(
                label="⬇️ Exportar plan completo a CSV",
                data=_goals_csv.getvalue(),
                file_name=f"plan_metas_{len(goals_list)}_metas.csv",
                mime="text/csv",
            )

            # ---------------------------------------------------------------- #
            #  PDF Report Download                                               #
            # ---------------------------------------------------------------- #
            st.divider()
            with st.expander("📄 Descargar Reporte PDF", expanded=False):
                st.markdown("Generá un reporte PDF profesional con tu plan de inversión completo.")
                _pdf_col1, _pdf_col2 = st.columns(2)
                with _pdf_col1:
                    _pdf_user_name = st.text_input(
                        "Nombre (opcional)",
                        placeholder="Ej: Juan Pérez",
                        key="pdf_goals_user_name",
                    )
                    _pdf_version = st.radio(
                        "Versión",
                        ["completo", "breve"],
                        key="pdf_goals_version",
                        format_func=lambda v: "📋 Completo (gráficos + riesgo)" if v == "completo" else "📝 Breve (metas + recomendaciones)",
                    )
                with _pdf_col2:
                    _pdf_incl_ai = st.checkbox("Incluir narrativa IA", value=True, key="pdf_goals_ai")
                    _pdf_incl_charts = st.checkbox("Incluir gráficos", value=True, key="pdf_goals_charts")
                    _pdf_incl_risk = st.checkbox("Incluir análisis de riesgo", value=True, key="pdf_goals_risk")

                if st.button("📄 Generar y Descargar PDF", type="primary", key="pdf_goals_generate"):
                    with st.spinner("Generando reporte PDF…"):
                        try:
                            from reports.investment_plan import InvestmentPlanReport, ReportOptions
                            _pdf_options = ReportOptions(
                                user_name=_pdf_user_name,
                                version=_pdf_version,
                                include_ai_narrative=_pdf_incl_ai,
                                include_charts=_pdf_incl_charts,
                                include_risk_section=_pdf_incl_risk,
                            )
                            from data.product_ux import assemble_plan_pdf_mc_params

                            _pdf_mc_params = assemble_plan_pdf_mc_params(
                                session=dict(st.session_state),
                                prefs=_prefs_sim,
                                profile_name={
                                    "conservative": "Conservador",
                                    "moderate": "Moderado",
                                    "aggressive": "Agresivo",
                                }.get(plan_profile, plan_profile),
                            )
                            # Keep explicit sim keys if present
                            _pdf_mc_params.setdefault(
                                "annual_withdrawal",
                                st.session_state.get("annual_withdrawal", 0),
                            )
                            _pdf_mc_params.setdefault(
                                "inflation_rate",
                                st.session_state.get("inflation_rate", 3.0),
                            )
                            _pdf_opt_result = st.session_state.get("goal_optimizer_result")
                            _pdf_ai_config = _get_ai_config() if _pdf_incl_ai else None
                            _pdf_bytes = InvestmentPlanReport().generate(
                                goal_plan=plan_result,
                                opt_result=_pdf_opt_result,
                                mc_result=None,
                                mc_params=_pdf_mc_params,
                                ai_config=_pdf_ai_config,
                                options=_pdf_options,
                            )
                            st.session_state["pdf_goals_bytes"] = _pdf_bytes
                        except Exception as _pdf_err:
                            st.error(f"Error generando el PDF: {_pdf_err}")

                if "pdf_goals_bytes" in st.session_state:
                    _fname = f"plan_inversion_{datetime.now().strftime('%Y%m%d')}.pdf"
                    st.download_button(
                        label="⬇️ Descargar PDF",
                        data=st.session_state["pdf_goals_bytes"],
                        file_name=_fname,
                        mime="application/pdf",
                        key="pdf_goals_dl_btn",
                    )
                    st.success("✅ PDF listo para descargar.")

            with st.expander("ℹ️ Metodología del planificador de metas"):
                st.markdown("""
**Modelo de simulación:**
- Cada meta se simula de forma independiente con Block Bootstrap Monte Carlo.
- El capital se distribuye proporcionalmente a la prioridad (Alta=3x, Media=2x, Baja=1x)
  salvo que lo especifiques manualmente.
- Los aportes anuales se modelan como retiros negativos (ingresos al portafolio).

**Métricas de SORR (Sequence of Returns Risk):**
- **Riesgo SORR:** % de simulaciones que sufren una caída >30% en los **primeros 5 años**.
  Crítico para metas de largo plazo — una caída temprana puede destruir el plan aunque el CAGR sea positivo.
- **Drawdown máximo mediano:** Caída pico-a-valle típica durante todo el horizonte.
- **Paths con caída ≥50%:** % de simulaciones que tocan una pérdida del 50% o más en algún momento.
- **Mínimo P10 intra-horizonte:** En el peor 10% de simulaciones, el portafolio baja hasta este valor.

**Asignación de capital automática:**
Si `capital_asignado = 0` en una meta, el planificador distribuye el capital total entre las metas
con peso proporcional a su prioridad. Podés sobreescribir esto ingresando un valor explícito.

**Limitaciones:** Los aportes anuales no crecen con inflación por defecto. Para retiros de largo
plazo ajustados por inflación, usá el tab Monte Carlo con retiro creciente.
                """)

with tab_goals:
    _tab_goals_content()

# ------------------------------------------------------------------ #
#  Footer                                                              #
# ------------------------------------------------------------------ #

st.divider()
st.caption(
    "⚠️ **Aviso:** Todas las simulaciones son herramientas educativas. "
    "Los resultados no predicen el futuro ni constituyen asesoramiento financiero. "
    "Consultá con un asesor certificado antes de tomar decisiones de inversión."
)
