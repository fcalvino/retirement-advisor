"""Portfolio Optimizer — Mean-Variance con universos múltiples y presets de retiro."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import OPTIMIZER, OPTIMIZER_PROFILES
from dashboard.shared import (
    _MOAT_EMOJI,
    _fetch_universe_parallel,
    _get_ai_config,
)
from data.preferences import UserPreferences
from data.universe_loader import UNIVERSE_META, list_universes, load_universe
from portfolio.optimizer import PortfolioOptimizer
from portfolio.tracker import Portfolio

# ------------------------------------------------------------------ #
#  Constants                                                           #
# ------------------------------------------------------------------ #

_PROFILE_LABELS = {
    "conservative": "🛡️  Conservador",
    "moderate":     "⚖️  Moderado",
    "aggressive":   "🚀 Agresivo",
}
_PROFILE_KEYS = {v: k for k, v in _PROFILE_LABELS.items()}
_PREFS_TO_KEY = {
    "Conservador": "conservative",
    "Moderado":    "moderate",
    "Agresivo":    "aggressive",
}

# Presets: universe + profile combinations with a retirement objective
_PRESETS = [
    {
        "label":       "💰 Alto Dividendo",
        "universe":    "dividend_focus",
        "profile":     "conservative",
        "description": "Dividend Aristocrats + REITs. Ingreso pasivo con bajo riesgo.",
    },
    {
        "label":       "⚖️ Balanced Quality",
        "universe":    "us_quality",
        "profile":     "moderate",
        "description": "Blue chips US de calidad. Crecimiento balanceado con ingreso.",
    },
    {
        "label":       "🚀 Growth con Moat",
        "universe":    "us_quality",
        "profile":     "aggressive",
        "description": "Tech + Healthcare + Consumer. Ventaja competitiva duradera.",
    },
    {
        "label":       "🌎 LATAM + ADRs",
        "universe":    "latam_adrs",
        "profile":     "moderate",
        "description": "ADRs latinoamericanos. Alto potencial, mayor volatilidad.",
    },
]

# ------------------------------------------------------------------ #
#  Page                                                                #
# ------------------------------------------------------------------ #

st.title("📈 Portfolio Optimizer")
st.caption(
    "Construye una cartera óptima combinando Score Ajustado, Moat y Dividend Yield "
    "con restricciones de riesgo según tu perfil de retiro. "
    "💵 Todos los valores están denominados en **USD**."
)

# Guard: initialize shared state if navigated directly (fresh session)
if "user_prefs" not in st.session_state:
    st.session_state.user_prefs = UserPreferences.load()
if "universe" not in st.session_state:
    _uk = getattr(st.session_state.user_prefs, "active_universe", "default") or "default"
    st.session_state.universe = load_universe(_uk)
    st.session_state.active_universe_key = _uk
if "portfolio" not in st.session_state:
    st.session_state.portfolio = Portfolio()

_prefs: UserPreferences = st.session_state.user_prefs
portfolio: Portfolio = st.session_state.portfolio

# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _universe_display_label(key: str) -> str:
    """Build the exact label string used by the sidebar selectbox."""
    meta  = UNIVERSE_META.get(key, {})
    name  = meta.get("name", key)
    count = meta.get("count", len(load_universe(key)))
    return f"{name} ({count})"


def _apply_preset(universe_key: str, profile_key: str) -> None:
    """Switch universe + profile atomically and trigger a full rerun.

    Uses pending keys so app.py can consume them before widget instantiation,
    avoiding the 'cannot modify after instantiation' Streamlit error.
    """
    # Pending keys: consumed by app.py (universe) and this page (profile)
    # before their respective widgets are created on the next render.
    st.session_state["_preset_universe_key"] = universe_key
    st.session_state["_preset_profile_key"]  = profile_key

    # Persist preferences immediately
    _prefs.active_universe = universe_key
    _prefs.default_profile = OPTIMIZER_PROFILES[profile_key].name
    _prefs.save()

    # Wipe optimizer caches so the new run starts fresh
    for k in [
        "optimizer_scored", "optimizer_universe",
        "optimizer_result", "optimizer_result_key",
        "optimizer_prev_result", "optimizer_prev_result_key",
        "optimizer_extra_universes", "optimizer_comparison_results",
        "optimizer_comparison_profile",
    ]:
        st.session_state.pop(k, None)

    st.rerun()


# ------------------------------------------------------------------ #
#  Sidebar — Presets                                                   #
# ------------------------------------------------------------------ #

st.sidebar.subheader("🎯 Presets de retiro")
_pcols = st.sidebar.columns(2)
for _i, _preset in enumerate(_PRESETS):
    with _pcols[_i % 2]:
        if st.button(
            _preset["label"],
            key=f"preset_{_i}",
            use_container_width=True,
            help=_preset["description"],
        ):
            _apply_preset(_preset["universe"], _preset["profile"])

st.sidebar.divider()

# ------------------------------------------------------------------ #
#  Sidebar — Profile selector                                          #
# ------------------------------------------------------------------ #
# Using key= (not index=) so Streamlit owns the widget state and avoids
# the "revert on first click" bug caused by index= conflicting with
# internal session_state on reruns.

# Consume pending profile from preset (must happen before widget instantiation)
if "_preset_profile_key" in st.session_state:
    _ppk = st.session_state.pop("_preset_profile_key")
    if _ppk in _PROFILE_LABELS:
        st.session_state["optimizer_profile_label"]   = _PROFILE_LABELS[_ppk]
        st.session_state.optimizer_last_saved_profile = OPTIMIZER_PROFILES[_ppk].name

if "optimizer_profile_label" not in st.session_state:
    _init_key = _PREFS_TO_KEY.get(_prefs.default_profile, "conservative")
    st.session_state["optimizer_profile_label"] = _PROFILE_LABELS[_init_key]

profile_label = st.sidebar.radio(
    "Perfil de riesgo",
    list(_PROFILE_LABELS.values()),
    key="optimizer_profile_label",
    help=(
        "Conservador: preserva capital con dividendos. "
        "Moderado: balance crecimiento/ingreso. "
        "Agresivo: maximiza crecimiento a largo plazo."
    ),
)
profile_key = _PROFILE_KEYS[profile_label]
prof        = OPTIMIZER_PROFILES[profile_key]

if "optimizer_last_saved_profile" not in st.session_state:
    st.session_state.optimizer_last_saved_profile = _prefs.default_profile

if prof.name != st.session_state.optimizer_last_saved_profile:
    _prefs.default_profile = prof.name
    _prefs.save()
    st.session_state.optimizer_last_saved_profile = prof.name
    st.toast(f"Perfil '{prof.name}' guardado como preferencia", icon="💾")

st.sidebar.divider()

# ------------------------------------------------------------------ #
#  Sidebar — Universe combination                                      #
# ------------------------------------------------------------------ #

_active_key  = st.session_state.get("active_universe_key", _prefs.active_universe or "default")
_other_keys  = [k for k in list_universes() if k != _active_key]

st.sidebar.subheader("🔗 Combinar universos")
_extra_keys: list[str] = st.sidebar.multiselect(
    "Agregar tickers de",
    options=_other_keys,
    format_func=lambda k: f"{UNIVERSE_META[k]['name']} (+{UNIVERSE_META[k]['count']})",
    help="Se combinan con el universo activo (sin duplicados, máx 2 adicionales).",
    key="optimizer_extra_universes",
    max_selections=2,
    default=[],
)

# Build effective ticker list: base + extras (deduped, preserving order)
_base_tickers  = list(st.session_state.universe)
_extra_tickers = [
    t for k in _extra_keys
    for t in load_universe(k)
    if t not in _base_tickers
]
_combined = _base_tickers + _extra_tickers

# Universe display name
_active_meta  = UNIVERSE_META.get(_active_key, {})
_active_name  = _active_meta.get("name", _active_key)
if _extra_keys:
    _extra_names         = " + ".join(UNIVERSE_META.get(k, {}).get("name", k) for k in _extra_keys)
    _display_universe    = f"{_active_name} + {_extra_names}"
else:
    _display_universe    = _active_name

st.sidebar.divider()

# ------------------------------------------------------------------ #
#  Sidebar — Ticker slider + Re-analyze                               #
# ------------------------------------------------------------------ #

max_tickers = st.sidebar.slider(
    "Tickers a analizar", 10, max(10, len(_combined)), len(_combined),
    help="Reducir el universo acelera el análisis. Se toman los primeros N tickers.",
)
selected_universe = _combined[:max_tickers]

if st.sidebar.button("🔄 Re-analizar universo", type="secondary"):
    for k in [
        "optimizer_scored", "optimizer_universe",
        "optimizer_result", "optimizer_result_key", "optimizer_prev_result",
    ]:
        st.session_state.pop(k, None)
    st.cache_data.clear()
    st.rerun()

# ------------------------------------------------------------------ #
#  Profile card                                                        #
# ------------------------------------------------------------------ #

_PROFILE_DESC = {
    "conservative": "Preservación de capital + ingreso por dividendos. Volatilidad controlada.",
    "moderate":     "Balance entre crecimiento e ingreso. Exposición al riesgo controlada.",
    "aggressive":   "Maximización de crecimiento a largo plazo. Mayor tolerancia al riesgo.",
}
with st.expander(f"📋 Perfil: **{prof.name}** — {_PROFILE_DESC[profile_key]}", expanded=True):
    pc1, pc2, pc3, pc4, pc5 = st.columns(5)
    pc1.metric("Pos. máx.",       f"{prof.max_position_pct:.0f}%")
    pc2.metric("Vol. máx.",       f"{prof.max_volatility_pct:.0f}%")
    pc3.metric("Div. mín.",       f"{prof.min_dividend_yield_pct:.1f}%")
    pc4.metric("Sector máx.",     f"{prof.max_sector_pct:.0f}%")
    pc5.metric("Min. posiciones", prof.min_positions)
    st.caption(
        f"Pesos objetivo — Score: {prof.score_weight:.0%} "
        f"· Dividendo: {prof.dividend_weight:.0%} "
        f"· Moat: {prof.moat_weight:.0%}"
    )

# ------------------------------------------------------------------ #
#  Cache validity                                                      #
# ------------------------------------------------------------------ #

universe_key     = tuple(selected_universe)
result_key       = (profile_key, universe_key)
has_valid_result = (
    "optimizer_result" in st.session_state
    and st.session_state.get("optimizer_result_key") == result_key
)

if "optimizer_result" in st.session_state and not has_valid_result:
    prev_rk        = st.session_state.get("optimizer_result_key", (None, None))
    prev_prof_name = OPTIMIZER_PROFILES.get(prev_rk[0], prof).name if prev_rk[0] else "—"
    st.info(
        f"ℹ️ El resultado anterior corresponde al perfil **{prev_prof_name}**. "
        "Presioná **Ejecutar Optimización** para actualizar."
    )

# ------------------------------------------------------------------ #
#  Run button + context banner                                         #
# ------------------------------------------------------------------ #

btn_col, ctx_col = st.columns([1, 3])
with btn_col:
    run_now = st.button(
        "🚀 Ejecutar Optimización",
        type="primary",
        use_container_width=True,
    )
with ctx_col:
    if "optimizer_scored" in st.session_state and st.session_state.get("optimizer_universe") == universe_key:
        st.info(
            f"🗂️ **{_display_universe}** · {len(selected_universe)} tickers · "
            f"perfil **{prof.name}** — análisis en caché, optimización instantánea.",
            icon="✅",
        )
    else:
        st.info(
            f"🗂️ Optimizando **{len(selected_universe)} tickers** del universo "
            f"**{_display_universe}** para perfil **{prof.name}**.",
            icon="ℹ️",
        )

if not run_now and not has_valid_result:
    st.info(
        f"👆 Configurá el perfil y el universo en el sidebar, luego presioná "
        f"**🚀 Ejecutar Optimización** para generar tu cartera óptima.",
        icon="📈",
    )
    # Profile quick-reference cards
    _prof_cards = st.columns(3)
    for _ci, (_pk, _pcfg) in enumerate(OPTIMIZER_PROFILES.items()):
        _active = (_pk == profile_key)
        with _prof_cards[_ci]:
            _border = "2px solid #1f77b4" if _active else "1px solid #ddd"
            st.markdown(
                f'<div style="border:{_border};border-radius:8px;padding:12px;'
                f'background:{"#e8f4fd" if _active else "#fafafa"}">'
                f'<b>{"✅ " if _active else ""}{_pcfg.name}</b><br>'
                f'<small style="color:#666">{_pcfg.description}</small><br><br>'
                f'<small>📊 Vol máx: <b>{_pcfg.max_volatility_pct:.0f}%</b> &nbsp;'
                f'💰 Div mín: <b>{_pcfg.min_dividend_yield_pct:.1f}%</b> &nbsp;'
                f'📌 Pos máx: <b>{_pcfg.max_position_pct:.0f}%</b></small>'
                f'</div>',
                unsafe_allow_html=True,
            )
    st.stop()

# ------------------------------------------------------------------ #
#  Fetch + score tickers                                               #
# ------------------------------------------------------------------ #

scored: list[dict] = []
current_weights: dict = {}

if run_now or not has_valid_result:
    if (
        "optimizer_scored" not in st.session_state
        or st.session_state.get("optimizer_universe") != universe_key
    ):
        ai_cfg = _get_ai_config(context="screener")
        n      = len(selected_universe)
        st.info(f"⚡ Analizando {n} tickers en paralelo… (primera vez tarda ~15s)")
        prog = st.progress(0)
        stat = st.empty()
        raw  = _fetch_universe_parallel(selected_universe, ai_cfg, prog, stat, label="Optimizer")
        prog.empty()
        stat.empty()

        scored = [
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

    # ------------------------------------------------------------------ #
    #  Optimize                                                            #
    # ------------------------------------------------------------------ #

    with st.spinner(f"Generando portafolio {prof.name}…"):
        opt = PortfolioOptimizer(profile=profile_key)
        try:
            current_weights = portfolio.get_position_weights()
        except Exception:
            current_weights = {}
        result = opt.optimize(scored, current_weights=current_weights or None)

    if "optimizer_result" in st.session_state:
        st.session_state.optimizer_prev_result     = st.session_state.optimizer_result
        st.session_state.optimizer_prev_result_key = st.session_state.get("optimizer_result_key")

    st.session_state.optimizer_result     = result
    st.session_state.optimizer_result_key = result_key

else:
    result = st.session_state.optimizer_result
    scored = st.session_state.optimizer_scored
    try:
        current_weights = portfolio.get_position_weights()
    except Exception:
        current_weights = {}

# ------------------------------------------------------------------ #
#  Profile-change delta banner                                         #
# ------------------------------------------------------------------ #

if run_now and "optimizer_prev_result" in st.session_state:
    prev      = st.session_state.optimizer_prev_result
    prev_key  = st.session_state.get("optimizer_prev_result_key", (None,))
    prev_name = OPTIMIZER_PROFILES.get(prev_key[0], prof).name if prev_key[0] else "—"

    if prev_name != prof.name:
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
        prev_w   = {a.symbol: a.weight_pct for a in prev.tickers}
        curr_w   = {a.symbol: a.weight_pct for a in result.tickers}
        all_syms = set(prev_w) | set(curr_w)
        movers   = sorted(
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

# ------------------------------------------------------------------ #
#  Status bar                                                          #
# ------------------------------------------------------------------ #

_method_badge = "🧮 Mean-Variance" if result.method == "mean-variance" else "⚖️ Score-weighted"
st.success(
    f"{_method_badge} · 🗂️ **{_display_universe}** · "
    f"Perfil **{result.profile_name}** · {len(result.tickers)} posiciones"
)
if result.warnings:
    for w in result.warnings:
        st.warning(w)

# ------------------------------------------------------------------ #
#  Summary metrics                                                     #
# ------------------------------------------------------------------ #

mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
mc1.metric("Retorno esperado", f"{result.expected_return_pct:.1f}%")
mc2.metric("Volatilidad",      f"{result.volatility_pct:.1f}%",
           delta=f"límite {prof.max_volatility_pct:.0f}%", delta_color="off")
mc3.metric("Sharpe Ratio",     f"{result.sharpe_ratio:.2f}")
mc4.metric("Div. Yield",       f"{result.dividend_yield_pct:.2f}%",
           delta=f"mín {prof.min_dividend_yield_pct:.1f}%", delta_color="off")
mc5.metric("Score Promedio",   f"{result.adjusted_score_avg:.0f}/100")
mc6.metric(
    "Max Drawdown est.",
    f"{result.max_drawdown_estimate_pct:.1f}%",
    help="Estimación del peor escenario anual: ≈ 1.5× volatilidad (regla empírica)",
    delta_color="off",
)

# ------------------------------------------------------------------ #
#  Tabs                                                                #
# ------------------------------------------------------------------ #

tab_cart, tab_front, tab_metrics, tab_rebal, tab_compare = st.tabs(
    ["🧺 Cartera", "📉 Frontier", "📊 Métricas", "🔄 Rebalanceo", "⚖️ Comparar"]
)

# ------------------------------------------------------------------ #
#  Tab 1: Cartera                                                      #
# ------------------------------------------------------------------ #

with tab_cart:
    if not result.tickers:
        st.warning("No hay posiciones en la cartera optimizada.")
    else:
        # Safety: renormalize weight_pct to always sum to ~100 %
        _total_w = sum(a.weight_pct for a in result.tickers)
        if _total_w > 0 and abs(_total_w - 100.0) > 0.5:
            _scale = 100.0 / _total_w
            for _a in result.tickers:
                _a.weight_pct = round(_a.weight_pct * _scale, 1)
            result.sector_weights = {
                k: round(v * _scale, 1) for k, v in result.sector_weights.items()
            }

        scored_map = {t["symbol"]: t for t in scored}
        alloc_data = []
        for a in result.tickers:
            t = scored_map.get(a.symbol, {})
            moat_cls      = t.get("moat_classification", "None")
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

        df_bar   = df_alloc[df_alloc["Peso %"] > 0].sort_values("Peso %")
        _max_val = df_bar["Peso %"].max() if not df_bar.empty else prof.max_position_pct
        fig_bar  = px.bar(
            df_bar, x="Peso %", y="Ticker", orientation="h",
            color="Score", color_continuous_scale="RdYlGn",
            range_color=[40, 100],
            title=f"Peso por ticker — {_display_universe} · Perfil {prof.name}",
            text="Peso %",
        )
        fig_bar.update_traces(
            texttemplate="%{text:.1f}%",
            textposition="inside",
            insidetextanchor="end",
        )
        fig_bar.add_vline(
            x=prof.max_position_pct,
            line_dash="dash",
            line_color="orange",
            annotation_text=f"máx {prof.max_position_pct:.0f}%",
            annotation_position="bottom right",
            annotation_font_color="orange",
        )
        fig_bar.update_layout(
            height=max(350, len(df_bar) * 22),
            yaxis_title="",
            coloraxis_showscale=False,
            xaxis_range=[0, max(_max_val, prof.max_position_pct) * 1.15],
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        st.dataframe(
            df_alloc,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Peso %": st.column_config.ProgressColumn(
                    "Peso %", min_value=0, max_value=100, format="%.1f%%"
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
                df_top     = df_alloc.nlargest(10, "Peso %")
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
            ars_syms     = ", ".join(a.symbol for a in result.tickers if a.is_ars)
            st.info(
                f"🇦🇷 **ADRs argentinos ({ars_syms}):** cotizan y liquidan en **USD** en NYSE/NASDAQ. "
                f"En perfil **{prof.name}** se aplica un descuento de **{discount_pct:.0f}%** "
                "al Score Ajustado para calcular el peso óptimo "
                "(no afecta el precio ni el dividend yield reportado)."
            )

    # CSV export
    if result.tickers:
        import io
        _csv_buf = io.StringIO()
        df_alloc.to_csv(_csv_buf, index=False)
        st.download_button(
            label="⬇️ Exportar cartera a CSV",
            data=_csv_buf.getvalue(),
            file_name=f"portfolio_{prof.name.lower()}_{_display_universe.replace(' ', '_')}.csv",
            mime="text/csv",
            use_container_width=False,
        )

    if result.excluded:
        with st.expander(f"Tickers excluidos de la optimización ({len(result.excluded)})"):
            for sym, reason in result.excluded:
                st.caption(f"**{sym}** — {reason}")

# ------------------------------------------------------------------ #
#  Tab 2: Efficient Frontier                                           #
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
            title=f"Frontera Eficiente — {_display_universe} · Monte Carlo ({OPTIMIZER.frontier_points} carteras)",
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
#  Tab 3: Métricas + Constraint Compliance                            #
# ------------------------------------------------------------------ #

with tab_metrics:
    m1, m2 = st.columns(2)

    with m1:
        st.subheader("Estadísticas de cartera")
        _dd_str = f"{result.max_drawdown_estimate_pct:.1f}%" if result.max_drawdown_estimate_pct else "—"
        st.markdown(f"""
