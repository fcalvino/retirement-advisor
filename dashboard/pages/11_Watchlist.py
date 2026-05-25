"""Watchlist — monitoreá tickers de interés con alertas de precio."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.shared import (
    _MOAT_EMOJI,
    ACTION_COLOR,
    _fetch_universe_parallel,
    _get_ai_config,
)
from data.preferences import UserPreferences

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("📋 Watchlist")

_prefs: UserPreferences = st.session_state.user_prefs

# ------------------------------------------------------------------ #
#  Empty state                                                         #
# ------------------------------------------------------------------ #

if not _prefs.watched_tickers:
    st.info(
        "Tu watchlist está vacía. "
        "Agregá tickers desde **🔍 Stock Analysis** (botón 'Agregar a Watchlist') "
        "o desde el panel lateral del **🏠 Screener**."
    )
    st.subheader("Agregar ticker a la watchlist")
    c1, c2 = st.columns([2, 1])
    with c1:
        new_sym = st.text_input("Ticker", placeholder="AAPL, MSFT, YPF…").upper().strip()
    with c2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Agregar", type="primary") and new_sym:
            if _prefs.watch(new_sym):
                st.session_state.user_prefs = _prefs
                st.toast(f"{new_sym} agregado a la watchlist", icon="📋")
                st.rerun()
            else:
                st.warning(f"{new_sym} ya está en la watchlist.")
    st.stop()

# ------------------------------------------------------------------ #
#  Fetch analysis for all watchlist tickers in parallel               #
# ------------------------------------------------------------------ #

ai_cfg = _get_ai_config(context="screener")

wl_key = tuple(sorted(_prefs.watched_tickers))
if (
    "wl_results" not in st.session_state
    or st.session_state.get("wl_key") != wl_key
):
    n = len(_prefs.watched_tickers)
    st.info(f"⚡ Analizando {n} tickers de la watchlist…")
    prog = st.progress(0)
    stat = st.empty()
    raw  = _fetch_universe_parallel(_prefs.watched_tickers, ai_cfg, prog, stat, label="Watchlist")
    prog.empty()
    stat.empty()
    st.session_state.wl_results = raw
    st.session_state.wl_key     = wl_key

raw_results: list[tuple] = st.session_state.wl_results

# Build lookup: symbol → (fund, tech, decision)
_analysis: dict[str, tuple] = {sym: (fund, tech, dec) for sym, fund, tech, dec in raw_results}

# Current prices dict for alert checking
prices_now = {sym: fund.current_price for sym, fund, _t, _d in raw_results if fund.current_price}

# ------------------------------------------------------------------ #
#  Check & display triggered price alerts                              #
# ------------------------------------------------------------------ #

newly_triggered = _prefs.check_price_alerts(prices_now)
if newly_triggered:
    st.session_state.user_prefs = _prefs  # sync mutated prefs
    for alert in newly_triggered:
        cond_str = "superó" if alert["condition"] == "above" else "cayó por debajo de"
        st.warning(
            f"🔔 **{alert['symbol']}** {cond_str} **${alert['target']:,.2f}** "
            f"(precio actual: ${prices_now.get(alert['symbol'], 0):,.2f})",
            icon="🔔",
        )

# Also show previously triggered alerts that haven't been cleared
for alert in _prefs.price_alerts:
    if alert.get("triggered") and alert not in newly_triggered:
        cond_str = "superó" if alert["condition"] == "above" else "cayó por debajo de"
        st.warning(
            f"🔔 **{alert['symbol']}** {cond_str} **${alert['target']:,.2f}** "
            f"(alerta cumplida — eliminala cuando hayas tomado acción)",
            icon="✅",
        )

# ------------------------------------------------------------------ #
#  Summary metrics                                                    #
# ------------------------------------------------------------------ #

total     = len(_prefs.watched_tickers)
buy_count = sum(
    1 for sym in _prefs.watched_tickers
    if sym in _analysis and "BUY" in _analysis[sym][2].action
)
alert_count = len(_prefs.price_alerts)
triggered_count = sum(1 for a in _prefs.price_alerts if a.get("triggered"))

s1, s2, s3, s4 = st.columns(4)
s1.metric("Tickers en watchlist", total)
s2.metric(
    "En señal BUY",
    f"{buy_count}/{total}",
    help="Tickers con señal de compra activa (STRONG BUY o BUY)",
)
s3.metric(
    "Alertas de precio",
    alert_count,
    help="Alertas de precio configuradas",
)
s4.metric(
    "Alertas disparadas",
    triggered_count,
    delta=str(triggered_count) if triggered_count > 0 else None,
    delta_color="inverse" if triggered_count > 0 else "off",
)

# ------------------------------------------------------------------ #
#  Main watchlist table                                               #
# ------------------------------------------------------------------ #

st.subheader("Tickers seguidos")

if not raw_results:
    st.warning("No se pudieron obtener datos. Verificá la conexión a internet.")
else:
    # Build rows
    rows = []
    for sym in _prefs.watched_tickers:
        if sym not in _analysis:
            rows.append({
                "Ticker": sym, "Empresa": "—", "Precio": None,
                "Score": None, "Señal": "—", "Moat": "—",
                "Div %": None, "Alertas": "⚠️ sin datos",
            })
            continue

        fund, tech, dec = _analysis[sym]
        moat_cls  = getattr(fund, "moat_classification", "None")
        sym_alerts = [a for a in _prefs.price_alerts if a.get("symbol") == sym]
        alert_strs = []
        for a in sym_alerts:
            fired = "✅" if a.get("triggered") else ""
            arrow = "▲" if a["condition"] == "above" else "▼"
            alert_strs.append(f"{arrow}${a['target']:,.2f}{fired}")
        action_color = ACTION_COLOR.get(dec.action, "#888")

        rows.append({
            "Ticker":  sym,
            "Empresa": (fund.company_name or sym)[:28],
            "Precio":  fund.current_price,
            "Score":   round(fund.adjusted_score, 1),
            "Señal":   f"{dec.action_emoji} {dec.action}",
            "_color":  action_color,
            "Técnico": tech.signal,
            "Moat":    f"{_MOAT_EMOJI.get(moat_cls, '⚪')} {moat_cls}",
            "Div %":   fund.dividend_yield,
            "Alertas": " · ".join(alert_strs) if alert_strs else "—",
        })

    df = pd.DataFrame(rows)
    display_cols = ["Ticker", "Empresa", "Precio", "Score", "Señal", "Técnico", "Moat", "Div %", "Alertas"]
    st.dataframe(
        df[display_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Precio": st.column_config.NumberColumn("Precio", format="$%.2f"),
            "Score":  st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.1f"
            ),
            "Div %":  st.column_config.NumberColumn("Div %", format="%.2f%%"),
        },
    )

# ------------------------------------------------------------------ #
#  Per-ticker action expanders                                        #
# ------------------------------------------------------------------ #

st.subheader("Acciones por ticker")

for sym in list(_prefs.watched_tickers):
    label = sym
    if sym in _analysis:
        fund, _t, dec = _analysis[sym]
        label = f"{dec.action_emoji} **{sym}** — {(fund.company_name or '')[:30]}"

    with st.expander(label, expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.caption("→ Abrí **🔍 Stock Analysis** y escribí este ticker para el análisis completo.")
            if st.button(f"❌ Quitar {sym} de la watchlist", key=f"rm_{sym}"):
                _prefs.unwatch(sym)
                st.session_state.user_prefs = _prefs
                # Invalidate cached results
                st.session_state.pop("wl_results", None)
                st.session_state.pop("wl_key", None)
                st.toast(f"{sym} eliminado de la watchlist", icon="❌")
                st.rerun()
        with col_b:
            # Quick alert form per ticker
            st.markdown("**🎯 Agregar alerta de precio**")
            ac1, ac2, ac3 = st.columns(3)
            cond_sel = ac1.selectbox(
                "Condición", ["below ▼", "above ▲"], key=f"cond_{sym}",
                label_visibility="collapsed",
            )
            target_price = ac2.number_input(
                "Precio objetivo", min_value=0.01, value=float(
                    _analysis[sym][0].current_price or 100.0
                ) if sym in _analysis else 100.0,
                step=1.0, key=f"target_{sym}",
                label_visibility="collapsed",
                format="%.2f",
            )
            if ac3.button("✚ Agregar", key=f"addalert_{sym}"):
                cond = "below" if "below" in cond_sel else "above"
                _prefs.add_price_alert(sym, cond, target_price)
                st.session_state.user_prefs = _prefs
                arrow = "▼" if cond == "below" else "▲"
                st.toast(
                    f"Alerta: {sym} {arrow}${target_price:,.2f}",
                    icon="🎯",
                )
                st.rerun()

# ------------------------------------------------------------------ #
#  Add ticker section                                                 #
# ------------------------------------------------------------------ #

st.divider()
st.subheader("➕ Agregar ticker a la watchlist")
ca1, ca2 = st.columns([2, 1])
with ca1:
    new_ticker = st.text_input(
        "Ticker a seguir",
        placeholder="AAPL, NVDA, MELI…",
        label_visibility="collapsed",
    ).upper().strip()
with ca2:
    if st.button("Agregar a watchlist", type="primary", use_container_width=True) and new_ticker:
        if _prefs.watch(new_ticker):
            st.session_state.user_prefs = _prefs
            st.session_state.pop("wl_results", None)
            st.session_state.pop("wl_key", None)
            st.toast(f"{new_ticker} agregado a la watchlist", icon="📋")
            st.rerun()
        else:
            st.info(f"{new_ticker} ya está en la watchlist.")

# ------------------------------------------------------------------ #
#  Price alerts management                                            #
# ------------------------------------------------------------------ #

st.divider()
st.subheader("🎯 Alertas de precio activas")

if not _prefs.price_alerts:
    st.caption("No hay alertas configuradas. Usá los formularios por ticker de arriba para agregar una.")
else:
    alert_rows = []
    for a in _prefs.price_alerts:
        current = prices_now.get(a["symbol"])
        arrow   = "▲ sube a" if a["condition"] == "above" else "▼ baja de"
        status  = "✅ Disparada" if a.get("triggered") else "⏳ Esperando"
        diff    = None
        if current and a.get("target"):
            diff = current - a["target"]
        alert_rows.append({
            "Ticker":   a["symbol"],
            "Condición": f"{arrow} ${a['target']:,.2f}",
            "Precio actual": current,
            "Diferencia": diff,
            "Estado":   status,
            "Creada":   a.get("created_at", "—"),
            "_cond":    a["condition"],
        })

    df_alerts = pd.DataFrame(alert_rows)
    st.dataframe(
        df_alerts[["Ticker", "Condición", "Precio actual", "Diferencia", "Estado", "Creada"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Precio actual": st.column_config.NumberColumn("Precio actual", format="$%.2f"),
            "Diferencia":    st.column_config.NumberColumn("Diferencia",    format="$%+.2f"),
        },
    )

    # Remove individual alerts
    st.caption("Eliminar alerta:")
    rem_cols = st.columns(min(len(_prefs.price_alerts), 4))
    for i, alert in enumerate(_prefs.price_alerts):
        arrow = "▲" if alert["condition"] == "above" else "▼"
        label = f"❌ {alert['symbol']} {arrow}${alert['target']:,.2f}"
        with rem_cols[i % 4]:
            if st.button(label, key=f"rmalert_{i}"):
                _prefs.remove_price_alert(alert["symbol"], alert["condition"])
                st.session_state.user_prefs = _prefs
                st.toast("Alerta eliminada", icon="🗑️")
                st.rerun()

    if st.button("🗑️ Limpiar todas las alertas disparadas", type="secondary"):
        _prefs.price_alerts = [a for a in _prefs.price_alerts if not a.get("triggered")]
        _prefs.save()
        st.session_state.user_prefs = _prefs
        st.toast("Alertas disparadas eliminadas", icon="🗑️")
        st.rerun()

# ------------------------------------------------------------------ #
#  Refresh button                                                     #
# ------------------------------------------------------------------ #

st.divider()
if st.button("🔄 Actualizar análisis", type="secondary"):
    st.session_state.pop("wl_results", None)
    st.session_state.pop("wl_key", None)
    st.cache_data.clear()
    st.rerun()
