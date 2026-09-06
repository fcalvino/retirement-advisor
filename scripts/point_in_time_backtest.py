#!/usr/bin/env python3
"""
Point-in-time Piotroski backtest — generate volume (PR 4/N, Idea 2).

Fetches SEC EDGAR ``companyfacts`` for each symbol — one network call per
ticker, its entire filing history in a single response — then scores the
reconstructed fundamentals at each requested historical cutoff via
``analysis.point_in_time_piotroski.piotroski_as_of``, persisting each
(symbol, cutoff) pair through ``analysis.synthetic_backtest.synthetic_backtest_store``.

Usage:
    ./venv/bin/python3 scripts/point_in_time_backtest.py \\
        --symbols AAPL,MSFT,JNJ \\
        --cutoffs 2020-06-01,2021-06-01

Resumable: a (symbol, as_of, source) pair already in the store — enforced by
its own unique index, migration-created so it applies to any pre-existing
database file too (``analysis/synthetic_backtest.py``) — is skipped without
spending a network call re-fetching it (``SyntheticBacktestStore.existing_pairs``).
An interrupted run just picks up where it left off; a re-run never
double-counts a ticker×cutoff into the calibration sample.

Paced at ``config.MULTI_SOURCE.sec_bulk_request_delay_s`` between per-ticker
requests — SEC's fair-access policy (https://www.sec.gov/os/accessing-edgar-data,
confirmed live 2026-09) caps at 10 requests/second and asks callers to
"moderate requests to minimize server load"; the default here (4 req/s)
stays comfortably under that. Retries go through ``data.fetcher._fetch_with_retry``
(``config.FETCH`` — the same policy every other network fetch in this
project already uses) rather than ``SecEdgarSource``'s silent
degrade-to-``None`` on any failure: that silence is correct for the live
single-ticker path (never break the user's screener), but a bulk historical
run needs to tell "SEC rate-limited us, retry" apart from "this ticker
genuinely has no SEC data" — conflating them would silently undercount the
calibration sample instead of raising a visible, retryable error.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

# scripts/ is not a package; mirror the sys.path bootstrap other scripts/*.py use
# (see scripts/_bootstrap.py) so this runs standalone via
# ``./venv/bin/python3 scripts/point_in_time_backtest.py``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger  # noqa: E402

from analysis.point_in_time_piotroski import piotroski_as_of  # noqa: E402
from analysis.synthetic_backtest import ALREADY_LOGGED, synthetic_backtest_store  # noqa: E402
from config import MULTI_SOURCE  # noqa: E402
from data.data_sources import SecEdgarSource  # noqa: E402
from data.fetcher import _fetch_with_retry  # noqa: E402


def _ensure_cik_map_loaded() -> bool:
    """Populates ``SecEdgarSource``'s shared ticker→CIK cache once, retried as
    a single unit, and returns whether it succeeded.

    SEC's ticker→CIK map is *one* JSON file covering every filer — not a
    per-symbol lookup — so failing to fetch it once means SEC is unreachable
    for the entire batch. Retrying it per-symbol (an earlier version of this
    script did) turns a single outage into a multi-attempt retry storm
    repeated for every remaining ticker in the universe; calling this once,
    up front, fails fast instead.
    """
    # Truthiness, not `is not None`: SecEdgarSource._resolve_cik's dict
    # comprehension can populate `_cik_map` as `{}` if SEC's response body is
    # non-empty but its rows don't carry the expected ticker/cik_str keys (a
    # schema change, a truncated body) — an empty map is exactly as useless
    # as no map, and must not be read as "every ticker legitimately has no
    # CIK", which is what every subsequent lookup would otherwise conclude.
    if SecEdgarSource._cik_map:
        return True

    def _load():
        # Any symbol forces SecEdgarSource._resolve_cik to fetch and cache
        # the shared map as a side effect — which symbol is irrelevant here,
        # only whether the class-level cache ends up populated.
        SecEdgarSource()._resolve_cik("AAPL")
        if not SecEdgarSource._cik_map:
            # SecEdgarSource._resolve_cik's own guard is `if _cik_map is None`
            # (data/data_sources.py) — it treats a landed-on `{}` as "already
            # resolved", so leaving it at `{}` here would make every retry
            # below a pure in-memory no-op against the poisoned empty cache,
            # never re-issuing the request, and would leave `{}` poisoning
            # every *future* call to this function in the same process (a
            # scheduler reusing the import) with no further attempt ever
            # made. Reset to `None` so the next retry — here or in a later
            # call — genuinely re-fetches. Under the same `_cik_lock`
            # `_resolve_cik` itself uses: this reset races that lock-guarded
            # read/write otherwise — a concurrent in-process caller of
            # `SecEdgarSource` (the screener's own thread pool, per
            # data/data_sources.py's own comment) could be mid-``with
            # cls._cik_lock:`` and observe ``_cik_map`` flip to ``None``
            # right before its own unguarded final ``.get()`` call, an
            # ``AttributeError`` on ``NoneType``.
            with SecEdgarSource._cik_lock:
                SecEdgarSource._cik_map = None
            raise RuntimeError("SEC ticker->CIK map fetch failed or returned no usable entries")

    _fetch_with_retry(_load, "SEC", "ticker->CIK map")
    time.sleep(MULTI_SOURCE.sec_bulk_request_delay_s)  # a real network attempt was just made
    return bool(SecEdgarSource._cik_map)


#: Sentinel: SEC itself confirms there is nothing to fetch for this ticker —
#: no CIK, or a 404 on a CIK that exists. A real, permanent, *expected*
#: condition (the Argentina ADRs in ``DEFAULT_TICKERS`` file 20-F/6-K, never
#: 10-K, and hit this on every run) — never a failure. Distinct from a bare
#: ``None``, which means the companyfacts request itself failed even after
#: retries: ``run()`` must count only the latter toward ``failed`` (and
#: therefore toward ``main()``'s exit code), or a normal run against a
#: universe that includes any permanently CIK-less ticker (ADRs, ETFs,
#: crypto) would always exit 1 — indistinguishable from a real SEC outage.
_NO_SEC_DATA = object()


def _fetch_companyfacts(symbol: str) -> Optional[dict]:
    """One retried network call for *symbol*'s entire SEC filing history.

    Assumes ``_ensure_cik_map_loaded()`` already succeeded — the CIK lookup
    here is then a pure in-memory dict read, no network, no pacing. Returns
    ``_NO_SEC_DATA`` (not ``None``) when SEC itself confirms nothing exists
    for this ticker — see that sentinel's own docstring — and ``None`` only
    when the companyfacts request itself failed even after
    ``FETCH.max_retries`` attempts, logged distinctly by ``_fetch_with_retry``
    either way.
    """
    cik = SecEdgarSource()._resolve_cik(symbol)
    if cik is None:
        logger.warning(f"{symbol}: no SEC CIK — non-US filer or not an equity, skipping")
        return _NO_SEC_DATA

    def _fetch():
        import requests

        url = SecEdgarSource._FACTS_URL.format(cik=cik)
        headers = {"User-Agent": MULTI_SOURCE.sec_user_agent}
        resp = requests.get(url, headers=headers, timeout=MULTI_SOURCE.request_timeout_s)
        if resp.status_code == 404:
            # Permanent, not a failure to retry: this CIK genuinely has no
            # companyfacts published (a shell company, a very recent IPO
            # with no XBRL filings yet). raise_for_status() would turn this
            # into an exception _fetch_with_retry treats identically to a
            # transient 429/5xx — burning the full retry budget (backoff
            # included) on a condition retrying can never fix, exactly the
            # "genuinely has no SEC data" case this module's own docstring
            # says must be told apart from "SEC rate-limited us, retry".
            logger.warning(f"{symbol}: SEC companyfacts 404 — CIK {cik} has no filings published")
            return _NO_SEC_DATA
        resp.raise_for_status()  # any other non-2xx (429, 5xx, ...) should retry
        return resp.json()

    result = _fetch_with_retry(_fetch, symbol, "SEC companyfacts (bulk backtest)")
    time.sleep(MULTI_SOURCE.sec_bulk_request_delay_s)  # a real network attempt was just made
    return result


def run(symbols: List[str], cutoffs: List[date]) -> dict:
    """Returns ``{"written", "skipped", "failed"}`` counts — ``main()`` uses
    ``failed`` to decide the process exit code, so a fully-failed run (SEC
    unreachable, bad User-Agent) doesn't report success to whatever launched
    it (cron, CI, a future scheduled job).

    Refuses outright (all of *symbols* × *cutoffs* counted as ``failed``,
    nothing fetched) rather than risk it silently, in two cases: the store's
    resumability guarantee could not be verified (see
    ``SyntheticBacktestStore.unique_index_verified``), or SEC's ticker→CIK
    map itself could not be fetched — checked *here*, not only in ``main()``,
    so any caller of ``run()`` directly (a scheduler, a notebook, the test
    suite) gets the same protection a CLI invocation does.
    """
    # De-duped up front, before `total` is computed from them: a duplicate
    # --cutoffs or --symbols entry must not inflate the reported failure
    # count above the number of distinct ticker×cutoff pairs actually at
    # stake, in the early-refusal paths below as much as in the main loop
    # (where it would otherwise also get scored twice and have its second
    # write rejected by the unique index as if something had gone wrong).
    # Symbols are upper-cased *here*, not left to main()'s CLI parsing —
    # SyntheticBacktestStore.existing_pairs/log_piotroski already upper-case
    # internally, so "aapl" and "AAPL" collide there; a direct caller of
    # run() (a scheduler, a notebook — not just the CLI) passing mixed case
    # must see the same one-ticker de-dup, not an inflated failure count.
    cutoffs = sorted(set(cutoffs))
    symbols = list(dict.fromkeys(s.upper() for s in symbols))
    total = len(symbols) * len(cutoffs)

    if not synthetic_backtest_store.unique_index_verified:
        # unique_index_verified was computed once, at store construction —
        # for the module-level singleton, that's import time. A lock held by
        # a concurrently-writing dashboard/scheduler at that exact moment
        # could have outlasted the migration's retry budget, and nothing
        # since then has re-checked: without this, that process would refuse
        # every batch run for its entire remaining lifetime even seconds
        # after the lock cleared. One more live attempt, right where it's
        # actually needed, costs nothing when the index was already fine.
        synthetic_backtest_store.unique_index_verified = synthetic_backtest_store._migrate(
            synthetic_backtest_store._engine
        )

    if not synthetic_backtest_store.unique_index_verified:
        logger.error(
            "synthetic_backtest_store: resumability guarantee not verified (unique index "
            "missing, likely pre-existing duplicate data) — refusing to run a batch backtest "
            "against an unprotected database"
        )
        return {"written": 0, "skipped": 0, "failed": total}

    written = skipped = failed = 0

    # Resolved for every symbol *before* touching the CIK map, not inside the
    # loop below — a fully-resumed run (every requested pair already logged)
    # must not still pay for a real ~1 MB SEC ticker→CIK download plus its
    # pacing delay when the loop was always going to skip every symbol.
    pending_by_symbol = {}
    for symbol in symbols:
        already = synthetic_backtest_store.existing_pairs(symbol)
        pending = [c for c in cutoffs if c.isoformat() not in already]
        skipped += len(cutoffs) - len(pending)
        if pending:
            pending_by_symbol[symbol] = pending
        else:
            logger.info(f"{symbol}: all {len(cutoffs)} cutoffs already logged, no fetch needed")

    if pending_by_symbol and not _ensure_cik_map_loaded():
        logger.error("SEC ticker->CIK map fetch failed after retries — aborting the whole batch")
        # `skipped` above already accounts for every pair that was NOT left
        # pending; what's pending (and now can't even be attempted) is just
        # the complement, `total - skipped` — recomputing it a second way
        # from `pending_by_symbol` would be two derivations of the same
        # number that must always agree.
        return {"written": 0, "skipped": skipped, "failed": total - skipped}

    for symbol, pending in pending_by_symbol.items():
        facts = _fetch_companyfacts(symbol)
        if facts is _NO_SEC_DATA:
            # SEC itself confirms nothing exists here (no CIK, or a 404) —
            # a real, permanent, *expected* condition (Argentina ADRs, ETFs,
            # crypto in config.DEFAULT_TICKERS all hit this every run), never
            # a failure: counting it toward `failed` would make main()'s
            # exit code 1 on every normal run against a universe that
            # includes any such ticker, indistinguishable from a real SEC
            # outage.
            logger.info(f"{symbol}: no SEC data (confirmed, not a failure) — skipping {len(pending)} cutoff(s)")
            skipped += len(pending)
            continue
        if facts is None:
            logger.error(f"{symbol}: SEC companyfacts unavailable — skipping {len(pending)} cutoff(s)")
            failed += len(pending)
            continue

        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        for cutoff in pending:
            try:
                detail = piotroski_as_of(us_gaap, cutoff)
            except Exception as exc:  # never let one bad cutoff abort the whole batch
                logger.error(f"{symbol} @ {cutoff}: reconstruction failed — {exc}")
                failed += 1
                continue

            row_id = synthetic_backtest_store.log_piotroski(symbol, cutoff, detail)
            if row_id is ALREADY_LOGGED:
                # existing_pairs() itself degrades to an empty set on a
                # transient read failure (same defensive shape as
                # log_piotroski) — that can make this loop re-attempt a pair
                # that was already safely stored. The unique index correctly
                # rejects the duplicate write; that is not a real failure.
                logger.info(f"{symbol} @ {cutoff}: already logged (resumability re-check), not a failure")
                skipped += 1
            elif row_id is None:
                failed += 1
            else:
                written += 1
                logger.info(f"{symbol} @ {cutoff}: score={detail.score}/9 (id={row_id})")

    logger.info(f"Done — {written} written, {skipped} already logged, {failed} failed")
    return {"written": written, "skipped": skipped, "failed": failed}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", required=True, help="Comma-separated tickers, e.g. AAPL,MSFT,JNJ")
    p.add_argument("--cutoffs", required=True, help="Comma-separated ISO dates, e.g. 2020-06-01,2021-06-01")
    return p.parse_args()


def main() -> int:
    """Exit code reflects whether anything actually failed — a caller
    wrapping this in cron/CI to run the real universe later must be able to
    tell a 100%-failed run (SEC down, User-Agent blocked, resumability
    guarantee unverified — all checked inside ``run()``) from success.
    """
    args = _parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    cutoffs = [
        datetime.strptime(c.strip(), "%Y-%m-%d").date()
        for c in args.cutoffs.split(",") if c.strip()
    ]
    summary = run(symbols, cutoffs)
    return 1 if summary["failed"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
