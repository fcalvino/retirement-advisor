"""Fuentes por Clase de activo: central y Desacuerdo (EO-2a/2b/2c, ADR 0001).

Una Estimación Objetiva sale de Fuentes declaradas —cada una con fecha y
procedencia— agrupadas por Clase de activo. Este módulo sólo describe: arma, por
Clase, la mediana de las Fuentes vigentes (el central) y su rango (el Desacuerdo).
Ningún motor lo consume todavía; eso es EO-4.

Tres tipos de Fuente: ``gestora`` (proyecciones publicadas, a mano), ``valuacion``
(CAPE de Shiller, Tesoro a 10 años) e ``historia`` (la serie más larga de la Clase).
Las dos últimas las arma ``scripts/refresh_fuentes.py`` con las funciones puras de
abajo y las escribe, fechadas, en el archivo curado.

Aparte, el riesgo país de Argentina (EO-2c): un dato fechado en puntos básicos, no
un rendimiento esperado, así que no entra al central de ninguna Clase.
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import median
from typing import List, Optional, Sequence, Tuple

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
    period_start: Optional[date] = None  # Historia: desde cuándo (hasta ``as_of``)


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
    bases = {s.basis for s in summary.used}
    if len(bases) > 1:
        raise ValueError(
            f"Fuentes de distinta base en {asset_class} ({', '.join(sorted(bases))}): "
            "una mediana entre nominal y real no significa nada"
        )
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
            period_start=(date.fromisoformat(e["period_start"])
                          if e.get("period_start") else None),
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


# --------------------------------------------------------------------------- #
#  Valuación e Historia (EO-2b): aritmética pura                               #
# --------------------------------------------------------------------------- #

def years_between(start: date, end: date) -> float:
    """Años entre dos fechas, en días de 365,25."""
    return (end - start).days / 365.25


def annualized_pct(start_value: float, end_value: float, years: float) -> float:
    """Rendimiento anual compuesto, en %."""
    return ((end_value / start_value) ** (1.0 / years) - 1.0) * 100.0


def real_to_nominal_pct(real_pct: float, inflation_pct: float) -> float:
    """Un rendimiento real llevado a nominal con la inflación (Fisher, compuesto)."""
    return ((1 + real_pct / 100.0) * (1 + inflation_pct / 100.0) - 1.0) * 100.0


def cape_expected_return_pct(cape: float, breakeven_pct: float) -> float:
    """Rendimiento esperado nominal desde la valuación: 1/CAPE (real) + inflación implícita.

    El rendimiento de las ganancias ajustadas por ciclo es una estimación del
    rendimiento real a largo plazo; se lleva a nominal con la inflación que descuenta
    el mercado de bonos a 10 años (decisión del usuario, 2026-10-05).
    """
    return real_to_nominal_pct(100.0 / cape, breakeven_pct)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def cut_at_month_end(obs: Sequence[Tuple[date, float]], *, today: date) -> List[Tuple[date, float]]:
    """Las observaciones hasta el último mes completo antes de ``today``."""
    first_of_month = today.replace(day=1)
    return [(d, v) for d, v in obs if d < first_of_month]


@dataclass(frozen=True)
class ShillerRow:
    """Una fila mensual de ie_data.xls: lo que EO-2b usa de ella."""

    year: int
    month: int
    cpi: float
    real_tr_price: float          # «Real Total Return Price»
    cape: Optional[float]         # «P/E10 or CAPE»; None antes de 1881


def shiller_entries(rows: Sequence[ShillerRow], *, breakeven_pct: float,
                    breakeven_as_of: str, file_note: str) -> List[dict]:
    """La valuación (CAPE) y la Historia de acciones de EE.UU. desde las filas de Shiller.

    Saltea las ``FUENTES.shiller_provisional_rows`` últimas: Shiller publica el mes en
    curso con el precio del día 1 y el IPC estimado. La Historia es el rendimiento
    total real del S&P desde la primera fila, llevado a nominal con el IPC del mismo
    período.
    """
    used = list(rows)[: len(rows) - FUENTES.shiller_provisional_rows]
    first, last = used[0], used[-1]
    end = _month_end(last.year, last.month)
    months = (last.year - first.year) * 12 + (last.month - first.month)
    years = months / 12.0
    real = annualized_pct(first.real_tr_price, last.real_tr_price, years)
    cpi = annualized_pct(first.cpi, last.cpi, years)
    common = {"asset_class": "us_equity", "basis": "nominal", "currency": "USD",
              "as_of": end.isoformat(), "source": FUENTES.shiller_page}
    return [
        {
            **common, "name": "CAPE de Shiller", "kind": "valuacion",
            "value_pct": round(cape_expected_return_pct(last.cape, breakeven_pct), 2),
            "edition": f"ie_data.xls, CAPE de {last.year}-{last.month:02d}",
            "note": (f"CAPE {last.cape:.2f} → 1/CAPE = {100 / last.cape:.2f} % real, compuesto "
                     f"con la inflación implícita a 10 años de FRED ({FUENTES.breakeven_series}) "
                     f"{breakeven_pct:.2f} % al {breakeven_as_of}. {file_note}"),
        },
        {
            **common, "name": "S&P de Shiller", "kind": "historia",
            "value_pct": round(real_to_nominal_pct(real, cpi), 2),
            "period_start": date(first.year, first.month, 1).isoformat(),
            "edition": f"ie_data.xls, {first.year}-{first.month:02d} a {last.year}-{last.month:02d}",
            "note": (f"Rendimiento total real {real:.2f} % anual («Real Total Return Price») "
                     f"e IPC {cpi:.2f} % anual en {years:.1f} años. {file_note}"),
        },
    ]


def fund_history_entry(symbol: str, asset_class: str, obs: Sequence[Tuple[date, float]],
                       *, today: date) -> dict:
    """La Historia de una Clase desde el fondo indexado más viejo, hasta el último mes completo.

    ``obs`` son precios ajustados por dividendos (rendimiento total), netos de las
    comisiones del fondo.
    """
    cut = cut_at_month_end(obs, today=today)
    (d0, v0), (d1, v1) = cut[0], cut[-1]
    years = years_between(d0, d1)
    return {
        "name": symbol, "kind": "historia", "asset_class": asset_class,
        "value_pct": round(annualized_pct(v0, v1, years), 2), "basis": "nominal",
        "currency": "USD", "as_of": d1.isoformat(), "period_start": d0.isoformat(),
        "source": f"https://finance.yahoo.com/quote/{symbol}/history",
        "edition": f"precios diarios ajustados de Yahoo Finance, {d0.isoformat()} a {d1.isoformat()}",
        "note": " ".join(filter(None, (
            f"Rendimiento total anual en {years:.1f} años (precio ajustado por "
            "dividendos), neto de las comisiones del fondo.",
            FUENTES.history_notes.get(symbol, ""),
        ))),
    }


def bond_yield_entry(value_pct: float, as_of: str) -> dict:
    """La valuación de bonos: la tasa del Tesoro a 10 años como rendimiento a 10 años."""
    sid = FUENTES.bond_yield_series
    return {
        "name": f"Tesoro a 10 años (FRED {sid})", "kind": "valuacion",
        "asset_class": "us_bonds", "value_pct": round(value_pct, 2), "basis": "nominal",
        "currency": "USD", "as_of": as_of,
        "source": f"https://fred.stlouisfed.org/series/{sid}",
        "edition": f"FRED {sid}, observación del {as_of}",
        "note": ("La tasa inicial de un bono es la mejor estimación de su rendimiento al "
                 "plazo. Es el Tesoro, no el agregado de las gestoras: sin crédito corporativo."),
    }


# --------------------------------------------------------------------------- #
#  Riesgo país (EO-2c): un dato aparte, no un rendimiento esperado             #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CountryRisk:
    """El riesgo país de un emisor: el spread de su deuda soberana en USD, en pb."""

    country: str
    value_bp: int        # puntos básicos sobre el Tesoro de EE.UU.
    as_of: date
    source: str
    edition: str = ""
    note: str = ""


def load_country_risk(path: Path | str) -> List[CountryRisk]:
    """El riesgo país del archivo curado (clave ``country_risk``, aparte de ``entries``)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: List[CountryRisk] = []
    for e in data.get("country_risk", []):
        if e.get("unit") != "pb":
            raise ValueError(f"Riesgo país en {path} sin unidad pb: {e.get('unit')!r}")
        out.append(CountryRisk(
            country=e["country"], value_bp=int(e["value_bp"]),
            as_of=date.fromisoformat(e["as_of"]), source=e["source"],
            edition=e.get("edition", ""), note=e.get("note", ""),
        ))
    return out


