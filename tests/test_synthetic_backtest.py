"""Functional tests for analysis/synthetic_backtest.py — always against an
explicit ``:memory:`` store, never the module singleton (which conftest.py
already redirects, but constructing one explicitly here is the documented
convention for any test that needs a real store, per docs/CONTEXT.md §5).
"""

from datetime import date

from analysis.scoring import PiotroskiDetail
from analysis.synthetic_backtest import (
    ALREADY_LOGGED,
    SyntheticBacktestStore,
    SyntheticRecommendation,
)


def _detail(score_true_count: int) -> PiotroskiDetail:
    """A PiotroskiDetail with the first *score_true_count* checks True."""
    fields = [
        "f1_roa_positive", "f2_ocf_positive", "f3_roa_improving",
        "f4_leverage_decreasing", "f5_liquidity_improving", "f6_no_dilution",
        "f7_gross_margin_improving", "f8_asset_turnover_improving", "f9_accruals_quality",
    ]
    return PiotroskiDetail(**{f: (i < score_true_count) for i, f in enumerate(fields)})


def test_log_piotroski_persists_the_score_and_all_nine_checks():
    store = SyntheticBacktestStore(":memory:")
    detail = _detail(7)

    row_id = store.log_piotroski("AAPL", date(2021, 6, 1), detail)

    rows = store.get_all()
    assert len(rows) == 1
    row = rows[0]
    assert row.id == row_id
    assert row.symbol == "AAPL"
    assert row.as_of == "2021-06-01"
    assert row.piotroski_score == 7
    assert row.f1_roa_positive is True
    assert row.f9_accruals_quality is False
    assert row.source == "point_in_time_piotroski"


def test_log_piotroski_leaves_outcome_columns_unset():
    """PR 5/N is schema-only — log_piotroski (PR 3/N) doesn't know about
    outcomes and must not silently invent a value for any of them.
    """
    store = SyntheticBacktestStore(":memory:")
    store.log_piotroski("AAPL", date(2021, 6, 1), _detail(7))

    row = store.get_all()[0]
    assert row.price_at_cutoff is None
    assert row.price_at_horizon is None
    assert row.horizon_date is None
    assert row.return_pct is None
    assert row.benchmark_return_pct is None
    assert row.excess_return_pct is None
    assert row.benchmark_missing is False
    assert row.outcome_scored_at is None


def test_outcome_columns_migrate_onto_a_pre_existing_database():
    """A database created before PR 5/N (PR 3/N and PR 4/N both shipped
    without these columns, and both are already merged) must gain them
    without losing any existing row — the same guarantee
    ``analysis/track_record.py``'s own ``_migrate`` already gives
    ``recommendation_log`` for its "Calibration inputs" columns.
    """
    import sqlite3

    from sqlalchemy import create_engine

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE synthetic_recommendation ("
        "id INTEGER PRIMARY KEY, symbol TEXT, as_of TEXT, piotroski_score INTEGER, "
        "source TEXT)"
    )
    conn.execute(
        "INSERT INTO synthetic_recommendation (symbol, as_of, piotroski_score, source) "
        "VALUES ('AAPL', '2021-06-01', 7, 'point_in_time_piotroski')"
    )
    conn.commit()

    store = SyntheticBacktestStore.__new__(SyntheticBacktestStore)
    store._engine = create_engine("sqlite://", creator=lambda: conn)
    store._migrate_outcome_columns(store._engine)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(synthetic_recommendation)")}
    assert {
        "price_at_cutoff", "price_at_horizon", "horizon_date", "return_pct",
        "benchmark_return_pct", "excess_return_pct", "benchmark_missing", "outcome_scored_at",
    } <= cols

    row = conn.execute("SELECT symbol, piotroski_score FROM synthetic_recommendation").fetchone()
    assert row == ("AAPL", 7)  # the pre-existing row survives untouched

    # benchmark_missing backfills to 0 (not NULL) on the pre-existing row —
    # "not scored yet" is a definite False, per the U2-4 precedent.
    assert conn.execute("SELECT benchmark_missing FROM synthetic_recommendation").fetchone()[0] == 0


