"""Portfolio Optimizer — Mean-Variance optimization with 3 risk profiles."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from config import OPTIMIZER, OPTIMIZER_PROFILES
from dashboard.shared import (
    _MOAT_EMOJI,
    _fetch_universe_parallel,
    _get_ai_config,
)
from data.preferences import UserPreferences
from portfolio.optimizer import PortfolioOptimizer
from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("📈 Portfolio Optimizer")
st.caption(
    "Construye una cartera óptima combinando Score Ajustado, Moat y Dividend Yield "
    "con restricciones de riesgo según tu perfil de retiro. "
    "💵 Todos los valores están denominados en **USD** (los ADRs argentinos cotizan en USD en NYSE/NASDAQ)."
)

_prefs: UserPreferences = st.session_state.user_prefs
portfolio: Portfolio = st.session_state.portfolio

# ------------------------------------------------------------------ #
#  Profile selector — persisted in session state                      #
# ------------------------------------------------------------------ #

_PROFILE_LABELS = {
    "conservative": "🛡️  Conservador",
    "moderate":     "⚖️  Moderado",
    "aggressive":   "🚀 Agresivo",
}
_PROFILE_KEYS = {v: k for k, v in _PROFILE_LABELS.items()}

if "optimizer_profile_key" not in st.session_state:
    _saved_profile = {
        "Conservador": "conservative",
        "Moderado":    "moderate",
        "Agresivo":    "aggressive",
    }.get(_prefs.default_profile, "conservative")
    st.session_state.optimizer_profile_key = _saved_profile

prev_profile_key = st.session_state.optimizer_profile_key
profile_label = st.sidebar.radio(
    "Perfil de riesgo",
    list(_PROFILE_LABELS.values()),
    index=list(_PROFILE_LABELS.keys()).index(prev_profile_key),
    help="Conservador: preserva capital con dividendos. Moderado: balance crecimiento/ingreso. Agresivo: maximiza crecimiento a largo plazo.",
)
profile_key     = _PROFILE_KEYS[profile_label]
profile_changed = profile_key != prev_profile_key
st.session_state.optimizer_profile_key = profile_key
prof = OPTIMIZER_PROFILES[profile_key]

# Auto-save profile on change
if profile_changed and _prefs.default_profile != prof.name:
    _prefs.default_profile = prof.name
    _prefs.save()
    st.toast(f"Perfil '{prof.name}' guardado como favorito", icon="💾")

max_tickers = st.sidebar.slider(
    "Tickers a analizar", 10, len(st.session_state.universe), len(st.session_state.universe),
    help="Reducir el universo acelera el análisis.",
)
selected_universe = st.session_state.universe[:max_tickers]

if st.sidebar.button("🔄 Re-analizar universo", type="secondary"):
    for k in ["optimizer_scored", "optimizer_universe", "optimizer_prev_result"]:
        st.session_state.pop(k, None)
    st.cache_data.clear()

# ------------------------------------------------------------------ #
#  Profile card                                                        #
# ------------------------------------------------------------------ #

_PROFILE_DESC = {
    "conservative": "Preservación de capital + ingreso por dividendos. Volatilidad controlada.",
    "moderate":     "Balance entre crecimiento e ingreso. Exposición al riesgo controlada.",
    "aggressive":   "Maximización de crecimiento a largo plazo. Mayor tolerancia al riesgo.",
}
with st.expander(f"📋 Perfil: **{prof.name}** — {_PROFILE_DESC[profile_key]}", expanded=profile_changed):
    pc1, pc2, pc3, pc4, pc5 = st.columns(5)
    pc1.metric("Pos. máx.",     f"{prof.max_position_pct:.0f}%")
    pc2.metric("Vol. máx.",     f"{prof.max_volatility_pct:.0f}%")
    pc3.metric("Div. mín.",     f"{prof.min_dividend_yield_pct:.1f}%")
    pc4.metric("Sector máx.",   f"{prof.max_sector_pct:.0f}%")
    pc5.metric("Min. posiciones", prof.min_positions)
    st.caption(
        f"Pesos objetivo — Score: {prof.score_weight:.0%} "
        f"· Dividendo: {prof.dividend_weight:.0%} "
        f"· Moat: {prof.moat_weight:.0%}"
    )

# ------------------------------------------------------------------ #
#  Gather scored tickers — cached in session_state per universe       #
# ------------------------------------------------------------------ #

universe_key = tuple(selected_universe)
if "optimizer_scored" not in st.session_state or st.session_state.get("optimizer_universe") != universe_key:
    ai_cfg = _get_ai_config(context="screener")
    n = len(selected_universe)
    st.info(
        f"⚡ Analizando {n} tickers en paralelo… "
        "(primera vez tarda ~15s, luego usa cache instantánea)"
    )
    prog = st.progress(0)
    stat = st.empty()
    raw = _fetch_universe_parallel(selected_universe, ai_cfg, prog, stat, label="Optimizer")
    prog.empty()
    stat.empty()

    scored: list[dict] = [
        {
            "symbol":              sym,
            "adjusted_score":      fund.adjusted_score,
            "total_score":         fund.total_score,
            "dividend_yield":      fund.dividend_yield or 0.0,
            "moat_score":          getattr(fund, "moat_score", 0.0),
            "moat_classification": getattr(fund, "moat_classification", "None"),
            "sector":              fund.sector or "Unknown",
            "company_name":        fund.company_name,
        }
        for sym, fund, _tech, _dec in raw
    ]
    if not scored:
        st.error("No se pudo analizar ningún ticker. Verificá la conexión a internet.")
        st.stop()
    st.session_state.optimizer_scored   = scored
    st.session_state.optimizer_universe = universe_key
else:
    scored = st.session_state.optimizer_scored
    st.caption(
        f"✓ Análisis cacheado — {len(scored)} tickers "
        "· cambia perfil instantáneamente · usa 'Re-analizar' para refrescar datos"
    )

# ------------------------------------------------------------------ #
#  Run optimizer                                                      #
# ------------------------------------------------------------------ #

with st.spinner("Optimizando cartera…"):
    opt = PortfolioOptimizer(profile=profile_key)
    current_weights: dict = {}
    try:
        current_weights = portfolio.get_position_weights()
    except Exception:
        pass
    result = opt.optimize(scored, current_weights=current_weights or None)

# ------------------------------------------------------------------ #
#  Profile-change delta banner                                        #
# ------------------------------------------------------------------ #

if profile_changed and "optimizer_prev_result" in st.session_state:
    prev      = st.session_state.optimizer_prev_result
    prev_name = OPTIMIZER_PROFILES[prev_profile_key].name
    d_ret = result.expected_return_pct - prev.expected_return_pct
    d_vol = result.volatility_pct      - prev.volatility_pct
    d_sh  = result.sharpe_ratio        - prev.sharpe_ratio
    d_div = result.dividend_yield_pct  - prev.dividend_yield_pct

    def _delta_str(v: float, unit: str = "%", positive_good: bool = True) -> str:
        sign  = "+" if v >= 0 else ""
        color = "green" if (v >= 0) == positive_good else "red"
        return f'<span style="color:{color}">{sign}{v:.1f}{unit}</span>'

    st.markdown(
        f"**Cambio de perfil:** {prev_name} → {prof.name} &nbsp;|&nbsp; "
        f"Retorno {_delta_str(d_ret)} &nbsp; "
        f"Volatilidad {_delta_str(d_vol, positive_good=False)} &nbsp; "
        f"Sharpe {_delta_str(d_sh)} &nbsp; "
        f"Div Yield {_delta_str(d_div)}",
        unsafe_allow_html=True,
    )
    prev_w  = {a.symbol: a.weight_pct for a in prev.tickers}
    curr_w  = {a.symbol: a.weight_pct for a in result.tickers}
    all_syms = set(prev_w) | set(curr_w)
    movers = sorted(
        [(s, curr_w.get(s, 0) - prev_w.get(s, 0)) for s in all_syms],
        key=lambda x: -abs(x[1]),
    )[:6]
    mover_parts = [
        f"{sym} {'▲' if delta > 0 else '▼'}{abs(delta):.1f}%"
        for sym, delta in movers
        if abs(delta) >= 0.5
    ]
    if mover_parts:
        st.caption("Principales cambios en posiciones: " + " · ".join(mover_parts))

st.session_state.optimizer_prev_result = result

# ------------------------------------------------------------------ #
#  Status bar                                                         #
# ------------------------------------------------------------------ #

_method_badge = "🧮 Mean-Variance" if result.method == "mean-variance" else "⚖️ Score-weighted"
st.success(f"{_method_badge} · Perfil **{result.profile_name}** · {len(result.tickers)} posiciones")
if result.warnings:
    for w in result.warnings:
        st.warning(w)

# ------------------------------------------------------------------ #
#  Summary metrics                                                    #
# ------------------------------------------------------------------ #

mc1, mc2, mc3, mc4, mc5 = st.columns(5)
mc1.metric("Retorno esperado", f"{result.expected_return_pct:.1f}%")
mc2.metric("Volatilidad",      f"{result.volatility_pct:.1f}%",
           delta=f"límite {prof.max_volatility_pct:.0f}%", delta_color="off")
mc3.metric("Sharpe Ratio",     f"{result.sharpe_ratio:.2f}")
mc4.metric("Div. Yield",       f"{result.dividend_yield_pct:.2f}%",
           delta=f"mín {prof.min_dividend_yield_pct:.1f}%", delta_color="off")
mc5.metric("Score Promedio",   f"{result.adjusted_score_avg:.0f}/100")

# ------------------------------------------------------------------ #
#  Tabs                                                               #
# ------------------------------------------------------------------ #

tab_cart, tab_front, tab_metrics, tab_rebal = st.tabs(
    ["🧺 Cartera", "📉 Frontier", "📊 Métricas", "🔄 Rebalanceo"]
)

# ------------------------------------------------------------------ #
#  Tab 1: Cartera                                                     #
# ------------------------------------------------------------------ #

with tab_cart:
    if not result.tickers:
        st.warning("No hay posiciones en la cartera optimizada.")
    else:
        scored_map = {t["symbol"]: t for t in scored}
        alloc_data = []
        for a in result.tickers:
            t = scored_map.get(a.symbol, {})
            moat_cls = t.get("moat_classification", "None")
            discount_note = f" (−{(1-OPTIMIZER.ars_risk_discount)*100:.0f}% ARS)" if a.score_discounted else ""
            alloc_data.append({
                "Ticker":  a.symbol,
                "Empresa": (t.get("company_name", a.symbol) or a.symbol)[:28],
                "Peso %":  a.weight_pct,
                "Score":   a.adjusted_score,
                "Moat":    f"{_MOAT_EMOJI.get(moat_cls, '⚪')} {moat_cls}",
                "Div %":   a.dividend_yield_pct,
                "Sector":  a.sector,
                "Notas":   ("🇦🇷" + discount_note) if a.is_ars else "",
            })
        df_alloc = pd.DataFrame(alloc_data)

        df_bar = df_alloc[df_alloc["Peso %"] > 0].sort_values("Peso %")
        fig_bar = px.bar(
            df_bar, x="Peso %", y="Ticker", orientation="h",
            color="Score", color_continuous_scale="RdYlGn",
            range_color=[40, 100],
            title="Peso por ticker (coloreado por Score Ajustado)",
            text="Peso %",
        )
        fig_bar.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig_bar.add_vline(
            x=prof.max_position_pct, line_dash="dash", line_color="orange",
            annotation_text=f"máx {prof.max_position_pct:.0f}%",
        )
        fig_bar.update_layout(
            height=max(350, len(df_bar) * 22), yaxis_title="", coloraxis_showscale=False,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        st.dataframe(
            df_alloc,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Peso %": st.column_config.ProgressColumn(
                    "Peso %", min_value=0, max_value=prof.max_position_pct * 1.5, format="%.1f%%"
                ),
                "Score":  st.column_config.NumberColumn("Score", format="%.0f"),
                "Div %":  st.column_config.NumberColumn("Div %", format="%.2f%%"),
            },
        )

        if result.sector_weights:
            col_sec, col_tick = st.columns(2)
            with col_sec:
                sec_df  = pd.DataFrame([{"Sector": k, "Peso %": v} for k, v in result.sector_weights.items()])
                fig_sec = px.pie(sec_df, values="Peso %", names="Sector", title="Por Sector", hole=0.4)
                fig_sec.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig_sec, use_container_width=True)
            with col_tick:
                df_top = df_alloc.nlargest(10, "Peso %")
                others_pct = 100 - df_top["Peso %"].sum()
                if others_pct > 0.5:
                    df_top = pd.concat(
                        [df_top, pd.DataFrame([{"Ticker": "Otros", "Peso %": others_pct}])],
                        ignore_index=True,
                    )
                fig_pie = px.pie(df_top, values="Peso %", names="Ticker", title="Top-10 por Ticker", hole=0.3)
                fig_pie.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig_pie, use_container_width=True)

        if any(a.is_ars for a in result.tickers):
            discount_pct = (1 - OPTIMIZER.ars_risk_discount) * 100
            ars_syms = ", ".join(a.symbol for a in result.tickers if a.is_ars)
            st.info(
                f"🇦🇷 **ADRs argentinos ({ars_syms}):** cotizan y liquidan en **USD** en NYSE/NASDAQ "
                f"— no hay conversión de moneda al comprar. Sin embargo, su valor en pesos argentinos "
                f"es vulnerable a devaluaciones y controles de capital. "
                f"Por eso, en perfil **{prof.name}**, se aplica un descuento de **{discount_pct:.0f}%** "
                "al Score Ajustado al calcular el peso óptimo (no afecta el precio ni el dividend yield reportado)."
            )

    if result.excluded:
        with st.expander(f"Tickers excluidos de la optimización ({len(result.excluded)})"):
            for sym, reason in result.excluded:
                st.caption(f"**{sym}** — {reason}")

# ------------------------------------------------------------------ #
#  Tab 2: Efficient Frontier                                          #
# ------------------------------------------------------------------ #

with tab_front:
    if not result.frontier_returns:
        st.info("Datos de precio insuficientes para calcular la Frontera Eficiente.")
    else:
        fig_front = px.scatter(
            x=result.frontier_vols,
            y=result.frontier_returns,
            color=result.frontier_sharpes,
            color_continuous_scale="RdYlGn",
            labels={
                "x": "Volatilidad % (anual)",
                "y": "Retorno Esperado % (anual)",
                "color": "Sharpe",
            },
            title=f"Frontera Eficiente — Monte Carlo ({OPTIMIZER.frontier_points} carteras)",
        )
        fig_front.add_scatter(
            x=[result.volatility_pct],
            y=[result.expected_return_pct],
            mode="markers",
            marker=dict(size=16, color="blue", symbol="star", line=dict(width=1, color="white")),
            name=f"Cartera {prof.name}",
        )
        fig_front.add_vline(
            x=prof.max_volatility_pct,
            line_dash="dash", line_color="red",
            annotation_text=f"Vol máx. {prof.max_volatility_pct:.0f}%",
            annotation_position="top right",
        )
        fig_front.update_layout(
            height=520, legend=dict(yanchor="bottom", y=0.01, xanchor="right", x=0.99),
        )
        st.plotly_chart(fig_front, use_container_width=True)
        st.caption(
            "La línea roja marca el techo de volatilidad del perfil. "
            "La estrella azul es la cartera óptima (máximo Sharpe dentro de las restricciones)."
        )

# ------------------------------------------------------------------ #
#  Tab 3: Métricas + Constraint Compliance                           #
# ------------------------------------------------------------------ #

with tab_metrics:
    m1, m2 = st.columns(2)

    with m1:
        st.subheader("Estadísticas de cartera")
        st.markdown(f"""
