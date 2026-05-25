"""Opportunity Screener — ranked table of the full ticker universe."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.shared import (
    _analyse_universe_parallel,
    _get_ai_config,
)
from data.preferences import UserPreferences

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("🏠 Opportunity Screener")
st.caption(
    "Análisis fundamental + técnico del universo completo. "
    "Cache de 1h por ticker — warm cache es instantáneo. "
    "Usá **🔍 Stock Analysis** para profundizar en cualquier ticker."
)

_prefs: UserPreferences = st.session_state.user_prefs

tickers = st.session_state.universe
max_tickers = st.sidebar.slider(
    "Max tickers to screen", 5, len(tickers), len(tickers),
    help="Reducí el número para ver resultados más rápido. Los primeros N tickers del universo son analizados.",
)
selected = tickers[:max_tickers]

if st.sidebar.button(
    "💾 Guardar como favorito",
    help="Guarda el universo como favorito y lo restaura en próximas sesiones",
):
    _prefs.last_used_universe = list(st.session_state.universe)
    _prefs.favorite_universe = list(st.session_state.universe)
    _prefs.save()
    st.toast("Universo guardado como favorito", icon="💾")

# Quick-add to watchlist from Screener sidebar
st.sidebar.divider()
st.sidebar.subheader("📋 Watchlist")
if _prefs.watched_tickers:
    st.sidebar.caption(f"{len(_prefs.watched_tickers)} tickers seguidos")
_wl_input = st.sidebar.text_input(
    "Agregar a watchlist",
    placeholder="AAPL…",
    label_visibility="collapsed",
    key="screener_wl_input",
).upper().strip()
if st.sidebar.button("➕ Agregar", key="screener_wl_btn") and _wl_input:
    if _prefs.watch(_wl_input):
        st.session_state.user_prefs = _prefs
        st.sidebar.success(f"✓ {_wl_input} agregado")
    else:
        st.sidebar.info(f"{_wl_input} ya está en la watchlist.")

col_btn, col_hint = st.columns([1, 4])
with col_btn:
    refresh = st.button("🔄 Refresh Analysis", type="primary", use_container_width=True)
with col_hint:
    st.caption("⚡ El análisis corre en paralelo. Primera vez ~15s · Después usa cache.")

if refresh:
    st.cache_data.clear()

progress = st.progress(0)
status = st.empty()

ai_cfg = _get_ai_config(context="screener")
rows = _analyse_universe_parallel(selected, ai_cfg, progress, status)

progress.empty()
status.empty()

# Auto-save last_used_universe silently after each successful run
if rows and list(st.session_state.universe) != _prefs.last_used_universe:
    _prefs.last_used_universe = list(st.session_state.universe)
    _prefs.save()

# Offer to save as favorite if universe differs from saved favorite
if rows and list(st.session_state.universe) != _prefs.favorite_universe:
    if st.sidebar.button(
        "⭐ Guardar como favorito",
        help=(
            f"Tu favorito actual tiene {len(_prefs.favorite_universe)} tickers. "
            "Reemplazar con el universo actual."
        ),
    ):
        _prefs.favorite_universe = list(st.session_state.universe)
        _prefs.save()
        st.toast("Universo guardado como favorito", icon="⭐")

if not rows:
    st.error(
        "No se pudieron obtener datos. Verificá la conexión a internet y volvé a intentar. "
        "Si el problema persiste, reducí el universo en **⚙️ Settings**."
    )
    st.stop()

df = pd.DataFrame(rows).sort_values("Adj. Score", ascending=False)

# Summary metrics
col1, col2, col3, col4 = st.columns(4)
buy_count  = df["Signal"].str.contains("BUY").sum()
hold_count = df["Signal"].str.contains("HOLD").sum()
sell_count = df["Signal"].str.contains("SELL|REDUCE|AVOID").sum()
col1.metric(
    "Strong/Buy signals", buy_count,
    help="Tickers con score ajustado ≥ 60 y señal técnica positiva",
)
col2.metric("Hold signals", hold_count,
    help="Tickers con señal neutral — mantener si ya están en cartera",
)
col3.metric("Sell/Reduce signals", sell_count,
    help="Tickers con fundamentos débiles o deterioro técnico",
)
col4.metric("Stocks screened", len(df))

# Table
st.dataframe(
    df[[
        "Ticker", "Company", "Sector", "Signal", "Score Bar",
        "Consistency", "Piotroski", "Moat Score", "Moat",
        "Technical", "P/E", "ROE %", "Rev CAGR 5Y", "Div Yield %", "MoS %", "Price",
    ]].rename(columns={
        "Consistency": "Consist./15",
        "Piotroski":   "Piotroski/9",
        "Moat Score":  "Moat/20",
    }),
    use_container_width=True,
    hide_index=True,
)

# Score distribution chart
fig = px.bar(
    df.sort_values("Adj. Score", ascending=True),
    x="Adj. Score",
    y="Ticker",
    orientation="h",
    color="Adj. Score",
    color_continuous_scale="RdYlGn",
    range_color=[0, 100],
    title="Adjusted Score Ranking (Base + Consistency + Piotroski + Moat)",
    labels={"Adj. Score": "Score Ajustado"},
)
fig.add_vline(x=75, line_dash="dash", line_color="green",  annotation_text="Strong Buy ≥75")
fig.add_vline(x=60, line_dash="dash", line_color="orange", annotation_text="Buy ≥60")
fig.update_layout(height=max(400, len(df) * 22), yaxis_title="")
st.plotly_chart(fig, use_container_width=True)

st.caption(
    "💡 Hacé clic en cualquier ticker en la tabla y luego abrí **🔍 Stock Analysis** "
    "para ver el análisis completo con Piotroski, Moat y AI."
)