def test_benchmark_missing_ddl_is_identical_on_the_fresh_and_migrated_paths():
    """A create_all()'d table and an ALTER-migrated one must give
    benchmark_missing the same SQL-level default — otherwise a raw SQL path
    that omits the column sees NULL on one and 0 on the other for the same
    "not scored yet" state.
    """
    import sqlite3

    from sqlalchemy import create_engine, text

    fresh = SyntheticBacktestStore(":memory:")
    with fresh._engine.connect() as conn:
        fresh_dflt = {
            r[1]: r[4] for r in conn.execute(text("PRAGMA table_info(synthetic_recommendation)"))
        }["benchmark_missing"]

    raw = sqlite3.connect(":memory:")
    raw.execute(
        "CREATE TABLE synthetic_recommendation ("
        "id INTEGER PRIMARY KEY, symbol TEXT, as_of TEXT, piotroski_score INTEGER, source TEXT)"
    )
    raw.commit()
    migrated = SyntheticBacktestStore.__new__(SyntheticBacktestStore)
    migrated._engine = create_engine("sqlite://", creator=lambda: raw)
    assert migrated._migrate_outcome_columns(migrated._engine) is True
    migrated_dflt = {
        r[1]: r[4] for r in raw.execute("PRAGMA table_info(synthetic_recommendation)")
    }["benchmark_missing"]

    assert fresh_dflt == migrated_dflt == "0"


def test_migrate_outcome_columns_reads_pragma_only_once_when_already_fully_migrated(monkeypatch):
    """The common case from the second run on: every column already exists,
    so the up-front ``PRAGMA table_info`` read already answers the same
    question a final re-verification would — paying for that query twice
    on every cold start of every process that imports this module, forever,
    to learn something already known is pure waste.
    """
    store = SyntheticBacktestStore(":memory:")  # already fully migrated

    calls = {"n": 0}
    real_migrated_columns = SyntheticBacktestStore._migrated_columns

    def _counting(engine):
        calls["n"] += 1
        return real_migrated_columns(engine)

    monkeypatch.setattr(store, "_migrated_columns", _counting)

    result = store._migrate_outcome_columns(store._engine)

    assert result is True
    assert calls["n"] == 1, "must not re-query PRAGMA table_info once `existing` already covers every column"


def test_migrate_outcome_columns_retries_a_transient_failure_and_still_succeeds(monkeypatch):
    """A concurrently-writing dashboard or scheduler on the same DB_PATH file
    can make ``ALTER TABLE ADD COLUMN`` raise a transient "database is
    locked" error too, same as the unique-index migration — checked via
    ``PRAGMA table_info`` up front specifically so this failure can be told
    apart from "column already exists" (SQLite raises the identical
    ``OperationalError`` for both) and retried rather than silently skipped.
    """
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE synthetic_recommendation ("
        "id INTEGER PRIMARY KEY, symbol TEXT, as_of TEXT, piotroski_score INTEGER, source TEXT)"
    )
    conn.commit()

    store = SyntheticBacktestStore.__new__(SyntheticBacktestStore)
    store._engine = create_engine("sqlite://", creator=lambda: conn)

    calls = {"n": 0}
    real_add = SyntheticBacktestStore._add_outcome_column

    def _flaky_add(engine, column, col_def):
        if column == "price_at_cutoff":
            calls["n"] += 1
            if calls["n"] == 1:
                raise OperationalError("ALTER TABLE ...", {}, RuntimeError("database is locked"))
        return real_add(engine, column, col_def)

    monkeypatch.setattr(store, "_add_outcome_column", _flaky_add)
    monkeypatch.setattr("analysis.synthetic_backtest.time.sleep", lambda *_: None)

    store._migrate_outcome_columns(store._engine)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(synthetic_recommendation)")}
    assert "price_at_cutoff" in cols
    assert calls["n"] == 2, "must retry exactly once after the transient failure, then succeed"


def test_migrate_outcome_columns_tolerates_a_concurrent_writer_adding_the_same_column(monkeypatch):
    """The up-front PRAGMA check only rules out the *initial* state — a second
    writer can add the same column in the gap before our own ALTER TABLE,
    raising the identical OperationalError ("duplicate column name") as a
    genuine lock. The batch just retries it (bounded by ``config.FETCH``) and
    the final PRAGMA re-read confirms it landed — so the migration still
    returns True without special-casing the race, and the other columns are
    unaffected.
    """
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    from config import FETCH

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE synthetic_recommendation ("
        "id INTEGER PRIMARY KEY, symbol TEXT, as_of TEXT, piotroski_score INTEGER, source TEXT)"
    )
    conn.commit()

    store = SyntheticBacktestStore.__new__(SyntheticBacktestStore)
    store._engine = create_engine("sqlite://", creator=lambda: conn)

    real_add = SyntheticBacktestStore._add_outcome_column
    raced = {"done": False}

    def _lost_the_race(engine, column, col_def):
        if column == "price_at_cutoff" and not raced["done"]:
            raced["done"] = True
            conn.execute(f"ALTER TABLE synthetic_recommendation ADD COLUMN {column} {col_def}")
            conn.commit()
            raise OperationalError("ALTER TABLE ...", {}, RuntimeError("duplicate column name: price_at_cutoff"))
        return real_add(engine, column, col_def)

    sleeps = {"n": 0}
    monkeypatch.setattr(store, "_add_outcome_column", _lost_the_race)
    monkeypatch.setattr(
        "analysis.synthetic_backtest.time.sleep",
        lambda *_: sleeps.__setitem__("n", sleeps["n"] + 1),
    )

    result = store._migrate_outcome_columns(store._engine)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(synthetic_recommendation)")}
    assert {
        "price_at_cutoff", "price_at_horizon", "horizon_date", "return_pct",
        "benchmark_return_pct", "excess_return_pct", "benchmark_missing", "outcome_scored_at",
    } <= cols, "the race on one column must not stop the rest of the batch from migrating"
    assert result is True
    assert sleeps["n"] <= max(1, int(FETCH.max_retries)), "the retry must stay bounded by config.FETCH, not spin"


