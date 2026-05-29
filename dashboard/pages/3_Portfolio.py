"""Portfolio Tracker — current holdings, P&L and sector allocation."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("💼 Mi Portfolio")

# ------------------------------------------------------------------ #
#  Defensive guard for st.navigation() direct page access             #
# ------------------------------------------------------------------ #
if "portfolio" not in st.session_state:
    st.session_state.portfolio = Portfolio()

portfolio: Portfolio = st.session_state.portfolio

# One-shot success message from a previous edit/delete action
if "_portfolio_msg" in st.session_state:
    st.success(st.session_state.pop("_portfolio_msg"))

if not portfolio.positions:
    st.info(
        "Sin posiciones todavía. Analizá una acción en **🔍 Stock Analysis** "
        "y usá el botón **Agregar al Portfolio** para comenzar."
    )
    st.stop()

values = portfolio.get_current_values()
metrics = portfolio.compute_metrics()

# Summary metrics
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Valor total",     f"${metrics.total_value:,.0f}")
col2.metric("P&L total",       f"${metrics.total_pnl:,.0f}", f"{metrics.total_pnl_pct:.1f}%")
col3.metric("Retorno anual",   f"{metrics.annualized_return_pct:.1f}%")
col4.metric("Sharpe Ratio",    f"{metrics.sharpe_ratio:.2f}")
col5.metric("Max Drawdown",    f"{metrics.max_drawdown_pct:.1f}%")

col1, col2, col3 = st.columns(3)
col1.metric("Sortino Ratio",   f"{metrics.sortino_ratio:.2f}")
col2.metric("Beta del portfolio", f"{metrics.beta:.2f}")
col3.metric("Posiciones",      metrics.num_positions)

st.divider()

# Holdings table (read-only overview, sortable)
st.subheader("📊 Posiciones actuales")
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

# ------------------------------------------------------------------ #
#  Edit / Delete dialogs                                               #
# ------------------------------------------------------------------ #


@st.dialog("✏️ Editar posición")
def _edit_position_dialog(sym: str) -> None:
    pos = portfolio.positions.get(sym)
    if pos is None:
        st.error("La posición ya no existe.")
        return

    st.text_input("Ticker", value=sym, disabled=True)

    c1, c2 = st.columns(2)
    new_shares = c1.number_input(
        "Cantidad de Shares", min_value=0.0, value=float(pos.shares),
        step=1.0, format="%.4f",
    )
    new_cost = c2.number_input(
        "Avg Cost (USD)", min_value=0.0, value=float(pos.avg_cost),
        step=0.01, format="%.2f",
    )

    try:
        _pd_val = date.fromisoformat(pos.purchase_date)
    except (ValueError, TypeError):
        _pd_val = date.today()
    new_date = st.date_input("Fecha de compra (opcional)", value=_pd_val)
    new_notes = st.text_area("Notas (opcional)", value=pos.notes or "")

    st.caption(f"Nuevo Cost Basis: **${new_shares * new_cost:,.2f}**")

    b1, b2 = st.columns(2)
    if b1.button("💾 Guardar cambios", type="primary", use_container_width=True):
        if new_shares <= 0:
            st.error("La cantidad de shares debe ser mayor a 0.")
        elif new_cost <= 0:
            st.error("El precio promedio debe ser mayor a 0.")
        else:
            portfolio.update_position(sym, new_shares, new_cost, str(new_date), new_notes)
            st.session_state.portfolio = portfolio
            st.session_state["_portfolio_msg"] = f"✅ Posición {sym} actualizada."
            st.rerun()
    if b2.button("Cancelar", use_container_width=True):
        st.rerun()


@st.dialog("🗑️ Eliminar posición")
def _delete_position_dialog(sym: str) -> None:
    pos = portfolio.positions.get(sym)
    if pos is None:
        st.error("La posición ya no existe.")
        return

    st.warning(
        f"¿Seguro que querés eliminar **{sym}** "
        f"({pos.shares:g} acciones @ ${pos.avg_cost:,.2f})?\n\n"
        "Esta acción no se puede deshacer."
    )

    b1, b2 = st.columns(2)
    if b1.button("Sí, eliminar", type="primary", use_container_width=True):
        portfolio.remove_position(sym)
        st.session_state.portfolio = portfolio
        st.session_state["_portfolio_msg"] = f"🗑️ Posición {sym} eliminada."
        st.rerun()
    if b2.button("Cancelar", use_container_width=True):
        st.rerun()


# ------------------------------------------------------------------ #
#  Manage positions — per-row edit / delete                            #
# ------------------------------------------------------------------ #

st.subheader("⚙️ Gestionar posiciones")
st.caption("Editá cantidad, precio promedio, fecha y notas, o eliminá una posición. Los cálculos se actualizan al instante.")

_widths = [1.2, 1, 1, 1.3, 1, 0.7, 0.8]
_hdr = st.columns(_widths)
for _c, _label in zip(_hdr, ["Ticker", "Shares", "Avg Cost", "Mkt Value", "P&L %", "Editar", "Borrar"]):
    _c.markdown(f"**{_label}**")

for sym, v in values.items():
    r = st.columns(_widths)
    r[0].write(f"**{sym}**")
    r[1].write(f"{v['shares']:g}")
    r[2].write(f"${v['avg_cost']:,.2f}")
    r[3].write(f"${v['market_value']:,.0f}")
    _pnl_pct = v["pnl_pct"]
    _color = "#16a34a" if _pnl_pct >= 0 else "#dc2626"
    r[4].markdown(f"<span style='color:{_color};font-weight:600'>{_pnl_pct:+.1f}%</span>", unsafe_allow_html=True)
    if r[5].button("✏️", key=f"edit_{sym}", help=f"Editar {sym}"):
        _edit_position_dialog(sym)
    if r[6].button("🗑️", key=f"del_{sym}", help=f"Eliminar {sym}"):
        _delete_position_dialog(sym)

# Charts
st.divider()
col1, col2 = st.columns(2)
with col1:
    sector_weights = portfolio.get_sector_weights()
    fig = px.pie(
        names=list(sector_weights.keys()),
        values=list(sector_weights.values()),
        title="Distribución sectorial",
        hole=0.4,
    )
    st.plotly_chart(fig, use_container_width=True)

with col2:
    pos_weights = portfolio.get_position_weights()
    fig = px.bar(
        x=list(pos_weights.keys()),
        y=list(pos_weights.values()),
        title="Peso por posición (%)",
        color=list(pos_weights.values()),
        color_continuous_scale="Blues",
    )
    fig.add_hline(y=8, line_dash="dash", line_color="red", annotation_text="Máx 8%")
    fig.update_layout(yaxis_title="%", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
