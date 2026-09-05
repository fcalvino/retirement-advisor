"""
Storage for synthetic point-in-time backtest recommendations (PR 3/N, Idea 2).

Third slice of "Backtesting point-in-time" (``docs/DIAGNOSTICO_PROXIMO_NIVEL_2026-09.md``
§2/§4). PR 1 (``analysis/point_in_time.py``) and PR 2
(``analysis/point_in_time_piotroski.py``) reconstruct fundamentals and score
them; neither persists anything. This module is where the resulting scores
*could* be persisted, for a future PR that runs the reconstruction across many
historical cutoffs and measures 1-year outcomes against them.

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

Schema deliberately minimal: just what PR 2's ``PiotroskiDetail`` already
produces. Outcome fields (price at cutoff, price at +1y, excess vs benchmark)
are not added yet — they belong to the PR that actually measures them, added
via the same ``_migrate`` pattern ``analysis/track_record.py`` already uses
for its own "Calibration inputs" columns, not guessed at now.
"""

from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from analysis.scoring import PiotroskiDetail
from config import DB_PATH
from data.clock import utc_now


class _Base(DeclarativeBase):
    pass


class SyntheticRecommendation(_Base):
    """One point-in-time Piotroski F-Score, reconstructed rather than emitted
    to a user — never a row a person actually saw.
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
        self._Session = sessionmaker(bind=self._engine)

    def log_piotroski(
        self,
        symbol: str,
        as_of: date,
        detail: PiotroskiDetail,
        source: str = "point_in_time_piotroski",
    ) -> int:
        """Persist one reconstructed F-Score. Returns the new row's id."""
        with self._Session() as session:
            row = SyntheticRecommendation(
                symbol=symbol,
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

    def get_all(self, symbol: Optional[str] = None) -> List[SyntheticRecommendation]:
        with self._Session() as session:
            query = session.query(SyntheticRecommendation)
            if symbol is not None:
                query = query.filter(SyntheticRecommendation.symbol == symbol)
            return query.order_by(SyntheticRecommendation.as_of).all()


# Module-level singleton (mirrors analysis.track_record.track_record_store)
synthetic_backtest_store = SyntheticBacktestStore()
