#!/usr/bin/env python3
"""Refresca la mediana por sector del Consistency Score (EO-6b-2, ADR 0001).

Puntúa los equities del **universo cacheado** sin red (la misma maquinaria offline de
``measure_score_impact.py``: sólo tickers con ``info`` e historia ya en la caché, la IA
sólo lee caché) y, de cada uno, toma las tres dimensiones del Consistency Score (ROE,
EPS, márgenes; 0–5) que **sí** se pudieron medir. Una dimensión faltante no entra:
``ConsistencyDetail.missing`` la nombra, así que un valor imputado nunca se vuelve a
medianar. Escribe ``CONSISTENCY.sector_medians_file`` con la fecha, el tamaño del universo
y, por sector y dimensión, la mediana y cuántos datos la sostienen.

El universo cacheado es distinto en cada instalación: por eso la mediana es una tabla
versionada y revisable en el PR, y no se calcula al vuelo.

    ./venv/bin/python3 scripts/refresh_sector_medians.py           # muestra la tabla
    ./venv/bin/python3 scripts/refresh_sector_medians.py --write   # y la escribe
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from loguru import logger  # noqa: E402

import analysis.sector_medians as sm  # noqa: E402
from analysis.fuentes import today  # noqa: E402
from config import CONSISTENCY  # noqa: E402


def collect_rows() -> list[dict]:
    """Una fila por equity cacheado: sector y las dimensiones medidas (None = faltante)."""
    import measure_score_impact as m

    m._make_offline()
    from analysis.strategy import full_analysis

    rows: list[dict] = []
    symbols = m.cached_symbols()
    for i, sym in enumerate(symbols, 1):
        try:
            fund, _tech, _dec = full_analysis(sym, ai_config=m.offline_ai_config())
        except Exception as exc:   # un ticker que no puntúa no entra a la mediana
            logger.warning(f"{sym}: no se pudo puntuar — {exc}")
            continue
        detail = fund.consistency_detail
        if fund.asset_class != "equity" or detail is None:
            continue
        row = {"symbol": sym, "sector": fund.sector}
        for dim, score in (("roe", detail.roe_score), ("eps", detail.eps_score),
                           ("margin", detail.margin_score)):
            row[dim] = None if dim in detail.missing else score
        rows.append(row)
        print(f"\r  {i}/{len(symbols)} {sym:<10}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="escribir la tabla")
    args = parser.parse_args()

    table = sm.build_table(collect_rows(), as_of=today().isoformat())
    for sector, dims in table["sectors"].items():
        cells = "  ".join(f"{d}={c['median']:.1f} (n={c['n']})" for d, c in dims.items())
        logger.info(f"{sector:<26} {cells}")
    logger.info("todos los equities: " + "  ".join(
        f"{d}={c['median']:.1f} (n={c['n']})" for d, c in table["all_equity"].items()))
    target = _root / CONSISTENCY.sector_medians_file
    if args.write:
        target.write_text(json.dumps(table, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        sm.load(target)                    # lo escrito tiene que volver a leerse
        logger.info(f"escrito {target.relative_to(_root)}: {table['universe_n']} equities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
