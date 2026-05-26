"""SQLite cache layer for API responses. Avoids hammering yfinance."""

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger
from sqlalchemy import Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import CACHE_TTL_HOURS, DB_PATH


class Base(DeclarativeBase):
    pass


class CacheEntry(Base):
    __tablename__ = "cache"

    key = Column(String, primary_key=True)
    data = Column(Text, nullable=False)
    cached_at = Column(DateTime, default=datetime.utcnow)


class DataCache:
    """JSON-based cache backed by SQLite. Thread-safe for read-heavy workloads."""

    def __init__(self, ttl_hours: int = CACHE_TTL_HOURS):
        self.ttl = timedelta(hours=ttl_hours)
        engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
        Base.metadata.create_all(engine)
        self._Session = sessionmaker(bind=engine)

    def get(self, key: str) -> Optional[Any]:
        with self._Session() as session:
            entry: Optional[CacheEntry] = session.get(CacheEntry, key)
            if entry is None:
                return None
            if datetime.utcnow() - entry.cached_at > self.ttl:
                session.delete(entry)
                session.commit()
                return None
            try:
                return json.loads(entry.data)
            except json.JSONDecodeError:
                return None

    def set(self, key: str, value: Any) -> None:
        try:
            serialized = json.dumps(value, default=str)
        except (TypeError, ValueError) as exc:
            logger.warning(f"Cache: cannot serialize {key}: {exc}")
            return
        with self._Session() as session:
            existing = session.get(CacheEntry, key)
            if existing:
                existing.data = serialized
                existing.cached_at = datetime.utcnow()
            else:
                session.add(CacheEntry(key=key, data=serialized, cached_at=datetime.utcnow()))
            session.commit()

    def invalidate(self, key: str) -> None:
        with self._Session() as session:
            entry = session.get(CacheEntry, key)
            if entry:
                session.delete(entry)
                session.commit()

    def clear_all(self) -> None:
        with self._Session() as session:
            session.query(CacheEntry).delete()
            session.commit()
        logger.info("Cache cleared.")

    def get_stats(self) -> dict:
        """Return live cache statistics for display in Settings."""
        now = datetime.utcnow()
        try:
            with self._Session() as session:
                total   = session.query(CacheEntry).count()
                valid   = session.query(CacheEntry).filter(
                    CacheEntry.cached_at > now - self.ttl
                ).count()
                oldest_row = (
                    session.query(CacheEntry)
                    .order_by(CacheEntry.cached_at.asc())
                    .first()
                )
                newest_row = (
                    session.query(CacheEntry)
                    .order_by(CacheEntry.cached_at.desc())
                    .first()
                )
        except Exception:
            total = valid = 0
            oldest_row = newest_row = None

        db_size_mb = DB_PATH.stat().st_size / 1_048_576 if DB_PATH.exists() else 0.0

        return {
            "total":      total,
            "valid":      valid,
            "expired":    total - valid,
            "oldest":     oldest_row.cached_at if oldest_row else None,
            "newest":     newest_row.cached_at if newest_row else None,
            "db_size_mb": round(db_size_mb, 2),
            "ttl_hours":  int(self.ttl.total_seconds() / 3600),
        }


# Module-level singleton
cache = DataCache()
