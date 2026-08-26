"""Opportunity Screener — ranked table of the full ticker universe."""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

# NOTE: dashboard.shared must be imported first — it seeds the repo root onto
# sys.path (via bootstrap) so the first-party imports below resolve when this
# page is executed standalone rather than through dashboard/app.py.
from dashboard.shared import (
    _analyse_universe_parallel,
    _get_ai_config,
    cached_full_analysis,
    custom_source_badge,
    log_screener_run,
    render_calc_badge,
    render_row_actions,
    screener_column_config,
)
from analysis.asset_class import EQUITY, asset_class_label, is_fundamentally_scorable
from analysis.ranking import (
    FilterCriteria,
    apply_filters,
    attach_percentiles,
    build_shortlist,
    filter_preset,
    preset_gap,
    strip_badge,
)
from config import SCREENER, STRATEGY
from config import DATA_QUALITY
from data.preferences import UserPreferences
from data.screener_store import (
    ScreenerRun,
    filter_to_selected,
    format_eta,
    is_subset_cache_hit,
    merge_screener_rows,
    prioritize_universe,
    screener_run_store,
    uncovered_selected,
)
from data.product_ux import second_source_quality_signal, universe_quality_summary

# Letters, digits, dot and dash — covers BRK-B, BTC-USD, MELI.
_WATCH_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")

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
_universe_key = st.session_state.get("active_universe_key", "default")

# Audit items 15/17 — the previous run comes off disk, so reopening the app is
# not another cold five minutes, and its scores let a capped run keep the names
# that matter instead of the first N in file order.
_stored = screener_run_store.load(_universe_key) if SCREENER.persist_runs else None
_prev_scores = _stored.scores() if _stored else {}
try:
    _holdings = [p.symbol for p in st.session_state.portfolio.positions]
except Exception:
    _holdings = []

_ordered = prioritize_universe(
    tickers,
    watchlist=_prefs.watched_tickers or [],
    holdings=_holdings,
    previous_scores=_prev_scores,
)

# A universe smaller than the slider's floor made `min_value > max_value` and
# crashed the page outright — reachable with a small custom universe.
_SLIDER_FLOOR = 5
if len(tickers) <= _SLIDER_FLOOR:
    max_tickers = len(tickers)
    st.sidebar.caption(f"Universo chico: se analizan los {len(tickers)}.")
else:
    max_tickers = st.sidebar.slider(
        "Máximo de tickers a analizar", _SLIDER_FLOOR, len(tickers),
        min(SCREENER.default_max_tickers, len(tickers)),
        help=(
            "Cuántos analizar en esta corrida. Se priorizan tu watchlist, tus posiciones "
            "y los mejores de la corrida anterior — no los primeros del archivo."
        ),
    )
selected = _ordered[:max_tickers]

# Quick-add to watchlist from Screener sidebar (audit item 12).
# The add used to run *after* the counter was drawn, so the sidebar kept showing
# the old number until some later rerun; there was no validation and no way to
# remove. Handling the write in a callback puts it before the render.
st.sidebar.divider()
st.sidebar.subheader("📋 Watchlist")


def _add_to_watchlist() -> None:
    raw = str(st.session_state.get("screener_wl_input", "")).upper().strip()
    st.session_state["screener_wl_msg"] = ()
    if not raw:
        return
    if not _WATCH_RE.match(raw):
        st.session_state["screener_wl_msg"] = ("error", f"'{raw}' no parece un ticker válido.")
        return
    if _prefs.watch(raw):
        st.session_state.user_prefs = _prefs
        st.session_state["screener_wl_msg"] = ("success", f"✓ {raw} agregado")
        st.session_state["screener_wl_input"] = ""
    else:
        st.session_state["screener_wl_msg"] = ("info", f"{raw} ya estaba en la watchlist.")


st.sidebar.text_input(
    "Agregar a watchlist",
    placeholder="AAPL…",
    label_visibility="collapsed",
    key="screener_wl_input",
)
st.sidebar.button("➕ Agregar", key="screener_wl_btn", on_click=_add_to_watchlist)

_wl_msg = st.session_state.get("screener_wl_msg") or ()
if _wl_msg:
    getattr(st.sidebar, _wl_msg[0])(_wl_msg[1])

