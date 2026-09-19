"""Portfolio Tracker — current holdings, P&L and sector allocation."""

from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st
from loguru import logger

from config import ALERTS, PERSONAL_BOOK
from dashboard.shared import (
    _get_ai_config,
    cached_personal_book_analysis,
    plan_price_lookup,
    render_committee_verdict,
    run_holdings_committee,
)
from data.personal_book_convictions import get_convictions, remove_conviction, set_all
from data.plan_context import compute_alignment_trades, drift_breakdown, get_active_plan
from data.product_ux import DOWNSIDE_RATIO_HELP, DOWNSIDE_RATIO_LABEL
from portfolio.tracker import ANNUALIZED_RETURN_CAVEAT, Portfolio

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
col3.metric("Retorno anual",   f"{metrics.annualized_return_pct:.1f}%",
            help=ANNUALIZED_RETURN_CAVEAT)
col4.metric("Sharpe Ratio",    f"{metrics.sharpe_ratio:.2f}")
col5.metric("Max Drawdown",    f"{metrics.max_drawdown_pct:.1f}%")

col1, col2, col3 = st.columns(3)
col1.metric(DOWNSIDE_RATIO_LABEL, f"{metrics.downside_vol_ratio:.2f}",
            help=DOWNSIDE_RATIO_HELP)
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
    width="stretch",
    hide_index=True,
)

# ------------------------------------------------------------------ #
#  Alineación con Mi Plan de Retiro (Fase C)                           #
# ------------------------------------------------------------------ #

_active_plan = get_active_plan()
if _active_plan is not None:
    _target = _active_plan.target_weights()
    _actual = portfolio.get_position_weights()  # {symbol: weight_pct}
    if _target:
        st.divider()
        st.subheader(f"🎯 Alineación con tu Plan: {_active_plan.name}")

        # Canonical drift math (U2-3) — same helper the alert detector and the
        # suggested trades use, so screen and mail cannot diverge.
        _bd = drift_breakdown(_target, _actual)
        _rows = [
            {
                "Ticker": r["symbol"],
                "Objetivo %": round(r["target_pct"], 1),
                "Actual %": round(r["actual_pct"], 1),
                "Drift %": round(r["drift_pct"], 1),
            }
            for r in _bd["rows"]
        ]
        _avg_drift = _bd["total_drift_pct"]

        _mc1, _mc2 = st.columns([1, 3])
        with _mc1:
            _over = _avg_drift > ALERTS.portfolio_rebalance_threshold_pct
            st.metric(
                "Deriva total",
                f"{_avg_drift:.1f}%",
                delta="rebalancear" if _over else "alineado",
                delta_color="inverse" if _over else "normal",
                delta_arrow="off",
            )
        with _mc2:
            if _avg_drift > ALERTS.portfolio_rebalance_threshold_pct:
                st.warning(
                    f"Tu portafolio se desvió **{_avg_drift:.1f}%** de tu plan "
                    f"(umbral {ALERTS.portfolio_rebalance_threshold_pct:.0f}%). "
                    "Considerá rebalancear hacia los pesos objetivo.",
                    icon="🔄",
                )
            else:
                st.success(
                    f"Tu portafolio está alineado con tu plan "
                    f"(deriva {_avg_drift:.1f}% < umbral {ALERTS.portfolio_rebalance_threshold_pct:.0f}%).",
                    icon="✅",
                )

        st.dataframe(
            pd.DataFrame(_rows),
            width="stretch", hide_index=True,
            column_config={
                "Objetivo %": st.column_config.NumberColumn("Objetivo %", format="%.1f%%"),
                "Actual %": st.column_config.NumberColumn("Actual %", format="%.1f%%"),
                "Drift %": st.column_config.NumberColumn("Drift %", format="%.1f%%"),
            },
        )
        st.caption(
            "Las posiciones por encima del objetivo son candidatas a reducir; "
            "las que están por debajo, a sumar. Gestioná el plan activo en 🗺️ Mi Plan de Retiro."
        )

        # ------------------------------------------------------------ #
        #  Trades sugeridos para alinear (Fase E)                       #
        # ------------------------------------------------------------ #
        with st.expander(
            "🛒 Trades sugeridos para alinear con tu plan",
            expanded=_avg_drift > ALERTS.portfolio_rebalance_threshold_pct,
        ):
            _align = compute_alignment_trades(
                _active_plan, _actual, metrics.total_value,
                price_lookup=plan_price_lookup,
            )
            _trades = _align["trades"]
            _as = _align["summary"]
            if not _trades:
                st.success(
                    f"No hay trades sugeridos: ninguna posición se desvía más de "
                    f"{_as['threshold_pct']:.0f}% (o los montos resultantes son menores a "
                    f"\\${_as['min_trade_usd']:,.0f}).",
                    icon="✅",
                )
            else:
                _tc1, _tc2, _tc3 = st.columns(3)
                _tc1.metric("Trades sugeridos", _as["n_suggested"])
                _tc2.metric("Total a comprar", f"${_as['buy_usd']:,.0f}")
                _tc3.metric("Total a vender", f"${_as['sell_usd']:,.0f}")
                _tdf = pd.DataFrame([
                    {
                        "Acción": ("🟢 Comprar" if t["action"] == "comprar" else "🔴 Vender"),
                        "Ticker": t["symbol"] + (" ⭐" if t["is_core"] else ""),
                        "Objetivo %": t["target_pct"],
                        "Actual %": t["actual_pct"],
                        "Drift %": t["drift_pct"],
                        "Monto (USD)": t["amount_usd"],
                        "Precio hoy": t["price_now"],
                        "≈ Shares": t["est_shares"],
                    }
                    for t in _trades
                ])
                st.dataframe(
                    _tdf, width="stretch", hide_index=True,
                    column_config={
                        "Objetivo %": st.column_config.NumberColumn("Objetivo %", format="%.1f%%"),
                        "Actual %": st.column_config.NumberColumn("Actual %", format="%.1f%%"),
                        "Drift %": st.column_config.NumberColumn("Drift %", format="%.1f%%"),
                        "Monto (USD)": st.column_config.NumberColumn("Monto (USD)", format="$%d"),
                        "Precio hoy": st.column_config.NumberColumn("Precio hoy", format="$%.2f"),
                    },
                )
                st.caption(
                    "⭐ = posición del núcleo del plan (priorizada). "
                    f"Solo se sugieren desvíos ≥ {_as['threshold_pct']:.0f}% y montos ≥ "
                    f"\\${_as['min_trade_usd']:,.0f} (configurable en config.py). "
                    "**Orientativo y educativo — no es asesoramiento financiero ni una orden "
                    "de compra/venta.** Ejecutá (o no) manualmente en tu broker, considerando "
                    "impuestos y comisiones."
                )


