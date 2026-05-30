"""Monte Carlo simulation and stress testing for the portfolio."""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import MONTE_CARLO, OPTIMIZER_PROFILES, SECTOR_MAP
from dashboard.shared import cached_monte_carlo, cached_stress_test, cached_goal_simulation, _get_ai_config
from portfolio.goals import (
    Goal, PRIORITY_LABELS, PRIORITY_COLORS, PRIORITY_EMOJIS,
    GOAL_TYPE_ICONS, GOAL_TYPE_LABELS, GOAL_TYPE_PLACEHOLDERS,
    required_monthly_savings,
)

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("🎲 Simulaciones & Stress Testing")
st.caption(
    "Proyectá tu portafolio a largo plazo con simulación Monte Carlo y evaluá "
    "su resistencia ante crisis históricas. "
    "💵 Valores en USD. Esta simulación es orientativa, no una garantía de resultados."
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

if st.sidebar.button("Aplicar preset", type="primary", use_container_width=True):
    if preset_choice == "Acumulación pura (20 años)":
        st.session_state["horizon_years"] = 20
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
        st.session_state["horizon_years"] = 30
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
        with st.spinner(f"Ejecutando {n_sims:,} simulaciones × {horizon_years} años…"):
            mc = cached_monte_carlo(
                symbols=tuple(symbols),
                weights_tuple=tuple(weights) if weights else None,
                horizon_years=horizon_years,
                n_sims=n_sims,
                initial_value=float(initial_value),
                annual_withdrawal=float(annual_withdrawal),
                target_value=float(target_value),
                withdrawal_growth_rate=float(inflation_rate) / 100.0,   # Phase 0: growing withdrawals
            )
        st.session_state["mc_result"] = mc
        st.session_state["mc_params"] = {
            "horizon_years": horizon_years,
            "initial_value": initial_value,
            "inflation_rate": inflation_rate,
            "n_sims": n_sims,
        }

    mc = st.session_state.get("mc_result")
    if mc is None:
        st.warning("No hay resultado de simulación disponible.")
        return

    for w in mc.warnings:
        st.warning(w)

    # ---- KPI row (improved clarity for long-term investors) ----
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Capital inicial", f"${initial_value:,.0f}")

    k2.metric(
        f"Valor más probable (mediana)",
        f"${mc.median_terminal:,.0f}",
        delta=f"{mc.median_cagr_pct:.1f}% CAGR promedio",
        help="En la mitad de las simulaciones terminás por encima de este número, y en la mitad por debajo.",
    )

    k3.metric(
        "⚠️ Escenario pesimista (peor 10%)",
        f"${mc.p10_terminal:,.0f}",
        delta=f"{mc.p10_cagr_pct:.1f}% CAGR",
        delta_color="inverse",
        help="En 1 de cada 10 simulaciones terminás con este valor o menos. Este es el caso 'malo' que debés estar dispuesto a aceptar.",
    )

    k4.metric(
        "Escenario optimista (mejor 10%)",
        f"${mc.p90_terminal:,.0f}",
        help="Solo en 1 de cada 10 simulaciones terminás por encima de este valor (caso muy favorable).",
    )

    if target_value > 0:
        k5.metric(
            f"Probabilidad de alcanzar tu meta",
            f"{mc.prob_achieve_target_pct:.1f}%",
            delta=f"de llegar a ${target_value:,.0f}",
            delta_color="off",
            help="Porcentaje de las 10.000 simulaciones que superaron o igualaron tu objetivo.",
        )
    else:
        k5.metric(
            "Probabilidad de quedarte en 0",
            f"{mc.prob_ruin_pct:.1f}%",
            delta_color="inverse",
            help="Casos en los que el portafolio llega a cero o negativo antes del final del horizonte.",
        )

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
- El modelo ya está siendo conservador (le saca 20% al retorno esperado histórico). Aun así, el período que usamos como base fue bueno. El futuro puede ser peor.
- Estos son solo valores **al final** de los {horizon_years} años. Durante el camino podés haber tenido caídas del 50% o más. Si en ese momento sacás plata o te asustás y vendés, el resultado final puede ser mucho peor que el P10 que ves acá.
- Si en algún momento empezás a retirar plata (aunque sea poco), el riesgo de que el "caso malo" sea realmente malo sube mucho (riesgo de secuencia de retornos).

En resumen: el modelo no está diciendo "siempre vas a ganar mucho". Está diciendo que, **incluso en un escenario malo pero no catastrófico**, todavía terminás con más capital del que empezaste en términos reales. Casos peores que los históricos (o errores de comportamiento) no están totalmente capturados.
""")
        else:
            st.markdown(f"""
- El modelo ya está siendo conservador (le saca 20% al retorno esperado histórico). Aun así, el futuro puede ser peor que el pasado reciente.
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
                weights = [a.weight_pct/100 for a in opt_for_narrative.tickers] if opt_for_narrative and opt_for_narrative.tickers else ([1.0/len(symbols)]*len(symbols) if symbols else [])

                narrative_context = {
                    "profile_name": getattr(opt_for_narrative, "profile_name", "Moderado"),
                    "tickers": tickers,
                    "weights": weights,
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
        st.plotly_chart(fan_chart, use_container_width=True)
        _real_note = (
            f" La línea naranja punteada muestra el poder adquisitivo real "
            f"(descontando {inflation_rate:.1f}% de inflación anual)."
            if inflation_rate > 0 else ""
        )
        st.caption(
            "Las bandas muestran el rango de resultados posibles según la historia real de los mercados. "
            "Azul = caso más probable | Rojo = mal caso (1 de cada 10) | Verde = muy buen caso (1 de cada 10). "
            + _real_note
            + " Los números usan un ajuste conservador (+10% volatilidad y −20% retorno esperado respecto al pasado)."
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
        st.plotly_chart(fig_hist, use_container_width=True)

    # ---- Terminal distribution table ----
    if mc.fan_paths:
        pct_rows = []
        for p in [5, 10, 25, 50, 75, 90, 95]:
            v = mc.fan_paths[horizon_years][p]
            real_v = v / (1 + inflation_rate / 100) ** horizon_years if inflation_rate > 0 else None
            row = {
                "Percentil": f"P{p}",
                "Valor nominal": v,
                "CAGR %": round(((v / initial_value) ** (1 / horizon_years) - 1) * 100, 1) if v > 0 else 0,
            }
            if real_v is not None:
                row["Valor real"] = round(real_v)
            pct_rows.append(row)

        df_terminal = pd.DataFrame(pct_rows)
        _col_cfg = {
            "Valor nominal": st.column_config.NumberColumn("Valor nominal", format="$%,.0f"),
            "CAGR %":        st.column_config.NumberColumn("CAGR %",        format="%.1f%%"),
        }
        if inflation_rate > 0:
            _col_cfg["Valor real"] = st.column_config.NumberColumn(
                f"Valor real ({inflation_rate:.1f}% inf.)", format="$%,.0f"
            )
        st.dataframe(df_terminal, use_container_width=True, hide_index=True, column_config=_col_cfg)

        # Export
        _csv_buf = io.StringIO()
        df_terminal.to_csv(_csv_buf, index=False)
        st.download_button(
            label="⬇️ Exportar distribución a CSV",
            data=_csv_buf.getvalue(),
            file_name=f"montecarlo_{horizon_years}y_{n_sims}sims.csv",
            mime="text/csv",
        )

    with st.expander("ℹ️ Metodología y limitaciones"):
        st.markdown(f"""
**Metodología:** Block Bootstrap ({mc.n_weeks_history} semanas de historia real, bloques de 4 semanas).
No asume distribución normal — captura fat tails y autocorrelación de corto plazo.

**Ajuste conservador aplicado:**
- Volatilidad histórica × **{MONTE_CARLO.vol_adjustment:.0%}** (+10%)
- Retorno esperado × **{MONTE_CARLO.mean_haircut:.0%}** (−20%)

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

# ================================================================== #
#  Tab 2: Stress Test                                                 #


with tab_mc:
    _tab_mc_content()

# ================================================================== #

with tab_stress:
    st.subheader("Simulación de crisis históricas")
    st.caption(
        "Impacto estimado sobre el portafolio actual en cada crisis, "
        "calculado desde los pesos por sector del optimizador."
    )

    if not sector_weights:
        st.info("Ejecutá el Optimizer primero para obtener pesos por sector.", icon="⚠️")
    else:
        stress_results = cached_stress_test(
            sector_weights=dict(sector_weights),
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
            use_container_width=True,
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
        st.plotly_chart(fig_stress, use_container_width=True)

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
        st.plotly_chart(fig_recov, use_container_width=True)

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
                sec_df, use_container_width=True, hide_index=True,
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

with tab_custom:
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
            st.plotly_chart(fig_recov_path, use_container_width=True)

# ================================================================== #
#  Tab 4: Comparar Perfiles                                           #
# ================================================================== #


def _tab_compare_content():
    st.subheader("🔀 Cómo afecta el perfil de riesgo a las proyecciones")
    st.caption(
        "Compara Conservador / Moderado / Agresivo usando los **mismos activos** "
        "pero con distintos supuestos de retorno y volatilidad. "
        "Conservador = más haircut al retorno esperado y más volatilidad simulada; "
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
    cmp_rows = []
    for _pk, _mc in compare_mc.items():
        _pname = _PROFILE_NAMES_MC[_pk]
        cmp_rows.append({
            "Perfil":     _pname,
            "P10 (USD)":  _mc.p10_terminal,
            "P50 (USD)":  _mc.median_terminal,
            "P90 (USD)":  _mc.p90_terminal,
            "CAGR P50 %": _mc.median_cagr_pct,
            "Prob. ruina %": _mc.prob_ruin_pct,
            "Prob. meta %":  _mc.prob_achieve_target_pct if target_value > 0 else None,
        })
    _cmp_df = pd.DataFrame(cmp_rows)
    _cmp_col_cfg = {
        "P10 (USD)":     st.column_config.NumberColumn("P10 (USD)",     format="$%,.0f"),
        "P50 (USD)":     st.column_config.NumberColumn("P50 (USD)",     format="$%,.0f"),
        "P90 (USD)":     st.column_config.NumberColumn("P90 (USD)",     format="$%,.0f"),
        "CAGR P50 %":    st.column_config.NumberColumn("CAGR P50 %",   format="%.1f%%"),
        "Prob. ruina %": st.column_config.NumberColumn("Prob. ruina %", format="%.1f%%"),
    }
    if target_value > 0:
        _cmp_col_cfg["Prob. meta %"] = st.column_config.NumberColumn(
            f"Prob. meta ${target_value:,.0f}", format="%.1f%%"
        )
    st.dataframe(_cmp_df, use_container_width=True, hide_index=True, column_config=_cmp_col_cfg)

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
    st.plotly_chart(fig_cmp, use_container_width=True)

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
    st.plotly_chart(fig_p10, use_container_width=True)

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

with tab_goals:
    st.subheader("🏆 Planificador de Metas Financieras")
    st.caption(
        "Definí múltiples metas de inversión (casa, independencia financiera, retiro) "
        "y simulá el plan completo con Monte Carlo independiente por meta. "
        "El capital se asigna automáticamente según prioridad, o podés definirlo manualmente."
    )

    # ---- Session state init for goals list ----
    if "goals_list" not in st.session_state:
        st.session_state["goals_list"] = []

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
            min_value=1, max_value=40, value=5, step=1,
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
                min_value=0, max_value=500_000, value=0, step=1_000,
                format="%d",
                help="Cuánto ahorrás por año específicamente para esta meta. 0 = solo crece el capital inicial.",
                key="new_goal_contribution",
            )
            new_allocated = gc7.number_input(
                "Capital asignado (USD, 0 = auto)",
                min_value=0, max_value=10_000_000, value=0, step=5_000,
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
                f"${new_target:,.0f} hoy → **${nominal_preview:,.0f} nominal** "
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
            nominal = g["target_amount_today"] * (1 + g["expected_inflation"] / 100) ** g["horizon_years"]
            col_info, col_up, col_dn, col_del = st.columns([10, 1, 1, 1])
            with col_info:
                st.markdown(
                    f"**{i+1}. {g_icon} {g['name']}** &nbsp; {p_emoji} {p_label} &nbsp;|&nbsp; "
                    f"${g['target_amount_today']:,.0f} → **${nominal:,.0f}** &nbsp;|&nbsp; "
                    f"{g['horizon_years']}a &nbsp;|&nbsp; aporte ${g['annual_contribution']:,.0f}/año"
                    + (f" &nbsp;·&nbsp; _{g['notes']}_" if g.get("notes") else "")
                )
            if i > 0:
                if col_up.button("⬆️", key=f"up_{i}", help="Subir prioridad"):
                    goals_list[i - 1], goals_list[i] = goals_list[i], goals_list[i - 1]
                    st.rerun()
            if i < len(goals_list) - 1:
                if col_dn.button("⬇️", key=f"dn_{i}", help="Bajar prioridad"):
                    goals_list[i], goals_list[i + 1] = goals_list[i + 1], goals_list[i]
                    st.rerun()
            if col_del.button("🗑️", key=f"del_goal_{i}", help=f"Eliminar '{g['name']}'"):
                st.session_state["goals_list"].pop(i)
                st.rerun()

        _col_clear, _col_opt = st.columns([1, 2])
        if _col_clear.button("🗑️ Limpiar todas las metas", key="clear_all_goals"):
            st.session_state["goals_list"] = []
            st.rerun()
        _col_opt.button(
            "🔬 Optimizar para mis metas",
            key="optimize_for_goals_placeholder",
            disabled=True,
            help="Próximamente en Fase 2 — Optimización multi-metas: ajusta los pesos del portafolio considerando el horizonte y capital de cada meta simultáneamente.",
        )

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
                help="Score ponderado por prioridad: P(éxito) × peso de prioridad.",
            )
            pk3.metric(
                "Metas con >80% prob. éxito",
                f"{sum(1 for gr in plan_result.goal_results if gr.prob_success_pct >= 80)}"
                f"/{len(plan_result.goal_results)}",
            )
            capital_gap = plan_result.capital_gap
            pk4.metric(
                "Gap de capital (vs. medianas)",
                f"${capital_gap:,.0f}" if capital_gap > 0 else "✅ Sin gap",
                delta="déficit proyectado" if capital_gap > 0 else None,
                delta_color="inverse" if capital_gap > 0 else "off",
                help="Diferencia entre las medianas proyectadas y los valores objetivo nominales.",
            )

            # Plan-level warnings
            for w in plan_result.warnings:
                st.warning(w)

            # ---------------------------------------------------------------- #
            #  Per-goal results cards                                           #
            # ---------------------------------------------------------------- #
            st.subheader("🎯 Resultados por meta")

            def _sorr_risk_score(sorr_pct: float, dd_pct: float) -> tuple:
                """Return (badge_label, hex_color) for SORR risk level."""
                if sorr_pct < 25 and dd_pct < 30:
                    return "🟢 Bajo", "#28A745"
                elif sorr_pct < 50 or dd_pct < 45:
                    return "🟡 Medio", "#FFC107"
                return "🔴 Alto", "#DC3545"

            for gr in plan_result.goal_results:
                goal = gr.goal
                mc = gr.mc_result
                p_color = goal.priority_color
                p_emoji = goal.priority_emoji
                p_label = goal.priority_label
                g_icon  = goal.icon

                # SORR Risk Score
                sorr_badge, sorr_color = _sorr_risk_score(
                    mc.sorr_early_drawdown_pct, mc.median_max_drawdown_pct
                )

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
                    )
                    m3.metric(
                        "Prob. éxito",
                        f"{gr.prob_success_pct:.1f}%",
                        delta=gr.feasibility_label,
                        delta_color="off",
                    )
                    m4.metric(
                        "Mediana proyectada",
                        f"${gr.median_terminal:,.0f}",
                        delta=f"CAGR {mc.median_cagr_pct:.1f}%",
                    )
                    m5.metric(
                        "Pesimista (P10)",
                        f"${mc.p10_terminal:,.0f}",
                        delta=f"CAGR {mc.p10_cagr_pct:.1f}%",
                        delta_color="inverse",
                    )

                    # Progreso estimado (si hay valor del portfolio actual en sesión)
                    _port_val = st.session_state.get("portfolio_current_value", 0.0)
                    if _port_val > 0 and gr.target_nominal > 0:
                        _pct_prog = min(_port_val / gr.target_nominal * 100, 100)
                        st.progress(
                            _pct_prog / 100,
                            text=f"📈 Progreso actual del portfolio: **{_pct_prog:.1f}%** hacia la meta nominal (${_port_val:,.0f} / ${gr.target_nominal:,.0f})",
                        )

                    st.divider()

                    # SORR section header with badge
                    _sorr_col_badge, _sorr_col_title = st.columns([1, 5])
                    _sorr_col_badge.markdown(
                        f"<div style='background:{sorr_color}22;border:2px solid {sorr_color};"
                        f"border-radius:10px;padding:8px;text-align:center;"
                        f"font-weight:700;font-size:1.1em;color:{sorr_color};'>"
                        f"SORR<br>{sorr_badge}</div>",
                        unsafe_allow_html=True,
                        help="Sequence of Returns Risk: riesgo de que una mala secuencia de retornos al inicio del horizonte destruya el plan, incluso si el CAGR promedio es positivo. "
                             "🟢 Bajo (<25% SORR, <30% drawdown máx.) · 🟡 Medio · 🔴 Alto (>50% SORR o >45% drawdown).",
                    )
                    with _sorr_col_title:
                        ds1, ds2, ds3, ds4 = st.columns(4)
                        ds1.metric(
                            "Drawdown máx. mediano",
                            f"{mc.median_max_drawdown_pct:.1f}%",
                            delta=f"típ. en año {mc.median_year_of_max_dd:.1f}",
                            delta_color="off",
                            help="Caída pico-a-valle mediana durante todo el horizonte. "
                                 "El 'delta' indica en qué año ocurre típicamente el peor drawdown.",
                        )
                        ds2.metric(
                            "Riesgo SORR (5a)",
                            f"{mc.sorr_early_drawdown_pct:.1f}%",
                            help="% de simulaciones con caída >30% en los **primeros 5 años**. "
                                 "Una secuencia negativa temprana puede ser devastadora si coincide con retiros.",
                            delta_color="inverse",
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
                            help="En el peor 10% de simulaciones, el portafolio llega a este valor mínimo en algún momento del horizonte.",
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
                                fillcolor="rgba(220,53,69,0.25)",
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
                        ))
                        fig_g.add_hline(
                            y=gr.target_nominal,
                            line_dash="dash", line_color="gold", line_width=2,
                            annotation_text=f"Meta ${gr.target_nominal:,.0f}",
                            annotation_position="right",
                        )
                        # Vertical line at median year of max drawdown
                        if 0 < mc.median_year_of_max_dd < goal.horizon_years:
                            fig_g.add_vline(
                                x=mc.median_year_of_max_dd,
                                line_dash="dot", line_color="rgba(220,53,69,0.6)", line_width=1.5,
                                annotation_text=f"Peor año típico: {mc.median_year_of_max_dd:.1f}",
                                annotation_position="top left",
                                annotation_font_size=10,
                            )
                        fig_g.update_layout(
                            title=f"{g_icon} {goal.name} — Proyección Monte Carlo",
                            xaxis_title="Años",
                            yaxis_title="USD",
                            yaxis_tickformat="$,.0f",
                            height=320,
                            margin=dict(l=0, r=80, t=45, b=30),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                            hovermode="x unified",
                        )
                        st.plotly_chart(fig_g, use_container_width=True)

                    # Monthly savings estimate
                    if gr.prob_success_pct < 80:
                        monthly_needed = required_monthly_savings(
                            target_nominal=gr.target_nominal,
                            initial_capital=gr.allocated_capital,
                            horizon_years=goal.horizon_years,
                            expected_annual_return=max(mc.median_cagr_pct / 100, 0.03),
                        )
                        if monthly_needed > 0:
                            st.info(
                                f"💡 Para mejorar la probabilidad de éxito de **{g_icon} {goal.name}**, "
                                f"necesitarías ahorrar aprox. **${monthly_needed:,.0f}/mes** adicionales "
                                f"(estimación con CAGR mediana {mc.median_cagr_pct:.1f}%)."
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
            st.plotly_chart(fig_timeline, use_container_width=True)

            # ---------------------------------------------------------------- #
            #  Summary table + export                                           #
            # ---------------------------------------------------------------- #
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
                    "CAGR mediana (%)": round(mc.median_cagr_pct, 1),
                    "Drawdown máx. med. (%)": round(mc.median_max_drawdown_pct, 1),
                    "Riesgo SORR (%)": round(mc.sorr_early_drawdown_pct, 1),
                })

            df_summary = pd.DataFrame(summary_rows)
            st.dataframe(
                df_summary,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Meta hoy (USD)":          st.column_config.NumberColumn(format="$%,.0f"),
                    "Meta nominal (USD)":       st.column_config.NumberColumn(format="$%,.0f"),
                    "Capital asignado (USD)":   st.column_config.NumberColumn(format="$%,.0f"),
                    "Mediana proyectada (USD)": st.column_config.NumberColumn(format="$%,.0f"),
                    "Prob. éxito (%)":          st.column_config.NumberColumn(format="%.1f%%"),
                    "P10 (USD)":                st.column_config.NumberColumn(format="$%,.0f"),
                    "P90 (USD)":                st.column_config.NumberColumn(format="$%,.0f"),
                    "CAGR mediana (%)":         st.column_config.NumberColumn(format="%.1f%%"),
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

# ------------------------------------------------------------------ #
#  Footer                                                              #
# ------------------------------------------------------------------ #

st.divider()
st.caption(
    "⚠️ **Aviso:** Todas las simulaciones son herramientas educativas. "
    "Los resultados no predicen el futuro ni constituyen asesoramiento financiero. "
    "Consultá con un asesor certificado antes de tomar decisiones de inversión."
)