# Counter renders after the write, so it is never a rerun behind.
_watched = list(_prefs.watched_tickers or [])
if _watched:
    st.sidebar.caption(f"{len(_watched)} tickers seguidos")
    _drop = st.sidebar.selectbox(
        "Quitar de la watchlist", ["—"] + _watched, key="screener_wl_drop",
        label_visibility="collapsed",
    )
    if _drop != "—" and st.sidebar.button(f"➖ Quitar {_drop}", key="screener_wl_rm"):
        _prefs.unwatch(_drop)
        st.session_state.user_prefs = _prefs
        st.rerun()
else:
    st.sidebar.caption("Todavía no seguís ningún ticker.")

col_btn, col_hint = st.columns([1, 4])
with col_btn:
    refresh = st.button("🔄 Actualizar análisis", type="primary", width="stretch")
with col_hint:
    _spt = (_stored.seconds_per_ticker() if _stored else None) or SCREENER.fallback_seconds_per_ticker
    _est = format_eta(_spt * len(selected))
    st.caption(
        f"⚡ Corre en paralelo. {len(selected)} tickers en frío: **{_est}**"
        + (" (medido en tu última corrida)." if _stored and _stored.seconds_per_ticker() else " (estimado).")
        + " Con cache tibio es casi instantáneo."
    )

# Compared as a set: rows come back in thread-pool completion order, so a tuple
# would never match the requested order and the page would re-analyse every time
# it loaded a stored run (audit item 15).
_sel_key = frozenset(selected)
_cached_rows = st.session_state.get("screener_rows")
_cached_key = st.session_state.get("screener_rows_key")

# Audit item 15 — seed the session from disk on first load so reopening the app
# shows the last ranking instead of a blank page and another cold run.
if _cached_rows is None and _stored and _stored.rows:
    _cached_rows = _stored.rows
    # Failures are part of what the run covered (see `covered_tickers`). Keying
    # on rows alone meant one broken ticker made this key disagree with the
    # universe forever, so every reopen paid another cold run (audit item 15).
    _cached_key = frozenset(_stored.covered_tickers())
    st.session_state["screener_rows"] = _cached_rows
    st.session_state["screener_rows_key"] = _cached_key
    st.session_state["screener_failures"] = _stored.failures
    st.session_state["screener_rows_at"] = _stored.ran_at.replace("T", " ")[5:16]

# A partial re-run: retry of failures, refresh of stale rows, or resume of a
# universe the last run never finished.
_rerun_only = st.session_state.pop("screener_rerun_subset", None)


def _persist(new_rows, new_failures, duration_s, *, measured_n: int = 0,
             replace_throughput: bool = False) -> None:
    """Merge newly measured rows into the previous run. Log only those rows.

    ``measured_n`` is how many tickers ``duration_s`` actually covers — see
    ``ScreenerRun.seconds_per_ticker``. A subset must never replace the last
    full run's throughput, and must never drop uncovered rows from disk.
    """
    if new_rows:
        log_screener_run(new_rows)

    if not SCREENER.persist_runs:
        return

    if _cached_rows:
        prev_rows = list(_cached_rows)
        prev_failures = list(st.session_state.get("screener_failures") or [])
    elif _stored:
        prev_rows = list(_stored.rows)
        prev_failures = list(_stored.failures)
    else:
        prev_rows, prev_failures = [], []

    merged_rows, merged_failures = merge_screener_rows(
        prev_rows, prev_failures, new_rows or [], new_failures or [],
    )
    if not merged_rows and not merged_failures:
        return

    if replace_throughput:
        dur, mn = float(duration_s), int(measured_n)
    elif _stored:
        dur, mn = float(_stored.duration_s), int(_stored.measured_n)
    else:
        dur, mn = float(duration_s), int(measured_n)

    screener_run_store.save(ScreenerRun(
        universe_key=_universe_key, duration_s=dur,
        measured_n=mn, rows=merged_rows, failures=merged_failures,
    ))


if refresh:
    # Only invalidate this page's own analyses. `st.cache_data.clear()` used to
    # wipe every cache in the app — Monte Carlo runs, optimizer price matrices,
    # plan lookups — for a button that says "Refresh Analysis" (audit item 14).
    try:
        cached_full_analysis.clear()
    except Exception:  # pragma: no cover — older Streamlit without per-func clear
        st.cache_data.clear()
    _cached_rows = None
    _cached_key = None

