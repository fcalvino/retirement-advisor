"""
Price on a date, with a staleness guard — one implementation for every outcome.

Pure (frames in, floats out). Used by the live track record scorer
(``analysis/track_record_scorer.py``) and by the point-in-time outcome
(``analysis/synthetic_outcome.py``). It must not import ``analysis.track_record``:
the synthetic table is kept out of the published hit rate structurally (N6), so
the helper both share lives outside either one.

Why a guard at all: "the last close at or before a date" with no age limit
prices a ticker that stopped trading in December at its December close in June
— an outcome that looks measured and isn't. PIT-1 closed that for the synthetic
sample; TR-STALE-PRICE closed it for the live one by moving both onto this
function and ``TRACK_RECORD.max_price_staleness_days``.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd


def _closes(frame: pd.DataFrame) -> pd.Series:
    """The close series indexed by day, whatever shape the cache returned."""
    if frame is None or frame.empty or "close" not in frame.columns:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    df = frame
    if "date" in df.columns:  # cold vs warm cache shape (tests/test_history_cache_shape.py)
        df = df.set_index(pd.to_datetime(df["date"]))
    series = pd.to_numeric(df["close"], errors="coerce")
    series.index = pd.to_datetime(series.index).normalize()
    return series.dropna().sort_index()


def price_near(frame: pd.DataFrame, when: date, max_stale_days: int) -> Optional[float]:
    """Close on ``when``, or on the last trading day before it — but only if
    that day is at most ``max_stale_days`` calendar days back. Never a close
    from after ``when``. ``None`` when there is no such close.
    """
    closes = _closes(frame)
    target = pd.Timestamp(when)
    upto = closes[closes.index <= target]
    if upto.empty:
        return None
    if (target - upto.index[-1]).days > max_stale_days:
        return None
    price = float(upto.iloc[-1])
    return price if price > 0 else None
