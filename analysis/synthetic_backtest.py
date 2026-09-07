"""
Storage for synthetic point-in-time backtest recommendations (PR 3/N + 5/N, Idea 2).

Third slice of "Backtesting point-in-time" (``docs/DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md``
§2/§4). PR 1 (``analysis/point_in_time.py``) and PR 2
(``analysis/point_in_time_piotroski.py``) reconstruct fundamentals and score
them; neither persists anything. This module is where the resulting scores
are persisted (PR 3/N) and, from PR 4/N on, actually generated in volume
against real SEC EDGAR data (``scripts/point_in_time_backtest.py``).

Deliberately a **separate table, separate store class, separate singleton** —
never ``analysis.track_record.RecommendationLog``/``track_record_store``.
N6 (see ``docs/ROADMAP.md``) is the reason this isn't a `source=` value on the
existing table: that incident showed the "some rows are fixtures/synthetic,
filter them out by default" pattern (``FIXTURE_SOURCE``, ``include_fixtures``)
is a **disciplinary** barrier — three read sites had to each remember to
apply the filter, and N6 itself happened because a totally different caller
(``alerts/engine.py``) reached the same singleton without anyone realizing.
At the volume a real backtest would produce (hundreds of synthetic scores
against ~417 real recommendations today), one read site that forgets to filter
would repeat N6's damage at a larger scale. A separate table makes the
exclusion **structural**: ``analysis.track_record_scorer``'s aggregates
(``hit_rate_by_action``, ``calibration_by_confidence``, ``equity_curve``, …)
query ``RecommendationLog``/``RecommendationOutcome`` directly — a table that
isn't there can't leak into them, no filter to forget.

PR 3/N's schema was deliberately minimal: just what PR 2's ``PiotroskiDetail``
already produces, with a note that outcome fields "are not added yet ...
not guessed at now". PR 5/N adds them — ``price_at_cutoff``,
``price_at_horizon``, ``return_pct``, ``benchmark_return_pct``,
``excess_return_pct``, ``benchmark_missing`` — via the same ``ADD COLUMN``
``_migrate`` pattern ``analysis/track_record.py`` uses for its own
"Calibration inputs" columns. **Schema only**: nothing in this PR measures
an outcome or writes a value into any of these columns — every one stays
``NULL``/unset until the PR that actually fetches prices via yfinance and
computes a return does so (PR 6/N). A single horizon (1 year), not
``RecommendationOutcome``'s multi-horizon 30/90/252-day table, because the
diagnóstico names exactly one horizon and Piotroski is itself a 1-year
signal (``config.PiotroskiConfig``) — a second table for horizons nothing
here asks for would be premature generality this project's conventions
already warn against.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, List, Optional, Union

from loguru import logger
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from analysis.scoring import PiotroskiDetail
from config import DB_PATH, FETCH
from data.clock import utc_now

#: Sentinel: ``log_piotroski``'s write was rejected because this exact
#: (symbol, as_of, source) already exists — the unique index doing exactly
#: its job, not a failure. Distinct from ``None`` (a genuine write error) so
#: a caller (``scripts/point_in_time_backtest.py``'s ``run()``) can tell them
#: apart: a transient read failure in ``existing_pairs`` (which itself
#: degrades to an empty set rather than raising) can make ``run()``
#: re-attempt a pair that was already safely stored, and that duplicate
#: write must not be counted as a real failure — see ``log_piotroski``'s
#: own docstring.
ALREADY_LOGGED = object()


class _Base(DeclarativeBase):
    pass


class SyntheticRecommendation(_Base):
    """One point-in-time Piotroski F-Score, reconstructed rather than emitted
    to a user — never a row a person actually saw.

    ``(symbol, as_of, source)`` is unique — enforced via a migration-created
    index (see ``SyntheticBacktestStore._migrate``), not a table-level
    ``UniqueConstraint`` here, because ``create_all`` only creates *missing*
    tables and never alters one that already exists (same limitation
    ``analysis/track_record.py``'s own ``_migrate`` works around). A
    constraint declared only in this class would never apply to a database
    file created before it — which for this table is not hypothetical: PR
    3/N shipped the schema with no constraint, and this PR's own manual
    verification run already wrote rows to the real database before this
    class gained one. So a batch backtest run (PR 4/N, which hits SEC EDGAR
    over the network per ticker) can use this table itself as its
    resumability checkpoint: skip a pair already here, insert otherwise — an
    interrupted run just picks up where it left off, and a re-run never
    double-counts a ticker×cutoff into the calibration sample, on *any*
    copy of the database regardless of when it was created.
    """

    __tablename__ = "synthetic_recommendation"
    id                        = Column(Integer, primary_key=True, autoincrement=True)
    symbol                    = Column(String, nullable=False, index=True)
    as_of                     = Column(String, nullable=False, index=True)  # ISO date, the cutoff
    piotroski_score           = Column(Integer, nullable=False)
    f1_roa_positive           = Column(Boolean, default=False)
    f2_ocf_positive           = Column(Boolean, default=False)
    f3_roa_improving          = Column(Boolean, default=False)
    f4_leverage_decreasing    = Column(Boolean, default=False)
    f5_liquidity_improving    = Column(Boolean, default=False)
    f6_no_dilution            = Column(Boolean, default=False)
    f7_gross_margin_improving = Column(Boolean, default=False)
    f8_asset_turnover_improving = Column(Boolean, default=False)
    f9_accruals_quality       = Column(Boolean, default=False)
    # Which reconstruction produced this row — always "point_in_time_piotroski"
    # today, but named (not assumed) for when a second synthetic generator
    # exists (e.g. the quant-only moat tramo mentioned in PR 2's discussion).
    source                    = Column(String, default="point_in_time_piotroski")
    created_at                = Column(DateTime, default=utc_now)

    # --- Outcome fields (PR 5/N) ---------------------------------------
    # Deliberately added via _migrate's ADD COLUMN pattern (below), not
    # designed into the original PR 3/N schema — see that module's own
    # docstring: "not guessed at now". Every column here is nullable and
    # unset by default; nothing that writes a row today (PR 4/N's
    # log_piotroski) sets any of these, and no PR yet *measures* them —
    # that is PR 6/N. This PR is schema-only.
    #
    # Single horizon (1 year), unlike analysis/track_record.py's
    # RecommendationOutcome (a separate table for 30/90/252-day horizons):
    # the diagnóstico that motivated this whole idea names one horizon —
    # "medir outcomes a 1 año" — and Piotroski is itself a 1-year signal
    # (config.PiotroskiConfig: "a 1-year value screen"), so a second table
    # for horizons nothing here will ever ask for would be exactly the
    # premature generality this project's own conventions warn against.
    price_at_cutoff           = Column(Float, nullable=True)   # price on `as_of`, for this ticker's own return
    price_at_horizon          = Column(Float, nullable=True)   # price ~1 year later
    horizon_date              = Column(String, nullable=True)  # ISO date actually used for "+1 year"
    return_pct                = Column(Float, nullable=True)
    benchmark_return_pct      = Column(Float, nullable=True)
    excess_return_pct         = Column(Float, nullable=True)
    # Same U2-4 precedent as RecommendationOutcome.benchmark_missing
    # (analysis/track_record.py): a benchmark that could not be priced is
    # unknown, not zero — benchmark_return_pct/excess_return_pct stay NULL
    # rather than defaulting to a number that would read as "tied the
    # market" when the truth is "we don't know".
    benchmark_missing         = Column(Boolean, default=False)
    outcome_scored_at         = Column(DateTime, nullable=True)


class SyntheticBacktestStore:
    """SQLite-backed store for synthetic point-in-time recommendations.

    Same ``DB_PATH`` as ``analysis.track_record.TrackRecordStore`` — same
    engine-construction shape, deliberately — but its own table, its own
    class, its own singleton. Nothing here imports
    ``analysis.track_record``, and nothing there imports this.
    """

    def __init__(self, db_path: Any = None) -> None:
        path = db_path if db_path is not None else DB_PATH
        url = "sqlite:///:memory:" if path == ":memory:" else f"sqlite:///{path}"
        self._engine = create_engine(url, echo=False)
        _Base.metadata.create_all(self._engine)
        self._migrate_outcome_columns(self._engine)
        self.unique_index_verified = self._migrate(self._engine)
        self._Session = sessionmaker(bind=self._engine)

    def _migrate_outcome_columns(self, engine) -> None:
        """Add the PR 5/N outcome columns to a database file that may
        already have this table without them (SQLite safe). Same shape as
        ``analysis/track_record.py``'s own ``_migrate`` — a plain ``ADD
        COLUMN`` per field, wrapped in ``try/except: pass`` because *that*
        exception (column already exists) genuinely is the benign,
        expected case here, unlike the unique-index migration below.
        """
        columns = [
            ("price_at_cutoff", "FLOAT"),
            ("price_at_horizon", "FLOAT"),
            ("horizon_date", "VARCHAR"),
            ("return_pct", "FLOAT"),
            ("benchmark_return_pct", "FLOAT"),
            ("excess_return_pct", "FLOAT"),
            ("benchmark_missing", "BOOLEAN DEFAULT 0"),
            ("outcome_scored_at", "DATETIME"),
        ]
        with engine.connect() as conn:
            for column, col_def in columns:
                try:
                    conn.execute(text(f"ALTER TABLE synthetic_recommendation ADD COLUMN {column} {col_def}"))
                    conn.commit()
                    logger.info(f"synthetic_backtest migration: added synthetic_recommendation.{column}")
                except Exception:
                    pass  # column already exists

    def _migrate(self, engine) -> bool:
        """Apply the uniqueness guarantee to a database file that may already
        exist (SQLite safe). ``CREATE UNIQUE INDEX IF NOT EXISTS`` is the
        SQLite-native way to add this after the fact, idempotent whether the
        table was just created fresh or already had rows in it — unlike
        ``analysis/track_record.py``'s own ``_migrate`` (a bare ``ADD COLUMN``
        that always raises on a column that already exists, the benign case
        its ``except: pass`` covers), ``IF NOT EXISTS`` already makes "already
        there" a silent no-op here, so this function's retry loop below has
        no equivalent there — it exists because this migration's one
        realistic failure mode (pre-existing duplicate data, or a transient
        lock) has no safe "already applied" reading to fall back on.

        An exception here is never "already exists". The one realistic cause
        is a database that already holds duplicate ``(symbol, as_of, source)``
        rows from before this constraint existed (not hypothetical: this
        table shipped with no constraint in PR 3/N). Silently swallowing that
        would leave every resumability guarantee this module advertises
        quietly false for that database. Returns whether the index was
        actually confirmed present (queried back, not assumed from a lack of
        exception) — callers that depend on the invariant (the batch backtest
        script) must check this and refuse to run rather than silently risk
        duplicate calibration rows.

        Retries ``OperationalError`` (e.g. "database is locked" from a
        concurrently-writing dashboard or scheduler on the same ``DB_PATH``
        file — this store's own singleton is built at import time, so this
        genuinely can race another process) via ``config.FETCH`` — the same
        retry policy every other network/IO fetch in this project already
        uses, not a second one invented here — before giving up;
        ``IntegrityError`` (real duplicate data — retrying changes nothing)
        fails immediately, the same transient-vs-permanent distinction
        ``log_piotroski`` already makes per row, applied here to the one-time
        migration step instead.
        """
        attempts = max(1, int(FETCH.max_retries))
        delay = float(FETCH.retry_base_delay_s)
        for attempt in range(1, attempts + 1):
            try:
                self._create_unique_index(engine)
                break
            except IntegrityError as exc:
                logger.error(
                    f"synthetic_backtest migration: duplicate (symbol, as_of, source) "
                    f"rows already exist — {exc}"
                )
                return False
            except OperationalError as exc:
                if attempt == attempts:
                    logger.error(f"synthetic_backtest migration: still locked after retries — {exc}")
                    return False
                time.sleep(delay)
                delay *= 2
            except Exception as exc:
                logger.error(f"synthetic_backtest migration: could not create unique index — {exc}")
                return False

        with engine.connect() as conn:
            exists = conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_synthetic_symbol_asof_source'"
            )).fetchone()
            if exists is None:
                logger.error("synthetic_backtest migration: unique index missing after CREATE — unverified")
                return False
            return True

    @staticmethod
    def _create_unique_index(engine) -> None:
        """One attempt at the ``CREATE UNIQUE INDEX``. Split out from
        ``_migrate`` so a retry test can stub *this* directly instead of
        wrapping a live SQLAlchemy connection.
        """
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_synthetic_symbol_asof_source "
                "ON synthetic_recommendation (symbol, as_of, source)"
            ))
            conn.commit()

    def log_piotroski(
        self,
        symbol: str,
        as_of: date,
        detail: PiotroskiDetail,
        source: str = "point_in_time_piotroski",
    ) -> Union[int, object, None]:
        """Persist one reconstructed F-Score. Returns the new row's id,
        ``ALREADY_LOGGED`` if this exact (symbol, as_of, source) already
        existed, or ``None`` on any other failure.

        ``ALREADY_LOGGED`` is not a failure — it is the unique index doing
        exactly its job — but it is not success either, and conflating it
        with a real error matters to a caller like
        ``scripts/point_in_time_backtest.py``'s ``run()``: that script's own
        ``existing_pairs()`` resumability check already has a defensive
        ``except Exception: return set()`` fallback for a transient read
        failure, which would otherwise make ``run()`` re-attempt a pair that
        was already safely stored. Rejecting that duplicate write with the
        *same* exception class ``log_piotroski`` used for every other error
        would count a one-off read hiccup as a real failure and flip
        ``main()``'s exit code, even though nothing was ever actually lost.

        Defensive by design, same as ``TrackRecordStore.log_recommendation``
        (``analysis/track_record.py``): the PR that wires this in loops over
        the universe × many historical cutoffs — hundreds or thousands of
        calls — and one transient sqlite error (lock contention with a
        concurrently-running dashboard reading the same ``DB_PATH`` file,
        say) must skip that row, not abort the whole batch.

        ``symbol`` is upper-cased to match ``get_all``'s exact-match filter
        and ``RecommendationLog``'s own convention — a caller passing a
        lowercase ticker would otherwise write a row ``get_all(symbol="AAPL")``
        can never find.
        """
        try:
            with self._Session() as session:
                row = SyntheticRecommendation(
                    symbol=symbol.upper(),
                    as_of=as_of.isoformat(),
                    piotroski_score=detail.score,
                    f1_roa_positive=detail.f1_roa_positive,
                    f2_ocf_positive=detail.f2_ocf_positive,
                    f3_roa_improving=detail.f3_roa_improving,
                    f4_leverage_decreasing=detail.f4_leverage_decreasing,
                    f5_liquidity_improving=detail.f5_liquidity_improving,
                    f6_no_dilution=detail.f6_no_dilution,
                    f7_gross_margin_improving=detail.f7_gross_margin_improving,
                    f8_asset_turnover_improving=detail.f8_asset_turnover_improving,
                    f9_accruals_quality=detail.f9_accruals_quality,
                    source=source,
                )
                session.add(row)
                session.commit()
                return row.id
        except IntegrityError as exc:
            logger.warning(f"synthetic_backtest: {symbol} @ {as_of} already logged — {exc}")
            return ALREADY_LOGGED
        except Exception as exc:  # never break a batch backtest run
            logger.error(f"synthetic_backtest: failed to log {symbol} @ {as_of} — {exc}")
            return None

    def get_all(self, symbol: Optional[str] = None) -> List[SyntheticRecommendation]:
        with self._Session() as session:
            query = session.query(SyntheticRecommendation)
            if symbol is not None:
                query = query.filter(SyntheticRecommendation.symbol == symbol.upper())
            return query.order_by(SyntheticRecommendation.as_of).all()

    def existing_pairs(self, symbol: str, source: str = "point_in_time_piotroski") -> set:
        """The ``as_of`` dates already logged for *symbol* — what a batch run
        checks before spending a network call, so an interrupted run can
        resume without re-fetching or re-scoring what it already has.

        Defensive like ``log_piotroski``, for the same reason: a batch run
        calls this once per symbol in its universe, and a transient sqlite
        error (lock contention with a concurrently-writing dashboard or
        scheduler on the same ``DB_PATH`` file) here must not crash the whole
        run. An empty result on failure is the safe direction — the caller
        re-fetches and re-scores that symbol as if nothing were logged yet,
        and any pair that genuinely already exists is caught downstream by
        the unique index (logged, not written twice), never lost silently.
        """
        try:
            with self._Session() as session:
                rows = (
                    session.query(SyntheticRecommendation.as_of)
                    .filter(
                        SyntheticRecommendation.symbol == symbol.upper(),
                        SyntheticRecommendation.source == source,
                    )
                    .all()
                )
                return {r[0] for r in rows}
        except Exception as exc:  # never break a batch backtest run
            logger.error(f"synthetic_backtest: failed to read existing pairs for {symbol} — {exc}")
            return set()


# Module-level singleton (mirrors analysis.track_record.track_record_store)
synthetic_backtest_store = SyntheticBacktestStore()