# Show the last run instantly instead of a blank page; only (re)analyse when
# the user asks for a refresh or the selected universe has tickers not yet covered.
_covered = _cached_key or frozenset()
if _rerun_only:
    progress = st.progress(0)
    status = st.empty()
    ai_cfg = _get_ai_config(context="screener")
    _new_rows, _new_failures, _elapsed = _analyse_universe_parallel(
        list(_rerun_only), ai_cfg, progress, status,
        eta_per_ticker=(_stored.seconds_per_ticker() if _stored else None),
    )
    progress.empty()
    status.empty()

    # Replace measured rows in place; keep everything untouched by this subset.
    rows, failures = merge_screener_rows(
        _cached_rows or [],
        st.session_state.get("screener_failures") or [],
        _new_rows, _new_failures,
    )
    st.session_state["screener_rows"] = rows
    st.session_state["screener_failures"] = failures
    st.session_state["screener_rows_key"] = frozenset(
        {r["Ticker"] for r in rows} | {f.get("Ticker") for f in failures}
    )
    st.session_state["screener_rows_at"] = datetime.now().strftime("%d/%m %H:%M")
    # This measured `_rerun_only`, not the table. Storing its seconds against
    # every row divided ~11s by all 85 and promised the next cold run in ~11s —
    # audit item 13 all over again. A subset, which may also be answering from
    # the warm 1h cache, is not a measurement of what a full run costs, so the
    # last full run's throughput is carried forward rather than overwritten.
    _persist(_new_rows, _new_failures, _elapsed)
    _recovered = {r["Ticker"] for r in _new_rows} & set(_rerun_only)
    if _recovered:
        st.success(f"✓ Actualizados: {', '.join(sorted(_recovered))}")
    rows = filter_to_selected(rows, selected)
    failures = filter_to_selected(failures, selected)
elif _cached_rows is not None and is_subset_cache_hit(selected, _covered):
    rows = filter_to_selected(_cached_rows, selected)
    failures = filter_to_selected(st.session_state.get("screener_failures") or [], selected)
    _when = st.session_state.get("screener_rows_at", "")
    st.caption(
        f"📋 Mostrando la última corrida{f' ({_when})' if _when else ''} · "
        f"{len(rows)} tickers. Tocá **🔄 Actualizar análisis** para volver a medir."
    )
else:
    _need = uncovered_selected(selected, _covered)
    progress = st.progress(0)
    status = st.empty()

    ai_cfg = _get_ai_config(context="screener")
    _new_rows, _new_failures, _elapsed = _analyse_universe_parallel(
        _need, ai_cfg, progress, status,
        eta_per_ticker=(_stored.seconds_per_ticker() if _stored else None),
    )

    progress.empty()
    status.empty()

    prev_fail = st.session_state.get("screener_failures") or (_stored.failures if _stored else [])
    rows, failures = merge_screener_rows(
        _cached_rows or (_stored.rows if _stored else []),
        prev_fail,
        _new_rows, _new_failures,
    )
    st.session_state["screener_rows"] = rows
    st.session_state["screener_rows_key"] = frozenset(
        {r["Ticker"] for r in rows} | {f.get("Ticker") for f in failures}
    )
    st.session_state["screener_rows_at"] = datetime.now().strftime("%d/%m %H:%M")
    st.session_state["screener_failures"] = failures
    # A first run with no previous store is the only honest basis for ETA.
    _persist(
        _new_rows, _new_failures, _elapsed,
        measured_n=len(_new_rows) + len(_new_failures),
        replace_throughput=not (_stored or _cached_rows),
    )
    rows = filter_to_selected(rows, selected)
    failures = filter_to_selected(failures, selected)

# ------------------------------------------------------------------ #
#  Audit item 16 — refresh what needs it, not all 85                  #
# ------------------------------------------------------------------ #
# The page already knew which rows were stale (the ⏳ badge) and which tickers a
# run never reached, but the only button was "redo everything".
_run_now = ScreenerRun(universe_key=_universe_key, rows=rows or [], failures=failures or [])
_stale = _run_now.stale_tickers(DATA_QUALITY.stale_warning_hours)
_missing = _run_now.missing_tickers(selected)

