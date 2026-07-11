"""
Universe data snapshots (Item 3 — data resilience).

A *snapshot* is a portable, JSON-serializable capture of the key data for a set
of tickers (last price + a few fundamental fields + timestamp). It partially
mitigates the single, fragile dependency on yfinance: a user can export a
snapshot of the current universe for backup/offline use, or share a reproducible
bundle with another machine.

Design mirrors ``data.plan_context``: **Streamlit-free** and **network-free** —
the price/info lookups are injected as callables, so this module never imports
yfinance and stays trivially unit-testable offline.

Usage:
    from data.snapshot import export_universe_data_snapshot
    snap = export_universe_data_snapshot(
        ["AAPL", "MSFT"], info_lookup=get_info, price_lookup=plan_price_lookup,
    )
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger

SCHEMA = "retirement_advisor.universe_snapshot"
SCHEMA_VERSION = "1.0"

# Key fundamental fields worth capturing (kept small + auditable).
_INFO_KEYS = (
    "shortName", "sector", "industry", "country", "currency",
    "currentPrice", "regularMarketPrice", "marketCap",
    "trailingPE", "dividendYield", "returnOnEquity",
)


def export_universe_data_snapshot(
    tickers: List[str],
    *,
    info_lookup: Optional[Callable[[str], dict]] = None,
    price_lookup: Optional[Callable[[str], Optional[float]]] = None,
) -> dict:
    """Build a snapshot dict for ``tickers`` using injected lookups.

    Both lookups are optional and wrapped defensively: a failure for one ticker
    simply records an empty/partial entry rather than aborting the whole export.
    Returns a versioned dict ready to ``json.dump``.
    """
    captured: Dict[str, dict] = {}
    for raw in tickers:
        sym = str(raw).upper().strip()
        if not sym:
            continue
        entry: Dict[str, object] = {}
        if info_lookup is not None:
            try:
                info = info_lookup(sym) or {}
                entry["info"] = {k: info.get(k) for k in _INFO_KEYS if info.get(k) is not None}
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"snapshot: info lookup failed for {sym}: {exc}")
                entry["info"] = {}
        if price_lookup is not None:
            try:
                p = price_lookup(sym)
                entry["price"] = round(float(p), 4) if p and float(p) > 0 else None
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"snapshot: price lookup failed for {sym}: {exc}")
                entry["price"] = None
        captured[sym] = entry

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "n_tickers": len(captured),
        "tickers": captured,
    }


def snapshot_to_bytes(snapshot: dict) -> bytes:
    """Serialize a snapshot dict to pretty UTF-8 JSON bytes (for download)."""
    return json.dumps(snapshot, indent=2, ensure_ascii=False).encode("utf-8")


def load_snapshot(data: dict) -> dict:
    """Validate + normalize a snapshot dict loaded from disk/upload.

    Raises ``ValueError`` if the payload is not a recognizable snapshot.
    """
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("Archivo de snapshot inválido o de un esquema desconocido.")
    if not isinstance(data.get("tickers"), dict):
        raise ValueError("El snapshot no contiene un mapa de tickers válido.")
    return data


def save_snapshot_to_path(snapshot: dict, path: Path) -> None:
    """Write a snapshot to disk atomically (mirrors plan_store/preferences)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
