"""
Persistent alert state — SQLite-backed snapshots, history, and cooldowns.

Three tables (same DB as cache):
  alert_snapshots  — last known score/signal per ticker
  alert_history    — log of every fired alert (capped at MAX_HISTORY)
  alert_cooldowns  — timestamp of last fire per (type, symbol) pair
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

from loguru import logger
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import DB_PATH

MAX_HISTORY = 500  # cap rows in alert_history


class AlertType(str, Enum):
    SIGNAL_CHANGE  = "signal_change"    # BUY→HOLD, HOLD→SELL, etc.
    SCORE_DROP     = "score_drop"       # adjusted_score fell ≥ threshold
    SCORE_SURGE    = "score_surge"      # adjusted_score rose ≥ threshold
    OPPORTUNITY    = "opportunity"      # ticker entered BUY/STRONG_BUY for first time
    MOAT_CHANGE    = "moat_change"      # moat classification changed category


class AlertSeverity(str, Enum):
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


# Cooldown in hours per alert type
_COOLDOWN_HOURS: dict[AlertType, int] = {
    AlertType.SIGNAL_CHANGE: 24,
    AlertType.SCORE_DROP:    168,   # 7 days
    AlertType.SCORE_SURGE:   168,
    AlertType.OPPORTUNITY:   72,    # 3 days
    AlertType.MOAT_CHANGE:   336,   # 14 days
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
    severity    = Column(String, default=AlertSeverity.INFO)
    fired_at    = Column(DateTime, default=datetime.utcnow)


class AlertCooldown(_Base):
    __tablename__ = "alert_cooldowns"
    key          = Column(String, primary_key=True)   # "{type}:{symbol}"
    last_fired   = Column(DateTime, nullable=False)


class AlertStore:
    """Thread-safe SQLite store for alert state."""

    def __init__(self) -> None:
        engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
        _Base.metadata.create_all(engine)
        self._Session = sessionmaker(bind=engine)

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
    ) -> None:
        with self._Session() as s:
            s.add(AlertHistory(
                alert_type=alert_type,
                symbol=symbol,
                message=message,
                severity=severity,
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
            # Detach from session for use outside
            return [
                AlertHistory(
                    id=r.id,
                    alert_type=r.alert_type,
                    symbol=r.symbol,
                    message=r.message,
                    severity=r.severity,
                    fired_at=r.fired_at,
                )
                for r in rows
            ]

    def clear_history(self) -> None:
        with self._Session() as s:
            s.query(AlertHistory).delete()
            s.commit()
        logger.info("Alert history cleared")


# Module-level singleton
alert_store = AlertStore()
