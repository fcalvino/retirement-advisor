"""
Portfolio optimizer — Mean-Variance with retirement-grade constraints.

Entry point:
    result = PortfolioOptimizer(profile="conservative").optimize(scored_tickers)

scored_tickers is a list of dicts with at minimum:
    symbol, adjusted_score, dividend_yield, moat_score, sector

Optimization flow:
  1. Filter eligible tickers (non-ETF, score ≥ threshold)
  2. Apply ARS risk discount for Argentine ADRs in conservative/moderate profiles
  3. Build 2Y weekly price matrix → covariance matrix
  4. Compute expected return proxy per ticker
  5. SLSQP Mean-Variance (minimize negative Sharpe) with hard constraints
  6. Fallback: score-weighted allocation if SLSQP infeasible or insufficient data
  7. Generate Efficient Frontier (Monte Carlo, N=frontier_points)
  8. Compare vs current portfolio for rebalancing suggestions
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from scipy.optimize import minimize

from config import (
    OPTIMIZER,
    OPTIMIZER_PROFILES,
    SECTOR_MAP,
    ProfileConfig,
)
from data.fetcher import get_history

# Argentine ADR tickers (trade as USD ADRs, but carry ARS macro risk)
_ARS_TICKERS = {"YPF", "PAM", "CEPU", "LOMA", "TEO", "EDN"}
# ETF tickers — excluded from optimization (no fundamentals)
_ETF_TICKERS = {"SPY", "QQQ", "VTI", "BND", "GLD", "SLV", "TLT", "IEF"}


@dataclass
class TickerAllocation:
    symbol: str
    weight_pct: float          # 0–100
    expected_return_pct: float
    volatility_pct: float
    dividend_yield_pct: float
    adjusted_score: float
    moat_score: float
    sector: str
    is_ars: bool = False
    score_discounted: bool = False


@dataclass
class RebalanceSuggestion:
    symbol: str
    current_pct: float
    target_pct: float
    delta_pct: float           # positive = buy, negative = sell
    action: str                # "BUY" | "SELL" | "HOLD"


@dataclass
class OptimizationResult:
    profile_name: str
    method: str                # "mean-variance" | "score-weighted"
    tickers: List[TickerAllocation] = field(default_factory=list)

    # Portfolio-level stats
    expected_return_pct: float = 0.0
    volatility_pct: float = 0.0
    sharpe_ratio: float = 0.0
    dividend_yield_pct: float = 0.0
    moat_score_avg: float = 0.0
    adjusted_score_avg: float = 0.0

    # Sector breakdown {sector: weight_pct}
    sector_weights: Dict[str, float] = field(default_factory=dict)

    # Efficient Frontier data for scatter chart
    frontier_returns: List[float] = field(default_factory=list)
    frontier_vols: List[float] = field(default_factory=list)
    frontier_sharpes: List[float] = field(default_factory=list)

    # Rebalancing vs current portfolio
    rebalance_suggestions: List[RebalanceSuggestion] = field(default_factory=list)

    # Excluded tickers with reason
    excluded: List[Tuple[str, str]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PortfolioOptimizer:
    """
    Conservative portfolio optimizer for retirement planning.

    Uses scipy SLSQP to minimize negative Sharpe ratio subject to:
      - Weights sum to 1
      - Per-ticker upper bound (max_position_pct)
      - Per-sector upper bound (max_sector_pct)
      - Portfolio volatility ≤ max_volatility_pct
      - Portfolio dividend yield ≥ min_dividend_yield_pct
      - Minimum N positions (min_positions)
      - Per-ticker lower bound = min_weight_pct (avoids dust)

    Falls back to score-weighted allocation when:
      - Price history is unavailable for ≥ 50% of tickers
      - SLSQP finds no feasible solution
    """

    def __init__(self, profile: str = "conservative"):
        self.profile_key = profile
        self.cfg: ProfileConfig = OPTIMIZER_PROFILES.get(profile, OPTIMIZER_PROFILES["conservative"])
        self.opt = OPTIMIZER

    def optimize(
        self,
        scored_tickers: List[dict],
        current_weights: Optional[Dict[str, float]] = None,
    ) -> OptimizationResult:
        """
        Run full optimization pipeline.

        scored_tickers: list of dicts from screener/fundamental analysis.
          Required keys: symbol, adjusted_score, dividend_yield, moat_score, sector
        current_weights: {symbol: weight_pct} from Portfolio.get_position_weights()
        """
        result = OptimizationResult(
            profile_name=self.cfg.name,
            method="mean-variance",
        )

        # 1 — Filter
        eligible, excluded = self._filter_eligible(scored_tickers)
        result.excluded = excluded

        if len(eligible) < 2:
            result.warnings.append("Insuficientes tickers elegibles para optimizar.")
            result.method = "score-weighted"
            return result

        # 2 — ARS discount
        eligible = self._apply_ars_discount(eligible)

        symbols = [t["symbol"] for t in eligible]

        # 3 — Price matrix
        price_matrix = self._build_price_matrix(symbols)
        usable_symbols = list(price_matrix.columns)

        if len(usable_symbols) < 2:
            result.warnings.append("Datos de precio insuficientes. Usando score-weighted.")
            result.method = "score-weighted"
            usable_symbols = symbols

        eligible_map = {t["symbol"]: t for t in eligible}
        eligible_filtered = [eligible_map[s] for s in usable_symbols if s in eligible_map]

        if len(eligible_filtered) < self.cfg.min_positions:
            result.warnings.append(
                f"Solo {len(eligible_filtered)} tickers con datos — mínimo recomendado: {self.cfg.min_positions}."
            )

        # 4 — Expected returns & covariance
        mu = self._expected_returns(eligible_filtered)

        if len(usable_symbols) >= 2 and price_matrix.shape[1] >= 2:
            cov = self._covariance_matrix(price_matrix[usable_symbols])
            cov_available = True
        else:
            cov = np.eye(len(eligible_filtered)) * 0.04
            cov_available = False

        # 5 — Optimize
        weights = None
        if cov_available:
            weights = self._run_slsqp(mu, cov, eligible_filtered)

        if weights is None:
            result.method = "score-weighted"
            result.warnings.append("SLSQP sin solución factible — usando score-weighted.")
            weights = self._score_weighted_optimize(eligible_filtered)

        # 6 — Build result
        self._populate_result(result, eligible_filtered, weights, mu, cov if cov_available else None)

        # Post-build constraint warnings (score-weighted fallback may violate profile limits)
        if result.method == "score-weighted":
            if result.volatility_pct > self.cfg.max_volatility_pct:
                result.warnings.append(
                    f"⚠️ Vol {result.volatility_pct:.1f}% excede el techo del perfil ({self.cfg.max_volatility_pct:.0f}%). "
                    "Considera cambiar al perfil Moderado o Agresivo."
                )
            if result.dividend_yield_pct < self.cfg.min_dividend_yield_pct:
                result.warnings.append(
                    f"⚠️ Div yield {result.dividend_yield_pct:.2f}% no alcanza el mínimo del perfil ({self.cfg.min_dividend_yield_pct:.1f}%). "
                    "El universo actual no tiene suficientes tickers de alto dividendo para el perfil Conservador."
                )

        # 7 — Frontier
        if cov_available and len(eligible_filtered) >= 4:
            self._compute_frontier(result, mu, cov, eligible_filtered)

        # 8 — Rebalancing
        if current_weights:
            result.rebalance_suggestions = self._rebalancing_suggestions(
                {t["symbol"]: w for t, w in zip(eligible_filtered, weights * 100)},
                current_weights,
            )

        return result

    # ------------------------------------------------------------------ #
    #  Filtering                                                           #
    # ------------------------------------------------------------------ #

    def _filter_eligible(
        self, scored_tickers: List[dict]
    ) -> Tuple[List[dict], List[Tuple[str, str]]]:
        eligible = []
        excluded = []
        for t in scored_tickers:
            sym = t.get("symbol", "")
            score = float(t.get("adjusted_score", t.get("total_score", 0)) or 0)
            if sym in _ETF_TICKERS:
                excluded.append((sym, "ETF — excluido de optimización"))
                continue
            if score < self.opt.min_score_threshold:
                excluded.append((sym, f"Score {score:.0f} < mínimo {self.opt.min_score_threshold:.0f}"))
                continue
            eligible.append(t)
        return eligible, excluded

    def _apply_ars_discount(self, tickers: List[dict]) -> List[dict]:
        if self.profile_key == "aggressive":
            return tickers
        result = []
        for t in tickers:
            t = dict(t)
            if t["symbol"] in _ARS_TICKERS:
                original = float(t.get("adjusted_score", 0) or 0)
                t["adjusted_score"] = original * self.opt.ars_risk_discount
                t["_ars_discounted"] = True
            result.append(t)
        return result

    @staticmethod
    def _clean_div_yield(raw: float) -> float:
        """Cap suspicious dividend yields — yfinance sometimes returns bad data (>15%)."""
        return raw if 0 <= raw <= 15.0 else 0.0

    # ------------------------------------------------------------------ #
    #  Price data                                                          #
    # ------------------------------------------------------------------ #

    def _build_price_matrix(self, symbols: List[str]) -> pd.DataFrame:
        """Weekly close prices for price_history_years. Returns DataFrame indexed by date."""
        period = f"{self.opt.price_history_years}y"
        frames = {}
        for sym in symbols:
            try:
                hist = get_history(sym, period=period, interval="1wk")
                if hist.empty:
                    continue
                # get_history returns a DataFrame — index may be DatetimeIndex or Date column
                if "Date" in hist.columns:
                    hist = hist.set_index("Date")
                elif "date" in hist.columns:
                    hist = hist.set_index("date")
                close_col = "close" if "close" in hist.columns else "Close"
                if close_col not in hist.columns:
                    continue
                series = hist[close_col].dropna()
                if len(series) >= self.opt.price_history_years * 40:
                    frames[sym] = series
            except Exception as exc:
                logger.warning(f"Price data failed for {sym}: {exc}")

        if not frames:
            return pd.DataFrame()

        matrix = pd.DataFrame(frames)
        matrix.index = pd.to_datetime(matrix.index)
        matrix = matrix.sort_index().dropna(how="all")
        # Drop tickers with too many missing prices
        min_obs = self.opt.price_history_years * 40
        matrix = matrix.loc[:, matrix.count() >= min_obs]
        matrix = matrix.ffill().dropna()
        return matrix

    # ------------------------------------------------------------------ #
    #  Expected returns & covariance                                       #
    # ------------------------------------------------------------------ #

    def _expected_returns(self, tickers: List[dict]) -> np.ndarray:
        """
        Composite expected return proxy per ticker.
        Blends adjusted_score, dividend_yield, and moat_score
        using the profile's objective weights.
        """
        cfg = self.cfg
        mu = []
        for t in tickers:
            score = float(t.get("adjusted_score", 0) or 0)
            div = self._clean_div_yield(float(t.get("dividend_yield", 0) or 0))
            moat = float(t.get("moat_score", 0) or 0)

            # Normalised components → annualised return proxies
            score_ret = (score / 100) * 0.18        # max ~18% from score
            div_ret = div / 100                      # dividend yield as-is
            moat_ret = (moat / 20) * 0.05            # max ~5% from moat (Wide moat)

            composite = (
                cfg.score_weight * score_ret
                + cfg.dividend_weight * div_ret
                + cfg.moat_weight * moat_ret
            )
            mu.append(composite)
        return np.array(mu)

    def _covariance_matrix(self, price_matrix: pd.DataFrame) -> np.ndarray:
        """Annualised covariance from weekly returns. Adds small regularisation diagonal."""
        weekly_ret = price_matrix.pct_change().dropna()
        cov = weekly_ret.cov().values * 52  # annualise
        # Ledoit-Wolf-style regularisation (avoids near-singular matrices)
        cov += np.eye(cov.shape[0]) * 1e-6
        return cov

    # ------------------------------------------------------------------ #
    #  SLSQP optimizer                                                     #
    # ------------------------------------------------------------------ #

    def _run_slsqp(
        self,
        mu: np.ndarray,
        cov: np.ndarray,
        tickers: List[dict],
    ) -> Optional[np.ndarray]:
        n = len(tickers)
        rf = self.opt.risk_free_rate
        cfg = self.cfg

        # Build per-ticker sector index lookup
        symbol_sector = {t["symbol"]: t.get("sector", "Unknown") for t in tickers}
        symbols = [t["symbol"] for t in tickers]

        # Dividend yields as array (cap bad data at 15%)
        divs = np.array([self._clean_div_yield(float(t.get("dividend_yield", 0) or 0)) / 100 for t in tickers])

        def neg_sharpe(w: np.ndarray) -> float:
            port_ret = float(mu @ w)
            port_vol = float(np.sqrt(w @ cov @ w))
            if port_vol < 1e-8:
                return 0.0
            return -(port_ret - rf) / port_vol

        def port_vol(w: np.ndarray) -> float:
            return float(np.sqrt(w @ cov @ w))

        def port_div(w: np.ndarray) -> float:
            return float(divs @ w * 100)

        # --- Constraints ---
        constraints = [
            {"type": "eq", "fun": lambda w: w.sum() - 1.0},
            # Volatility ceiling
            {"type": "ineq", "fun": lambda w: (cfg.max_volatility_pct / 100) - port_vol(w)},
            # Dividend yield floor
            {"type": "ineq", "fun": lambda w: port_div(w) - cfg.min_dividend_yield_pct},
        ]

        # Sector caps
        sectors_present = set(symbol_sector.values())
        for sector in sectors_present:
            idx = [i for i, s in enumerate(symbols) if symbol_sector[s] == sector]
            if idx:
                max_s = cfg.max_sector_pct / 100
                constraints.append({
                    "type": "ineq",
                    "fun": lambda w, ix=idx, ms=max_s: ms - sum(w[i] for i in ix),
                })

        # --- Bounds: [min_weight, max_position_pct] per ticker ---
        lb = self.opt.min_weight_pct / 100
        # Ensure ub ≥ 1/n so sum-to-1 constraint is always feasible
        ub = max(cfg.max_position_pct / 100, 1.0 / n)
        bounds = [(lb, ub)] * n

        # Check if dividend constraint is satisfiable at all
        max_possible_div = float(np.sort(divs)[-min(n, cfg.min_positions):][::-1].mean()) * 100
        if max_possible_div < cfg.min_dividend_yield_pct:
            logger.warning(
                f"Dividend constraint ({cfg.min_dividend_yield_pct}%) may be unsatisfiable "
                f"— best avg div in universe: {max_possible_div:.1f}%"
            )

        # --- Initial guess: bias toward high-div tickers when div constraint is tight ---
        min_div_needed = cfg.min_dividend_yield_pct / 100
        avg_div = float(divs.mean())
        if avg_div < min_div_needed * 0.8:
            # Weight initial guess by dividend yield to help SLSQP find a feasible start
            raw = divs + 1e-4  # avoid zero
            w0 = raw / raw.sum()
        else:
            w0 = np.ones(n) / n
        w0 = np.clip(w0, lb, ub)
        w0 /= w0.sum()

        def _try_minimize(start: np.ndarray) -> Optional[np.ndarray]:
            res = minimize(
                neg_sharpe,
                start,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 1000, "ftol": 1e-9},
            )
            if res.success:
                w = np.clip(res.x, 0, 1)
                if w.sum() > 0:
                    w /= w.sum()
                if n > cfg.min_positions:
                    w[w < lb * 0.5] = 0
                    if w.sum() > 0:
                        w /= w.sum()
                logger.info(f"SLSQP converged — Sharpe {-res.fun:.3f}")
                return w
            return None

        try:
            w = _try_minimize(w0)
            if w is not None:
                return w
            # Retry with equal-weight starting point if div-biased start failed
            w = _try_minimize(np.ones(n) / n)
            if w is not None:
                return w
            logger.warning("SLSQP did not converge after 2 attempts")
            return None
        except Exception as exc:
            logger.error(f"SLSQP error: {exc}")
            return None

    # ------------------------------------------------------------------ #
    #  Score-weighted fallback                                             #
    # ------------------------------------------------------------------ #

    def _score_weighted_optimize(self, tickers: List[dict]) -> np.ndarray:
        """Proportional allocation by adjusted_score, clipped to profile bounds."""
        cfg = self.cfg
        scores = np.array([float(t.get("adjusted_score", 1) or 1) for t in tickers])
        scores = np.clip(scores, 0.01, None)
        w = scores / scores.sum()

        # Iteratively clip to max_position_pct and renormalise (3 passes)
        ub = cfg.max_position_pct / 100
        for _ in range(5):
            w = np.clip(w, 0, ub)
            if w.sum() > 0:
                w /= w.sum()

        return w

    # ------------------------------------------------------------------ #
    #  Efficient Frontier                                                  #
    # ------------------------------------------------------------------ #

    def _compute_frontier(
        self,
        result: OptimizationResult,
        mu: np.ndarray,
        cov: np.ndarray,
        tickers: List[dict],
    ) -> None:
        """Monte Carlo portfolios on the Efficient Frontier."""
        n = len(tickers)
        rf = self.opt.risk_free_rate
        ub = self.cfg.max_position_pct / 100
        rng = np.random.default_rng(42)

        rets, vols, sharpes = [], [], []
        for _ in range(self.opt.frontier_points):
            w = rng.dirichlet(np.ones(n))
            w = np.clip(w, 0, ub)
            if w.sum() > 0:
                w /= w.sum()
            r = float(mu @ w) * 100
            v = float(np.sqrt(w @ cov @ w)) * 100
            s = (r / 100 - rf) / (v / 100) if v > 0 else 0
            rets.append(round(r, 2))
            vols.append(round(v, 2))
            sharpes.append(round(s, 3))

        result.frontier_returns = rets
        result.frontier_vols = vols
        result.frontier_sharpes = sharpes

    # ------------------------------------------------------------------ #
    #  Result population                                                   #
    # ------------------------------------------------------------------ #

    def _populate_result(
        self,
        result: OptimizationResult,
        tickers: List[dict],
        weights: np.ndarray,
        mu: np.ndarray,
        cov: Optional[np.ndarray],
    ) -> None:
        rf = self.opt.risk_free_rate

        sector_weights: Dict[str, float] = {}
        allocations = []

        for i, (t, w, er) in enumerate(zip(tickers, weights, mu)):
            if w < 0.001:
                continue
            sym = t["symbol"]
            sector = t.get("sector", "Unknown")
            div = self._clean_div_yield(float(t.get("dividend_yield", 0) or 0))
            score = float(t.get("adjusted_score", 0) or 0)
            moat = float(t.get("moat_score", 0) or 0)

            # Per-ticker annualised vol from diagonal of cov (if available)
            if cov is not None:
                ticker_vol = math.sqrt(max(cov[i, i], 0)) * 100
            else:
                ticker_vol = 0.0

            alloc = TickerAllocation(
                symbol=sym,
                weight_pct=round(w * 100, 1),
                expected_return_pct=round(er * 100, 1),
                volatility_pct=round(ticker_vol, 1),
                dividend_yield_pct=round(div, 2),
                adjusted_score=round(score, 1),
                moat_score=round(moat, 1),
                sector=sector,
                is_ars=sym in _ARS_TICKERS,
                score_discounted=bool(t.get("_ars_discounted", False)),
            )
            allocations.append(alloc)
            sector_weights[sector] = sector_weights.get(sector, 0) + w * 100

        # Sort by weight descending
        allocations.sort(key=lambda a: -a.weight_pct)
        result.tickers = allocations

        w_arr = weights
        port_ret = float(mu @ w_arr)
        result.expected_return_pct = round(port_ret * 100, 1)

        if cov is not None:
            port_vol = float(np.sqrt(w_arr @ cov @ w_arr))
            result.volatility_pct = round(port_vol * 100, 1)
            if port_vol > 0:
                result.sharpe_ratio = round((port_ret - rf) / port_vol, 2)

        divs = np.array([self._clean_div_yield(float(t.get("dividend_yield", 0) or 0)) / 100 for t in tickers])
        result.dividend_yield_pct = round(float(divs @ w_arr) * 100, 2)

        moats = np.array([float(t.get("moat_score", 0) or 0) for t in tickers])
        scores = np.array([float(t.get("adjusted_score", 0) or 0) for t in tickers])
        result.moat_score_avg = round(float(moats @ w_arr), 1)
        result.adjusted_score_avg = round(float(scores @ w_arr), 1)

        result.sector_weights = {k: round(float(v), 1) for k, v in sorted(sector_weights.items(), key=lambda x: -x[1])}

    # ------------------------------------------------------------------ #
    #  Rebalancing                                                         #
    # ------------------------------------------------------------------ #

    def _rebalancing_suggestions(
        self,
        target_weights: Dict[str, float],
        current_weights: Dict[str, float],
    ) -> List[RebalanceSuggestion]:
        all_symbols = set(target_weights) | set(current_weights)
        suggestions = []
        for sym in sorted(all_symbols):
            target = target_weights.get(sym, 0.0)
            current = current_weights.get(sym, 0.0)
            delta = target - current
            if abs(delta) < 0.5:
                action = "HOLD"
            elif delta > 0:
                action = "BUY"
            else:
                action = "SELL"
            suggestions.append(RebalanceSuggestion(
                symbol=sym,
                current_pct=round(current, 1),
                target_pct=round(target, 1),
                delta_pct=round(delta, 1),
                action=action,
            ))
        suggestions.sort(key=lambda s: -abs(s.delta_pct))
        return suggestions