# ------------------------------------------------------------------ #
#  🏛️ Dictamen del comité sobre tu portfolio actual                   #
# ------------------------------------------------------------------ #

st.divider()
st.subheader("🏛️ Dictamen del comité sobre tu portfolio")
st.caption(
    "Un panel de agentes (Estratega del Plan, Gestor de Riesgo, Macro y el Abogado del Diablo) "
    "debate tu cartera **actual** citando los números ya calculados: riesgo realizado (Sharpe, "
    "beta, drawdown), concentración, caída en crisis y desvío vs tu plan activo. Interpreta, no recalcula."
)
if not values:
    st.info("Cargá posiciones para que el comité pueda evaluar tu portfolio.", icon="💼")
else:
    _cmt_ai = _get_ai_config()
    if not getattr(_cmt_ai, "enabled", False):
        st.info(
            "El comité necesita la IA habilitada. Activala en ⚙️ Settings y elegí un proveedor.",
            icon="🤖",
        )
    else:
        # Position/sector weights from the already-fetched current values (no re-fetch).
        _total_mv = sum(v["market_value"] for v in values.values()) or 1.0
        _pos_w = {s: v["market_value"] / _total_mv * 100 for s, v in values.items()}
        _sec_w: dict[str, float] = {}
        for v in values.values():
            _sec_w[v["sector"]] = _sec_w.get(v["sector"], 0.0) + v["market_value"] / _total_mv * 100

        if st.button("🏛️ Convocar al comité", key="convene_holdings_committee"):
            with st.spinner("El comité está deliberando (varios agentes en paralelo)…"):
                try:
                    st.session_state["holdings_committee_verdict"] = run_holdings_committee(
                        metrics=metrics,
                        sector_weights=_sec_w,
                        position_weights=_pos_w,
                        total_value=metrics.total_value,
                        active_plan=_active_plan,
                    )
                except Exception as exc:  # pragma: no cover - UI guard
                    logger.error(f"holdings committee failed — {exc}")
                    st.error(f"No se pudo convocar al comité: {exc}")

        _verdict = st.session_state.get("holdings_committee_verdict")
        if _verdict is not None:
            _max_w = max(_pos_w.values()) if _pos_w else 0.0
            _footer = (
                f"Sharpe {metrics.sharpe_ratio} · beta {metrics.beta} · "
                f"max DD {metrics.max_drawdown_pct:.0f}% · posición máx {_max_w:.0f}%"
            )
            render_committee_verdict(_verdict, footer_facts=_footer)


