"""Asset Allocation Advisor — age-based allocation with concentration checks."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from dashboard.shared import get_user_prefs
from data.product_ux import (
    DEFENSIVE_SLEEVE_HELP,
    DEFENSIVE_SLEEVE_LABEL,
    defensive_sleeve_caption,
)
from portfolio.allocation import AllocationAdvisor
from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("📐 Asset Allocation Advisor")

# Smart defaults from the personal profile (onboarding — Fase A)
_prefs = get_user_prefs()
_default_age = int(_prefs.age) if getattr(_prefs, "age", 0) else 35
_default_age = min(max(_default_age, 20), 80)
_default_ret = min(max(int(getattr(_prefs, "retirement_age", 65)), _default_age + 1), 80)
if _prefs.is_onboarded:
    st.caption("📋 Valores iniciales tomados de **Mi Perfil** (editable en ⚙️ Settings).")

col1, col2 = st.columns(2)
with col1:
    age = st.slider("Tu edad actual", 20, 80, _default_age)
with col2:
    retirement_age = st.slider("Edad objetivo para el retiro", age + 1, 80, max(age + 1, _default_ret))

portfolio: Portfolio = st.session_state.portfolio
sector_weights   = portfolio.get_sector_weights()   if portfolio.positions else {}
position_weights = portfolio.get_position_weights() if portfolio.positions else {}

advisor = AllocationAdvisor()
# The glide path and the concentration limits both read the risk profile the
# onboarding already asked for (U5-7) — before that, everyone got the
# conservative path regardless of what they answered.
advice = advisor.advise(
    age, retirement_age, sector_weights, position_weights,
    profile=_prefs.default_profile,
)
st.caption(
    f"📊 Calculado · perfil **{advice.profile_name}** — la mezcla acciones/bonos y los "
    f"límites de concentración salen de él. Se cambia en ⚙️ Settings."
)

# Allocation pie
fig = px.pie(
    names=["Acciones EE.UU.", "Internacional", "Bienes Raíces", "Bonos", "Efectivo"],
    values=[
        advice.us_large_cap_pct,
        advice.international_pct,
        advice.real_estate_pct,
        advice.bonds_pct,
        advice.cash_pct,
    ],
    title=f"Asignación Recomendada — Edad {age}",
    color_discrete_sequence=px.colors.qualitative.Set2,
    hole=0.3,
)
st.plotly_chart(fig, width="stretch")

# Detail. The age rule governs the defensive sleeve — bonds *plus* the cash
# buffer — so that is the number shown against it, with the split underneath
# (N9). Showing "Bonos 25 %" alone next to a rule that says 30 read as a 5 pp
# error for one release.
col1, col2 = st.columns(2)
col1.metric("Acciones Totales", f"{advice.equity_pct:.0f}%")
col2.metric(
    DEFENSIVE_SLEEVE_LABEL,
    f"{advice.defensive_pct:.0f}%",
    help=DEFENSIVE_SLEEVE_HELP,
)

sub1, sub2 = st.columns(2)
sub1.metric("↳ Bonos", f"{advice.bonds_pct:.0f}%")
sub2.metric("↳ Buffer de Efectivo", f"{advice.cash_pct:.0f}%")

st.caption(defensive_sleeve_caption(advice))

st.info(f"💡 {advice.inflation_note}")

if advice.concentration_warnings:
    st.subheader("⚠️ Problemas de Concentración")
    for w in advice.concentration_warnings:
        st.warning(w)

if advice.rebalancing_actions:
    st.subheader("🔄 Acciones de Rebalanceo")
    for a in advice.rebalancing_actions:
        st.info(f"→ {a}")
