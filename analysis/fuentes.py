"""Fuentes por Clase de activo: central y Desacuerdo (EO-2a, ADR 0001).

Una Estimación Objetiva sale de Fuentes declaradas —cada una con fecha y
procedencia— agrupadas por Clase de activo. Este módulo sólo describe: arma, por
Clase, la mediana de las Fuentes vigentes (el central) y su rango (el Desacuerdo).
Ningún motor lo consume todavía; eso es EO-4.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import median
from typing import List, Optional

from config import FUENTES


@dataclass(frozen=True)
class Fuente:
    """Un número citado: lo que una Fuente dice que rinde una Clase de activo."""

    name: str            # «JPMorgan LTCMA 2026», «CAPE de Shiller»…
    kind: str            # gestora | valuacion | historia
    asset_class: str     # clave de FUENTES.asset_classes
    value_pct: float     # rendimiento anual esperado, en %
    basis: str           # nominal | real
    currency: str        # USD, …
    as_of: date          # fecha de la edición / del dato
    source: str          # URL o cita exacta
    edition: str = ""    # edición o documento
    range_pct: Optional[tuple] = None   # rango publicado por la Fuente, si da uno
    note: str = ""       # dónde está el número (página, tabla) y sus salvedades


@dataclass
class ClassSummary:
    """Central y Desacuerdo de una Clase, con las Fuentes que los explican."""

    asset_class: str
    central_pct: Optional[float] = None
    low_pct: Optional[float] = None
    high_pct: Optional[float] = None
    used: List[Fuente] = field(default_factory=list)       # entran al central
    stale: List[Fuente] = field(default_factory=list)      # > stale_warn_months
    excluded: List[Fuente] = field(default_factory=list)   # > stale_drop_months
    all_sources: List[Fuente] = field(default_factory=list)
    declared_absent: bool = False   # Clase sin Fuente externa: sin central (glosario)


def age_months(as_of: date, today: date) -> int:
    """Meses cumplidos entre la fecha de una Fuente y hoy."""
    months = (today.year - as_of.year) * 12 + (today.month - as_of.month)
    return months - 1 if today.day < as_of.day else months


def summarize_class(asset_class: str, sources: List[Fuente], *, today: date) -> ClassSummary:
    """Mediana y rango de las Fuentes vigentes de una Clase.

    Una Fuente de más de ``stale_warn_months`` se marca vieja y sigue contando; una
    de más de ``stale_drop_months`` sale del central y del rango, pero queda en
    ``all_sources`` y en ``excluded`` para que la vista la muestre marcada.
    """
    summary = ClassSummary(asset_class=asset_class, all_sources=list(sources))
    if asset_class in FUENTES.declared_absent:
        summary.declared_absent = True
        return summary
    for s in sources:
        age = age_months(s.as_of, today)
        if age > FUENTES.stale_drop_months:
            summary.excluded.append(s)
            continue
        if age > FUENTES.stale_warn_months:
            summary.stale.append(s)
        summary.used.append(s)
    values = [s.value_pct for s in summary.used]
    if values:
        summary.central_pct = float(median(values))
        summary.low_pct = min(values)
        summary.high_pct = max(values)
    return summary


# --------------------------------------------------------------------------- #
#  Ticker → Clase                                                              #
# --------------------------------------------------------------------------- #

def asset_class_for(
    symbol: str, *, country: Optional[str], sector: Optional[str], kind: Optional[str],
) -> Optional[str]:
    """La Clase de activo de un ticker, o None si no se puede decir.

    ``kind`` es la clase de ``AssetClassConfig`` (equity / fund / crypto). Los fondos
    se asignan a mano (``FUENTES.etf_classes``); las acciones, por país —con el
    sector «Real Estate» de EE.UU. como REITs—. Un ticker sin Clase no cae en una
    por defecto: se nombra (``unmapped``).
    """
    if kind == "crypto":
        return "crypto"
    if kind == "fund":
        return FUENTES.etf_classes.get(symbol)
    if symbol in FUENTES.ticker_classes:
        return FUENTES.ticker_classes[symbol]
    if country == "United States":
        return "reits" if sector == "Real Estate" else "us_equity"
    if country in FUENTES.developed_countries:
        return "developed_ex_us"
    if country in FUENTES.emerging_countries:
        return "emerging"
    return None


def unmapped(rows: List[dict]) -> List[str]:
    """Los símbolos que no tienen Clase, para nombrarlos en la vista."""
    return [
        r["symbol"] for r in rows
        if asset_class_for(r["symbol"], country=r.get("country"), sector=r.get("sector"),
                           kind=r.get("kind")) is None
    ]


# --------------------------------------------------------------------------- #
#  El archivo curado                                                           #
# --------------------------------------------------------------------------- #

def load_sources(path: Path | str) -> List[Fuente]:
    """Las Fuentes del archivo curado. Una Clase desconocida es un error, no un salto."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: List[Fuente] = []
    for e in data.get("entries", []):
        if e["asset_class"] not in FUENTES.asset_classes:
            raise ValueError(f"Clase desconocida en {path}: {e['asset_class']}")
        rng = e.get("range_pct")
        out.append(Fuente(
            name=e["name"], kind=e["kind"], asset_class=e["asset_class"],
            value_pct=float(e["value_pct"]), basis=e["basis"], currency=e["currency"],
            as_of=date.fromisoformat(e["as_of"]), source=e["source"],
            edition=e.get("edition", ""), range_pct=tuple(rng) if rng else None,
            note=e.get("note", ""),
        ))
    return out


def load_shipped() -> List[Fuente]:
    """Las Fuentes del archivo curado del repo (``FUENTES.data_file``)."""
    root = Path(__file__).resolve().parents[1]
    return load_sources(root / FUENTES.data_file)


def today() -> date:
    """La fecha contra la que se mide la antigüedad (un punto para fijarla en tests)."""
    return date.today()


def summarize_all(sources: List[Fuente], *, today: date) -> dict:
    """Un resumen por cada una de las Clases, en el orden de ``FUENTES.asset_classes``.

    Una Clase sin Fuentes cargadas tiene central None pero no es «declarada ausente»:
    eso queda para las de ``FUENTES.declared_absent``.
    """
    return {
        cls: summarize_class(cls, [s for s in sources if s.asset_class == cls], today=today)
        for cls in FUENTES.asset_classes
    }