if _stale or _missing:
    _s1, _s2, _s3 = st.columns([3, 1.2, 1.2])
    _bits = []
    if _stale:
        _bits.append(f"⏳ {len(_stale)} con más de {DATA_QUALITY.stale_warning_hours:.0f}h")
    if _missing:
        _bits.append(f"🕳️ {len(_missing)} sin medir")
    _spt_now = (_stored.seconds_per_ticker() if _stored else None) or SCREENER.fallback_seconds_per_ticker
    _s1.caption("Actualización parcial disponible: " + " · ".join(_bits))
    if _stale and _s2.button(
        f"⏳ Refrescar {len(_stale)} ({format_eta(_spt_now * len(_stale))})",
        key="screener_refresh_stale", width="stretch",
    ):
        st.session_state["screener_rerun_subset"] = _stale
        st.rerun()
    if _missing and _s3.button(
        f"🕳️ Medir {len(_missing)} ({format_eta(_spt_now * len(_missing))})",
        key="screener_run_missing", width="stretch",
    ):
        st.session_state["screener_rerun_subset"] = _missing
        st.rerun()

# Audit item 05 — a ticker that blew up used to leave no trace at all: no row, no
# message, and "Stocks screened" counted only the survivors. Name them, say why,
# and offer to retry just those.
if failures:
    _n_failed = len(failures)
    _n_asked = len(selected)
    with st.expander(
        f"⚠️ {_n_failed} de {_n_asked} tickers no se pudieron analizar — no están en la tabla",
        expanded=False,
    ):
        st.caption(
            "Estos símbolos fallaron al traer o procesar datos. **No aparecen en el ranking "
            "ni en los contadores de abajo** — no es que no califiquen, es que no se midieron."
        )
        st.dataframe(
            pd.DataFrame(failures)[["Ticker", "Tipo", "Error"]],
            width="stretch",
            hide_index=True,
        )
        if st.button(f"🔁 Reintentar los {_n_failed} fallidos", key="screener_retry_btn"):
            st.session_state["screener_rerun_subset"] = [f["Ticker"] for f in failures]
            st.rerun()

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
# Audit item 12 — the watchlist is edited in this page's sidebar but never showed
# up in the results. Computed here rather than in the row builder so following a
# ticker reflects immediately, without re-running the analysis.
_watched_set = {t.upper() for t in (_prefs.watched_tickers or [])}
df["⭐"] = df["Ticker"].apply(lambda t: "⭐" if str(t).upper() in _watched_set else "")
_n_custom = int((df["Fuente"] == "⚠️ Propio").sum())
if _n_custom:
    st.warning(
        f"🧪 {_n_custom} ticker(s) **personalizado(s)** en este universo. Su scoring y "
        "calidad de datos pueden ser parciales — están marcados como **⚠️ Propio** en la "
        "columna *Fuente*. Tratalos como experimentales.",
        icon="⚠️",
    )

# ------------------------------------------------------------------ #
#  Audit item 01 — segment by asset class before ranking anything     #
# ------------------------------------------------------------------ #
# The fundamental scorer reads ROE, Piotroski and moat off financial statements.
# Index ETFs, bond funds and crypto have none, so running them through it does
# not give them a low score — it gives them a meaningless one, which the decision
# engine then published as SELL. Measured on this universe: SPY/QQQ/VTI/BND/
# SCHD/VGT scored 22–25 and were the six worst of 85, each flagged SELL. They are
# the canonical core of a retirement portfolio. They get their own section, with
# no score and no signal, instead of competing against companies.
def _render_non_scorable(frame) -> None:
    """The funds/crypto table. A function because two paths reach it: the normal
    one at the bottom of the page, and the run that has no companies at all."""
    if frame.empty:
        return
    st.subheader(f"🧺 Fondos, ETFs y cripto · {len(frame)}")
    st.info(
        "Estos activos **no tienen estados financieros**, así que el score fundamental "
        "(ROE, Piotroski, moat) y la señal que sale de él no aplican: no se les calcula "
        "ranking ni recomendación en esta página. Antes aparecían al fondo de la tabla con "
        "señal de venta, que era un artefacto de medirlos con una vara ajena. "
        "Se muestran precio, señal técnica y calidad de datos, que sí significan algo.",
        icon="🧺",
    )
    _other_cols = [
        "⭐", "Ticker", "Company", "Clase", "Fuente", "Technical",
        "Div Yield %", "Price", "Datos",
    ]
    st.dataframe(
        frame[_other_cols],
        width="stretch",
        hide_index=True,
        column_config=screener_column_config(_other_cols),
    )
    render_calc_badge(
        "para evaluar un ETF mirá costo, tracking y exposición — no fundamentales de empresa"
    )


