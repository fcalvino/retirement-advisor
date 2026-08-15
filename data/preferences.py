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
# Tracked template used to seed a fresh clone. The real file above is
# gitignored — it contains the user's personal financial profile (audit D6).
_PREFS_EXAMPLE_PATH = Path(__file__).parent / "user_preferences.example.json"

# ------------------------------------------------------------------ #
#  Personal-profile mappings (onboarding wizard — Fase A)              #
# ------------------------------------------------------------------ #

# Risk tolerance (stored, user-facing) → optimizer profile key / display name.
RISK_TOLERANCE_TO_PROFILE_KEY = {
    "conservadora": "conservative",
    "moderada":     "moderate",
    "agresiva":     "aggressive",
}
RISK_TOLERANCE_TO_PROFILE_NAME = {
    "conservadora": "Conservador",
    "moderada":     "Moderado",
    "agresiva":     "Agresivo",
}

# Dividend preference (stored) → human label.
DIVIDEND_PREFERENCE_LABELS = {
    "crecimiento": "Crecimiento (reinvertir, foco en apreciación)",
    "balance":     "Balance (crecimiento + algo de ingreso)",
    "ingreso":     "Ingreso (dividendos / flujo de caja)",
}


@dataclass
class UserPreferences:
    # Optimizer
    default_profile: str = "Conservador"

    # --------------------------------------------------------------- #
    #  Personal profile (onboarding wizard — Fase A)                   #
    #  All default to "unset" so existing pref files stay backward-    #
    #  compatible and the app treats the user as not-yet-onboarded.    #
    # --------------------------------------------------------------- #
    onboarded: bool = False
    age: int = 0                          # 0 = sin definir
    retirement_age: int = 65
    current_capital: float = 0.0          # USD disponibles hoy para invertir
    monthly_savings: float = 0.0          # USD aportados por mes
    risk_tolerance: str = "conservadora"  # conservadora | moderada | agresiva
    primary_goal_type: str = "retiro"     # clave de portfolio.goals.GOAL_TYPE_ICONS
    dividend_preference: str = "balance"  # crecimiento | balance | ingreso

    # Universes
    active_universe: str = "default"        # key matching data/universes/<key>.json
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

    # Mi Plan de Retiro (Fase C) — id of the saved plan the user "activated"
    # as their living retirement target. Drift alerts and the Portfolio
    # alignment view use this plan's allocation as the source of truth.
    # Empty string = no active plan (backward-compatible default).
    active_plan_id: str = ""

    # Custom tickers (Item 3) — user-added symbols beyond the curated universe.
    # Each: {"symbol", "note", "added_at"}. Source is flagged "custom" downstream
    # so scoring/data-quality warnings are loud and the optimizer treats them
    # conservatively. Empty list = pre-feature behavior (backward-compatible).
    custom_tickers: List[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ #

    @classmethod
    def get_default(cls) -> "UserPreferences":
        return cls()

    # ------------------------------------------------------------------ #
    #  Personal-profile derived helpers (read-only)                       #
    # ------------------------------------------------------------------ #

    @property
    def is_onboarded(self) -> bool:
        """True once the user has completed the onboarding wizard."""
        return bool(self.onboarded) and self.age > 0

    @property
    def primary_horizon_years(self) -> int:
        """Years until target retirement (0 if profile incomplete)."""
        if self.age > 0 and self.retirement_age > self.age:
            return int(self.retirement_age - self.age)
        return 0

    @property
    def annual_savings(self) -> float:
        """Yearly savings derived from the monthly figure."""
        return float(self.monthly_savings) * 12.0

    @property
    def profile_key(self) -> str:
        """Optimizer profile key derived from risk tolerance."""
        return RISK_TOLERANCE_TO_PROFILE_KEY.get(self.risk_tolerance, "conservative")

    def apply_personal_profile(
        self,
        *,
        age: int,
        retirement_age: int,
        current_capital: float,
        monthly_savings: float,
        risk_tolerance: str,
        primary_goal_type: str,
        dividend_preference: str,
    ) -> None:
        """Persist the onboarding answers and keep default_profile in sync."""
        self.age                 = int(age)
        self.retirement_age      = int(retirement_age)
        self.current_capital     = float(current_capital)
        self.monthly_savings     = float(monthly_savings)
        self.risk_tolerance      = risk_tolerance
        self.primary_goal_type   = primary_goal_type
        self.dividend_preference = dividend_preference
        # Risk tolerance is the single source of truth for the optimizer profile.
        self.default_profile = RISK_TOLERANCE_TO_PROFILE_NAME.get(
            risk_tolerance, self.default_profile
        )
        self.onboarded = True
        self.save()

    @classmethod
    def _from_raw(cls, data: dict) -> "UserPreferences":
        """Build from a raw dict, dropping unknown keys (old/annotated files)."""
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def load(cls) -> "UserPreferences":
        """Load from disk. Returns defaults on missing or corrupt file.

        The real file is gitignored (audit D6: it holds the user's actual age,
        capital and savings). On a fresh clone it does not exist, so we seed
        from the tracked ``user_preferences.example.json`` template — which is
        deliberately ``onboarded: false`` so the wizard runs. Any failure to
        read the template falls back to the in-code defaults.
        """
        if not _PREFS_PATH.exists():
            if _PREFS_EXAMPLE_PATH.exists():
                try:
                    return cls._from_raw(
                        json.loads(_PREFS_EXAMPLE_PATH.read_text(encoding="utf-8"))
                    )
                except Exception as exc:
                    logger.warning(f"Could not seed prefs from template ({exc}) — using defaults")
            return cls.get_default()
        try:
            data = json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
            # Unknown keys are silently dropped so old files stay compatible
            return cls._from_raw(data)
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

    # ------------------------------------------------------------------ #
    #  Active retirement plan (Fase C)                                     #
    # ------------------------------------------------------------------ #

    def set_active_plan(self, plan_id: str) -> None:
        """Mark a saved plan as the active retirement target and persist."""
        self.active_plan_id = (plan_id or "").strip()
        self.save()

    def clear_active_plan(self) -> None:
        """Unset the active retirement target and persist."""
        self.active_plan_id = ""
        self.save()

    # ------------------------------------------------------------------ #
    #  Custom tickers (Item 3)                                             #
    # ------------------------------------------------------------------ #

    def custom_symbols(self) -> List[str]:
        """Return just the symbols of the user's custom tickers (upper-cased)."""
        out: List[str] = []
        for c in self.custom_tickers:
            sym = str(c.get("symbol", "")).upper().strip()
            if sym and sym not in out:
                out.append(sym)
        return out

    def add_custom_ticker(self, symbol: str, note: str = "") -> bool:
        """Add a custom ticker (dedup, basic validation). Returns True if added.

        Validation is intentionally light (format only) — the point is that the
        user can extend the universe, with loud data-quality warnings elsewhere.
        """
        import datetime
        import re
        sym = (symbol or "").upper().strip()
        if not sym or not re.fullmatch(r"[A-Z0-9.\-]{1,12}", sym):
            return False
        if sym in self.custom_symbols():
            return False
        self.custom_tickers.append({
            "symbol": sym,
            "note": (note or "").strip()[:200],
            "added_at": datetime.date.today().isoformat(),
        })
        self.save()
        return True

    def remove_custom_ticker(self, symbol: str) -> None:
        """Remove a custom ticker by symbol and persist."""
        sym = (symbol or "").upper().strip()
        self.custom_tickers = [
            c for c in self.custom_tickers
            if str(c.get("symbol", "")).upper().strip() != sym
        ]
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
