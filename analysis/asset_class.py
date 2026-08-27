"""Asset-class classification — who the fundamental scorer may judge (audit item 01).

Pure module: no network, no Streamlit, no dataframe. The whole point is that the
question "is this thing a company?" gets one answer that the screener, the row
builder and the tests all share.

Why this exists
---------------
``FundamentalAnalyzer`` scores profitability, financial health, valuation, growth
and dividends from financial statements. An index ETF, a bond fund and a coin
have none of those by construction, so the scorer does not rate them harshly —
it rates them *meaninglessly*, and the decision engine then turns that number
into an action. Measured on the US Quality universe (85 tickers, 2026-08-17):

    SPY 23.0 SELL · QQQ 23.0 SELL · VTI 23.0 SELL
    BND 25.0 SELL · SCHD 25.0 SELL · VGT 22.0 SELL

Those six were the six worst of the universe. In a retirement product they are
the canonical core. The fix is not to tune their score — it is to stop pretending
the equity score applies to them.

Resolution order (see ``AssetClassConfig``)
    1. ``quoteType`` from the data feed — authoritative and self-maintaining
    2. curated ``SECTOR_MAP`` buckets — covers feeds that return no quoteType
    3. resolved sector name — last resort ("Index", "Crypto", …)
    4. default: ``EQUITY``

Step 1 is what keeps the classification from drifting: ``SECTOR_MAP["ETF"]``
lists four symbols while ``us_quality.json`` ships six ETFs, so VGT and SCHD were
resolving to sector "Unknown" and being scored as companies.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

EQUITY = "equity"
FUND = "fund"
CRYPTO = "crypto"

#: Every class this module can return, in display order.
ALL_CLASSES = (EQUITY, FUND, CRYPTO)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def classify_asset(
    symbol: str,
    *,
    quote_type: Optional[str] = None,
    sector: Optional[str] = None,
    is_crypto: bool = False,
    config=None,
) -> str:
    """Return ``EQUITY`` | ``FUND`` | ``CRYPTO`` for one ticker.

    ``quote_type`` is the yfinance ``info["quoteType"]`` when available; passing
    ``None`` simply falls through to the curated lists, so callers that only have
    a symbol still get a usable answer.
    """
    if config is None:
        from config import ASSET_CLASS as config  # noqa: N811 — singleton default

    from config import SECTOR_MAP, normalize_crypto_ticker

    sym = _norm(symbol).upper()

    # 0. The crypto analyzer already knows what it built.
    if is_crypto:
        return CRYPTO

    # 1. Feed-provided quoteType — authoritative, needs no maintenance.
    qt = _norm(quote_type).upper()
    if qt:
        if qt in {t.upper() for t in config.crypto_quote_types}:
            return CRYPTO
        if qt in {t.upper() for t in config.fund_quote_types}:
            return FUND
        if qt == "EQUITY":
            return EQUITY

    # 2. Curated buckets — the historical mechanism, kept as a safety net.
    if sym:
        normalized = _norm(normalize_crypto_ticker(sym)).upper()
        if sym in {s.upper() for s in SECTOR_MAP.get("Crypto", [])} or normalized in {
            s.upper() for s in SECTOR_MAP.get("Crypto", [])
        }:
            return CRYPTO
        if sym in {s.upper() for s in SECTOR_MAP.get("ETF", [])}:
            return FUND

    # 3. Resolved sector name.
    sec = _norm(sector)
    if sec:
        if sec in config.crypto_sectors:
            return CRYPTO
        if sec in config.fund_sectors:
            return FUND

    return EQUITY


def classify_result(result: Any, *, quote_type: Optional[str] = None, config=None) -> str:
    """``classify_asset`` for a ``FundamentalResult``-shaped object."""
    return classify_asset(
        getattr(result, "symbol", ""),
        quote_type=quote_type,
        sector=getattr(result, "sector", ""),
        is_crypto=bool(getattr(result, "is_crypto", False)),
        config=config,
    )


def is_fundamentally_scorable(asset_class: str, *, config=None) -> bool:
    """True when the fundamental score and its derived signal mean something.

    False for funds and crypto: they have no statements to score, so the number
    the equity scorer produces for them carries no information.
    """
    if config is None:
        from config import ASSET_CLASS as config  # noqa: N811

    return _norm(asset_class).lower() in {c.lower() for c in config.scorable_classes}


def asset_class_label(asset_class: str, *, config=None) -> str:
    """Short Spanish label for a table cell / section heading."""
    if config is None:
        from config import ASSET_CLASS as config  # noqa: N811

    key = _norm(asset_class).lower() or EQUITY
    return config.labels.get(key, key)


def split_by_scorability(rows, *, key: str = "Clase", config=None):
    """Split screener rows into (scorable, non-scorable), preserving order.

    Kept here rather than in the page so the segmentation the Screener shows is
    testable without a Streamlit session.
    """
    scorable, other = [], []
    for row in rows:
        cls = row.get(key, EQUITY) if isinstance(row, Mapping) else EQUITY
        (scorable if is_fundamentally_scorable(cls, config=config) else other).append(row)
    return scorable, other