| Métrica | Valor |
|---|---|
| Universo | **{_display_universe}** |
| Retorno esperado | **{result.expected_return_pct:.1f}%** anual |
| Volatilidad | **{result.volatility_pct:.1f}%** anual |
| Sharpe Ratio | **{result.sharpe_ratio:.2f}** |
| Max Drawdown est. | **{_dd_str}** (1 año) |
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
#  Tab 4: Rebalanceo                                                   #
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
        rb1.metric("Compras",    len(buys))
        rb2.metric("Ventas",     len(sells))
        rb3.metric("Sin cambio", len(holds))

        rebal_data = [
            {
                "Ticker":     s.symbol,
                "Actual %":   s.current_pct,
                "Objetivo %": s.target_pct,
                "Δ %":        s.delta_pct,
                "Acción":     s.action,
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

        all_rebal_data = [
            {
                "Ticker":     s.symbol,
                "Actual %":   s.current_pct,
                "Objetivo %": s.target_pct,
                "Δ %":        s.delta_pct,
                "Acción":     s.action,
            }
            for s in result.rebalance_suggestions
        ]
        st.dataframe(
            pd.DataFrame(rebal_data if rebal_data else all_rebal_data),
            use_container_width=True,
            hide_index=True,
            column_config={"Δ %": st.column_config.NumberColumn("Δ %", format="%.1f")},
        )
        st.caption(
            "Solo se muestran movimientos ≥ 0.5%. "
            "⚠️ Estas sugerencias son orientativas y no constituyen asesoramiento financiero."
        )

# ------------------------------------------------------------------ #
#  Tab 5: Comparar universos                                           #
# ------------------------------------------------------------------ #

with tab_compare:
    st.subheader(f"Comparación de universos — perfil {prof.name}")
    st.caption(
        "Corre el optimizer en todos los universos disponibles con el perfil actual. "
        "Usa los **top 25 tickers** de cada universo para mantener la comparación rápida (~30s primera vez, "
        "instantánea cuando hay caché). Los tickers ya analizados en esta sesión son reutilizados."
    )

    _COMPARE_CAP = 25  # tickers por universo para la comparación rápida

    run_compare = st.button(
        f"🔄 Comparar todos los universos ({len(list_universes())} disponibles)",
        type="secondary",
        key="run_compare_btn",
    )

    _comp_stale = (
        st.session_state.get("optimizer_comparison_profile") != profile_key
        and "optimizer_comparison_results" in st.session_state
    )
    if _comp_stale:
        st.warning(
            f"Los resultados de comparación son del perfil anterior. "
            "Presioná el botón para actualizar."
        )

    if run_compare:
        _comp_universes = list_universes()
        _comp_results: dict = {}
        _comp_prog = st.progress(0.0)
        _comp_status = st.empty()

        _comp_ai_cfg = _get_ai_config(context="screener")

        for _ci, _uk in enumerate(_comp_universes):
            _u_name    = UNIVERSE_META.get(_uk, {}).get("name", _uk)
            _u_tickers = load_universe(_uk)[:_COMPARE_CAP]
            _comp_status.text(f"Analizando {_u_name} ({len(_u_tickers)} tickers)…")

            _dummy_prog = st.empty()  # silent progress for sub-fetches
            _dummy_stat = st.empty()
            try:
                _u_raw = _fetch_universe_parallel(
                    _u_tickers, _comp_ai_cfg, _dummy_prog, _dummy_stat,
                    label=f"Compare-{_uk}",
                )
                _dummy_prog.empty()
                _dummy_stat.empty()
            except Exception:
                _dummy_prog.empty()
                _dummy_stat.empty()
                _comp_prog.progress((_ci + 1) / len(_comp_universes))
                continue

            _u_scored = [
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
                for sym, fund, _t, _d in _u_raw
            ]
            if _u_scored:
                try:
                    _u_opt    = PortfolioOptimizer(profile=profile_key)
                    _u_result = _u_opt.optimize(_u_scored)
                    _comp_results[_uk] = _u_result
                except Exception:
                    pass

            _comp_prog.progress((_ci + 1) / len(_comp_universes))

        _comp_prog.progress(1.0, text="¡Listo!")
        _comp_status.empty()
        _comp_prog.empty()

        st.session_state.optimizer_comparison_results = _comp_results
        st.session_state.optimizer_comparison_profile = profile_key

    # Render comparison table
    if (
        "optimizer_comparison_results" in st.session_state
        and st.session_state.get("optimizer_comparison_profile") == profile_key
    ):
        _comp_rows = []
        for _uk, _ures in st.session_state.optimizer_comparison_results.items():
            _u_meta = UNIVERSE_META.get(_uk, {})
            _comp_rows.append({
                "Universo":      _u_meta.get("name", _uk),
                "Tickers base":  _u_meta.get("count", "?"),
                "Analizados":    len(st.session_state.optimizer_comparison_results[_uk].tickers),
                "Posiciones":    len(_ures.tickers),
                "Retorno %":     round(_ures.expected_return_pct, 1),
                "Volatilidad %": round(_ures.volatility_pct, 1),
                "Sharpe":        round(_ures.sharpe_ratio, 2),
                "Div Yield %":   round(_ures.dividend_yield_pct, 2),
                "Score Avg":     round(_ures.adjusted_score_avg, 0),
                "Método":        _ures.method,
            })

        if _comp_rows:
            _comp_df = pd.DataFrame(_comp_rows)
            # Highlight current universe row
            st.dataframe(
                _comp_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Retorno %":     st.column_config.NumberColumn("Retorno %", format="%.1f%%"),
                    "Volatilidad %": st.column_config.NumberColumn("Vol %", format="%.1f%%"),
                    "Sharpe":        st.column_config.NumberColumn("Sharpe", format="%.2f"),
                    "Div Yield %":   st.column_config.NumberColumn("Div %", format="%.2f%%"),
                    "Score Avg":     st.column_config.NumberColumn("Score", format="%.0f"),
                },
            )

            # Grouped bar chart comparing key metrics
            _bar_metrics = ["Retorno %", "Volatilidad %", "Div Yield %"]
            _fig_comp    = go.Figure()
            for _metric in _bar_metrics:
                _fig_comp.add_trace(go.Bar(
                    name=_metric,
                    x=_comp_df["Universo"],
                    y=_comp_df[_metric],
                    text=_comp_df[_metric].apply(lambda v: f"{v:.1f}%"),
                    textposition="outside",
                ))
            _fig_comp.update_layout(
                barmode="group",
                title=f"Retorno · Volatilidad · Div Yield — perfil {prof.name} (top {_COMPARE_CAP} tickers por universo)",
                height=420,
                yaxis_title="%",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(_fig_comp, use_container_width=True)

            # Sharpe comparison as horizontal bar
            _fig_sharpe = px.bar(
                _comp_df.sort_values("Sharpe"),
                x="Sharpe", y="Universo", orientation="h",
                color="Sharpe", color_continuous_scale="RdYlGn",
                text="Sharpe",
                title=f"Sharpe Ratio por universo — perfil {prof.name}",
            )
            _fig_sharpe.update_traces(texttemplate="%{text:.2f}", textposition="inside")
            _fig_sharpe.update_layout(height=300, coloraxis_showscale=False)
            st.plotly_chart(_fig_sharpe, use_container_width=True)

            st.caption(
                f"⚠️ Comparación basada en los primeros {_COMPARE_CAP} tickers de cada universo. "
                "Para análisis completo, seleccioná el universo en el sidebar y ejecutá el optimizer completo."
            )
        else:
            st.warning("No se pudo obtener resultados para ningún universo.")
    elif "optimizer_comparison_results" not in st.session_state:
        st.info(
            "Presioná **Comparar todos los universos** para ver qué universo "
            f"rinde mejor con el perfil **{prof.name}**."
        )
