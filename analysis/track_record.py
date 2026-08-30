"""
Track record — persistent log of every recommendation the engine emits.

Gran Salto, Fase 1. Mirrors the persistence pattern of ``alerts/store.py``
(SQLAlchemy DeclarativeBase + SQLite at the shared ``DB_PATH``). This module is
the *capture* half; deferred outcome scoring lives in
``analysis/track_record_scorer.py``.

Tables (same DB as cache/alerts):
  recommendation_log      — one row per recommendation emitted to the user
  recommendation_outcome  — deferred scoring of each (rec, horizon) pair

"Una recomendación por día" se decide en dos lugares y con **una sola** regla
(``same_local_day_key``): ``_exists_today`` la aplica al escribir, y
``collapse_same_local_day`` la aplica al leer, sobre las filas que la regla vieja
—día UTC, pre-U5-18— alcanzó a dejar entrar. El log crudo no se toca: es el
registro de lo que el motor efectivamente emitió.

Design notes (project conventions):
  - Config-driven: horizons, benchmark and dedupe behaviour come from
    ``config.TRACK_RECORD`` — never hardcoded here.
  - Synchronous, no async. Logging via loguru.
  - Tests use a real in-memory SQLite, not mocks (see tests/test_track_record.py).
"""

from __future__ import annotations

import json
from datetime import datetime
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
from data.clock import local_day_start_utc, utc_now


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
    created_at        = Column(DateTime, default=utc_now, index=True)

    # --- Calibration inputs (2026-08-22) ------------------------------------
    # Everything above describes *what was recommended*. These describe *why*, and
    # they exist because the questions this table is supposed to settle could not be
    # answered without them: where to cut the decision thresholds, which capital
    # ratio separates a solid bank from a fragile one, what leverage is normal for a
    # regulated utility. All three are answered by grouping past recommendations by
    # the metric that drove them — and none of that was being stored.
    #
    # This is the one gap that could not wait: a recommendation's metrics cannot be
    # reconstructed once prices and statements have moved on, so every day without
    # these columns produced evidence that would never be usable.
    sector            = Column(String, default="")
    industry          = Column(String, default="")
    profitability_score = Column(Float, nullable=True)
    health_score      = Column(Float, nullable=True)
    valuation_score   = Column(Float, nullable=True)
    growth_score      = Column(Float, nullable=True)
    dividend_score    = Column(Float, nullable=True)
    # Industry-specific metrics, JSON-encoded like ``rationale`` above, because what
    # matters is polymorphic: equity/assets for a bank, P/FFO for a REIT, D/E for a
    # utility. A ``backfilled`` key marks rows reconstructed after the fact.
    metrics_json      = Column(Text, default="")


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
    scored_at             = Column(DateTime, default=utc_now)

    # --- U2-4 (2026-08-24) --------------------------------------------------
    # True when the benchmark could not be priced at one or both ends of the
    # horizon. Such a row is *incomplete*, not neutral: ``benchmark_return_pct``
    # and ``excess_return_pct`` are NULL (the market's move is unknown, which is
    # not the same number as zero) and ``hit`` is NULL for any call graded against
    # the market. It stays pending — ``get_pending_scoring`` keeps returning it so
    # a later run can fill the benchmark in.
    benchmark_missing     = Column(Boolean, default=False)


#: U5-18: el reloj y el corte del día viven en ``data.clock``. Este módulo tenía
#: su propio ``_utcnow`` —correcto pero duplicado— y un ``_start_of_day`` que
#: cortaba a las 00:00 **UTC**. Para un usuario en UTC−3 eso hacía que el "día"
#: del dedup corriera de 21:00 a 21:00 local, y dejaba entrar 80 de 394 filas
#: que eran la misma recomendación repetida en el mismo día del usuario.


# --------------------------------------------------------------------------- #
#  "Una recomendación por día" — la regla, en un solo lugar                    #
# --------------------------------------------------------------------------- #

def same_local_day_key(symbol: str, action: str, created_at: datetime) -> tuple:
    """La identidad de «la misma recomendación, el mismo día».

    Existe para que la escritura y la lectura no puedan derivar. U5-18 arregló el
    corte del día en el write-side (``_exists_today``) pero **no migró nada**, y
    no podía: las filas que la regla vieja dejó entrar siguen en la base. Así que
    la lectura tiene que aplicar la misma regla sobre lo ya escrito, y la única
    forma de garantizar que sea *la misma* es que haya una sola.

    Los tres componentes importan. El día se corta en **local** porque "uno por
    día" es un concepto humano (ver ``data.clock``); el símbolo se normaliza a
    mayúsculas porque es como lo guarda ``log_recommendation``; y la acción entra
    tal cual, porque un BUY y un HOLD del mismo ticker el mismo día son dos
    recomendaciones distintas, no una repetida.
    """
    return (
        str(symbol or "").upper(),
        str(action or ""),
        local_day_start_utc(created_at),
    )


