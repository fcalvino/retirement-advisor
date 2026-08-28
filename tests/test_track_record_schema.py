"""The track record stores what calibration needs, and the migration keeps the data.

Three open questions have been deferred to empirical evidence: where to cut the
decision thresholds, which capital ratio separates a solid bank from a fragile one,
and what leverage is normal for a regulated utility. All three are answered by
grouping past recommendations by the metric that drove them — and none of that was
being stored. The log kept a single ``fundamental_score`` and nothing else, so the
industry questions could not be answered from it at any sample size.

That gap was the one that could not wait. A recommendation's metrics cannot be
reconstructed once prices and statements have moved on, so every day without these
columns produced evidence born unusable.

Two things are pinned here. First, the **migration**: ``create_all`` creates missing
tables but never touches an existing one, so on a database created before these
columns — which is every real one — they simply would not appear. Second, the
**capture contract**: the store's older promise is that a logging failure never
breaks the analysis it hangs off, and adding fields must not weaken it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from analysis.track_record import TrackRecordStore, calibration_fields

# --------------------------------------------------------------------------- #
#  The pre-migration schema, verbatim                                         #
# --------------------------------------------------------------------------- #

_OLD_SCHEMA = """
CREATE TABLE recommendation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR NOT NULL,
    action VARCHAR NOT NULL,
    confidence VARCHAR,
    fundamental_score FLOAT,
    technical_signal VARCHAR,
    source VARCHAR,
    price_at_rec FLOAT,
    rationale TEXT,
    plan_id VARCHAR,
    created_at DATETIME
)
"""

_NEW_COLUMNS = (
    "sector", "industry", "profitability_score", "health_score",
    "valuation_score", "growth_score", "dividend_score", "metrics_json",
)


@pytest.fixture()
def legacy_db(tmp_path):
    """A database as it exists today: old schema, real rows in it."""
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        conn.execute(text(_OLD_SCHEMA))
        conn.execute(text(
            "INSERT INTO recommendation_log "
            "(symbol, action, confidence, fundamental_score, source, created_at) "
            "VALUES ('KO', 'BUY', 'HIGH', 72.5, 'rule_based', '2026-06-16 10:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO recommendation_log "
            "(symbol, action, confidence, fundamental_score, source, created_at) "
            "VALUES ('JNJ', 'HOLD', 'MEDIUM', 61.0, 'ai', '2026-06-19 10:00:00')"
        ))
        conn.commit()
    engine.dispose()
    return path


def _columns(path) -> set:
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(recommendation_log)")).fetchall()
    engine.dispose()
    return {r[1] for r in rows}


def _row_count(path) -> int:
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM recommendation_log")).scalar()
    engine.dispose()
    return int(n)


# --------------------------------------------------------------------------- #
#  Migration                                                                  #
# --------------------------------------------------------------------------- #

class TestMigration:
    def test_old_database_gains_the_columns(self, legacy_db):
        assert not (_columns(legacy_db) & set(_NEW_COLUMNS))
        TrackRecordStore(db_path=str(legacy_db))
        assert set(_NEW_COLUMNS) <= _columns(legacy_db)

    def test_existing_rows_survive(self, legacy_db):
        """The only way this change can destroy anything."""
        assert _row_count(legacy_db) == 2
        TrackRecordStore(db_path=str(legacy_db))
        assert _row_count(legacy_db) == 2

        store = TrackRecordStore(db_path=str(legacy_db))
        recs = store.get_recommendations(limit=10)
        assert {r.symbol for r in recs} == {"KO", "JNJ"}
        assert next(r for r in recs if r.symbol == "KO").fundamental_score == 72.5

    def test_old_rows_read_back_with_empty_new_fields(self, legacy_db):
        store = TrackRecordStore(db_path=str(legacy_db))
        rec = next(r for r in store.get_recommendations(limit=10) if r.symbol == "KO")
        assert rec.sector in (None, "")
        assert rec.health_score is None

    def test_migration_is_idempotent(self, legacy_db):
        TrackRecordStore(db_path=str(legacy_db))
        TrackRecordStore(db_path=str(legacy_db))
        TrackRecordStore(db_path=str(legacy_db))
        assert _row_count(legacy_db) == 2
        assert set(_NEW_COLUMNS) <= _columns(legacy_db)

    def test_a_fresh_database_has_them_from_the_start(self, tmp_path):
        path = tmp_path / "fresh.db"
        TrackRecordStore(db_path=str(path))
        assert set(_NEW_COLUMNS) <= _columns(path)


# --------------------------------------------------------------------------- #
#  What gets extracted                                                        #
# --------------------------------------------------------------------------- #

def _fundamental(**overrides):
    base = dict(
        sector="Real Estate",
        industry="REIT - Retail",
        profitability_score=12.0,
        health_score=6.0,
        valuation_score=8.0,
        growth_score=10.0,
        dividend_score=9.0,
        debt_equity=1.35,
        p_ffo=16.5,
        ffo_payout_pct=70.2,
        roe=8.4,
        roic=5.1,
        moat_score=11.0,
        negative_equity=False,
        equity_to_assets_pct=41.2,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestCalibrationFields:
    def test_none_yields_nothing(self):
        assert calibration_fields(None) == {}

    def test_dimensions_and_sector_become_columns(self):
        fields = calibration_fields(_fundamental())
        assert fields["sector"] == "Real Estate"
        assert fields["industry"] == "REIT - Retail"
        assert fields["health_score"] == 6.0
        assert fields["dividend_score"] == 9.0

    def test_industry_metrics_go_to_json(self):
        metrics = json.loads(calibration_fields(_fundamental())["metrics_json"])
        assert metrics["p_ffo"] == 16.5
        assert metrics["ffo_payout_pct"] == 70.2
        assert metrics["equity_to_assets_pct"] == 41.2
        assert metrics["negative_equity"] is False

    def test_the_bank_ratio_is_captured(self):
        """The one metric that is genuinely unrecoverable after the fact."""
        bank = _fundamental(sector="Financial Services", industry="Banks - Diversified",
                            equity_to_assets_pct=8.2, p_ffo=None, ffo_payout_pct=None)
        metrics = json.loads(calibration_fields(bank)["metrics_json"])
        assert metrics["equity_to_assets_pct"] == 8.2

    def test_absent_attributes_are_simply_skipped(self):
        sparse = SimpleNamespace(sector="Technology")
        fields = calibration_fields(sparse)
        assert fields == {"sector": "Technology"}

    def test_none_values_do_not_reach_the_json(self):
        fields = calibration_fields(_fundamental(p_ffo=None, roic=None))
        metrics = json.loads(fields["metrics_json"])
        assert "p_ffo" not in metrics
        assert "roic" not in metrics


# --------------------------------------------------------------------------- #
#  The capture contract                                                       #
# --------------------------------------------------------------------------- #

def _decision(symbol="O", action="BUY"):
    return SimpleNamespace(
        symbol=symbol, action=action, confidence="HIGH",
        fundamental_score=68.0, technical_signal="BULLISH",
        rationale=["motivo uno", "motivo dos"],
    )


class TestLogging:
    def test_fundamental_is_persisted(self, tmp_path):
        store = TrackRecordStore(db_path=str(tmp_path / "t.db"))
        rec_id = store.log_recommendation(_decision(), fundamental=_fundamental())
        assert rec_id is not None

        rec = store.get_recommendations(limit=1)[0]
        assert rec.sector == "Real Estate"
        assert rec.valuation_score == 8.0
        assert json.loads(rec.metrics_json)["p_ffo"] == 16.5

    def test_without_fundamental_it_behaves_as_before(self, tmp_path):
        store = TrackRecordStore(db_path=str(tmp_path / "t.db"))
        assert store.log_recommendation(_decision()) is not None

        rec = store.get_recommendations(limit=1)[0]
        assert rec.symbol == "O"
        assert rec.fundamental_score == 68.0
        assert rec.sector in (None, "")

    def test_a_broken_fundamental_still_logs_the_recommendation(self, tmp_path):
        """The older promise holds: capture never breaks the caller."""
        class Hostile:
            def __getattr__(self, name):
                raise RuntimeError("boom")

        store = TrackRecordStore(db_path=str(tmp_path / "t.db"))
        rec_id = store.log_recommendation(_decision(), fundamental=Hostile())
        assert rec_id is not None
        assert store.get_recommendations(limit=1)[0].symbol == "O"
