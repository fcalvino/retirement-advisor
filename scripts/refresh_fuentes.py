#!/usr/bin/env python3
"""Refresca la valuación, la Historia y el riesgo país del archivo curado (EO-2b/2c, ADR 0001).

Reemplaza en ``FUENTES.data_file`` las entradas de tipo ``valuacion`` e ``historia``;
las de las gestoras no se tocan (se cargan a mano). Lo que baja:

- **Shiller** (``FUENTES.shiller_page``): ie_data.xls, a ``FUENTES.raw_dir`` (ignorado
  por git: el archivo no trae licencia y el repo es público). Del archivo salen dos
  números: el CAPE como rendimiento esperado y la Historia del S&P desde 1871. Cada
  uno cita la fecha de descarga y el sha256 del archivo.
- **FRED** (necesita ``FRED_API_KEY``): la inflación implícita a 10 años, para el CAPE,
  y la tasa del Tesoro a 10 años, como valuación de los bonos.
- **Yahoo Finance**: la Historia del resto de las Clases (``FUENTES.history_proxies``),
  por ``data.fetcher.get_history``: queda en la caché de la base, como cualquier precio.
- **ArgentinaDatos** (``FUENTES.country_risk_url``, sin clave): el riesgo país de
  Argentina, la última observación. Va en ``country_risk``, aparte de ``entries``: es
  un spread en pb, no un rendimiento esperado (EO-2c).

Correr una vez por año, junto con la tabla de gestoras:
    ./venv/bin/python3 scripts/refresh_fuentes.py           # muestra las entradas
    ./venv/bin/python3 scripts/refresh_fuentes.py --write   # y las escribe
    ./venv/bin/python3 scripts/refresh_fuentes.py --country-risk-only --write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from loguru import logger  # noqa: E402

import analysis.fuentes as fuentes  # noqa: E402
from config import FUENTES  # noqa: E402

# Columnas de la hoja «Data» de ie_data.xls y el rótulo que tiene que tener cada una
# (filas 5–8 del encabezado, unidas). Si Shiller mueve una columna, el script frena.
_SHILLER_COLS = {"date": (0, "Date"), "cpi": (4, "CPI"),
                 "real_tr_price": (9, "Real Total Return Price"), "cape": (12, "CAPE")}
_SHILLER_FIRST_ROW = 8


def _download_shiller(raw_dir: Path) -> tuple[Path, str]:
    import requests

    page = requests.get(FUENTES.shiller_page, timeout=30)
    page.raise_for_status()
    match = re.search(r'href="([^"]*ie_data\.xls[^"]*)"', page.text)
    if not match:
        raise SystemExit(f"No encontré el enlace a ie_data.xls en {FUENTES.shiller_page}")
    url = match.group(1)
    url = f"https:{url}" if url.startswith("//") else url
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"ie_data_{fuentes.today().isoformat()}.xls"
    path.write_bytes(resp.content)
    return path, hashlib.sha256(resp.content).hexdigest()


def _read_shiller(path: Path) -> list[fuentes.ShillerRow]:
    try:
        import xlrd
    except ImportError:
        raise SystemExit("Falta xlrd: ./venv/bin/pip install -r requirements-dev.txt")
    sheet = xlrd.open_workbook(str(path)).sheet_by_name("Data")
    for key, (col, label) in _SHILLER_COLS.items():
        header = " ".join(str(sheet.cell_value(r, col)).strip() for r in range(4, 8))
        if label not in " ".join(header.split()):
            raise SystemExit(f"ie_data.xls cambió: la columna {col} ya no es «{label}» ({header!r})")
    rows = []
    for r in range(_SHILLER_FIRST_ROW, sheet.nrows):
        stamp = sheet.cell_value(r, 0)
        if not isinstance(stamp, float):
            continue
        year = int(stamp)
        cape = sheet.cell_value(r, _SHILLER_COLS["cape"][0])
        rows.append(fuentes.ShillerRow(
            year=year, month=round((stamp - year) * 100),
            cpi=float(sheet.cell_value(r, _SHILLER_COLS["cpi"][0])),
            real_tr_price=float(sheet.cell_value(r, _SHILLER_COLS["real_tr_price"][0])),
            cape=float(cape) if isinstance(cape, float) else None,
        ))
    return rows


def _fred(series_id: str):
    from data.data_sources import FredSource

    sv = FredSource().latest_series_value(series_id)
    if sv is None:
        raise SystemExit(f"FRED no devolvió {series_id} (¿falta FRED_API_KEY o la red?)")
    return sv


def _fund_history(symbol: str, asset_class: str) -> dict:
    from data.fetcher import get_history

    df = get_history(symbol, period="max", interval="1d")
    obs = [(ts.date(), float(v)) for ts, v in df["close"].dropna().items()]
    return fuentes.fund_history_entry(symbol, asset_class, obs, today=fuentes.today())


def _country_risk() -> dict:
    import requests

    resp = requests.get(FUENTES.country_risk_url, timeout=30)
    resp.raise_for_status()
    obs = [(date.fromisoformat(o["fecha"]), float(o["valor"])) for o in resp.json()]
    if not obs:
        raise SystemExit(f"{FUENTES.country_risk_url} no devolvió observaciones")
    return fuentes.country_risk_entry(obs, today=fuentes.today())


def build_entries() -> list[dict]:
    path, sha = _download_shiller(_root / FUENTES.raw_dir)
    breakeven = _fred(FUENTES.breakeven_series)
    bond = _fred(FUENTES.bond_yield_series)
    file_note = (f"ie_data.xls de {FUENTES.shiller_page}, descargado el "
                 f"{fuentes.today().isoformat()} (sha256 {sha}); se versiona sólo este "
                 "número derivado: el archivo no trae licencia.")
    entries = fuentes.shiller_entries(_read_shiller(path), breakeven_pct=breakeven.value,
                                      breakeven_as_of=breakeven.as_of, file_note=file_note)
    entries.append(fuentes.bond_yield_entry(bond.value, bond.as_of))
    for cls, symbol in FUENTES.history_proxies.items():
        if symbol != "shiller":
            entries.append(_fund_history(symbol, cls))
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="escribir el archivo curado")
    parser.add_argument("--country-risk-only", action="store_true",
                        help="refrescar sólo el riesgo país (no toca valuación ni Historia)")
    args = parser.parse_args()

    target = _root / FUENTES.data_file
    data = json.loads(target.read_text(encoding="utf-8"))
    if not args.country_risk_only:
        derived = build_entries()
        for e in derived:
            span = f"{e['period_start']} → " if e.get("period_start") else ""
            logger.info(f"{e['asset_class']:<16} {e['kind']:<9} {e['value_pct']:>6.2f} %  "
                        f"{span}{e['as_of']}  {e['name']}")
        gestoras = [e for e in data["entries"] if e["kind"] == "gestora"]
        data["entries"] = gestoras + derived
    risk = _country_risk()
    logger.info(f"riesgo país {risk['country']}: {risk['value_bp']} pb al {risk['as_of']}")
    data["country_risk"] = [risk]
    if args.write:
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        fuentes.load_sources(target)        # lo escrito tiene que volver a leerse
        fuentes.load_country_risk(target)
        logger.info(f"escrito {target.relative_to(_root)}: {len(data['entries'])} entradas "
                    "y el riesgo país")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
