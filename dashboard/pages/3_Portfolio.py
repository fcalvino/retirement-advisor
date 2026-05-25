"""Portfolio Tracker — current holdings, P&L and sector allocation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("💼 My Portfolio")

portfolio: Portfolio = st.session_state.portfolio

if not portfolio.positions:
    st.info("No positions yet. Analyze a stock and add it from the Stock Analysis page.")
    st.stop()

values = portfolio.get_current_values()
metrics = portfolio.compute_metrics()

# Summary metrics
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Value",   f"${metrics.total_value:,.0f}")
col2.metric("Total P&L",     f"${metrics.total_pnl:,.0f}", f"{metrics.total_pnl_pct:.1f}%")
col3.metric("Ann. Return",   f"{metrics.annualized_return_pct:.1f}%")
col4.metric("Sharpe Ratio",  f"{metrics.sharpe_ratio:.2f}")
col5.metric("Max Drawdown",  f"{metrics.max_drawdown_pct:.1f}%")

col1, col2, col3 = st.columns(3)
col1.metric("Sortino Ratio",  f"{metrics.sortino_ratio:.2f}")
col2.metric("Portfolio Beta", f"{metrics.beta:.2f}")
col3.metric("Positions",      metrics.num_positions)

st.divider()

# Holdings table
st.subheader("Holdings")
rows = list(values.values())
df = pd.DataFrame(rows)
df["pnl_pct"]      = df["pnl_pct"].round(1)
df["pnl"]          = df["pnl"].round(0)
df["market_value"] = df["market_value"].round(0)
df["weight_pct"]   = (df["market_value"] / metrics.total_value * 100).round(1)

st.dataframe(
    df[[
        "symbol", "sector", "shares", "avg_cost", "current_price",
        "cost_basis", "market_value", "pnl", "pnl_pct", "weight_pct",
    ]].rename(columns={
        "symbol":        "Ticker",
        "sector":        "Sector",
        "shares":        "Shares",
        "avg_cost":      "Avg Cost",
        "current_price": "Price",
        "cost_basis":    "Cost Basis",
        "market_value":  "Mkt Value",
        "pnl":           "P&L ($)",
        "pnl_pct":       "P&L %",
        "weight_pct":    "Weight %",
    }),
    use_container_width=True,
    hide_index=True,
)

# Charts
col1, col2 = st.columns(2)
with col1:
    sector_weights = portfolio.get_sector_weights()
    fig = px.pie(
        names=list(sector_weights.keys()),
        values=list(sector_weights.values()),
        title="Sector Allocation",
        hole=0.4,
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    pos_weights = portfolio.get_position_weights()
    fig = px.bar(
        x=list(pos_weights.keys()),
        y=list(pos_weights.values()),
        title="Position Weights (%)",
        color=list(pos_weights.values()),
        color_continuous_scale="Blues",
    )
    fig.add_hline(y=8, line_dash="dash", line_color="red", annotation_text="Max 8%")
    fig.update_layout(yaxis_title="%", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# Remove position
st.divider()
st.subheader("Remove / Trim Position")
col1, col2 = st.columns(2)
with col1:
    sym_to_remove = st.selectbox("Ticker", list(portfolio.positions.keys()))
with col2:
    shares_to_remove = st.number_input("Shares (blank = close all)", min_value=0.0, value=0.0)
if st.button("Remove", type="secondary"):
    portfolio.remove_position(sym_to_remove, shares_to_remove if shares_to_remove > 0 else None)
    st.session_state.portfolio = portfolio
    st.rerun()