if "Clase" not in df.columns:   # rows cached by a previous version of this page
    df["Clase"] = EQUITY
# Rows of mixed vintage leave the column present but null for the older ones, and
# a null is not "not a company": it would file real equities under funds, with
# the literal string "nan" as their class. Unknown means equity, same as above.
df["Clase"] = df["Clase"].fillna(EQUITY)
_scorable_mask = df["Clase"].apply(is_fundamentally_scorable)
df_equity = df[_scorable_mask].copy()
df_other  = df[~_scorable_mask].copy()
df_other["Clase"] = df_other["Clase"].apply(asset_class_label)

# Nothing to rank: a custom universe of ETFs, or a run where every company failed.
# `attach_percentiles([])` returns [], whose DataFrame has no columns at all, so
# sorting it by "Score bruto" killed the page — including the funds table that
# exists precisely for these assets. Show them and stop.
if df_equity.empty:
    st.info(
        f"Ninguno de los {len(df)} activos de esta corrida tiene estados financieros, "
        "así que no hay ranking que calcular: el score fundamental y su señal no les "
        "aplican. Abajo van con precio, señal técnica y calidad de datos, que sí "
        "significan algo. Agregá acciones al universo en **⚙️ Settings** para usar el "
        "ranking, el embudo y los filtros.",
        icon="🧺",
    )
    _render_non_scorable(df_other)
    st.stop()

# ------------------------------------------------------------------ #
#  Audit items 06 + 11 — rank relative to the run, and break the ties #
# ------------------------------------------------------------------ #
# 86% of the companies carried a buy signal and the median score (74.8) sat right
# on the "Strong Buy ≥75" line: absolute thresholds calibrated against the whole
# market cannot cut an already-curated quality universe. The percentile below adds
# the missing relative dimension, and "Score bruto" (uncapped) restores the
# ordering the [0,100] clamp destroys among the top names.
if "Score bruto" not in df_equity.columns:   # rows cached by an older page version
    df_equity["Score bruto"] = df_equity["Adj. Score"]
_ranked = attach_percentiles(df_equity.to_dict("records"))
df_equity = pd.DataFrame(_ranked).sort_values(
    ["Score bruto", "Adj. Score"], ascending=False
)
_shortlist = build_shortlist(_ranked)

# The funnel replaces the old counters. "67 with a buy signal" is a step, not an
# answer, and presenting it as a headline was the whole of audit item 06.
_cols = st.columns(len(_shortlist.steps))
for _col, _step in zip(_cols, _shortlist.steps):
    _col.metric(
        _step.label, _step.kept,
        # The delta is a subtitle ("−10 quedaron afuera"), not a trend: without
        # delta_arrow="off" Streamlit renders an up-arrow on a negative number.
        # Same pitfall the goal-card audit hit — see CONTEXT §8.
        delta=(f"−{_step.dropped} afuera" if _step.dropped else None),
        delta_arrow="off",
        delta_color="off",
        help=_step.detail or None,
    )

st.markdown(f"### {_shortlist.summary()}")
if failures:
    st.caption(f"⚠️ Además, {len(failures)} tickers fallaron y no entraron en ningún paso.")

