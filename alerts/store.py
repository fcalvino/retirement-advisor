"""
Persistent alert state — SQLite-backed snapshots, history, cooldowns and mutes.

Tables (same DB as cache):
  alert_snapshots  — last known score/signal per ticker
  alert_history    — log of every fired alert (capped at MAX_HISTORY)
  alert_cooldowns  — timestamp of last fire per (type, symbol) pair
  alert_mutes      — silenced (ticker, type) combinations with optional TTL
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

from loguru import logger
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DB_PATH

MAX_HISTORY = 500  # cap rows in alert_history


class AlertType(str, Enum):
    SIGNAL_CHANGE       = "signal_change"       # BUY→HOLD, HOLD→SELL, etc.
    SCORE_DROP          = "score_drop"           # adjusted_score fell ≥ threshold
    SCORE_SURGE         = "score_surge"          # adjusted_score rose ≥ threshold
    OPPORTUNITY         = "opportunity"           # ticker entered BUY/STRONG_BUY for first time
    MOAT_CHANGE         = "moat_change"          # moat classification changed category
    # Phase 6 — portfolio & goal alerts
    PORTFOLIO_LOSS      = "portfolio_loss"       # position P&L < -threshold%
    PORTFOLIO_DRIFT     = "portfolio_drift"      # weight deviates from optimizer target
    PORTFOLIO_REBALANCE = "portfolio_rebalance"  # aggregate drift > threshold (rebalance needed)
    SORR_HIGH           = "sorr_high"            # SORR early drawdown probability > threshold
    GOAL_RISK           = "goal_risk"            # probability of meeting a goal dropped significantly
    # Fase H.2 — longitudinal plan health
    PLAN_HEALTH_DEGRADATION = "plan_health_degradation"  # sustained structural drift of the active plan


class AlertSeverity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


# Cooldown in hours per alert type
_COOLDOWN_HOURS: dict[AlertType, int] = {
    AlertType.SIGNAL_CHANGE:       24,
    AlertType.SCORE_DROP:          168,   # 7 days
    AlertType.SCORE_SURGE:         168,
    AlertType.OPPORTUNITY:         72,    # 3 days
    AlertType.MOAT_CHANGE:         336,   # 14 days
    AlertType.PORTFOLIO_LOSS:      72,    # 3 days
    AlertType.PORTFOLIO_DRIFT:     168,   # 7 days
    AlertType.PORTFOLIO_REBALANCE: 168,   # 7 days
    AlertType.SORR_HIGH:           336,   # 14 days
    AlertType.GOAL_RISK:           168,   # 7 days
}


class _Base(DeclarativeBase):
    pass


class AlertSnapshot(_Base):
    __tablename__ = "alert_snapshots"
    symbol          = Column(String, primary_key=True)
    score           = Column(Float, default=0.0)
    signal          = Column(String, default="")
    moat_class      = Column(String, default="")
    updated_at      = Column(DateTime, default=datetime.utcnow)


class AlertHistory(_Base):
    __tablename__ = "alert_history"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    alert_type  = Column(String, nullable=False)
    symbol      = Column(String, nullable=False)
    message     = Column(Text, nullable=False)
    explanation = Column(Text, default="")    # AI-generated explanation (Phase 6)
    severity    = Column(String, default=AlertSeverity.INFO)
    is_read     = Column(Boolean, default=False)
    fired_at    = Column(DateTime, default=datetime.utcnow)


class AlertCooldown(_Base):
    __tablename__ = "alert_cooldowns"
    key          = Column(String, primary_key=True)   # "{type}:{symbol}"
    last_fired   = Column(DateTime, nullable=False)


class AlertMute(_Base):
    """Silenced combinations of (alert_type, symbol). Either field can be '*' for wildcard."""
    __tablename__ = "alert_mutes"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    symbol      = Column(String, nullable=False, default="*")   # "*" = all tickers
    alert_type  = Column(String, nullable=False, default="*")   # "*" = all types
    expires_at  = Column(DateTime, nullable=True)               # None = permanent


class AlertStore:
    """Thread-safe SQLite store for alert state."""

    def __init__(self) -> None:
        engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
        _Base.metadata.create_all(engine)
        self._Session = sessionmaker(bind=engine)
        self._migrate(engine)

    def _migrate(self, engine) -> None:
        """Add new columns to existing tables without dropping data (SQLite safe)."""
        migrations = [
            ("alert_history", "explanation", "TEXT DEFAULT ''"),
            ("alert_history", "is_read",     "BOOLEAN DEFAULT 0"),
        ]
        with engine.connect() as conn:
            from sqlalchemy import text
            for table, column, col_def in migrations:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
                    conn.commit()
                    logger.info(f"Migration: added {table}.{column}")
                except Exception:
                    pass  # column already exists

    # ------------------------------------------------------------------ #
    #  Snapshots                                                           #
    # ------------------------------------------------------------------ #

    def get_snapshot(self, symbol: str) -> Optional[AlertSnapshot]:
        with self._Session() as s:
            return s.get(AlertSnapshot, symbol)

    def save_snapshot(self, symbol: str, score: float, signal: str, moat_class: str) -> None:
        with self._Session() as s:
            snap = s.get(AlertSnapshot, symbol)
            if snap:
                snap.score      = score
                snap.signal     = signal
                snap.moat_class = moat_class
                snap.updated_at = datetime.utcnow()
            else:
                s.add(AlertSnapshot(
                    symbol=symbol, score=score,
                    signal=signal, moat_class=moat_class,
                    updated_at=datetime.utcnow(),
                ))
            s.commit()

    # ------------------------------------------------------------------ #
    #  Cooldowns                                                           #
    # ------------------------------------------------------------------ #

    def is_on_cooldown(self, alert_type: AlertType, symbol: str) -> bool:
        key = f"{alert_type}:{symbol}"
        hours = _COOLDOWN_HOURS.get(alert_type, 24)
        with self._Session() as s:
            cd = s.get(AlertCooldown, key)
            if cd is None:
                return False
            return datetime.utcnow() - cd.last_fired < timedelta(hours=hours)

    def set_cooldown(self, alert_type: AlertType, symbol: str) -> None:
        key = f"{alert_type}:{symbol}"
        with self._Session() as s:
            cd = s.get(AlertCooldown, key)
            if cd:
                cd.last_fired = datetime.utcnow()
            else:
                s.add(AlertCooldown(key=key, last_fired=datetime.utcnow()))
            s.commit()

    # ------------------------------------------------------------------ #
    #  History                                                             #
    # ------------------------------------------------------------------ #

    def record(
        self,
        alert_type: AlertType,
        symbol: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.INFO,
        explanation: str = "",
    ) -> None:
        with self._Session() as s:
            s.add(AlertHistory(
                alert_type=alert_type,
                symbol=symbol,
                message=message,
                explanation=explanation,
                severity=severity,
                is_read=False,
                fired_at=datetime.utcnow(),
            ))
            s.commit()
            # Trim old rows
            count = s.query(AlertHistory).count()
            if count > MAX_HISTORY:
                oldest_ids = (
                    s.query(AlertHistory.id)
                    .order_by(AlertHistory.fired_at)
                    .limit(count - MAX_HISTORY)
                    .all()
                )
                s.query(AlertHistory).filter(
                    AlertHistory.id.in_([r.id for r in oldest_ids])
                ).delete(synchronize_session=False)
                s.commit()

    def get_history(self, limit: int = 100) -> List[AlertHistory]:
        with self._Session() as s:
            rows = (
                s.query(AlertHistory)
                .order_by(AlertHistory.fired_at.desc())
                .limit(limit)
                .all()
            )
            return [
                AlertHistory(
                    id=r.id,
                    alert_type=r.alert_type,
                    symbol=r.symbol,
                    message=r.message,
                    explanation=r.explanation or "",
                    severity=r.severity,
                    is_read=r.is_read,
                    fired_at=r.fired_at,
                )
                for r in rows
            ]

    def get_unread_count(self) -> int:
        with self._Session() as s:
            return s.query(AlertHistory).filter(AlertHistory.is_read == False).count()  # noqa: E712

    def mark_all_read(self) -> None:
        with self._Session() as s:
            s.query(AlertHistory).filter(AlertHistory.is_read == False).update(  # noqa: E712
                {AlertHistory.is_read: True}
            )
            s.commit()

    def clear_history(self) -> None:
        with self._Session() as s:
            s.query(AlertHistory).delete()
            s.commit()
        logger.info("Alert history cleared")

    # ------------------------------------------------------------------ #
    #  Mutes                                                               #
    # ------------------------------------------------------------------ #

    def add_mute(
        self,
        symbol: str = "*",
        alert_type: str = "*",
        days: Optional[int] = None,
    ) -> None:
        """Silence a (symbol, alert_type) combination. Use '*' as wildcard."""
        expires_at = datetime.utcnow() + timedelta(days=days) if days else None
        with self._Session() as s:
            s.add(AlertMute(symbol=symbol, alert_type=alert_type, expires_at=expires_at))
            s.commit()
        logger.info(f"Muted {symbol}/{alert_type} (expires: {expires_at or 'never'})")

    def remove_mute(self, mute_id: int) -> None:
        with self._Session() as s:
            m = s.get(AlertMute, mute_id)
            if m:
                s.delete(m)
                s.commit()

    def get_mutes(self) -> List[AlertMute]:
        now = datetime.utcnow()
        with self._Session() as s:
            rows = (
                s.query(AlertMute)
                .filter((AlertMute.expires_at == None) | (AlertMute.expires_at > now))  # noqa: E711
                .order_by(AlertMute.id)
                .all()
            )
            return [
                AlertMute(
                    id=r.id, symbol=r.symbol,
                    alert_type=r.alert_type, expires_at=r.expires_at,
                )
                for r in rows
            ]

    def is_muted(self, symbol: str, alert_type: str) -> bool:
        """Return True if this (symbol, alert_type) combination is silenced."""
        now = datetime.utcnow()
        with self._Session() as s:
            q = s.query(AlertMute).filter(
                (AlertMute.expires_at == None) | (AlertMute.expires_at > now)  # noqa: E711
            )
            for mute in q.all():
                sym_match  = mute.symbol     in ("*", symbol)
                type_match = mute.alert_type in ("*", alert_type)
                if sym_match and type_match:
                    return True
        return False

    def purge_expired_mutes(self) -> None:
        with self._Session() as s:
            s.query(AlertMute).filter(
                AlertMute.expires_at != None,  # noqa: E711
                AlertMute.expires_at <= datetime.utcnow(),
            ).delete(synchronize_session=False)
            s.commit()


# Module-level singleton
alert_store = AlertStore()
