"""La Estimación que usa el Monte Carlo para cada activo (EO-4a, ADR 0001).

Cada activo se proyecta con la Estimación objetiva de su Clase —el central de las
Fuentes vigentes (``analysis.fuentes``)—, salvo donde el usuario decidió otra cosa
(2026-10-05, sobre el resultado de EO-3; ``config.ESTIMACION``):

- acciones EE.UU.: la Estimación, «calibrada» (EO-3 pasó);
- bonos EE.UU.: conservan el haircut sobre su propia historia, «no calibrado»;
- ex-EE.UU., emergentes y REITs: la Estimación, «no calibrable»;
- cripto (Fuente declarada ausente): 0 % real, el Escenario pesimista, que en
  nominal es la inflación implícita;
- un ticker sin Clase, o una Clase sin Fuentes vigentes: haircut, y se lo nombra.

Puro salvo ``classes_for``, que pide la ficha de cada ticker (``get_info``,
cacheada): la usa quien construye el simulador; el Monte Carlo nunca sale a la red.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional

from loguru import logger

from analysis.fuentes import (
    asset_class_for,
    load_shipped,
    load_shipped_inflation,
    summarize_all,
)
from analysis.fuentes import today as fuentes_today
from config import ESTIMACION, FUENTES

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


def class_centrals() -> Dict[str, Optional[float]]:
    """El central de cada Clase hoy; None si no tiene (cripto, o sin Fuentes vigentes)."""
    summaries = summarize_all(load_shipped(), today=fuentes_today())
    return {cls: (None if s.declared_absent else s.central_pct) for cls, s in summaries.items()}


def inflation_pct() -> float:
    """La inflación implícita del archivo de Fuentes: el 0 % real de cripto, en nominal."""
    return load_shipped_inflation()["value_pct"]


def _class_label(cls: str) -> str:
    return FUENTES.asset_classes.get(cls, cls)


def estimate_asset(symbol: str, asset_class: Optional[str], *,
                   centrals: Mapping[str, Optional[float]], inflation: float) -> AssetEstimation:
    """La regla de un activo; ver el docstring del módulo."""
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
    return AssetEstimation(symbol, asset_class, OBJETIVA, central, f"{name} {central:.1f}% · {status}")


def asset_estimations(symbols: Iterable[str],
                      asset_classes: Mapping[str, Optional[str]]) -> List[AssetEstimation]:
    """La Estimación de cada símbolo, con el central y la inflación de hoy."""
    centrals, inflation = class_centrals(), inflation_pct()
    return [estimate_asset(s, asset_classes.get(s), centrals=centrals, inflation=inflation)
            for s in symbols]


def classify(symbol: str, info: Mapping) -> Optional[str]:
    """La Clase de un ticker desde su ficha, con la lógica de la vista «Supuestos»."""
    from analysis.asset_class import classify_asset

    kind = classify_asset(symbol, quote_type=info.get("quoteType"), sector=info.get("sector"))
    return asset_class_for(symbol, country=info.get("country"), sector=info.get("sector"),
                           kind=kind)


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
