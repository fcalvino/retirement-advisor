"""Portfolio Optimizer — Mean-Variance con universos múltiples y presets de retiro."""

from __future__ import annotations

import io
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

_PROFILE_COLORS = {
    "conservative": {"bg": "#e8f5e9", "border": "#43a047", "accent": "#2e7d32", "icon": "🛡️"},
    "moderate":     {"bg": "#fff3e0", "border": "#fb8c00", "accent": "#e65100", "icon": "⚖️"},
    "aggressive":   {"bg": "#fce4ec", "border": "#e91e63", "accent": "#880e4f", "icon": "🚀"},
}

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

# Static benchmark reference data (annualized avg ~2014–2024)
_BENCHMARKS = {
    "SPY (S&P 500)":   {"return": 10.5, "vol": 15.2, "sharpe": 0.52, "div": 1.35, "max_dd": -22.8},
    "60/40 Portfolio": {"return": 7.8,  "vol": 9.5,  "sharpe": 0.58, "div": 2.10, "max_dd": -14.3},
    "BND (Bonos)":     {"return": 4.2,  "vol": 5.8,  "sharpe": 0.35, "div": 3.80, "max_dd": -8.7},
}

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

def _apply_preset(universe_key: str, profile_key: str) -> None:
    """Switch universe + profile atomically via pending keys (avoids widget-state conflict)."""
    st.session_state["_preset_universe_key"] = universe_key
    st.session_state["_preset_profile_key"]  = profile_key
    _prefs.active_universe = universe_key
    _prefs.default_profile = OPTIMIZER_PROFILES[profile_key].name
    _prefs.save()
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

# Consume pending profile from preset before widget instantiation
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

# Detect profile change BEFORE updating last_saved (used to auto-expand constraint card)
_profile_just_changed = prof.name != st.session_state.optimizer_last_saved_profile
if _profile_just_changed:
    _prefs.default_profile = prof.name
    _prefs.save()
    st.session_state.optimizer_last_saved_profile = prof.name
    st.toast(f"Perfil '{prof.name}' guardado", icon="💾")

st.sidebar.divider()

# ------------------------------------------------------------------ #
#  Sidebar — Universe combination                                      #
# ------------------------------------------------------------------ #

_active_key  = st.session_state.get("active_universe_key", getattr(_prefs, "active_universe", "default") or "default")
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

_base_tickers  = list(st.session_state.universe)
_extra_tickers = [t for k in _extra_keys for t in load_universe(k) if t not in _base_tickers]
_combined      = _base_tickers + _extra_tickers

_active_meta  = UNIVERSE_META.get(_active_key, {})
_active_name  = _active_meta.get("name", _active_key)
_display_universe = (
    f"{_active_name} + " + " + ".join(UNIVERSE_META.get(k, {}).get("name", k) for k in _extra_keys)
    if _extra_keys else _active_name
)

st.sidebar.divider()

# ------------------------------------------------------------------ #
#  Sidebar — Ticker slider + Portfolio value + Re-analyze             #
# ------------------------------------------------------------------ #

max_tickers = st.sidebar.slider(
    "Tickers a analizar", 10, max(10, len(_combined)), len(_combined),
    help="Reducir el universo acelera el análisis.",
)
selected_universe = _combined[:max_tickers]

total_capital = st.sidebar.number_input(
    "Capital a invertir (USD)",
    min_value=0,
    value=st.session_state.get("optimizer_total_capital", 0),
    step=1000,
    help="Opcional: ingresá el total para ver el valor en USD de cada posición.",
    format="%d",
)
st.session_state["optimizer_total_capital"] = int(total_capital)

if st.sidebar.button("🔄 Re-analizar universo", type="secondary"):
    for k in [
        "optimizer_scored", "optimizer_universe",
        "optimizer_result", "optimizer_result_key", "optimizer_prev_result",
    ]:
        st.session_state.pop(k, None)
    st.cache_data.clear()
    st.rerun()

