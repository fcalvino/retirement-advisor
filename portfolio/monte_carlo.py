"""
Monte Carlo Simulation for retirement portfolio projections.

Methodology: Block bootstrap over historical weekly portfolio returns.
  - Samples blocks of 4 consecutive weeks from real history (preserves
    short-term autocorrelation and fat tails — no Gaussian assumption).
  - Each asset is recentred, compound-wise, on the Estimación of its Clase
    (EO-4a, ADR 0001; ``analysis.estimacion``): its weekly log-returns are
    demeaned and shifted to ``log(1 + E) / 52``, so the median path earns E.
    Bonds, tickers without a Clase and Clases without current Fuentes keep the
    old haircut (+10% volatility, -20% return) on their own history. A run
    without ``asset_classes`` uses that haircut on the whole portfolio, exactly
    as before EO-4a, and says so in ``warnings``.
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

import copy
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from config import ESTIMACION, MONTE_CARLO, WITHDRAWAL
from data.fetcher import get_history
from data.fx import fx_pair_symbol, to_base_or_reason
from portfolio.decumulation import (
    WithdrawalStrategy,
    apply_cash_flow_schedule,
    apply_withdrawal_strategy,
    cash_flow_weeks,
    decumulation_metrics,
    phased_strategy_events,
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
    #  Recent-history reference (the "realistic_*" fields). Populated ONLY  #
    #  when run(include_realistic_reference=True): the same draws on the    #
    #  RAW returns, with no Estimación and no haircut, so the UI can show    #
    #  the Estimación next to "if the future looks like the last 10 years".  #
    #  Drags and withdrawals are kept identical. Flag off → byte-identical.  #
    # ------------------------------------------------------------------ #
    #: EO-4a: with what each asset was projected —``asdict`` of
    #: ``analysis.estimacion.AssetEstimation`` (symbol, asset_class, mode,
    #: annual_pct, label)— so the UI can say where the projection comes from.
    #: Empty for a run without ``asset_classes``.
    estimations: List[dict] = field(default_factory=list)
    #: EO-4c: the Escenario every number above was projected with (the
    #: planning one), and —with ``run(include_scenarios=True)``— the terminal
    #: stats of the three, same draws: {name: {median_terminal, p10_terminal,
    #: p90_terminal, prob_achieve_target_pct}}.
    scenario: str = ESTIMACION.default_scenario
    scenarios: Dict[str, Dict[str, float]] = field(default_factory=dict)
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
    #: Yearly savings the caller passed that the strategy path did NOT apply
    #: (WD-STRATEGY-CONTRIB). A strategy means "already retired": the savings
    #: are left out on purpose (user's decision, 2026-09-30) and said so in
    #: ``warnings``. 0.0 when nothing was left out.
    contribution_ignored_by_strategy: float = 0.0
    prob_sustain_real_pct: float = 0.0        # % paths income lasted the whole horizon
    prob_legacy_pct: float = 0.0              # % paths with money left at the end
    median_legacy: float = 0.0               # median terminal value (USD)
    expected_depletion_year: float = 0.0     # median year (from today) of depletion among paths that ran dry
    longevity_years: int = 0                 # years of retirement the sustain metric refers to
    #: Years of saving before the strategy starts (WD-PHASED). 0 = the plan is
    #: already retired: the strategy draws from today and the savings stay out.
    retirement_years: int = 0


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
        currencies: Optional[Dict[str, str]] = None,
        asset_classes: Optional[Mapping[str, Optional[str]]] = None,
        scenario: str = ESTIMACION.default_scenario,
    ) -> None:
        self.symbols = symbols
        # EO-4c: which Escenario the Estimación of each Clase is taken in
        # (pesimista / central / optimista). The caller resolves it from the
        # Perfil (``data.product_ux.profile_planning_scenario``).
        if scenario not in ESTIMACION.scenarios:
            raise ValueError(f"Escenario desconocido: {scenario!r}")
        self.scenario = scenario
        # EO-4a: the Clase of each symbol (``analysis.estimacion.classes_for``),
        # resolved by the caller so the simulator never goes to the network. None
        # keeps the pre-EO-4a haircut on the whole portfolio, and says so.
        self._asset_classes = dict(asset_classes) if asset_classes is not None else None
        self._asset_hist: Optional[np.ndarray] = None
        self._asset_weights: Optional[np.ndarray] = None
        self._asset_symbols: List[str] = []
        # #154: quote currency per symbol. Whatever is not given is resolved by
        # ``data.fx.quote_currency`` — none of the six places that build a simulator
        # knows it, and a Tokyo listing projected in yen is the defect.
        self._currencies: Dict[str, str] = dict(currencies or {})
        self.converted_currencies: Dict[str, str] = {}
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
        include_scenarios: bool = False,       # EO-4c: terminal stats of the three Escenarios
        contribution_growth_rate: float = 0.0, # N8b: yearly raise of the savings, its own assumption
        years_to_retirement: Optional[int] = None,  # WD-PHASED: save until then, spend after
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
                        metric refers to. Defaults to ``horizon_years``; with a
                        retirement phase, to ``WITHDRAWAL.default_longevity_years``.
                        Counted from retirement.
        years_to_retirement : WD-PHASED. With a strategy and a value > 0 the plan
                        saves for that many years —``annual_contribution``,
                        monthly— and the strategy draws from the pot each path
                        reached by then, for ``longevity_years`` more. ``None``
                        or ≤ 0 is the plan that is already retired: the strategy
                        draws from today, the savings stay out and the result is
                        byte-identical to the engine before this parameter.
                        Without a strategy it is ignored.
        include_realistic_reference : when True, runs a second compact pass on
                        the RAW historical returns (no conservative haircut) and
                        populates the ``realistic_*`` fields so the UI can show
                        the realistic median next to the conservative one. Drags
                        and withdrawals are applied identically, so the two
                        differ by exactly the haircut. Uses the same bootstrap
                        draws (re-seeded), so the comparison is apples-to-apples.
                        When False the engine is byte-identical to before.
        include_scenarios : EO-4c. When True, ``result.scenarios`` carries the
                        terminal stats of the three Escenarios: this run's for
                        its own, and a full re-run —same kwargs, a copy of this
                        simulator re-seeded identically— for each of the other
                        two, so goals, withdrawals and drags are applied the same
                        way. Same draws as this run when it is the first one on
                        the instance. Three times the cost; off by default.
        """
        run_kwargs = dict(
            horizon_years=horizon_years, n_sims=n_sims, initial_value=initial_value,
            annual_withdrawal=annual_withdrawal, annual_contribution=annual_contribution,
            target_value=target_value, withdrawal_growth_rate=withdrawal_growth_rate,
            drags=drags, withdrawal_strategy=withdrawal_strategy,
            longevity_years=longevity_years, contribution_growth_rate=contribution_growth_rate,
            years_to_retirement=years_to_retirement,
        )
        result = MonteCarloResult(
            n_sims=n_sims,
            horizon_years=horizon_years,
            initial_value=initial_value,
            annual_withdrawal=annual_withdrawal,
            annual_contribution=annual_contribution,
            target_value=target_value,
        )
        result.scenario = self.scenario

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

        # 2 — EO-4a: recentre each asset on its Estimación (or keep the haircut)
        port_hist_adj = self._estimation_adjustment(port_hist, result)

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
        #
        # WD-PHASED: con una fase de ahorro la longevidad se cuenta desde el
        # retiro, así que la ventana larga termina R + longevidad años después de
        # hoy. Sin estrategia la edad de retiro no significa nada para el motor.
        retirement_years = 0
        if withdrawal_strategy is not None and years_to_retirement and int(years_to_retirement) > 0:
            retirement_years = int(years_to_retirement)
            longevity_years = (
                int(longevity_years) if longevity_years else int(WITHDRAWAL.default_longevity_years)
            )
            sim_years = max(int(horizon_years), retirement_years + longevity_years)
        else:
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
            # REALISTIC-TAIL-CLIP: the plan covers the years this market has, not
            # `n_sim_weeks`. The two kernels below clip every flow onto the last
            # week, so a market shorter than the plan — the realistic reference
            # only draws the projection horizon — got the spending of the years it
            # does not simulate all at once, on the week of the terminal. With the
            # defaults (horizon 20, longevity 30) the realistic median fell below
            # the conservative one, or to 0. `_apply_phased_plan` drops those
            # events instead, so it keeps `n_sim_weeks`.
            plan_weeks = min(n_sim_weeks, (market.shape[1] - 1) // 52 * 52)
            if strategy is not None and retirement_years:
                return self._apply_phased_plan(
                    market, initial_value, basis, contribution, strategy,
                    retirement_years, n_sim_weeks,
                    withdrawal_growth_rate=withdrawal_growth_rate,
                    contribution_growth_rate=contribution_growth_rate,
                ) * basis
            if strategy is not None:
                return apply_withdrawal_strategy(
                    market, initial_value, strategy, plan_weeks,
                    inflation_rate=withdrawal_growth_rate,
                ) * initial_value
            return self._apply_cash_flows(
                market, initial_value, basis, withdrawal, contribution,
                plan_weeks, withdrawal_growth_rate=withdrawal_growth_rate,
                contribution_growth_rate=contribution_growth_rate,
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
                start_week=retirement_years * 52,
            )
            result.withdrawal_strategy_applied = strategy.to_dict()
            result.retirement_years = retirement_years
            # WD-STRATEGY-CONTRIB: apply_withdrawal_strategy takes no deposits, so a
            # plan with savings and a strategy projects without the savings. That
            # is the decided model when there is no saving phase — a strategy
            # means you already retired — but the screen must not show it as a
            # projection that includes them. With a phase (WD-PHASED) they do go in.
            if contribution > 0 and not retirement_years:
                result.contribution_ignored_by_strategy = contribution
                result.warnings.append(
                    f"Con una estrategia de retiro activa la proyección no incluye tu "
                    f"ahorro (${contribution:,.0f}/año): la estrategia supone que ya "
                    f"estás retirado y gastando. Para ver el plan con tu ahorro, volvé "
                    f"a «Acumulación (sin retiros)»."
                )
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
        if include_scenarios:
            result.scenarios = self._scenario_stats(result, run_kwargs)
        return result

    @staticmethod
    def _terminal_stats(res: "MonteCarloResult") -> Dict[str, float]:
        return {
            "median_terminal": res.median_terminal,
            "p10_terminal": res.p10_terminal,
            "p90_terminal": res.p90_terminal,
            "prob_achieve_target_pct": res.prob_achieve_target_pct,
        }

    def _scenario_stats(self, result: "MonteCarloResult", run_kwargs: dict) -> Dict[str, Dict[str, float]]:
        """The three Escenarios' terminal stats (EO-4c); see ``run(include_scenarios=)``."""
        out: Dict[str, Dict[str, float]] = {}
        for name in ESTIMACION.scenarios:
            if name == self.scenario:
                out[name] = self._terminal_stats(result)
                continue
            other = copy.copy(self)
            other.scenario = name
            other._rng = np.random.default_rng(self._seed)
            out[name] = self._terminal_stats(other.run(**run_kwargs))
        return out

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
        fx_excluded: List[str] = []

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
                s, ccy, reason = to_base_or_reason(
                    sym, s, self._currencies.get(sym),
                    period=self.HISTORY_PERIOD, interval="1wk",
                )
                if s is None:
                    fx_excluded.append(f"{sym} ({reason})" if ccy is None
                                       else f"{sym} ({ccy}: {reason})")
                    continue
                if fx_pair_symbol(ccy) is not None:
                    self.converted_currencies[sym] = ccy
                if len(s) >= 52:
                    frames[sym] = s
            except Exception as exc:
                logger.warning(f"MC: price fetch failed for {sym}: {exc}")

        if self.converted_currencies:
            logger.info(
                f"MC: {len(self.converted_currencies)} serie(s) convertidas a la moneda de "
                f"la cartera: {', '.join(f'{k} ({v})' for k, v in sorted(self.converted_currencies.items()))}"
            )
        if fx_excluded:
            warnings.append(
                "Fuera de la proyección por su moneda, para no proyectarlos como "
                f"dólares: {', '.join(fx_excluded)}."
            )

        if not frames:
            warnings.append("No se pudieron obtener datos de precio. Usando SPY como proxy.")
            rets, n, used, fallback_warnings = self._spy_fallback()
            return rets, n, used, warnings + fallback_warnings

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

        if len(symbols_used) + len(fx_excluded) < len(self.symbols):
            missing = len(self.symbols) - len(symbols_used) - len(fx_excluded)
            warnings.append(f"{missing} ticker(s) sin datos históricos — rebalanceando entre los disponibles.")

        weekly_returns = price_df.pct_change().dropna().values
        port_returns   = weekly_returns @ weights
        # EO-4a: the per-asset matrix, so each column can be recentred on its own
        # Estimación before it is weighted into the portfolio.
        self._asset_hist, self._asset_weights = weekly_returns, weights
        self._asset_symbols = symbols_used

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
    #  Estimación (EO-4a)                                                  #
    # ------------------------------------------------------------------ #

    def _estimation_adjustment(self, port_hist: np.ndarray, result: "MonteCarloResult") -> np.ndarray:
        """The portfolio series the bootstrap draws from (EO-4a).

        Compound recentring at the **portfolio** level —the contract EO-3 tested on
        the S&P, which is itself a portfolio—: the weekly deviations are the
        assets' own (weighted), and the portfolio's mean log-return is moved to
        ``log(1 + E) / 52``, so the median path earns ``E``. ``E`` is the weighted
        average of each asset's target: its Estimación, or —for bonds, tickers
        without a Clase and Clases without current Fuentes— its own history under
        the old haircut, whose deviations also keep the ×1,10.

        Recentring each asset on its Clase's central instead would hand a single
        stock the index's compound return with the stock's own volatility, i.e. a
        higher arithmetic return than the index; three of them rebalanced weekly
        projected 8,3 %/yr on a 6,7 % Estimación (live QA, 2026-10-06).

        Without ``asset_classes`` (or on the SPY fallback, which has no assets)
        this is ``_conservative_adjustment`` on the whole portfolio — byte-identical
        to the engine before EO-4a — and ``warnings`` says so.
        """
        if self._asset_classes is None:
            result.warnings.append(
                "Proyección con el ajuste histórico (−20 % al rendimiento, +10 % a la "
                "volatilidad): no se pasaron las Clases de los activos, así que no hay "
                "Estimación objetiva (sin Clases)."
            )
            return self._conservative_adjustment(port_hist)
        if self._asset_hist is None:
            return self._conservative_adjustment(port_hist)
        from analysis.estimacion import OBJETIVA, asset_estimations

        ests = asset_estimations(self._asset_symbols, self._asset_classes, self.scenario)
        result.estimations = [asdict(e) for e in ests]
        unclassed = [e.symbol for e in ests if e.asset_class is None]
        if unclassed:
            result.warnings.append(
                f"{', '.join(unclassed)} sin Clase: se proyecta(n) con el ajuste histórico "
                "(−20 % / +10 %) sobre su propia historia."
            )
        periods = ESTIMACION.periods_per_year
        deviations, targets = [], []
        for j, e in enumerate(ests):
            r = self._asset_hist[:, j]
            m = r.mean()
            if e.mode == OBJETIVA:
                deviations.append((r - m) * self.vol_scale)
                targets.append(np.expm1(np.log1p(e.annual_pct / 100.0) * self.return_scale))
            else:
                deviations.append((r - m) * MONTE_CARLO.vol_adjustment * self.vol_scale)
                weekly = m * MONTE_CARLO.mean_haircut * self.return_scale
                targets.append((1.0 + weekly) ** periods - 1.0)
        w = self._asset_weights
        port_dev = np.column_stack(deviations) @ w
        port_target = float(np.dot(w, targets))
        logr = np.log1p(port_dev)
        return np.expm1(logr - logr.mean() + np.log1p(port_target) / periods)

    # ------------------------------------------------------------------ #
    #  Conservative adjustment (bonds, no Clase, runs without Clases)      #
    # ------------------------------------------------------------------ #

    def _conservative_adjustment(self, returns: np.ndarray) -> np.ndarray:
        """
        The pre-EO-4a haircut, still used for bonds (EO-3 did not pass), tickers
        without a Clase and runs without ``asset_classes``:
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
        contribution_growth_rate: float = 0.0,
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

        Each direction grows with its own rate (N8b): withdrawals with
        ``withdrawal_growth_rate`` — the spending indexation Simulaciones feeds
        with inflation — and deposits with ``contribution_growth_rate``, default
        0. Until N8b one rate grew both, so indexing the spending also indexed
        the savings and the lab's lever moved an accumulation plan the wrong way.
        Either rate steps once a year, so the twelve deposits of a year still
        sum to that year's nominal total. Only the timing changes,
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

        # Contributions are queued first, and the sort below is stable, so a
        # deposit and a withdrawal on the same week keep that order.
        if annual_contribution:
            events += MonteCarloSimulator._flow_events(
                annual_contribution, MONTE_CARLO.contribution_periods_per_year, -1.0,
                contribution_growth_rate, basis, horizon_years, n_cols,
            )
        if annual_withdrawal:
            events += MonteCarloSimulator._flow_events(
                annual_withdrawal, MONTE_CARLO.withdrawal_periods_per_year, +1.0,
                withdrawal_growth_rate, basis, horizon_years, n_cols,
            )

        events.sort(key=lambda ev: ev[0])
        return apply_cash_flow_schedule(market, initial_value / basis, events)

    @staticmethod
    def _flow_events(
        annual_amount: float,
        periods_per_year: int,
        sign: float,
        growth_rate: float,
        basis: float,
        years: int,
        n_cols: int,
    ) -> List[Tuple[int, object]]:
        """A fixed flow of ``annual_amount`` a year for ``years`` years, as events.

        In multiples of ``basis``; ``sign`` −1 deposits, +1 withdraws. The amount
        steps up by ``growth_rate`` once a year, so the instalments of one year
        add up to that year's nominal total.
        """
        periods = max(1, int(periods_per_year))
        per_period = annual_amount / periods / basis
        events: List[Tuple[int, object]] = []
        for i, week in enumerate(cash_flow_weeks(periods, years, n_cols)):
            year = i // periods + 1
            grown = per_period * ((1 + growth_rate) ** (year - 1))
            events.append((week, _constant_amount(sign * grown)))
        return events

    @staticmethod
    def _apply_phased_plan(
        market: np.ndarray,
        initial_value: float,
        basis: float,
        annual_contribution: float,
        strategy: WithdrawalStrategy,
        years_to_retirement: int,
        n_sim_weeks: int,
        withdrawal_growth_rate: float = 0.0,
        contribution_growth_rate: float = 0.0,
    ) -> np.ndarray:
        """Save until retirement, then run the strategy on what each path saved.

        WD-PHASED. Deposits arrive monthly for ``years_to_retirement`` years —
        the same schedule ``_apply_cash_flows`` uses. Week ``52 R`` takes the pot
        **each path** reached, after that week's deposit, and the strategy's
        first instalment lands one withdrawal period later: its first year is
        the first one of retirement, drawn on that pot and not on today's
        capital. The
        fixed amount of ``fixed_real`` is in today's dollars, so it has already
        grown ``years_to_retirement`` years of inflation by the first withdrawal.

        Events past the end of ``market`` are dropped, not clipped onto its last
        week: a market that ends before retirement (the realistic reference only
        draws the projection horizon) just has not got there yet. In multiples of
        ``basis``, like ``_apply_cash_flows``.
        """
        n_cols = market.shape[1]
        unbounded = n_sim_weeks + 1
        events: List[Tuple[int, object]] = []
        if annual_contribution:
            events += MonteCarloSimulator._flow_events(
                annual_contribution, MONTE_CARLO.contribution_periods_per_year, -1.0,
                contribution_growth_rate, basis, years_to_retirement, unbounded,
            )
        retirement_week = years_to_retirement * 52
        events += phased_strategy_events(
            strategy,
            n_sims=market.shape[0],
            unit=basis,
            retirement_week=retirement_week,
            decumulation_years=n_sim_weeks // 52 - years_to_retirement,
            inflation_rate=withdrawal_growth_rate,
            index_years=years_to_retirement,
        )
        events = [ev for ev in events if ev[0] < n_cols]
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
        cannot express a plan starting from zero (U4-2). Its one rate grows
        whichever direction the sign names — the contract it was written with,
        kept byte-identical across N8b.
        """
        withdrawal = max(annual_withdrawal, 0.0)
        contribution = max(-annual_withdrawal, 0.0)
        return MonteCarloSimulator._apply_cash_flows(
            paths, initial_value, wealth_basis(initial_value, contribution),
            withdrawal, contribution, n_horizon_weeks,
            withdrawal_growth_rate=withdrawal_growth_rate,
            contribution_growth_rate=withdrawal_growth_rate,
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
        pct_severe = float((max_dd_per_path >= MONTE_CARLO.severe_drawdown_threshold).mean() * 100)

        # Year of max drawdown: median AND quartiles across paths. The IQR is
        # what makes the number honest — see the docstring.
        max_dd_week = np.argmax(drawdown, axis=1)   # week index of worst drawdown per path
        median_year_max_dd = float(np.median(max_dd_week) / 52)
        p25_year_max_dd = float(np.percentile(max_dd_week, 25) / 52)
        p75_year_max_dd = float(np.percentile(max_dd_week, 75) / 52)

        # SORR: % of paths with an early large drawdown (first 5 years)
        early_weeks = min(5 * 52, n_weeks_plus1)
        early_dd = drawdown[:, :early_weeks].max(axis=1)
        sorr_early = float((early_dd >= MONTE_CARLO.sorr_early_threshold).mean() * 100)

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
