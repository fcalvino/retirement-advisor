"""
Track record — persistent log of every recommendation the engine emits.

Gran Salto, Fase 1. Mirrors the persistence pattern of ``alerts/store.py``
(SQLAlchemy DeclarativeBase + SQLite at the shared ``DB_PATH``). This module is
the *capture* half; deferred outcome scoring lives in
``analysis/track_record_scorer.py``.

Tables (same DB as cache/alerts):
  recommendation_log      — one row per recommendation emitted to the user
  recommendation_outcome  — deferred scoring of each (rec, horizon) pair

Design notes (project conventions):
  - Config-driven: horizons, benchmark and dedupe behaviour come from
    ``config.TRACK_RECORD`` — never hardcoded here.
  - Synchronous, no async. Logging via loguru.
  - Tests use a real in-memory SQLite, not mocks (see tests/test_track_record.py).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from loguru import logger
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DB_PATH, TRACK_RECORD


class _Base(DeclarativeBase):
    pass


class RecommendationLog(_Base):
    """One row per recommendation emitted to the user."""

    __tablename__ = "recommendation_log"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    symbol            = Column(String, nullable=False, index=True)
    action            = Column(String, nullable=False)   # STRONG BUY | BUY | HOLD | REDUCE | SELL | AVOID
    confidence        = Column(String, default="MEDIUM")  # HIGH | MEDIUM | LOW
    fundamental_score = Column(Float, default=0.0)
    technical_signal  = Column(String, default="")
    source            = Column(String, default="rule_based")  # rule_based | ai | committee
    price_at_rec      = Column(Float, nullable=True)
    rationale         = Column(Text, default="")          # JSON-encoded list[str]
    plan_id           = Column(String, nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow, index=True)


class RecommendationOutcome(_Base):
    """Deferred scoring of a recommendation at a fixed horizon."""

    __tablename__ = "recommendation_outcome"
    __table_args__ = (UniqueConstraint("rec_id", "horizon_days", name="uq_rec_horizon"),)

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    rec_id                = Column(Integer, nullable=False, index=True)
    horizon_days          = Column(Integer, nullable=False)
    price_at_horizon      = Column(Float, nullable=True)
    return_pct            = Column(Float, nullable=True)
    benchmark_return_pct  = Column(Float, nullable=True)
    excess_return_pct     = Column(Float, nullable=True)
    hit                   = Column(Boolean, nullable=True)
    scored_at             = Column(DateTime, default=datetime.utcnow)
    # --- U2-4 (2026-08-24) --------------------------------------------------
    # True when the benchmark could not be priced at one or both ends of the
    # horizon. Such a row is *incomplete*, not neutral: ``benchmark_return_pct``
    # and ``excess_return_pct`` are NULL (the market's move is unknown, which is
    # not the same number as zero) and ``hit`` is NULL for any call graded against
    # the market. It stays pending — ``get_pending_scoring`` keeps returning it so
    # a later run can fill the benchmark in.
    benchmark_missing     = Column(Boolean, default=False)


#: Metrics worth keeping per company type, as ``(attribute, key)``. Deliberately
#: small: these are the numbers the open calibration questions turn on, not a dump
#: of the whole result. Absent attributes are skipped, so an object that does not
#: carry them (a crypto result, a duck-typed stub) simply contributes nothing.
_INDUSTRY_METRICS = (
    ("debt_equity", "debt_equity"),
    ("p_ffo", "p_ffo"),
    ("ffo_payout_pct", "ffo_payout_pct"),
    ("roe", "roe"),
    ("roic", "roic"),
    ("moat_score", "moat_score"),
    ("negative_equity", "negative_equity"),
)


#: Every attribute ``snapshot_calibration_inputs`` reads. Exported so a caller
#: that cannot keep the object around — the Screener, which builds rows inside a
#: thread pool — can snapshot the raw values and rebuild an equivalent stand-in.
CALIBRATION_ATTRS = (
    "sector", "industry",
    "profitability_score", "health_score", "valuation_score",
    "growth_score", "dividend_score",
    "equity_to_assets_pct",
) + tuple(attr for attr, _ in _INDUSTRY_METRICS)


def snapshot_calibration_inputs(fundamental: Any) -> dict:
    """Raw values of the attributes the track-record payload stores as ``inputs``.

    Pure and defensive: a missing attribute is skipped. Used by
    ``dashboard.shared._track_payload`` so a FundamentalResult-like object can
    be flattened after the thread pool without redesigning the store.
    """
    out = {}
    for attr in CALIBRATION_ATTRS:
        try:
            value = getattr(fundamental, attr, None)
        except Exception:
            continue
        if value is not None:
            out[attr] = value
    return out


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


class TrackRecordStore:
    """SQLite-backed store for recommendations and their scored outcomes."""

    def __init__(self, db_path: Any = None) -> None:
        path = db_path if db_path is not None else DB_PATH
        # ``sqlite:///:memory:`` is supported for tests by passing db_path=":memory:".
        url = "sqlite:///:memory:" if path == ":memory:" else f"sqlite:///{path}"
        self._engine = create_engine(url, echo=False)
        _Base.metadata.create_all(self._engine)
        self._migrate(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    def _migrate(self, engine) -> None:
        """Add new columns to an existing table without dropping data (SQLite safe).

        ``create_all`` creates *missing tables*; it does not touch a table that
        already exists, so U2-4's ``benchmark_missing`` would not appear on any
        database created before it. Same shape as ``alerts/store.py:_migrate``.
        """
        with engine.connect() as conn:
            from sqlalchemy import text

            try:
                conn.execute(text(
                    "ALTER TABLE recommendation_outcome "
                    "ADD COLUMN benchmark_missing BOOLEAN DEFAULT 0"
                ))
                conn.commit()
                logger.info("track_record migration: added recommendation_outcome.benchmark_missing")
            except Exception:
                pass  # column already exists

    # ------------------------------------------------------------------ #
    #  Capture                                                            #
    # ------------------------------------------------------------------ #

    def log_recommendation(
        self,
        decision: Any,
        *,
        source: str = "rule_based",
        price_at_rec: Optional[float] = None,
        plan_id: Optional[str] = None,
    ) -> Optional[int]:
        """Persist a ``Decision`` (or duck-typed equivalent). Returns the row id.

        Returns ``None`` when capture is disabled or the row is deduped away.
        Defensive by design: a logging failure must never break the analysis
        flow it is attached to.
        """
        if not TRACK_RECORD.enabled:
            return None

        try:
            symbol = str(getattr(decision, "symbol", "") or "").upper()
            action = str(getattr(decision, "action", "") or "")
            if not symbol or not action:
                logger.warning("track_record: skipping log — missing symbol/action")
                return None

            confidence = str(getattr(decision, "confidence", "MEDIUM") or "MEDIUM")
            fscore = float(getattr(decision, "fundamental_score", 0.0) or 0.0)
            tsignal = str(getattr(decision, "technical_signal", "") or "")
            rationale = getattr(decision, "rationale", []) or []

            if TRACK_RECORD.dedupe_same_day and self._exists_today(symbol, action):
                logger.debug(f"track_record: dedupe {symbol}/{action} (already logged today)")
                return None

            with self._Session() as s:
                row = RecommendationLog(
                    symbol=symbol,
                    action=action,
                    confidence=confidence,
                    fundamental_score=fscore,
                    technical_signal=tsignal,
                    source=source,
                    price_at_rec=(round(float(price_at_rec), 4) if price_at_rec else None),
                    rationale=json.dumps(list(rationale), ensure_ascii=False),
                    plan_id=plan_id,
                    created_at=_utcnow(),
                )
                s.add(row)
                s.commit()
                logger.info(f"track_record: logged {symbol} {action} ({source}) id={row.id}")
                return row.id
        except Exception as exc:  # never break the caller
            logger.error(f"track_record: failed to log recommendation — {exc}")
            return None

    def _exists_today(self, symbol: str, action: str) -> bool:
        today = _start_of_day(_utcnow())
        with self._Session() as s:
            return (
                s.query(RecommendationLog.id)
                .filter(
                    RecommendationLog.symbol == symbol,
                    RecommendationLog.action == action,
                    RecommendationLog.created_at >= today,
                )
                .first()
                is not None
            )

    # ------------------------------------------------------------------ #
    #  Reads                                                              #
    # ------------------------------------------------------------------ #

    def get_recommendations(
        self,
        *,
        symbol: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[RecommendationLog]:
        with self._Session() as s:
            q = s.query(RecommendationLog)
            if symbol:
                q = q.filter(RecommendationLog.symbol == symbol.upper())
            if source:
                q = q.filter(RecommendationLog.source == source)
            q = q.order_by(RecommendationLog.created_at.desc())
            if limit:
                q = q.limit(limit)
            return list(q.all())

    def get_pending_scoring(self, horizon_days: int, now: Optional[datetime] = None) -> List[RecommendationLog]:
        """Recommendations old enough for ``horizon_days`` that lack a *complete* outcome.

        An outcome written without its benchmark (U2-4) is not done — it carries a
        real return but no excess and, for a directional call, no hit. A failed
        benchmark lookup is usually transient, so those rows stay pending and a
        later run completes them in place (``save_outcome`` upserts). The cost is
        one cached lookup of the benchmark per run.
        """
        now = now or _utcnow()
        from datetime import timedelta

        cutoff = now - timedelta(days=horizon_days)
        with self._Session() as s:
            scored_ids = {
                r[0]
                for r in s.query(RecommendationOutcome.rec_id)
                .filter(
                    RecommendationOutcome.horizon_days == horizon_days,
                    RecommendationOutcome.benchmark_missing.isnot(True),
                )
                .all()
            }
            q = (
                s.query(RecommendationLog)
                .filter(RecommendationLog.created_at <= cutoff)
                .order_by(RecommendationLog.created_at)
            )
            return [r for r in q.all() if r.id not in scored_ids]

    def save_outcome(
        self,
        *,
        rec_id: int,
        horizon_days: int,
        price_at_horizon: Optional[float],
        return_pct: Optional[float],
        benchmark_return_pct: Optional[float],
        excess_return_pct: Optional[float],
        hit: Optional[bool],
        benchmark_missing: bool = False,
    ) -> None:
        """Upsert an outcome (idempotent on the (rec_id, horizon_days) pair).

        ``benchmark_missing`` defaults to False so existing call sites keep their
        exact behaviour; the scorer passes True when the benchmark could not be
        priced, which also keeps the row in ``get_pending_scoring`` for a retry.
        """
        with self._Session() as s:
            existing = (
                s.query(RecommendationOutcome)
                .filter(
                    RecommendationOutcome.rec_id == rec_id,
                    RecommendationOutcome.horizon_days == horizon_days,
                )
                .first()
            )
            if existing:
                existing.price_at_horizon = price_at_horizon
                existing.return_pct = return_pct
                existing.benchmark_return_pct = benchmark_return_pct
                existing.excess_return_pct = excess_return_pct
                existing.hit = hit
                existing.benchmark_missing = bool(benchmark_missing)
                existing.scored_at = _utcnow()
            else:
                s.add(
                    RecommendationOutcome(
                        rec_id=rec_id,
                        horizon_days=horizon_days,
                        price_at_horizon=price_at_horizon,
                        return_pct=return_pct,
                        benchmark_return_pct=benchmark_return_pct,
                        excess_return_pct=excess_return_pct,
                        hit=hit,
                        benchmark_missing=bool(benchmark_missing),
                        scored_at=_utcnow(),
                    )
                )
            s.commit()

    # joined view, handy for the dashboard
    def get_scored_rows(self, horizon_days: int) -> List[dict]:
        """Recommendations joined with their outcome at ``horizon_days``."""
        with self._Session() as s:
            recs = {r.id: r for r in s.query(RecommendationLog).all()}
            outs = (
                s.query(RecommendationOutcome)
                .filter(RecommendationOutcome.horizon_days == horizon_days)
                .all()
            )
            rows = []
            for o in outs:
                r = recs.get(o.rec_id)
                if r is None:
                    continue
                rows.append(
                    {
                        "rec_id": r.id,
                        "symbol": r.symbol,
                        "action": r.action,
                        "confidence": r.confidence,
                        "source": r.source,
                        "created_at": r.created_at,
                        "price_at_rec": r.price_at_rec,
                        "horizon_days": o.horizon_days,
                        "return_pct": o.return_pct,
                        "benchmark_return_pct": o.benchmark_return_pct,
                        "excess_return_pct": o.excess_return_pct,
                        "hit": o.hit,
                        # NULL on rows written before U2-4 — those were all scored
                        # with a benchmark, so False is the truthful reading.
                        "benchmark_missing": bool(o.benchmark_missing),
                    }
                )
            return rows


# Module-level singleton (mirrors alerts.store.alert_store)
track_record_store = TrackRecordStore()