# ------------------------------------------------------------------ #
#  Profile constraint card                                             #
# ------------------------------------------------------------------ #

_PROFILE_DESC = {
    "conservative": "Preservación de capital + ingreso por dividendos.",
    "moderate":     "Balance entre crecimiento e ingreso.",
    "aggressive":   "Maximización de crecimiento a largo plazo.",
}
_pc = _PROFILE_COLORS[profile_key]
with st.expander(
    f"{_pc['icon']} Perfil **{prof.name}** — {_PROFILE_DESC[profile_key]}",
    expanded=_profile_just_changed,
):
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
    if _profile_just_changed:
        st.info("Presioná **🚀 Ejecutar Optimización** para generar la cartera con el nuevo perfil.", icon="🔄")

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
    run_now = st.button("🚀 Ejecutar Optimización", type="primary", use_container_width=True)
with ctx_col:
    if "optimizer_scored" in st.session_state and st.session_state.get("optimizer_universe") == universe_key:
        st.info(
            f"🗂️ **{_display_universe}** · {len(selected_universe)} tickers · "
            f"perfil **{prof.name}** — análisis en caché, optimización instantánea.",
            icon="✅",
        )
    else:
        st.info(
            f"🗂️ **{len(selected_universe)} tickers** · universo **{_display_universe}** · perfil **{prof.name}**.",
            icon="ℹ️",
        )

# ------------------------------------------------------------------ #
#  Welcome state                                                       #
# ------------------------------------------------------------------ #