def test_migrate_outcome_columns_returns_false_on_a_fully_locked_database(monkeypatch):
    """Every ALTER and the PRAGMA re-reads all fail (database genuinely
    locked for the whole window) — ``_migrate_outcome_columns`` must return
    False, never raise out of ``__init__`` and crash the import-time
    singleton.
    """
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE synthetic_recommendation ("
        "id INTEGER PRIMARY KEY, symbol TEXT, as_of TEXT, piotroski_score INTEGER, source TEXT)"
    )
    conn.commit()

    store = SyntheticBacktestStore.__new__(SyntheticBacktestStore)
    store._engine = create_engine("sqlite://", creator=lambda: conn)

    def _always_locked(engine, column, col_def):
        raise OperationalError("ALTER TABLE ...", {}, RuntimeError("database is locked"))

    def _read_also_locked(engine):
        raise OperationalError("PRAGMA table_info ...", {}, RuntimeError("database is locked"))

    monkeypatch.setattr(store, "_add_outcome_column", _always_locked)
    monkeypatch.setattr(store, "_migrated_columns", _read_also_locked)
    monkeypatch.setattr("analysis.synthetic_backtest.time.sleep", lambda *_: None)

    result = store._migrate_outcome_columns(store._engine)  # must not raise
    assert result is False, "a database this locked cannot be confirmed migrated"


def test_migrate_outcome_columns_returns_true_once_every_column_is_confirmed_present():
    """``outcome_columns_verified`` (``__init__``) mirrors
    ``unique_index_verified`` precisely so a future writer (PR 6/N) has a
    flag to check instead of grepping logs for an import-time failure.
    """
    store = SyntheticBacktestStore(":memory:")
    assert store.outcome_columns_verified is True


def test_migrate_outcome_columns_returns_false_when_a_column_permanently_fails_to_add(monkeypatch):
    """A genuinely non-recoverable failure (not a lock, not a concurrent
    add — e.g. a read-only mount) must be visible on the return value, not
    just in a log line nobody may be watching at import time.
    """
    import sqlite3

    from sqlalchemy import create_engine

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE synthetic_recommendation ("
        "id INTEGER PRIMARY KEY, symbol TEXT, as_of TEXT, piotroski_score INTEGER, source TEXT)"
    )
    conn.commit()

    store = SyntheticBacktestStore.__new__(SyntheticBacktestStore)
    store._engine = create_engine("sqlite://", creator=lambda: conn)

    def _boom(engine, column, col_def):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(store, "_add_outcome_column", _boom)

    result = store._migrate_outcome_columns(store._engine)

    assert result is False


