"""Un ticker local leído como su ADR (``config.LISTING_ALIASES``).

``SHEL.L`` y ``SHEL`` son el mismo emisor con otro precio. Los universos listan el ADR;
lo que el usuario ya tiene guardado (un plan, un ticker tipeado) puede decir el local.
Este módulo resuelve la equivalencia **al leer**: no reescribe ningún archivo, y un
ticker sin alias vuelve tal cual.

Los pesos (%) son adimensionales, así que se pueden sumar bajo el ADR sin convertir
nada. Lo que depende del precio (``price_at_save``, una cantidad de acciones) **no** pasa
por acá: cambia de moneda y de razón acciones/ADR (``config.LISTING_ALIASES``).
"""

from __future__ import annotations

from typing import Dict, Mapping

from config import LISTING_ALIASES


def resolve_listing(symbol: str) -> str:
    """El ADR de ``symbol`` si hay alias; ``symbol`` sin cambios si no."""
    alias = LISTING_ALIASES.aliases.get(str(symbol).strip().upper())
    return alias[0] if alias else symbol


def resolve_weights(weights: Mapping[str, float]) -> Dict[str, float]:
    """``{símbolo: peso}`` con cada símbolo llevado a su ADR; los repetidos se suman."""
    out: Dict[str, float] = {}
    for symbol, weight in weights.items():
        key = resolve_listing(symbol)
        out[key] = out.get(key, 0.0) + float(weight or 0.0)
    return out
