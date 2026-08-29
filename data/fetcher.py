"""yfinance wrapper with caching, retries and robust error handling."""

import time
from typing import Any, Dict, Optional, Tuple

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


_DATE_COLUMNS = ("date", "datetime", "index", "level_0")


def _restore_date_index(df: pd.DataFrame) -> pd.DataFrame:
    """Put a cached price frame back into the shape a fresh fetch returns.

    The cache stores ``df.reset_index().to_dict(orient="records")``, which turns the
    ``DatetimeIndex`` into a plain ``"Date"`` column and leaves a ``RangeIndex``
    behind. So ``get_history`` returned **two different shapes** depending on cache
    state — a bug that only appears once something is cached, which is exactly when
    nobody is looking.

    What it cost: ``track_record_scorer._price_on_or_before`` guards with
    ``if "date" in df.columns`` (lower case) against a column named ``"Date"``, so on
    a warm cache it never reindexes, compares integers to a ``Timestamp``, raises
    ``TypeError`` — and the surrounding ``except`` swallows it into "cannot score
    yet / skip". That is the scorer that fills ``recommendation_outcome``, the only
    empirical evidence this project has for calibrating anything. The Stock Analysis
    price chart plots ``x=hist.index`` and silently drew bar numbers instead of dates
    on the same warm cache.

    Restoring on *read* rather than changing the write format is deliberate: entries
    already on disk are in the records format, and a new format would make them
    unreadable without a word.
    """
    if df.empty:
        return df

    for candidate in df.columns:
        if str(candidate).strip().lower() not in _DATE_COLUMNS:
            continue
        try:
            index = pd.to_datetime(df[candidate])
        except (TypeError, ValueError):
            continue
        if index.isna().any():
            # Some pandas versions coerce unparseable values to NaT instead of
            # raising. A NaT in the index is worse than leaving the frame alone.
            continue
        df = df.drop(columns=[candidate])
        df.index = index
        df.index.name = "Date"
        return df.sort_index()

    return df


def get_history(symbol: str, period: str = "10y", interval: str = "1wk") -> pd.DataFrame:
    """Return OHLCV DataFrame. Weekly bars, 10 years by default for long-term context.

    The frame is identical whether it came from the network or the cache: a
    ``DatetimeIndex`` named ``Date`` with lower-case OHLCV columns. See
    ``_restore_date_index`` for why that needs saying.
    """
    key = f"history:{symbol}:{period}:{interval}"
    cached = cache.get(key)
    if cached:
        return _restore_date_index(pd.DataFrame(cached))

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


def get_info_age_hours(symbol: str) -> Optional[float]:
    """Hours since ``ticker.info`` was cached for *symbol* (None = not cached).

    Used by the data-quality layer (Fase E) to flag stale data in the
    dashboard. Read-only — never triggers a network fetch.
    """
    return cache.get_age_hours(f"info:{symbol}")


def compute_cagr(series: pd.Series, years: int) -> Optional[float]:
    """
    Compute CAGR from an annual time series (most recent value first).
    Returns None if insufficient data.

    Fixed window: needs ``years + 1`` points or it gives up. Callers that would
    rather measure the window they have should use ``compute_cagr_available``.
    """
    series = series.dropna()
    if len(series) < years + 1:
        return None
    end_val = series.iloc[0]
    start_val = series.iloc[years]
    if start_val <= 0 or end_val <= 0:
        return None
    return (end_val / start_val) ** (1 / years) - 1


def compute_cagr_available(
    series: pd.Series,
    *,
    target_years: int,
    min_years: int,
) -> Tuple[Optional[float], int]:
    """CAGR over the longest window the data supports, with the window returned.

    Returns ``(cagr, years_used)``; ``(None, 0)`` when even ``min_years`` is not
    covered, or when the start value is non-positive (no meaningful rate off a
    zero or negative base).

    Why this exists: ``compute_cagr(series, years=5)`` needs six annual points and
    yfinance's statements carry **four**, so every `years=5` call in the scoring
    engine returned ``None`` for every company — measured 78/78 on the US Quality
    universe, 2026-08-17. The revenue data was there and fine (MSFT's four periods
    give 16.1%/yr over three years); only the demand for a six-point window was
    unmeetable. Nothing free supplies six years, so the fix is to compute over the
    window that exists and report which one it was, rather than silently drop the
    metric and the 7 score points that depend on it.

    The window is capped at ``target_years`` so tickers with deeper history stay
    comparable to the rest instead of being measured over a longer, gentler span.
    """
    series = series.dropna()
    n_points = len(series)
    if n_points < min_years + 1:
        return None, 0

    years = min(target_years, n_points - 1)
    end_val = series.iloc[0]
    start_val = series.iloc[years]
    if start_val <= 0 or end_val <= 0:
        return None, 0

    return (end_val / start_val) ** (1 / years) - 1, years


def usd_ars_quote(symbol: str = "ARS=X"):
    """Official USD/ARS rate and the date it is from, or ``None`` (N1).

    Goes through :func:`get_history`, so it shares the cache, the TTL and the
    failure handling of every other price this project fetches — no second
    mechanism for talking to the same feed.

    Returns ``(pesos_per_usd, "YYYY-MM-DD")``. ``None`` when the quote is missing
    or non-positive: the caller falls back to the placeholder and labels it as
    one, because a fabricated rate that looks sourced is what would unlock a
    brecha that describes nothing.
    """
    try:
        hist = get_history(symbol, period="5d", interval="1d")
    except Exception as exc:
        logger.debug(f"usd_ars_quote: {symbol} failed — {exc}")
        return None
    if hist is None or hist.empty or "close" not in hist.columns:
        return None
    closes = hist["close"].dropna()
    if closes.empty:
        return None
    rate = float(closes.iloc[-1])
    if rate <= 0:
        return None
    return rate, str(closes.index[-1])[:10]