if _shortlist.rows:
    _short_df = pd.DataFrame(_shortlist.rows)
    # Audit item 07 rides along: a shortlist that is one sector is one bet.
    # `value_counts()` drops nulls, so a shortlist with no sector at all yields an
    # empty Series and `.iloc[0]` raised instead of simply having nothing to warn.
    _sectors = _short_df["Sector"].value_counts()
    _top_sector_pct = float(_sectors.iloc[0]) / len(_short_df) * 100 if len(_sectors) else 0.0
    if _top_sector_pct >= SCREENER.concentration_warn_pct:
        st.warning(
            f"🎯 **{_sectors.index[0]}** es {_top_sector_pct:.0f}% de esta lista "
            f"({int(_sectors.iloc[0])} de {len(_short_df)}). Comprar la lista entera es "
            "una sola apuesta sectorial repetida, no una cartera diversificada.",
            icon="🎯",
        )
    _short_cols = [
        "⭐", "Ticker", "Company", "Sector", "Signal", "Motivo", "Conf.",
        "Percentil", "Adj. Score", "Score bruto", "Moat", "Viento", "Datos",
    ]
    _short_event = st.dataframe(
        _short_df[_short_cols],
        width="stretch",
        hide_index=True,
        column_config=screener_column_config(_short_cols),
        on_select="rerun",
        selection_mode="single-row",
        key="screener_shortlist_select",
    )
    render_calc_badge(
        f"percentil calculado sobre las {len(df_equity)} acciones de esta corrida — "
        "cambia si cambiás el universo"
    )
    render_row_actions(_short_df, _short_event, prefix="short")

# ------------------------------------------------------------------ #
#  Audit item 03 — quality headline computed, not asserted            #
# ------------------------------------------------------------------ #
# This used to print `"partial" if any_custom_ticker else "good"`, so it claimed
# "calidad good" directly above a warning reporting 7 poor and 63 partial rows in
# the same run. Both numbers now come from the same place: the rows on screen.
_dq_rollup = universe_quality_summary(df["_dq"] if "_dq" in df.columns else [])
_sig_home = second_source_quality_signal(
    None,
    data_quality={"level": _dq_rollup["level"], "stale": bool(_dq_rollup["n_stale"])},
)
st.caption(f"🔬 {_sig_home['message']} · En **Stock Analysis** podés reconciliar SEC vs Yahoo por ticker.")

if _dq_rollup["level"] in ("partial", "poor") or _dq_rollup["n_stale"]:
    st.warning(
        f"**Calidad de datos (yfinance).** {_dq_rollup['message']} "
        "Los tickers con datos incompletos reciben scores neutrales en las métricas "
        "faltantes, y la política de calidad puede bajarles la señal — revisá la columna "
        "**Datos** antes de confiar en su ranking. Usá 🔄 Actualizar análisis para refrescar el cache.",
        icon="🧪",
    )

# ------------------------------------------------------------------ #
#  Audit item 09 — filters on the full table                          #
# ------------------------------------------------------------------ #
# These narrow the table only, never the funnel above. Recomputing the funnel on
# a filtered subset would make "top 25%" quietly mean "top 25% of Healthcare"
# while still being labelled as the universe.
st.subheader(f"📈 Todas las acciones analizadas · {len(df_equity)}")
st.caption(
    "La lista completa, ordenada por score. Las de arriba son las destacadas; "
    "el resto queda acá para que puedas revisar por qué no pasaron. "
    "**Los filtros afectan solo esta tabla** — el embudo de arriba siempre se "
    "calcula sobre el universo entero."
)

_FILTER_KEYS = {
    "flt_search": "", "flt_sectors": [], "flt_signals": [], "flt_moats": [],
    "flt_quality": [], "flt_pct": 0, "flt_watch": False,
}


def _clear_filters() -> None:
    """Reset every filter widget.

    Must run as an ``on_click`` callback: callbacks fire *before* the rerun, and
    Streamlit refuses `st.session_state[key] = …` once the widget with that key
    has been instantiated in the current run.
    """
    for key, default in _FILTER_KEYS.items():
        st.session_state[key] = default
    st.session_state["flt_preset"] = _NO_PRESET


def _apply_preset() -> None:
    """Seed the filter widgets from a named preset so the user can tweak it."""
    name = st.session_state.get("flt_preset")
    if not name or name == _NO_PRESET:
        return
    crit = filter_preset(name)
    st.session_state["flt_search"] = crit.search
    st.session_state["flt_sectors"] = list(crit.sectors)
    st.session_state["flt_signals"] = list(crit.signals)
    # The "Foso ancho" preset asks on this axis; without the widget it seeded
    # nothing, cleared every other filter, and showed the whole table under a
    # name that promised a slice of it.
    st.session_state["flt_moats"] = list(crit.moats)
    st.session_state["flt_quality"] = list(crit.quality_levels)
    st.session_state["flt_pct"] = int(crit.min_percentile)
    st.session_state["flt_watch"] = bool(crit.only_watchlist)


