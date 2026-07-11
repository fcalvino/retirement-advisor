"""
Track record scorer — deferred outcome scoring + aggregate metrics.

Gran Salto, Fase 1. Reads ``recommendation_log``, and for every recommendation
whose horizon has elapsed and lacks an outcome, computes its return vs a
benchmark and a directional hit, then writes ``recommendation_outcome``.

Pure-function metrics (calibration, equity curve, hit rate) live here too so the
dashboard page is a thin presentation layer and the math is unit-testable.

Conventions: config-driven (``config.TRACK_RECORD``), synchronous, loguru.
Network access is isolated in ``_price_on_or_before`` so the scoring logic can be
tested with injected prices (no yfinance in tests).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import pandas as pd
from loguru import logger

from analysis.track_record import track_record_store
from config import TRACK_RECORD

# A price lookup: (symbol, date) -> price at or just before that date, or None.
PriceLookup = Callable[[str, datetime], Optional[float]]


# --------------------------------------------------------------------------- #
#  Price lookup (the only part that touches the network)                      #
# --------------------------------------------------------------------------- #

def _price_on_or_before(symbol: str, when: datetime) -> Optional[float]:
    """Closing price for ``symbol`` on the last trading day at/just before ``when``.

    Uses the daily-bar history from ``data.fetcher`` (cached). Returns None on
    any failure — callers treat None as "cannot score yet / skip".
    """
    try:
        from data.fetcher import get_history

        df = get_history(symbol, period="max", interval="1d")
        if df is None or df.empty:
            return None
        # ``get_history`` returns a tz-naive index named after reset; normalize.
        if "date" in df.columns:
            df = df.set_index(pd.to_datetime(df["date"]))
        df = df.sort_index()
        upto = df.loc[df.index <= pd.Timestamp(when)]
        if upto.empty:
            return None
        close = upto.iloc[-1].get("close")
        return float(close) if close and float(close) > 0 else None
    except Exception as exc:
        logger.warning(f"track_record_scorer: price lookup failed for {symbol} — {exc}")
        return None


# --------------------------------------------------------------------------- #
#  Hit logic (pure)                                                           #
# --------------------------------------------------------------------------- #

def compute_hit(action: str, return_pct: float, excess_return_pct: float) -> bool:
    """Directional correctness of a recommendation.

    - Bullish actions (BUY/STRONG BUY): hit when we beat the benchmark.
    - Bearish actions (REDUCE/SELL/AVOID): hit when we underperform it
      (i.e. avoiding/trimming was right).
    - HOLD (and anything else): hit when the absolute move stayed within the
      configured band — holding meant we neither missed nor avoided a big move.
    """
    a = (action or "").upper()
    if a in tuple(x.upper() for x in TRACK_RECORD.bullish_actions):
        return excess_return_pct > 0
    if a in tuple(x.upper() for x in TRACK_RECORD.bearish_actions):
        return excess_return_pct < 0
    return abs(return_pct) <= TRACK_RECORD.hold_band_pct


# --------------------------------------------------------------------------- #
#  Scoring job                                                                #
# --------------------------------------------------------------------------- #

def score_due_recommendations(
    store=None,
    *,
    now: Optional[datetime] = None,
    price_lookup: Optional[PriceLookup] = None,
) -> Dict[str, int]:
    """Score every recommendation whose horizon elapsed and has no outcome yet.

    Idempotent: an already-scored (rec_id, horizon) pair is skipped via the
    unique constraint + ``get_pending_scoring`` filter. Re-running is safe.

    ``price_lookup`` is injectable for tests; defaults to the yfinance-backed one.
    Returns a small summary: {"scored": n, "skipped": m}.
    """
    store = store or track_record_store
    now = now or datetime.utcnow()
    price_lookup = price_lookup or _price_on_or_before
    benchmark = TRACK_RECORD.benchmark

    scored = 0
    skipped = 0

    for horizon in TRACK_RECORD.horizons_days:
        pending = store.get_pending_scoring(horizon, now=now)
        for rec in pending:
            horizon_date = rec.created_at + timedelta(days=horizon)

            price_then = rec.price_at_rec or price_lookup(rec.symbol, rec.created_at)
            price_now = price_lookup(rec.symbol, horizon_date)
            if not price_then or not price_now:
                skipped += 1
                continue

            return_pct = (price_now / price_then - 1.0) * 100.0

            bench_then = price_lookup(benchmark, rec.created_at)
            bench_now = price_lookup(benchmark, horizon_date)
            if bench_then and bench_now:
                benchmark_return_pct = (bench_now / bench_then - 1.0) * 100.0
            else:
                benchmark_return_pct = 0.0

            excess = return_pct - benchmark_return_pct
            hit = compute_hit(rec.action, return_pct, excess)

            store.save_outcome(
                rec_id=rec.id,
                horizon_days=horizon,
                price_at_horizon=round(price_now, 4),
                return_pct=round(return_pct, 4),
                benchmark_return_pct=round(benchmark_return_pct, 4),
                excess_return_pct=round(excess, 4),
                hit=hit,
            )
            scored += 1

    logger.info(f"track_record_scorer: scored={scored} skipped={skipped}")
    return {"scored": scored, "skipped": skipped}


# --------------------------------------------------------------------------- #
#  Aggregate metrics (pure functions over scored rows)                        #
# --------------------------------------------------------------------------- #

def calibration_by_confidence(rows: List[dict]) -> Dict[str, dict]:
    """For each confidence level: hit rate, n, mean excess return.

    ``rows`` are dicts as produced by ``TrackRecordStore.get_scored_rows``.
    A well-calibrated model hits more often when it says HIGH than when it
    says LOW.
    """
    out: Dict[str, dict] = {}
    for level in TRACK_RECORD.min_confidence_for_calibration:
        subset = [r for r in rows if (r.get("confidence") or "").upper() == level.upper() and r.get("hit") is not None]
        n = len(subset)
        if n == 0:
            out[level] = {"n": 0, "hit_rate": None, "mean_excess_pct": None}
            continue
        hits = sum(1 for r in subset if r["hit"])
        mean_excess = sum(float(r.get("excess_return_pct") or 0.0) for r in subset) / n
        out[level] = {
            "n": n,
            "hit_rate": round(hits / n, 4),
            "mean_excess_pct": round(mean_excess, 4),
        }
    return out


def hit_rate_by_action(rows: List[dict]) -> Dict[str, dict]:
    """Hit rate and mean excess return grouped by recommendation action."""
    out: Dict[str, dict] = {}
    actions = sorted({(r.get("action") or "").upper() for r in rows if r.get("hit") is not None})
    for action in actions:
        subset = [r for r in rows if (r.get("action") or "").upper() == action and r.get("hit") is not None]
        n = len(subset)
        hits = sum(1 for r in subset if r["hit"])
        mean_excess = sum(float(r.get("excess_return_pct") or 0.0) for r in subset) / n
        out[action] = {"n": n, "hit_rate": round(hits / n, 4), "mean_excess_pct": round(mean_excess, 4)}
    return out


def hit_rate_by_source(rows: List[dict]) -> Dict[str, dict]:
    """Hit rate by source (rule_based vs ai vs committee) — the Fase 2 yardstick."""
    out: Dict[str, dict] = {}
    sources = sorted({(r.get("source") or "").lower() for r in rows if r.get("hit") is not None})
    for source in sources:
        subset = [r for r in rows if (r.get("source") or "").lower() == source and r.get("hit") is not None]
        n = len(subset)
        hits = sum(1 for r in subset if r["hit"])
        out[source] = {"n": n, "hit_rate": round(hits / n, 4)}
    return out


def equity_curve(rows: List[dict]) -> pd.DataFrame:
    """Cumulative growth of $1 following the model's bullish signals vs benchmark.

    Only bullish actions are 'invested'; each scored bullish recommendation is
    treated as an independent position whose return is its ``return_pct``. We
    chain them chronologically into a simple compounded equity curve and do the
    same with the matching benchmark returns for an apples-to-apples line.
    """
    bullish = {x.upper() for x in TRACK_RECORD.bullish_actions}
    invested = [
        r for r in rows
        if (r.get("action") or "").upper() in bullish
        and r.get("return_pct") is not None
        and r.get("created_at") is not None
    ]
    invested.sort(key=lambda r: r["created_at"])
    if not invested:
        return pd.DataFrame(columns=["created_at", "model_equity", "benchmark_equity"])

    model_eq = 1.0
    bench_eq = 1.0
    records = []
    for r in invested:
        model_eq *= 1.0 + float(r["return_pct"]) / 100.0
        bench_eq *= 1.0 + float(r.get("benchmark_return_pct") or 0.0) / 100.0
        records.append(
            {
                "created_at": r["created_at"],
                "model_equity": round(model_eq, 6),
                "benchmark_equity": round(bench_eq, 6),
            }
        )
    return pd.DataFrame(records)


def summary_stats(rows: List[dict]) -> dict:
    """Headline numbers for the page header."""
    scored = [r for r in rows if r.get("hit") is not None]
    n = len(scored)
    if n == 0:
        return {"n": 0, "overall_hit_rate": None, "mean_excess_pct": None}
    hits = sum(1 for r in scored if r["hit"])
    mean_excess = sum(float(r.get("excess_return_pct") or 0.0) for r in scored) / n
    return {
        "n": n,
        "overall_hit_rate": round(hits / n, 4),
        "mean_excess_pct": round(mean_excess, 4),
    }