def load_shipped_country_risk() -> List[CountryRisk]:
    """El riesgo país del archivo curado del repo (``FUENTES.data_file``)."""
    root = Path(__file__).resolve().parents[1]
    return load_country_risk(root / FUENTES.data_file)


def country_risk_status(cr: CountryRisk, *, today: date) -> str:
    """«vigente», «vieja» o «fuera», con las mismas reglas que una Fuente."""
    age = age_months(cr.as_of, today)
    if age > FUENTES.stale_drop_months:
        return "fuera"
    if age > FUENTES.stale_warn_months:
        return "vieja"
    return "vigente"


def country_risk_entry(obs: Sequence[Tuple[date, float]], *, today: date) -> dict:
    """El riesgo país de Argentina: la última observación hasta ``today``, en pb."""
    d, v = max((o for o in obs if o[0] <= today), key=lambda o: o[0])
    return {
        "country": "Argentina", "value_bp": int(round(v)), "unit": "pb",
        "as_of": d.isoformat(), "source": FUENTES.country_risk_url,
        "edition": f"ArgentinaDatos, observación del {d.isoformat()}",
        "note": ("EMBI de J.P. Morgan para Argentina (spread de la deuda soberana en USD "
                 "sobre el Tesoro de EE.UU.) que publica Ámbito "
                 f"({FUENTES.country_risk_upstream}); ArgentinaDatos lo extrae de Ámbito a "
                 "diario (API comunitaria, no oficial; Ámbito bloquea el acceso directo). "
                 "No es un rendimiento esperado: no entra al central de emergentes."),
    }


