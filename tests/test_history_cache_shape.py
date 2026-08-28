"""``get_history`` returns one shape, warm or cold (CONTEXT §5).

The defect: the cache stores ``df.reset_index().to_dict(orient="records")`` and the
read path did ``pd.DataFrame(cached)``, so the ``DatetimeIndex`` came back as a plain
``"Date"`` column with a ``RangeIndex`` underneath. A cold call and a warm call
returned **different shapes for the same ticker**, and only the warm one is wrong —
which is why it survived: the first run of anything always works.

What it cost, in order of how quietly it failed:

  * ``track_record_scorer._price_on_or_before`` guards with ``if "date" in
    df.columns`` — lower case, against a column actually named ``"Date"``. On a warm
    cache it therefore skips the reindex, compares integers to a ``Timestamp``,
    raises ``TypeError``, and the surrounding ``except`` turns that into "cannot
    score yet / skip". That scorer fills ``recommendation_outcome``, which has zero
    rows against 57 logged recommendations — the empirical evidence every calibration
    question in this project has been deferred to.
  * ``dashboard/pages/2_Stock_Analysis.py`` plots ``x=hist.index`` and drew bar
    numbers instead of dates whenever the history was cached.
  * ``analysis/backtesting.py`` and ``data/crypto_fetcher.py`` each carry their own
    workaround for it, spelled differently.

There is no oracle here — the correct behaviour is not a formula but an *invariant*:
the two paths agree. The tests are written as round-trips against that invariant, so
they stay true regardless of how the cache serializes.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pandas as pd
import pytest

import data.fetcher as fetcher
from data.fetcher import _restore_date_index

# --------------------------------------------------------------------------- #
#  Shapes                                                                     #
# --------------------------------------------------------------------------- #

def _fresh_frame(n: int = 8) -> pd.DataFrame:
    """What the network path builds: DatetimeIndex named Date, lower-case columns."""
    index = pd.date_range("2026-01-05", periods=n, freq="W")
    index.name = "Date"
    return pd.DataFrame(
        {
            "open": [10.0 + i for i in range(n)],
            "high": [11.0 + i for i in range(n)],
            "low": [9.0 + i for i in range(n)],
            "close": [10.5 + i for i in range(n)],
            "volume": [1000 + 10 * i for i in range(n)],
        },
        index=index,
    )


def _as_cached(df: pd.DataFrame) -> pd.DataFrame:
    """Exactly what the cache round-trip produces: records, then back."""
    records = df.reset_index().to_dict(orient="records")
    # json.dumps(..., default=str) stringifies the Timestamps on the way to SQLite.
    for row in records:
        row["Date"] = str(row["Date"])
    return pd.DataFrame(records)


# --------------------------------------------------------------------------- #
#  The invariant                                                              #
# --------------------------------------------------------------------------- #

class TestWarmAndColdAgree:
    def test_same_index_type_and_name(self):
        cold = _fresh_frame()
        warm = _restore_date_index(_as_cached(cold))

        assert type(warm.index) is type(cold.index)
        assert isinstance(warm.index, pd.DatetimeIndex)
        assert warm.index.name == cold.index.name

    def test_same_columns_in_the_same_order(self):
        cold = _fresh_frame()
        warm = _restore_date_index(_as_cached(cold))
        assert list(warm.columns) == list(cold.columns)

    def test_same_values(self):
        cold = _fresh_frame()
        warm = _restore_date_index(_as_cached(cold))
        pd.testing.assert_frame_equal(warm, cold, check_freq=False)

    def test_the_date_does_not_survive_as_a_column(self):
        warm = _restore_date_index(_as_cached(_fresh_frame()))
        assert not [c for c in warm.columns if str(c).lower() in ("date", "datetime", "index")]


# --------------------------------------------------------------------------- #
#  The consumer that failed silently                                          #
# --------------------------------------------------------------------------- #

def _price_on_or_before(df: pd.DataFrame, when: datetime):
    """Verbatim body of analysis/track_record_scorer._price_on_or_before.

    Copied rather than imported so the test exercises the caller's logic against the
    shape ``get_history`` hands it, without a network fetch. If that function changes,
    this copy going stale is itself a signal worth having.
    """
    try:
        if "date" in df.columns:
            df = df.set_index(pd.to_datetime(df["date"]))
        df = df.sort_index()
        upto = df.loc[df.index <= pd.Timestamp(when)]
        if upto.empty:
            return None
        close = upto.iloc[-1].get("close")
        return float(close) if close and float(close) > 0 else None
    except Exception:
        return None


class TestTrackRecordScorerCanReadPrices:
    def test_the_bug_reproduces_on_the_unrestored_shape(self):
        """Guard the diagnosis: the raw cached frame really does defeat the scorer."""
        raw = _as_cached(_fresh_frame())
        assert _price_on_or_before(raw, datetime(2026, 2, 1)) is None

    def test_the_restored_shape_yields_a_price(self):
        warm = _restore_date_index(_as_cached(_fresh_frame()))
        cold = _fresh_frame()
        when = datetime(2026, 2, 1)

        price = _price_on_or_before(warm, when)
        assert price is not None
        assert price == _price_on_or_before(cold, when)


# --------------------------------------------------------------------------- #
#  Tolerance for what is already on disk                                      #
# --------------------------------------------------------------------------- #

class TestGetHistoryUsesIt:
    """The call site, not just the helper.

    Written after a mutation run caught the gap: reverting ``get_history`` to
    ``pd.DataFrame(cached)`` left every test above green, because they all exercise
    ``_restore_date_index`` directly. A helper nobody calls is not a fix.
    """

    def test_cache_hit_returns_the_fresh_shape(self):
        cold = _fresh_frame()
        records = _as_cached(cold).to_dict(orient="records")

        with patch.object(fetcher.cache, "get", return_value=records):
            warm = fetcher.get_history("TEST", period="10y", interval="1wk")

        assert isinstance(warm.index, pd.DatetimeIndex)
        assert warm.index.name == "Date"
        assert "Date" not in warm.columns
        pd.testing.assert_frame_equal(warm, cold, check_freq=False)

    def test_cache_miss_is_untouched(self):
        """No cached entry ⇒ the network path runs and nothing intercepts it."""
        with (
            patch.object(fetcher.cache, "get", return_value=None),
            patch.object(fetcher, "_fetch_with_retry", return_value=_fresh_frame()) as fetched,
            patch.object(fetcher.cache, "set"),
        ):
            out = fetcher.get_history("TEST", period="10y", interval="1wk")

        assert fetched.called
        assert isinstance(out.index, pd.DatetimeIndex)


class TestBackwardCompatibility:
    @pytest.mark.parametrize("column", ["Date", "date", "Datetime", "index"])
    def test_reads_any_spelling_of_the_date_column(self, column):
        cold = _fresh_frame(4)
        records = cold.reset_index().to_dict(orient="records")
        rows = [{column: str(r.pop("Date")), **r} for r in records]

        warm = _restore_date_index(pd.DataFrame(rows))
        assert isinstance(warm.index, pd.DatetimeIndex)
        assert list(warm["close"]) == list(cold["close"])

    def test_a_frame_with_no_date_column_is_returned_untouched(self):
        df = pd.DataFrame({"close": [1.0, 2.0]})
        out = _restore_date_index(df)
        pd.testing.assert_frame_equal(out, df)

    def test_empty_frame_survives(self):
        assert _restore_date_index(pd.DataFrame()).empty

    def test_unparseable_date_column_does_not_raise(self):
        df = pd.DataFrame({"date": ["no-es-fecha", "tampoco"], "close": [1.0, 2.0]})
        out = _restore_date_index(df)
        assert list(out["close"]) == [1.0, 2.0]

    def test_rows_come_back_in_chronological_order(self):
        cold = _fresh_frame(5)
        shuffled = _as_cached(cold).iloc[::-1].reset_index(drop=True)
        warm = _restore_date_index(shuffled)
        assert list(warm.index) == sorted(warm.index)
