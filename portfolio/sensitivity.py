"""
Sensitivity & scenario lab (Fase H.3).

A "what-if" workbench on top of the existing Monte Carlo engine. It answers
questions like *"if spending is indexed 1pp hotter, how much lower is my
pessimistic P10?"* or *"what if I live 5 years longer?"* using the user's OWN
plan numbers. The lever that used to be labelled "Inflación" moves
``withdrawal_growth_rate`` (N8): it is indexation of spending or deposits, not
a real-return inflation shock.

Design (mirrors the rest of the project):
  - Pure + injectable: the simulation is provided as a ``run_fn(params) ->
    MonteCarloResult`` callable, so this module needs no network and is fully
    unit-testable offline with a fake runner.
  - Config-driven: every perturbation magnitude comes from ``config.SENSITIVITY``;
    nothing is hardcoded.
  - The "base" run is never mutated — each factor/scenario perturbs a COPY of
    the base params, so the base case is always the comparison reference.

Two views are produced:
  - Tornado: one factor at a time (spending indexation, fees, real return,
    volatility), moved low/high, to rank what the plan's outcome is most
    sensitive to.
  - Scenarios: predefined retirement what-ifs (live longer, full real-world
    frictions, adverse market) shown as outcome deltas vs the base case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List

from config import SENSITIVITY
from data.product_ux import (
    INDEXATION_LABEL,
    INDEXATION_SCENARIO_DESCRIPTION,
    indexation_scenario_label,
)

# Metrics pulled from a MonteCarloResult for every run.
METRIC_KEYS = ("p10_terminal", "median_terminal", "p90_terminal", "prob_ruin_pct")

# A runner maps a params dict to something exposing the METRIC_KEYS attributes.
RunFn = Callable[[dict], object]


# ------------------------------------------------------------------ #
#  Result dataclasses                                                  #
# ------------------------------------------------------------------ #

@dataclass
class FactorResult:
    """One tornado row: a factor moved low vs high and the resulting metrics."""
    key: str
    label: str
    low_label: str
    high_label: str
    low: Dict[str, float] = field(default_factory=dict)    # metric -> value at low
    high: Dict[str, float] = field(default_factory=dict)   # metric -> value at high
    #: Whether moving this assumption reached the plan at all (U4-3). False when
    #: low and high left every metric identical — see ``_applies``.
    applies: bool = True


@dataclass
class ScenarioResult:
    """One predefined what-if: resulting metrics + deltas vs base."""
    key: str
    label: str
    description: str
    metrics: Dict[str, float] = field(default_factory=dict)
    deltas: Dict[str, float] = field(default_factory=dict)   # metric -> (scenario - base)
    #: Whether the what-if reached the plan at all (U4-3). False when every
    #: delta is exactly zero — see ``_applies``.
    applies: bool = True


@dataclass
class SensitivityResult:
    base: Dict[str, float]
    primary_metric: str
    factors: List[FactorResult] = field(default_factory=list)
    scenarios: List[ScenarioResult] = field(default_factory=list)


# ------------------------------------------------------------------ #
#  Param helpers                                                       #
# ------------------------------------------------------------------ #

def _metrics(result) -> Dict[str, float]:
    """Extract the comparison metrics from a MonteCarloResult-like object."""
    return {k: float(getattr(result, k, 0.0) or 0.0) for k in METRIC_KEYS}


def _applies(low: Dict[str, float], high: Dict[str, float]) -> bool:
    """Did moving this assumption reach the plan at all? (U4-3)

    An assumption that leaves **every** metric identical did not fail to matter:
    it never entered the wealth path. The tornado draws ``x = high - low``, so
    the two cases are the same picture — a zero-width bar next to its label,
    under a caption that says "the longest bar is what moves your result most".
    The user reads a measurement where there was none.

    Measured, not enumerated. The lab does not need to know which withdrawal
    method indexes spending: ``constant_pct`` takes a percentage of the current
    pot and never reads ``inflation_rate`` (``decumulation.py`` ~:389), and pure
    accumulation has no indexed spending to move at all — both come out of this
    comparison on their own, and so will the next method somebody adds.

    Compared across ALL of ``METRIC_KEYS`` rather than the charted one: a solvent
    plan reports ``prob_ruin_pct = 0`` for every factor, and reading only the
    metric selected in the UI would brand four live assumptions inapplicable.
    """
    return any(low.get(k) != high.get(k) for k in METRIC_KEYS)


def _bumped(params: dict, **changes) -> dict:
    """Return a copy of params with ``changes`` applied additively or set.

    Each change is ``key=(op, value)`` where op is "add" or "set". Numeric
    floors are applied for keys that must stay non-negative.
    """
    out = dict(params)
    for key, (op, value) in changes.items():
        cur = float(out.get(key, 0.0) or 0.0)
        out[key] = value if op == "set" else cur + value
    # Keep economic-drag total non-negative.
    if "drags_total_pct" in out and out["drags_total_pct"] is not None:
        out["drags_total_pct"] = max(0.0, float(out["drags_total_pct"]))
    return out


# ------------------------------------------------------------------ #
#  Tornado factors + scenarios                                         #
# ------------------------------------------------------------------ #

def _factor_specs(cfg) -> list[dict]:
    """Definition of the one-at-a-time tornado factors (config-driven)."""
    infl = cfg.inflation_delta_pct / 100.0
    return [
        {
            "key": "inflation",  # identifier kept; the label is N8
            "label": INDEXATION_LABEL,
            "param": "withdrawal_growth_rate",
            "delta": infl,
            "low_label": f"−{cfg.inflation_delta_pct:.1f}pp",
            "high_label": f"+{cfg.inflation_delta_pct:.1f}pp",
        },
        {
            "key": "fees",
            "label": "Fricciones (fees/drags)",
            "param": "drags_total_pct",
            "delta": cfg.fee_drag_delta_pct,
            "low_label": f"−{cfg.fee_drag_delta_pct:.2f}%",
            "high_label": f"+{cfg.fee_drag_delta_pct:.2f}%",
        },
        {
            "key": "real_return",
            "label": "Retorno histórico",
            "param": "return_scale",
            "delta": cfg.real_return_delta,
            "low_label": f"−{cfg.real_return_delta * 100:.0f}%",
            "high_label": f"+{cfg.real_return_delta * 100:.0f}%",
        },
        {
            "key": "volatility",
            "label": "Volatilidad",
            "param": "vol_scale",
            "delta": cfg.vol_delta,
            "low_label": f"−{cfg.vol_delta * 100:.0f}%",
            "high_label": f"+{cfg.vol_delta * 100:.0f}%",
        },
    ]


def _scenario_specs(cfg) -> list[dict]:
    """Predefined retirement what-ifs. ``changes`` feed ``_bumped``."""
    infl = cfg.inflation_delta_pct / 100.0
    return [
        {
            "key": "inflation_hot",  # identifier kept; the label is N8
            "label": indexation_scenario_label(cfg.inflation_delta_pct),
            "description": INDEXATION_SCENARIO_DESCRIPTION,
            "changes": {"withdrawal_growth_rate": ("add", infl)},
        },
        {
            "key": "drags_full",
            "label": "Fricciones reales completas",
            "description": f"Drags totales {cfg.full_drag_pct:.2f}%/año (fees + impuestos + rebalanceo + buffer AR).",
            "changes": {"drags_total_pct": ("set", cfg.full_drag_pct)},
        },
        {
            "key": "adverse_market",
            "label": "Mercado adverso",
            "description": "Retornos más bajos y mayor volatilidad de forma persistente.",
            "changes": {
                "return_scale": ("add", -2 * cfg.real_return_delta),
                "vol_scale": ("add", 2 * cfg.vol_delta),
            },
        },
        {
            "key": "live_longer",
            "label": f"Vivir {cfg.longevity_delta_years} años más",
            "description": "Horizonte de retiro más largo (riesgo de longevidad).",
            "changes": {
                "horizon_years": ("add", cfg.longevity_delta_years),
                "longevity_years": ("add", cfg.longevity_delta_years),
            },
        },
    ]


# ------------------------------------------------------------------ #
#  Public API                                                          #
# ------------------------------------------------------------------ #

def run_sensitivity(
    run_fn: RunFn,
    base_params: dict,
    *,
    cfg=SENSITIVITY,
    primary_metric: str = "p10_terminal",
    include_scenarios: bool = True,
) -> SensitivityResult:
    """Run the full sensitivity lab.

    Parameters
    ----------
    run_fn : callable
        ``params_dict -> MonteCarloResult``. Injected so the engine stays pure.
    base_params : dict
        The base Monte Carlo params (keys used: withdrawal_growth_rate,
        drags_total_pct, return_scale, vol_scale, horizon_years, longevity_years,
        plus whatever ``run_fn`` needs). Never mutated.
    primary_metric : str
        The metric the tornado is ranked/charted on (default pessimistic P10).
    include_scenarios : bool
        Also evaluate the predefined retirement scenarios.
    """
    base_res = run_fn(base_params)
    base_m = _metrics(base_res)

    factors: List[FactorResult] = []
    for spec in _factor_specs(cfg):
        low_p = _bumped(base_params, **{spec["param"]: ("add", -spec["delta"])})
        high_p = _bumped(base_params, **{spec["param"]: ("add", spec["delta"])})
        low_m = _metrics(run_fn(low_p))
        high_m = _metrics(run_fn(high_p))
        factors.append(FactorResult(
            key=spec["key"],
            label=spec["label"],
            low_label=spec["low_label"],
            high_label=spec["high_label"],
            low=low_m,
            high=high_m,
            applies=_applies(low_m, high_m),
        ))

    scenarios: List[ScenarioResult] = []
    if include_scenarios:
        for spec in _scenario_specs(cfg):
            m = _metrics(run_fn(_bumped(base_params, **spec["changes"])))
            scenarios.append(ScenarioResult(
                key=spec["key"],
                label=spec["label"],
                description=spec["description"],
                metrics=m,
                deltas={k: round(m[k] - base_m[k], 2) for k in METRIC_KEYS},
                applies=_applies(base_m, m),
            ))

    return SensitivityResult(
        base=base_m,
        primary_metric=primary_metric,
        factors=factors,
        scenarios=scenarios,
    )


def tornado_rows(result: SensitivityResult, metric: str | None = None) -> list[dict]:
    """Flatten a SensitivityResult into tornado-chart rows, sorted by impact.

    Each row: {key, label, low, high, base, swing, applies} for the chosen
    metric. Sorted descending by ``swing`` (|high − low|) so the most impactful
    factor is on top — the canonical tornado ordering.

    ``applies`` travels with the row because the surface cannot re-derive it: it
    is decided over every metric, not the one being charted (see ``_applies``).
    A row with ``applies=False`` must not be drawn as a zero-length bar.
    """
    metric = metric or result.primary_metric
    base = result.base.get(metric, 0.0)
    rows = []
    for f in result.factors:
        low = f.low.get(metric, 0.0)
        high = f.high.get(metric, 0.0)
        rows.append({
            "key": f.key,
            "label": f.label,
            "low_label": f.low_label,
            "high_label": f.high_label,
            "low": round(low, 2),
            "high": round(high, 2),
            "base": round(base, 2),
            "swing": round(abs(high - low), 2),
            "applies": f.applies,
        })
    rows.sort(key=lambda r: r["swing"], reverse=True)
    return rows
