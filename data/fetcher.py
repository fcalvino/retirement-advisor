"""yfinance wrapper with caching, retries and robust error handling."""

import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger

from data.cache import cache

# Maximum attempts and base delay for exponential backoff on yfinance failures.
# N2: the policy lives in config.FETCH with the rest of the tunables.

#: Sentinel: "the feed answered, and the answer is no dividends". Distinct from a
#: failed call, which must be retried; paying nothing is not an error.
_NO_DIVIDENDS = pd.Series(dtype=float)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        return v if not pd.isna(v) else default
    except (TypeError, ValueError):
        return default


def _fetch_with_retry(fn, symbol: str, label: str):
    """
    Call fn() up to ``FETCH.max_retries`` times with exponential backoff.
    Returns the result or None on permanent failure.

    Every fetcher that reaches the network goes through here (N2). Two of the four
    used to skip it, and a transient failure on ``get_financials`` demoted a BUY
    to HOLD by way of an empty statement and a "poor" data-quality badge.
    """
    from config import FETCH

    attempts = max(1, int(FETCH.max_retries))
    delay = float(FETCH.retry_base_delay_s)
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts:
                logger.error(f"{symbol}: {label} failed after {attempts} attempts — {exc}")
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


def _drop_trailing_empty_bars(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    """Drop the trailing run of bars that have no ``close`` (U5-19).

    yfinance returns a bar for the *week in progress*; asked before that week has
    traded it comes back with OHLC all NaN and a partial ``volume``. It is not a
    price — it is the absence of one — and a single NaN at the tail makes every
    trailing rolling window NaN at once, so ``above_sma50/100/200`` and
    ``sma200_slope_pct`` all read ``None`` and the technical signal collapses to
    ``NEUTRAL``. See ``config.FetchConfig.drop_trailing_empty_bars`` for what that
    then costs downstream.

    Deliberately narrow:

    * only the **trailing** run — an interior NaN is a hole in the feed, and
      deleting it would shift the windows rather than shorten them;
    * never the whole frame — "no data at all" is already handled by the callers
      (``TechnicalAnalyzer.analyze`` bails at ``len(df) < 50``), and returning an
      empty frame here would turn a warm cache into a fetch failure;
    * ``close`` only, not ``volume`` — volume is the field that *does* arrive on
      the incomplete bar, so keying on it would keep exactly the row to drop.

    Dropping the bar shortens the series, so a ticker that genuinely lacks the
    history still answers ``None``. The fix removes the false negatives, not the
    distinction.
    """
    from config import FETCH

    if not FETCH.drop_trailing_empty_bars or df.empty:
        return df

    close_col = next((c for c in df.columns if str(c).strip().lower() == "close"), None)
    if close_col is None:
        return df

    valid = df[close_col].notna().to_numpy()
    if valid.all() or not valid.any():
        return df

    last_valid = len(valid) - 1 - int(np.argmax(valid[::-1]))
    if last_valid == len(valid) - 1:
        return df

    dropped = len(valid) - 1 - last_valid
    logger.info(
        f"{symbol or 'history'}: dropping {dropped} trailing bar(s) with no close "
        "(incomplete period)"
    )
    return df.iloc[: last_valid + 1]


def get_history(symbol: str, period: str = "10y", interval: str = "1wk") -> pd.DataFrame:
    """Return OHLCV DataFrame. Weekly bars, 10 years by default for long-term context.

    The frame is identical whether it came from the network or the cache: a
    ``DatetimeIndex`` named ``Date`` with lower-case OHLCV columns. See
    ``_restore_date_index`` for why that needs saying.

    The trailing incomplete bar is dropped on **both** paths (U5-19): filtering
    only before ``cache.set`` would leave whatever is already on disk poisoned
    until its own ``CACHE_TTL_HOURS`` runs out.
    """
    key = f"history:{symbol}:{period}:{interval}"
    cached = cache.get(key)
    if cached:
        return _drop_trailing_empty_bars(
            _restore_date_index(pd.DataFrame(cached)), symbol
        )

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
        df = _drop_trailing_empty_bars(df, symbol)
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

    # N2: through the retry, like every other networked fetch. A transient
    # failure here returns empty statements, and empty statements demote a BUY to
    # HOLD via has_financials=False and a "poor" data-quality badge — a scoring
    # consequence for one flaky HTTP call.
    def _fetch():
        ticker = yf.Ticker(symbol)
        statements = {
            "income_stmt": ticker.financials,
            "balance_sheet": ticker.balance_sheet,
            "cashflow": ticker.cashflow,
        }
        # Drop entirely empty statements
        statements = {k: v for k, v in statements.items() if v is not None and not v.empty}
        if not statements:
            raise ValueError("no financial statements available")
        return statements

    result = _fetch_with_retry(_fetch, symbol, "financials")
    if not result:
        return {}

    # Timestamps can't be JSON keys — convert columns and index to strings
    serializable = {
        k: df.rename(columns=str).rename(index=str).to_dict()
        for k, df in result.items()
    }
    cache.set(key, serializable)
    return result


def get_dividends(symbol: str) -> pd.Series:
    """Return dividend history as a Series indexed by date."""
    key = f"dividends:{symbol}"
    cached = cache.get(key)
    if cached:
        s = pd.Series(cached)
        s.index = pd.to_datetime(s.index)
        return s

    # N2: through the retry. A failure here costs the dividend dimension and the
    # growth streak. An empty series is a real answer — a company that pays
    # nothing — so it is returned rather than retried.
    def _fetch():
        ticker = yf.Ticker(symbol)
        divs = ticker.dividends
        if divs is None or divs.empty:
            return _NO_DIVIDENDS
        divs.index = divs.index.tz_localize(None)
        return divs

    divs = _fetch_with_retry(_fetch, symbol, "dividends")
    if divs is None or divs is _NO_DIVIDENDS or divs.empty:
        return pd.Series(dtype=float)
    # Convert Timestamp index to strings for JSON compatibility
    cache.set(key, {str(k): v for k, v in divs.to_dict().items()})
    return divs


def _normalize_news_item(item: Any) -> Optional[Dict[str, str]]:
    """yfinance 1.x news item → ``{title, summary, published, provider}`` (None = drop).

    Only text stories with a publication date: videos carry no summary worth
    quoting, and an undated headline cannot be a dated fact.
    """
    content = (item or {}).get("content") or {}
    if content.get("contentType") != "STORY":
        return None
    title = (content.get("title") or "").strip()
    published = (content.get("pubDate") or "")[:10]
    if not title or len(published) != 10:
        return None
    return {
        "title": title,
        "summary": (content.get("summary") or "").strip(),
        "published": published,
        "provider": ((content.get("provider") or {}).get("displayName") or "").strip(),
    }


def get_news(symbol: str) -> List[Dict[str, str]]:
    """Recent dated headlines for *symbol* (#130 paso 7). Cached; ``[]`` on failure."""
    key = f"news:{symbol}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    def _fetch():
        return yf.Ticker(symbol).news or []

    raw = _fetch_with_retry(_fetch, symbol, "news")
    if raw is None:
        return []
    items = [n for n in (_normalize_news_item(i) for i in raw) if n]
    cache.set(key, items)
    return items


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