def test_migrate_outcome_columns_prunes_already_present_columns_after_a_failed_upfront_read(monkeypatch, caplog):
    """A transient lock on the *up-front* PRAGMA read of an already-migrated
    DB makes `existing` fall back to empty, so every ADD COLUMN then fails
    with "duplicate column name". A cheap re-read before the first backoff
    must prune those so the batch neither burns its retry budget (import-time
    sleeps) nor logs a false "still not added" ERROR.
    """
    import sqlite3

    from sqlalchemy import create_engine

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE synthetic_recommendation ("
        "id INTEGER PRIMARY KEY, symbol TEXT, as_of TEXT, piotroski_score INTEGER, source TEXT, "
        "price_at_cutoff FLOAT, price_at_horizon FLOAT, horizon_date VARCHAR, return_pct FLOAT, "
        "benchmark_return_pct FLOAT, excess_return_pct FLOAT, benchmark_missing BOOLEAN DEFAULT 0, "
        "outcome_scored_at DATETIME)"
    )
    conn.commit()

    store = SyntheticBacktestStore.__new__(SyntheticBacktestStore)
    store._engine = create_engine("sqlite://", creator=lambda: conn)

    real_migrated_columns = SyntheticBacktestStore._migrated_columns
    reads = {"n": 0}

    def _flaky_read(engine):
        reads["n"] += 1
        if reads["n"] == 1:  # the up-front read is the one that's locked
            raise Exception("database is locked")
        return real_migrated_columns(engine)

    sleeps = {"n": 0}
    monkeypatch.setattr(store, "_migrated_columns", _flaky_read)
    monkeypatch.setattr(
        "analysis.synthetic_backtest.time.sleep",
        lambda *_: sleeps.__setitem__("n", sleeps["n"] + 1),
    )

    with caplog.at_level("ERROR"):
        result = store._migrate_outcome_columns(store._engine)

    assert result is True
    assert sleeps["n"] == 0, "a stale up-front read must not cost the retry budget's sleeps"
    assert "still not added" not in caplog.text, "a benign 'already exists' race is not a failure"


def test_get_all_filters_by_symbol():
    store = SyntheticBacktestStore(":memory:")
    store.log_piotroski("AAPL", date(2021, 6, 1), _detail(5))
    store.log_piotroski("MSFT", date(2021, 6, 1), _detail(3))

    aapl_rows = store.get_all(symbol="AAPL")
    assert len(aapl_rows) == 1
    assert aapl_rows[0].symbol == "AAPL"


def test_get_all_orders_by_as_of():
    store = SyntheticBacktestStore(":memory:")
    store.log_piotroski("AAPL", date(2021, 6, 1), _detail(5))
    store.log_piotroski("AAPL", date(2020, 6, 1), _detail(4))

    rows = store.get_all(symbol="AAPL")
    assert [r.as_of for r in rows] == ["2020-06-01", "2021-06-01"]


def test_two_stores_do_not_share_state():
    """Two ``:memory:`` stores are two separate SQLite databases — the same
    guarantee ``TrackRecordStore(":memory:")`` already gives, verified here
    for the new class since nothing else does yet.
    """
    a = SyntheticBacktestStore(":memory:")
    b = SyntheticBacktestStore(":memory:")
    a.log_piotroski("AAPL", date(2021, 6, 1), _detail(9))

    assert b.get_all() == []


def test_synthetic_recommendation_table_name_is_separate_from_track_record():
    """Structural guard against ever merging this back into recommendation_log."""
    assert SyntheticRecommendation.__tablename__ == "synthetic_recommendation"


def test_symbol_is_upper_cased_so_get_all_can_find_it():
    """A lowercase/mixed-case symbol must still be findable by an upper-case
    query — same convention as ``RecommendationLog`` (``analysis/track_record.py``),
    and the same exact-match ``==`` filter ``get_all`` uses would otherwise
    silently drop the row from any aggregation.
    """
    store = SyntheticBacktestStore(":memory:")
    store.log_piotroski("aapl", date(2021, 6, 1), _detail(5))

    rows = store.get_all(symbol="AAPL")
    assert len(rows) == 1
    assert rows[0].symbol == "AAPL"


def test_log_piotroski_never_raises_on_a_write_failure(monkeypatch):
    """A future batch backtest loops over the universe × many historical
    cutoffs — hundreds or thousands of calls. One transient sqlite error must
    skip that row, not abort the whole run, same as
    ``TrackRecordStore.log_recommendation``'s defensive ``except Exception``.
    """
    store = SyntheticBacktestStore(":memory:")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(store, "_Session", _boom)

    result = store.log_piotroski("AAPL", date(2021, 6, 1), _detail(5))

    assert result is None


def test_existing_pairs_returns_the_logged_as_of_dates():
    """The batch backtest script's resumability check (PR 4/N): what a run
    already has for a symbol, without touching the network.
    """
    store = SyntheticBacktestStore(":memory:")
    store.log_piotroski("AAPL", date(2020, 6, 1), _detail(5))
    store.log_piotroski("AAPL", date(2021, 6, 1), _detail(6))
    store.log_piotroski("MSFT", date(2021, 6, 1), _detail(3))

    assert store.existing_pairs("AAPL") == {"2020-06-01", "2021-06-01"}
    assert store.existing_pairs("MSFT") == {"2021-06-01"}
    assert store.existing_pairs("JNJ") == set()


