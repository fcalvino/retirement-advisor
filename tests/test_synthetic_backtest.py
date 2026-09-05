"""Functional tests for analysis/synthetic_backtest.py — always against an
explicit ``:memory:`` store, never the module singleton (which conftest.py
already redirects, but constructing one explicitly here is the documented
convention for any test that needs a real store, per docs/CONTEXT.md §5).
"""

from datetime import date

from analysis.scoring import PiotroskiDetail
from analysis.synthetic_backtest import SyntheticBacktestStore, SyntheticRecommendation


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
