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
  5. SLSQP Mean-Variance (minimize the negative attractiveness/vol ratio)
     with hard constraints
  6. Fallback: score-weighted allocation if SLSQP infeasible or insufficient data
  7. Generate Efficient Frontier (Monte Carlo, N=frontier_points)
  8. Compare vs current portfolio for rebalancing suggestions
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from scipy.optimize import minimize

from analysis.moat import classify_moat, moat_scale_max
from config import (
    ARS_RISK,
    OPTIMIZER,
    OPTIMIZER_PROFILES,
    TAILWINDS,
    THRESHOLDS,
    VIEW_WEIGHTS,
    OptimizerConfig,
    ProfileConfig,
)
from data.fetcher import get_history

# ETF tickers — excluded from optimization (no fundamentals)
_ETF_TICKERS = {"SPY", "QQQ", "VTI", "BND", "GLD", "SLV", "TLT", "IEF"}


def moat_rank_factor(moat_score: float, *, ai_available: bool) -> float:
    """El moat como multiplicador de ranking, en 0,5–1,5 (U3-7b).

    ``_core_rank`` documentaba ese rango y entregaba 0,53–1,10, porque dividía
    por 20 un total que sin IA tiene techo 12. El comentario decía la intención
    y el código el 60 % de ella.

    ``ai_available`` es obligatorio: la escala la decide la capa que produjo el
    número, igual que en ``classify_moat``.
    """
    from analysis.moat import moat_scale_max

    techo = moat_scale_max(ai_available=ai_available)
    return (float(moat_score) / techo) + 0.5 if techo > 0 else 0.5


def _moat_had_ai(row) -> bool:
    """Si la capa de IA corrió sobre esa fila.

    Se lee del dato, no se asume. Una fila que no lo trae se toma como
    cuantitativa: es lo que produce el screener, es lo que tienen las 150
    equities cacheadas, y equivocarse hacia esa escala sólo puede sub-estimar un
    moat enriquecido, nunca inflar uno que no lo está.
    """
    if isinstance(row, dict):
        valor = row.get("moat_ai_available")
    else:
        valor = getattr(row, "moat_ai_available", None)
    return bool(valor)


def is_ars_exposed(ticker: dict) -> bool:
    """Whether a row carries the macro risk the ARS discount exists for.

    U5-16: this was a literal set of six ADR symbols. Measured across the 167
    tickers in the shipped universes that set was exactly the companies the feed
    marks ``country == "Argentina"`` — right, but right by coincidence. It could
    not reach the one population it was unable to enumerate: an Argentine ADR a
    user adds through ``custom_tickers`` (GGAL, BMA, SUPV, BBAR, TGS, CRESY, IRS
    — none of which ship) got no discount, and the macro risk does not care who
    typed the symbol.

    A row with no country is **not** assumed exposed: unknown is not Argentina.
    """
    country = str(ticker.get("country") or "").strip()
    return bool(country) and country in tuple(ARS_RISK.exposed_countries)


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
    # The label the engine already computed, carried rather than re-derived: the
    # scale depends on whether the AI layer ran, and this row cannot tell (U3-7).
    moat_classification: str = ""
    is_ars: bool = False
    score_discounted: bool = False
    # Sector-country structural tailwind (Idea 2) — defaults keep backward compat
    tailwind_score: float = 0.0
    tailwind_classification: str = "Neutral"


@dataclass
class RebalanceSuggestion:
    symbol: str
    current_pct: float
    target_pct: float
    delta_pct: float           # positive = buy, negative = sell
    action: str                # "BUY" | "SELL" | "HOLD"


@dataclass
class GoalConstraints:
    """Derived constraints from user goals for goal-aware optimization."""
    nearest_horizon_years: int
    binding_goal_name: str          # name of the goal driving the constraint
    max_volatility_pct: float
    max_crypto_pct: float
    min_dividend_yield_pct: float
    explanation: str                # human-readable reason for each override


