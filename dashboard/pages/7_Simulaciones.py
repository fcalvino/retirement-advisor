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
from dashboard.shared import cached_monte_carlo, cached_stress_test, _get_ai_config

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

tab_mc, tab_stress, tab_custom, tab_compare = st.tabs(
    ["📈 Monte Carlo", "🌪️ Stress Test", "🎯 Escenario personalizado", "🔀 Comparar Perfiles"]
)

# ================================================================== #
#  Tab 1: Monte Carlo                                                 #
# ================================================================== #

with tab_mc:
    run_mc = st.button("▶ Ejecutar simulación Monte Carlo", type="primary")

    if not run_mc and "mc_result" not in st.session_state:
        st.info(
            "Configurá los parámetros en el sidebar (horizonte, capital inicial, retiro anual, meta, inflación) "
            "y hacé clic en **▶ Ejecutar simulación Monte Carlo** para comenzar.\n\n"
            "Las simulaciones usan block-bootstrap sobre historia real de 10 años con ajustes conservadores "
            "— ideales para evaluar planes de inversión a 10-30 años.",
            icon="🎲",
        )
        st.stop()

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
        st.stop()

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
            st.markdown(f"- Caso más probable: tus **${initial_value:,.0f}** de hoy tendrían el poder de compra de **${real_median:,.0f}**")
            st.markdown(f"- Escenario pesimista (1 de cada 10 casos): **${real_p10:,.0f}**")
            st.markdown(f"- Escenario muy bueno (1 de cada 10 casos): **${real_p90:,.0f}**")
        else:
            st.markdown("**Valores en dólares de hoy:**")

        st.markdown(f"""
**Valores nominales (sin ajustar por inflación):**
- Caso más probable: **${mc.median_terminal:,.0f}** ({mc.median_terminal/initial_value:.1f}x)
- Escenario pesimista: **${mc.p10_terminal:,.0f}** o menos
- Escenario optimista: **${mc.p90_terminal:,.0f}** o más
""")

        # Much more direct reality check
        st.markdown("**⚠️ Por qué estos números pueden engañarte (importante leer):**")
        if real_p10 is not None:
            st.markdown(f"""
Aunque el escenario pesimista nominal (${mc.p10_terminal:,.0f}) parece "ganar", tené en cuenta:

- En **poder de compra real** (después de inflación), en el peor 10% de los casos solo terminás con **${real_p10:,.0f}** de los dólares de hoy. Eso es un crecimiento real bastante modesto en {horizon_years} años.
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
                st.success(f"✅ Con este plan tenés **muy buena probabilidad ({mc.prob_achieve_target_pct:.0f}%)** de alcanzar tu meta de ${target_value:,.0f}.")
            elif mc.prob_achieve_target_pct >= 60:
                st.warning(f"⚠️ Tenés una probabilidad razonable ({mc.prob_achieve_target_pct:.0f}%), pero no es altísima. Considerá ajustar aportes, reducir la meta o asumir un poco más de riesgo.")
            else:
                st.error(f"❌ La probabilidad de alcanzar ${target_value:,.0f} es baja ({mc.prob_achieve_target_pct:.0f}%). Este plan probablemente necesite cambios (más ahorro, más horizonte, o menos retiro).")

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

with tab_compare:
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
        st.stop()

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
        st.stop()

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

# ------------------------------------------------------------------ #
#  Footer                                                              #
# ------------------------------------------------------------------ #

st.divider()
st.caption(
    "⚠️ **Aviso:** Todas las simulaciones son herramientas educativas. "
    "Los resultados no predicen el futuro ni constituyen asesoramiento financiero. "
    "Consultá con un asesor certificado antes de tomar decisiones de inversión."
)