| Métrica | Valor |
|---|---|
| Retorno esperado | **{result.expected_return_pct:.1f}%** anual |
| Volatilidad | **{result.volatility_pct:.1f}%** anual |
| Sharpe Ratio | **{result.sharpe_ratio:.2f}** |
| Dividend Yield | **{result.dividend_yield_pct:.2f}%** |
| Score promedio | **{result.adjusted_score_avg:.0f}**/100 |
| Moat promedio | **{result.moat_score_avg:.1f}**/20 |
| Posiciones | **{len(result.tickers)}** |
| Método | {result.method} |
""")

        st.subheader("Compliance de restricciones")
        _checks = [
            (
                f"Volatilidad ≤ {prof.max_volatility_pct:.0f}%",
                result.volatility_pct <= prof.max_volatility_pct,
                f"{result.volatility_pct:.1f}%",
            ),
            (
                f"Div. Yield ≥ {prof.min_dividend_yield_pct:.1f}%",
                result.dividend_yield_pct >= prof.min_dividend_yield_pct,
                f"{result.dividend_yield_pct:.2f}%",
            ),
            (
                f"Pos. máx. ≤ {prof.max_position_pct:.0f}%",
                all(a.weight_pct <= prof.max_position_pct + 0.1 for a in result.tickers),
                f"máx actual {max((a.weight_pct for a in result.tickers), default=0):.1f}%",
            ),
            (
                f"Sector máx. ≤ {prof.max_sector_pct:.0f}%",
                all(v <= prof.max_sector_pct + 0.1 for v in result.sector_weights.values()),
                f"máx actual {max(result.sector_weights.values(), default=0):.1f}%",
            ),
            (
                f"Posiciones ≥ {prof.min_positions}",
                len(result.tickers) >= prof.min_positions,
                f"{len(result.tickers)} posiciones",
            ),
        ]
        for label, ok, detail in _checks:
            icon = "✅" if ok else "❌"
            st.markdown(f"{icon} **{label}** — {detail}")

    with m2:
        st.subheader("Pesos por sector")
        if result.sector_weights:
            for sector, pct in result.sector_weights.items():
                ratio   = pct / prof.max_sector_pct
                bar_pct = min(int(ratio * 100), 100)
                color   = (
                    "#ff4444" if pct > prof.max_sector_pct
                    else ("#ffbb33" if pct > prof.max_sector_pct * 0.8 else "#00C851")
                )
                st.markdown(
                    f"**{sector}** — {pct:.1f}% / {prof.max_sector_pct:.0f}%"
                    f'<div style="background:#e8e8e8;border-radius:4px;height:8px;margin-bottom:6px;">'
                    f'<div style="width:{bar_pct}%;background:{color};height:8px;border-radius:4px;"></div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

# ------------------------------------------------------------------ #
#  Tab 4: Rebalanceo                                                  #
# ------------------------------------------------------------------ #

with tab_rebal:
    if result.rebalance_frequency:
        _freq_icon = {"Anual": "📅", "Semestral": "🗓️", "Trimestral": "⏱️"}.get(
            result.rebalance_frequency, "📅"
        )
        st.info(
            f"{_freq_icon} **Frecuencia recomendada: {result.rebalance_frequency}** — "
            f"{result.rebalance_rationale}"
        )

    if not result.rebalance_suggestions:
        if not current_weights:
            st.info(
                "Para ver las acciones de rebalanceo específicas, agrega tus posiciones actuales "
                "en la página 💼 **Portfolio**. El optimizador calculará cuánto comprar/vender de cada ticker."
            )
        else:
            st.success("✅ Tu cartera actual ya está alineada con la asignación óptima.")
    else:
        buys  = [s for s in result.rebalance_suggestions if s.action == "BUY"]
        sells = [s for s in result.rebalance_suggestions if s.action == "SELL"]
        holds = [s for s in result.rebalance_suggestions if s.action == "HOLD"]

        rb1, rb2, rb3 = st.columns(3)
        rb1.metric("Compras",   len(buys))
        rb2.metric("Ventas",    len(sells))
        rb3.metric("Sin cambio", len(holds))

        rebal_data = [
            {
                "Ticker":    s.symbol,
                "Actual %":  s.current_pct,
                "Objetivo %": s.target_pct,
                "Δ %":       s.delta_pct,
                "Acción":    s.action,
            }
            for s in result.rebalance_suggestions
            if abs(s.delta_pct) >= 0.5
        ]
        df_rebal = pd.DataFrame(rebal_data)
        if not df_rebal.empty:
            fig_rebal = px.bar(
                df_rebal.sort_values("Δ %"),
                x="Δ %", y="Ticker", orientation="h",
                color="Δ %", color_continuous_scale="RdYlGn",
                range_color=[-20, 20],
                title="Δ Peso recomendado vs. cartera actual",
            )
            fig_rebal.add_vline(x=0, line_color="gray", line_width=1)
            fig_rebal.update_layout(
                height=max(300, len(df_rebal) * 22), coloraxis_showscale=False,
            )
            st.plotly_chart(fig_rebal, use_container_width=True)

        st.dataframe(
            pd.DataFrame(rebal_data) if rebal_data else pd.DataFrame(
                [
                    {
                        "Ticker":    s.symbol,
                        "Actual %":  s.current_pct,
                        "Objetivo %": s.target_pct,
                        "Δ %":       s.delta_pct,
                        "Acción":    s.action,
                    }
                    for s in result.rebalance_suggestions
                ]
            ),
            use_container_width=True,
            hide_index=True,
            column_config={"Δ %": st.column_config.NumberColumn("Δ %", format="%.1f")},
        )
        st.caption(
            "Solo se muestran movimientos ≥ 0.5%. Los pesos son porcentajes sobre el total de la cartera. "
            "⚠️ Estas sugerencias son orientativas y no constituyen asesoramiento financiero. "
            "Consultá con un asesor antes de ejecutar operaciones."
        )
