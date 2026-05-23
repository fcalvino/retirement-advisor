"""
Portfolio tracker — records positions and computes performance metrics.

Metrics computed:
  - Total return, annualized return (IRR/XIRR)
  - Sharpe Ratio, Sortino Ratio
  - Max Drawdown
  - Portfolio Beta (vs SPY)
  - Sector weights
  - Dividend income received
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from config import DB_PATH
from data.fetcher import get_history, get_info

PORTFOLIO_FILE = DB_PATH.parent / "portfolio.json"


@dataclass
class Position:
    symbol: str
    shares: float
    avg_cost: float          # USD per share
    purchase_date: str       # ISO format YYYY-MM-DD
    sector: str = "Unknown"
    notes: str = ""

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost


@dataclass
class PortfolioMetrics:
    total_value: float = 0.0
    total_cost: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    annualized_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    beta: float = 1.0
    dividend_income_ytd: float = 0.0
    num_positions: int = 0


class Portfolio:
    """
    Manages the user's investment portfolio with persistent JSON storage.
    Computes performance metrics on demand.
    """

    def __init__(self, file_path: Path = PORTFOLIO_FILE):
        self.file_path = file_path
        self.positions: Dict[str, Position] = {}
        self._load()

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def add_position(
        self,
        symbol: str,
        shares: float,
        avg_cost: float,
        purchase_date: str,
        notes: str = "",
    ) -> None:
        symbol = symbol.upper()
        info = get_info(symbol)
        sector = info.get("sector", "Unknown")

        if symbol in self.positions:
            # Average down/up
            existing = self.positions[symbol]
            total_shares = existing.shares + shares
            total_cost = existing.cost_basis + shares * avg_cost
            existing.shares = total_shares
            existing.avg_cost = total_cost / total_shares
            logger.info(f"Updated {symbol}: {total_shares:.2f} shares @ ${existing.avg_cost:.2f}")
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                shares=shares,
                avg_cost=avg_cost,
                purchase_date=purchase_date,
                sector=sector,
                notes=notes,
            )
            logger.info(f"Added {symbol}: {shares:.2f} shares @ ${avg_cost:.2f}")
        self._save()

    def remove_position(self, symbol: str, shares: Optional[float] = None) -> None:
        symbol = symbol.upper()
        if symbol not in self.positions:
            logger.warning(f"{symbol} not in portfolio")
            return
        if shares is None or shares >= self.positions[symbol].shares:
            del self.positions[symbol]
            logger.info(f"Closed {symbol}")
        else:
            self.positions[symbol].shares -= shares
            logger.info(f"Reduced {symbol} by {shares:.2f} shares")
        self._save()

    # ------------------------------------------------------------------ #
    #  Valuation & Metrics                                                 #
    # ------------------------------------------------------------------ #

    def get_current_values(self) -> Dict[str, Dict]:
        """Return current market value per position."""
        values = {}
        for sym, pos in self.positions.items():
            info = get_info(sym)
            price = float(info.get("currentPrice") or info.get("regularMarketPrice") or pos.avg_cost)
            market_value = price * pos.shares
            pnl = market_value - pos.cost_basis
            pnl_pct = pnl / pos.cost_basis * 100 if pos.cost_basis > 0 else 0
            values[sym] = {
                "symbol": sym,
                "shares": pos.shares,
                "avg_cost": pos.avg_cost,
                "current_price": price,
                "cost_basis": pos.cost_basis,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "sector": pos.sector,
                "purchase_date": pos.purchase_date,
            }
        return values

    def compute_metrics(self) -> PortfolioMetrics:
        metrics = PortfolioMetrics()
        if not self.positions:
            return metrics

        values = self.get_current_values()
        metrics.num_positions = len(values)
        metrics.total_value = sum(v["market_value"] for v in values.values())
        metrics.total_cost = sum(v["cost_basis"] for v in values.values())
        metrics.total_pnl = metrics.total_value - metrics.total_cost
        metrics.total_pnl_pct = (
            metrics.total_pnl / metrics.total_cost * 100 if metrics.total_cost > 0 else 0
        )

        # Annualized return — use earliest purchase date as start
        dates = [
            datetime.fromisoformat(self.positions[s].purchase_date)
            for s in self.positions
        ]
        if dates:
            start = min(dates)
            years = max((datetime.now() - start).days / 365.25, 0.1)
            if metrics.total_cost > 0:
                metrics.annualized_return_pct = (
                    (metrics.total_value / metrics.total_cost) ** (1 / years) - 1
                ) * 100

        # Sharpe / Sortino / Drawdown from portfolio equity curve
        equity_curve = self._build_equity_curve()
        if equity_curve is not None and len(equity_curve) > 10:
            returns = equity_curve.pct_change().dropna()
            annual_factor = 52  # weekly returns
            mean_ret = returns.mean() * annual_factor
            std_ret = returns.std() * np.sqrt(annual_factor)
            rf = 0.045  # 4.5% risk-free rate

            metrics.sharpe_ratio = round((mean_ret - rf) / std_ret, 2) if std_ret > 0 else 0

            downside = returns[returns < 0]
            downside_std = downside.std() * np.sqrt(annual_factor) if len(downside) > 0 else 0
            metrics.sortino_ratio = round((mean_ret - rf) / downside_std, 2) if downside_std > 0 else 0

            rolling_max = equity_curve.cummax()
            drawdown = (equity_curve - rolling_max) / rolling_max
            metrics.max_drawdown_pct = round(float(drawdown.min()) * 100, 2)

            # Beta vs SPY
            spy = get_history("SPY", period="5y", interval="1wk")
            if not spy.empty:
                spy_ret = spy["close"].pct_change().dropna()
                port_ret = returns.reindex(spy_ret.index).dropna()
                spy_ret = spy_ret.reindex(port_ret.index).dropna()
                if len(port_ret) > 10:
                    cov = np.cov(port_ret, spy_ret)
                    metrics.beta = round(cov[0, 1] / cov[1, 1], 2) if cov[1, 1] != 0 else 1.0

        return metrics

    def get_sector_weights(self) -> Dict[str, float]:
        """Return sector → % of portfolio weight."""
        values = self.get_current_values()
        total = sum(v["market_value"] for v in values.values())
        if total == 0:
            return {}
        sector_totals: Dict[str, float] = {}
        for v in values.values():
            sector_totals[v["sector"]] = sector_totals.get(v["sector"], 0) + v["market_value"]
        return {k: round(v / total * 100, 1) for k, v in sorted(sector_totals.items(), key=lambda x: -x[1])}

    def get_position_weights(self) -> Dict[str, float]:
        values = self.get_current_values()
        total = sum(v["market_value"] for v in values.values())
        if total == 0:
            return {}
        return {sym: round(v["market_value"] / total * 100, 1) for sym, v in values.items()}

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _build_equity_curve(self) -> Optional[pd.Series]:
        """Build a weekly portfolio equity curve using historical prices."""
        try:
            curves = []
            for sym, pos in self.positions.items():
                hist = get_history(sym, period="5y", interval="1wk")
                if hist.empty:
                    continue
                weighted = hist["close"] * pos.shares
                curves.append(weighted)
            if not curves:
                return None
            combined = pd.concat(curves, axis=1).sum(axis=1).dropna()
            return combined
        except Exception as exc:
            logger.error(f"Equity curve error: {exc}")
            return None

    def _save(self) -> None:
        data = {sym: asdict(pos) for sym, pos in self.positions.items()}
        self.file_path.write_text(json.dumps(data, indent=2))

    def _load(self) -> None:
        if self.file_path.exists():
            try:
                data = json.loads(self.file_path.read_text())
                self.positions = {sym: Position(**pos) for sym, pos in data.items()}
            except Exception as exc:
                logger.error(f"Failed to load portfolio: {exc}")
