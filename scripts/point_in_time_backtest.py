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
its own unique constraint (``analysis/synthetic_backtest.py``) — is skipped
without spending a network call re-fetching it (``SyntheticBacktestStore.existing_pairs``).
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
from analysis.synthetic_backtest import synthetic_backtest_store  # noqa: E402
from config import MULTI_SOURCE  # noqa: E402
from data.data_sources import SecEdgarSource  # noqa: E402
from data.fetcher import _fetch_with_retry  # noqa: E402


def _fetch_companyfacts(symbol: str) -> Optional[dict]:
    """One retried network call for *symbol*'s entire SEC filing history.

    ``None`` means either "no SEC CIK for this ticker" (a real, permanent
    condition — non-US filers like the Argentina ADRs in ``DEFAULT_TICKERS``
    file 20-F/6-K, not 10-K, and never appear in SEC's ticker→CIK map) or a
    request that failed even after ``FETCH.max_retries`` attempts, logged
    distinctly by ``_fetch_with_retry`` either way.
    """
    source = SecEdgarSource()
    cik = source._resolve_cik(symbol)
    if cik is None:
        logger.warning(f"{symbol}: no SEC CIK — non-US filer or not an equity, skipping")
        return None

    def _fetch():
        import requests

        url = SecEdgarSource._FACTS_URL.format(cik=cik)
        headers = {"User-Agent": MULTI_SOURCE.sec_user_agent}
        resp = requests.get(url, headers=headers, timeout=MULTI_SOURCE.request_timeout_s)
        resp.raise_for_status()
        return resp.json()

    return _fetch_with_retry(_fetch, symbol, "SEC companyfacts (bulk backtest)")


def run(symbols: List[str], cutoffs: List[date]) -> None:
    written = skipped = failed = 0

    for symbol in symbols:
        already = synthetic_backtest_store.existing_pairs(symbol)
        pending = [c for c in cutoffs if c.isoformat() not in already]
        skipped += len(cutoffs) - len(pending)
        if not pending:
            logger.info(f"{symbol}: all {len(cutoffs)} cutoffs already logged, no fetch needed")
            continue

        facts = _fetch_companyfacts(symbol)
        time.sleep(MULTI_SOURCE.sec_bulk_request_delay_s)  # pace every real network call
        if facts is None:
            logger.error(f"{symbol}: SEC companyfacts unavailable — skipping {len(pending)} cutoff(s)")
            failed += len(pending)
            continue

        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        for cutoff in pending:
            detail = piotroski_as_of(us_gaap, cutoff)
            row_id = synthetic_backtest_store.log_piotroski(symbol, cutoff, detail)
            if row_id is None:
                failed += 1
            else:
                written += 1
                logger.info(f"{symbol} @ {cutoff}: score={detail.score}/9 (id={row_id})")

    logger.info(f"Done — {written} written, {skipped} already logged, {failed} failed")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", required=True, help="Comma-separated tickers, e.g. AAPL,MSFT,JNJ")
    p.add_argument("--cutoffs", required=True, help="Comma-separated ISO dates, e.g. 2020-06-01,2021-06-01")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    cutoffs = [
        datetime.strptime(c.strip(), "%Y-%m-%d").date()
        for c in args.cutoffs.split(",") if c.strip()
    ]
    run(symbols, cutoffs)


if __name__ == "__main__":
    main()
