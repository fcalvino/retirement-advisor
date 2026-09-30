"""Oracle tests for the Track Record over tickers quoted in another currency (#154, PR D).

Until this PR the store refused every quote outside ``TRACK_RECORD.benchmark_currency``
(LLM-2): its excess over SPY would have measured the exchange rate, not the call. So 90
of the 126 tickers of ``global_quality`` never left any evidence. With the conversion of
``data/fx.py`` the scorer grades a Tokyo listing in dollars — the return a dollar
investor got — and the gate on currency goes away. The other two LLM-2 gates (ticker
shape, empty feed) stay.

References from the definition: price in USD = local price × USD per unit, at both
ends of the horizon. A Toyota flat at 3000 JPY while JPYUSD goes 0.0064 → 0.0070
returned (3000·0.0070)/(3000·0.0064) − 1 = +9.375 % to a dollar investor.

Real SQLite stores (project convention); prices and FX are injected, so no network.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

import data.fx as fx_mod
from analysis.track_record import (
    RecommendationLog,
    TrackRecordStore,
    admission_skip_reason,
)
from analysis.track_record_scorer import score_due_recommendations
from config import PORTFOLIO, TRACK_RECORD
from data.clock import utc_now


@pytest.fixture
def store(tmp_path):
    return TrackRecordStore(db_path=str(tmp_path / "tr.db"))


def _decision(symbol, action="BUY"):
    return SimpleNamespace(symbol=symbol, action=action, confidence="MEDIUM",
                           fundamental_score=80.0, technical_signal="BULLISH",
                           rationale=["oráculo #154 D"])


def _fund(currency, price=100.0):
    return SimpleNamespace(currency=currency, current_price=price,
                           data_quality={"level": "good"})


def _log_due(store, symbol, currency, price_at_rec, *, action="BUY", days_ago=40):
    rid = store.log_recommendation(_decision(symbol, action), price_at_rec=price_at_rec,
                                   fundamental=_fund(currency) if currency is not None else None)
    assert rid is not None
    created = utc_now() - timedelta(days=days_ago)
    with store._Session() as s:  # noqa: SLF001 - test introspection
        s.get(RecommendationLog, rid).created_at = created
        s.commit()
    return rid, created


def _table(entries):
    def lookup(key, when):
        return entries.get((key, when.date()))
    return lookup


def _row(store, rid, horizon=30):
    return next(r for r in store.get_scored_rows(horizon) if r["rec_id"] == rid)


# --------------------------------------------------------------------------- #
#  Admission and what the log keeps                                            #
# --------------------------------------------------------------------------- #


class TestAdmission:
    def test_a_yen_quote_is_admitted(self):
        assert admission_skip_reason("7203.T", _fund("JPY")) is None

    def test_the_other_llm2_gates_stay(self):
        assert admission_skip_reason("BTC-USD — BITCOIN", _fund("USD")) is not None
        empty = SimpleNamespace(currency="EUR", current_price=None,
                                data_quality={"level": "poor"})
        assert admission_skip_reason("NODATA.DE", empty) is not None

    def test_the_currency_is_stored_with_the_row(self, store):
        rid = store.log_recommendation(_decision("7203.T"), price_at_rec=3000.0,
                                       fundamental=_fund("JPY"))
        rid2 = store.log_recommendation(_decision("AAPL"), price_at_rec=200.0, fundamental=None)
        with store._Session() as s:  # noqa: SLF001
            assert s.get(RecommendationLog, rid).currency == "JPY"
            assert s.get(RecommendationLog, rid2).currency == ""

    def test_a_database_created_before_the_column_gains_it(self, tmp_path):
        path = tmp_path / "old.db"
        eng = create_engine(f"sqlite:///{path}")
        with eng.connect() as c:
            c.execute(text("CREATE TABLE recommendation_log (id INTEGER PRIMARY KEY, "
                           "symbol VARCHAR NOT NULL, action VARCHAR NOT NULL, created_at DATETIME)"))
            c.execute(text("INSERT INTO recommendation_log (symbol, action) VALUES ('AAPL','BUY')"))
            c.commit()
        TrackRecordStore(db_path=str(path))
        with eng.connect() as c:
            cols = [r[1] for r in c.execute(text("PRAGMA table_info(recommendation_log)"))]
            assert "currency" in cols
            assert c.execute(text("SELECT currency FROM recommendation_log")).scalar() == ""

    def test_the_benchmark_is_in_the_portfolio_currency(self):
        """The rate converts to PORTFOLIO.base_currency and the excess is taken over the
        benchmark: if the two diverge, the excess mixes currencies again."""
        assert TRACK_RECORD.benchmark_currency == PORTFOLIO.base_currency


# --------------------------------------------------------------------------- #
#  Scoring in dollars                                                          #
# --------------------------------------------------------------------------- #


class TestScoringInDollars:
    def test_flat_in_yen_with_the_yen_up_is_graded_in_dollars(self, store):
        rid, created = _log_due(store, "7203.T", "JPY", 3000.0)
        h = created + timedelta(days=30)
        prices = _table({("7203.T", h.date()): 3000.0,
                         ("SPY", created.date()): 500.0, ("SPY", h.date()): 510.0})
        fx = _table({("JPY", created.date()): 0.0064, ("JPY", h.date()): 0.0070})
        res = score_due_recommendations(store, price_lookup=prices, fx_lookup=fx)
        assert res == {"scored": 1, "partial": 0, "skipped": 0}
        row = _row(store, rid)
        expected = ((3000 * 0.0070) / (3000 * 0.0064) - 1) * 100      # +9.375
        assert row["return_pct"] == pytest.approx(expected, abs=1e-3)
        assert row["excess_return_pct"] == pytest.approx(expected - 2.0, abs=1e-3)
        assert row["hit"] is True           # a local-currency grade said 0 % vs +2 %: a miss
        assert row["currency"] == "JPY"

    def test_the_price_at_horizon_stays_in_the_quote_currency(self, store):
        rid, created = _log_due(store, "7203.T", "JPY", 3000.0)
        h = created + timedelta(days=30)
        prices = _table({("7203.T", h.date()): 3150.0,
                         ("SPY", created.date()): 500.0, ("SPY", h.date()): 500.0})
        fx = _table({("JPY", created.date()): 0.0064, ("JPY", h.date()): 0.0064})
        score_due_recommendations(store, price_lookup=prices, fx_lookup=fx)
        with store._Session() as s:  # noqa: SLF001
            from analysis.track_record import RecommendationOutcome
            out = s.query(RecommendationOutcome).filter_by(rec_id=rid).one()
            assert out.price_at_horizon == pytest.approx(3150.0)   # auditable against the feed
            assert out.return_pct == pytest.approx(5.0, abs=1e-3)  # same rate: local = USD

    def test_pence_cancel_and_the_pound_is_what_counts(self, store):
        rid, created = _log_due(store, "SHEL.L", "GBp", 2600.0)
        h = created + timedelta(days=30)
        prices = _table({("SHEL.L", h.date()): 2600.0,
                         ("SPY", created.date()): 500.0, ("SPY", h.date()): 500.0})
        fx = _table({("GBp", created.date()): 0.0130, ("GBp", h.date()): 0.0117})
        score_due_recommendations(store, price_lookup=prices, fx_lookup=fx)
        assert _row(store, rid)["return_pct"] == pytest.approx(-10.0, abs=1e-3)

    def test_a_missing_rate_is_skipped_and_stays_pending_never_graded_as_dollars(self, store):
        rid, created = _log_due(store, "7203.T", "JPY", 3000.0)
        h = created + timedelta(days=30)
        prices = _table({("7203.T", h.date()): 3300.0,
                         ("SPY", created.date()): 500.0, ("SPY", h.date()): 500.0})
        fx = _table({("JPY", created.date()): 0.0064})                   # no rate at horizon
        res = score_due_recommendations(store, price_lookup=prices, fx_lookup=fx)
        assert res == {"scored": 0, "partial": 0, "skipped": 1}
        assert store.get_scored_rows(30) == []
        assert [r.id for r in store.get_pending_scoring(30)] == [rid]


class TestRowsWithoutACurrency:
    def test_a_us_listing_is_scored_exactly_as_before_without_any_rate(self, store):
        rid, created = _log_due(store, "AAPL", None, 200.0)
        h = created + timedelta(days=30)
        prices = _table({("AAPL", h.date()): 220.0,
                         ("SPY", created.date()): 500.0, ("SPY", h.date()): 505.0})

        def no_fx(currency, when):
            raise AssertionError("una fila en dólares no busca tipo de cambio")

        score_due_recommendations(store, price_lookup=prices, fx_lookup=no_fx)
        row = _row(store, rid)
        assert row["return_pct"] == pytest.approx(10.0, abs=1e-6)
        assert row["excess_return_pct"] == pytest.approx(9.0, abs=1e-6)

    def test_a_suffixed_symbol_without_currency_is_resolved_from_the_feed(
        self, store, monkeypatch
    ):
        monkeypatch.setattr(fx_mod, "get_info", lambda s: {"currency": "EUR"})
        rid, created = _log_due(store, "SAP.DE", None, 200.0)
        h = created + timedelta(days=30)
        prices = _table({("SAP.DE", h.date()): 200.0,
                         ("SPY", created.date()): 500.0, ("SPY", h.date()): 500.0})
        fx = _table({("EUR", created.date()): 1.10, ("EUR", h.date()): 1.21})
        score_due_recommendations(store, price_lookup=prices, fx_lookup=fx)
        assert _row(store, rid)["return_pct"] == pytest.approx(10.0, abs=1e-3)

    def test_an_unconfirmable_currency_is_skipped(self, store, monkeypatch):
        monkeypatch.setattr(fx_mod, "get_info", lambda s: {})
        _log_due(store, "SAP.DE", None, 200.0)
        res = score_due_recommendations(
            store, price_lookup=_table({}), fx_lookup=_table({}))
        assert res["skipped"] == 1
        assert store.get_scored_rows(30) == []


# --------------------------------------------------------------------------- #
#  The rate on a date                                                          #
# --------------------------------------------------------------------------- #


def _daily(values, end="2026-09-25"):
    idx = pd.bdate_range(end=end, periods=len(values))
    df = pd.DataFrame({"close": values}, index=idx)
    df.index.name = "Date"
    return df


class TestRateOn:
    def test_base_currency_is_one_and_unknown_is_none(self):
        when = pd.Timestamp("2026-09-25")
        assert fx_mod.rate_on(PORTFOLIO.base_currency, when, 7) == 1.0
        assert fx_mod.rate_on("", when, 7) is None
        assert fx_mod.rate_on(None, when, 7) is None

    def test_reads_the_daily_pair_with_the_staleness_guard(self, monkeypatch):
        calls = []

        def _gh(symbol, period, interval):
            calls.append((symbol, period, interval))
            return _daily([0.0064, 0.0065, 0.0066])

        monkeypatch.setattr(fx_mod, "get_history", _gh)
        assert fx_mod.rate_on("JPY", pd.Timestamp("2026-09-25"), 7) == pytest.approx(0.0066)
        assert calls == [("JPYUSD=X", "max", "1d")]
        # Saturday: carries Friday's close; three weeks later it is stale.
        assert fx_mod.rate_on("JPY", pd.Timestamp("2026-09-26"), 7) == pytest.approx(0.0066)
        assert fx_mod.rate_on("JPY", pd.Timestamp("2026-10-16"), 7) is None

    def test_pence_are_a_hundredth_of_the_pound_rate(self, monkeypatch):
        monkeypatch.setattr(fx_mod, "get_history", lambda s, period, interval: _daily([1.30]))
        assert fx_mod.rate_on("GBp", pd.Timestamp("2026-09-25"), 7) == pytest.approx(0.013)

    def test_a_bad_print_is_not_used_as_the_rate_of_that_day(self, monkeypatch):
        """CLPUSD=X 2016-12-22 = 0.2, the real series around it."""
        clp = [0.001485, 0.001505, 0.001507, 0.2, 0.001507, 0.001484]
        monkeypatch.setattr(fx_mod, "get_history",
                            lambda s, period, interval: _daily(clp, end="2016-12-26"))
        rate = fx_mod.rate_on("CLP", pd.Timestamp("2016-12-22"), 7)
        assert rate == pytest.approx(0.001507)   # the day before, not the 0.2 print
