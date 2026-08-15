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

from dataclasses import dataclass
from typing import Dict, Optional

from loguru import logger

from config import MULTI_SOURCE


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


# --------------------------------------------------------------------------- #
#  yfinance (always available — wraps the existing fetcher)                   #
# --------------------------------------------------------------------------- #

class YFinanceSource(DataSource):
    name = "yfinance"

    def fetch_fundamentals(self, symbol: str) -> Dict[str, SourceValue]:
        try:
            from data.fetcher import get_info

            info = get_info(symbol) or {}
        except Exception as exc:
            logger.warning(f"YFinanceSource: {symbol} failed — {exc}")
            return {}

        mapping = {
            "total_revenue": info.get("totalRevenue"),
            "net_income": info.get("netIncomeToCommon"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "market_cap": info.get("marketCap"),
            # Overlap with SEC EDGAR raw facts (P0.3) — absolute $, not ratios.
            "total_equity": info.get("totalStockholderEquity") or info.get("stockholdersEquity"),
            "total_assets": info.get("totalAssets"),
        }
        out: Dict[str, SourceValue] = {}
        for field_name, raw in mapping.items():
            v = _f(raw)
            if v is not None:
                out[field_name] = SourceValue(field_name, v, self.name)
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

    # canonical field -> candidate us-gaap concept tags (first hit wins)
    _CONCEPTS = {
        "total_revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        "net_income": ["NetIncomeLoss"],
        "total_equity": ["StockholdersEquity"],
        "total_assets": ["Assets"],
    }

    def __init__(self):
        self._cik_cache: Dict[str, int] = {}

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
        if symbol in self._cik_cache:
            return self._cik_cache[symbol]
        data = self._http_json(self._TICKER_MAP_URL)
        if not data:
            return None
        for row in data.values():
            if str(row.get("ticker", "")).upper() == symbol.upper():
                cik = int(row["cik_str"])
                self._cik_cache[symbol] = cik
                return cik
        return None

    @staticmethod
    def _latest_annual(concept_facts: dict) -> Optional[tuple]:
        """Return (value, as_of) for the most recent annual (FY) USD datapoint."""
        units = (concept_facts or {}).get("units", {})
        rows = units.get("USD") or units.get("shares") or []
        annual = [r for r in rows if r.get("form", "").startswith("10-K") and r.get("fp") == "FY" and "val" in r]
        if not annual:
            annual = [r for r in rows if "val" in r and r.get("end")]
        if not annual:
            return None
        best = max(annual, key=lambda r: r.get("end", ""))
        return _f(best.get("val")), best.get("end")

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
            for tag in tags:
                if tag in us_gaap:
                    parsed = self._latest_annual(us_gaap[tag])
                    if parsed and parsed[0] is not None:
                        out[field_name] = SourceValue(field_name, parsed[0], self.name, as_of=parsed[1], unit="USD")
                        break
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