# --------------------------------------------------------------------------- #
#  Inflación implícita (EO-4a): el 0 % real de cripto, en nominal              #
# --------------------------------------------------------------------------- #

def load_inflation(path: Path | str) -> dict:
    """La inflación implícita del archivo curado (clave ``inflation``): serie, %, fecha, cita."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    infl = data.get("inflation")
    if not infl:
        raise ValueError(f"{path} no trae la inflación implícita (clave inflation)")
    return {**infl, "value_pct": float(infl["value_pct"])}


def load_shipped_inflation() -> dict:
    """La inflación implícita del archivo curado del repo (``FUENTES.data_file``)."""
    root = Path(__file__).resolve().parents[1]
    return load_inflation(root / FUENTES.data_file)


def inflation_entry(value_pct: float, as_of: str) -> dict:
    """La inflación implícita a 10 años de FRED, como la escribe ``refresh_fuentes.py``."""
    sid = FUENTES.breakeven_series
    return {"series": sid, "value_pct": round(value_pct, 2), "as_of": as_of,
            "source": f"https://fred.stlouisfed.org/series/{sid}",
            "note": ("Inflación que descuenta el mercado de bonos a 10 años. Lleva a "
                     "nominal el 0 % real de cripto (EO-4a) y el 1/CAPE (EO-2b).")}
