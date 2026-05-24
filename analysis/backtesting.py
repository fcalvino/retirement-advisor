"""
Backtesting Engine — Phase 2

Evaluates the historical price performance of stocks selected by the
fundamental scoring model, comparing against a benchmark (default: SPY).

KNOWN LIMITATION — Lookahead bias in fundamental signals:
  yfinance does not provide point-in-time fundamental snapshots. Scores are
  computed from *current* financial statements (last 4–5 annual periods).
  This means we are measuring whether stocks that score well TODAY also had
  strong historical price returns — a valid model-quality check, but not a
  true walk-forward simulation. Price-derived metrics (CAGR, Sharpe, Drawdown)
  are clean and free of lookahead bias.

What the backtest answers:
  "If I had bought the top-N scoring stocks N years ago and held equal-weight,
   how would I have done vs SPY?"
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

from config import DB_PATH
from data.fetcher import get_history

RESULTS_DIR = DB_PATH.parent / "backtests"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

RISK_FREE_RATE = 0.045  # 4.5 % annual (proxy for 10Y Treasury)


# ------------------------------------------------------------------ #
#  Result dataclasses                                                  #
# ------------------------------------------------------------------ #

@dataclass
class TickerPerformance:
    symbol: str
    score: float            # adjusted_score used for ranking
    cagr_pct: float
    sharpe: float
    sortino: float          # downside-risk adjusted return
    max_drawdown_pct: float
    volatility_pct: float
    win_rate_pct: float     # % of weeks beating benchmark
    total_return_pct: float
    alpha_pct: float        # cagr − benchmark cagr


@dataclass
class BacktestResult:
    run_date: str
    period_years: int
    start_date: str
    end_date: str
    benchmark: str
    top_n: int
    universe_size: int

    rebalance_freq: str = "annual"   # "annual" | "quarterly" | "monthly" | "buy_and_hold"

    # Portfolio-level metrics
    portfolio_cagr_pct: float = 0.0
    portfolio_sharpe: float = 0.0
    portfolio_sortino: float = 0.0
    portfolio_max_drawdown_pct: float = 0.0
    portfolio_volatility_pct: float = 0.0
    portfolio_total_return_pct: float = 0.0
    portfolio_win_rate_pct: float = 0.0
    calmar_ratio: float = 0.0

    benchmark_cagr_pct: float = 0.0
    benchmark_total_return_pct: float = 0.0
    alpha_pct: float = 0.0          # portfolio CAGR − benchmark CAGR

    # Equity curves: ISO date string → normalized value (base = 100)
    portfolio_curve: Dict[str, float] = field(default_factory=dict)
    benchmark_curve: Dict[str, float] = field(default_factory=dict)
    drawdown_curve: Dict[str, float] = field(default_factory=dict)

    # Per-ticker breakdown (all universe tickers, not just top-N)
    ticker_results: List[TickerPerformance] = field(default_factory=list)

    # Score vs realized-return pairs for correlation scatter
    score_vs_return: List[Dict] = field(default_factory=list)

    notes: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ #
#  Engine                                                              #
# ------------------------------------------------------------------ #

class BacktestEngine:
    """
    Systematic equal-weight backtest of the fundamental scoring strategy.

    Usage:
        engine = BacktestEngine()
        result = engine.run(scored_fund_results, period_years=5, top_n=10)
        engine.save(result)
    """

    def __init__(self, risk_free_rate: float = RISK_FREE_RATE):
        self.rf = risk_free_rate

    # ---------------------------------------------------------------- #
    #  Public API                                                        #
    # ---------------------------------------------------------------- #

    def run(
        self,
        scored_results: list,           # List[FundamentalResult] — already scored
        period_years: int = 5,
        top_n: int = 10,
        benchmark: str = "SPY",
        rebalance_freq: str = "annual", # "annual" | "quarterly" | "monthly" | "buy_and_hold"
    ) -> BacktestResult:
        """
        Run backtest and return a fully populated BacktestResult.

        Args:
            scored_results:  FundamentalResult objects with adjusted_score populated.
            period_years:    How many years of history to use (1–10).
            top_n:           Number of top-scoring tickers to include in portfolio.
            benchmark:       Ticker used as benchmark (default SPY).
            rebalance_freq:  How often to rebalance back to equal weight.
                             "buy_and_hold" skips rebalancing entirely.
        """
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=period_years * 365 + 30)  # +30 day buffer
        period_str = f"{period_years + 1}y"  # fetch a bit more than needed

        result = BacktestResult(
            run_date=datetime.now().isoformat(),
            period_years=period_years,
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=end_dt.strftime("%Y-%m-%d"),
            benchmark=benchmark,
            top_n=top_n,
            universe_size=len(scored_results),
            rebalance_freq=rebalance_freq,
        )
        result.notes.append(
            "⚠️ Scores use current financials — lookahead bias in fundamental signals. "
            "Price metrics (CAGR, Sharpe, Drawdown) are clean."
        )

        # Rank by adjusted_score
        valid = [r for r in scored_results if r.adjusted_score > 0 and r.symbol]
        sorted_all = sorted(valid, key=lambda r: r.adjusted_score, reverse=True)
        top_results = sorted_all[:top_n]
        top_tickers = [r.symbol for r in top_results]

        logger.info(f"Backtest top-{top_n}: {top_tickers}")
        result.notes.append(f"Portfolio: {', '.join(top_tickers)}")

        # Benchmark prices
        bench_hist = get_history(benchmark, period=period_str, interval="1wk")
        if bench_hist.empty:
            result.notes.append(f"ERROR: Could not fetch {benchmark} history.")
            return result
        bench_prices = self._prices_from_hist(bench_hist)
        bench_prices = bench_prices[bench_prices.index >= pd.Timestamp(start_dt)]

        # Fetch top-N ticker prices
        top_prices: Dict[str, pd.Series] = {}
        for sym in top_tickers:
            s = self._fetch_prices(sym, period_str, start_dt)
            if s is not None:
                top_prices[sym] = s
            else:
                result.notes.append(f"No price history for {sym} — excluded from portfolio.")

        if not top_prices:
            result.notes.append("ERROR: No price data available for any portfolio ticker.")
            return result

        # Build portfolio equity curve aligned to benchmark dates
        port_curve = self._equal_weight_curve(top_prices, bench_prices.index, rebalance_freq)
        if len(port_curve) < 10:
            result.notes.append("Insufficient overlapping price data.")
            return result

        # Align both curves on their common dates
        port_curve, bench_curve = self._align(port_curve, bench_prices)

        if len(port_curve) < 10:
            result.notes.append("Insufficient overlapping price data after alignment.")
            return result

        # Normalize to 100
        port_norm = port_curve / port_curve.iloc[0] * 100
        bench_norm = bench_curve / bench_curve.iloc[0] * 100

        # Portfolio metrics
        pm = self._metrics(port_curve, bench_curve)
        result.portfolio_cagr_pct = pm["cagr"]
        result.portfolio_sharpe = pm["sharpe"]
        result.portfolio_sortino = pm["sortino"]
        result.portfolio_max_drawdown_pct = pm["max_drawdown"]
        result.portfolio_volatility_pct = pm["volatility"]
        result.portfolio_total_return_pct = pm["total_return"]
        result.portfolio_win_rate_pct = pm["win_rate"]
        result.calmar_ratio = pm["calmar"]

        bm = self._metrics(bench_curve)
        result.benchmark_cagr_pct = bm["cagr"]
        result.benchmark_total_return_pct = bm["total_return"]
        result.alpha_pct = round(result.portfolio_cagr_pct - result.benchmark_cagr_pct, 2)

        # Drawdown curve
        rolling_max = port_norm.cummax()
        drawdown = (port_norm - rolling_max) / rolling_max * 100

        result.portfolio_curve = self._series_to_dict(port_norm)
        result.benchmark_curve = self._series_to_dict(bench_norm)
        result.drawdown_curve = self._series_to_dict(drawdown)

        # Per-ticker performance (full universe)
        for fund_result in sorted_all:
            sym = fund_result.symbol
            s = self._fetch_prices(sym, period_str, start_dt)
            if s is None or len(s) < 10:
                continue
            s_aligned, b_aligned = self._align(s, bench_prices)
            if len(s_aligned) < 10:
                continue
            tm = self._metrics(s_aligned, b_aligned)
            result.ticker_results.append(TickerPerformance(
                symbol=sym,
                score=fund_result.adjusted_score,
                cagr_pct=tm["cagr"],
                sharpe=tm["sharpe"],
                sortino=tm["sortino"],
                max_drawdown_pct=tm["max_drawdown"],
                volatility_pct=tm["volatility"],
                win_rate_pct=tm["win_rate"],
                total_return_pct=tm["total_return"],
                alpha_pct=round(tm["cagr"] - bm["cagr"], 2),
            ))
            result.score_vs_return.append({
                "symbol": sym,
                "score": fund_result.adjusted_score,
                "cagr_pct": tm["cagr"],
                "total_return_pct": tm["total_return"],
            })

        return result

    # ---------------------------------------------------------------- #
    #  Persistence                                                       #
    # ---------------------------------------------------------------- #

    def save(self, result: BacktestResult, filename: str = None) -> Path:
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backtest_{result.period_years}y_top{result.top_n}_{ts}.json"
        path = RESULTS_DIR / filename
        path.write_text(json.dumps(asdict(result), indent=2, default=str))
        logger.info(f"Backtest saved → {path}")
        return path

    @staticmethod
    def load(path: Path) -> BacktestResult:
        data = json.loads(path.read_text())
        tickers = [TickerPerformance(**t) for t in data.pop("ticker_results", [])]
        result = BacktestResult(**data)
        result.ticker_results = tickers
        return result

    @staticmethod
    def list_saved() -> List[Path]:
        return sorted(RESULTS_DIR.glob("backtest_*.json"), reverse=True)

    # ---------------------------------------------------------------- #
    #  Internal helpers                                                  #
    # ---------------------------------------------------------------- #

    @staticmethod
    def _normalize_index(s: pd.Series) -> pd.Series:
        """Strip timezone and normalize DatetimeIndex to date-only for consistent alignment."""
        idx = pd.to_datetime(s.index)
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        # Normalize to midnight so dates from different tz sources still match
        s = s.copy()
        s.index = idx.normalize()
        return s

    @staticmethod
    def _prices_from_hist(hist: pd.DataFrame) -> pd.Series:
        """Extract a clean, DatetimeIndex price series from a get_history() DataFrame."""
        if hist.empty:
            return pd.Series(dtype=float)
        if "Date" in hist.columns:
            hist = hist.set_index("Date")
        s = hist["close"].dropna()
        s.index = pd.to_datetime(s.index)
        if s.index.tz is not None:
            s.index = s.index.tz_convert(None)
        return s

    def _fetch_prices(
        self,
        symbol: str,
        period_str: str,
        start_dt: datetime,
    ) -> Optional[pd.Series]:
        hist = get_history(symbol, period=period_str, interval="1wk")
        if hist.empty:
            return None
        s = self._prices_from_hist(hist)
        cutoff = pd.Timestamp(start_dt)
        s = s[s.index >= cutoff]
        return s if len(s) >= 10 else None

    @staticmethod
    def _align(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
        """Return two series aligned on their common dates (inner join)."""
        combined = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
        return combined["a"], combined["b"]

    def _equal_weight_curve(
        self,
        prices: Dict[str, pd.Series],
        reference_index: pd.DatetimeIndex,
        rebalance_freq: str = "annual",
    ) -> pd.Series:
        """
        Build an equal-weight portfolio curve with optional periodic rebalancing.

        Buy-and-hold: each stock normalized to 1.0 at start, portfolio = mean.
        Rebalanced: at each rebalancing date, reset shares so every position
        is again worth 1/N of the total portfolio value.
        """
        # Align all price series to the reference (benchmark) index
        prices_df = pd.DataFrame({
            sym: s.reindex(reference_index).ffill()
            for sym, s in prices.items()
        }).dropna(how="all").ffill()

        if prices_df.empty:
            return pd.Series(dtype=float)

        syms = prices_df.columns.tolist()

        if rebalance_freq == "buy_and_hold":
            # Simple normalized average — no rebalancing
            norm = prices_df.apply(lambda col: col / col.dropna().iloc[0])
            return norm.mean(axis=1).dropna()

        # Determine rebalancing dates mapped to actual index dates
        rebal_set = self._rebalance_dates(prices_df.index, rebalance_freq)

        # Simulate share-level portfolio starting at portfolio value = 1.0
        first_row = prices_df.iloc[0]
        valid_syms = [s for s in syms if pd.notna(first_row[s]) and first_row[s] > 0]
        n_valid = len(valid_syms)
        if n_valid == 0:
            return pd.Series(dtype=float)

        # Initial shares: equal allocation of 1/n_valid per stock
        shares: Dict[str, float] = {
            sym: (1.0 / n_valid) / first_row[sym] for sym in valid_syms
        }

        portfolio = pd.Series(index=prices_df.index, dtype=float)

        for date in prices_df.index:
            row = prices_df.loc[date]
            # Current portfolio value
            value = sum(
                shares.get(sym, 0.0) * row[sym]
                for sym in valid_syms
                if pd.notna(row[sym]) and row[sym] > 0
            )
            portfolio[date] = value

            # Rebalance: redistribute value equally across available stocks
            if date in rebal_set and date != prices_df.index[0] and value > 0:
                avail = {sym: row[sym] for sym in valid_syms
                         if pd.notna(row[sym]) and row[sym] > 0}
                if avail:
                    alloc = value / len(avail)
                    shares = {sym: alloc / price for sym, price in avail.items()}

        return portfolio.dropna()

    @staticmethod
    def _rebalance_dates(index: pd.DatetimeIndex, freq: str) -> set:
        """Map target calendar rebalancing dates to the nearest actual trading dates."""
        freq_map = {
            "monthly":   "ME",
            "quarterly": "QE",
            "annual":    "YE",
        }
        pd_freq = freq_map.get(freq)
        if pd_freq is None:
            return set()
        targets = pd.date_range(index[0], index[-1], freq=pd_freq)
        actual = set()
        for td in targets:
            diffs = np.abs((index - td).view(np.int64))
            actual.add(index[int(np.argmin(diffs))])
        return actual

    def _metrics(
        self,
        prices: pd.Series,
        benchmark: pd.Series = None,
    ) -> dict:
        """Compute standard performance metrics from a weekly price series."""
        empty = {
            "cagr": 0.0, "sharpe": 0.0, "sortino": 0.0, "max_drawdown": 0.0,
            "volatility": 0.0, "total_return": 0.0, "win_rate": 0.0, "calmar": 0.0,
        }
        if prices is None or len(prices) < 4:
            return empty

        returns = prices.pct_change().dropna()
        annual_factor = 52  # weekly data

        years = max(len(prices) / annual_factor, 0.1)
        total_return = (prices.iloc[-1] / prices.iloc[0] - 1) * 100
        cagr = ((prices.iloc[-1] / prices.iloc[0]) ** (1 / years) - 1) * 100

        vol = returns.std() * np.sqrt(annual_factor) * 100
        excess = cagr / 100 - self.rf
        sharpe = round(excess / (vol / 100), 2) if vol > 0 else 0.0

        # Sortino: penalizes only downside volatility
        downside = returns[returns < 0]
        downside_vol = downside.std() * np.sqrt(annual_factor) if len(downside) > 1 else 0.0
        sortino = round(excess / downside_vol, 2) if downside_vol > 0 else 0.0

        rolling_max = prices.cummax()
        drawdown = (prices - rolling_max) / rolling_max
        max_dd = float(drawdown.min()) * 100
        calmar = round(cagr / abs(max_dd), 2) if max_dd != 0 else 0.0

        win_rate = 0.0
        if benchmark is not None and len(benchmark) >= 4:
            bench_ret = benchmark.pct_change().dropna()
            port_ret = returns.reindex(bench_ret.index).dropna()
            bench_ret = bench_ret.reindex(port_ret.index).dropna()
            if len(port_ret) > 0:
                win_rate = round(float((port_ret > bench_ret).mean()) * 100, 1)

        return {
            "cagr": round(cagr, 2),
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown": round(max_dd, 2),
            "volatility": round(vol, 2),
            "total_return": round(total_return, 2),
            "win_rate": win_rate,
            "calmar": calmar,
        }

    @staticmethod
    def _series_to_dict(s: pd.Series) -> Dict[str, float]:
        return {str(k.date()): round(float(v), 2) for k, v in s.items()}
