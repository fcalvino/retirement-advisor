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


# Module-level singleton
cache = DataCache()
