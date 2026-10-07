"""Oráculo EO-6a: el track record guarda la versión del método de señales (ADR 0001).

EO-6b va a cambiar la escalera de señales (tope simétrico, faltantes por la mediana del
sector, atenuación simétrica). Antes de mover la primera señal, cada recomendación
registrada lleva la versión del método con que se decidió, para separar después los
outcomes de una escalera de los de la otra (decisión del usuario, bloque 6 del BACKLOG).

- la versión es propia: no es ``ENGINE_VERSION`` ni ``COMMITTEE.prompt_version``;
- la escribe el único escritor, ``TrackRecordStore.log_recommendation``;
- una base creada antes de la columna la gana sin tocar sus filas: quedan en NULL y se
  rotulan «anterior a EO-6»; no se les inventa versión;
- este PR no mueve ninguna señal ni umbral.

Los esperados están escritos a mano. Salvo la migración, que necesita una base de archivo
con el esquema viejo, todo corre sobre ``TrackRecordStore(":memory:")``. Sin red.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from analysis.track_record import RecommendationLog, RecommendationOutcome, TrackRecordStore
from analysis.track_record_scorer import hit_rate_by_signal_method
from config import (
    COMMITTEE,
    ENGINE_VERSION,
    SIGNAL_METHOD_LEGACY_LABEL,
    SIGNAL_METHOD_VERSION,
    STRATEGY,
)


def _decision(symbol="AAPL", action="BUY"):
    return SimpleNamespace(symbol=symbol, action=action, confidence="MEDIUM",
                           fundamental_score=80.0, technical_signal="BULLISH",
                           rationale=["oráculo EO-6a"])


def _fund():
    return SimpleNamespace(currency="USD", current_price=100.0, data_quality={"level": "good"})


@pytest.fixture
def store():
    return TrackRecordStore(db_path=":memory:")


def test_the_version_is_its_own_not_the_engines_or_the_committees():
    assert SIGNAL_METHOD_VERSION == "2026.10-senales1"
    assert SIGNAL_METHOD_VERSION not in (ENGINE_VERSION, COMMITTEE.prompt_version)
    assert SIGNAL_METHOD_LEGACY_LABEL == "anterior a EO-6"


def test_every_logged_recommendation_carries_the_version(store):
    rid = store.log_recommendation(_decision(), price_at_rec=100.0, fundamental=_fund())
    rid2 = store.log_recommendation(_decision("MSFT", "HOLD"), source="committee",
                                    price_at_rec=300.0, fundamental=_fund())
    with store._Session() as s:  # noqa: SLF001 - test introspection
        assert s.get(RecommendationLog, rid).signal_method_version == SIGNAL_METHOD_VERSION
        assert s.get(RecommendationLog, rid2).signal_method_version == SIGNAL_METHOD_VERSION


def test_a_database_created_before_the_column_gains_it_and_keeps_its_rows_null(tmp_path):
    path = tmp_path / "old.db"
    TrackRecordStore(db_path=str(path))
    eng = create_engine(f"sqlite:///{path}")
    with eng.connect() as c:    # la base como estaba antes de EO-6a
        c.execute(text("ALTER TABLE recommendation_log DROP COLUMN signal_method_version"))
        c.execute(text("INSERT INTO recommendation_log (symbol, action, created_at) "
                       "VALUES ('AAPL', 'BUY', '2026-09-01 12:00:00')"))
        c.commit()
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(recommendation_log)"))]
        assert "signal_method_version" not in cols
    store = TrackRecordStore(db_path=str(path))      # abrir la gana
    with eng.connect() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(recommendation_log)"))]
        assert "signal_method_version" in cols
        assert c.execute(text("SELECT signal_method_version FROM recommendation_log")).scalar() is None
    TrackRecordStore(db_path=str(path))              # reabrir no rompe ni toca nada
    rid = store.log_recommendation(_decision("KO"), price_at_rec=60.0, fundamental=_fund())
    assert rid is not None
    with eng.connect() as c:
        rows = dict(c.execute(text("SELECT symbol, signal_method_version FROM recommendation_log")).all())
    assert rows == {"AAPL": None, "KO": SIGNAL_METHOD_VERSION}


def _score(store, rid, *, hit, horizon=30):
    with store._Session() as s:  # noqa: SLF001
        s.add(RecommendationOutcome(rec_id=rid, horizon_days=horizon, return_pct=1.0,
                                    benchmark_return_pct=0.0, excess_return_pct=1.0, hit=hit))
        s.commit()


def test_scored_rows_expose_the_version(store):
    rid = store.log_recommendation(_decision(), price_at_rec=100.0, fundamental=_fund())
    _score(store, rid, hit=True)
    (row,) = store.get_scored_rows(30)
    assert row["signal_method_version"] == SIGNAL_METHOD_VERSION


def test_hit_rate_by_method_separates_the_two_ladders_by_hand():
    rows = [
        {"hit": True, "signal_method_version": None},               # anterior
        {"hit": False, "signal_method_version": None},              # anterior
        {"hit": True, "signal_method_version": None},               # anterior
        {"hit": True, "signal_method_version": "2026.10-senales1"},
        {"hit": False, "signal_method_version": "2026.10-senales1"},
        {"hit": None, "signal_method_version": "2026.10-senales1"},  # sin calificar: afuera
        {"hit": True, "signal_method_version": "2026.11-senales2"},
    ]
    assert hit_rate_by_signal_method(rows) == {
        "2026.10-senales1": {"n": 2, "hit_rate": 0.5},
        "2026.11-senales2": {"n": 1, "hit_rate": 1.0},
        "anterior a EO-6": {"n": 3, "hit_rate": 0.6667},
    }


def test_no_signal_threshold_moves_in_this_pr():
    """EO-6a es sólo el sello: la escalera sigue como la de antes de EO-6b."""
    assert STRATEGY.ai_action_capped_by_score_ladder is True
