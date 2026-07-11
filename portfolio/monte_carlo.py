"""
Monte Carlo Simulation for retirement portfolio projections.

Methodology: Block bootstrap over historical weekly portfolio returns.
  - Samples blocks of 4 consecutive weeks from real history (preserves
    short-term autocorrelation and fat tails — no Gaussian assumption).
  - Conservative adjustments: +10% volatility, -20% expected return
    (future returns expected to be lower than historical).
  - Fully vectorised with NumPy — 10 000 sims complete in < 2 seconds.

Usage:
    sim = MonteCarloSimulator(symbols, weights)
    result = sim.run(
        horizon_years=20,
        n_sims=10_000,
        initial_value=100_000,
        annual_withdrawal=0,
        target_value=500_000,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from config import MONTE_CARLO
from data.fetcher import get_history
from portfolio.decumulation import (
    WithdrawalStrategy,
    apply_withdrawal_strategy,
    decumulation_metrics,
)

# ------------------------------------------------------------------ #
#  Result dataclass                                                    #
# ------------------------------------------------------------------ #

@dataclass
class MonteCarloResult:
    # Input parameters
    n_sims: int
    horizon_years: int
    initial_value: float
    annual_withdrawal: float
    target_value: float

    # Fan chart: year → {pct: portfolio_value}
    # Percentiles stored: 5, 10, 25, 50, 75, 90, 95
    fan_paths: Dict[int, Dict[int, float]] = field(default_factory=dict)
    # year_labels for x-axis
    years: List[int] = field(default_factory=list)

    # Terminal value statistics
    median_terminal: float = 0.0
    p10_terminal: float = 0.0       # pessimistic (10th pct)
    p25_terminal: float = 0.0
    p75_terminal: float = 0.0
    p90_terminal: float = 0.0       # optimistic (90th pct)

    # Probability metrics
    prob_achieve_target_pct: float = 0.0   # % of sims that reach target_value
    prob_ruin_pct: float = 0.0             # % of sims that hit $0 before end

    # Annualised return stats across simulations
    median_cagr_pct: float = 0.0
    p10_cagr_pct: float = 0.0

    # Sequence of Returns Risk (SORR) and intra-horizon drawdown metrics
    # % of paths with >30% peak-to-trough drawdown in first 5 years
    sorr_early_drawdown_pct: float = 0.0
    # Median peak-to-trough drawdown across all paths (full horizon)
    median_max_drawdown_pct: float = 0.0
    # % of paths that hit a drawdown ≥50% at any point
    pct_paths_severe_drawdown: float = 0.0
    # P10 intra-horizon minimum value (worst path 10th pct)
    p10_intra_min: float = 0.0
    # Median year in which the maximum drawdown typically occurs
    median_year_of_max_dd: float = 0.0

    # Data quality note
    n_weeks_history: int = 0
    symbols_used: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    #  Economic drags (Item 1 — transparency layer). All optional /       #
    #  backward-compatible: populated ONLY when run(drags=...) is given.   #
    #  When None, every metric above is the pre-feature "base" number.     #
    # ------------------------------------------------------------------ #
    drags_applied: Optional[dict] = None        # the drags dict used (or None)
    total_annual_drag_pct: float = 0.0          # sum of components, annual %
    # "Base" (no-drag) reference terminal stats, so the UI can show
    # base vs with-drags side by side. Zero when no drags applied.
    base_median_terminal: float = 0.0
    base_p10_terminal: float = 0.0
    base_p90_terminal: float = 0.0
    base_prob_achieve_target_pct: float = 0.0

    # ------------------------------------------------------------------ #
    #  Realistic (no-haircut) reference — transparency of the conservative #
    #  bias. Populated ONLY when run(include_realistic_reference=True).     #
    #  These remove the conservative haircut (vol_adjustment / mean_haircut)#
    #  so the UI can show the "realistic" median (future ≈ historical) next  #
    #  to the conservative "planning floor". Drags and withdrawals are kept  #
    #  identical, so the two scenarios differ by EXACTLY the haircut. When   #
    #  the flag is off, every metric above is byte-identical to before.      #
    # ------------------------------------------------------------------ #
    realistic_reference_applied: bool = False
    realistic_median_terminal: float = 0.0
    realistic_p10_terminal: float = 0.0
    realistic_p90_terminal: float = 0.0
    realistic_prob_achieve_target_pct: float = 0.0

    # ------------------------------------------------------------------ #
    #  Decumulation (Fase H.1). All optional / backward-compatible:        #
    #  populated ONLY when run(withdrawal_strategy=...) is given. When      #
    #  None, every metric above is the pre-feature "base" number and these  #
    #  stay at their defaults.                                              #
    # ------------------------------------------------------------------ #
    withdrawal_strategy_applied: Optional[dict] = None
    prob_sustain_real_pct: float = 0.0        # % paths income lasted the whole horizon
    prob_legacy_pct: float = 0.0              # % paths with money left at the end
    median_legacy: float = 0.0               # median terminal value (USD)
    expected_depletion_year: float = 0.0     # median year of depletion among paths that ran dry
    longevity_years: int = 0                 # horizon the sustain metric refers to


# ------------------------------------------------------------------ #
#  Simulator                                                           #
# ------------------------------------------------------------------ #

class MonteCarloSimulator:
    """
    Block-bootstrap Monte Carlo simulator.

    Parameters
    ----------
    symbols : list of ticker symbols (must match weights order)
    weights : portfolio allocation as fractions summing to 1.0
              If None, equal-weight allocation is used.
    """

    BLOCK_SIZE = 4          # weeks per bootstrap block
    HISTORY_PERIOD = "10y"  # how much price history to fetch
    PERCENTILES = [5, 10, 25, 50, 75, 90, 95]

    def __init__(
        self,
        symbols: List[str],
        weights: Optional[np.ndarray] = None,
        seed: int = 42,
        vol_scale: float = 1.0,
        return_scale: float = 1.0,
    ) -> None:
        self.symbols = symbols
        self._weights_input = weights
        self._seed = seed
        self._rng = np.random.default_rng(seed)
        self._port_returns: Optional[np.ndarray] = None
        # Profile-specific adjustment multipliers applied ON TOP of the global
        # conservative adjustments (vol_adjustment, mean_haircut from config).
        self.vol_scale = vol_scale
        self.return_scale = return_scale

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def run(
        self,
        horizon_years: int,
        n_sims: int,
        initial_value: float,
        annual_withdrawal: float = 0.0,
        target_value: float = 0.0,
        withdrawal_growth_rate: float = 0.0,   # e.g. 0.03 for 3% annual increase (inflation)
        drags: Optional[dict] = None,          # Item 1: economic drags (None = base behavior)
        withdrawal_strategy=None,              # Fase H.1: WithdrawalStrategy | dict | None
        longevity_years: Optional[int] = None, # Fase H.1: horizon for "outliving money" metric
        include_realistic_reference: bool = False,  # show realistic (no-haircut) next to conservative
    ) -> MonteCarloResult:
        """
        Run the full Monte Carlo simulation.

        Parameters
        ----------
        horizon_years : projection horizon (5, 10, 15, 20, 30, etc.)
        n_sims        : number of simulation paths (default 10 000)
        initial_value : starting portfolio value in USD
        annual_withdrawal : amount withdrawn at end of each year (0 = accumulation phase)
        target_value  : retirement goal for probability calculation (0 = skip)
        drags         : optional economic-drag dict (Item 1). When None the
                        simulation is byte-identical to the pre-feature engine.
                        When provided, an annual effective drag (fees, dividend
                        tax, rebalance cost, AR buffer) compounds weekly on top
                        of the conservative adjustment, and ``base_*`` reference
                        metrics are populated for side-by-side comparison.
                        Accepts either ``{"total_annual_drag_pct": x}`` or the
                        individual component keys (summed).
        withdrawal_strategy : optional decumulation strategy (Fase H.1) as a
                        ``WithdrawalStrategy`` or plain dict. When provided it
                        REPLACES the legacy ``annual_withdrawal`` path and
                        populates the decumulation metrics (prob_sustain_real,
                        prob_legacy, expected_depletion_year). When None the
                        engine is byte-identical to the pre-feature behavior.
        longevity_years : optional planning horizon (years) the "income lasts"
                        metric refers to. Defaults to ``horizon_years``.
        include_realistic_reference : when True, runs a second compact pass on
                        the RAW historical returns (no conservative haircut) and
                        populates the ``realistic_*`` fields so the UI can show
                        the realistic median next to the conservative one. Drags
                        and withdrawals are applied identically, so the two
                        differ by exactly the haircut. Uses the same bootstrap
                        draws (re-seeded), so the comparison is apples-to-apples.
                        When False the engine is byte-identical to before.
        """
        result = MonteCarloResult(
            n_sims=n_sims,
            horizon_years=horizon_years,
            initial_value=initial_value,
            annual_withdrawal=annual_withdrawal,
            target_value=target_value,
        )

        # 1 — Load historical returns
        port_hist, n_weeks, symbols_used, warnings = self._load_returns()
        result.n_weeks_history = n_weeks
        result.symbols_used    = symbols_used
        result.warnings        = list(warnings)

        # P2 D11: surface model assumptions (no path math change)
        if getattr(MONTE_CARLO, "warn_static_weights", True):
            result.warnings.append(
                "Simulación con pesos fijos (sin rebalanceo periódico en el path; "
                "un solo régimen histórico de block-bootstrap)."
            )
        if (
            getattr(MONTE_CARLO, "warn_crypto_without_extra_vol", True)
            and self.vol_scale <= 1.0
            and symbols_used
        ):
            try:
                from config import is_crypto
                if any(is_crypto(s) for s in symbols_used):
                    result.warnings.append(
                        "Hay crypto en el portafolio con vol_scale≤1.0 — sin haircut "
                        "extra de volatilidad. Considerá vol_scale≥1.15 en perfiles "
                        "conservadores (MONTE_CARLO.default_vol_scale_conservative)."
                    )
            except Exception:
                pass

        if n_weeks < MONTE_CARLO.min_history_weeks:
            result.warnings.append(
                f"Historial insuficiente ({n_weeks} semanas). "
                f"Se necesitan al menos {MONTE_CARLO.min_history_weeks} para una simulación confiable."
            )
            if n_weeks < 52:
                result.warnings.append("Simulación cancelada — datos insuficientes.")
                return result

        # 2 — Apply conservative adjustments
        port_hist_adj = self._conservative_adjustment(port_hist)

        # 3 — Simulate paths
        logger.info(f"Monte Carlo: {n_sims} sims × {horizon_years}y using {n_weeks} weeks of history")
        n_horizon_weeks = horizon_years * 52
        paths = self._simulate_paths(port_hist_adj, n_sims, n_horizon_weeks)

        # 3b — Economic drags (Item 1). total_drag_frac == 0 → base behavior,
        # paths untouched, base_* reference metrics left at 0 (byte-identical
        # to the pre-feature engine). When drags apply, we keep a "base" copy
        # to expose no-drag reference metrics alongside the real numbers.
        total_drag_frac = self._total_drag_fraction(drags)
        base_paths = None
        if total_drag_frac > 0:
            base_paths = paths.copy()
            paths = self._apply_drags(paths, total_drag_frac)
            result.drags_applied = dict(drags) if drags else None
            result.total_annual_drag_pct = round(total_drag_frac * 100, 4)

        # 4 — Apply withdrawals (reduce portfolio value at year end).
        # Fase H.1: when an explicit withdrawal_strategy is given it REPLACES
        # the legacy fixed-amount path. With no strategy, behavior is unchanged.
        strategy = WithdrawalStrategy.coerce(withdrawal_strategy)

        def _withdraw(p: np.ndarray) -> np.ndarray:
            if strategy is not None:
                return apply_withdrawal_strategy(
                    p, initial_value, strategy, n_horizon_weeks,
                    inflation_rate=withdrawal_growth_rate,
                )
            if annual_withdrawal > 0:
                return self._apply_withdrawals(
                    p, initial_value, annual_withdrawal, n_horizon_weeks,
                    withdrawal_growth_rate=withdrawal_growth_rate
                )
            return p

        paths = _withdraw(paths)

        # Scale from relative (start=1.0) to dollar values
        paths_usd = paths * initial_value

        # 5 — Compute output statistics
        result.years = list(range(0, horizon_years + 1))
        result.fan_paths = self._fan_paths(paths_usd, horizon_years)

        terminal = paths_usd[:, -1]
        result.median_terminal = float(np.median(terminal))
        result.p10_terminal    = float(np.percentile(terminal, 10))
        result.p25_terminal    = float(np.percentile(terminal, 25))
        result.p75_terminal    = float(np.percentile(terminal, 75))
        result.p90_terminal    = float(np.percentile(terminal, 90))

        if target_value > 0:
            result.prob_achieve_target_pct = float((terminal >= target_value).mean() * 100)

        # 5b — Base (no-drag) reference metrics for the comparison badge.
        if base_paths is not None:
            base_terminal = _withdraw(base_paths)[:, -1] * initial_value
            result.base_median_terminal = float(np.median(base_terminal))
            result.base_p10_terminal    = float(np.percentile(base_terminal, 10))
            result.base_p90_terminal    = float(np.percentile(base_terminal, 90))
            if target_value > 0:
                result.base_prob_achieve_target_pct = float((base_terminal >= target_value).mean() * 100)

        # 5b' — Realistic (no-haircut) reference. Re-runs the bootstrap on the
        # RAW returns (port_hist, before _conservative_adjustment) using a fresh
        # RNG seeded identically, so the block draws match the main pass and the
        # only difference is the conservative haircut. Drags + withdrawals are
        # applied the same way. Cheap (one extra pass) and fully opt-in.
        if include_realistic_reference:
            realistic_rng = np.random.default_rng(self._seed)
            realistic_paths = self._simulate_paths(
                port_hist, n_sims, n_horizon_weeks, rng=realistic_rng
            )
            if total_drag_frac > 0:
                realistic_paths = self._apply_drags(realistic_paths, total_drag_frac)
            realistic_terminal = _withdraw(realistic_paths)[:, -1] * initial_value
            result.realistic_reference_applied = True
            result.realistic_median_terminal = float(np.median(realistic_terminal))
            result.realistic_p10_terminal    = float(np.percentile(realistic_terminal, 10))
            result.realistic_p90_terminal    = float(np.percentile(realistic_terminal, 90))
            if target_value > 0:
                result.realistic_prob_achieve_target_pct = float(
                    (realistic_terminal >= target_value).mean() * 100
                )

        result.prob_ruin_pct = float((terminal <= 0).mean() * 100)

        # SORR and intra-horizon drawdown metrics
        (result.sorr_early_drawdown_pct, result.median_max_drawdown_pct,
         result.pct_paths_severe_drawdown, result.p10_intra_min,
         result.median_year_of_max_dd) = \
            self._compute_drawdown_metrics(paths_usd, horizon_years)

        # CAGR per simulation
        terminal_positive = np.where(terminal > 0, terminal, np.nan)
        cagrs = (terminal_positive / initial_value) ** (1 / horizon_years) - 1
        result.median_cagr_pct = float(np.nanmedian(cagrs) * 100)
        result.p10_cagr_pct    = float(np.nanpercentile(cagrs, 10) * 100)

        # 5c — Decumulation metrics (Fase H.1). Only when a strategy was applied.
        if strategy is not None:
            dec = decumulation_metrics(
                paths_usd, horizon_years, initial_value,
                longevity_years=longevity_years,
            )
            result.withdrawal_strategy_applied = strategy.to_dict()
            result.prob_sustain_real_pct = dec["prob_sustain_real_pct"]
            result.prob_legacy_pct       = dec["prob_legacy_pct"]
            result.median_legacy         = dec["median_legacy"]
            result.expected_depletion_year = dec["expected_depletion_year"]
            result.longevity_years       = int(dec["longevity_years"])

        logger.info(
            f"Monte Carlo complete: median={result.median_terminal:,.0f} "
            f"p10={result.p10_terminal:,.0f} p90={result.p90_terminal:,.0f} "
            f"prob_target={result.prob_achieve_target_pct:.1f}% "
            f"prob_ruin={result.prob_ruin_pct:.1f}%"
        )
        return result

    # ------------------------------------------------------------------ #
    #  Data loading                                                        #
    # ------------------------------------------------------------------ #

    def _load_returns(self) -> Tuple[np.ndarray, int, List[str], List[str]]:
        """
        Fetch weekly prices for each symbol, compute portfolio returns.
        Falls back to SPY if individual symbols fail.
        """
        warnings: List[str] = []
        frames: Dict[str, pd.Series] = {}

        for sym in self.symbols:
            try:
                hist = get_history(sym, period=self.HISTORY_PERIOD, interval="1wk")
                if hist.empty:
                    continue
                if "Date" in hist.columns:
                    hist = hist.set_index("Date")
                elif "date" in hist.columns:
                    hist = hist.set_index("date")
                close_col = "close" if "close" in hist.columns else "Close"
                if close_col not in hist.columns:
                    continue
                s = hist[close_col].dropna()
                s.index = pd.to_datetime(s.index)
                if len(s) >= 52:
                    frames[sym] = s
            except Exception as exc:
                logger.warning(f"MC: price fetch failed for {sym}: {exc}")

        if not frames:
            warnings.append("No se pudieron obtener datos de precio. Usando SPY como proxy.")
            return self._spy_fallback()

        # Align all series to common dates
        price_df = pd.DataFrame(frames).sort_index().ffill().dropna()
        symbols_used = list(price_df.columns)

        # Build weights for available symbols
        if self._weights_input is not None and len(self._weights_input) == len(self.symbols):
            sym_idx = {s: i for i, s in enumerate(self.symbols)}
            raw_w = np.array([
                self._weights_input[sym_idx[s]] if s in sym_idx else 0.0
                for s in symbols_used
            ])
        else:
            raw_w = np.ones(len(symbols_used))

        if raw_w.sum() > 0:
            weights = raw_w / raw_w.sum()
        else:
            weights = np.ones(len(symbols_used)) / len(symbols_used)

        if len(symbols_used) < len(self.symbols):
            missing = len(self.symbols) - len(symbols_used)
            warnings.append(f"{missing} ticker(s) sin datos históricos — rebalanceando entre los disponibles.")

        weekly_returns = price_df.pct_change().dropna().values
        port_returns   = weekly_returns @ weights

        return port_returns, len(port_returns), symbols_used, warnings

    def _spy_fallback(self) -> Tuple[np.ndarray, int, List[str], List[str]]:
        """Use SPY as a fallback portfolio proxy."""
        try:
            hist = get_history("SPY", period=self.HISTORY_PERIOD, interval="1wk")
            if not hist.empty:
                close_col = "close" if "close" in hist.columns else "Close"
                s = hist[close_col].dropna()
                rets = s.pct_change().dropna().values
                return rets, len(rets), ["SPY"], ["Usando SPY como proxy de portafolio."]
        except Exception as exc:
            logger.error(f"MC: SPY fallback failed: {exc}")
        return np.array([]), 0, [], ["Imposible obtener datos históricos."]

    # ------------------------------------------------------------------ #
    #  Conservative adjustment                                             #
    # ------------------------------------------------------------------ #

    def _conservative_adjustment(self, returns: np.ndarray) -> np.ndarray:
        """
        Apply conservative bias to historical returns:
          - Inflate volatility by vol_adjustment × vol_scale
          - Reduce expected return by mean_haircut × return_scale
        vol_scale / return_scale are profile-specific overrides (default 1.0 = no extra adjustment).
        """
        mean = returns.mean()
        vol_adj    = MONTE_CARLO.vol_adjustment * self.vol_scale
        return_adj = MONTE_CARLO.mean_haircut   * self.return_scale
        return (returns - mean) * vol_adj + mean * return_adj

    # ------------------------------------------------------------------ #
    #  Economic drags (Item 1)                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _total_drag_fraction(drags: Optional[dict]) -> float:
        """Resolve a drags dict into a single annual drag *fraction* (0.0–1.0).

        Accepts either a precomputed ``total_annual_drag_pct`` or the individual
        component percentages, which are summed. Returns 0.0 for ``None``, a
        disabled master switch, or non-positive totals — in which case the
        engine stays byte-identical to the pre-feature behavior.
        """
        if not drags:
            return 0.0
        if not drags.get("enabled", True):
            return 0.0
        if "total_annual_drag_pct" in drags:
            total_pct = float(drags.get("total_annual_drag_pct") or 0.0)
        else:
            total_pct = float(
                (drags.get("annual_fee_pct") or 0.0)
                + (drags.get("dividend_tax_drag_pct") or 0.0)
                + (drags.get("rebalance_cost_annual_pct") or 0.0)
                + (drags.get("ar_buffer_pct") or 0.0)
            )
        return max(0.0, total_pct / 100.0)

    @staticmethod
    def _apply_drags(paths: np.ndarray, total_drag_frac: float) -> np.ndarray:
        """Compound an annual drag fraction weekly across each path.

        The drag is independent of returns, so it is exact and auditable: a
        path value at week ``t`` is multiplied by ``weekly_factor ** t`` where
        ``weekly_factor = (1 - total_drag_frac) ** (1/52)``. Applied to the
        relative paths (start = 1.0) BEFORE withdrawals, matching how fees are
        charged on the standing balance. O(weeks) — negligible cost.
        """
        n_cols = paths.shape[1]
        weekly_factor = (1.0 - total_drag_frac) ** (1.0 / 52.0)
        drag_mult = weekly_factor ** np.arange(n_cols)
        return paths * drag_mult[np.newaxis, :]

    # ------------------------------------------------------------------ #
    #  Simulation (vectorised)                                             #
    # ------------------------------------------------------------------ #

    def _simulate_paths(
        self,
        port_hist: np.ndarray,
        n_sims: int,
        n_weeks: int,
        rng: Optional[np.random.Generator] = None,
    ) -> np.ndarray:
        """
        Vectorised block bootstrap simulation.

        Returns array of shape (n_sims, n_weeks + 1) with relative portfolio
        values (start = 1.0).

        ``rng`` lets a caller supply an independent generator (used by the
        realistic-reference pass so it can replay the same draws on raw returns).
        Defaults to the instance RNG, preserving the original behavior exactly.
        """
        rng = rng if rng is not None else self._rng
        T = len(port_hist)
        block_size = self.BLOCK_SIZE
        max_start  = max(T - block_size, 1)
        n_blocks   = n_weeks // block_size + 2  # slightly more than needed

        # Sample block start indices: shape (n_sims, n_blocks)
        starts = rng.integers(0, max_start, size=(n_sims, n_blocks))

        # Build block offset indices: shape (n_sims, n_blocks * block_size)
        offsets = np.arange(block_size)
        # indices: (n_sims, n_blocks, block_size) → flatten last two dims
        indices = (starts[:, :, np.newaxis] + offsets[np.newaxis, np.newaxis, :])
        indices = indices.reshape(n_sims, -1)[:, :n_weeks]  # trim to exact length
        # Clip to valid range
        indices = np.clip(indices, 0, T - 1)

        # Sampled weekly returns: (n_sims, n_weeks)
        sampled = port_hist[indices]

        # Cumulative product → paths (n_sims, n_weeks + 1), start = 1.0
        paths = np.concatenate(
            [np.ones((n_sims, 1)), np.cumprod(1.0 + sampled, axis=1)],
            axis=1,
        )
        return paths

    @staticmethod
    def _apply_withdrawals(
        paths: np.ndarray,
        initial_value: float,
        annual_withdrawal: float,
        n_horizon_weeks: int,
        withdrawal_growth_rate: float = 0.0,
    ) -> np.ndarray:
        """
        Apply annual withdrawals (as fraction of initial_value) at every 52-week mark.
        If withdrawal_growth_rate > 0, the withdrawal amount grows each year
        (e.g. 0.03 = 3% inflation adjustment — common for long-term retirement planning).
        Portfolio cannot go below 0.
        """
        withdrawal_fraction = annual_withdrawal / initial_value
        horizon_years = n_horizon_weeks // 52

        for yr in range(1, horizon_years + 1):
            week_idx = min(yr * 52, paths.shape[1] - 1)
            # Grow the withdrawal fraction over time if requested
            grown_fraction = withdrawal_fraction * ((1 + withdrawal_growth_rate) ** (yr - 1))
            paths[:, week_idx:] -= grown_fraction
            paths = np.maximum(paths, 0)

        return paths

    @staticmethod
    def _compute_drawdown_metrics(
        paths_usd: np.ndarray,
        horizon_years: int,
    ) -> tuple:
        """
        Compute SORR and drawdown statistics from USD paths.

        Returns
        -------
        (sorr_early_pct, median_max_dd_pct, pct_severe_pct, p10_intra_min,
         median_year_of_max_dd)
        """
        n_sims, n_weeks_plus1 = paths_usd.shape

        # Running peak (cummax across time axis)
        running_peak = np.maximum.accumulate(paths_usd, axis=1)
        # Drawdown at each step: (peak - value) / peak
        drawdown = np.where(running_peak > 0, (running_peak - paths_usd) / running_peak, 0.0)

        # Max drawdown per path (full horizon)
        max_dd_per_path = drawdown.max(axis=1)  # shape (n_sims,)
        median_max_dd = float(np.median(max_dd_per_path) * 100)
        pct_severe = float((max_dd_per_path >= 0.50).mean() * 100)

        # Year of max drawdown (median across paths)
        max_dd_week = np.argmax(drawdown, axis=1)   # week index of worst drawdown per path
        median_year_max_dd = float(np.median(max_dd_week) / 52)

        # SORR: % of paths with >30% drawdown in first 5 years
        early_weeks = min(5 * 52, n_weeks_plus1)
        early_dd = drawdown[:, :early_weeks].max(axis=1)
        sorr_early = float((early_dd >= 0.30).mean() * 100)

        # P10 intra-horizon minimum value
        p10_min = float(np.percentile(paths_usd.min(axis=1), 10))

        return sorr_early, median_max_dd, pct_severe, p10_min, median_year_max_dd

    def _fan_paths(
        self,
        paths_usd: np.ndarray,
        horizon_years: int,
    ) -> Dict[int, Dict[int, float]]:
        """
        Compute percentile values at each year mark.
        Returns {year: {percentile: value}}.
        """
        fan: Dict[int, Dict[int, float]] = {}
        n_cols = paths_usd.shape[1]

        for yr in range(horizon_years + 1):
            week_idx = min(yr * 52, n_cols - 1)
            col = paths_usd[:, week_idx]
            fan[yr] = {
                p: round(float(np.percentile(col, p)), 0)
                for p in self.PERCENTILES
            }
        return fan
