"""Track Record — historial auditable de recomendaciones y su calibración (Fase 1)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from loguru import logger

from analysis.track_record import track_record_store
from analysis.track_record_scorer import (
    calibration_by_confidence,
    equity_curve,
    hit_rate_by_action,
    hit_rate_by_source,
    score_due_recommendations,
    summary_stats,
)
from config import TRACK_RECORD

st.title("📒 Track Record")
st.caption(
    "Historial auditable de cada recomendación que emitió el motor y su acierto medido "
    "contra el benchmark. Convierte el “creeme” en “acá está mi historial”."
)

# Honest-framing note (requisito de producto del Gran Salto).
st.info(
    "**Lectura honesta.** Esto muestra aciertos *y* errores, en horizontes largos "
    f"({', '.join(str(h) for h in TRACK_RECORD.horizons_days)} días) y sin elegir ventanas "
    "favorables. Una recomendación solo se evalúa cuando su horizonte ya transcurrió; las "
    "recientes todavía no tienen resultado.",
    icon="🔍",
)

# ------------------------------------------------------------------ #
#  Controls                                                            #
# ------------------------------------------------------------------ #

ctrl_l, ctrl_r = st.columns([3, 1])
with ctrl_l:
    horizon = st.selectbox(
        "Horizonte de evaluación (días)",
        options=list(TRACK_RECORD.horizons_days),
        index=0,
        help="Cada recomendación se puntúa a múltiples horizontes; elegí cuál ver.",
    )
with ctrl_r:
    st.write("")
    st.write("")
    if st.button("🔄 Puntuar pendientes", help="Evalúa recomendaciones cuyo horizonte ya venció (puede tardar)."):
        with st.spinner("Puntuando recomendaciones vencidas…"):
            try:
                result = score_due_recommendations()
                _msg = (
                    f"Listo: {result['scored']} puntuadas, "
                    f"{result['skipped']} salteadas (sin precio)."
                )
                if result.get("partial"):
                    _msg += (
                        f" {result['partial']} quedaron sin benchmark "
                        f"({TRACK_RECORD.benchmark}): se reintentan en la próxima corrida."
                    )
                st.success(_msg)
            except Exception as exc:  # pragma: no cover - UI guard
                logger.error(f"track_record page: scoring failed — {exc}")
                st.error(f"No se pudo puntuar: {exc}")

rows = track_record_store.get_scored_rows(horizon)
all_recs = track_record_store.get_recommendations()

# Source filter. The Screener logs everything it analyses as `screener`, which is the
# unbiased sample calibration needs — but those are recommendations nobody looked at,
# so they must not silently become the headline of "how the model did".
_sources = sorted({(r.get("source") or "").lower() for r in rows if r.get("source")})
if len(_sources) > 1:
    _picked = st.multiselect(
        "Fuente",
        options=_sources,
        default=_sources,
        help=(
            "`screener` son corridas completas del universo — muestra sin sesgo de "
            "selección, ideal para calibrar. El resto son recomendaciones que "
            "efectivamente viste."
        ),
    )
    if _picked:
        rows = [r for r in rows if (r.get("source") or "").lower() in _picked]

# ------------------------------------------------------------------ #
#  Headline                                                            #
# ------------------------------------------------------------------ #

stats = summary_stats(rows)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Recomendaciones logueadas", len(all_recs))
m2.metric("Evaluadas a este horizonte", stats["n"])
m3.metric(
    "Tasa de acierto",
    f"{stats['overall_hit_rate'] * 100:.0f}%" if stats["overall_hit_rate"] is not None else "—",
)
m4.metric(
    "Exceso medio vs benchmark",
    f"{stats['mean_excess_pct']:+.1f}%" if stats["mean_excess_pct"] is not None else "—",
    help=(
        f"Promedio sobre las {stats['n_excess']} recomendaciones que tienen un exceso medido. "
        "Una recomendación cuyo benchmark no se pudo cotizar no entra: sin el dato del "
        "mercado no hay exceso que promediar."
    ),
)

# A row whose benchmark could not be priced is *incomplete*, never a win (U2-4).
if stats.get("n_benchmark_missing"):
    st.warning(
        f"**{stats['n_benchmark_missing']}** recomendaciones evaluadas a este horizonte no "
        f"tienen cotización de {TRACK_RECORD.benchmark} en alguno de los dos extremos. No "
        "cuentan como acierto ni como error, y su exceso no entra en ningún promedio — se "
        "vuelven a intentar cada vez que corrés la puntuación.",
        icon="⚠️",
    )

# One honest line that combines the numbers above — no spin.
if stats["n"] > 0 and stats["overall_hit_rate"] is not None:
    _hr = stats["overall_hit_rate"] * 100
    _ex = stats["mean_excess_pct"]
    if _ex is None:
        _verdict = (
            f"De las **{stats['n']}** recomendaciones evaluables a este horizonte, "
            f"acertó el **{_hr:.0f}%**."
        )
    else:
        _beat = "le ganó al" if _ex >= 0 else "quedó por debajo del"
        _verdict = (
            f"De las **{stats['n']}** recomendaciones evaluables a este horizonte, "
            f"acertó el **{_hr:.0f}%** y en promedio {_beat} mercado por **{_ex:+.1f}%**."
        )
    st.info(_verdict, icon="📒")

if stats["n"] == 0:
    if rows:
        st.warning(
            "Hay resultados guardados a este horizonte, pero ninguno se pudo calificar: a "
            f"todos les falta la cotización de {TRACK_RECORD.benchmark}. Volvé a correr la "
            "puntuación cuando el dato esté disponible."
        )
    else:
        st.warning(
            "Todavía no hay recomendaciones evaluadas a este horizonte. A medida que pase el "
            "tiempo y corras la puntuación, esta página se va a poblar."
        )
    st.stop()

# ------------------------------------------------------------------ #
#  Calibración por confianza                                           #
# ------------------------------------------------------------------ #

st.subheader("🎯 Calibración por nivel de confianza")
st.caption("Un modelo bien calibrado acierta más cuando dice HIGH que cuando dice LOW.")

calib = calibration_by_confidence(rows)
calib_df = pd.DataFrame(
    [
        {
            "Confianza": level,
            "N": d["n"],
            "Tasa de acierto": (d["hit_rate"] * 100 if d["hit_rate"] is not None else None),
            "N con exceso": d["n_excess"],
            "Exceso medio %": d["mean_excess_pct"],
        }
        for level, d in calib.items()
    ]
)
cc1, cc2 = st.columns([1, 1])
with cc1:
    st.dataframe(calib_df, hide_index=True, use_container_width=True)
with cc2:
    plot_df = calib_df.dropna(subset=["Tasa de acierto"]).set_index("Confianza")["Tasa de acierto"]
    if not plot_df.empty:
        st.bar_chart(plot_df)

# ------------------------------------------------------------------ #
#  Equity curve                                                        #
# ------------------------------------------------------------------ #

st.subheader("📈 Curva de equity — señales del modelo vs benchmark")
st.caption(
    f"Crecimiento compuesto de $1 siguiendo las señales alcistas del modelo, contra "
    f"{TRACK_RECORD.benchmark} en los mismos tramos."
)
eq = equity_curve(rows)
if not eq.empty:
    eq_plot = eq.set_index("created_at")[["model_equity", "benchmark_equity"]].rename(
        columns={"model_equity": "Modelo", "benchmark_equity": TRACK_RECORD.benchmark}
    )
    st.line_chart(eq_plot)
else:
    st.caption("Sin señales alcistas evaluadas todavía.")

# ------------------------------------------------------------------ #
#  Hit rate by action / source                                         #
# ------------------------------------------------------------------ #

hc1, hc2 = st.columns(2)
with hc1:
    st.subheader("Por acción")
    st.caption(
        "El **margen** es el ancho de la incertidumbre al 95 %: el promedio es "
        "compatible con cualquier valor dentro de ± ese número. Cuando el margen es "
        "mayor que el promedio, la fila dice «sin señal» — todavía no hay muestra "
        "para distinguirlo de cero. **N** cuenta las recomendaciones calificables y "
        "**N con exceso** las que además tienen benchmark: difieren cuando falta la "
        "cotización del mercado."
    )
    act = hit_rate_by_action(rows)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Acción": k,
                    "N": v["n"],
                    "Acierto %": round(v["hit_rate"] * 100, 0),
                    "N con exceso": v["n_excess"],
                    "Exceso medio %": v["mean_excess_pct"],
                    "Margen ±": v.get("excess_band_pct"),
                    "Lectura": "sin señal" if v.get("inconclusive") else "distinguible de 0",
                }
                for k, v in act.items()
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
with hc2:
    st.subheader("Por fuente")
    st.caption("Comparar rule_based vs ai (y, en Fase 2, committee).")
    src = hit_rate_by_source(rows)
    st.dataframe(
        pd.DataFrame(
            [{"Fuente": k, "N": v["n"], "Acierto %": round(v["hit_rate"] * 100, 0)} for k, v in src.items()]
        ),
        hide_index=True,
        use_container_width=True,
    )

# ------------------------------------------------------------------ #
#  Detail table                                                        #
# ------------------------------------------------------------------ #

st.subheader("🧾 Detalle de recomendaciones evaluadas")
detail = pd.DataFrame(rows)
if not detail.empty:
    detail = detail[
        [
            "created_at", "symbol", "action", "confidence", "source",
            "price_at_rec", "return_pct", "benchmark_return_pct", "excess_return_pct", "hit",
            "benchmark_missing",
        ]
    ].rename(
        columns={
            "created_at": "Fecha",
            "symbol": "Ticker",
            "action": "Acción",
            "confidence": "Confianza",
            "source": "Fuente",
            "price_at_rec": "Precio inicial",
            "return_pct": "Retorno %",
            "benchmark_return_pct": "Benchmark %",
            "excess_return_pct": "Exceso %",
            "hit": "Acierto",
            "benchmark_missing": "Sin benchmark",
        }
    )
    st.dataframe(detail.sort_values("Fecha", ascending=False), hide_index=True, use_container_width=True)
