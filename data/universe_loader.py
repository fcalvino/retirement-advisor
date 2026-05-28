"""
Universe loader — reads named JSON universes from data/universes/.

Usage:
    from data.universe_loader import list_universes, load_universe, UNIVERSE_META
    tickers = load_universe("dividend_focus")
    meta    = UNIVERSE_META["dividend_focus"]   # {"name": ..., "description": ..., "count": ...}
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from loguru import logger

_UNIVERSES_DIR = Path(__file__).parent / "universes"

# Canonical order for UI display
_DISPLAY_ORDER = ["default", "growth_moat", "dividend_focus", "us_quality", "latam_adrs"]


def _universe_path(key: str) -> Path:
    return _UNIVERSES_DIR / f"{key}.json"


def _is_valid_ticker(t: object) -> bool:
    if not isinstance(t, str):
        return False
    cleaned = t.strip().upper()
    if not cleaned or len(cleaned) > 7:
        return False
    # Allow letters, digits, hyphens and dots (e.g. BRK-B, BF.B)
    return all(c.isalnum() or c in "-." for c in cleaned)


@lru_cache(maxsize=16)
def _load_raw(key: str) -> dict:
    path = _universe_path(key)
    if not path.exists():
        raise FileNotFoundError(f"Universe '{key}' not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_universes() -> List[str]:
    """Return known universe keys in display order (plus any extras found on disk)."""
    on_disk = {p.stem for p in _UNIVERSES_DIR.glob("*.json")}
    ordered = [k for k in _DISPLAY_ORDER if k in on_disk]
    extras  = sorted(on_disk - set(_DISPLAY_ORDER))
    return ordered + extras


def load_universe(key: str) -> List[str]:
    """
    Load and return a validated ticker list for the given universe key.

    Validation: silently skips entries that are not 1-6 uppercase alphanumeric
    characters (with optional hyphen), and warns if >20% are filtered.
    """
    try:
        raw = _load_raw(key)
    except FileNotFoundError:
        logger.warning(f"Universe '{key}' not found — falling back to 'default'")
        raw = _load_raw("default")

    tickers_raw: List[str] = raw.get("tickers", [])
    valid   = [t for t in tickers_raw if _is_valid_ticker(t)]
    dropped = len(tickers_raw) - len(valid)

    if dropped:
        pct = dropped / max(len(tickers_raw), 1) * 100
        msg = f"Universe '{key}': dropped {dropped} invalid ticker(s) ({pct:.0f}%)"
        if pct > 20:
            logger.warning(msg)
        else:
            logger.debug(msg)

    return valid


def get_universe_meta(key: str) -> Dict[str, str | int]:
    """Return display metadata for a universe key."""
    try:
        raw = _load_raw(key)
    except FileNotFoundError:
        return {"name": key, "description": "", "count": 0}
    return {
        "name":        raw.get("name", key),
        "description": raw.get("description", ""),
        "count":       len(load_universe(key)),
    }


# Pre-built metadata dict for all known universes (populated once on import)
UNIVERSE_META: Dict[str, Dict] = {k: get_universe_meta(k) for k in list_universes()}