def collapse_same_local_day(rows: List[dict]) -> List[dict]:
    """Una fila por ``(símbolo, acción, día local)``: sobrevive la **primera**.

    Puro. ``rows`` son los dicts que produce ``TrackRecordStore.get_scored_rows``.

    **Por qué la primera y no la última.** Es la que el write-side ya elige:
    ``_exists_today`` rechaza la *posterior* ("already logged today"). Quedarse
    con la última mezclaría dos políticas de selección en la misma muestra —las
    filas escritas después de U5-18 seleccionadas por una regla y las anteriores
    por otra—, que es exactamente la clase de defecto que U5-18 cerró. El precio
    no decide: medido sobre los 74 pares reales que lo tienen, ``price_at_rec`` es
    **idéntico** dentro del par (sale de ``get_history(interval="1d")`` cacheado,
    así que las dos corridas del mismo día leen el mismo cierre). Lo que sí
    difiere es ``created_at``: los 80 pares cruzan el límite de día UTC, de modo
    que la última lleva una fecha del día siguiente para algo que el usuario vio
    el día anterior, y su horizonte (``created_at + 30d``) cae contra otro cierre.

    **Por qué esto en vez de borrar las filas.** Borrar es irreversible —la base
    está gitignoreada— y edita el registro de lo que el motor efectivamente
    emitió: emitió esas filas. Colapsar en lectura corrige lo que se cuenta y deja
    intacto lo que pasó.

    Una fila **sin fecha** pasa entera en vez de desaparecer: no pertenece a
    ningún día, y asignarle uno sería inventarlo (la misma regla que
    ``data.clock.hours_since``). El orden de entrada se preserva.
    """
    ganadores: dict = {}
    for idx, row in enumerate(rows):
        created = row.get("created_at")
        if created is None:
            continue
        key = same_local_day_key(row.get("symbol"), row.get("action"), created)
        # Desempate por ``rec_id`` para que dos filas con el mismo instante elijan
        # siempre la misma, y por índice para que el resultado no dependa de un
        # ``rec_id`` ausente.
        rank = (created, row.get("rec_id") or 0, idx)
        if key not in ganadores or rank < ganadores[key][0]:
            ganadores[key] = (rank, idx)

    conservados = {idx for _, idx in ganadores.values()}
    return [
        row for idx, row in enumerate(rows)
        if row.get("created_at") is None or idx in conservados
    ]


#: Metrics worth keeping per company type, as ``(attribute, key)``. Deliberately
#: small: these are the numbers the open calibration questions turn on, not a dump
#: of the whole result. Absent attributes are skipped, so an object that does not
#: carry them (a crypto result, a duck-typed stub) simply contributes nothing.
_INDUSTRY_METRICS = (
    ("debt_equity", "debt_equity"),        # utilities: what leverage is normal here?
    ("p_ffo", "p_ffo"),                    # REITs: the multiple that means something
    ("ffo_payout_pct", "ffo_payout_pct"),
    ("roe", "roe"),
    ("roic", "roic"),
    ("moat_score", "moat_score"),
    ("negative_equity", "negative_equity"),
)


#: Every attribute ``calibration_fields`` reads. Exported so a caller that cannot
#: keep the object around — the Screener, which builds rows inside a thread pool —
#: can snapshot the raw values and rebuild an equivalent stand-in later.
CALIBRATION_ATTRS = (
    "sector", "industry",
    "profitability_score", "health_score", "valuation_score",
    "growth_score", "dividend_score",
    "equity_to_assets_pct",
) + tuple(attr for attr, _ in _INDUSTRY_METRICS)


