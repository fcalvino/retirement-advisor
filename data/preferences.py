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
    # Each alert: {"symbol", "condition" ("above"|"below"), "target", "created_at", "triggered"}
    price_alerts: List[dict] = field(default_factory=list)

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

    def watch(self, symbol: str) -> bool:
        """Add symbol to watchlist. Returns True if it was newly added."""
        sym = symbol.upper().strip()
        if sym and sym not in self.watched_tickers:
            self.watched_tickers.append(sym)
            self.save()
            return True
        return False

    def unwatch(self, symbol: str) -> None:
        """Remove symbol from watchlist and its price alerts."""
        sym = symbol.upper().strip()
        self.watched_tickers = [t for t in self.watched_tickers if t != sym]
        self.price_alerts = [a for a in self.price_alerts if a.get("symbol") != sym]
        self.save()

    def add_price_alert(self, symbol: str, condition: str, target: float) -> None:
        """Add a price alert. Replaces existing alert for same symbol+condition."""
        import datetime
        sym = symbol.upper().strip()
        self.price_alerts = [
            a for a in self.price_alerts
            if not (a.get("symbol") == sym and a.get("condition") == condition)
        ]
        self.price_alerts.append({
            "symbol":     sym,
            "condition":  condition,
            "target":     target,
            "created_at": datetime.date.today().isoformat(),
            "triggered":  False,
        })
        self.save()

    def remove_price_alert(self, symbol: str, condition: str) -> None:
        """Remove a specific price alert."""
        sym = symbol.upper().strip()
        self.price_alerts = [
            a for a in self.price_alerts
            if not (a.get("symbol") == sym and a.get("condition") == condition)
        ]
        self.save()

    def check_price_alerts(self, prices: dict[str, float]) -> list[dict]:
        """
        Return list of newly-triggered alerts given current prices dict.
        Marks triggered alerts in-place and persists.
        """
        triggered = []
        changed = False
        for alert in self.price_alerts:
            if alert.get("triggered"):
                continue
            sym   = alert.get("symbol", "")
            price = prices.get(sym)
            if price is None:
                continue
            cond   = alert.get("condition")
            target = alert.get("target", 0)
            fired  = (cond == "above" and price >= target) or (cond == "below" and price <= target)
            if fired:
                alert["triggered"] = True
                triggered.append(alert)
                changed = True
        if changed:
            self.save()
        return triggered
