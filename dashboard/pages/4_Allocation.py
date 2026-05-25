"""Asset Allocation Advisor — age-based allocation with concentration checks."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import plotly.express as px
import streamlit as st

from portfolio.allocation import AllocationAdvisor
from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("📐 Asset Allocation Advisor")

col1, col2 = st.columns(2)
with col1:
    age = st.slider("Your current age", 20, 80, 35)
with col2:
    retirement_age = st.slider("Target retirement age", age + 1, 80, max(age + 5, 65))

portfolio: Portfolio = st.session_state.portfolio
sector_weights   = portfolio.get_sector_weights()   if portfolio.positions else {}
position_weights = portfolio.get_position_weights() if portfolio.positions else {}

advisor = AllocationAdvisor()
advice = advisor.advise(age, retirement_age, sector_weights, position_weights)

# Allocation pie
fig = px.pie(
    names=["US Equities", "International", "Real Estate", "Bonds", "Cash"],
    values=[
        advice.us_large_cap_pct,
        advice.international_pct,
        advice.real_estate_pct,
        advice.bonds_pct,
        advice.cash_pct,
    ],
    title=f"Recommended Allocation — Age {age}",
    color_discrete_sequence=px.colors.qualitative.Set2,
    hole=0.3,
)
st.plotly_chart(fig, use_container_width=True)

# Detail
col1, col2, col3 = st.columns(3)
col1.metric("Total Equities", f"{advice.equity_pct:.0f}%")
col2.metric("Bonds",          f"{advice.bonds_pct:.0f}%")
col3.metric("Cash Buffer",    f"{advice.cash_pct:.0f}%")

st.info(f"💡 {advice.inflation_note}")

if advice.concentration_warnings:
    st.subheader("⚠️ Concentration Issues")
    for w in advice.concentration_warnings:
        st.warning(w)

if advice.rebalancing_actions:
    st.subheader("🔄 Rebalancing Actions")
    for a in advice.rebalancing_actions:
        st.info(f"→ {a}")
