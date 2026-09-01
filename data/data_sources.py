"""
Multi-source data layer (Gran Salto — Fase 3A).

Pulls the same canonical raw facts from more than one provider so a downstream
reconciliation step (``analysis/data_reconciliation.py``) can detect when sources
disagree — the antidote to "todo entra por yfinance / garbage in, garbage out".

Each source returns a dict ``{canonical_field: SourceValue}``. Canonical fields
are deliberately raw, cross-comparable facts (not derived ratios), because that
is where a like-for-like comparison between providers is valid:

    total_revenue, net_income, shares_outstanding, total_equity,
    total_assets, current_price, market_cap

Cross-source overlap (yfinance + SEC) is strongest on total_revenue, net_income,
total_equity and total_assets. Price/mcap/shares are typically yfinance-only.
This does **not** validate score ratios (ROE, PE, …) directly — only the raw
inputs that can support a like-for-like check.

Sources degrade gracefully: any network/parse failure yields ``{}`` (and a log
line), never an exception, so the rest of the pipeline keeps working. The
abstraction is the point — adapters can be injected/faked, so the reconciliation
brain is fully testable offline.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

from config import FETCH, MULTI_SOURCE
from data.cache import cache


@dataclass
class SourceValue:
    field: str
    value: float
    source: str
    as_of: Optional[str] = None  # ISO date of the underlying data, when known
    unit: str = ""

    def as_dict(self) -> dict:
        return {
            "field": self.field, "value": self.value, "source": self.source,
            "as_of": self.as_of, "unit": self.unit,
        }


class DataSource:
    """Base class. Subclasses implement ``fetch_fundamentals``."""

    name = "base"

    def fetch_fundamentals(self, symbol: str) -> Dict[str, SourceValue]:  # pragma: no cover - interface
        raise NotImplementedError


def _f(value) -> Optional[float]:
    try:
        if value is None:
            return None
        v = float(value)
        return v if v == v else None  # drop NaN
    except (TypeError, ValueError):
        return None


def _annual_fact(df, candidates: List[str]) -> Optional[tuple]:
    """``(value, as_of_iso)`` for the newest annual column of a matching row.

    yfinance moves its statement row labels between versions, so every canonical
    fact is looked up through a candidate list — the same lists the scoring engine
    already uses (``analysis/moat.py``, ``analysis/scoring.py``,
    ``analysis/fundamental.py``). Mirrors ``FundamentalAnalyzer._extract_annual_series``.

    Returns ``None`` when no candidate matches or the newest column is empty, so a
    fact that cannot be dated is simply not emitted rather than emitted undated.
    """
    if df is None or getattr(df, "empty", True):
        return None
    for name in candidates:
        if name not in df.index:
            continue
        series = df.loc[name].dropna()
        if series.empty:
            continue
        try:
            series.index = pd.to_datetime(series.index)
        except (TypeError, ValueError):
            continue
        series = series.sort_index(ascending=False)
        value = _f(series.iloc[0])
        if value is None:
            continue
        return value, series.index[0].date().isoformat()
    return None


def _cached_info(symbol: str) -> dict:
    """What ``get_info`` already stored. Miss → {} , no network (N2b)."""
    return cache.get(f"info:{symbol}") or {}


def _cached_financials(symbol: str) -> Dict[str, pd.DataFrame]:
    """What ``get_financials`` already stored. Miss → {} , no network (N2b)."""
    raw = cache.get(f"financials:{symbol}")
    if not raw or not isinstance(raw, dict):
        return {}
    return {k: pd.DataFrame(v) for k, v in raw.items()}


def _fetched_info(symbol: str) -> dict:
    """Kill-switch path: go to the fetcher. Default is cache-only."""
    try:
        from data.fetcher import get_info

        return get_info(symbol) or {}
    except Exception as exc:
        logger.warning(f"YFinanceSource: {symbol} info failed — {exc}")
        return {}


def _fetched_financials(symbol: str) -> Dict[str, pd.DataFrame]:
    try:
        from data.fetcher import get_financials

        return get_financials(symbol) or {}
    except Exception as exc:
        logger.warning(f"YFinanceSource: {symbol} financials failed — {exc}")
        return {}


# --------------------------------------------------------------------------- #
#  yfinance (always available — wraps the existing fetcher)                   #
# --------------------------------------------------------------------------- #

class YFinanceSource(DataSource):
    """Adapter over the yfinance *cache*, not a second fetcher (N2b).

    ``FundamentalAnalyzer.analyze`` is the one that calls ``get_info`` /
    ``get_financials``. This class maps whatever those already stored into
    canonical ``SourceValue``s for reconciliation. A cache miss is ``{}``, not
    another trip to the network — that second trip is what doubled the retry
    loop. Kill-switch: ``FETCH.adapter_reads_cache_only``.
    """

    name = "yfinance"

    # Periodic facts read off the annual statements, so each one carries the
    # fiscal period it covers. ``info``'s totalRevenue / netIncomeToCommon are
    # **TTM with no date attached**, and comparing them against SEC's last closed
    # 10-K is what manufactured the false conflicts: measured on US Quality
    # (2026-08-18), every company growing faster than ``discrepancy_pct`` looked
    # like a discrepancy — 20 of 25 on revenue, 18 of 25 on net income — while
    # total_equity and total_assets, the two facts with no period, never did.
    _STATEMENT_FACTS = {
        "total_revenue": ("income_stmt", ["Total Revenue", "Revenue"]),
        "net_income": ("income_stmt", ["Net Income"]),
        "total_equity": (
            "balance_sheet",
            ["Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity"],
        ),
        "total_assets": ("balance_sheet", ["Total Assets"]),
    }

    # Point-in-time facts: "now" by definition, so they carry no as_of. SEC does
    # not publish them, so they are never cross-checked anyway.
    _INFO_FACTS = {
        "shares_outstanding": ("sharesOutstanding",),
        "current_price": ("currentPrice", "regularMarketPrice"),
        "market_cap": ("marketCap",),
    }

    def fetch_fundamentals(self, symbol: str) -> Dict[str, SourceValue]:
        out: Dict[str, SourceValue] = {}

        if FETCH.adapter_reads_cache_only:
            info = _cached_info(symbol)
            financials = _cached_financials(symbol)
        else:
            info = _fetched_info(symbol)
            financials = _fetched_financials(symbol)

        for field_name, keys in self._INFO_FACTS.items():
            raw = next((info.get(k) for k in keys if info.get(k) is not None), None)
            v = _f(raw)
            if v is not None:
                out[field_name] = SourceValue(field_name, v, self.name)

        for field_name, (stmt_key, candidates) in self._STATEMENT_FACTS.items():
            parsed = _annual_fact(financials.get(stmt_key), candidates)
            if parsed is not None:
                out[field_name] = SourceValue(
                    field_name, parsed[0], self.name, as_of=parsed[1], unit="USD"
                )
        return out


# --------------------------------------------------------------------------- #
#  SEC EDGAR (real fundamentals from filings — no API key, needs User-Agent)  #
# --------------------------------------------------------------------------- #

class SecEdgarSource(DataSource):
    """Best-effort adapter for SEC EDGAR companyfacts (US tickers).

    Uses the public ``companyfacts`` API. Requires a descriptive User-Agent per
    SEC policy. Degrades to ``{}`` on any failure (non-US ticker, no network,
    rate limit) so it never breaks the pipeline.
    """

    name = "sec_edgar"
    _TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
    _FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

    # Canonical field -> candidate us-gaap concept tags. **All candidates are
    # scanned and the most recently reported one wins** — order is only the
    # tie-break when two tags cover the same period, so preferred tags go first.
    #
    # It used to be "first tag that exists wins", which silently returned figures
    # a decade stale: companies retire tags (ASC 606 moved revenue off `Revenues`),
    # but the retired tag stays in companyfacts forever with its last historical
    # value. Measured 2026-08-18 against the live API: MSFT resolved to `Revenues`
    # from **FY2010** (62.48 B), CRM to **FY2017** (8.39 B), and MA to
    # `NetIncomeLoss` from **FY2013** (3.12 B) — MA reports under `ProfitLoss` now,
    # a tag that was not even in this list.
    _CONCEPTS = {
        "total_revenue": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ],
        "net_income": ["NetIncomeLoss", "ProfitLoss"],
        "total_equity": ["StockholdersEquity"],
        "total_assets": ["Assets"],
    }

    # A fiscal year, with slack for 52/53-week calendars.
    _MIN_ANNUAL_DAYS = 330
    _MAX_ANNUAL_DAYS = 400

    # The ticker->CIK map is a ~1 MB download that does not change within a
    # session, but ``default_fundamental_sources()`` builds a fresh adapter per
    # ticker — so an instance-level cache made the screener re-download it once
    # per ticker, six worker threads at a time. Shared at class level and guarded,
    # so the pool pays for it once and SEC sees one request instead of N.
    _cik_map: Optional[Dict[str, int]] = None
    _cik_lock = threading.Lock()

    def _http_json(self, url: str) -> Optional[dict]:
        try:
            import requests

            headers = {"User-Agent": MULTI_SOURCE.sec_user_agent}
            resp = requests.get(url, headers=headers, timeout=MULTI_SOURCE.request_timeout_s)
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as exc:
            logger.debug(f"SecEdgarSource: request failed {url} — {exc}")
            return None

    def _resolve_cik(self, symbol: str) -> Optional[int]:
        cls = type(self)
        with cls._cik_lock:
            if cls._cik_map is None:
                data = self._http_json(self._TICKER_MAP_URL)
                if not data:
                    return None          # not cached: a transient failure must stay retryable
                cls._cik_map = {
                    str(row["ticker"]).upper(): int(row["cik_str"])
                    for row in data.values()
                    if row.get("ticker") and row.get("cik_str") is not None
                }
        return cls._cik_map.get(symbol.upper())

    @classmethod
    def _annual_rows(cls, concept_facts: dict) -> List[dict]:
        """Every 10-K datapoint that really covers a full fiscal year.

        Two filters the previous version lacked, each one a measured bug:

        - **Duration 330-400 days.** ``form=10-K`` and ``fp=FY`` are not enough: a
          10-K also carries quarterly duration facts tagged that way. With no span
          check, the "latest annual" revenue for KLAC resolved to a **10-Q
          half-year from 2011** (1.45 B against a real 13.58 B), an 89 % apparent
          discrepancy that was entirely an artifact of this function.
        - **No fallback to "any row with a val".** That fallback is what reached
          for quarterly data whenever a tag had no annual rows at all. A field we
          cannot date properly is better dropped than guessed.

        Instant facts (equity, assets) carry no ``start``; they are kept on ``end``.
        """
        units = (concept_facts or {}).get("units", {})
        rows = units.get("USD") or units.get("shares") or []
        out: List[dict] = []
        for r in rows:
            if "val" not in r or not r.get("end"):
                continue
            if not str(r.get("form", "")).startswith("10-K"):
                continue
            start = r.get("start")
            if start:
                try:
                    span = (date.fromisoformat(r["end"]) - date.fromisoformat(start)).days
                except (ValueError, TypeError):
                    continue
                if not (cls._MIN_ANNUAL_DAYS <= span <= cls._MAX_ANNUAL_DAYS):
                    continue
            out.append(r)
        return out

    @classmethod
    def _latest_annual(cls, us_gaap: dict, tags: List[str]) -> Optional[tuple]:
        """``(value, as_of)`` for the most recently reported full year across *tags*.

        Scans every candidate tag rather than stopping at the first that exists,
        so a tag the company retired years ago cannot outrank the one it files
        under today. Ties on ``end`` go to the earlier tag in *tags*.
        """
        best: Optional[dict] = None
        for tag in tags:
            facts = (us_gaap or {}).get(tag)
            if not facts:
                continue
            for row in cls._annual_rows(facts):
                if best is None or row["end"] > best["end"]:
                    best = row
        if best is None:
            return None
        value = _f(best.get("val"))
        if value is None:
            return None
        return value, best.get("end")

    def fetch_fundamentals(self, symbol: str) -> Dict[str, SourceValue]:
        cik = self._resolve_cik(symbol)
        if cik is None:
            return {}
        facts = self._http_json(self._FACTS_URL.format(cik=cik))
        if not facts:
            return {}
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        out: Dict[str, SourceValue] = {}
        for field_name, tags in self._CONCEPTS.items():
            parsed = self._latest_annual(us_gaap, tags)
            if parsed is not None:
                out[field_name] = SourceValue(
                    field_name, parsed[0], self.name, as_of=parsed[1], unit="USD"
                )
        return out


# --------------------------------------------------------------------------- #
#  FRED (macro series — needs an API key; graceful without)                   #
# --------------------------------------------------------------------------- #

class FredSource(DataSource):
    """Macro series from FRED. Not a per-ticker fundamentals source; exposes a
    helper to fetch the latest value of a series (e.g. CPI, Fed Funds). Returns
    {} for ``fetch_fundamentals`` (kept for interface symmetry)."""

    name = "fred"
    _SERIES_URL = "https://api.stlouisfed.org/fred/series/observations"

    def fetch_fundamentals(self, symbol: str) -> Dict[str, SourceValue]:
        return {}

    def latest_series_value(self, series_id: str) -> Optional[SourceValue]:
        if not MULTI_SOURCE.fred_api_key:
            logger.debug("FredSource: no FRED_API_KEY set — skipping.")
            return None
        try:
            import requests

            params = {
                "series_id": series_id,
                "api_key": MULTI_SOURCE.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            }
            resp = requests.get(self._SERIES_URL, params=params, timeout=MULTI_SOURCE.request_timeout_s)
            if resp.status_code != 200:
                return None
            obs = (resp.json().get("observations") or [])
            if not obs:
                return None
            v = _f(obs[0].get("value"))
            if v is None:
                return None
            return SourceValue(series_id, v, self.name, as_of=obs[0].get("date"))
        except Exception as exc:
            logger.debug(f"FredSource: {series_id} failed — {exc}")
            return None


class FmpSource(DataSource):
    """Financial Modeling Prep cross-check (needs an API key; graceful without).

    Pulls the same canonical raw facts as a third independent opinion. Returns
    ``{}`` when no key is set or the request fails.
    """

    name = "fmp"
    _PROFILE_URL = "https://financialmodelingprep.com/api/v3/profile/{symbol}"
    _INCOME_URL = "https://financialmodelingprep.com/api/v3/income-statement/{symbol}"

    def fetch_fundamentals(self, symbol: str) -> Dict[str, SourceValue]:
        if not MULTI_SOURCE.fmp_api_key:
            logger.debug("FmpSource: no FMP_API_KEY set — skipping.")
            return {}
        try:
            import requests

            key = MULTI_SOURCE.fmp_api_key
            timeout = MULTI_SOURCE.request_timeout_s
            out: Dict[str, SourceValue] = {}

            prof = requests.get(self._PROFILE_URL.format(symbol=symbol),
                                params={"apikey": key}, timeout=timeout)
            if prof.status_code == 200 and prof.json():
                p = prof.json()[0]
                for fld, raw in (("current_price", p.get("price")), ("market_cap", p.get("mktCap"))):
                    v = _f(raw)
                    if v is not None:
                        out[fld] = SourceValue(fld, v, self.name)

            inc = requests.get(self._INCOME_URL.format(symbol=symbol),
                               params={"apikey": key, "limit": 1}, timeout=timeout)
            if inc.status_code == 200 and inc.json():
                row = inc.json()[0]
                as_of = row.get("date")
                for fld, raw in (("total_revenue", row.get("revenue")), ("net_income", row.get("netIncome"))):
                    v = _f(raw)
                    if v is not None:
                        out[fld] = SourceValue(fld, v, self.name, as_of=as_of, unit="USD")
            return out
        except Exception as exc:
            logger.debug(f"FmpSource: {symbol} failed — {exc}")
            return {}


def default_fundamental_sources() -> list:
    """The fundamentals sources used in production.

    yfinance + SEC EDGAR always; FMP is added only when an API key is configured
    (it's the optional third cross-check).
    """
    sources = [YFinanceSource(), SecEdgarSource()]
    if MULTI_SOURCE.fmp_api_key:
        sources.append(FmpSource())
    return sources