def _derive_constraints_from_goals(
    goals: list,
    base_cfg: "ProfileConfig",
    opt_cfg: "OptimizerConfig" = None,
) -> GoalConstraints:
    """
    Derives portfolio constraints from the goal with the shortest horizon.
    Grok rule: shortest horizon is always the binding constraint regardless of priority.
    Returns GoalConstraints describing each override with a plain-language explanation.
    """
    if not goals:
        return None

    if opt_cfg is None:
        from config import OPTIMIZER as opt_cfg  # type: ignore[assignment]

    # Sort by horizon to find the binding (shortest) goal
    sorted_goals = sorted(goals, key=lambda g: g["horizon_years"])
    binding = sorted_goals[0]
    horizon = binding["horizon_years"]
    name = binding.get("name", "tu meta")

    overrides = []

    # Vol cap — tighten based on shortest horizon (S10)
    if horizon <= 2:
        max_vol = min(base_cfg.max_volatility_pct, opt_cfg.glide_vol_cap_short)
        if max_vol < base_cfg.max_volatility_pct:
            overrides.append(f"Volatilidad máx reducida a {max_vol:.0f}% por '{name}' (horizonte {horizon}a)")
    elif horizon <= 5:
        max_vol = min(base_cfg.max_volatility_pct, opt_cfg.glide_vol_cap_medium)
        if max_vol < base_cfg.max_volatility_pct:
            overrides.append(f"Volatilidad máx reducida a {max_vol:.0f}% por '{name}' (horizonte {horizon}a)")
    elif horizon <= 10:
        max_vol = min(base_cfg.max_volatility_pct, opt_cfg.glide_vol_cap_long)
        if max_vol < base_cfg.max_volatility_pct:
            overrides.append(f"Volatilidad máx reducida a {max_vol:.0f}% por '{name}' (horizonte {horizon}a)")
    else:
        max_vol = base_cfg.max_volatility_pct

    # Crypto cap — restrict for short horizons (S10)
    if horizon <= 4:
        max_crypto = min(base_cfg.max_crypto_pct, opt_cfg.glide_crypto_cap_near)
        if max_crypto < base_cfg.max_crypto_pct:
            overrides.append(f"Cripto cap reducido a {max_crypto:.0f}% (meta cercana en {horizon}a)")
    elif horizon <= 7:
        max_crypto = min(base_cfg.max_crypto_pct, opt_cfg.glide_crypto_cap_mid)
        if max_crypto < base_cfg.max_crypto_pct:
            overrides.append(f"Cripto cap reducido a {max_crypto:.0f}% (meta en {horizon}a)")
    else:
        max_crypto = base_cfg.max_crypto_pct

    # Dividend floor — raise for near-term goals (cash flow matters) (S10)
    if horizon <= 3:
        min_div = max(base_cfg.min_dividend_yield_pct, opt_cfg.glide_div_floor_near)
        if min_div > base_cfg.min_dividend_yield_pct:
            overrides.append(f"Dividendo mínimo subido a {min_div:.1f}% (meta '{name}' necesita flujo en {horizon}a)")
    else:
        min_div = base_cfg.min_dividend_yield_pct

    if overrides:
        explanation = "🛡️ **Glide Path activo:** " + " · ".join(overrides) + "."
    else:
        explanation = f"✅ Sin cambios: tu meta más cercana ('{name}') tiene horizonte {horizon}a — el perfil base aplica sin restricciones adicionales."

    return GoalConstraints(
        nearest_horizon_years=horizon,
        binding_goal_name=name,
        max_volatility_pct=max_vol,
        max_crypto_pct=max_crypto,
        min_dividend_yield_pct=min_div,
        explanation=explanation,
    )


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

    # Rebalancing recommendation
    rebalance_frequency: str = ""       # e.g. "Anual", "Semestral", "Trimestral"
    rebalance_rationale: str = ""       # one-line explanation

    # Rule-of-thumb drawdown, 1-year horizon: −OPTIMIZER.max_dd_vol_multiple ×
    # annualised vol. Not a model — nothing is simulated and this portfolio's own
    # history is never read (U1-10). The simulated drawdown is
    # MonteCarloResult.median_max_drawdown_pct, a different figure.
    max_drawdown_estimate_pct: float = 0.0

    # ------------------------------------------------------------------
    # Instrumentation fields (populated by the optimizer for diagnostics)
    # ------------------------------------------------------------------
    n_input: int = 0              # scored_tickers received by optimize()
    n_eligible: int = 0           # after ETF/score filter
    n_candidates: int = 0         # after profile down-select (pre-SLSQP)
    slsqp_success: bool = False   # True when SLSQP converged (not fallback)
    build_matrix_ms: float = 0.0  # ms spent fetching price data

    # ------------------------------------------------------------------
    # Deterministic core portfolio (always populated by the optimizer;
    # does NOT require LLM — based on weight × score × moat heuristic).
    # The AI layer may replace/enrich grok_core_holdings with LLM output.
    # ------------------------------------------------------------------
    profile_core_holdings: List[dict] = field(default_factory=list)  # [{"symbol":, "suggested_weight_pct":, "why":""}]

    # ------------------------------------------------------------------
    # Grok AI voice + human-scale concentration advice (populated by the
    # AI layer in ai_analyzer when AI is enabled; the pure math optimizer
    # leaves these at their defaults).
    # ------------------------------------------------------------------
    ai_grok_narrative: str = ""                     # full Grok-voice explanation of the portfolio + macro
    grok_recommended_max_human_positions: int = 0   # what Grok thinks a normal human can actually track
    grok_core_holdings: List[dict] = field(default_factory=list)   # [{"symbol": , "suggested_weight_pct": , "why": ""}, ...]
    grok_dropped_tickers: List[dict] = field(default_factory=list)
    grok_human_review_tips: List[str] = field(default_factory=list)


