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
from typing import Dict, List, NamedTuple

from loguru import logger

from config import UNIVERSE

_UNIVERSES_DIR = Path(__file__).parent / "universes"

# Canonical order for UI display
_DISPLAY_ORDER = [
    "default", "growth_moat", "dividend_focus", "us_quality", "latam_adrs", "global_quality",
]


class TickerMeta(NamedTuple):
    """Curated country/industry of one universe entry. Empty = not curated."""

    country: str = ""
    industry: str = ""


def _universe_path(key: str) -> Path:
    return _UNIVERSES_DIR / f"{key}.json"


def _is_valid_ticker(t: object) -> bool:
    if not isinstance(t, str):
        return False
    cleaned = t.strip().upper()
    if not cleaned or len(cleaned) > UNIVERSE.max_ticker_len:
        return False
    # Allow letters, digits, hyphens and dots (e.g. BRK-B, BF.B)
    return all(c.isalnum() or c in "-." for c in cleaned)


@lru_cache(maxsize=16)
def _load_raw(key: str) -> dict:
    path = _universe_path(key)
    if not path.exists():
        raise FileNotFoundError(f"Universe '{key}' not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def optimizer_universes() -> List[str]:
    """``list_universes()`` minus the Screener-only ones (``UNIVERSE.screener_only``).

    The Optimizer combines and compares universes over raw price series with no
    FX conversion, so a multi-currency universe must not join those lists by
    merely existing on disk.
    """
    excluded = set(UNIVERSE.screener_only)
    return [k for k in list_universes() if k not in excluded]


def _entry_symbol(entry: object) -> object:
    """A universe entry is a bare symbol or ``{"ticker", "country", "industry"}``."""
    if isinstance(entry, dict):
        return entry.get("ticker")
    return entry


def list_universes() -> List[str]:
    """Return known universe keys in display order (plus any extras found on disk)."""
    on_disk = {p.stem for p in _UNIVERSES_DIR.glob("*.json")}
    ordered = [k for k in _DISPLAY_ORDER if k in on_disk]
    extras  = sorted(on_disk - set(_DISPLAY_ORDER))
    return ordered + extras


def load_universe(key: str) -> List[str]:
    """
    Load and return a validated ticker list for the given universe key.

    Validation: silently skips entries longer than ``UNIVERSE.max_ticker_len`` or
    with characters other than letters, digits, dot and hyphen; warns if >20%
    are filtered. Entries may be bare symbols or ``{"ticker", ...}`` dicts.
    """
    try:
        raw = _load_raw(key)
    except FileNotFoundError:
        logger.warning(f"Universe '{key}' not found — falling back to 'default'")
        raw = _load_raw("default")

    tickers_raw: List[object] = [_entry_symbol(e) for e in raw.get("tickers", [])]
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


def load_universe_metadata(key: str) -> Dict[str, TickerMeta]:
    """Curated ``{symbol: TickerMeta}`` for a universe; empty for bare-symbol files.

    The legacy universes list symbols only, so they return ``{}`` and every
    consumer falls back to what the feed reports — their behaviour is unchanged.
    """
    try:
        raw = _load_raw(key)
    except FileNotFoundError:
        return {}
    out: Dict[str, TickerMeta] = {}
    for entry in raw.get("tickers", []):
        if not isinstance(entry, dict) or not _is_valid_ticker(entry.get("ticker")):
            continue
        out[str(entry["ticker"]).upper().strip()] = TickerMeta(
            country=str(entry.get("country") or ""),
            industry=str(entry.get("industry") or ""),
        )
    return out


def apply_universe_metadata(
    rows: List[dict],
    meta: Dict[str, TickerMeta],
    *,
    unknown_country: str | None = None,
) -> List[dict]:
    """Copies of Screener rows with ``País`` filled and a missing sector repaired.

    Country: the curated value wins, then what the feed reported, then
    ``UNIVERSE.unknown_country`` — never an empty cell, so the country filter
    has an option for every row (rows stored by an older page have no ``País``).

    Sector: the feed stays authoritative (it is what the scorer used). The
    curated industry only fills a feed that returned nothing, so a ticker whose
    ``info`` came back empty still lands in a sector bucket instead of "Unknown".
    With ``meta == {}`` (legacy universes) only the country default applies.
    """
    unknown = UNIVERSE.unknown_country if unknown_country is None else unknown_country
    out: List[dict] = []
    for row in rows:
        new = dict(row)
        m = meta.get(str(new.get("Ticker", "")).upper().strip(), TickerMeta())
        new["País"] = m.country or str(new.get("País") or "") or unknown
        if m.industry and str(new.get("Sector") or "") in ("", "Unknown"):
            new["Sector"] = m.industry
        out.append(new)
    return out


def get_effective_universe(
    key: str,
    custom_symbols: List[str] | None = None,
) -> tuple[List[str], List[str]]:
    """Return ``(tickers, custom_used)`` = base universe + valid custom tickers.

    Item 3: merges the curated universe for ``key`` with the user's custom
    tickers (deduped, format-validated via ``_is_valid_ticker``). Customs are
    appended AFTER the curated names so existing ordering is preserved, and the
    second return value lists exactly which customs ended up included (so the UI
    can badge them "Custom" and warn about data quality). Passing no customs is
    byte-identical to ``load_universe(key)``.
    """
    base = load_universe(key)
    base_set = {t.upper() for t in base}
    custom_used: List[str] = []
    for sym in (custom_symbols or []):
        s = str(sym).upper().strip()
        if not _is_valid_ticker(s):
            logger.debug(f"Custom ticker '{sym}' skipped (invalid format).")
            continue
        if s in base_set or s in custom_used:
            continue
        custom_used.append(s)
    return base + custom_used, custom_used


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


def _build_universe_meta() -> Dict[str, Dict]:
    """Build metadata for all universes found on disk, refreshing the lru_cache for new files."""
    keys = list_universes()
    meta = {}
    for k in keys:
        if not _universe_path(k).exists():
            continue
        # Clear cache entry for any key not yet seen so _load_raw picks up new files
        try:
            meta[k] = get_universe_meta(k)
        except Exception:
            meta[k] = {"name": k, "description": "", "count": 0}
    return meta


# Pre-built metadata dict for all known universes (populated once on import)
UNIVERSE_META: Dict[str, Dict] = _build_universe_meta()
