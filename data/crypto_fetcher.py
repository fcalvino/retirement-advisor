"""
Crypto data fetching utilities.

Wraps yfinance for crypto OHLCV price history and computes supplemental
metrics (volatility, drawdown, halving cycle position) that replace the
equity-specific financial-statement metrics.

All functions use the same SQLite cache infrastructure as data.fetcher.
No external APIs beyond yfinance are required — the project stays
dependency-free for the BTC MVP.

Usage:
    from data.crypto_fetcher import get_crypto_info, compute_crypto_metrics
    from data.fetcher import get_history   # price bars — reused directly

    info    = get_crypto_info("BTC-USD")
    history = get_history("BTC-USD", period="10y", interval="1wk")
    metrics = compute_crypto_metrics("BTC-USD", info, history)
"""

from __future__ import annotations

from datetime import date
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

# ---------------------------------------------------------------------------
# Known BTC halving dates (block reward halving every ~210k blocks ≈ 4 years)
# ---------------------------------------------------------------------------

_BTC_HALVINGS: list[date] = [
    date(2012, 11, 28),   # Block 210,000 — reward 25 BTC
    date(2016,  7,  9),   # Block 420,000 — reward 12.5 BTC
    date(2020,  5, 11),   # Block 630,000 — reward 6.25 BTC
    date(2024,  4, 19),   # Block 840,000 — reward 3.125 BTC
    date(2028,  4, 15),   # Block 1,050,000 — reward 1.5625 BTC (estimated)
]

# ---------------------------------------------------------------------------
# Data fetching — yfinance wrapper (same cache infrastructure as fetcher.py)
# ---------------------------------------------------------------------------


def get_crypto_info(symbol: str) -> dict:
    """
    Fetch yfinance `ticker.info` for a crypto asset (e.g. "BTC-USD").

    Cached for CACHE_TTL_HOURS (default 24 h) using the same SQLite cache
    as data.fetcher.get_info().  All fields are coerced defensively so the
    caller never sees a raw yfinance KeyError.

    Returns a normalized dict with keys:
        currentPrice, marketCap, volume24h,
        circulatingSupply, maxSupply,
        fiftyTwoWeekHigh, fiftyTwoWeekLow,
        longName
    Any missing field defaults to 0.0 or "".
    """
    # Reuse the shared get_info() which already has retry + cache logic
    from data.fetcher import get_info, _safe_float
    raw = get_info(symbol)
    if not raw:
        logger.warning(f"{symbol}: crypto info fetch returned empty dict")
        return {}

    # Normalise field names — yfinance uses camelCase inconsistently across versions
    price = _safe_float(raw.get("currentPrice") or raw.get("regularMarketPrice"))
    mcap  = _safe_float(raw.get("marketCap"))

    # circulatingSupply sometimes lives under different keys
    circ  = _safe_float(
        raw.get("circulatingSupply")
        or raw.get("sharesOutstanding")   # yfinance quirk
    )
    max_s = _safe_float(raw.get("maxSupply"))

    # If marketCap missing but price + supply available, derive it
    if mcap == 0.0 and price > 0 and circ > 0:
        mcap = price * circ

    return {
        "longName":          raw.get("longName", symbol),
        "currentPrice":      price,
        "marketCap":         mcap,
        "volume24h":         _safe_float(raw.get("volume24Hr") or raw.get("regularMarketVolume")),
        "circulatingSupply": circ,
        "maxSupply":         max_s,
        "fiftyTwoWeekHigh":  _safe_float(raw.get("fiftyTwoWeekHigh")),
        "fiftyTwoWeekLow":   _safe_float(raw.get("fiftyTwoWeekLow")),
    }


# ---------------------------------------------------------------------------
# Halving cycle logic
# ---------------------------------------------------------------------------


def _halving_position(today: date | None = None) -> Tuple[str, int, int]:
    """
    Return (phase_label, days_since_last_halving, days_to_next_halving).

    Phase labels:
        "pre-halving"  — within 180 days before the next halving
        "post-halving" — within 365 days after the last halving
        "mid-cycle"    — everything else
    """
    if today is None:
        today = date.today()

    halvings = sorted(_BTC_HALVINGS)
    past     = [h for h in halvings if h <= today]
    future   = [h for h in halvings if h > today]

    last_halving = past[-1] if past else halvings[0]
    next_halving = future[0] if future else date(2028, 4, 15)

    days_since = (today - last_halving).days
    days_to    = (next_halving - today).days

    if days_to <= 180:
        phase = "pre-halving"
    elif days_since <= 365:
        phase = "post-halving"
    else:
        phase = "mid-cycle"

    return phase, days_since, days_to


