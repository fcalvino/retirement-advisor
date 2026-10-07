"""La Estimación que usa el Monte Carlo para cada activo (EO-4a, ADR 0001).

Cada activo se proyecta con la Estimación objetiva de su Clase —el central de las
Fuentes vigentes (``analysis.fuentes``)—, salvo donde el usuario decidió otra cosa
(2026-10-05, sobre el resultado de EO-3; ``config.ESTIMACION``):

- acciones EE.UU.: la Estimación, «calibrada» (EO-3 pasó);
- bonos EE.UU.: conservan el haircut sobre su propia historia, «no calibrado»;
- ex-EE.UU., emergentes y REITs: la Estimación, «no calibrable»;
- cripto (Fuente declarada ausente): 0 % real, el Escenario pesimista, que en
  nominal es la inflación implícita;
- un ticker sin Clase, o una Clase sin Fuentes vigentes: haircut, y se lo nombra;
- un emisor con riesgo país (EO-4d; hoy Argentina): su Estimación es la de la Clase
  menos el riesgo país en pp, sin bajar del 0 % real (la inflación implícita). Es un
  dato citado, igual en los tres Escenarios; con el dato «fuera» (más de 24 meses) o
  ausente no se resta y se avisa. Con haircut no se resta: su historia ya trae el
  riesgo realizado.

Puro salvo ``classes_for``, que pide la ficha de cada ticker (``get_info``,
cacheada): la usa quien construye el simulador; el Monte Carlo nunca sale a la red.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from loguru import logger

from analysis.fuentes import (
    CountryRisk,
    asset_class_for,
    country_risk_status,
    load_shipped,
    load_shipped_country_risk,
    load_shipped_inflation,
    summarize_all,
)
from analysis.fuentes import today as fuentes_today
from config import ARS_RISK, ESTIMACION, FUENTES

OBJETIVA = "objetiva"
HAIRCUT = "haircut"


@dataclass(frozen=True)
class AssetEstimation:
    """Con qué proyecta el Monte Carlo un activo, y cómo se lo dice al usuario."""

    symbol: str
    asset_class: Optional[str]
    mode: str                       # objetiva | haircut
    annual_pct: Optional[float]     # la Estimación nominal anual; None con haircut
    label: str
    #: pp que el riesgo país le restó a la Estimación de la Clase (EO-4d); 0 si no.
    country_adj_pp: float = 0.0
    #: El aviso del riesgo país de este activo, vacío si no le toca.
    country_note: str = ""


def class_ranges() -> Dict[str, tuple]:
    """(más baja, más alta) de las Fuentes vigentes de cada Clase; (None, None) sin ellas."""
    summaries = summarize_all(load_shipped(), today=fuentes_today())
    return {cls: ((None, None) if s.declared_absent else (s.low_pct, s.high_pct))
            for cls, s in summaries.items()}


def class_estimates(scenario: str = ESTIMACION.default_scenario) -> Dict[str, Optional[float]]:
    """La Estimación de cada Clase en un Escenario (EO-4c): Desacuerdo, no Azar.

    pesimista / optimista ponen cada Clase en su Fuente vigente más baja / más alta;
    central es la mediana (``class_centrals``).
    """
    if scenario not in ESTIMACION.scenarios:
        raise ValueError(f"Escenario desconocido: {scenario!r}")
    if scenario == "central":
        return class_centrals()
    idx = 0 if scenario == "pesimista" else 1
    return {cls: rng[idx] for cls, rng in class_ranges().items()}


def class_centrals() -> Dict[str, Optional[float]]:
    """El central de cada Clase hoy; None si no tiene (cripto, o sin Fuentes vigentes)."""
    summaries = summarize_all(load_shipped(), today=fuentes_today())
    return {cls: (None if s.declared_absent else s.central_pct) for cls, s in summaries.items()}


def inflation_pct() -> float:
    """La inflación implícita del archivo de Fuentes: el 0 % real de cripto, en nominal."""
    return load_shipped_inflation()["value_pct"]


def _class_label(cls: str) -> str:
    return FUENTES.asset_classes.get(cls, cls)


def _country_adjustment(country: Optional[str], risks: Mapping[str, CountryRisk],
                        today: date) -> Tuple[Optional[CountryRisk], str]:
    """(el riesgo país que se resta, el aviso). None si no toca o no hay dato vigente."""
    if not country or country not in tuple(ARS_RISK.exposed_countries):
        return None, ""
    cr = risks.get(country)
    if cr is None:
        return None, (f"riesgo país de {country}: sin dato cargado; la Estimación no lo "
                      "descuenta")
    status = country_risk_status(cr, today=today)
    if status == "fuera":
        return None, (f"riesgo país de {country}: el dato del {cr.as_of.isoformat()} tiene "
                      f"más de {FUENTES.stale_drop_months} meses; la Estimación no lo descuenta")
    return cr, ("dato viejo (más de "
                f"{FUENTES.stale_warn_months} meses)" if status == "vieja" else "")


def estimate_asset(symbol: str, asset_class: Optional[str], *,
                   centrals: Mapping[str, Optional[float]], inflation: float,
                   scenario: str = ESTIMACION.default_scenario,
                   country: Optional[str] = None,
                   country_risks: Optional[Mapping[str, CountryRisk]] = None,
                   today: Optional[date] = None) -> AssetEstimation:
    """La regla de un activo; ver el docstring del módulo.

    ``centrals`` es la Estimación de cada Clase en ``scenario`` (``class_estimates``);
    fuera del central el rótulo nombra el Escenario. Haircut y cripto no cambian.
    ``country`` y ``country_risks`` (país → ``CountryRisk``) activan el descuento por
    riesgo país (EO-4d); sin ellos, la Estimación es la de la Clase.
    """
    if asset_class is None:
        return AssetEstimation(symbol, None, HAIRCUT, None,
                               f"{symbol}: sin Clase · ajuste histórico (−20 % / +10 %)")
    name = _class_label(asset_class)
    if asset_class in FUENTES.declared_absent:
        return AssetEstimation(symbol, asset_class, OBJETIVA, inflation,
                               f"{name} {inflation:.1f}% · 0 % real, el Escenario pesimista "
                               "(Fuente declarada ausente)")
    if asset_class in ESTIMACION.haircut_classes:
        return AssetEstimation(symbol, asset_class, HAIRCUT, None,
                               f"{name}: ajuste histórico (−20 % / +10 %) · no calibrado: "
                               "el backtest EO-3 no pasó")
    central = centrals.get(asset_class)
    if central is None:
        return AssetEstimation(symbol, asset_class, HAIRCUT, None,
                               f"{name}: sin Fuentes vigentes · ajuste histórico (−20 % / +10 %)")
    status = "calibrada" if asset_class in ESTIMACION.calibrated_classes else "no calibrable"
    tag = "" if scenario == "central" else f" ({scenario})"
    label = f"{name} {central:.1f}%{tag} · {status}"
    cr, aviso = _country_adjustment(country, country_risks or {}, today or fuentes_today())
    if cr is None:
        return AssetEstimation(symbol, asset_class, OBJETIVA, central, label, 0.0, aviso)
    annual = max(central - cr.value_bp / 100.0, inflation)
    adj = central - annual
    binds = central - cr.value_bp / 100.0 < inflation
    resta = (f"−{adj:.2f} pp (el spread, {cr.value_bp / 100.0:.2f} pp, lo llevaría bajo el piso "
             "de 0 % real)" if binds else f"−{adj:.2f} pp")
    nota = (f"riesgo país de {cr.country} {cr.value_bp} pb al {cr.as_of.isoformat()}: "
            f"{resta}, {annual:.2f}%")
    if aviso:
        nota += f"; {aviso}"
    return AssetEstimation(symbol, asset_class, OBJETIVA, annual,
                           f"{label} · {nota}", adj, nota)


def country_risks() -> Dict[str, CountryRisk]:
    """El riesgo país del archivo curado por país (EO-2c); vacío si no hay."""
    return {c.country: c for c in load_shipped_country_risk()}


def asset_estimations(symbols: Iterable[str],
                      asset_classes: Mapping[str, Optional[str]],
                      scenario: str = ESTIMACION.default_scenario,
                      countries: Optional[Mapping[str, Optional[str]]] = None,
                      ) -> List[AssetEstimation]:
    """La Estimación de cada símbolo en un Escenario, con las Fuentes y la inflación de hoy.

    ``countries`` (símbolo → país del emisor) activa el riesgo país (EO-4d); lo
    resuelve quien construye el simulador, como las Clases (``countries_for``).
    """
    estimates, inflation = class_estimates(scenario), inflation_pct()
    countries = countries or {}
    risks = country_risks() if countries else {}
    out = []
    for s in symbols:
        e = estimate_asset(s, asset_classes.get(s), centrals=estimates, inflation=inflation,
                           scenario=scenario, country=countries.get(s),
                           country_risks=risks)
        if e.mode == HAIRCUT and countries.get(s) in tuple(ARS_RISK.exposed_countries):
            e = replace(e, country_note=("sin Estimación objetiva: el riesgo país no se resta "
                                         "(su historia ya trae el riesgo realizado)"))
        out.append(e)
    return out


def country_warnings(ests: Iterable[AssetEstimation]) -> List[str]:
    """Una línea por aviso de riesgo país (activos juntos si es el mismo): lo que se restó, o por qué no."""
    by_note: Dict[str, List[str]] = {}
    for e in ests:
        if e.country_note:
            by_note.setdefault(e.country_note, []).append(e.symbol)
    return [f"{', '.join(syms)}: {note}" for note, syms in by_note.items()]


def classify(symbol: str, info: Mapping) -> Optional[str]:
    """La Clase de un ticker desde su ficha, con la lógica de la vista «Supuestos»."""
    from analysis.asset_class import classify_asset

    kind = classify_asset(symbol, quote_type=info.get("quoteType"), sector=info.get("sector"))
    return asset_class_for(symbol, country=info.get("country"), sector=info.get("sector"),
                           kind=kind)


def countries_for(symbols: Iterable[str]) -> Dict[str, Optional[str]]:
    """El país del emisor de cada símbolo (``get_info``); None si la ficha no se puede leer."""
    from data.fetcher import get_info

    out: Dict[str, Optional[str]] = {}
    for sym in symbols:
        try:
            out[sym] = (get_info(sym) or {}).get("country")
        except Exception as exc:   # sin ficha no hay país: sin ajuste por riesgo país
            logger.warning(f"estimacion: sin país para {sym} — {exc}")
            out[sym] = None
    return out


def classes_for(symbols: Iterable[str]) -> Dict[str, Optional[str]]:
    """La Clase de cada símbolo; si su ficha no se puede leer, queda sin Clase."""
    from data.fetcher import get_info

    out: Dict[str, Optional[str]] = {}
    for sym in symbols:
        try:
            out[sym] = classify(sym, get_info(sym) or {})
        except Exception as exc:   # sin ficha no hay Clase: haircut, y se lo nombra
            logger.warning(f"estimacion: sin Clase para {sym} — {exc}")
            out[sym] = None
    return out
