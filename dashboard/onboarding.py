"""
Lightweight onboarding wizard (Fase A).

Captures the user's personal retirement profile (age, horizon, capital,
savings rate, primary goal, risk tolerance, dividend preference) and persists
it to UserPreferences. Consumed across the app as smart defaults:
  - Optimizer  → risk profile + capital to invest
  - Simulaciones → horizon + initial capital
  - Allocation → age + retirement age

The wizard is deliberately optional and short: a single st.form with
conservative defaults so a user can skip it and still get sensible behavior.
Rendered both on Home (when not yet onboarded) and on Settings ("Mi Perfil").
"""

from __future__ import annotations

import streamlit as st

from dashboard.shared import get_user_prefs, seed_session_defaults_from_profile
from data.preferences import (
    DIVIDEND_PREFERENCE_LABELS,
    RISK_TOLERANCE_TO_PROFILE_NAME,
)
from portfolio.goals import GOAL_TYPE_ICONS, GOAL_TYPE_LABELS

_RISK_OPTIONS = ["conservadora", "moderada", "agresiva"]
_RISK_LABELS = {
    "conservadora": "🛡️ Conservadora — preservar capital, dormir tranquilo",
    "moderada":     "⚖️ Moderada — balance crecimiento / estabilidad",
    "agresiva":     "🚀 Agresiva — maximizar crecimiento, tolero caídas",
}
_DIV_OPTIONS = ["crecimiento", "balance", "ingreso"]


def render_profile_summary(prefs) -> None:
    """Compact read-only summary of the saved personal profile."""
    cols = st.columns(4)
    cols[0].metric("Edad → retiro", f"{prefs.age} → {prefs.retirement_age}")
    cols[1].metric("Horizonte", f"{prefs.primary_horizon_years} años")
    cols[2].metric("Perfil", prefs.default_profile)
    cols[3].metric("Ahorro/mes", f"${prefs.monthly_savings:,.0f}")
    _goal_icon = GOAL_TYPE_ICONS.get(prefs.primary_goal_type, "💼")
    _goal_lbl = GOAL_TYPE_LABELS.get(prefs.primary_goal_type, "Otro")
    st.caption(
        f"Capital actual: **\\${prefs.current_capital:,.0f}** · "
        f"Meta principal: {_goal_icon} **{_goal_lbl}** · "
        f"Preferencia: **{DIVIDEND_PREFERENCE_LABELS.get(prefs.dividend_preference, prefs.dividend_preference)}**"
    )


def render_onboarding_wizard(*, key_prefix: str = "onb") -> bool:
    """Render the personal-profile form. Returns True if it was just saved."""
    prefs = get_user_prefs()

    with st.form(f"{key_prefix}_wizard"):
        c1, c2 = st.columns(2)
        age = c1.number_input(
            "Tu edad actual", min_value=18, max_value=90,
            value=int(prefs.age) if prefs.age else 35, step=1,
            key=f"{key_prefix}_age",
        )
        retirement_age = c2.number_input(
            "Edad objetivo de retiro", min_value=int(age) + 1, max_value=95,
            value=max(int(prefs.retirement_age), int(age) + 1), step=1,
            key=f"{key_prefix}_retage",
            help="Usamos esto para el horizonte de tus proyecciones de largo plazo.",
        )

        c3, c4 = st.columns(2)
        current_capital = c3.number_input(
            "Capital actual a invertir (USD)", min_value=0, max_value=100_000_000,
            value=int(prefs.current_capital), step=5_000, format="%d",
            key=f"{key_prefix}_capital",
        )
        monthly_savings = c4.number_input(
            "Ahorro mensual aproximado (USD)", min_value=0, max_value=1_000_000,
            value=int(prefs.monthly_savings), step=100, format="%d",
            key=f"{key_prefix}_savings",
        )

        goal_keys = list(GOAL_TYPE_ICONS.keys())
        _goal_idx = goal_keys.index(prefs.primary_goal_type) if prefs.primary_goal_type in goal_keys else goal_keys.index("retiro")
        primary_goal_type = st.selectbox(
            "Tu meta principal",
            options=goal_keys,
            index=_goal_idx,
            format_func=lambda k: f"{GOAL_TYPE_ICONS[k]} {GOAL_TYPE_LABELS[k]}",
            key=f"{key_prefix}_goal",
        )

        _risk_idx = _RISK_OPTIONS.index(prefs.risk_tolerance) if prefs.risk_tolerance in _RISK_OPTIONS else 0
        risk_tolerance = st.radio(
            "Tolerancia al riesgo (define tu perfil del Optimizer)",
            options=_RISK_OPTIONS,
            index=_risk_idx,
            format_func=lambda r: _RISK_LABELS[r],
            key=f"{key_prefix}_risk",
        )

        _div_idx = _DIV_OPTIONS.index(prefs.dividend_preference) if prefs.dividend_preference in _DIV_OPTIONS else 1
        dividend_preference = st.radio(
            "Preferencia de inversión",
            options=_DIV_OPTIONS,
            index=_div_idx,
            format_func=lambda d: DIVIDEND_PREFERENCE_LABELS[d],
            horizontal=True,
            key=f"{key_prefix}_div",
        )

        st.caption(
            f"Tu perfil del Optimizer quedará en **{RISK_TOLERANCE_TO_PROFILE_NAME.get(risk_tolerance, 'Conservador')}**. "
            "Podés cambiarlo cuando quieras desde el Optimizer o esta página."
        )
        submitted = st.form_submit_button("💾 Guardar mi perfil", type="primary")

    if submitted:
        prefs.apply_personal_profile(
            age=age,
            retirement_age=retirement_age,
            current_capital=current_capital,
            monthly_savings=monthly_savings,
            risk_tolerance=risk_tolerance,
            primary_goal_type=primary_goal_type,
            dividend_preference=dividend_preference,
        )
        # Refresh Optimizer/Simulaciones defaults from the new profile.
        seed_session_defaults_from_profile(prefs, force=True)
        st.toast("✅ Perfil guardado — el Optimizer y las Simulaciones ya usan tus datos.", icon="🧭")
        return True

    return False