class PortfolioOptimizer:
    """
    Conservative portfolio optimizer for retirement planning.

    Uses scipy SLSQP to minimize the negative attractiveness/vol ratio
    — (mu_proxy − Rf) / sigma_hist, a proxy numerator over a historical
    denominator, not a Sharpe — subject to:
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

    The resulting OptimizationResult may contain additional Grok AI fields
    (ai_grok_narrative, grok_core_holdings, etc.) when the caller (UI layer)
    enriches it with generate_optimizer_advice(). The pure optimizer itself
    never calls AI and always produces the full mathematical result.
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
        result.n_input = len(scored_tickers)

        # 1 — Filter
        eligible, excluded = self._filter_eligible(scored_tickers)
        result.excluded = excluded
        result.n_eligible = len(eligible)

        if len(eligible) < 2:
            result.warnings.append("Insuficientes tickers elegibles para optimizar.")
            result.method = "score-weighted"
            return result

        # 2 — ARS discount
        eligible = self._apply_ars_discount(eligible)

        # 2b — Profile-aware candidate down-select (Fase C)
        # Reduces large eligible sets to a manageable pool before cov/SLSQP,
        # tilted by the profile's scoring priorities. Avoids dusty allocations
        # and improves performance for N>pre_filter_top_k universes.
        eligible = self._select_candidates_for_profile(eligible)
        result.n_candidates = len(eligible)

        if result.n_candidates < result.n_eligible:
            logger.info(
                f"[{self.cfg.name}] Profile down-select: {result.n_eligible} eligible → "
                f"{result.n_candidates} candidates (top_k={self.cfg.pre_filter_top_k})"
            )

        symbols = [t["symbol"] for t in eligible]

        # 3 — Price matrix (parallelized)
        t0 = time.monotonic()
        price_matrix = self._build_price_matrix(symbols)
        result.build_matrix_ms = round((time.monotonic() - t0) * 1000, 1)
        usable_symbols = list(price_matrix.columns)

        logger.info(
            f"[{self.cfg.name}] n_input={result.n_input} eligible={result.n_eligible} "
            f"candidates={result.n_candidates} usable={len(usable_symbols)} "
            f"matrix_ms={result.build_matrix_ms}"
        )

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

        # 4b — Black-Litterman posterior (Fase 5): blend the score-derived views
        # with the market equilibrium. Opt-in (config) + guarded; on any mismatch
        # or failure it returns the original proxy so the path stays valid.
        mu = self._apply_black_litterman(mu, cov, eligible_filtered, cov_available)

        # 5 — Optimize
        weights = None
        if cov_available:
            weights = self._run_slsqp(mu, cov, eligible_filtered)

        if weights is None:
            result.method = "score-weighted"
            result.slsqp_success = False
            result.warnings.append("SLSQP sin solución factible — usando score-weighted.")
            weights = self._score_weighted_optimize(eligible_filtered)
        else:
            result.slsqp_success = True

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

        # 6b — Deterministic core (always computed, no LLM required)
        result.profile_core_holdings = self._select_core_holdings(result.tickers)

        logger.info(
            f"[{self.cfg.name}] result: {len(result.tickers)} pos, "
            f"method={result.method}, core={len(result.profile_core_holdings)}, "
            f"slsqp={result.slsqp_success}"
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

        # 9 — Rebalancing frequency recommendation
        result.rebalance_frequency, result.rebalance_rationale = self._suggest_rebalance_frequency(result)

        return result

    # ------------------------------------------------------------------ #
    #  Filtering                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _data_quality_level(t: dict) -> str:
        """Resolve data-quality level from flat or nested scored-ticker dicts."""
        level = t.get("data_quality_level")
        if level:
            return str(level)
        dq = t.get("data_quality")
        if isinstance(dq, dict) and dq.get("level"):
            return str(dq["level"])
        return "good"

    def _filter_eligible(
        self, scored_tickers: List[dict]
    ) -> Tuple[List[dict], List[Tuple[str, str]]]:
        from config import DATA_QUALITY

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
            dq_level = self._data_quality_level(t)
            if DATA_QUALITY.exclude_poor_from_optimizer and dq_level == "poor":
                excluded.append((sym, "Data quality pobre — excluido de optimización"))
                continue
            # Work on a shallow copy so screener cache scores stay intact.
            row = dict(t)
            haircut = float(getattr(DATA_QUALITY, "partial_optimizer_score_haircut", 1.0) or 1.0)
            if dq_level == "partial" and 0 < haircut < 1.0:
                base = float(row.get("adjusted_score", row.get("total_score", 0)) or 0)
                row["adjusted_score"] = round(base * haircut, 4)
                row["_dq_partial_haircut"] = haircut
            eligible.append(row)
        return eligible, excluded

    def _apply_ars_discount(self, tickers: List[dict]) -> List[dict]:
        if self.profile_key == "aggressive":
            return tickers
        result = []
        for t in tickers:
            t = dict(t)
            if is_ars_exposed(t):
                original = float(t.get("adjusted_score", 0) or 0)
                t["adjusted_score"] = original * self.opt.ars_risk_discount
                t["_ars_discounted"] = True
            result.append(t)
        return result

    @staticmethod
    def _clean_div_yield(raw: float) -> float:
        """Drop implausible dividend yields — yfinance mixes units across its
        dividend fields, so a "313 %" yield is a unit error, not an opportunity.

        U5-10: the ceiling was a literal 15.0 here and
        ``THRESHOLDS.max_plausible_dividend_yield_pct`` (30.0) in
        ``normalize_dividend_yield_pct``. One question, two answers 15 pp apart:
        a 20 % yield was scored by the fundamental engine and silently rewritten
        to 0.0 by the optimizer, so the same company was paid for its dividend
        in the score and not in μ. Both now read the same number, and the
        scorer's is the one that survives — it is the one that *logs* the
        discard instead of blanking the value without a trace.
        """
        ceiling = THRESHOLDS.max_plausible_dividend_yield_pct
        return raw if 0 <= raw <= ceiling else 0.0

    def _rank_score(self, t: dict) -> float:
        """Puntaje compuesto que decide qué candidatos entran a SLSQP.

        Método y no una función local adentro del down-select, para que sea
        ejercitable directo: es lo que elige el pool sobre el que después corre
        toda la optimización.

        U3-7b: el moat se normaliza por el techo que aplica a ESA fila, no por
        20 siempre. Con las 150 equities cacheadas —todas sin IA, todas bajo 12—
        el `/20` dejaba al término de moat aportando el 60 % de `moat_weight`.
        """
        cfg = self.cfg
        score = float(t.get("adjusted_score", 0) or 0) / 100.0
        div = self._clean_div_yield(float(t.get("dividend_yield", 0) or 0)) / self.opt.div_yield_normalization_pct
        moat = float(t.get("moat_score", 0) or 0) / moat_scale_max(
            ai_available=_moat_had_ai(t)
        )
        return cfg.score_weight * score + cfg.dividend_weight * div + cfg.moat_weight * moat

    # ------------------------------------------------------------------ #
    #  Profile-aware candidate selection (Fase C)                          #
    # ------------------------------------------------------------------ #

    def _select_candidates_for_profile(self, eligible: List[dict]) -> List[dict]:
        """
        Down-select eligible tickers to at most cfg.pre_filter_top_k candidates
        using a profile-tilted composite rank.

        Conservative: income_quality = 0.45×div + 0.35×score + 0.20×moat
        Moderate:     balance = 0.30×div + 0.50×score + 0.20×moat
        Aggressive:   growth = 0.15×div + 0.65×score + 0.20×moat

        Uses the same weights as the profile's expected_returns objective so the
        pre-filter is consistent with the optimizer's objective function.
        A minimum of cfg.min_positions candidates is always preserved so the
        optimizer can satisfy diversity constraints.
        """
        k = self.cfg.pre_filter_top_k
        min_keep = max(self.cfg.min_positions + 2, k)  # never drop below min_positions+2
        if len(eligible) <= min_keep:
            return eligible

        ranked = sorted(eligible, key=self._rank_score, reverse=True)
        return ranked[:k]

    # ------------------------------------------------------------------ #
    #  Deterministic core portfolio selector (Fase C / Fase B fallback)   #
    # ------------------------------------------------------------------ #

    def _select_core_holdings(self, allocations: List["TickerAllocation"]) -> List[dict]:
        """
        Build a human-manageable core portfolio without calling any LLM.

        Ranks allocated positions by weight × adjusted_score × moat_rank_factor(...)
        and keeps the top cfg.target_max_human_positions. Rescales weights to 100 %
        and adds a plain-data reason line (no LLM needed).

        Returns [{"symbol":, "suggested_weight_pct":, "why":""}, ...]
        """
        if not allocations:
            return []

        target = self.cfg.target_max_human_positions

        def _core_rank(a: "TickerAllocation") -> float:
            moat_factor = moat_rank_factor(          # range 0.5–1.5, de verdad
                a.moat_score, ai_available=_moat_had_ai(a)
            )
            return a.weight_pct * (a.adjusted_score / 100.0) * moat_factor

        ranked = sorted(allocations, key=_core_rank, reverse=True)
        core = ranked[:target]

        total_w = sum(a.weight_pct for a in core)
        if total_w <= 0:
            return []

        result = []
        for a in core:
            rescaled = round(a.weight_pct / total_w * 100.0, 1)
            # U3-7: this used to hardcode `>= 14` on the 0–20 scale, over rows
            # that in the Optimizer path usually come without AI — where the
            # quantitative tramo caps at 12, so "Wide Moat" was unreachable and
            # this screen disagreed with every other one about the same ticker.
            # Prefer the label the engine computed; classify only as a fallback,
            # and then on the quant-only scale, which is what a bare score is.
            _moat_class = a.moat_classification or classify_moat(
                a.moat_score, ai_available=False
            )
            moat_label = f"{_moat_class} Moat · " if _moat_class in ("Wide", "Narrow") else ""
            div_note = f"Div {a.dividend_yield_pct:.1f}% · " if a.dividend_yield_pct >= 1.0 else ""
            _twc = getattr(a, "tailwind_classification", "Neutral")
            tw_note = ""
            if _twc == "Strong":
                tw_note = "🌬️ Tailwind sector-país · "
            elif _twc == "Headwind":
                tw_note = "🌪️ Headwind sector-país · "
            why = f"{moat_label}{tw_note}{div_note}Score {a.adjusted_score:.0f} · {a.sector}"
            result.append({
                "symbol":              a.symbol,
                "suggested_weight_pct": rescaled,
                "why":                 why,
            })
        return result

    # ------------------------------------------------------------------ #
    #  Price data (parallelized)                                           #
    # ------------------------------------------------------------------ #

    def _fetch_single_price(self, sym: str, period: str, min_obs: int):
        """Fetch price history for one symbol. Returns (sym, series) or (sym, None)."""
        try:
            hist = get_history(sym, period=period, interval="1wk")
            if hist.empty:
                return sym, None
            if "Date" in hist.columns:
                hist = hist.set_index("Date")
            elif "date" in hist.columns:
                hist = hist.set_index("date")
            close_col = "close" if "close" in hist.columns else "Close"
            if close_col not in hist.columns:
                return sym, None
            series = hist[close_col].dropna()
            if len(series) >= min_obs:
                return sym, series
        except Exception as exc:
            logger.warning(f"Price data failed for {sym}: {exc}")
        return sym, None

    def _build_price_matrix(self, symbols: List[str]) -> pd.DataFrame:
        """Weekly close prices for price_history_years. Parallel fetch with ThreadPoolExecutor."""
        period = f"{self.opt.price_history_years}y"
        min_obs = self.opt.price_history_years * 40

        frames = {}
        workers = min(self.opt.price_fetch_max_workers, len(symbols)) if symbols else 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._fetch_single_price, sym, period, min_obs): sym for sym in symbols}
            for fut in as_completed(futures):
                sym, series = fut.result()
                if series is not None:
                    frames[sym] = series

        if not frames:
            return pd.DataFrame()

        matrix = pd.DataFrame(frames)
        matrix.index = pd.to_datetime(matrix.index)
        matrix = matrix.sort_index().dropna(how="all")
        matrix = matrix.loc[:, matrix.count() >= min_obs]
        matrix = matrix.ffill().dropna()
        return matrix

    # ------------------------------------------------------------------ #
    #  Expected returns & covariance                                       #
    # ------------------------------------------------------------------ #

    def _expected_returns(self, tickers: List[dict]) -> np.ndarray:
        """
        Composite expected-return *view* per ticker (Black-Litterman views).

        Blends adjusted_score and dividend_yield using the global
        ``VIEW_WEIGHTS`` — deliberately NOT the profile's preference weights.

        The moat is NOT a third term (U5-6). ``adjusted_score`` already carries
        the moat bonus the engine assigned it, so adding a moat term paid the
        same advantage twice and overweighted wide-moat companies against the
        engine's own valuation of them. Removing it moved μ by −0.50 pp on
        average across the 150 cached equities and turned over 2 names in the
        top 20. The moat still reaches μ — once, through the score.

        An asset's expected return is a property of the asset, not of who is
        looking at it. Until the 2026-08 audit this used ``cfg.score_weight``
        et al., so the same ticker "yielded" 5.08% for a conservative investor
        and 7.72% for an aggressive one (audit D3). The profile now enters
        through ``cfg.risk_aversion`` (the δ of the BL equilibrium prior) and
        through the SLSQP constraints, which is where preference belongs.

        The sector-country tailwind (Idea 2) IS a second expression of something
        already inside adjusted_score, and unlike the moat term that is
        deliberate and bounded: ``TAILWINDS.optimizer_er_tilt`` caps it at
        ≈ ±0.9% annual at score ±10, versus the ±1.0% the moat term added
        unbounded by any such intent. It is opt-out (set the config to 0) and
        neutral tickers are unaffected. The difference that matters is that this
        one is a declared tilt with a knob, not an accounting error.
        """
        views = VIEW_WEIGHTS
        mu = []
        for t in tickers:
            score = float(t.get("adjusted_score", 0) or 0)
            div = self._clean_div_yield(float(t.get("dividend_yield", 0) or 0))
            tailwind = float(t.get("tailwind_score", 0) or 0)

            # Normalised components → annualised return proxies
            span = self.opt.score_return_span        # U5-9: was a literal 0.18
            score_ret = (score / 100) * span
            div_ret = div / 100                      # dividend yield as-is

            composite = (
                views.score * score_ret
                + views.dividend * div_ret
            )
            if TAILWINDS.enabled and tailwind != 0.0:
                composite += TAILWINDS.optimizer_er_tilt * (tailwind / 10.0) * span
            # P2 audit D4: hard ceiling so score-proxy μ stays economically plausible
            cap = float(getattr(self.opt, "er_absolute_cap", 0.0) or 0.0)
            if cap > 0:
                composite = min(composite, cap)
            mu.append(composite)
        return np.array(mu)

    def _covariance_matrix(self, price_matrix: pd.DataFrame) -> np.ndarray:
        """Annualised covariance from weekly returns. Adds small regularisation diagonal.

        Fase 5: when ``BLACK_LITTERMAN.shrinkage_enabled`` the full Ledoit-Wolf
        shrinkage estimator is used (more stable with few observations → fewer
        extreme weights); otherwise the legacy sample covariance path.
        """
        weekly_ret = price_matrix.pct_change().dropna()
        from config import BLACK_LITTERMAN as _BL
        if _BL.shrinkage_enabled and weekly_ret.shape[0] >= 2 and weekly_ret.shape[1] >= 2:
            try:
                from portfolio.black_litterman import ledoit_wolf_shrinkage

                cov, shrink = ledoit_wolf_shrinkage(weekly_ret.values, periods_per_year=52.0)
                logger.debug(f"covariance: Ledoit-Wolf shrinkage intensity={shrink:.3f}")
                return cov
            except Exception as exc:
                logger.warning(f"Ledoit-Wolf shrinkage failed ({exc}); using sample covariance")
        cov = weekly_ret.cov().values * 52  # annualise
        # Ledoit-Wolf-style regularisation (avoids near-singular matrices)
        cov += np.eye(cov.shape[0]) * 1e-6
        return cov

    def _apply_black_litterman(self, mu: np.ndarray, cov: np.ndarray,
                               tickers: List[dict], cov_available: bool) -> np.ndarray:
        """Blend the score-view expected returns with the market equilibrium (BL).

        Opt-in via ``BLACK_LITTERMAN.enabled`` and fully guarded: on any size
        mismatch, single asset, or numerical failure it returns ``mu`` unchanged.
        """
        from config import BLACK_LITTERMAN as _BL

        if not _BL.enabled or not cov_available:
            return mu
        if cov.shape[0] != len(mu) or len(mu) < 2:
            return mu
        try:
            from portfolio.black_litterman import bl_expected_returns

            caps = np.array([float(t.get("market_cap", 0) or 0) for t in tickers], dtype=float)
            market_weights = caps if caps.sum() > 0 else None
            conf = None
            if _BL.use_score_confidence:
                conf = np.array(
                    [max(0.1, float(t.get("adjusted_score", 0) or 0) / 100.0) for t in tickers],
                    dtype=float,
                )
            # δ comes from the PROFILE, not the global BL default: this is the
            # one place the investor's risk appetite legitimately shapes the
            # return anchor (audit D3). Falls back to the global when a profile
            # predates the field.
            delta = float(getattr(self.cfg, "risk_aversion", 0) or _BL.risk_aversion)
            posterior = bl_expected_returns(
                mu, cov, market_weights=market_weights, view_confidence=conf,
                risk_aversion=delta, tau=_BL.tau,
            )
            if posterior is not None and len(posterior) == len(mu) and np.all(np.isfinite(posterior)):
                return np.asarray(posterior, dtype=float)
        except Exception as exc:
            logger.warning(f"Black-Litterman posterior skipped — {exc}")
        return mu

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

        # --- Bounds: per-ticker [min_weight, max_pct] ---
        # Crypto tickers get a tighter cap (max_crypto_pct) to prevent over-concentration
        # of a single high-volatility asset in retirement portfolios.
        lb = self.opt.min_weight_pct / 100
        standard_ub = max(cfg.max_position_pct / 100, 1.0 / n)
        crypto_ub   = max(cfg.max_crypto_pct / 100, lb)

        from config import is_crypto as _is_crypto_ticker
        bounds = [
            (lb, crypto_ub if _is_crypto_ticker(t["symbol"]) else standard_ub)
            for t in tickers
        ]

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
        # Clip initial guess using per-ticker upper bounds array
        ub_arr = np.array([b[1] for b in bounds])
        w0 = np.clip(w0, lb, ub_arr)
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
                # Clip to actual bounds (not just [0,1]) so numerical overflow
                # from SLSQP doesn't allow any ticker to exceed max_position_pct
                w = np.clip(res.x, lb, ub_arr)
                if w.sum() > 0:
                    w /= w.sum()
                if n > cfg.min_positions:
                    w[w < lb * 0.5] = 0
                    if w.sum() > 0:
                        w /= w.sum()
                logger.info(f"SLSQP converged — proxy/vol ratio {-res.fun:.3f}")
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
        """Proportional allocation by adjusted_score, clipped to profile bounds.

        Crypto tickers are capped at max_crypto_pct regardless of score.
        """
        cfg = self.cfg
        scores = np.array([float(t.get("adjusted_score", 1) or 1) for t in tickers])
        scores = np.clip(scores, 0.01, None)
        w = scores / scores.sum()

        from config import is_crypto as _is_crypto_ticker
        standard_ub = cfg.max_position_pct / 100
        crypto_ub   = cfg.max_crypto_pct / 100
        ubs = np.array([
            crypto_ub if _is_crypto_ticker(t["symbol"]) else standard_ub
            for t in tickers
        ])

        # Water-filling: cap over-allocated tickers and redistribute excess
        # to under-allocated ones. Converges in ≤ n iterations (one per ticker).
        for _ in range(len(tickers) + 5):
            over = w > ubs + 1e-10
            if not over.any():
                break
            excess = (w[over] - ubs[over]).sum()
            w[over] = ubs[over]
            under = ~over
            if w[under].sum() > 1e-10:
                # Redistribute excess proportionally among uncapped tickers
                w[under] += excess * (w[under] / w[under].sum())

        # Final normalisation guard (handles floating-point drift)
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
        # Normalize to sum=1 before any display logic (guards against floating-point
        # drift and the double-zeroing in _try_minimize leaving a sum < 1)
        weights = np.asarray(weights, dtype=float).copy()
        if weights.sum() > 0:
            weights /= weights.sum()
        # Hard-cap each position to profile max (defensive: SLSQP can overshoot
        # bounds by a small epsilon; renormalization can amplify this)
        max_w = self.cfg.max_position_pct / 100
        if weights.max() > max_w + 0.001:
            weights = np.clip(weights, 0, max_w)
            if weights.sum() > 0:
                weights /= weights.sum()
        # Zero dust positions
        weights[weights < 0.001] = 0.0
        # Re-normalize after zeroing so displayed weights sum exactly to 100 %
        if weights.sum() > 0:
            weights /= weights.sum()

        rf = self.opt.risk_free_rate

        sector_weights: Dict[str, float] = {}
        allocations = []

        for i, (t, w, er) in enumerate(zip(tickers, weights, mu)):
            if w < 1e-6:
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
                moat_classification=str(t.get("moat_classification", "") or ""),
                is_ars=is_ars_exposed(t),
                score_discounted=bool(t.get("_ars_discounted", False)),
                tailwind_score=round(float(t.get("tailwind_score", 0.0) or 0.0), 1),
                tailwind_classification=str(t.get("tailwind_classification", "Neutral") or "Neutral"),
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
                # 1-year max drawdown estimate: empirical rule
                # MaxDD ≈ −multiple × annual vol. The multiple is config (U1-10);
                # the value did not move.
                result.max_drawdown_estimate_pct = round(
                    -result.volatility_pct * self.opt.max_dd_vol_multiple, 1
                )

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

    def _suggest_rebalance_frequency(self, result: OptimizationResult) -> Tuple[str, str]:
        """
        Recommend rebalancing cadence based on profile and portfolio drift.

        Conservative: annual — minimize transaction costs and tax drag.
        Moderate: semi-annual — capture drift without excessive churn.
        Aggressive: quarterly — track growth opportunities and control risk.
        High volatility portfolios get bumped up one tier.
        """
        high_vol = result.volatility_pct > 18.0

        if self.profile_key == "conservative":
            if high_vol:
                return (
                    "Semestral",
                    "La volatilidad supera el objetivo del perfil — "
                    "revisar cada 6 meses para contener la deriva.",
                )
            return (
                "Anual",
                "El perfil Conservador minimiza rotación para reducir costos y carga fiscal. "
                "Rebalancear en enero con cada ciclo anual de revisión.",
            )
        elif self.profile_key == "moderate":
            if high_vol:
                return (
                    "Trimestral",
                    "Volatilidad elevada para el perfil — "
                    "revisión trimestral para capturar la deriva de manera oportuna.",
                )
            return (
                "Semestral",
                "Rebalanceo cada 6 meses (enero y julio) captura la deriva del mercado "
                "sin generar exceso de operaciones.",
            )
        else:  # aggressive
            return (
                "Trimestral",
                "El perfil Agresivo se beneficia de revisión trimestral para capturar "
                "oportunidades de crecimiento y reencuadrar el riesgo activamente.",
            )

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

    # ------------------------------------------------------------------ #
    #  Goal-Aware Optimization (Fase 2)                                    #
    # ------------------------------------------------------------------ #

    def optimize_for_goals(
        self,
        scored_tickers: List[dict],
        goals: list,
        current_weights: Optional[Dict[str, float]] = None,
    ) -> tuple:
        """
        Run optimization with constraints derived from user goals.

        goals: list of dicts with keys: name, horizon_years, priority, target_amount_today, etc.
               (raw session_state format, no Goal dataclass import needed)

        Returns: (OptimizationResult, explanation_str)
        """
        import dataclasses

        constraints = _derive_constraints_from_goals(goals, self.cfg, self.opt)

        # No override needed — all goals have long horizons
        if constraints is None or (
            constraints.max_volatility_pct == self.cfg.max_volatility_pct
            and constraints.max_crypto_pct == self.cfg.max_crypto_pct
            and constraints.min_dividend_yield_pct == self.cfg.min_dividend_yield_pct
        ):
            result = self.optimize(scored_tickers, current_weights)
            explanation = constraints.explanation if constraints else "Sin metas definidas."
            return result, explanation

        # Temporarily override profile config with goal-derived constraints
        original_cfg = self.cfg
        try:
            self.cfg = dataclasses.replace(
                original_cfg,
                max_volatility_pct=constraints.max_volatility_pct,
                max_crypto_pct=constraints.max_crypto_pct,
                min_dividend_yield_pct=constraints.min_dividend_yield_pct,
            )
            result = self.optimize(scored_tickers, current_weights)
        finally:
            self.cfg = original_cfg

        result.profile_name = f"{original_cfg.name} · Metas"
        return result, constraints.explanation
