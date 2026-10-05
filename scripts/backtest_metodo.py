#!/usr/bin/env python3
"""Corre el backtest point-in-time del método de Estimación (EO-3, ADR 0001).

Lee ie_data.xls de Shiller (no versionado: no trae licencia y el repo es público),
corre ``analysis.backtest_metodo`` para acciones y bonos de EE.UU. y escribe en
``BACKTEST_METODO.report_file`` sólo números derivados: por Clase, la cobertura del
p10–p90 en ventanas sin superposición (la que decide) y superpuestas (informada),
cada ventana sin superposición con su central, banda y resultado, y el sha256 del
archivo de origen.

    ./venv/bin/python3 scripts/backtest_metodo.py --xls RUTA            # muestra
    ./venv/bin/python3 scripts/backtest_metodo.py --xls RUTA --write    # y escribe

Sin ``--xls`` usa el ie_data más nuevo de ``FUENTES.raw_dir`` (lo deja ahí
``scripts/refresh_fuentes.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from loguru import logger  # noqa: E402

from analysis.backtest_metodo import MonthlyRow, run_backtest  # noqa: E402
from config import BACKTEST_METODO, FUENTES  # noqa: E402
from scripts.refresh_fuentes import open_shiller  # noqa: E402

# Lo que usa el backtest de la hoja «Data», con el rótulo que tiene que tener.
_COLS = {"date": (0, "Date"), "cpi": (4, "CPI"), "gs10": (6, "GS10"),
         "real_tr_price": (9, "Real Total Return Price"), "cape": (12, "CAPE"),
         "real_bond_index": (18, "Real Total Bond Returns")}
_FIRST_ROW = 8


def _num(v):
    return float(v) if isinstance(v, float) else None


def read_monthly(path: Path) -> list[MonthlyRow]:
    """Las filas mensuales, sin las ``FUENTES.shiller_provisional_rows`` últimas."""
    sheet = open_shiller(path, _COLS)
    rows = []
    for r in range(_FIRST_ROW, sheet.nrows):
        stamp = sheet.cell_value(r, 0)
        if not isinstance(stamp, float):
            continue
        year = int(stamp)
        rows.append(MonthlyRow(
            year=year, month=round((stamp - year) * 100),
            cpi=float(sheet.cell_value(r, _COLS["cpi"][0])),
            real_tr_price=float(sheet.cell_value(r, _COLS["real_tr_price"][0])),
            cape=_num(sheet.cell_value(r, _COLS["cape"][0])),
            gs10=_num(sheet.cell_value(r, _COLS["gs10"][0])),
            real_bond_index=_num(sheet.cell_value(r, _COLS["real_bond_index"][0])),
        ))
    return rows[: len(rows) - FUENTES.shiller_provisional_rows]


def _r(x: float) -> float:
    return round(x, 2)


def _coverage(c) -> dict:
    return {"n": c.n, "k": c.k, "rate": round(c.rate, 4), "low": round(c.low, 4),
            "high": round(c.high, 4), "passes": c.passes}


def build_report(path: Path) -> dict:
    rows = read_monthly(path)
    classes = {}
    for asset in ("us_equity", "us_bonds"):
        res = run_backtest(rows, asset)
        nov = res.non_overlapping
        classes[asset] = {
            "verdict": "pasa" if nov.passes else "no pasa",
            "non_overlapping": {**_coverage(nov), "windows": [
                {"date": w.date, "central": _r(w.central), "p10": _r(w.p10), "p90": _r(w.p90),
                 "realized": _r(w.realized), "hit": w.hit}
                for w in res.non_overlapping_windows
            ]},
            "overlapping": {**_coverage(res.overlapping),
                            "first": res.windows[0].date, "last": res.windows[-1].date},
            "mean_bias_pp": _r(res.mean_bias_pp),
            "mean_width_pp": _r(res.mean_width_pp),
        }
        logger.info(f"{asset}: sin superposición {nov.k}/{nov.n} = {nov.rate:.1%} "
                    f"[{nov.low:.1%}, {nov.high:.1%}] → {classes[asset]['verdict']}; "
                    f"superpuestas {res.overlapping.k}/{res.overlapping.n} = "
                    f"{res.overlapping.rate:.1%}; sesgo {res.mean_bias_pp:+.2f} pp, "
                    f"ancho {res.mean_width_pp:.2f} pp")
    cfg = BACKTEST_METODO
    return {
        "_doc": ("EO-3 (ADR 0001): ¿el p10–p90 de la Estimación central contiene el "
                 "rendimiento real a 10 años el 80 % de las veces? Todo en % real anual. "
                 "Lo escribe scripts/backtest_metodo.py; sólo números derivados de ie_data.xls."),
        "source": {"file": "ie_data.xls", "page": FUENTES.shiller_page,
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "last_month": f"{rows[-1].year}-{rows[-1].month:02d}",
                   "generated": date.today().isoformat()},
        "method": {
            "central": ("mediana de las Fuentes conocidas en t. Acciones: 1/CAPE y la "
                        "Historia real del S&P desde 1871. Bonos: GS10 menos la inflación de "
                        f"los {cfg.inflation_proxy_months} meses previos (Fisher; supuesto del "
                        "backtest) y la Historia real de los bonos desde 1871"),
            "azar": (f"bootstrap por bloques de {cfg.block_months} mes de los "
                     f"{cfg.azar_window_months} meses previos, recentrado compuesto en el "
                     f"central (la mediana de los caminos rinde el central); {cfg.n_sims} "
                     f"caminos por fecha; semilla {cfg.seed}"),
            "horizon_months": cfg.horizon_months,
            "rule": (f"pasa si {cfg.coverage_target:.0%} cae dentro del intervalo de "
                     f"Clopper-Pearson al {cfg.confidence:.0%} de la cobertura en ventanas "
                     "sin superposición"),
        },
        "classes": classes,
        "not_calibrable": dict(cfg.not_calibrable),
    }


def _default_xls() -> Path:
    found = sorted((_root / FUENTES.raw_dir).glob("ie_data_*.xls"))
    if not found:
        raise SystemExit(f"No hay ie_data en {FUENTES.raw_dir}: pasá --xls o corré "
                         "scripts/refresh_fuentes.py")
    return found[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--xls", type=Path, help="ie_data.xls de Shiller")
    parser.add_argument("--write", action="store_true", help="escribir el informe")
    args = parser.parse_args()
    report = build_report(args.xls or _default_xls())
    if args.write:
        target = _root / BACKTEST_METODO.report_file
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info(f"escrito {target.relative_to(_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
