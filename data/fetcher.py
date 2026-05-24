"""yfinance wrapper with caching, retries and robust error handling."""

import time
from typing import Any, Dict, Optional

import pandas as pd
import yfinance as yf
from loguru import logger

from data.cache import cache

# Maximum attempts and base delay for exponential backoff on yfinance failures.
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0   # seconds — doubles each attempt (2s, 4s, 8s)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        return v if not pd.isna(v) else default
    except (TypeError, ValueError):
        return default


def _fetch_with_retry(fn, symbol: str, label: str):
    """
    Call fn() up to _MAX_RETRIES times with exponential backoff.
    Returns the result or None on permanent failure.
    """
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == _MAX_RETRIES:
                logger.error(f"{symbol}: {label} failed after {_MAX_RETRIES} attempts — {exc}")
                return None
            logger.warning(f"{symbol}: {label} attempt {attempt} failed ({exc}), retrying in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2


def get_info(symbol: str) -> Dict[str, Any]:
    """Return ticker.info dict. Cached for CACHE_TTL_HOURS."""
    key = f"info:{symbol}"
    cached = cache.get(key)
    if cached:
        return cached

    def _fetch():
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        if not info or info.get("regularMarketPrice") is None:
            raise ValueError("empty or incomplete info")
        return info

    info = _fetch_with_retry(_fetch, symbol, "info")
    if info:
        cache.set(key, info)
        return info
    return {}


def get_history(symbol: str, period: str = "10y", interval: str = "1wk") -> pd.DataFrame:
    """Return OHLCV DataFrame. Weekly bars, 10 years by default for long-term context."""
    key = f"history:{symbol}:{period}:{interval}"
    cached = cache.get(key)
    if cached:
        return pd.DataFrame(cached)

    def _fetch():
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            raise ValueError("empty price history")
        df.index = df.index.tz_localize(None)
        df.columns = [c.lower() for c in df.columns]
        return df

    df = _fetch_with_retry(_fetch, symbol, "history")
    if df is not None and not df.empty:
        cache.set(key, df.reset_index().to_dict(orient="records"))
        return df
    logger.warning(f"{symbol}: no price history available")
    return pd.DataFrame()


def get_financials(symbol: str) -> Dict[str, pd.DataFrame]:
    """
    Return dict with keys: income_stmt, balance_sheet, cashflow.
    Each is a DataFrame with annual columns (most recent first).
    Cached for CACHE_TTL_HOURS.
    """
    key = f"financials:{symbol}"
    cached = cache.get(key)
    if cached:
        return {
            k: pd.DataFrame(v) for k, v in cached.items()
        }

    try:
        ticker = yf.Ticker(symbol)
        result = {
            "income_stmt": ticker.financials,
            "balance_sheet": ticker.balance_sheet,
            "cashflow": ticker.cashflow,
        }
        # Drop entirely empty statements
        result = {k: v for k, v in result.items() if v is not None and not v.empty}
        if not result:
            logger.warning(f"{symbol}: no financial statements available")
            return {}

        # Timestamps can't be JSON keys — convert columns and index to strings
        serializable = {
            k: df.rename(columns=str).rename(index=str).to_dict()
            for k, df in result.items()
        }
        cache.set(key, serializable)
        return result
    except Exception as exc:
        logger.error(f"{symbol}: failed to fetch financials — {exc}")
        return {}


def get_dividends(symbol: str) -> pd.Series:
    """Return dividend history as a Series indexed by date."""
    key = f"dividends:{symbol}"
    cached = cache.get(key)
    if cached:
        s = pd.Series(cached)
        s.index = pd.to_datetime(s.index)
        return s

    try:
        ticker = yf.Ticker(symbol)
        divs = ticker.dividends
        if divs is None or divs.empty:
            return pd.Series(dtype=float)
        divs.index = divs.index.tz_localize(None)
        # Convert Timestamp index to strings for JSON compatibility
        cache.set(key, {str(k): v for k, v in divs.to_dict().items()})
        return divs
    except Exception as exc:
        logger.error(f"{symbol}: failed to fetch dividends — {exc}")
        return pd.Series(dtype=float)


def compute_cagr(series: pd.Series, years: int) -> Optional[float]:
    """
    Compute CAGR from an annual time series (most recent value first).
    Returns None if insufficient data.
    """
    series = series.dropna()
    if len(series) < years + 1:
        return None
    end_val = series.iloc[0]
    start_val = series.iloc[years]
    if start_val <= 0 or end_val <= 0:
        return None
    return (end_val / start_val) ** (1 / years) - 1
