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

import math
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

def compute_hit(action: str, return_pct: float, excess_return_pct: Optional[float]) -> Optional[bool]:
    """Directional correctness of a recommendation, or None when it is ungradable.

    - Bullish actions (BUY/STRONG BUY): hit when we beat the benchmark.
    - Bearish actions (REDUCE/SELL/AVOID): hit when we underperform it
      (i.e. avoiding/trimming was right).
    - HOLD (and anything else): hit when the absolute move stayed within the
      configured band — holding meant we neither missed nor avoided a big move.

    ``excess_return_pct`` is None when the benchmark could not be priced (U2-4).
    The first two rules grade a call *against the market*, so with the market
    unknown there is no answer and this returns None — a recommendation nobody
    could grade must not be filed as a win. The HOLD rule is measured against an
    absolute band with no market term in it, so it stays gradable.
    """
    a = (action or "").upper()
    if a in tuple(x.upper() for x in TRACK_RECORD.bullish_actions):
        return None if excess_return_pct is None else excess_return_pct > 0
    if a in tuple(x.upper() for x in TRACK_RECORD.bearish_actions):
        return None if excess_return_pct is None else excess_return_pct < 0
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
    Returns a small summary with three disjoint counts:
    ``{"scored": n, "partial": p, "skipped": m}`` — fully scored, persisted
    without a benchmark (U2-4, retried on the next run), and not persisted at all
    because the ticker itself could not be priced.
    """
    store = store or track_record_store
    now = now or datetime.utcnow()
    price_lookup = price_lookup or _price_on_or_before
    benchmark = TRACK_RECORD.benchmark

    scored = 0
    partial = 0
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

            # U2-4: a benchmark that could not be priced is *unknown*, not flat.
            # Defaulting it to 0.0 made ``excess`` equal ``return_pct``, so a BUY
            # that rose 10 % while the market rose 12 % — a loss — was persisted as
            # a ten-point win, permanently and indistinguishably from a real one.
            benchmark_missing = not (bench_then and bench_now)
            if benchmark_missing:
                benchmark_return_pct = None
                excess = None
                logger.warning(
                    f"track_record_scorer: no benchmark ({benchmark}) for {rec.symbol} "
                    f"@{horizon}d ({rec.created_at:%Y-%m-%d} → {horizon_date:%Y-%m-%d}) "
                    "— outcome saved without excess/hit, will retry"
                )
            else:
                benchmark_return_pct = (bench_now / bench_then - 1.0) * 100.0
                excess = return_pct - benchmark_return_pct

            hit = compute_hit(rec.action, return_pct, excess)

            store.save_outcome(
                rec_id=rec.id,
                horizon_days=horizon,
                price_at_horizon=round(price_now, 4),
                return_pct=round(return_pct, 4),
                benchmark_return_pct=(None if benchmark_return_pct is None else round(benchmark_return_pct, 4)),
                excess_return_pct=(None if excess is None else round(excess, 4)),
                hit=hit,
                benchmark_missing=benchmark_missing,
            )
            if benchmark_missing:
                partial += 1
            else:
                scored += 1

    logger.info(f"track_record_scorer: scored={scored} partial={partial} skipped={skipped}")
    return {"scored": scored, "partial": partial, "skipped": skipped}


# --------------------------------------------------------------------------- #
#  Aggregate metrics (pure functions over scored rows)                        #
# --------------------------------------------------------------------------- #

def _known_excesses(rows: List[dict]) -> List[float]:
    """The excess returns that exist, in order.

    U2-4: every aggregate here used to read ``float(r.get("excess_return_pct") or 0.0)``,
    which averages "the market's move is unknown" as "the market moved exactly as
    much as we did". A row without a benchmark has no excess to contribute — it is
    absent from the sample, not a zero in it. Kept in one place so the three callers
    cannot drift on what counts.
    """
    return [
        float(r["excess_return_pct"])
        for r in rows
        if r.get("excess_return_pct") is not None
    ]


def _gradable(rows: List[dict]) -> List[dict]:
    """Rows carrying an actual verdict. ``hit is None`` means nobody could grade it."""
    return [r for r in rows if r.get("hit") is not None]


def calibration_by_confidence(rows: List[dict]) -> Dict[str, dict]:
    """For each confidence level: hit rate, n, mean excess return.

    ``rows`` are dicts as produced by ``TrackRecordStore.get_scored_rows``.
    A well-calibrated model hits more often when it says HIGH than when it
    says LOW.

    ``n`` counts gradable calls and ``n_excess`` counts the ones with a known
    excess; they differ whenever a benchmark lookup failed (U2-4), so the two
    numbers are reported separately rather than papered over.
    """
    out: Dict[str, dict] = {}
    for level in TRACK_RECORD.min_confidence_for_calibration:
        at_level = [r for r in rows if (r.get("confidence") or "").upper() == level.upper()]
        subset = _gradable(at_level)
        n = len(subset)
        excesses = _known_excesses(at_level)
        if n == 0 and not excesses:
            out[level] = {"n": 0, "n_excess": 0, "hit_rate": None, "mean_excess_pct": None}
            continue
        hits = sum(1 for r in subset if r["hit"])
        out[level] = {
            "n": n,
            "n_excess": len(excesses),
            "hit_rate": (round(hits / n, 4) if n else None),
            "mean_excess_pct": (round(sum(excesses) / len(excesses), 4) if excesses else None),
        }
    return out


def mean_with_band(values: List[float]) -> dict:
    """Mean of *values* with the width of its 95 % uncertainty band.

    Pure. Exists because the mean alone invites a conclusion the sample cannot
    support. Measured on the real data (2026-08-22), the page showed:

        STRONG BUY   n=4    mean excess  +10.40 %
        BUY          n=13   mean excess   +4.08 %

    which reads as "STRONG BUY beats BUY by six points". But these excess returns
    have a standard deviation of 9.63 % and range from −23.5 % to +29.0 %; with
    four observations the band around that +10.40 % is roughly ±9 points, so the
    difference is indistinguishable from zero. Distinguishing a ~4-point gap needs
    something like fifty observations per group.

    ``band`` is the half-width: the mean is compatible with anything in
    ``mean ± band``. ``inconclusive`` is True when that interval contains zero,
    which is the flag the UI needs so a reader does not mistake noise for signal.

    Uses Student's t rather than 1.96, which matters precisely where this function
    is most needed: at n=4 the critical value is 3.18, not 1.96, so the normal
    approximation would understate the band by 60 % exactly when the sample is
    least trustworthy. A standard deviation estimated from four points is itself a
    noisy number, and t is what accounts for that.
    """
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "band": None, "inconclusive": True}
    mean = sum(values) / n
    if n < 2:
        return {"n": n, "mean": round(mean, 4), "band": None, "inconclusive": True}

    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    std_error = math.sqrt(variance / n)
    band = _t_critical(n - 1) * std_error
    return {
        "n": n,
        "mean": round(mean, 4),
        "band": round(band, 4),
        "inconclusive": abs(mean) <= band,
    }


def _t_critical(df: int) -> float:
    """Two-sided 95 % critical value for *df* degrees of freedom."""
    try:
        from scipy import stats

        return float(stats.t.ppf(0.975, df))
    except Exception:  # pragma: no cover - scipy is a hard dependency of the project
        return 1.96


def hit_rate_by_action(rows: List[dict]) -> Dict[str, dict]:
    """Hit rate and mean excess return grouped by recommendation action.

    The excess return carries its uncertainty band — see ``mean_with_band``. Without
    it the table invites conclusions from four observations.

    U2-4: a recommendation whose benchmark could not be priced is ungradable, so it
    moves neither the numerator nor the denominator of the hit rate, and its
    non-existent excess stays out of the average. ``n_excess`` says how many rows
    the average actually rests on.
    """
    out: Dict[str, dict] = {}
    actions = sorted({(r.get("action") or "").upper() for r in rows if r.get("hit") is not None})
    for action in actions:
        at_action = [r for r in rows if (r.get("action") or "").upper() == action]
        subset = _gradable(at_action)
        n = len(subset)
        hits = sum(1 for r in subset if r["hit"])
        excesses = _known_excesses(at_action)
        stats = mean_with_band(excesses)
        out[action] = {
            "n": n,
            "n_excess": len(excesses),
            "hit_rate": round(hits / n, 4),
            "mean_excess_pct": (round(sum(excesses) / len(excesses), 4) if excesses else None),
            "excess_band_pct": stats["band"],
            "inconclusive": stats["inconclusive"],
        }
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

    A stretch whose benchmark could not be priced (U2-4) is dropped from *both*
    lines: the chart's claim is "the model against the benchmark over the same
    stretches", and a stretch with no benchmark has no counterpart to race. Keeping
    it — as ``benchmark_return_pct or 0.0`` did — let the model compound while its
    opponent stood still. A genuine 0.0 % benchmark is a measurement and stays.
    """
    bullish = {x.upper() for x in TRACK_RECORD.bullish_actions}
    invested = [
        r for r in rows
        if (r.get("action") or "").upper() in bullish
        and r.get("return_pct") is not None
        and r.get("benchmark_return_pct") is not None
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
        bench_eq *= 1.0 + float(r["benchmark_return_pct"]) / 100.0
        records.append(
            {
                "created_at": r["created_at"],
                "model_equity": round(model_eq, 6),
                "benchmark_equity": round(bench_eq, 6),
            }
        )
    return pd.DataFrame(records)


def summary_stats(rows: List[dict]) -> dict:
    """Headline numbers for the page header.

    Three counts, because after U2-4 they are genuinely three different things:
    ``n`` gradable calls, ``n_excess`` of them with a measured excess, and
    ``n_benchmark_missing`` rows whose benchmark could not be priced. When nothing
    has a benchmark, ``mean_excess_pct`` is None — the honest answer is "—", not
    "+0.0 % vs the market".
    """
    scored = _gradable(rows)
    n = len(scored)
    excesses = _known_excesses(rows)
    missing = sum(1 for r in rows if r.get("benchmark_missing"))
    hits = sum(1 for r in scored if r["hit"])
    return {
        "n": n,
        "n_excess": len(excesses),
        "n_benchmark_missing": missing,
        "overall_hit_rate": (round(hits / n, 4) if n else None),
        "mean_excess_pct": (round(sum(excesses) / len(excesses), 4) if excesses else None),
    }
