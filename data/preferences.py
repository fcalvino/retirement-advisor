"""
User preferences — persistent JSON storage.

Preferences survive browser refreshes and Streamlit restarts.
All mutations go through save() so the file is always consistent.

Usage:
    from data.preferences import UserPreferences
    prefs = UserPreferences.load()
    prefs.default_profile = "Moderado"
    prefs.save()
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List

from loguru import logger

_PREFS_PATH = Path(__file__).parent / "user_preferences.json"


@dataclass
class UserPreferences:
    # Optimizer
    default_profile: str = "Moderado"

    # Universes
    favorite_universe: List[str] = field(default_factory=list)
    last_used_universe: List[str] = field(default_factory=list)

    # Watchlist
    watched_tickers: List[str] = field(default_factory=list)

    # Display
    preferred_currency: str = "USD"  # "USD" | "ARS"

    # AI
    ai_enabled_in_screener: bool = False

    # ------------------------------------------------------------------ #

    @classmethod
    def get_default(cls) -> "UserPreferences":
        return cls()

    @classmethod
    def load(cls) -> "UserPreferences":
        """Load from disk. Returns defaults on missing or corrupt file."""
        if not _PREFS_PATH.exists():
            return cls.get_default()
        try:
            data = json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
            # Unknown keys are silently dropped so old files stay compatible
            known = {f for f in cls.__dataclass_fields__}
            filtered = {k: v for k, v in data.items() if k in known}
            return cls(**filtered)
        except Exception as exc:
            logger.warning(f"Could not load preferences ({exc}) — using defaults")
            return cls.get_default()

    def save(self) -> None:
        """Persist current state to disk atomically."""
        try:
            _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _PREFS_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(_PREFS_PATH)
        except Exception as exc:
            logger.error(f"Could not save preferences: {exc}")

    def update_universe(self, tickers: List[str]) -> None:
        """Helper: update last_used_universe and persist."""
        self.last_used_universe = list(tickers)
        self.save()