# ------------------------------------------------------------------ #
#  📊 Análisis de Sizing — Tu Libro Personal (Fase I)                  #
#  La ventaja competitiva de la concentración (NO es retirement).      #
# ------------------------------------------------------------------ #

if PERSONAL_BOOK.enabled:
    st.divider()
    st.subheader("📊 Análisis de Sizing — Tu Libro Personal (La Ventaja de la Concentración)")
    st.info(
        "Este análisis es para tu **cuenta personal / trading book individual**. Es "
        "intencionalmente **distinto** de las restricciones de diversificación de "
        "*Mi Plan de Retiro*. Como individuo (no fondo) tu ventaja estructural es la "
        "**libertad de concentrar** en pocas ideas de altísima convicción: sin límites "
        "por emisor (~5-10%), sin redenciones forzadas, sin comités de riesgo.",
        icon="🎯",
    )

    # --- Colores de badge por acción ------------------------------------ #
    _ACTION_COLORS = {
        "ACUMULAR_AGRESIVO": "#15803d",
        "ACUMULAR_MODERADO": "#22c55e",
        "AGREGAR_EN_DEBILIDAD": "#2563eb",
        "HOLDEAR": "#ca8a04",
        "TRIM_PARCIAL": "#ea580c",
        "VENDER_PARTE": "#ea580c",
        "VENDER_TODO": "#dc2626",
        "REVISAR_URGENTE": "#9333ea",
    }

    _symbols_now = sorted(values.keys())
    _saved_conv = get_convictions()

    # --- Form de convicciones ------------------------------------------- #
    with st.form("personal_book_convictions_form"):
        st.markdown("**Tu convicción declarada por posición** (subjetiva — separada de los datos)")
        _conv_cols = st.columns(min(4, max(1, len(_symbols_now))))
        _conv_inputs: dict[str, str] = {}
        _levels = ["HIGH", "MEDIUM", "LOW"]
        for _i, _sym in enumerate(_symbols_now):
            _default = _saved_conv.get(_sym, PERSONAL_BOOK.default_conviction)
            _idx = _levels.index(_default) if _default in _levels else 1
            with _conv_cols[_i % len(_conv_cols)]:
                _conv_inputs[_sym] = st.selectbox(_sym, _levels, index=_idx, key=f"conv_{_sym}")
        _save_conv = st.form_submit_button("💾 Guardar convicciones", type="secondary")
        if _save_conv:
            set_all(_conv_inputs)
            st.success("Convicciones guardadas.")
            _saved_conv = _conv_inputs

    _run = st.button(
        "🔍 Ejecutar / refrescar análisis de sizing (precios y fundamentals live)",
        type="primary",
    )

    if _run:
        _conv_for_run = {s: st.session_state.get(f"conv_{s}", _saved_conv.get(s, PERSONAL_BOOK.default_conviction))
                         for s in _symbols_now}
        _pos_tuple = tuple(
            (
                s,
                round(float(values[s]["market_value"]), 2),
                float(portfolio.get_position_weights().get(s, 0.0)),
                float(values[s]["shares"]),
                float(values[s]["avg_cost"]),
                str(values[s]["purchase_date"]),
                str(values[s]["sector"]),
            )
            for s in _symbols_now
        )
        _conv_tuple = tuple(sorted(_conv_for_run.items()))
        _ai = _get_ai_config("detailed_analysis")
        with st.spinner("Analizando tu libro personal…"):
            _book = cached_personal_book_analysis(
                _pos_tuple, _conv_tuple,
                _ai.provider, _ai.model, _ai.enabled, _ai.api_key,
            )
        st.session_state["_personal_book_analysis"] = _book

    _book = st.session_state.get("_personal_book_analysis")
    if _book is not None and _book.num_positions > 0:
        # --- KPIs de concentración -------------------------------------- #
        _k1, _k2, _k3, _k4, _k5 = st.columns(5)
        _k1.metric("Valor del libro", f"${_book.total_value:,.0f}")
        _k2.metric("Posiciones", _book.num_positions)
        _k3.metric("Mayor posición", f"{_book.max_weight_pct:.0f}%")
        _k4.metric("Top-3", f"{_book.top3_weight_pct:.0f}%")
        _k5.metric("Pos. efectivas", f"{_book.effective_positions:.1f}")
        st.caption(_book.concentration_risk_note)

        # --- Recomendaciones por ticker --------------------------------- #
        for _r in _book.recommendations:
            _color = _ACTION_COLORS.get(_r.action, "#6b7280")
            _tgt = f" → objetivo ~{_r.suggested_target_weight_pct:.0f}%" if _r.suggested_target_weight_pct else ""
            _title = f"{_r.action_emoji} {_r.symbol} — {_r.current_weight_pct:.0f}% · {_r.action_label}"
            with st.expander(_title, expanded=False):
                st.markdown(
                    f"<span style='background:{_color};color:white;padding:3px 10px;"
                    f"border-radius:6px;font-weight:600'>{_r.action_label}{_tgt}</span>",
                    unsafe_allow_html=True,
                )
                if _r.suggested_action_detail:
                    st.markdown(f"**Acción:** {_r.suggested_action_detail}")
                st.markdown("**Por qué (drivers):**")
                for _b in _r.justification_bullets:
                    st.markdown(f"- {_b}")
                st.markdown(
                    f"> **🎯 Tesis de concentración (ventaja personal):** {_r.concentration_thesis}"
                )
                if _r.risk_notes:
                    st.markdown("**⚠️ Riesgos:**")
                    for _n in _r.risk_notes:
                        st.markdown(f"- {_n}")
                st.caption(
                    f"Convicción declarada: **{_r.conviction_used}** · "
                    f"Calidad de datos: **{_r.data_quality_level}**"
                )

        # --- Resumen general + estructura sugerida ---------------------- #
        st.markdown("### 📋 Resumen de tu libro")
        st.markdown(_book.overall_summary)
        st.markdown(f"**Estructura sugerida.** {_book.suggested_book_structure}")
        with st.expander("ℹ️ Cómo se ponderan las decisiones (transparencia)"):
            st.markdown(_book.concentration_justification_overall)
        st.caption(_book.disclaimer)

        # --- Export JSON ------------------------------------------------ #
        import json as _json
        st.download_button(
            "⬇️ Exportar análisis (JSON)",
            data=_json.dumps(_book.to_dict(), ensure_ascii=False, indent=2),
            file_name=f"libro_personal_{date.today().isoformat()}.json",
            mime="application/json",
        )
    elif _run:
        st.warning("Sin posiciones para analizar.")


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
    if b1.button("💾 Guardar cambios", type="primary", width="stretch"):
        if new_shares <= 0:
            st.error("La cantidad de shares debe ser mayor a 0.")
        elif new_cost <= 0:
            st.error("El precio promedio debe ser mayor a 0.")
        else:
            portfolio.update_position(sym, new_shares, new_cost, str(new_date), new_notes)
            st.session_state.portfolio = portfolio
            st.session_state["_portfolio_msg"] = f"✅ Posición {sym} actualizada."
            st.rerun()
    if b2.button("Cancelar", width="stretch"):
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
    if b1.button("Sí, eliminar", type="primary", width="stretch"):
        portfolio.remove_position(sym)
        remove_conviction(sym)
        st.session_state.portfolio = portfolio
        st.session_state["_portfolio_msg"] = f"🗑️ Posición {sym} eliminada."
        st.rerun()
    if b2.button("Cancelar", width="stretch"):
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
    st.plotly_chart(fig, width="stretch")

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
    st.plotly_chart(fig, width="stretch")
