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
from typing import Dict, Optional

from loguru import logger

_CONV_PATH = Path(__file__).parent / "personal_book_convictions.json"

VALID_LEVELS = ("HIGH", "MEDIUM", "LOW")


def _normalize_level(level: str) -> str:
    up = str(level).strip().upper()
    if up not in VALID_LEVELS:
        raise ValueError(f"Nivel de convicción inválido: {level!r}. Usá uno de {VALID_LEVELS}.")
    return up


class ConvictionsUnavailable(OSError):
    """The convictions file is unreadable and could not be set aside: nothing was written (AUDIT-AIIO-3)."""


def _is_object(data) -> bool:
    return isinstance(data, dict)


def _read_items() -> Optional[dict]:
    """The raw stored object, or ``None`` when the file is unreadable AND could not be set aside.

    An unreadable file (truncated JSON, not an object, not UTF-8) is moved to
    ``personal_book_convictions.corrupt-<fecha>.json`` with its bytes intact and read as empty
    (AUDIT-AIIO-3): reading it as ``{}`` and leaving it in place meant the next save —
    ``remove_conviction`` ran on every deleted position — replaced every declared conviction with ``{}``.
    ``None`` means the file is still there and still unreadable: the writers must not go over it.
    """
    from data.json_files import set_aside_unreadable

    for _ in range(2):          # twice: another session may fix the file between our two reads
        if not _CONV_PATH.exists():
            return {}
        try:
            raw = json.loads(_CONV_PATH.read_text(encoding="utf-8"))
            if _is_object(raw):
                return raw
            reason = f"se esperaba un objeto y hay {type(raw).__name__}"
        except Exception as exc:
            reason = str(exc)
        state = set_aside_unreadable(_CONV_PATH, reason, _is_object)
        if state == "valid":
            continue
        if state in ("moved", "gone"):
            return {}
        logger.error(f"convicciones: archivo ilegible ({reason}); se deja donde está")
        return None
    return None


def get_convictions() -> Dict[str, str]:
    """Lee todas las convicciones declaradas. Un archivo ilegible se aparta y se lee como vacío."""
    raw = _read_items()
    return {} if raw is None else _normalized(raw)


def _normalized(raw: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for ticker, level in raw.items():
        try:
            out[str(ticker).upper()] = _normalize_level(level)
        except ValueError:
            logger.warning(f"convicciones: nivel inválido para {ticker!r}, ignorado.")
    return out


def _save(convictions: Dict[str, str]) -> None:
    """Atomic: a temporary file and a swap, so a cut mid-write cannot leave the file truncated."""
    tmp = _CONV_PATH.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(convictions, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(_CONV_PATH)
    except OSError:
        tmp.unlink(missing_ok=True)      # a stray temporary would hold the convictions outside the ignored name
        raise
    logger.info(f"convicciones: guardadas {len(convictions)} entradas en {_CONV_PATH.name}")


def set_all(convictions: Dict[str, str]) -> Dict[str, str]:
    """
    Reemplaza el conjunto completo de convicciones (útil al guardar el form de la UI).
    Niveles inválidos lanzan ValueError; tickers se normalizan a mayúsculas.
    Lanza ``ConvictionsUnavailable`` si el archivo está ilegible y no se pudo apartar.
    """
    cleaned = {str(t).upper(): _normalize_level(lvl) for t, lvl in convictions.items()}
    if _read_items() is None:      # sets an unreadable file aside before the swap replaces it
        raise ConvictionsUnavailable("el archivo de convicciones está ilegible y no se pudo apartar")
    _save(cleaned)
    return cleaned


def remove_conviction(ticker: str) -> Dict[str, str]:
    """Elimina la convicción de un ticker (p. ej. al borrar la posición).

    No escribe nada si el ticker no tenía convicción (AUDIT-AIIO-3: se reescribía el archivo entero con lo
    que se había leído, aunque no hubiera nada que borrar).
    """
    raw = _read_items()
    if raw is None:
        raise ConvictionsUnavailable("el archivo de convicciones está ilegible y no se pudo apartar")
    convs = _normalized(raw)
    if str(ticker).upper() in convs:
        convs.pop(str(ticker).upper())
        _save(convs)
    return convs