def snapshot_calibration_inputs(fundamental: Any) -> dict:
    """Raw values of the attributes ``calibration_fields`` reads.

    The round-trip that matters: ``calibration_fields(SimpleNamespace(**snapshot))``
    must equal ``calibration_fields(fundamental)``. Storing the *output* of
    ``calibration_fields`` instead would not survive it — the industry metrics come
    back already JSON-encoded and a second pass would silently drop them.
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


def calibration_fields(fundamental: Any) -> dict:
    """Columns to store alongside a recommendation so it can be calibrated later.

    Pure and defensive: anything missing is simply left out. Returns ``{}`` for
    ``None`` so callers that have no ``FundamentalResult`` behave exactly as before.

    The point of separating this from the store is that *what is worth remembering*
    is a judgement that changes as new questions appear (banks needed a capital
    ratio nobody was recording), while the persistence around it does not.
    """
    if fundamental is None:
        return {}

    def safe(attr):
        """A hostile or half-built object costs us the field, never the row."""
        try:
            return getattr(fundamental, attr, None)
        except Exception:
            return None

    out: dict = {}
    for attr in ("sector", "industry"):
        value = safe(attr)
        if value:
            out[attr] = str(value)

    for attr in ("profitability_score", "health_score", "valuation_score",
                 "growth_score", "dividend_score"):
        value = safe(attr)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[attr] = float(value)

    metrics = {}
    # Equity/assets leads the list: it is the capital ratio the bank question turns
    # on, and the one genuinely unrecoverable later — it needs the balance sheet as
    # of the recommendation, not as of whenever someone gets around to asking.
    for attr, key in (("equity_to_assets_pct", "equity_to_assets_pct"),) + _INDUSTRY_METRICS:
        value = safe(attr)
        if isinstance(value, bool):
            metrics[key] = value
        elif isinstance(value, (int, float)):
            metrics[key] = round(float(value), 4)

    if metrics:
        try:
            out["metrics_json"] = json.dumps(metrics, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
    return out


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
        already exists, so the calibration columns added in 2026-08 would simply not
        appear on any database created before them — and every read of them would
        fail. Same shape as ``alerts/store.py:_migrate``.
        """
        migrations = [
            ("recommendation_log", "sector",              "VARCHAR DEFAULT ''"),
            ("recommendation_log", "industry",            "VARCHAR DEFAULT ''"),
            ("recommendation_log", "profitability_score", "FLOAT"),
            ("recommendation_log", "health_score",        "FLOAT"),
            ("recommendation_log", "valuation_score",     "FLOAT"),
            ("recommendation_log", "growth_score",        "FLOAT"),
            ("recommendation_log", "dividend_score",      "FLOAT"),
            ("recommendation_log", "metrics_json",        "TEXT DEFAULT ''"),
            ("recommendation_outcome", "benchmark_missing", "BOOLEAN DEFAULT 0"),
        ]
        with engine.connect() as conn:
            from sqlalchemy import text

            for table, column, col_def in migrations:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
                    conn.commit()
                    logger.info(f"track_record migration: added {table}.{column}")
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
        fundamental: Any = None,
    ) -> Optional[int]:
        """Persist a ``Decision`` (or duck-typed equivalent). Returns the row id.

        Pass ``fundamental`` (the ``FundamentalResult`` behind the decision) to also
        capture what the calibration questions need: sector, industry, the five
        dimensions separately, and the industry-specific metric. Optional so every
        existing call site keeps working, but a call without it records a
        recommendation that can never be used to calibrate anything.

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

            fields = calibration_fields(fundamental)

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
                    created_at=utc_now(),
                    **fields,
                )
                s.add(row)
                s.commit()
                logger.info(f"track_record: logged {symbol} {action} ({source}) id={row.id}")
                return row.id
        except Exception as exc:  # never break the caller
            logger.error(f"track_record: failed to log recommendation — {exc}")
            return None

    def _exists_today(self, symbol: str, action: str) -> bool:
        """¿Ya se logueó esta recomendación en el día **local** de hoy?

        Los tres términos del filtro salen de ``same_local_day_key``, no de un
        ``local_day_start_utc`` propio. Es deliberado: la lectura
        (``collapse_same_local_day``) aplica esa misma clave sobre lo ya escrito,
        y una sola definición es lo único que impide que las dos reglas deriven.
        ``tests/test_track_record_dedupe_read_oracle.py`` las ejercita con los
        mismos datos en cuatro zonas horarias y exige que decidan lo mismo.
        """
        symbol_key, action_key, day_start = same_local_day_key(symbol, action, utc_now())
        with self._Session() as s:
            return (
                s.query(RecommendationLog.id)
                .filter(
                    RecommendationLog.symbol == symbol_key,
                    RecommendationLog.action == action_key,
                    RecommendationLog.created_at >= day_start,
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
        now = now or utc_now()
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
                existing.scored_at = utc_now()
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
                        scored_at=utc_now(),
                    )
                )
            s.commit()

    # joined view, handy for the dashboard
    def get_scored_rows(self, horizon_days: int, *, collapse_same_day: bool = True) -> List[dict]:
        """Recommendations joined with their outcome at ``horizon_days``.

        ``collapse_same_day`` deja una fila por ``(símbolo, acción, día local)``
        —la primera— vía ``collapse_same_local_day``. Es **el** punto por donde
        pasan las cinco métricas de la página, así que el default prendido las
        corrige sin tocar a los dos consumidores (``13_Track_Record.py`` y
        ``shared.py``).

        Hoy es un no-op y lo será por unas semanas: la vista se arma desde
        ``recommendation_outcome``, y ninguna de las 80 duplicadas del log tiene
        outcome porque ninguna cumplió los 30 días. Cuando venzan deja de serlo, y
        lo que más se mueve no es el ``n`` sino ``equity_curve``, que **compone**:
        cada fila multiplica el capital, así que una duplicada aplica dos veces el
        mismo retorno — y el sesgo es asimétrico a favor del motor, porque el
        modelo compone más rápido que el benchmark y la brecha se ensancha sola.

        ``collapse_same_day=False`` devuelve el crudo. No es un detalle: es la
        auditoría de lo que el motor realmente emitió, y es justo lo que borrar
        las filas sacaría para siempre. Es keyword-only para que no se confunda
        con el horizonte.

        No depende de ``TRACK_RECORD.dedupe_same_day``: ese flag gobierna qué se
        **escribe**. El log ya contiene filas escritas con una regla que no rige
        más, así que la lectura tiene que colapsar igual.
        """
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
            return collapse_same_local_day(rows) if collapse_same_day else rows


# Module-level singleton (mirrors alerts.store.alert_store)
track_record_store = TrackRecordStore()
