"""
Technical analysis module — long-term perspective.

For retirement investing we focus on:
  - Long-term trend integrity (SMA 200, EMA 200)
  - Momentum sustainability (RSI monthly, MACD weekly)
  - Avoidance of parabolic / bubble conditions
  - Volume confirmation
  - ADX trend strength

Signal output: BULLISH | NEUTRAL | BEARISH
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    import pandas_ta as ta
    HAS_TA = True
except ImportError:
    HAS_TA = False
    logger.warning("pandas_ta not available — technical indicators will be limited")

from data.fetcher import get_history


@dataclass
class TechnicalResult:
    symbol: str
    signal: str = "NEUTRAL"          # BULLISH | NEUTRAL | BEARISH
    signal_strength: int = 0         # -100 to +100
    current_price: float = 0.0

    # Trend
    above_sma50: bool = False
    above_sma100: bool = False
    above_sma200: bool = False
    sma200_slope_pct: float = 0.0     # % change of SMA200 over last 26 weeks
    golden_cross: bool = False        # SMA50 > SMA200 and recently crossed
    death_cross: bool = False

    # Momentum
    rsi_weekly: Optional[float] = None
    macd_bullish: Optional[bool] = None
    adx: Optional[float] = None       # >25 = strong trend

    # Volatility
    atr_pct: Optional[float] = None   # ATR as % of price
    near_bb_upper: bool = False       # price near Bollinger upper — caution
    near_bb_lower: bool = False       # price near Bollinger lower — opportunity

    # Volume
    volume_trend: str = "NEUTRAL"     # INCREASING | NEUTRAL | DECREASING

    # 52-week context
    price_vs_52w_high_pct: float = 0.0
    price_vs_52w_low_pct: float = 0.0

    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class TechnicalAnalyzer:
    """
    Computes technical indicators on weekly price data (10 years).
    Uses weekly bars to filter out short-term noise — appropriate for
    long-horizon investment decisions.
    """

    def analyze(self, symbol: str, df: Optional[pd.DataFrame] = None) -> TechnicalResult:
        symbol = symbol.upper()
        result = TechnicalResult(symbol=symbol)

        if df is None or df.empty:
            df = get_history(symbol, period="10y", interval="1wk")

        if df.empty or len(df) < 50:
            result.warnings.append("Insufficient price history for technical analysis")
            return result

        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        # Ensure datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        price = df["close"]
        result.current_price = float(price.iloc[-1])

        self._compute_trend(df, price, result)
        self._compute_momentum(df, price, result)
        self._compute_volatility(df, price, result)
        self._compute_volume(df, result)
        self._compute_52w_context(price, result)
        self._derive_signal(result)

        logger.info(f"{symbol}: technical signal = {result.signal} ({result.signal_strength:+d})")
        return result

    # ------------------------------------------------------------------ #
    #  Trend                                                               #
    # ------------------------------------------------------------------ #

    def _compute_trend(self, df: pd.DataFrame, price: pd.Series, result: TechnicalResult) -> None:
        last = float(price.iloc[-1])

        sma50 = price.rolling(50).mean()
        sma100 = price.rolling(100).mean()
        sma200 = price.rolling(200).mean()

        result.above_sma50 = last > float(sma50.iloc[-1]) if not pd.isna(sma50.iloc[-1]) else False
        result.above_sma100 = last > float(sma100.iloc[-1]) if not pd.isna(sma100.iloc[-1]) else False
        result.above_sma200 = last > float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else False

        # SMA200 slope — is the long-term trend rising?
        if not pd.isna(sma200.iloc[-1]) and not pd.isna(sma200.iloc[-26]):
            slope = (float(sma200.iloc[-1]) - float(sma200.iloc[-26])) / float(sma200.iloc[-26]) * 100
            result.sma200_slope_pct = round(slope, 2)
            if slope > 2:
                result.notes.append(f"SMA200 rising +{slope:.1f}% — long-term uptrend confirmed")
            elif slope < -2:
                result.warnings.append(f"SMA200 declining {slope:.1f}% — long-term downtrend")

        # Golden / Death cross (SMA50 vs SMA200)
        if not pd.isna(sma50.iloc[-1]) and not pd.isna(sma200.iloc[-1]):
            current_cross = sma50.iloc[-1] > sma200.iloc[-1]
            prev_cross = sma50.iloc[-5] > sma200.iloc[-5] if len(sma50) > 5 else current_cross
            result.golden_cross = current_cross and not prev_cross
            result.death_cross = not current_cross and prev_cross
            if result.golden_cross:
                result.notes.append("Golden Cross detected (SMA50 > SMA200) — bullish")
            if result.death_cross:
                result.warnings.append("Death Cross detected — bearish")

    # ------------------------------------------------------------------ #
    #  Momentum                                                            #
    # ------------------------------------------------------------------ #

    def _compute_momentum(self, df: pd.DataFrame, price: pd.Series, result: TechnicalResult) -> None:
        # RSI (14 periods on weekly bars = ~3.5 months)
        rsi = self._rsi(price, 14)
        if rsi is not None:
            result.rsi_weekly = round(rsi, 1)
            if rsi < 30:
                result.notes.append(f"RSI oversold {rsi:.0f} — potential entry")
            elif rsi > 75:
                result.warnings.append(f"RSI overbought {rsi:.0f} — extended, caution")

        # MACD (12/26/9) on weekly bars
        macd_line, signal_line = self._macd(price, 12, 26, 9)
        if macd_line is not None:
            result.macd_bullish = float(macd_line) > float(signal_line)
            if result.macd_bullish:
                result.notes.append("MACD bullish crossover")
            else:
                result.warnings.append("MACD below signal — bearish momentum")

        # ADX — trend strength (not direction)
        adx = self._adx(df, 14)
        if adx is not None:
            result.adx = round(adx, 1)
            if adx >= 25:
                result.notes.append(f"ADX {adx:.0f} — strong trend")
            elif adx < 15:
                result.notes.append(f"ADX {adx:.0f} — weak/ranging market")

    # ------------------------------------------------------------------ #
    #  Volatility                                                          #
    # ------------------------------------------------------------------ #

    def _compute_volatility(self, df: pd.DataFrame, price: pd.Series, result: TechnicalResult) -> None:
        last = float(price.iloc[-1])

        # ATR (14 periods weekly)
        atr = self._atr(df, 14)
        if atr is not None:
            result.atr_pct = round(atr / last * 100, 2)

        # Bollinger Bands (20, 2)
        sma20 = price.rolling(20).mean()
        std20 = price.rolling(20).std()
        upper = sma20 + 2 * std20
        lower = sma20 - 2 * std20

        if not pd.isna(upper.iloc[-1]):
            u, l = float(upper.iloc[-1]), float(lower.iloc[-1])
            band_width = u - l
            if band_width > 0:
                pct_b = (last - l) / band_width
                result.near_bb_upper = pct_b > 0.9
                result.near_bb_lower = pct_b < 0.1
                if result.near_bb_upper:
                    result.warnings.append("Price near Bollinger upper band — extended")
                if result.near_bb_lower:
                    result.notes.append("Price near Bollinger lower band — potential support")

    # ------------------------------------------------------------------ #
    #  Volume                                                              #
    # ------------------------------------------------------------------ #

    def _compute_volume(self, df: pd.DataFrame, result: TechnicalResult) -> None:
        if "volume" not in df.columns:
            return
        vol = df["volume"].dropna()
        if len(vol) < 26:
            return
        recent_avg = float(vol.iloc[-13:].mean())
        prior_avg = float(vol.iloc[-26:-13].mean())
        if prior_avg > 0:
            ratio = recent_avg / prior_avg
            if ratio > 1.2:
                result.volume_trend = "INCREASING"
                result.notes.append(f"Volume +{(ratio-1)*100:.0f}% vs prior period — institutional interest")
            elif ratio < 0.8:
                result.volume_trend = "DECREASING"
                result.warnings.append("Volume declining — waning interest")

    # ------------------------------------------------------------------ #
    #  52-Week Context                                                     #
    # ------------------------------------------------------------------ #

    def _compute_52w_context(self, price: pd.Series, result: TechnicalResult) -> None:
        recent = price.iloc[-52:] if len(price) >= 52 else price
        high52 = float(recent.max())
        low52 = float(recent.min())
        last = float(price.iloc[-1])
        if high52 > 0:
            result.price_vs_52w_high_pct = round((last / high52 - 1) * 100, 1)
        if low52 > 0:
            result.price_vs_52w_low_pct = round((last / low52 - 1) * 100, 1)

    # ------------------------------------------------------------------ #
    #  Final Signal                                                        #
    # ------------------------------------------------------------------ #

    def _derive_signal(self, result: TechnicalResult) -> None:
        score = 0

        # Trend weight = 50%
        if result.above_sma200:
            score += 25
        if result.above_sma100:
            score += 10
        if result.above_sma50:
            score += 5
        if result.sma200_slope_pct > 2:
            score += 10
        elif result.sma200_slope_pct < -2:
            score -= 10
        if result.golden_cross:
            score += 15
        if result.death_cross:
            score -= 20

        # Momentum weight = 30%
        if result.rsi_weekly is not None:
            rsi = result.rsi_weekly
            if 40 <= rsi <= 65:
                score += 15       # healthy momentum
            elif rsi < 30:
                score += 10       # oversold — entry opportunity
            elif rsi > 75:
                score -= 15       # overbought
        if result.macd_bullish is True:
            score += 10
        elif result.macd_bullish is False:
            score -= 10
        if result.adx is not None and result.adx >= 25:
            score += 5

        # Volatility weight = 20%
        if result.near_bb_upper:
            score -= 10
        if result.near_bb_lower:
            score += 10
        if result.volume_trend == "INCREASING":
            score += 5
        elif result.volume_trend == "DECREASING":
            score -= 5

        result.signal_strength = max(-100, min(100, score))
        if score >= 30:
            result.signal = "BULLISH"
        elif score <= -20:
            result.signal = "BEARISH"
        else:
            result.signal = "NEUTRAL"

    # ------------------------------------------------------------------ #
    #  Indicator calculations (pure pandas — no ta-lib dependency)         #
    # ------------------------------------------------------------------ #

    def _rsi(self, price: pd.Series, period: int = 14) -> Optional[float]:
        try:
            delta = price.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
            avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
            rs = avg_gain / avg_loss.replace(0, 1e-10)
            rsi = 100 - (100 / (1 + rs))
            val = rsi.iloc[-1]
            return float(val) if not pd.isna(val) else None
        except Exception:
            return None

    def _macd(self, price: pd.Series, fast: int, slow: int, signal: int):
        try:
            ema_fast = price.ewm(span=fast, adjust=False).mean()
            ema_slow = price.ewm(span=slow, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            return macd_line.iloc[-1], signal_line.iloc[-1]
        except Exception:
            return None, None

    def _atr(self, df: pd.DataFrame, period: int = 14) -> Optional[float]:
        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ], axis=1).max(axis=1)
            atr = tr.ewm(span=period, adjust=False).mean()
            val = atr.iloc[-1]
            return float(val) if not pd.isna(val) else None
        except Exception:
            return None

    def _adx(self, df: pd.DataFrame, period: int = 14) -> Optional[float]:
        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            prev_close = close.shift(1)
            prev_high = high.shift(1)
            prev_low = low.shift(1)

            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ], axis=1).max(axis=1)

            dm_plus = np.where((high - prev_high) > (prev_low - low), np.maximum(high - prev_high, 0), 0)
            dm_minus = np.where((prev_low - low) > (high - prev_high), np.maximum(prev_low - low, 0), 0)

            atr = tr.ewm(span=period, adjust=False).mean()
            di_plus = pd.Series(dm_plus, index=df.index).ewm(span=period, adjust=False).mean() / atr * 100
            di_minus = pd.Series(dm_minus, index=df.index).ewm(span=period, adjust=False).mean() / atr * 100

            dx = (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, 1e-10) * 100
            adx = dx.ewm(span=period, adjust=False).mean()
            val = adx.iloc[-1]
            return float(val) if not pd.isna(val) else None
        except Exception:
            return None
