"""Persisted Screener runs (audit items 13, 15, 16, 17).

Mirrors the load/save pattern of ``data.plan_health.PlanHealthStore``: one JSON
file, Streamlit-free, import-light.

Why this exists
---------------
A cold Screener run over the 85-ticker universe was measured at **~5 minutes**
(2026-08-17), and the result lived only in ``st.session_state``. Closing the tab
or restarting the server threw all of it away, so the everyday cost of opening
the app was another five minutes — while the page's caption promised "~15s".

Persisting the last run buys four things at once:

  * **15** — reopening the app shows the previous ranking instead of a blank page
  * **13** — a measured duration is the only honest basis for an ETA next time
  * **16** — knowing when each ticker was measured is what makes "refresh only the
    stale ones" possible instead of re-running all 85
  * **17** — last run's scores let the ticker cap keep the names that matter
    rather than the first N in file order

The file is derived data: it is gitignored and safe to delete at any time.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from loguru import logger

_STORE_PATH = Path(__file__).parent / "screener_last_run.json"

#: Bump when the row schema changes in a way that makes old rows unusable.
#: 2 — scoring rewrite (missing-metric, FFO, yield units, U2-2). A schema-1
#: ranking must not be presented as current.
SCHEMA_VERSION = 2


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


@dataclass
class ScreenerRun:
    """One completed (or partial) analysis of a universe."""

    universe_key: str = "default"
    ran_at: str = field(default_factory=_now_iso)
    duration_s: float = 0.0
    #: How many tickers ``duration_s`` actually covers. Stops being
    #: ``len(rows) + len(failures)`` the moment a partial refresh stores a
    #: subset's duration alongside the whole run's rows. 0 = not recorded.
    measured_n: int = 0
    rows: List[dict] = field(default_factory=list)
    failures: List[dict] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    # -------------------------------------------------------------- #

    @property
    def tickers(self) -> List[str]:
        return [str(r.get("Ticker", "")) for r in self.rows if r.get("Ticker")]

    def seconds_per_ticker(self) -> Optional[float]:
        """Measured throughput — the only honest basis for an ETA (item 13).

        The denominator is ``measured_n`` when the run recorded one. Inferring it
        from the row count is only correct while every row was measured by the
        same run: a partial refresh of 3 tickers divided its 11 seconds by all 85
        rows and promised the next cold run in ~11s instead of ~5 min — the very
        defect item 13 fixed. Files written before the field exists have 0 and
        keep the historical denominator.
        """
        n = self.measured_n or (len(self.rows) + len(self.failures))
        if n <= 0 or self.duration_s <= 0:
            return None
        return self.duration_s / n

    def age_hours(self) -> Optional[float]:
        ts = _parse(self.ran_at)
        if ts is None:
            return None
        return (datetime.now() - ts).total_seconds() / 3600.0

    def stale_tickers(self, max_age_hours: float) -> List[str]:
        """Tickers measured longer ago than ``max_age_hours`` (item 16).

        A row with no timestamp counts as stale: unknown age is not fresh.
        """
        cutoff = datetime.now() - timedelta(hours=float(max_age_hours))
        out: List[str] = []
        for row in self.rows:
            sym = str(row.get("Ticker", ""))
            if not sym:
                continue
            ts = _parse(str(row.get("_measured_at", "")))
            if ts is None or ts < cutoff:
                out.append(sym)
        return out

    def covered_tickers(self) -> set[str]:
        """Every ticker this run already touched — measured, or seen failing.

        A ticker that blew up is not *unknown*: the run reached it and has an
        answer for it. Leaving failures out of this set made the page's cache key
        disagree with the universe it asked for, so a single yfinance hiccup
        turned every reopen into another cold run (audit item 15).
        """
        return set(self.tickers) | {str(f.get("Ticker", "")) for f in self.failures}

    def missing_tickers(self, wanted: Sequence[str]) -> List[str]:
        """Requested tickers this run has neither a row nor a failure for.

        Non-empty after an interrupted run, which is what makes resuming possible
        instead of starting the five minutes over.
        """
        known = self.covered_tickers()
        return [s for s in wanted if s not in known]

    def scores(self) -> Dict[str, float]:
        """ticker → adjusted score, for prioritising a capped run (item 17)."""
        out: Dict[str, float] = {}
        for row in self.rows:
            sym = str(row.get("Ticker", ""))
            try:
                out[sym] = float(row.get("Adj. Score") or 0.0)
            except (TypeError, ValueError):
                continue
        return out

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Optional["ScreenerRun"]:
        if not isinstance(data, dict):
            return None
        if int(data.get("schema_version", 0)) != SCHEMA_VERSION:
            logger.info("Screener cache: schema mismatch, ignoring stored run")
            return None
        known = {f for f in cls.__dataclass_fields__}          # noqa: SLF001
        return cls(**{k: v for k, v in data.items() if k in known})


class ScreenerRunStore:
    """Single-file JSON store keyed by universe."""

    def __init__(self, path: Path = _STORE_PATH):
        self.path = path

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) or {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Screener cache unreadable ({exc}); starting fresh")
            return {}

    def save(self, run: ScreenerRun) -> None:
        data = self._read()
        data[run.universe_key] = run.as_dict()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except OSError as exc:
            # A cache that cannot be written must never break the analysis.
            logger.warning(f"Screener cache not saved: {exc}")

    def load(self, universe_key: str = "default") -> Optional[ScreenerRun]:
        return ScreenerRun.from_dict(self._read().get(universe_key))

    def clear(self, universe_key: Optional[str] = None) -> None:
        if universe_key is None:
            self.path.unlink(missing_ok=True)
            return
        data = self._read()
        data.pop(universe_key, None)
        try:
            self.path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except OSError as exc:
            logger.warning(f"Screener cache not cleared: {exc}")


#: Module-level singleton, mirroring plan_store / plan_health_store.
screener_run_store = ScreenerRunStore()


# ------------------------------------------------------------------ #
#  Pure helpers used by the page                                       #
# ------------------------------------------------------------------ #


def is_subset_cache_hit(selected: Sequence[str], covered: Sequence[str]) -> bool:
    """True when every selected ticker is already in the stored/session run.

    Equality used to be the hit test, so a slider below the last run's size
    (default 25 vs a previous 85) was a miss, re-ran the prefix, and overwrote
    the JSON with those 25 rows.
    """
    sel = frozenset(selected)
    return bool(sel) and sel <= frozenset(covered)


def uncovered_selected(selected: Sequence[str], covered: Sequence[str]) -> List[str]:
    """``selected`` minus ``covered``, preserving selected order."""
    known = frozenset(covered)
    return [s for s in selected if s not in known]


def filter_to_selected(rows: List[dict], selected: Sequence[str]) -> List[dict]:
    """Keep rows whose ``Ticker`` is in ``selected`` (display the cap, not the store)."""
    sel = frozenset(selected)
    return [r for r in rows if r.get("Ticker") in sel]


def merge_screener_rows(
    previous_rows: List[dict],
    previous_failures: List[dict],
    new_rows: List[dict],
    new_failures: List[dict],
) -> tuple[List[dict], List[dict]]:
    """Replace touched tickers in place; keep everything the subset did not measure."""
    touched = {r.get("Ticker") for r in new_rows} | {f.get("Ticker") for f in new_failures}
    touched.discard("")
    touched.discard(None)
    rows = [r for r in previous_rows if r.get("Ticker") not in touched] + list(new_rows)
    failures = [f for f in previous_failures if f.get("Ticker") not in touched] + list(new_failures)
    return rows, failures


def format_eta(seconds: float) -> str:
    """Human ETA. Says minutes when it is minutes — the point of item 13."""
    s = max(float(seconds), 0.0)
    if s < 90:
        return f"~{int(round(s))}s"
    minutes = s / 60.0
    if minutes < 10:
        return f"~{minutes:.1f} min".replace(".0 ", " ")
    return f"~{int(round(minutes))} min"


def prioritize_universe(
    tickers: Sequence[str],
    *,
    watchlist: Sequence[str] = (),
    holdings: Sequence[str] = (),
    previous_scores: Optional[Dict[str, float]] = None,
) -> List[str]:
    """Order a universe so that capping it keeps what matters (audit item 17).

    The page used to take ``tickers[:max_tickers]`` — a prefix of the JSON file,
    ordered by nothing. Lowering the cap to go faster therefore returned an
    arbitrary subset while looking like "the top N".

    Order: watchlist, then current holdings, then best scorers from the last run,
    then everything else. Ties and unknowns keep their original relative order,
    so the result is deterministic.
    """
    scores = previous_scores or {}
    watch = {str(s).upper() for s in watchlist}
    held = {str(s).upper() for s in holdings}

    def rank(item) -> tuple:
        idx, sym = item
        up = str(sym).upper()
        if up in watch:
            tier = 0
        elif up in held:
            tier = 1
        elif up in scores:
            tier = 2
        else:
            tier = 3
        # Negative score sorts best-first inside the "previously scored" tier.
        return (tier, -scores.get(sym, 0.0), idx)

    return [sym for _, sym in sorted(enumerate(tickers), key=rank)]
