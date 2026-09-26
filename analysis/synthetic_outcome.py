"""
Outcome of the point-in-time backtest at one year (PIT-1).

``analysis/synthetic_backtest.py`` stores Piotroski F-Scores reconstructed at
past cutoffs. This module measures what happened next: the ticker's return
from the cutoff to one year later, the benchmark's over the same dates, and
the excess — the evidence U5-1b needs to recalibrate the Piotroski bonus, and
that the live track record will not have at one year for another year.

Scope decided by the user (2026-09-26):

- a ticker delisted before the horizon keeps a NULL outcome **and a mark**
  (``OUTCOME_DELISTED``) — not dropped, so the sample is not survivors-only;
- the benchmark is ``TRACK_RECORD.benchmark`` on ``get_history``'s adjusted
  close (``auto_adjust=True``, so dividends are in: total return);
- a cutoff less than a year old stays pending — nothing is estimated.

Why this module has its own price lookup instead of reusing
``track_record_scorer._price_on_or_before``: that one returns the last close at
or before a date **however old it is**. Over a 30-day horizon on names that
trade today that rarely matters; over a year, across cutoffs years back, a
delisted ticker would be "priced" at the horizon with its last close from
months before — an outcome that looks measured and isn't, on exactly the rows
the user decided to keep. ``price_near`` refuses a close older than
``SYNTHETIC_BACKTEST.max_price_staleness_days``. The same latent gap in the
track record is BACKLOG ``TR-STALE-PRICE``.

It also must not import ``analysis.track_record`` (directly or through the
scorer): the synthetic table is kept out of the published hit rate
structurally, not by a filter (see ``analysis/synthetic_backtest.py``, N6).

Network access is isolated in ``_history`` so the scoring is testable with
injected frames.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Dict, Optional

import pandas as pd
from loguru import logger

from analysis.synthetic_backtest import (
    OUTCOME_DELISTED,
    OUTCOME_NO_HISTORY,
    OUTCOME_NO_PRICE,
    OUTCOME_PARTIAL,
    OUTCOME_SCORED,
    synthetic_backtest_store,
)
from config import SYNTHETIC_BACKTEST, TRACK_RECORD
from data.clock import utc_now

#: symbol -> daily price history in ``get_history``'s shape (empty if none).
HistoryFn = Callable[[str], pd.DataFrame]


def _history(symbol: str) -> pd.DataFrame:
    """Daily adjusted history, the same call the track record scorer makes."""
    try:
        from data.fetcher import get_history

        df = get_history(symbol, period="max", interval="1d")
        return df if df is not None else pd.DataFrame()
    except Exception as exc:
        logger.warning(f"synthetic_outcome: history failed for {symbol} — {exc}")
        return pd.DataFrame()


def _closes(frame: pd.DataFrame) -> pd.Series:
    """The close series indexed by day, whatever shape the cache returned."""
    if frame is None or frame.empty or "close" not in frame.columns:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    df = frame
    if "date" in df.columns:  # same guard as track_record_scorer: cold vs warm cache shape
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


def _ends_before(frame: pd.DataFrame, when: date, max_stale_days: int) -> bool:
    """Whether the history stops more than ``max_stale_days`` before ``when``."""
    closes = _closes(frame)
    return not closes.empty and (pd.Timestamp(when) - closes.index[-1]).days > max_stale_days


def _pct(end: float, start: float) -> float:
    return round((end / start - 1.0) * 100.0, 4)


def score_due_outcomes(
    store=None,
    *,
    today: Optional[date] = None,
    history: Optional[HistoryFn] = None,
) -> Dict[str, int]:
    """Measure the one-year outcome of every synthetic row whose horizon has
    passed and that is not final yet.

    A row is due when ``as_of + horizon_days`` is **strictly before** ``today``:
    on the horizon day itself that day's close does not exist yet, and using
    the previous one would measure a shorter year.

    Returns disjoint counts: ``scored``, ``partial`` (benchmark missing),
    ``delisted``, ``no_price``, ``no_history``, and ``pending`` (not due yet).
    """
    store = store or synthetic_backtest_store
    today = today or utc_now().date()
    history = history or _history
    horizon = timedelta(days=int(SYNTHETIC_BACKTEST.horizon_days))
    stale = int(SYNTHETIC_BACKTEST.max_price_staleness_days)
    benchmark = TRACK_RECORD.benchmark

    counts = {"scored": 0, "partial": 0, "delisted": 0, "no_price": 0, "no_history": 0, "pending": 0}
    frames: Dict[str, pd.DataFrame] = {}

    def frame_of(symbol: str) -> pd.DataFrame:
        if symbol not in frames:
            frames[symbol] = history(symbol)
        return frames[symbol]

    for row in store.get_unscored():
        cutoff = date.fromisoformat(row.as_of)
        horizon_date = cutoff + horizon
        if horizon_date >= today:
            counts["pending"] += 1
            continue

        frame = frame_of(row.symbol)
        if frame is None or frame.empty:
            store.save_outcome(row.id, outcome_status=OUTCOME_NO_HISTORY)
            counts["no_history"] += 1
            continue

        p0 = price_near(frame, cutoff, stale)
        p1 = price_near(frame, horizon_date, stale)
        if p0 is not None and p1 is None and _ends_before(frame, horizon_date, stale):
            store.save_outcome(
                row.id,
                price_at_cutoff=round(p0, 4),
                horizon_date=horizon_date.isoformat(),
                outcome_status=OUTCOME_DELISTED,
            )
            counts["delisted"] += 1
            continue
        if p0 is None or p1 is None:
            store.save_outcome(row.id, outcome_status=OUTCOME_NO_PRICE)
            counts["no_price"] += 1
            continue

        return_pct = _pct(p1, p0)
        bench = frame_of(benchmark)
        b0 = price_near(bench, cutoff, stale)
        b1 = price_near(bench, horizon_date, stale)
        missing = b0 is None or b1 is None
        bench_pct = None if missing else _pct(b1, b0)

        store.save_outcome(
            row.id,
            price_at_cutoff=round(p0, 4),
            price_at_horizon=round(p1, 4),
            horizon_date=horizon_date.isoformat(),
            return_pct=return_pct,
            benchmark_return_pct=bench_pct,
            excess_return_pct=None if missing else round(return_pct - bench_pct, 4),
            benchmark_missing=missing,
            outcome_scored_at=None if missing else utc_now(),
            outcome_status=OUTCOME_PARTIAL if missing else OUTCOME_SCORED,
        )
        if missing:
            logger.warning(
                f"synthetic_outcome: no benchmark ({benchmark}) for {row.symbol} "
                f"{cutoff} → {horizon_date} — saved without excess, will retry"
            )
            counts["partial"] += 1
        else:
            counts["scored"] += 1

    logger.info("synthetic_outcome: " + " ".join(f"{k}={v}" for k, v in counts.items()))
    return counts
