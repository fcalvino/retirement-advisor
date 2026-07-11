"""
Convicciones personales por ticker — almacenamiento JSON ligero (Fase I).

La "convicción declarada" es subjetiva (la pone el usuario) y vive **separada** de
las posiciones y del análisis objetivo. El motor de sizing (``portfolio.personal_sizer``)
la usa como uno de sus cuatro ejes de decisión.

Formato del archivo (``data/personal_book_convictions.json``)::

    { "GOOGL": "HIGH", "INTU": "MEDIUM" }

Uso::

    from data.personal_book_convictions import get_convictions, set_all, remove_conviction
    convs = get_convictions()              # {"GOOGL": "HIGH", ...}
    set_all({"GOOGL": "HIGH", "INTU": "LOW"})
    remove_conviction("INTU")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from loguru import logger

_CONV_PATH = Path(__file__).parent / "personal_book_convictions.json"

VALID_LEVELS = ("HIGH", "MEDIUM", "LOW")


def _normalize_level(level: str) -> str:
    up = str(level).strip().upper()
    if up not in VALID_LEVELS:
        raise ValueError(f"Nivel de convicción inválido: {level!r}. Usá uno de {VALID_LEVELS}.")
    return up


def get_convictions() -> Dict[str, str]:
    """Lee todas las convicciones declaradas. Tolerante a archivo ausente/corrupto."""
    if not _CONV_PATH.exists():
        return {}
    try:
        raw = json.loads(_CONV_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"convicciones: archivo ilegible ({exc}); se asume vacío.")
        return {}
    if not isinstance(raw, dict):
        logger.warning("convicciones: formato inesperado; se asume vacío.")
        return {}
    out: Dict[str, str] = {}
    for ticker, level in raw.items():
        try:
            out[str(ticker).upper()] = _normalize_level(level)
        except ValueError:
            logger.warning(f"convicciones: nivel inválido para {ticker!r}, ignorado.")
    return out


def _save(convictions: Dict[str, str]) -> None:
    _CONV_PATH.write_text(
        json.dumps(convictions, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    logger.info(f"convicciones: guardadas {len(convictions)} entradas en {_CONV_PATH.name}")


def set_all(convictions: Dict[str, str]) -> Dict[str, str]:
    """
    Reemplaza el conjunto completo de convicciones (útil al guardar el form de la UI).
    Niveles inválidos lanzan ValueError; tickers se normalizan a mayúsculas.
    """
    cleaned = {str(t).upper(): _normalize_level(lvl) for t, lvl in convictions.items()}
    _save(cleaned)
    return cleaned


def remove_conviction(ticker: str) -> Dict[str, str]:
    """Elimina la convicción de un ticker (p. ej. al borrar la posición)."""
    convs = get_convictions()
    convs.pop(str(ticker).upper(), None)
    _save(convs)
    return convs
