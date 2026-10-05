"""Supuestos — de dónde salen los rendimientos de cada Clase de activo (EO-2a/2b, ADR 0001).

Muestra, por Clase, la mediana de las Fuentes vigentes (el central), su rango (el
Desacuerdo) y cada Fuente con su fecha, su antigüedad y su cita. Todavía no alimenta
ningún motor: Simulaciones y el Optimizer siguen con su método hasta EO-4.
"""

from __future__ import annotations

import streamlit as st

import analysis.fuentes as fuentes
from config import FUENTES

st.title("🧭 Supuestos")
st.caption(
    "De dónde salen los rendimientos esperados de cada Clase de activo. Cada número es "
    "de una **Fuente** con fecha y cita —una gestora, la valuación de hoy o la historia "
    "de la Clase—; el **central** es la mediana de las Fuentes vigentes y el "
    "**Desacuerdo**, su rango. 💵 Nominal, en USD, anual."
)
st.info(
    "Estos supuestos todavía **no alimentan** las proyecciones: Simulaciones y el "
    "Optimizer siguen con su método actual hasta que la Estimación objetiva los use.",
    icon="ℹ️",
)

_today = fuentes.today()
_summaries = fuentes.summarize_all(fuentes.load_shipped(), today=_today)


def _kind_label(f) -> str:
    if f.kind == "historia" and f.period_start:
        return f"historia {f.period_start:%Y-%m} → {f.as_of:%Y-%m}"
    return {"gestora": "gestora", "valuacion": "valuación"}.get(f.kind, f.kind)


def _source_line(f, flag: str) -> str:
    rng = f" (rango {f.range_pct[0]:.1f}%–{f.range_pct[1]:.1f}%)" if f.range_pct else ""
    age = fuentes.age_months(f.as_of, _today)
    return (
        f"**{f.name}** ({_kind_label(f)}): {f.value_pct:.1f}%{rng} · {f.basis}, {f.currency} · al "
        f"{f.as_of.isoformat()} ({age} meses){flag} · [cita]({f.source})"
    )


for _cls, _label in FUENTES.asset_classes.items():
    s = _summaries[_cls]
    st.markdown(f"#### {_label}")
    if s.declared_absent:
        st.info(
            f"**{_label}: sin Fuente externa.** Ninguna gestora publica un rendimiento "
            "esperado creíble para esta Clase, así que no hay central: la app no inventa uno.",
            icon="🕳️",
        )
        continue
    if s.central_pct is None:
        st.caption("Sin Fuentes vigentes cargadas todavía para esta Clase.")
    else:
        st.markdown(
            f"**Central {s.central_pct:.1f}%** · Desacuerdo {s.low_pct:.1f}%–{s.high_pct:.1f}% "
            f"· {len(s.used)} Fuente(s)"
        )
    for f in s.used:
        _flag = (f" · ⚠️ vieja (más de {FUENTES.stale_warn_months} meses)"
                 if f in s.stale else "")
        st.caption(_source_line(f, _flag))
    for f in s.excluded:
        st.caption(_source_line(
            f, f" · ⛔ fuera del central (más de {FUENTES.stale_drop_months} meses)"
        ))

st.divider()
with st.expander("🗂️ Tu universo por Clase de activo", expanded=False):
    st.caption(
        "Cada ticker del universo activo va a la Clase de su país (o, si es un fondo, a la "
        "que tiene asignada). Un ticker que no se puede clasificar se nombra acá."
    )
    if st.button("Clasificar el universo activo", key="supuestos_classify"):
        from analysis.asset_class import classify_asset
        from data.fetcher import get_info

        _by_class: dict[str, list[str]] = {}
        _rows = []
        for _sym in st.session_state.get("universe", []):
            _info = get_info(_sym) or {}
            _row = {"symbol": _sym, "country": _info.get("country"),
                    "sector": _info.get("sector"),
                    "kind": classify_asset(_sym, quote_type=_info.get("quoteType"),
                                           sector=_info.get("sector"))}
            _rows.append(_row)
            _cls = fuentes.asset_class_for(_sym, country=_row["country"],
                                           sector=_row["sector"], kind=_row["kind"])
            if _cls:
                _by_class.setdefault(_cls, []).append(_sym)
        for _cls, _label in FUENTES.asset_classes.items():
            if _by_class.get(_cls):
                st.markdown(f"**{_label}:** {', '.join(sorted(_by_class[_cls]))}")
        _missing = fuentes.unmapped(_rows)
        if _missing:
            st.warning(f"Sin Clase: {', '.join(_missing)}.", icon="⚠️")
