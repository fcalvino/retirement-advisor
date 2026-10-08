"""La mediana por sector que reemplaza al 0 de los datos faltantes (EO-6b-2, ADR 0001).

El Consistency Score (ROE, EPS y márgenes, 5 pts cada uno) puntuaba un dato faltante con
``CONSISTENCY.missing_data_score`` = 0 (auditoría D6: no regalar puntos). Con la
Estimación objetiva ya no se castiga con un número sin base: un equity sin historia
suficiente recibe la mediana de esa dimensión entre los equities de su sector que sí
tienen el dato, tomada del **universo cacheado** y sin red (decisión del usuario,
2026-10-08). Un sector con menos de ``CONSISTENCY.sector_median_min_tickers`` datos usa la
mediana de todos los equities.

La mediana es una tabla derivada y versionada (``CONSISTENCY.sector_medians_file``), que
escribe ``scripts/refresh_sector_medians.py``: el universo cacheado es distinto en cada
instalación, y calcularla al vuelo daría scores distintos según lo que cada usuario
tenga cacheado. Los fondos y el cripto no se imputan: puntúan en otra escala.

Puro salvo ``load_shipped`` (lee el archivo, una vez).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from loguru import logger

from config import CONSISTENCY

DIMENSIONS = ("roe", "eps", "margin")
ALL_EQUITY = "todos los equities"


@dataclass(frozen=True)
class Imputation:
    """Qué se imputó, de dónde y con cuántos datos."""

    value: float
    source: str          # el sector, o ``ALL_EQUITY``
    n: int


@dataclass(frozen=True)
class SectorMedians:
    as_of: str
    universe_n: int
    sectors: Mapping[str, Mapping[str, Mapping[str, float]]]   # sector → dim → {median, n}
    all_equity: Mapping[str, Mapping[str, float]]               # dim → {median, n}

    def lookup(self, dim: str, sector: Optional[str], *, min_tickers: int) -> Optional[Imputation]:
        """La mediana del sector si tiene ``min_tickers`` datos; si no, la de todos los equities."""
        if dim not in DIMENSIONS:
            raise ValueError(f"Dimensión desconocida: {dim!r}")
        own = (self.sectors.get(sector or "") or {}).get(dim)
        if own and own["n"] >= min_tickers:
            return Imputation(float(own["median"]), str(sector), int(own["n"]))
        pooled = self.all_equity.get(dim)
        if pooled and pooled["n"] >= min_tickers:
            return Imputation(float(pooled["median"]), ALL_EQUITY, int(pooled["n"]))
        return None


def build_table(rows: Iterable[Mapping], *, as_of: str) -> dict:
    """La tabla a partir de una fila por equity: ``{sector, roe, eps, margin}``.

    Un valor ``None`` es un dato faltante y no entra a la mediana (ni el imputado de una
    corrida anterior: quien arma las filas pasa sólo lo medido).
    """
    rows = list(rows)
    by_sector: Dict[str, Dict[str, List[float]]] = {}
    pooled: Dict[str, List[float]] = {d: [] for d in DIMENSIONS}
    for r in rows:
        sector = str(r.get("sector") or "").strip()
        for d in DIMENSIONS:
            v = r.get(d)
            if v is None:
                continue
            pooled[d].append(float(v))
            if sector:
                by_sector.setdefault(sector, {x: [] for x in DIMENSIONS})[d].append(float(v))

    def cell(vals: List[float]) -> Optional[dict]:
        return {"median": float(statistics.median(vals)), "n": len(vals)} if vals else None

    sectors = {
        s: {d: c for d, vals in dims.items() if (c := cell(vals)) is not None}
        for s, dims in sorted(by_sector.items())
    }
    return {
        "as_of": as_of,
        "universe_n": len(rows),
        "sectors": sectors,
        "all_equity": {d: c for d, vals in pooled.items() if (c := cell(vals)) is not None},
    }


def load(path: Path | str) -> SectorMedians:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return SectorMedians(
        as_of=str(data["as_of"]), universe_n=int(data["universe_n"]),
        sectors=data["sectors"], all_equity=data["all_equity"],
    )


@lru_cache(maxsize=1)
def load_shipped() -> Optional[SectorMedians]:
    """La tabla del repo, o None si no está (el scorer vuelve al ``missing_data_score``)."""
    path = Path(__file__).resolve().parents[1] / CONSISTENCY.sector_medians_file
    try:
        return load(path)
    except (OSError, ValueError, KeyError) as exc:
        logger.warning(f"sector_medians: sin tabla en {path} — {exc}")
        return None
