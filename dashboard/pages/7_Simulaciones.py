"""Monte Carlo simulation and stress testing for the portfolio."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import MONTE_CARLO, SECTOR_MAP
from portfolio.monte_carlo import MonteCarloSimulator
from portfolio.stress_test import StressTester

# ------------------------------------------------------------------ #
#  Page config                                                         #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="Simulaciones — Retirement Advisor",
    page_icon="🎲",
    layout="wide",
)

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("🎲 Simulaciones & Stress Testing")
st.caption(
    "Proyecta tu portafolio a largo plazo con simulación Monte Carlo y evalúa "
    "su resistencia ante crisis históricas. "
    "💵 Valores en USD. Esta simulación es orientativa, no una garantía de resultados."
)

# ------------------------------------------------------------------ #
#  Sidebar controls                                                    #
# ------------------------------------------------------------------ #

st.sidebar.subheader("Parámetros de simulación")

horizon_years = st.sidebar.selectbox(
    "Horizonte de proyección",
    [5, 10, 15, 20, 25, 30],
    index=3,
    format_func=lambda y: f"{y} años",
    help="Años desde hoy hasta la meta de retiro.",
)
initial_value = st.sidebar.number_input(
    "Capital inicial (USD)",
    min_value=1_000,
    max_value=10_000_000,
    value=100_000,
    step=5_000,
    format="%d",
)
annual_withdrawal = st.sidebar.number_input(
    "Retiro anual (USD, 0 = acumulación)",
    min_value=0,
    max_value=500_000,
    value=0,
    step=1_000,
    format="%d",
    help="Cuánto retirás cada año (fase de desacumulación). 0 si todavía estás acumulando.",
)
target_value = st.sidebar.number_input(
    "Meta de retiro (USD)",
    min_value=0,
    max_value=20_000_000,
    value=500_000,
    step=10_000,
    format="%d",
    help="Valor objetivo del portafolio al final del horizonte.",
)
n_sims = st.sidebar.select_slider(
    "Número de simulaciones",
    options=[1_000, 2_000, 5_000, 10_000],
    value=MONTE_CARLO.default_n_sims,
    help="Más simulaciones = más precisión pero más lento. 10 000 tarda < 3s.",
)

# ------------------------------------------------------------------ #
#  Resolve symbols and weights from session state                     #
# ------------------------------------------------------------------ #

opt_result = st.session_state.get("optimizer_prev_result", None)

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

st.caption(
    f"📊 Fuente de datos: **{data_source}**. "
    "Usa el Optimizer para definir pesos específicos por perfil de riesgo."
)

# ------------------------------------------------------------------ #
#  Tabs                                                               #
# ------------------------------------------------------------------ #

tab_mc, tab_stress, tab_custom = st.tabs(
    ["📈 Monte Carlo", "🌪️ Stress Test", "🎯 Escenario personalizado"]
)

# ================================================================== #
#  Tab 1: Monte Carlo                                                 #
# ================================================================== #

with tab_mc:
    run_mc = st.button("▶ Ejecutar simulación Monte Carlo", type="primary")

    if not run_mc and "mc_result" not in st.session_state:
        st.info(
            "Configurá los parámetros en el sidebar y hacé clic en "
            "**▶ Ejecutar simulación Monte Carlo** para comenzar."
        )
    else:
        if run_mc:
            with st.spinner(f"Ejecutando {n_sims:,} simulaciones × {horizon_years} años…"):
                w_np = np.array(weights) if weights else None
                sim  = MonteCarloSimulator(symbols, w_np, seed=42)
                mc   = sim.run(
                    horizon_years=horizon_years,
                    n_sims=n_sims,
                    initial_value=initial_value,
                    annual_withdrawal=annual_withdrawal,
                    target_value=target_value,
                )
            st.session_state["mc_result"] = mc
            st.session_state["mc_params"] = {
                "horizon": horizon_years, "initial": initial_value,
                "withdrawal": annual_withdrawal, "target": target_value,
            }

        mc = st.session_state.get("mc_result")
        if mc is None:
            st.warning("No hay resultado de simulación disponible.")
            st.stop()

        if mc.warnings:
            for w in mc.warnings:
                st.warning(w)

        # KPI row
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Capital inicial",                    f"${initial_value:,.0f}")
        k2.metric(f"Mediana a {horizon_years}a",        f"${mc.median_terminal:,.0f}",
                  delta=f"{mc.median_cagr_pct:.1f}% CAGR")
        k3.metric("Peor 10% (P10)",                     f"${mc.p10_terminal:,.0f}",
                  delta=f"{mc.p10_cagr_pct:.1f}% CAGR", delta_color="inverse")
        k4.metric("Mejor 10% (P90)",                    f"${mc.p90_terminal:,.0f}")
        if target_value > 0:
            k5.metric(
                f"Prob. meta ${target_value:,.0f}",
                f"{mc.prob_achieve_target_pct:.1f}%",
                delta="Probabilidad", delta_color="off",
            )
        else:
            k5.metric("Prob. ruina", f"{mc.prob_ruin_pct:.1f}%", delta_color="inverse")

        st.divider()

        # Fan chart
        if mc.fan_paths:
            _BAND_COLORS = {
                5:  "rgba(220,53,69,0.15)",
                10: "rgba(255,193,7,0.15)",
                25: "rgba(40,167,69,0.15)",
            }
            years_list = mc.years
            fan_chart  = go.Figure()

            for lo, hi in [(5, 95), (10, 90), (25, 75)]:
                lo_vals = [mc.fan_paths[y][lo] for y in years_list]
                hi_vals = [mc.fan_paths[y][hi] for y in years_list]
                fan_chart.add_trace(go.Scatter(
                    x=years_list + years_list[::-1],
                    y=hi_vals + lo_vals[::-1],
                    fill="toself", fillcolor=_BAND_COLORS[lo],
                    line=dict(color="rgba(0,0,0,0)"),
                    name=f"P{lo}–P{hi}", hoverinfo="skip",
                ))

            median_vals = [mc.fan_paths[y][50] for y in years_list]
            fan_chart.add_trace(go.Scatter(
                x=years_list, y=median_vals,
                mode="lines", line=dict(color="#17A2B8", width=2.5),
                name="Mediana (P50)",
            ))
            p10_vals = [mc.fan_paths[y][10] for y in years_list]
            fan_chart.add_trace(go.Scatter(
                x=years_list, y=p10_vals,
                mode="lines", line=dict(color="#DC3545", width=1.5, dash="dot"),
                name="Pesimista (P10)",
            ))
            p90_vals = [mc.fan_paths[y][90] for y in years_list]
            fan_chart.add_trace(go.Scatter(
                x=years_list, y=p90_vals,
                mode="lines", line=dict(color="#28A745", width=1.5, dash="dot"),
                name="Optimista (P90)",
            ))
            if target_value > 0:
                fan_chart.add_hline(
                    y=target_value, line_dash="dash", line_color="gold", line_width=2,
                    annotation_text=f"Meta: ${target_value:,.0f}",
                    annotation_position="right",
                )

            fan_chart.update_layout(
                title=f"Fan Chart — {n_sims:,} simulaciones × {horizon_years} años",
                xaxis_title="Años desde hoy",
                yaxis_title="Valor del portafolio (USD)",
                yaxis_tickformat="$,.0f",
                height=500,
                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
                hovermode="x unified",
            )
            st.plotly_chart(fan_chart, use_container_width=True)
            st.caption(
                "Las bandas muestran el rango de resultados posibles. "
                "La línea azul es la mediana; la roja punteada el peor 10%; la verde el mejor 10%. "
                "⚠️ Ajuste conservador aplicado: +10% volatilidad, −20% retorno esperado vs. historia."
            )

        # Terminal value distribution table
        if mc.fan_paths:
            terminal_data = {
                p: mc.fan_paths[horizon_years][p]
                for p in [5, 10, 25, 50, 75, 90, 95]
            }
            df_terminal = pd.DataFrame([
                {
                    "Percentil": f"P{p}",
                    "Valor USD": v,
                    "CAGR %":    round(((v / initial_value) ** (1 / horizon_years) - 1) * 100, 1) if v > 0 else 0,
                }
                for p, v in terminal_data.items()
            ])
            st.subheader(f"Distribución de resultados a {horizon_years} años")
            st.dataframe(
                df_terminal,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Valor USD": st.column_config.NumberColumn("Valor USD", format="$%,.0f"),
                    "CAGR %":   st.column_config.NumberColumn("CAGR %",   format="%.1f%%"),
                },
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

**Limitaciones:** Esta simulación no predice el futuro. Los retornos pasados no garantizan resultados futuros.
No considera inflación, impuestos, cambios en la asignación de activos, ni eventos imprevisibles.
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
        st.info("Ejecutá el Optimizer primero para obtener pesos por sector.")
    else:
        tester        = StressTester()
        stress_results = tester.run(sector_weights, initial_value=initial_value)

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

        fig_stress = go.Figure()
        names   = [r.scenario.name.split("—")[0].strip() for r in stress_results]
        port_dd = [r.portfolio_drawdown_pct for r in stress_results]
        spy_dd  = [r.benchmark_drawdown_pct  for r in stress_results]

        fig_stress.add_trace(go.Bar(
            name="Cartera actual", x=names, y=port_dd,
            marker_color="#17A2B8", text=[f"{v:.1f}%" for v in port_dd],
            textposition="outside",
        ))
        fig_stress.add_trace(go.Bar(
            name="SPY (benchmark)", x=names, y=spy_dd,
            marker_color="#DC3545", text=[f"{v:.1f}%" for v in spy_dd],
            textposition="outside",
        ))
        fig_stress.update_layout(
            barmode="group",
            title="Caída máxima por escenario: Cartera vs SPY",
            yaxis_title="Caída % (negativo = pérdida)",
            yaxis_tickformat=".0f%",
            height=420,
            legend=dict(yanchor="bottom", y=0.01, xanchor="right", x=0.99),
        )
        st.plotly_chart(fig_stress, use_container_width=True)

        worst = stress_results[0]
        with st.expander(f"📊 Detalle por sector — {worst.scenario.name}"):
            st.markdown(f"**Descripción:** {worst.scenario.description}")
            sec_df = pd.DataFrame([
                {
                    "Sector":           s,
                    "Shock %":          v,
                    "Peso cartera %":   round(sector_weights.get(s, 0), 1),
                    "Impacto %":        round(v * sector_weights.get(s, 0) / 100, 1),
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

        st.caption(
            "Los shocks son estimaciones calibradas con datos históricos reales. "
            "Los resultados son ilustrativos — la magnitud real de una crisis depende "
            "de muchos factores no modelables. ⚠️ No constituye asesoramiento financiero."
        )

# ================================================================== #
#  Tab 3: Escenario personalizado                                     #
# ================================================================== #

with tab_custom:
    st.subheader("Crear escenario personalizado")
    st.caption("Definí una caída uniforme y calculá el impacto sobre tu portafolio.")

    c1, c2, c3 = st.columns(3)
    custom_drop     = c1.slider("Caída del mercado (%)", min_value=-80, max_value=-5, value=-30, step=5)
    custom_months   = c2.slider("Duración (meses)",             min_value=1,  max_value=36,  value=12)
    custom_recovery = c3.slider("Recuperación estimada (meses)", min_value=6,  max_value=120, value=36)

    if st.button("📊 Calcular impacto"):
        if not sector_weights:
            st.warning("Necesitás pesos por sector. Ejecuta el Optimizer primero.")
        else:
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

st.divider()
st.caption(
    "⚠️ **Aviso:** Todas las simulaciones son herramientas educativas. "
    "Los resultados no predicen el futuro ni constituyen asesoramiento financiero. "
    "Consultá con un asesor certificado antes de tomar decisiones de inversión."
)