_NO_PRESET = "— sin preset —"
_sector_opts = sorted(df_equity["Sector"].dropna().unique().tolist())
_signal_opts = sorted({strip_badge(s) for s in df_equity["Signal"] if strip_badge(s)})
# `apply_filters` has always supported the moat axis and two presets ask on it —
# the widget was simply never built, so those presets did nothing.
_moat_opts = sorted({strip_badge(m) for m in df_equity["Moat"] if strip_badge(m)})

with st.container(border=True):
    _f1, _f2, _f3 = st.columns([2, 2, 2])
    _f1.text_input("Buscar", key="flt_search", placeholder="AAPL o Apple…")
    _f2.selectbox("Preset", [_NO_PRESET] + list(SCREENER.filter_presets),
                  key="flt_preset", on_change=_apply_preset)
    _f3.multiselect("Sector", _sector_opts, key="flt_sectors")

    _f4, _f5, _f6, _f7, _f8 = st.columns([2, 2, 2, 2, 1.4])
    _f4.multiselect("Señal", _signal_opts, key="flt_signals")
    _f5.multiselect("Foso", _moat_opts, key="flt_moats",
                    help="Ventaja competitiva: Wide / Narrow / Minimal / None.")
    _f6.multiselect("Calidad de datos", ["good", "partial", "poor"], key="flt_quality")
    _f7.slider("Percentil mínimo", 0, 100, key="flt_pct",
               help="0 = sin filtro. 75 = solo el cuartil superior de esta corrida.")
    _f8.checkbox("Solo watchlist", key="flt_watch")

_criteria = FilterCriteria(
    search=st.session_state.get("flt_search", ""),
    sectors=tuple(st.session_state.get("flt_sectors", [])),
    signals=tuple(st.session_state.get("flt_signals", [])),
    moats=tuple(st.session_state.get("flt_moats", [])),
    quality_levels=tuple(st.session_state.get("flt_quality", [])),
    min_percentile=float(st.session_state.get("flt_pct", 0) or 0),
    only_watchlist=bool(st.session_state.get("flt_watch", False)),
)

# Streamlit silently drops multiselect values that are not among this run's
# options, so a preset can resolve to "no filter at all" while its name stays in
# the box — "Lo que descarté" over a universe that is 86 % buys showed all 78
# rows. Say it, instead of letting the label lie about what is on screen.
_active_preset = st.session_state.get("flt_preset", _NO_PRESET)
_gap = preset_gap(filter_preset(_active_preset), _criteria) if _active_preset != _NO_PRESET else {}
if _gap:
    _gap_bits = " · ".join(
        f"{axis}: {', '.join(str(v) for v in vals)}" for axis, vals in _gap.items()
    )
    st.caption(
        f"⚠️ El preset **{_active_preset}** pide {_gap_bits}, y ninguna acción de esta "
        "corrida lo cumple — ese filtro no se aplicó."
    )
_visible = apply_filters(
    df_equity.to_dict("records"), _criteria,
    watchlist=getattr(_prefs, "watched_tickers", []) or [],
)

if _criteria.is_active():
    _c1, _c2 = st.columns([4, 1])
    _c1.caption(f"🔎 Mostrando **{len(_visible)}** de {len(df_equity)} acciones.")
    _c2.button("Limpiar filtros", key="flt_clear", width="stretch",
               on_click=_clear_filters)

# The filtered view. `df_equity` stays whole — the funds section, the chart's
# reference lines and the percentile caption all still describe the full run.
df_view = pd.DataFrame(_visible) if _visible else df_equity.iloc[0:0]

if df_view.empty:
    st.info(
        "Ningún ticker cumple estos filtros. Aflojá alguno o tocá **Limpiar filtros**.",
        icon="🔎",
    )
else:
    # Audit item 08: "Adj. Score" is the column the table is sorted by, so it has
    # to BE in the table. The ASCII "Score Bar" it used to stand behind sorted
    # lexicographically — a plausible, wrong order. ProgressColumn draws the bar.
    _all_df = df_view.rename(columns={
        "Consistency": "Consist./15",
        "Piotroski":   "Piotroski/9",
        "Moat Score":  "Moat/20",
    })
    _all_cols = [
        "⭐", "Ticker", "Company", "Sector", "Fuente", "Signal", "Motivo", "Conf.",
        "Percentil", "Adj. Score",
        "Score bruto", "Consist./15", "Piotroski/9", "Moat/20", "Moat", "Viento",
        "Technical", "P/E", "ROE %", "Rev CAGR %", "CAGR años", "Div Yield %", "MoS %", "Price", "Datos",
    ]
    _all_event = st.dataframe(
        _all_df[_all_cols],
        width="stretch",
        hide_index=True,
        column_config=screener_column_config(_all_cols),
        on_select="rerun",
        selection_mode="single-row",
        key="screener_all_select",
    )
    render_row_actions(df_view, _all_event, prefix="all")

