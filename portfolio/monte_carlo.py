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
    apply_cash_flow_schedule,
    apply_withdrawal_strategy,
    cash_flow_weeks,
    decumulation_metrics,
    wealth_basis,
)


def _constant_amount(amount: float):
    """An ``amount_fn`` that ignores the pot and always moves the same figure."""
    return lambda _wealth: amount


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
    # Savings per year, deposited monthly. Separate from annual_withdrawal since
    # tier2: cadence is a property of the instrument, not of a sign (U4-1).
    annual_contribution: float = 0.0

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

    # Annualised growth of the pot: (terminal / initial) ** (1/years) - 1.
    # WARNING: this is NOT a rate of return when there are cash flows. With
    # contributions (annual_withdrawal < 0) the contributed capital lands in
    # ``terminal`` but not in ``initial``, so the figure inflates far above any
    # return the portfolio earned (e.g. 30 %/yr for a 7 % portfolio fed monthly).
    # Callers MUST NOT label it "CAGR"/"retorno" when cash flows are present.
    median_cagr_pct: float = 0.0
    p10_cagr_pct: float = 0.0

    # Sequence of Returns Risk (SORR) and intra-horizon drawdown metrics.
    # U2-2: every percentage below is measured on the MARKET series — the
    # bootstrap path before economic drags and before any withdrawal or
    # contribution. They answer "how badly can the market fall", NOT "how much
    # does my pot shrink" (planned spending is not a crash). The shrinking of
    # the actual pot is prob_ruin_pct / p10_intra_min / prob_sustain_real_pct /
    # expected_depletion_year.
    # % of paths with >30% peak-to-trough market drawdown in first 5 years
    sorr_early_drawdown_pct: float = 0.0
    # Median peak-to-trough market drawdown across all paths (full horizon)
    median_max_drawdown_pct: float = 0.0
    # % of paths whose market path hits a drawdown ≥50% at any point
    pct_paths_severe_drawdown: float = 0.0
    # P10 intra-horizon minimum value (worst path 10th pct). The exception to
    # the note above: a USD floor of the REAL pot, so it does include drags and
    # cash flows — it is what tells the retiree how low the money actually gets.
    p10_intra_min: float = 0.0
    # Median year in which the maximum market drawdown typically occurs.
    # WARNING: near-uniform distribution ⇒ this tends to horizon/2 for any
    # portfolio. Never present it alone as "the dangerous year"; use the
    # P25–P75 band below, which states the real (usually large) uncertainty.
    median_year_of_max_dd: float = 0.0
    p25_year_of_max_dd: float = 0.0
    p75_year_of_max_dd: float = 0.0

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

    @property
    def block_size(self) -> int:
        """Weeks per bootstrap block, from config (U5-10).

        This was a class constant ``BLOCK_SIZE = 4`` while
        ``MONTE_CARLO.block_size_weeks = 4`` sat in config being read by nobody.
        Same value, so nothing moved — but the config field looked like the knob
        and editing it was a silent no-op, which is worse than not having one.
        A property rather than a constant because config is mutated in-process
        by the sensitivity lab and the measurement harness.
        """
        return int(MONTE_CARLO.block_size_weeks)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def run(
        self,
        horizon_years: int,
        n_sims: int,
        initial_value: float,
        annual_withdrawal: float = 0.0,
        annual_contribution: float = 0.0,
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
        annual_withdrawal : amount withdrawn at the end of each year, ANNUAL
                        cadence (0 = accumulation phase). A NEGATIVE value is
                        still accepted as a contribution — the form GoalPlanner
                        and the chat tool used before ``annual_contribution``
                        existed — and is folded into it.
        annual_contribution : amount saved per year, deposited MONTHLY (U4-1).
                        The user is asked for a monthly figure, so the money has
                        to arrive monthly; depositing the year's total in week 52
                        cost eleven of the twelve deposits their partial year of
                        growth. Works with ``initial_value=0`` (U4-2), which is
                        the plan of anyone who is saving their way in.
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
            annual_contribution=annual_contribution,
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
        # U4-4: la simulación cubre lo que se le pregunte. `longevity_years` es
        # «cuántos años tiene que durarme el ingreso» y podía superar al horizonte
        # de proyección — de fábrica lo hace, porque los defaults son 20 y 30. Con
        # `cap_week = min(longevity*52, n_cols-1)` los años de más simplemente no
        # existían y el producto respondía igual para 30, 45 o 60, afirmando una
        # longevidad que nunca simuló. Los años no simulados son justo aquellos en
        # que el pozo está más chico, así que el recorte era sistemáticamente
        # optimista.
        #
        # Se simula hasta el mayor de los dos y **las métricas de riqueza siguen
        # siendo las del horizonte de proyección**: terminal, fan chart, CAGR,
        # drawdown y ruina se leen en `horizon_week`, no al final del array. Sólo
        # las de decumulación miran la ventana larga. Con longevidad ≤ horizonte
        # nada se mueve.
        sim_years = max(int(horizon_years), int(longevity_years or 0))
        logger.info(
            f"Monte Carlo: {n_sims} sims × {horizon_years}y "
            + (f"(simuladas {sim_years}y por longevidad) " if sim_years > horizon_years else "")
            + f"using {n_weeks} weeks of history"
        )
        n_horizon_weeks = horizon_years * 52
        n_sim_weeks = sim_years * 52
        #: La columna donde termina el horizonte de PROYECCIÓN. Todo lo que
        #: describe riqueza se lee acá y no en `[:, -1]`, que desde U4-4 puede
        #: estar más adelante.
        horizon_week = n_horizon_weeks

        # El horizonte se sortea PRIMERO y con su largo de siempre, y la cola se
        # empalma después. No es un detalle de estilo: `_simulate_paths` sortea
        # `rng.integers(size=(n_sims, n_blocks))`, así que pedir más semanas
        # cambia la forma del array y **redibuja también los primeros años**.
        # Medido antes de hacerlo así: mover la longevidad de 20 a 45 movía el
        # capital terminal ~1 %, que es ruido de muestreo y no sesgo, pero
        # significaba que preguntar «¿cuánto me dura?» cambiaba la respuesta a
        # «¿cuánto junto?». Son dos preguntas independientes y tienen que serlo
        # también en los números.
        paths = self._simulate_paths(port_hist_adj, n_sims, n_horizon_weeks)
        if n_sim_weeks > n_horizon_weeks:
            cola = self._simulate_paths(
                port_hist_adj, n_sims, n_sim_weeks - n_horizon_weeks
            )
            # `cola` arranca en 1.0; se la escala por donde terminó el horizonte.
            paths = np.concatenate(
                [paths, paths[:, -1:] * cola[:, 1:]], axis=1
            )

        # 3a — U2-2 (P2): SORR and drawdown are measured on the MARKET series —
        # the bootstrap path before drags and before ANY cash flow. Measuring
        # them on the post-withdrawal wealth path turned planned spending into a
        # crash: on a market that never moves, a 4 % annual withdrawal reported
        # a 100 % "drawdown" (fixed_real takes 4 % of the INITIAL capital every
        # year, so the pot falls linearly and hits zero in year 25) ⇒ 🔴 badge
        # and a CRITICAL SORR_HIGH e-mail with zero volatility. Cash-flow
        # depletion is already reported by prob_ruin_pct / p10_intra_min /
        # prob_sustain_real_pct / expected_depletion_year.
        #
        # Drags are excluded on purpose: a deterministic bleed has no *sequence*,
        # and 1.5 %/yr over 30 years would re-create the same mechanical decline
        # through the other door. Their effect is shown by the base_* metrics.
        #
        # Computed here rather than later because this IS the market series.
        # It used to have a second reason — the legacy kernel wrote through its
        # input, so a reference held across step 4 would have read a
        # contaminated array. Since tier2 the cash-flow kernel holds units and
        # never touches `paths`, so the guarantee is structural and pinned by
        # ``tests/test_cash_flow_oracle.py`` instead of resting on call order.
        # U4-4: sobre el horizonte de PROYECCIÓN. El drawdown de mercado y el
        # SORR describen el camino hasta la meta, no la cola de longevidad.
        market_dd = self._compute_drawdown_metrics(
            paths[:, : horizon_week + 1], horizon_years
        )

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

        # A negative ``annual_withdrawal`` has always meant a contribution —
        # that is how GoalPlanner modelled ``Goal.annual_contribution``. Since
        # tier2 the two directions are separate parameters, because cadence is a
        # property of the instrument (savings arrive monthly, retirement
        # withdrawals annually) and hanging that on the sign of one number is
        # the kind of implicit contract that needs a paragraph to explain.
        # The negative form is still accepted so saved sessions and the chat
        # tool keep working.
        contribution = float(annual_contribution)
        withdrawal = float(annual_withdrawal)
        if withdrawal < 0:
            contribution += -withdrawal
            withdrawal = 0.0

        # The pot is expressed in multiples of a positive basis. With capital
        # that basis IS the capital, so every existing plan keeps its exact
        # contract; without capital it falls back to the size of the savings, so
        # a plan that starts empty still has a unit to compound in (U4-2).
        basis = wealth_basis(initial_value, contribution)
        # Report the resolved figures, not the raw arguments: a caller that sent
        # a negative annual_withdrawal still described a contribution, and every
        # predicate downstream should see it as one.
        result.annual_withdrawal = withdrawal
        result.annual_contribution = contribution

        def _wealth_usd(market: np.ndarray) -> np.ndarray:
            if strategy is not None:
                return apply_withdrawal_strategy(
                    market, initial_value, strategy, n_sim_weeks,
                    inflation_rate=withdrawal_growth_rate,
                ) * initial_value
            return self._apply_cash_flows(
                market, initial_value, basis, withdrawal, contribution,
                n_sim_weeks, withdrawal_growth_rate=withdrawal_growth_rate,
            ) * basis

        paths_usd = _wealth_usd(paths)

        # 5 — Compute output statistics
        result.years = list(range(0, horizon_years + 1))
        result.fan_paths = self._fan_paths(paths_usd, horizon_years)

        terminal = paths_usd[:, horizon_week]
        result.median_terminal = float(np.median(terminal))
        result.p10_terminal    = float(np.percentile(terminal, 10))
        result.p25_terminal    = float(np.percentile(terminal, 25))
        result.p75_terminal    = float(np.percentile(terminal, 75))
        result.p90_terminal    = float(np.percentile(terminal, 90))

        if target_value > 0:
            result.prob_achieve_target_pct = float((terminal >= target_value).mean() * 100)

        # 5b — Base (no-drag) reference metrics for the comparison badge.
        if base_paths is not None:
            base_terminal = _wealth_usd(base_paths)[:, horizon_week]
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
            realistic_terminal = _wealth_usd(realistic_paths)[:, horizon_week]
            result.realistic_reference_applied = True
            result.realistic_median_terminal = float(np.median(realistic_terminal))
            result.realistic_p10_terminal    = float(np.percentile(realistic_terminal, 10))
            result.realistic_p90_terminal    = float(np.percentile(realistic_terminal, 90))
            if target_value > 0:
                result.realistic_prob_achieve_target_pct = float(
                    (realistic_terminal >= target_value).mean() * 100
                )

        # Ruin is measured on the intra-horizon minimum, not the terminal value:
        # a path that runs dry mid-horizon has failed even if the market later
        # recovers. With the absorbing kernel the two agree, but measuring the
        # minimum states the intent and stays correct if the kernel changes.
        # (audit D2 — the terminal-only test used to hide early bankruptcies.)
        #
        # Ruin means the money ran out, which presupposes there was money. A plan
        # funded purely by savings is worth 0 until its first deposit lands, and
        # reading that prefix as bankruptcy would report 100 % failure for every
        # saver who starts with nothing. The prefix is deterministic (0 × market
        # on every path), so the boundary is a scalar, not a per-path search.
        _first_flow_week = 0
        if initial_value <= 0 and contribution > 0:
            _first_flow_week = cash_flow_weeks(
                MONTE_CARLO.contribution_periods_per_year, horizon_years, paths_usd.shape[1]
            )[0]
        _ruin_eps = max(initial_value, contribution, 1.0) * 1e-9
        result.prob_ruin_pct = float(
            (paths_usd[:, _first_flow_week:horizon_week + 1].min(axis=1) <= _ruin_eps)
            .mean() * 100
        )
        if initial_value <= 0 and contribution <= 0:
            result.warnings.append(
                "Este plan no tiene capital inicial ni aportes: no hay nada que proyectar."
            )

        # SORR and drawdown metrics — computed in step 3a on the market series.
        (result.sorr_early_drawdown_pct, result.median_max_drawdown_pct,
         result.pct_paths_severe_drawdown,
         result.median_year_of_max_dd, result.p25_year_of_max_dd,
         result.p75_year_of_max_dd) = market_dd

        # The dollar floor, in contrast, IS a property of the real pot: it must
        # keep seeing drags and withdrawals (U2-2 moves the % metrics, not this).
        result.p10_intra_min = float(
            np.percentile(paths_usd[:, : horizon_week + 1].min(axis=1), 10)
        )

        # Pot growth per simulation. Already not a rate of return whenever there
        # are cash flows (see MonteCarloResult) — and with no starting capital it
        # is not a number at all: there is no base to have grown from. Report 0
        # rather than inf, and let the caller's cash-flow check suppress the
        # label, so no surface can render "∞ %/año" as a projection.
        if initial_value > 0:
            terminal_positive = np.where(terminal > 0, terminal, np.nan)
            with np.errstate(divide="ignore", invalid="ignore"):
                cagrs = (terminal_positive / initial_value) ** (1 / horizon_years) - 1
            if np.isfinite(cagrs).any():
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
        block_size = self.block_size
        # U5-17: ``+ 1`` because ``rng.integers`` excludes its upper bound. Without
        # it starts stopped at ``T - block_size - 1``, so no block could reach the
        # last observation and the ones before it were drawn by fewer starts than
        # the rest — coverage 1,2,3,…,3,2,1,0 across the window, asymmetric at the
        # tail for no reason. The projection therefore leaned on the older part of
        # the history: measured over twelve seeds, PFE — whose last four weeks ran
        # at +2.76 %/wk against a +0.11 % mean — came out 6.96 % low.
        max_start  = max(T - block_size + 1, 1)
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
    def _apply_cash_flows(
        market: np.ndarray,
        initial_value: float,
        basis: float,
        annual_withdrawal: float,
        annual_contribution: float,
        n_horizon_weeks: int,
        withdrawal_growth_rate: float = 0.0,
    ) -> np.ndarray:
        """Turn a market curve plus a savings/spending plan into a wealth curve.

        ``market`` is the relative bootstrap path (start = 1.0) and is never
        modified. The return value is wealth in multiples of ``basis``, so the
        caller multiplies once to get dollars.

        Two cadences, because a saving and a pension are two different
        instruments (U4-1): contributions arrive
        ``MONTE_CARLO.contribution_periods_per_year`` times a year — twelve,
        matching the monthly figure the profile asks for — while withdrawals stay
        annual. Setting the config to 1 reproduces the tier1 engine exactly.

        The inflation rate steps once a year for both, so the twelve deposits of
        a year still sum to that year's nominal total. Only the timing changes,
        which is what makes the direction of the fix provable rather than merely
        different.

        When a deposit and a withdrawal land on the same week — month 12 and the
        year's withdrawal both fall on week 52 — the deposit is applied first.
        You get paid, then you spend.

        Delegates to ``portfolio.decumulation.cash_flow_units`` via
        ``apply_cash_flow_schedule``, the single implementation of the cash-flow
        maths, so this entry point and the strategy engine cannot drift apart.
        """
        n_cols = market.shape[1]
        horizon_years = n_horizon_weeks // 52
        events: List[Tuple[int, object]] = []

        def _schedule(annual_amount: float, periods_per_year: int, sign: float) -> None:
            periods = max(1, int(periods_per_year))
            per_period = annual_amount / periods / basis
            for i, week in enumerate(cash_flow_weeks(periods, horizon_years, n_cols)):
                year = i // periods + 1
                grown = per_period * ((1 + withdrawal_growth_rate) ** (year - 1))
                events.append((week, _constant_amount(sign * grown)))

        # Contributions are queued first, and the sort below is stable, so a
        # deposit and a withdrawal on the same week keep that order.
        if annual_contribution:
            _schedule(annual_contribution, MONTE_CARLO.contribution_periods_per_year, -1.0)
        if annual_withdrawal:
            _schedule(annual_withdrawal, MONTE_CARLO.withdrawal_periods_per_year, +1.0)

        events.sort(key=lambda ev: ev[0])
        return apply_cash_flow_schedule(market, initial_value / basis, events)

    @staticmethod
    def _apply_withdrawals(
        paths: np.ndarray,
        initial_value: float,
        annual_withdrawal: float,
        n_horizon_weeks: int,
        withdrawal_growth_rate: float = 0.0,
    ) -> np.ndarray:
        """Legacy entry point: cash flows expressed as one signed annual amount.

        A negative ``annual_withdrawal`` is a contribution. Kept so callers and
        tests written before the two directions were separated keep working;
        new code should call :meth:`_apply_cash_flows`. Requires capital, since
        a signed fraction of ``initial_value`` is the very representation that
        cannot express a plan starting from zero (U4-2).
        """
        withdrawal = max(annual_withdrawal, 0.0)
        contribution = max(-annual_withdrawal, 0.0)
        return MonteCarloSimulator._apply_cash_flows(
            paths, initial_value, wealth_basis(initial_value, contribution),
            withdrawal, contribution, n_horizon_weeks,
            withdrawal_growth_rate=withdrawal_growth_rate,
        )

    @staticmethod
    def _compute_drawdown_metrics(
        paths: np.ndarray,
        horizon_years: int,
    ) -> tuple:
        """
        Compute SORR and drawdown statistics from the MARKET series.

        ``paths`` must be the bootstrap series BEFORE drags and BEFORE any cash
        flow (U2-2). Peak-to-trough is scale-invariant, so relative paths
        (start = 1.0) and USD paths give the same percentages — what matters is
        that no withdrawal or contribution has bent the series, otherwise
        planned spending is counted as a market crash. See step 3a of ``run``.

        Returns
        -------
        (sorr_early_pct, median_max_dd_pct, pct_severe_pct,
         median_year_of_max_dd, p25_year_of_max_dd, p75_year_of_max_dd)

        Note on the *year* of the max drawdown: the distribution of
        ``argmax(drawdown)`` is close to uniform over the horizon, so its median
        lands near ``horizon / 2`` for almost any portfolio. The median alone is
        therefore an artifact of the horizon, not a property of the portfolio —
        the quartiles are returned so the UI can show the dispersion (a wide
        band = the timing of the worst drawdown is essentially unpredictable)
        instead of a single misleadingly precise year.
        """
        n_sims, n_weeks_plus1 = paths.shape

        # Running peak (cummax across time axis)
        running_peak = np.maximum.accumulate(paths, axis=1)
        # Drawdown at each step: (peak - value) / peak
        drawdown = np.where(running_peak > 0, (running_peak - paths) / running_peak, 0.0)

        # Max drawdown per path (full horizon)
        max_dd_per_path = drawdown.max(axis=1)  # shape (n_sims,)
        median_max_dd = float(np.median(max_dd_per_path) * 100)
        pct_severe = float((max_dd_per_path >= 0.50).mean() * 100)

        # Year of max drawdown: median AND quartiles across paths. The IQR is
        # what makes the number honest — see the docstring.
        max_dd_week = np.argmax(drawdown, axis=1)   # week index of worst drawdown per path
        median_year_max_dd = float(np.median(max_dd_week) / 52)
        p25_year_max_dd = float(np.percentile(max_dd_week, 25) / 52)
        p75_year_max_dd = float(np.percentile(max_dd_week, 75) / 52)

        # SORR: % of paths with >30% drawdown in first 5 years
        early_weeks = min(5 * 52, n_weeks_plus1)
        early_dd = drawdown[:, :early_weeks].max(axis=1)
        sorr_early = float((early_dd >= 0.30).mean() * 100)

        return (sorr_early, median_max_dd, pct_severe,
                median_year_max_dd, p25_year_max_dd, p75_year_max_dd)

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
