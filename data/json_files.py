"""Helpers for the JSON files the app owns (preferences, plan health, convictions…).

One rule, written once (AUDIT-AIIO-1/2/3): a file that cannot be read is **set aside**, never left for the
next save to overwrite. Reading it as «empty» is fine for showing the screen, but every store rewrites its
whole file from that reading, so a truncated JSON (power cut, full disk) used to be wiped by the next
click. ``PlanStore`` has its own copy of this for the saved plans.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from data.clock import utc_now


def set_aside_unreadable(path: Path, reason: str, is_valid: Callable[[Any], bool]) -> str:
    """Move an unreadable JSON file to ``<name>.corrupt-<stamp><suffix>``, bytes untouched.

    ``is_valid`` says whether a parsed value has the shape the store expects (an object, a list…).
    Returns what the caller should do next:

    * ``"moved"``  — the file was unreadable and now sits aside; the path is free for a clean one.
    * ``"valid"``  — it reads fine now (another session saved a good file between the caller's failed
      read and this one): nothing was touched, read it again.
    * ``"gone"``   — missing or empty: there is nothing to keep.
    * ``"failed"`` — it could not be read or moved; it stays where it is (logged), so the caller must
      not assume the path is free.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return "gone"
    except OSError as exc:
        logger.error(f"{path.name} unreadable ({reason}) and re-read failed: {exc}")
        return "failed"
    try:
        if is_valid(json.loads(raw.decode("utf-8"))):
            return "valid"
    except Exception:       # ValueError, UnicodeDecodeError, and RecursionError on a pathological nesting
        pass
    if not raw.strip():
        return "gone"
    stamp = utc_now().strftime("%Y%m%dT%H%M%S%f")
    aside = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    n = 1
    while aside.exists():   # ``Path.replace`` overwrites: never on top of an earlier copy
        n += 1
        aside = path.with_name(f"{path.stem}.corrupt-{stamp}-{n}{path.suffix}")
    try:
        path.replace(aside)
    except OSError as exc:
        logger.error(f"{path.name} unreadable ({reason}) and could not be moved aside: {exc}")
        return "failed"
    logger.error(f"{path.name} unreadable ({reason}) — moved to {aside.name}; starting clean")
    return "moved"
