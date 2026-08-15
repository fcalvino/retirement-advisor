"""Opportunity Screener — ranked table of the full ticker universe."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.shared import (
    _analyse_universe_parallel,
    _get_ai_config,
    custom_source_badge,
    data_quality_badge,
    render_calc_badge,
)
from data.preferences import UserPreferences
from data.product_ux import second_source_quality_signal

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("🏠 Opportunity Screener")
st.caption(
    "Análisis fundamental + técnico del universo completo. "
    "Cache de 1h por ticker — warm cache es instantáneo. "
    "Usá **🔍 Stock Analysis** para profundizar en cualquier ticker."
)

# ------------------------------------------------------------------ #
#  Defensive guard for st.navigation() (prevents crash on direct nav)
# ------------------------------------------------------------------ #
if "user_prefs" not in st.session_state or "universe" not in st.session_state:
    st.warning(
        "⚠️ La aplicación aún no está inicializada. "
        "Por favor volvé a la página **Inicio** (en el menú de la izquierda) y esperá a que cargue completamente. "
        "Luego navegá a Screener, Optimizer o Simulaciones."
    )
    st.stop()

_prefs: UserPreferences = st.session_state.user_prefs
tickers = st.session_state.universe
max_tickers = st.sidebar.slider(
    "Max tickers to screen", 5, len(tickers), len(tickers),
    help="Reducí el número para ver resultados más rápido. Los primeros N tickers del universo son analizados.",
)
selected = tickers[:max_tickers]

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
    refresh = st.button("🔄 Refresh Analysis", type="primary", width="stretch")
with col_hint:
    st.caption("⚡ El análisis corre en paralelo. Primera vez ~15s · Después usa cache.")

_sel_key = tuple(selected)
_cached_rows = st.session_state.get("screener_rows")
_cached_key = st.session_state.get("screener_rows_key")

if refresh:
    st.cache_data.clear()
    _cached_rows = None

# Show the last run instantly instead of a blank page; only (re)analyse when
# the user asks for a refresh or the selected universe changed.
if _cached_rows is not None and _cached_key == _sel_key:
    rows = _cached_rows
    _when = st.session_state.get("screener_rows_at", "")
    st.caption(
        f"📋 Mostrando la última corrida{f' ({_when})' if _when else ''} · "
        f"{len(rows)} tickers. Tocá **🔄 Refresh Analysis** para actualizar."
    )
else:
    progress = st.progress(0)
    status = st.empty()

    ai_cfg = _get_ai_config(context="screener")
    rows = _analyse_universe_parallel(selected, ai_cfg, progress, status)

    progress.empty()
    status.empty()

    if rows:
        from datetime import datetime
        st.session_state["screener_rows"] = rows
        st.session_state["screener_rows_key"] = _sel_key
        st.session_state["screener_rows_at"] = datetime.now().strftime("%d/%m %H:%M")


if not rows:
    st.error(
        "No se pudieron obtener datos. Verificá la conexión a internet y volvé a intentar. "
        "Si el problema persiste, reducí el universo en **⚙️ Settings**."
    )
    st.info(
        "💡 Mientras tanto: andá a **Stock Analysis** y probá AAPL, o cargá un "
        "**plan de ejemplo** en Mi Plan para ver el producto con datos.",
        icon="🧭",
    )
    st.stop()

df = pd.DataFrame(rows).sort_values("Adj. Score", ascending=False)
render_calc_badge("ranking del universo — fórmulas + reglas; la IA solo si está activada en screener")

# Item 3 — mark each ticker's source (curated vs user-added custom).
df["Fuente"] = df["Ticker"].apply(custom_source_badge)
_n_custom = int((df["Fuente"] == "⚠️ Custom").sum())
if _n_custom:
    st.warning(
        f"🧪 {_n_custom} ticker(s) **personalizado(s)** en este universo. Su scoring y "
        "calidad de datos pueden ser parciales — están marcados como **⚠️ Custom** en la "
        "columna *Fuente*. Tratalos como experimentales.",
        icon="⚠️",
    )

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

# Data-quality + second-source path (backlog 4 / 9) on the decision surface
_sig_home = second_source_quality_signal(
    None,
    data_quality={"level": "partial" if _n_custom else "good", "stale": False},
)
st.caption(f"🔬 {_sig_home['message']} · En **Stock Analysis** podés reconciliar SEC vs Yahoo por ticker.")
if "Datos" in df.columns:
    _dq_poor    = df["Datos"].str.contains("🔴").sum()
    _dq_partial = df["Datos"].str.contains("🟡").sum()
    _dq_stale   = df["Datos"].str.contains("⏳").sum()
    if _dq_poor or _dq_partial or _dq_stale:
        _parts = []
        if _dq_poor:
            _parts.append(f"🔴 {_dq_poor} con datos pobres")
        if _dq_partial:
            _parts.append(f"🟡 {_dq_partial} con datos parciales")
        if _dq_stale:
            _parts.append(f"⏳ {_dq_stale} con cache viejo")
        st.warning(
            "**Calidad de datos (yfinance):** " + " · ".join(_parts) + ". "
            "Los tickers con datos incompletos reciben scores neutrales en las métricas "
            "faltantes — revisá la columna **Datos** antes de confiar en su ranking. "
            "Usá 🔄 Refresh Analysis para refrescar el cache.",
            icon="🧪",
        )

# Table
st.dataframe(
    df[[
        "Ticker", "Company", "Sector", "Fuente", "Signal", "Score Bar",
        "Consistency", "Piotroski", "Moat Score", "Moat", "Viento",
        "Technical", "P/E", "ROE %", "Rev CAGR 5Y", "Div Yield %", "MoS %", "Price", "Datos",
    ]].rename(columns={
        "Consistency": "Consist./15",
        "Piotroski":   "Piotroski/9",
        "Moat Score":  "Moat/20",
    }),
    width="stretch",
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
st.plotly_chart(fig, width="stretch")

st.caption(
    "💡 Hacé clic en cualquier ticker en la tabla y luego abrí **🔍 Stock Analysis** "
    "para ver el análisis completo con Piotroski, Moat y AI. "
    "🌬️ **Viento** = cola de viento estructural sector-país (dato curado, ej. Vaca Muerta "
    "para energía argentina) — outlook a la fecha de curaduría, no garantía."
)