# ---------------------------------------------------------------------------
# Derived metrics from price history
# ---------------------------------------------------------------------------


def compute_crypto_metrics(
    symbol: str,
    info: dict,
    price_df: pd.DataFrame,
) -> dict:
    """
    Compute crypto-specific metrics from yfinance price history.

    All calculations use only the price DataFrame (weekly bars, 10Y)
    returned by data.fetcher.get_history() — no external API calls.

    Returns a dict with:
        annualized_volatility_pct  — 52-week annualised vol from weekly returns (%)
        max_drawdown_pct           — max peak-to-trough decline over full history (%)
        cagr_4y_pct                — 4-year price CAGR as an adoption proxy (%)
        supply_scarcity_pct        — circulating / max_supply × 100 (% issued so far)
        halving_cycle_position     — "pre-halving" | "post-halving" | "mid-cycle" | "unknown"
        days_since_last_halving    — integer days since last BTC halving (BTC only)
        days_to_next_halving       — integer days to estimated next BTC halving (BTC only)
        market_cap_b               — market cap in billions USD
    """
    result: Dict[str, object] = {
        "annualized_volatility_pct": None,
        "max_drawdown_pct":          None,
        "cagr_4y_pct":               None,
        "supply_scarcity_pct":       None,
        "halving_cycle_position":    "unknown",
        "days_since_last_halving":   None,
        "days_to_next_halving":      None,
        "market_cap_b":              (info.get("marketCap") or 0) / 1e9,
    }

    # --- Supply scarcity ---
    circ  = info.get("circulatingSupply", 0) or 0
    max_s = info.get("maxSupply", 0) or 0
    if circ > 0 and max_s > 0:
        result["supply_scarcity_pct"] = round(circ / max_s * 100, 2)

    # --- Halving cycle (BTC-specific; safe default for other cryptos) ---
    if "BTC" in symbol.upper():
        phase, since, to_next = _halving_position()
        result["halving_cycle_position"]  = phase
        result["days_since_last_halving"] = since
        result["days_to_next_halving"]    = to_next

    # --- Price-based metrics require at least a few bars ---
    if price_df is None or price_df.empty:
        logger.warning(f"{symbol}: empty price history — skipping vol/drawdown/CAGR")
        return result

    # Normalise column names (yfinance may return Title or lowercase)
    df = price_df.copy()
    df.columns = [c.lower() for c in df.columns]

    # Ensure DatetimeIndex for resample (yfinance may return RangeIndex on some versions)
    if not isinstance(df.index, pd.DatetimeIndex):
        # Try to convert from a "Date" or "Datetime" column
        for candidate in ("date", "datetime", "Date", "Datetime"):
            if candidate in df.columns:
                df = df.set_index(candidate)
                df.index = pd.to_datetime(df.index)
                break
        else:
            logger.warning(f"{symbol}: price_df has no DatetimeIndex — skipping CAGR")
            # Vol and drawdown still work without resample
    if isinstance(df.index, pd.DatetimeIndex):
        df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index

    close = df["close"].dropna() if "close" in df.columns else pd.Series(dtype=float)
    if len(close) < 4:
        return result

    # Annualised volatility — std of weekly log-returns × √52
    log_ret = np.log(close / close.shift(1)).dropna()
    if len(log_ret) >= 4:
        # Use last 52 weeks for recency; fall back to full history if shorter
        window = log_ret.iloc[-52:] if len(log_ret) >= 52 else log_ret
        result["annualized_volatility_pct"] = round(float(window.std() * np.sqrt(52) * 100), 1)

    # Maximum drawdown — peak-to-trough over full available history
    rolling_max = close.cummax()
    drawdown    = (close - rolling_max) / rolling_max * 100   # negative values
    result["max_drawdown_pct"] = round(float(drawdown.min()), 1)   # worst (most negative)

    # 4-year CAGR — proxy for adoption growth (requires DatetimeIndex for resample)
    from data.fetcher import compute_cagr
    if isinstance(close.index, pd.DatetimeIndex):
        annual = close.resample("YE").last().dropna().sort_index(ascending=False)
        cagr = compute_cagr(annual, years=4)
        if cagr is not None:
            result["cagr_4y_pct"] = round(cagr * 100, 1)

    logger.debug(
        f"{symbol}: crypto metrics — vol={result['annualized_volatility_pct']}% "
        f"dd={result['max_drawdown_pct']}% cagr4y={result['cagr_4y_pct']}% "
        f"halving={result['halving_cycle_position']}"
    )
    return result