# Non-fundamental vehicles — listed, never scored.
_render_non_scorable(df_other)

# Score distribution chart — companies only, for the same reason.
# ------------------------------------------------------------------ #
#  Audit item 19 — two charts that say something, not 78 bars         #
# ------------------------------------------------------------------ #
# This used to draw one horizontal bar per company: 78 rows at 22px is a ~1.700px
# wall that nobody scrolls and that repeats, less legibly, the table right above
# it. The distribution is the thing the table cannot show — and it is exactly
# what makes the calibration problem visible (the median sitting on the
# "Strong Buy" line). Top-N answers "who leads"; the histogram answers "compared
# to what".
_chart_df = df_view if not df_view.empty else df_equity
_top_n = min(SCREENER.chart_top_n, len(_chart_df))
_c_left, _c_right = st.columns([1, 1])

with _c_left:
    _top_df = _chart_df.nlargest(_top_n, "Score bruto")
    _suffix = " (filtradas)" if _criteria.is_active() and not df_view.empty else ""
    fig = px.bar(
        _top_df.sort_values("Score bruto", ascending=True),
        x="Score bruto", y="Ticker", orientation="h",
        color="Score bruto", color_continuous_scale="RdYlGn",
        range_color=[0, 100],
        title=f"Top {_top_n} por score{_suffix}",
        labels={"Score bruto": "Score ajustado (sin tope)"},
    )
    fig.add_vline(
        x=STRATEGY.strong_buy_score, line_dash="dash", line_color="green",
        annotation_text=f"Strong Buy ≥{STRATEGY.strong_buy_score:.0f}",
    )
    fig.update_layout(height=max(320, _top_n * 26), yaxis_title="",
                      coloraxis_showscale=False, margin=dict(t=60, b=20))
    st.plotly_chart(fig, width="stretch")

with _c_right:
    _hist = px.histogram(
        _chart_df, x="Adj. Score", nbins=20,
        title=f"Distribución de las {len(_chart_df)} acciones",
        labels={"Adj. Score": "Score ajustado"},
    )
    _median = float(_chart_df["Adj. Score"].median())
    _hist.add_vline(
        x=STRATEGY.buy_score, line_dash="dash", line_color="orange",
        annotation_text=f"Buy ≥{STRATEGY.buy_score:.0f}",
    )
    _hist.add_vline(
        x=STRATEGY.strong_buy_score, line_dash="dash", line_color="green",
        annotation_text=f"Strong Buy ≥{STRATEGY.strong_buy_score:.0f}",
    )
    _hist.add_vline(
        x=_median, line_color="#666",
        annotation_text=f"mediana {_median:.1f}", annotation_position="bottom right",
    )
    _hist.update_layout(height=max(320, _top_n * 26), yaxis_title="acciones",
                        showlegend=False, margin=dict(t=60, b=20))
    st.plotly_chart(_hist, width="stretch")

if _median >= STRATEGY.buy_score:
    st.caption(
        f"📐 La mediana del universo ({_median:.1f}) está por encima de la línea "
        f"**Buy ≥{STRATEGY.buy_score:.0f}**: los umbrales absolutos están calibrados "
        "contra el mercado entero, no contra una lista ya filtrada por calidad. "
        "Por eso el ranking usa además el **percentil dentro de esta corrida**."
    )

st.caption(
    "💡 Tocá una fila de cualquier tabla para analizar ese ticker, seguirlo o llevarlo "
    "al comité — el análisis completo (Piotroski, Moat y AI) se abre en **🔍 Stock Analysis**. "
    "🌬️ **Viento** = cola de viento estructural sector-país (dato curado, ej. Vaca Muerta "
    "para energía argentina) — outlook a la fecha de curaduría, no garantía."
)