if not run_now and not has_valid_result:
    st.markdown("---")
    st.markdown("### Seleccioná un perfil y ejecutá la optimización")

    _prof_cards = st.columns(3)
    for _ci, (_pk, _pcfg) in enumerate(OPTIMIZER_PROFILES.items()):
        _active = (_pk == profile_key)
        _clr    = _PROFILE_COLORS[_pk]
        _border = f"3px solid {_clr['border']}" if _active else f"1px solid {_clr['border']}88"
        with _prof_cards[_ci]:
            st.markdown(
                f"""<div style="
                    border:{_border};
                    border-radius:12px;
                    padding:20px 16px;
                    background:{_clr['bg']};
                    min-height:190px;
                ">
                    <div style="font-size:2em;margin-bottom:4px">{_clr['icon']}</div>
                    <div style="font-size:1.1em;font-weight:700;color:{_clr['accent']}">
                        {"✅ " if _active else ""}{_pcfg.name}
                    </div>
                    <div style="font-size:0.82em;color:#555;margin:6px 0 10px">{_pcfg.description}</div>
                    <div style="font-size:0.78em;color:{_clr['accent']}">
                        📊 Vol ≤ <b>{_pcfg.max_volatility_pct:.0f}%</b> &nbsp;
                        💰 Div ≥ <b>{_pcfg.min_dividend_yield_pct:.1f}%</b><br>
                        📌 Pos ≤ <b>{_pcfg.max_position_pct:.0f}%</b> &nbsp;
                        🔢 Min <b>{_pcfg.min_positions}</b> activos
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )

    st.markdown("&nbsp;", unsafe_allow_html=True)
    st.markdown("##### O elegí un preset de retiro:")
    _qcols = st.columns(len(_PRESETS))
    for _qi, _preset in enumerate(_PRESETS):
        with _qcols[_qi]:
            if st.button(
                _preset["label"],
                key=f"welcome_preset_{_qi}",
                use_container_width=True,
                help=_preset["description"],
            ):
                _apply_preset(_preset["universe"], _preset["profile"])
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

    with st.spinner(f"⚙️ Generando portafolio {prof.name} · Maximizando Sharpe Ratio…"):
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
            f"**Cambio de perfil:** {prev_name} → **{prof.name}** &nbsp;|&nbsp; "
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
            f"{sym} {'▲' if d > 0 else '▼'}{abs(d):.1f}%"
            for sym, d in movers if abs(d) >= 0.5
        ]
        if mover_parts:
            st.caption("Principales cambios en posiciones: " + " · ".join(mover_parts))

# ------------------------------------------------------------------ #
#  Status bar                                                          #
# ------------------------------------------------------------------ #

_method_badge = "🧮 Mean-Variance" if result.method == "mean-variance" else "⚖️ Score-weighted (fallback)"
if result.method == "mean-variance":
    st.success(
        f"{_method_badge} · 🗂️ **{_display_universe}** · "
        f"Perfil **{result.profile_name}** · {len(result.tickers)} posiciones"
    )
else:
    st.warning(
        f"{_method_badge} · 🗂️ **{_display_universe}** · "
        f"Perfil **{result.profile_name}** · {len(result.tickers)} posiciones — "
        "datos de precio insuficientes para Mean-Variance completo."
    )
for w in result.warnings:
    st.warning(w, icon="⚠️")

# ------------------------------------------------------------------ #
#  Summary metrics                                                     #
# ------------------------------------------------------------------ #

mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
mc1.metric(
    "Retorno esperado", f"{result.expected_return_pct:.1f}%",
    help="Retorno anual proxy (score + dividendo + moat).",
)
mc2.metric(
    "Volatilidad", f"{result.volatility_pct:.1f}%",
    delta=f"límite {prof.max_volatility_pct:.0f}%", delta_color="off",
)
mc3.metric(
    "Sharpe Ratio", f"{result.sharpe_ratio:.2f}",
    help="Retorno ajustado por riesgo (rf = 4.5%). Por encima de 0.5 es bueno.",
)
mc4.metric(
    "Div. Yield", f"{result.dividend_yield_pct:.2f}%",
    delta=f"mín {prof.min_dividend_yield_pct:.1f}%", delta_color="off",
)
mc5.metric("Score Promedio", f"{result.adjusted_score_avg:.0f}/100")
mc6.metric(
    "Max Drawdown est.", f"{result.max_drawdown_estimate_pct:.1f}%",
    help="Estimación peor escenario 1 año: ≈ 1.5× volatilidad (regla empírica).",
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
        # Renormalize weights to exactly 100 % (guards floating-point drift)
        _total_w = sum(a.weight_pct for a in result.tickers)
        if _total_w > 0 and abs(_total_w - 100.0) > 0.5:
            _scale = 100.0 / _total_w
            for _a in result.tickers:
                _a.weight_pct = round(_a.weight_pct * _scale, 1)
            result.sector_weights = {k: round(v * _scale, 1) for k, v in result.sector_weights.items()}

        scored_map = {t["symbol"]: t for t in scored}
        _total_val = st.session_state.get("optimizer_total_capital", 0)

        alloc_data = []
        for a in result.tickers:
            t             = scored_map.get(a.symbol, {})
            moat_cls      = t.get("moat_classification", "None")
            discount_note = f" (−{(1-OPTIMIZER.ars_risk_discount)*100:.0f}% ARS)" if a.score_discounted else ""
            row = {
                "Ticker":  a.symbol,
                "Empresa": (t.get("company_name", a.symbol) or a.symbol)[:32],
                "Peso %":  a.weight_pct,
                "Score":   a.adjusted_score,
                "Moat":    f"{_MOAT_EMOJI.get(moat_cls, '⚪')} {moat_cls}",
                "Div %":   a.dividend_yield_pct,
                "Sector":  a.sector,
                "Notas":   ("🇦🇷" + discount_note) if a.is_ars else "",
            }
            if _total_val > 0:
                row["Valor USD"] = round(a.weight_pct / 100 * _total_val)
            alloc_data.append(row)

        df_alloc = pd.DataFrame(alloc_data)

        # ---- Hero: allocation donut (left) + bar chart (right) ----
        col_donut, col_bar = st.columns(2)

        with col_donut:
            fig_donut = px.pie(
                df_alloc[df_alloc["Peso %"] > 0],
                values="Peso %",
                names="Ticker",
                title=f"Asignación — {len(result.tickers)} posiciones",
                hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Set3,
            )
            fig_donut.update_traces(
                textposition="outside",
                textinfo="label+percent",
                pull=[0.02] * len(df_alloc),
            )
            fig_donut.update_layout(
                height=420,
                showlegend=False,
                margin=dict(t=40, b=10, l=10, r=10),
                title_font_size=14,
            )
            st.plotly_chart(fig_donut, use_container_width=True)

        with col_bar:
            df_bar   = df_alloc[df_alloc["Peso %"] > 0].sort_values("Peso %")
            _max_val = df_bar["Peso %"].max() if not df_bar.empty else prof.max_position_pct
            fig_bar  = px.bar(
                df_bar, x="Peso %", y="Ticker", orientation="h",
                color="Score", color_continuous_scale="RdYlGn",
                range_color=[40, 100],
                title="Peso por ticker (color = Score Ajustado)",
                text="Peso %",
            )
            fig_bar.update_traces(
                texttemplate="%{text:.1f}%",
                textposition="inside",
                insidetextanchor="end",
            )
            fig_bar.add_vline(
                x=prof.max_position_pct,
                line_dash="dash", line_color="orange",
                annotation_text=f"máx {prof.max_position_pct:.0f}%",
                annotation_position="bottom right",
                annotation_font_color="orange",
            )
            fig_bar.update_layout(
                height=max(320, len(df_bar) * 22 + 60),
                yaxis_title="",
                coloraxis_showscale=False,
                xaxis_range=[0, max(_max_val, prof.max_position_pct) * 1.15],
                margin=dict(t=40, b=10),
                title_font_size=14,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        # ---- Allocation table ----
        _col_cfg: dict = {
            "Peso %": st.column_config.ProgressColumn("Peso %", min_value=0, max_value=100, format="%.1f%%"),
            "Score":  st.column_config.NumberColumn("Score",  format="%.0f"),
            "Div %":  st.column_config.NumberColumn("Div %",  format="%.2f%%"),
        }
        if _total_val > 0:
            _col_cfg["Valor USD"] = st.column_config.NumberColumn("Valor USD", format="$%d")

        st.dataframe(df_alloc, use_container_width=True, hide_index=True, column_config=_col_cfg)

        # ---- CSV export ----
        _csv_buf = io.StringIO()
        df_alloc.to_csv(_csv_buf, index=False)
        st.download_button(
            label="⬇️ Exportar cartera a CSV",
            data=_csv_buf.getvalue(),
            file_name=f"portfolio_{prof.name.lower()}_{_display_universe.replace(' ', '_')}.csv",
            mime="text/csv",
        )

        # ---- Sector breakdown ----
        if result.sector_weights:
            st.markdown("---")
            col_sec, col_top = st.columns(2)
            with col_sec:
                sec_df  = pd.DataFrame([{"Sector": k, "Peso %": v} for k, v in result.sector_weights.items()])
                fig_sec = px.pie(
                    sec_df, values="Peso %", names="Sector",
                    title="Diversificación por Sector",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Pastel,
                )
                fig_sec.update_traces(textposition="inside", textinfo="percent+label")
                fig_sec.update_layout(height=340, title_font_size=14)
                st.plotly_chart(fig_sec, use_container_width=True)
            with col_top:
                df_top     = df_alloc.nlargest(10, "Peso %")
                others_pct = 100 - df_top["Peso %"].sum()
                if others_pct > 0.5:
                    df_top = pd.concat(
                        [df_top, pd.DataFrame([{"Ticker": "Otros", "Peso %": others_pct}])],
                        ignore_index=True,
                    )
                fig_top = px.pie(
                    df_top, values="Peso %", names="Ticker",
                    title="Top-10 por Ticker",
                    hole=0.3,
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig_top.update_traces(textposition="inside", textinfo="percent+label")
                fig_top.update_layout(height=340, title_font_size=14)
                st.plotly_chart(fig_top, use_container_width=True)

        # ARS disclaimer
        if any(a.is_ars for a in result.tickers):
            discount_pct = (1 - OPTIMIZER.ars_risk_discount) * 100
            ars_syms     = ", ".join(a.symbol for a in result.tickers if a.is_ars)
            st.info(
                f"🇦🇷 **ADRs argentinos ({ars_syms}):** cotizan y liquidan en **USD** en NYSE/NASDAQ. "
                f"En perfil **{prof.name}** se aplica un descuento de **{discount_pct:.0f}%** al Score "
                "Ajustado para el cálculo del peso óptimo (no afecta precio ni dividend yield)."
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
            title=f"Frontera Eficiente — Monte Carlo ({OPTIMIZER.frontier_points} carteras)",
        )
        # Optimal portfolio star
        fig_front.add_scatter(
            x=[result.volatility_pct],
            y=[result.expected_return_pct],
            mode="markers",
            marker=dict(size=16, color="royalblue", symbol="star", line=dict(width=1, color="white")),
            name=f"Óptima ({prof.name})",
        )
        # Benchmark reference points
        for _bname, _bd in _BENCHMARKS.items():
            fig_front.add_scatter(
                x=[_bd["vol"]],
                y=[_bd["return"]],
                mode="markers+text",
                marker=dict(size=10, color="#888", symbol="diamond"),
                text=[_bname.split("(")[0].strip()],
                textposition="top right",
                textfont=dict(size=9, color="#888"),
                showlegend=False,
            )
        fig_front.add_vline(
            x=prof.max_volatility_pct,
            line_dash="dash", line_color="red",
            annotation_text=f"Vol máx. {prof.max_volatility_pct:.0f}%",
            annotation_position="top right",
        )
        fig_front.update_layout(
            height=540,
            legend=dict(yanchor="bottom", y=0.01, xanchor="right", x=0.99),
        )
        st.plotly_chart(fig_front, use_container_width=True)
        st.caption(
            "⭐ Estrella azul = cartera óptima del perfil. "
            "💎 Diamantes grises = benchmarks de referencia (SPY, 60/40, BND). "
            "Línea roja = techo de volatilidad del perfil."
        )

# ------------------------------------------------------------------ #
#  Tab 3: Métricas + Compliance + Benchmarks                          #
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
            st.markdown(f"{'✅' if ok else '❌'} **{label}** — {detail}")

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

    # ---- Benchmark comparison ----
    st.divider()
    st.subheader("📊 Comparación vs. Benchmarks")
    st.caption("Referencia histórica anualizada 2014–2024. Los datos del portafolio son estimaciones del modelo.")

    _bench_rows = [
        {
            "Portafolio / Benchmark": f"🧺 Tu Cartera ({prof.name})",
            "Retorno %":     result.expected_return_pct,
            "Vol %":         result.volatility_pct,
            "Sharpe":        result.sharpe_ratio,
            "Div Yield %":   result.dividend_yield_pct,
            "Max DD %":      result.max_drawdown_estimate_pct,
        }
    ] + [
        {
            "Portafolio / Benchmark": f"📈 {name}",
            "Retorno %":   bd["return"],
            "Vol %":       bd["vol"],
            "Sharpe":      bd["sharpe"],
            "Div Yield %": bd["div"],
            "Max DD %":    bd["max_dd"],
        }
        for name, bd in _BENCHMARKS.items()
    ]
    _bench_df = pd.DataFrame(_bench_rows)
    st.dataframe(
        _bench_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Portafolio / Benchmark": st.column_config.TextColumn("Portafolio / Benchmark"),
            "Retorno %":  st.column_config.NumberColumn("Retorno %",  format="%.1f%%"),
            "Vol %":      st.column_config.NumberColumn("Vol %",      format="%.1f%%"),
            "Sharpe":     st.column_config.NumberColumn("Sharpe",     format="%.2f"),
            "Div Yield %":st.column_config.NumberColumn("Div Yield %",format="%.2f%%"),
            "Max DD %":   st.column_config.NumberColumn("Max DD %",   format="%.1f%%"),
        },
    )

    # Grouped bar: Retorno vs Sharpe vs Div Yield
    _metrics_to_plot = ["Retorno %", "Sharpe", "Div Yield %"]
    _fig_bench = go.Figure()
    for _, row in _bench_df.iterrows():
        _fig_bench.add_trace(go.Bar(
            name=row["Portafolio / Benchmark"],
            x=_metrics_to_plot,
            y=[row[m] for m in _metrics_to_plot],
            text=[f"{row[m]:.2f}" for m in _metrics_to_plot],
            textposition="outside",
        ))
    _fig_bench.update_layout(
        barmode="group",
        title="Tu cartera vs. Benchmarks — Retorno · Sharpe · Div Yield",
        height=380,
        yaxis_title="Valor",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(_fig_bench, use_container_width=True)
    st.caption(
        "⚠️ Los retornos del portafolio son proyecciones del modelo, no retornos históricos reales. "
        "Los benchmarks reflejan performance pasada y no garantizan resultados futuros."
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
            fig_rebal.update_layout(height=max(300, len(df_rebal) * 22), coloraxis_showscale=False)
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

    _COMPARE_CAP = 25

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
        st.warning("Los resultados de comparación son del perfil anterior. Presioná el botón para actualizar.")

    if run_compare:
        _comp_universes = list_universes()
        _comp_results: dict = {}
        _comp_prog   = st.progress(0.0)
        _comp_status = st.empty()
        _comp_ai_cfg = _get_ai_config(context="screener")

        for _ci, _uk in enumerate(_comp_universes):
            _u_name    = UNIVERSE_META.get(_uk, {}).get("name", _uk)
            _u_tickers = load_universe(_uk)[:_COMPARE_CAP]
            _comp_status.text(f"Analizando {_u_name} ({len(_u_tickers)} tickers)…")

            _dummy_prog = st.empty()
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
                    _u_result = PortfolioOptimizer(profile=profile_key).optimize(_u_scored)
                    _comp_results[_uk] = _u_result
                except Exception:
                    pass

            _comp_prog.progress((_ci + 1) / len(_comp_universes))

        _comp_prog.progress(1.0, text="¡Listo!")
        _comp_status.empty()
        _comp_prog.empty()
        st.session_state.optimizer_comparison_results = _comp_results
        st.session_state.optimizer_comparison_profile = profile_key

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
            st.dataframe(
                _comp_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Retorno %":     st.column_config.NumberColumn("Retorno %",  format="%.1f%%"),
                    "Volatilidad %": st.column_config.NumberColumn("Vol %",      format="%.1f%%"),
                    "Sharpe":        st.column_config.NumberColumn("Sharpe",     format="%.2f"),
                    "Div Yield %":   st.column_config.NumberColumn("Div %",      format="%.2f%%"),
                    "Score Avg":     st.column_config.NumberColumn("Score",      format="%.0f"),
                },
            )

            _fig_comp = go.Figure()
            for _metric in ["Retorno %", "Volatilidad %", "Div Yield %"]:
                _fig_comp.add_trace(go.Bar(
                    name=_metric,
                    x=_comp_df["Universo"],
                    y=_comp_df[_metric],
                    text=_comp_df[_metric].apply(lambda v: f"{v:.1f}%"),
                    textposition="outside",
                ))
            _fig_comp.update_layout(
                barmode="group",
                title=f"Retorno · Volatilidad · Div Yield — perfil {prof.name} (top {_COMPARE_CAP} tickers)",
                height=420,
                yaxis_title="%",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(_fig_comp, use_container_width=True)

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
            f"Presioná **Comparar todos los universos** para ver qué universo "
            f"rinde mejor con el perfil **{prof.name}**."
        )