def test_existing_pairs_never_raises_on_a_read_failure(monkeypatch):
    """A batch run calls this once per symbol in its universe — a transient
    sqlite error (lock contention with a concurrently-writing dashboard or
    scheduler on the same DB_PATH file) must not crash the whole run, same
    as ``log_piotroski``'s own defensive ``except Exception``. An empty
    result is the safe direction: the caller re-fetches and re-scores that
    symbol, and the unique index catches any pair that genuinely already
    exists rather than losing it silently.
    """
    store = SyntheticBacktestStore(":memory:")
    store.log_piotroski("AAPL", date(2021, 6, 1), _detail(5))

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated read failure")

    monkeypatch.setattr(store, "_Session", _boom)

    assert store.existing_pairs("AAPL") == set()


def test_unique_index_verified_is_true_on_a_healthy_store():
    store = SyntheticBacktestStore(":memory:")
    assert store.unique_index_verified is True


def test_unique_index_verified_is_false_when_duplicate_data_predates_the_constraint():
    """The scenario the migration exists to guard against: a database that
    already has two rows for the same (symbol, as_of, source) — written
    before this constraint existed — must not silently claim to be protected.
    """
    import sqlite3

    from sqlalchemy import create_engine

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE synthetic_recommendation ("
        "id INTEGER PRIMARY KEY, symbol TEXT, as_of TEXT, piotroski_score INTEGER, source TEXT)"
    )
    conn.executemany(
        "INSERT INTO synthetic_recommendation (symbol, as_of, piotroski_score, source) VALUES (?, ?, ?, ?)",
        [("AAPL", "2021-06-01", 5, "point_in_time_piotroski"),
         ("AAPL", "2021-06-01", 9, "point_in_time_piotroski")],  # pre-existing duplicate
    )
    conn.commit()

    store = SyntheticBacktestStore.__new__(SyntheticBacktestStore)
    store._engine = create_engine("sqlite://", creator=lambda: conn)
    verified = store._migrate(store._engine)

    assert verified is False


def test_migrate_retries_a_transient_lock_and_still_succeeds(monkeypatch):
    """A concurrently-writing dashboard or scheduler on the same DB_PATH file
    can make CREATE UNIQUE INDEX raise a transient "database is locked"
    error — this must be retried, not treated the same as real duplicate
    data (which retrying would never fix).
    """
    from sqlalchemy.exc import OperationalError

    store = SyntheticBacktestStore(":memory:")  # already migrated once by __init__
    real_create = SyntheticBacktestStore._create_unique_index
    calls = {"n": 0}

    def _flaky_create(engine):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("CREATE UNIQUE INDEX ...", {}, RuntimeError("database is locked"))
        return real_create(engine)

    monkeypatch.setattr(store, "_create_unique_index", _flaky_create)
    monkeypatch.setattr("analysis.synthetic_backtest.time.sleep", lambda *_: None)

    verified = store._migrate(store._engine)

    assert verified is True
    assert calls["n"] == 2, "must retry exactly once after the transient failure, then succeed"


def test_migrate_gives_up_after_repeated_lock_failures(monkeypatch):
    """If the lock never clears within the retry budget, the migration must
    still fail loudly (``unique_index_verified = False``) rather than hang
    or silently claim success.
    """
    from sqlalchemy.exc import OperationalError

    store = SyntheticBacktestStore(":memory:")

    def _always_locked(engine):
        raise OperationalError("CREATE UNIQUE INDEX ...", {}, RuntimeError("database is locked"))

    monkeypatch.setattr(store, "_create_unique_index", _always_locked)
    monkeypatch.setattr("analysis.synthetic_backtest.time.sleep", lambda *_: None)

    verified = store._migrate(store._engine)

    assert verified is False


def test_duplicate_symbol_as_of_source_is_rejected_not_silently_duplicated():
    """The unique constraint (symbol, as_of, source) is what makes the table
    itself a safe resumability checkpoint — a caller that races or re-runs
    without checking ``existing_pairs`` first must not end up with two rows
    for the same ticker×cutoff silently inflating the calibration sample.

    The rejection returns ``ALREADY_LOGGED``, not ``None`` — a caller (the
    batch backtest script) needs to tell "this exact pair already existed"
    (not a failure) apart from "the write genuinely broke" (a real failure
    that should count toward main()'s exit code).
    """
    store = SyntheticBacktestStore(":memory:")
    first_id = store.log_piotroski("AAPL", date(2021, 6, 1), _detail(5))
    assert first_id is not None

    second_id = store.log_piotroski("AAPL", date(2021, 6, 1), _detail(9))
    assert second_id is ALREADY_LOGGED   # rejected by the unique constraint, logged, not raised

    rows = store.get_all(symbol="AAPL")
    assert len(rows) == 1
    assert rows[0].piotroski_score == 5   # the first write survives untouched
