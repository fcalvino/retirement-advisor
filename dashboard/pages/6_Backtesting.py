"""Backtesting Engine — historical strategy simulation vs benchmark."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from loguru import logger

from analysis.backtesting import BacktestEngine, BacktestResult
from config import BACKTEST
from dashboard.shared import _get_ai_config, cached_full_analysis

# ------------------------------------------------------------------ #
#  Page config                                                         #
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="Backtesting — Retirement Advisor",
    page_icon="📊",
    layout="wide",
)

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("📊 Backtesting Engine")
st.caption(
    "Simula una cartera equal-weight de los top-N tickers por score ajustado "
    "y compara su performance histórica vs el benchmark."
)
st.warning(
    "⚠️ **Limitación conocida:** Los scores se calculan con fundamentals actuales "
    "(yfinance no provee snapshots históricos). Las métricas de precio (CAGR, Sharpe, "
    "Drawdown) son limpias. Los resultados miden si las empresas que hoy puntúan alto "
    "también tuvieron buenos retornos históricos.",
    icon="⚠️",
)

# ------------------------------------------------------------------ #
#  Configuration                                                      #
# ------------------------------------------------------------------ #

with st.expander("⚙️ Configuración del backtest", expanded=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        period_years = st.selectbox(
            "Período", [1, 3, 5, 10],
            index=2,
            format_func=lambda y: f"{y} año{'s' if y > 1 else ''}",
        )
    with col2:
        top_n = st.slider("Top-N tickers", min_value=3, max_value=20, value=BACKTEST.default_top_n)
    with col3:
        benchmark = st.selectbox("Benchmark", ["SPY", "QQQ", "VTI", "BND"], index=0)

    col1, col2 = st.columns(2)
    with col1:
        _FREQ_OPTIONS = {
            "Anual":                        "annual",
            "Trimestral":                   "quarterly",
            "Mensual":                      "monthly",
            "Buy & Hold (sin rebalanceo)":  "buy_and_hold",
        }
        freq_label    = st.selectbox(
            "Frecuencia de rebalanceo",
            list(_FREQ_OPTIONS.keys()),
            index=0,
            help="Con qué frecuencia se redistribuye el capital en partes iguales entre los top-N tickers.",
        )
        rebalance_freq = _FREQ_OPTIONS[freq_label]
    with col2:
        universe_choice = st.selectbox(
            "Universo",
            ["Universo completo", "Solo US Large Cap", "Solo Argentina ADRs"],
        )

_US_LARGE_CAP  = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B",
                  "JPM", "V", "MA", "JNJ", "UNH", "PG", "KO", "HD", "XOM"]
_ARGENTINA_ADR = ["YPF", "PAM", "CEPU", "LOMA", "MELI", "GLOB", "TEO", "EDN"]

if universe_choice == "Solo US Large Cap":
    backtest_universe = _US_LARGE_CAP
elif universe_choice == "Solo Argentina ADRs":
    backtest_universe = _ARGENTINA_ADR
else:
    backtest_universe = [t for t in st.session_state.universe if t not in (benchmark,)]

st.caption(
    f"Universo seleccionado: {len(backtest_universe)} tickers — "
    f"{', '.join(backtest_universe[:10])}{'...' if len(backtest_universe) > 10 else ''}"
)

col_run, col_load = st.columns([2, 1])
run_btn     = col_run.button("▶ Correr Backtest", type="primary", use_container_width=True)
saved_files = BacktestEngine.list_saved()
load_choice = col_load.selectbox(
    "Cargar resultado guardado",
    ["— nuevo —"] + [f.name for f in saved_files[:BACKTEST.results_max_saved]],
    label_visibility="collapsed",
)

# ------------------------------------------------------------------ #
#  Load or run                                                        #
# ------------------------------------------------------------------ #

bt_result: BacktestResult | None = None

if load_choice != "— nuevo —":
    target = next((f for f in saved_files if f.name == load_choice), None)
    if target:
        try:
            bt_result = BacktestEngine.load(target)
            st.info(f"Resultado cargado: **{load_choice}**")
        except Exception as e:
            st.error(f"Error al cargar: {e}")

if run_btn:
    with st.spinner(f"Obteniendo scores para {len(backtest_universe)} tickers..."):
        ai_cfg = _get_ai_config(context="screener")
        fund_results = []
        prog = st.progress(0)
        for i, sym in enumerate(backtest_universe):
            try:
                fund, _tech, _dec = cached_full_analysis(
                    sym, ai_cfg.provider, ai_cfg.model, ai_cfg.enabled, ai_cfg.api_key
                )
                fund_results.append(fund)
            except Exception as exc:
                logger.warning(f"Backtest: skipping {sym} — {exc}")
            prog.progress((i + 1) / len(backtest_universe))
        prog.empty()

    if not fund_results:
        st.error("No se pudieron obtener datos fundamentales.")
        st.stop()

    with st.spinner(f"Calculando backtest {period_years}Y vs {benchmark} ({freq_label})..."):
        engine    = BacktestEngine()
        bt_result = engine.run(
            fund_results,
            period_years=period_years,
            top_n=top_n,
            benchmark=benchmark,
            rebalance_freq=rebalance_freq,
        )
        saved_path = engine.save(bt_result)
        st.success(f"Backtest completado y guardado en `{saved_path.name}`")

# ------------------------------------------------------------------ #
#  Display results                                                    #
# ------------------------------------------------------------------ #

if bt_result is None:
    st.info("Configurá los parámetros y presioná **▶ Correr Backtest**, o cargá un resultado anterior.")
    st.stop()

st.divider()
st.subheader("📈 Performance Summary")

alpha_color = "normal" if bt_result.alpha_pct >= 0 else "inverse"
rebal_label = bt_result.rebalance_freq.replace("_", " ").title()
st.caption(
    f"Rebalanceo: **{rebal_label}** · Top-{bt_result.top_n} "
    f"· {bt_result.period_years}Y · vs {bt_result.benchmark}"
)

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "Portfolio CAGR",
    f"{bt_result.portfolio_cagr_pct:+.1f}%",
    f"α {bt_result.alpha_pct:+.1f}% vs {bt_result.benchmark}",
    delta_color=alpha_color,
)
col2.metric("Benchmark CAGR",         f"{bt_result.benchmark_cagr_pct:+.1f}%")
col3.metric("Total Return Portfolio",  f"{bt_result.portfolio_total_return_pct:+.1f}%")
col4.metric("Total Return Benchmark",  f"{bt_result.benchmark_total_return_pct:+.1f}%")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Sharpe Ratio",    f"{bt_result.portfolio_sharpe:.2f}",
            help="(CAGR − Rf) / Vol total")
col2.metric("Sortino Ratio",   f"{getattr(bt_result, 'portfolio_sortino', 0):.2f}",
            help="(CAGR − Rf) / Vol bajista — penaliza solo pérdidas")
col3.metric("Max Drawdown",    f"{bt_result.portfolio_max_drawdown_pct:.1f}%")
col4.metric("Win Rate vs Bench", f"{bt_result.portfolio_win_rate_pct:.0f}%")
col5.metric("Calmar Ratio",    f"{bt_result.calmar_ratio:.2f}",
            help="CAGR / |Max Drawdown|")

# ------------------------------------------------------------------ #
#  Charts                                                             #
# ------------------------------------------------------------------ #

tab_curve, tab_drawdown, tab_scatter, tab_tickers = st.tabs(
    ["📈 Equity Curve", "📉 Drawdown", "🔵 Score vs Retorno", "📋 Por Ticker"]
)

with tab_curve:
    if bt_result.portfolio_curve and bt_result.benchmark_curve:
        port_s  = pd.Series(bt_result.portfolio_curve)
        bench_s = pd.Series(bt_result.benchmark_curve)
        port_s.index  = pd.to_datetime(port_s.index)
        bench_s.index = pd.to_datetime(bench_s.index)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=port_s.index, y=port_s.values,
            name=f"Top-{bt_result.top_n} Portfolio",
            line=dict(color="#2196F3", width=2.5),
        ))
        fig.add_trace(go.Scatter(
            x=bench_s.index, y=bench_s.values,
            name=bt_result.benchmark,
            line=dict(color="#FF9800", width=2, dash="dot"),
        ))
        fig.update_layout(
            title=f"Equity Curve — {bt_result.period_years}Y (base = 100)",
            yaxis_title="Valor Normalizado",
            height=420,
            legend=dict(orientation="h"),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos de curva de equity.")

with tab_drawdown:
    if bt_result.drawdown_curve:
        dd_s = pd.Series(bt_result.drawdown_curve)
        dd_s.index = pd.to_datetime(dd_s.index)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dd_s.index, y=dd_s.values,
            name="Drawdown %",
            fill="tozeroy",
            line=dict(color="#F44336", width=1.5),
            fillcolor="rgba(244,67,54,0.15)",
        ))
        fig.update_layout(
            title="Portfolio Drawdown",
            yaxis_title="Drawdown %",
            height=300,
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

with tab_scatter:
    if bt_result.score_vs_return:
        scatter_df = pd.DataFrame(bt_result.score_vs_return)
        fig = px.scatter(
            scatter_df,
            x="score", y="cagr_pct", text="symbol",
            color="cagr_pct", color_continuous_scale="RdYlGn",
            size=[8] * len(scatter_df),
            title="Score Ajustado vs CAGR Histórico",
            labels={"score": "Score Ajustado", "cagr_pct": "CAGR % (histórico)"},
        )
        fig.update_traces(textposition="top center", marker=dict(size=10))
        if len(scatter_df) > 3:
            corr = scatter_df["score"].corr(scatter_df["cagr_pct"])
            fig.add_annotation(
                xref="paper", yref="paper", x=0.02, y=0.97,
                text=f"Correlación score↔CAGR: r = {corr:.2f}",
                showarrow=False,
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#888",
            )
        fig.add_hline(
            y=bt_result.benchmark_cagr_pct,
            line_dash="dash", line_color="orange",
            annotation_text=f"{bt_result.benchmark} CAGR",
        )
        fig.update_layout(height=480, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Cada punto es un ticker del universo. La línea naranja es el CAGR del benchmark.")

with tab_tickers:
    if bt_result.ticker_results:
        rows = [
            {
                "Ticker":        t.symbol,
                "Score":         t.score,
                "CAGR %":        t.cagr_pct,
                "Alpha %":       t.alpha_pct,
                "Sharpe":        t.sharpe,
                "Sortino":       getattr(t, "sortino", 0),
                "Max DD %":      t.max_drawdown_pct,
                "Volatilidad %": t.volatility_pct,
                "Win Rate %":    t.win_rate_pct,
                "Retorno Total %": t.total_return_pct,
                "En Portfolio":  "✅" if t.symbol in [
                    r["symbol"] for r in bt_result.score_vs_return[:bt_result.top_n]
                ] else "",
            }
            for t in sorted(bt_result.ticker_results, key=lambda x: x.score, reverse=True)
        ]
        tdf = pd.DataFrame(rows)
        st.dataframe(
            tdf,
            use_container_width=True,
            hide_index=True,
            column_config={
                "CAGR %":    st.column_config.NumberColumn(format="%.1f%%"),
                "Alpha %":   st.column_config.NumberColumn(format="%.1f%%"),
                "Sharpe":    st.column_config.NumberColumn(format="%.2f"),
                "Sortino":   st.column_config.NumberColumn(format="%.2f"),
                "Max DD %":  st.column_config.NumberColumn(format="%.1f%%"),
                "Win Rate %": st.column_config.NumberColumn(format="%.0f%%"),
            },
        )
        csv = tdf.to_csv(index=False)
        st.download_button(
            "⬇️ Descargar CSV",
            data=csv,
            file_name=f"backtest_{bt_result.period_years}y_{bt_result.run_date[:10]}.csv",
            mime="text/csv",
        )

if bt_result.notes:
    with st.expander("📝 Notas del backtest"):
        for note in bt_result.notes:
            st.caption(note)
