"""
Decumulation / withdrawal-strategy engine (Fase H.1).

Turns the Monte Carlo projection from a pure *accumulation* tool into a
*retirement* tool: given simulated portfolio paths, it applies a chosen
withdrawal strategy during the spending phase and reports retirement-specific
success metrics ("will my income last?", "how likely am I to leave a legacy?",
"when do I typically run dry if I do?").

Design rules (mirror the rest of the project):
  - Pure NumPy, no Streamlit, no network — fully testable offline.
  - Functions operate on the *relative* paths array (start = 1.0) produced by
    ``MonteCarloSimulator._simulate_paths``; ``initial_value`` converts to USD.
  - Strategies are config-driven (``config.WITHDRAWAL``); nothing hardcoded.
  - ``cash_flow_units`` is the single implementation of the cash-flow maths.
    ``MonteCarloSimulator._apply_cash_flows`` delegates to it, so the two entry
    points cannot drift apart.

Cash-flow semantics (audit D1/D2 in 2026-08, backlog U4-1/U4-2 in tier2)
------------------------------------------------------------------------
The pot is held as **units of the market index**: wealth is ``units × market``.
A withdrawal sells units, so the cash leaves and only the remaining capital
keeps compounding — never subtracting a constant nominal level from every future
week, which is what let withdrawn money keep growing implicitly and overstated
terminal wealth by ~60% over 30 years (``docs/AUDITORIA_2026-08.md`` D1,
``tests/test_withdrawal_oracle.py``).

Ruin is absorbing by construction: units floored at 0 stay 0, so no amount of
market growth revives a pot that was spent (D2) — no separate bookkeeping.

Holding units rather than a rescaled wealth path is also what makes a *deposit*
expressible. Scaling by ``remaining / current`` can shrink a pot but can never
inject into one worth nothing, so a plan with no starting capital used to
discard every contribution and project zero (backlog U4-2). Units are bought at
the market level, so an empty plan funds itself, and a schedule of twelve
monthly deposits costs no more than one annual lump (U4-1).

Strategies
----------
fixed_real   : constant inflation-adjusted dollar amount (4%-rule style).
constant_pct : withdraw a fixed % of the *current* portfolio value each year.
guardrails   : **simplified** Guyton-Klinger — start at a base rate, then cut
               spending when the withdrawal rate breaches the upper guardrail
               (portfolio fell) and raise it below the lower guardrail.

               Two of the four GK decision rules run here: capital preservation
               (the cut) and prosperity (the raise). Three do not, and no surface
               may imply otherwise (U1-6, ``data/product_ux.GUARDRAILS_OMISSIONS``):

                 * the **inflation rule** — canonical GK freezes the inflation
                   raise after a year with a negative portfolio return; below,
                   ``spend *= (1 + inflation_rate)`` runs unconditionally;
                 * the **portfolio management rule** — which sleeve funds the
                   withdrawal; ``cash_flow_units`` sells the portfolio pro rata;
                 * the **time bound on the cut** — GK suspends capital
                   preservation in the last 15 years of the plan; here it applies
                   at every horizon year.

               Implementing them is out of scope for U1-6 (``no_hacer``:
               "Reimplementar GK canonico"); the copy says what runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Dict, Optional, Union

import numpy as np

from config import WITHDRAWAL

VALID_KINDS = ("fixed_real", "constant_pct", "guardrails")


# ------------------------------------------------------------------ #
#  Strategy descriptor                                                 #
# ------------------------------------------------------------------ #

@dataclass
class WithdrawalStrategy:
    """A JSON-serializable description of a decumulation strategy.

    ``annual_amount`` is used by ``fixed_real`` (dollars/year, inflation-grown).
    ``pct`` is a fraction (0.04 == 4%) used by ``constant_pct`` (of current
    value) and as the *initial* rate for ``guardrails``. Guardrail bands and
    step sizes default to ``config.WITHDRAWAL``.
    """

    kind: str = "fixed_real"
    annual_amount: float = 0.0          # dollars/year (fixed_real)
    pct: float = 0.0                    # fraction 0–1 (constant_pct / guardrails base rate)
    guardrail_ceiling_band: float = WITHDRAWAL.guardrail_ceiling_band
    guardrail_floor_band: float = WITHDRAWAL.guardrail_floor_band
    guardrail_cut_pct: float = WITHDRAWAL.guardrail_cut_pct
    guardrail_raise_pct: float = WITHDRAWAL.guardrail_raise_pct
    label: str = ""

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(
                f"Unknown withdrawal strategy '{self.kind}'. "
                f"Expected one of {VALID_KINDS}."
            )

    # -- constructors ------------------------------------------------ #

    @classmethod
    def fixed_real(cls, annual_amount: float, label: str = "") -> "WithdrawalStrategy":
        return cls(kind="fixed_real", annual_amount=float(annual_amount),
                   label=label or "Retiro fijo real")

    @classmethod
    def constant_pct(cls, pct: float, label: str = "") -> "WithdrawalStrategy":
        return cls(kind="constant_pct", pct=float(pct),
                   label=label or f"{pct * 100:.1f}% del valor actual")

    @classmethod
    def guardrails(
        cls,
        base_pct: float,
        ceiling_band: Optional[float] = None,
        floor_band: Optional[float] = None,
        cut_pct: Optional[float] = None,
        raise_pct: Optional[float] = None,
        label: str = "",
    ) -> "WithdrawalStrategy":
        return cls(
            kind="guardrails",
            pct=float(base_pct),
            guardrail_ceiling_band=WITHDRAWAL.guardrail_ceiling_band if ceiling_band is None else float(ceiling_band),
            guardrail_floor_band=WITHDRAWAL.guardrail_floor_band if floor_band is None else float(floor_band),
            guardrail_cut_pct=WITHDRAWAL.guardrail_cut_pct if cut_pct is None else float(cut_pct),
            guardrail_raise_pct=WITHDRAWAL.guardrail_raise_pct if raise_pct is None else float(raise_pct),
            label=label or f"Guardrails simplificado {base_pct * 100:.1f}%",
        )

    @classmethod
    def coerce(cls, value: Union["WithdrawalStrategy", dict, None]) -> Optional["WithdrawalStrategy"]:
        """Normalize a strategy passed as a dataclass or a plain dict (or None)."""
        if value is None:
            return None
        if isinstance(value, WithdrawalStrategy):
            return value
        if isinstance(value, dict):
            known = {f for f in cls.__dataclass_fields__}
            return cls(**{k: v for k, v in value.items() if k in known})
        raise TypeError(f"Cannot coerce {type(value)!r} into a WithdrawalStrategy")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "annual_amount": round(float(self.annual_amount), 2),
            "pct": round(float(self.pct), 6),
            "guardrail_ceiling_band": self.guardrail_ceiling_band,
            "guardrail_floor_band": self.guardrail_floor_band,
            "guardrail_cut_pct": self.guardrail_cut_pct,
            "guardrail_raise_pct": self.guardrail_raise_pct,
            "label": self.label,
        }


# ------------------------------------------------------------------ #
#  Cash-flow kernel — the single source of cash-flow maths             #
# ------------------------------------------------------------------ #

def wealth_basis(initial_value: float, *flows: float) -> float:
    """The positive USD scale the relative pot is expressed in.

    Equals ``initial_value`` whenever the plan has capital, so every existing
    caller keeps its exact contract. When the plan starts empty it falls back to
    the size of a cash flow, because a savings-only plan still needs a unit to
    be expressed in — and expressing it in "multiples of zero" is what made the
    engine answer 0 % to "¿llego si ahorro X por mes?" (backlog U4-2).

    Never returns 0. That is the whole point.
    """
    if initial_value > 0:
        return float(initial_value)
    for flow in flows:
        if flow:
            return float(abs(flow))
    return 1.0


def cash_flow_units(units: np.ndarray, market_at_week: np.ndarray, amount) -> np.ndarray:
    """THE cash-flow primitive: buy or sell units at the current market level.

    Parameters
    ----------
    units : (n_sims,) holdings before the flow. Wealth is ``units × market``.
    market_at_week : (n_sims,) the market index at the week the flow happens.
    amount : scalar or ``(n_sims,)``, in the same units as wealth. **Positive
            removes capital, negative adds it.**

    Holding units instead of a rescaled wealth path is what lets both defects be
    fixed at once. Selling units is still what a withdrawal does — the cash
    leaves and only the remaining capital compounds (audit D1) — but a *deposit*
    into a pot worth nothing is now expressible, because units are bought at the
    market level rather than as a fraction of a balance that does not exist.

    Units are floored at 0, so a pot emptied by spending stays empty however the
    market moves afterwards (audit D2). Absorption is now a property of the
    algebra rather than of a defensive branch. A later *contribution* does
    revive such a path, which is arithmetic: depositing money into an empty
    account leaves you with the money you deposited.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        delta = np.where(market_at_week > 0, amount / market_at_week, 0.0)
    delta = np.nan_to_num(delta, nan=0.0, posinf=0.0, neginf=0.0)
    return np.maximum(units - delta, 0.0)


def apply_cash_flow_schedule(market: np.ndarray, units0, events) -> np.ndarray:
    """Materialise a wealth path from an untouched market index and a schedule.

    Parameters
    ----------
    market : (n_sims, n_weeks+1) relative market curve, starting at 1.0. **Never
            modified** — that is what makes the U2-2 guarantee structural rather
            than a consequence of the order in which ``run`` calls things.
    units0 : scalar or ``(n_sims,)`` holdings at week 0.
    events : iterable of ``(week_idx, amount_fn)`` in non-decreasing week order.
            ``amount_fn`` receives the pre-flow wealth at that week, so
            value-dependent strategies (constant_pct, guardrails) keep working.

    Each week is written exactly once, so a schedule of 360 monthly flows costs
    the same as one of 30 annual flows. That is what makes the monthly cadence
    of U4-1 affordable: the previous kernel rescaled the whole remaining path on
    every event, which at twelve events a year would have been a 12× slowdown of
    an engine that promises to answer in under two seconds.
    """
    n_sims = market.shape[0]
    units = np.broadcast_to(np.asarray(units0, dtype=float), (n_sims,)).astype(float).copy()
    out = np.empty_like(market)

    previous = 0
    for week_idx, amount_fn in events:
        out[:, previous:week_idx] = units[:, np.newaxis] * market[:, previous:week_idx]
        pre_flow_wealth = units * market[:, week_idx]
        units = cash_flow_units(units, market[:, week_idx], amount_fn(pre_flow_wealth))
        previous = week_idx

    out[:, previous:] = units[:, np.newaxis] * market[:, previous:]
    return out


def cash_flow_weeks(periods_per_year: int, horizon_years: int, n_cols: int) -> list[int]:
    """The week each cash flow of a plan lands on, clipped to the horizon.

    With weekly bars a month is 52/12 ≈ 4.33 bars, so monthly flows alternate
    between 4- and 5-week gaps and period 12 lands exactly on week 52. Year
    boundaries therefore still coincide with the fan-chart year marks and with
    the annual withdrawal schedule.
    """
    periods = max(1, int(periods_per_year))
    weeks = []
    for year in range(1, horizon_years + 1):
        for period in range(1, periods + 1):
            week = (year - 1) * 52 + round(period * 52 / periods)
            weeks.append(min(week, n_cols - 1))
    return weeks


# ------------------------------------------------------------------ #
#  Path transformation                                                 #
# ------------------------------------------------------------------ #

def apply_withdrawal_strategy(
    paths: np.ndarray,
    initial_value: float,
    strategy: WithdrawalStrategy,
    n_horizon_weeks: int,
    inflation_rate: float = 0.0,
) -> np.ndarray:
    """Apply a withdrawal strategy to relative simulation paths.

    Parameters
    ----------
    paths : (n_sims, n_weeks+1) array of *relative* portfolio values (start=1.0).
    initial_value : starting portfolio value in USD (scales fixed amounts).
    strategy : the chosen :class:`WithdrawalStrategy`.
    n_horizon_weeks : total simulated weeks (``horizon_years * 52``).
    inflation_rate : annual growth applied to spending (e.g. 0.03).

    Returns a NEW array (input is copied). At each 52-week mark the withdrawal
    is taken out of capital via :func:`cash_flow_units`, so the remaining
    balance keeps tracking the market and depletion is permanent.

    Decumulation stays **annual** on purpose. The guardrails strategy *is* an
    annual review, so paying monthly while deciding annually is a separate
    design question (backlog U4-1c), not a side effect of the contribution
    cadence fix.
    """
    horizon_years = n_horizon_weeks // 52
    n_cols = paths.shape[1]
    n_sims = paths.shape[0]
    weeks = [min(yr * 52, n_cols - 1) for yr in range(1, horizon_years + 1)]

    if initial_value <= 0:
        # Decumulating nothing is degenerate: there is no capital to convert a
        # dollar amount or a percentage into. Returning zeros states that, where
        # silently withdrawing nothing would present an empty plan as a solvent
        # one. ``MonteCarloSimulator.run`` warns when it hits this.
        return np.zeros_like(paths)

    if strategy.kind == "fixed_real":
        withdrawal_fraction = strategy.annual_amount / initial_value
        events = [
            (week, _fixed_amount(withdrawal_fraction * ((1 + inflation_rate) ** (yr - 1))))
            for yr, week in enumerate(weeks, start=1)
        ]
        return apply_cash_flow_schedule(paths, 1.0, events)

    if strategy.kind == "constant_pct":
        pct = strategy.pct
        events = [(week, lambda wealth: pct * wealth) for week in weeks]
        return apply_cash_flow_schedule(paths, 1.0, events)

    if strategy.kind == "guardrails":
        wr0 = strategy.pct                           # initial withdrawal rate (fraction of initial value)
        ceiling_rate = wr0 * (1.0 + strategy.guardrail_ceiling_band)
        floor_rate = wr0 * (1.0 - strategy.guardrail_floor_band)
        # Spending in relative units (start = wr0, since paths start at 1.0 == initial_value).
        state = {"spend": np.full(n_sims, wr0, dtype=float)}

        def _guardrail_amount(current: np.ndarray, *, year: int) -> np.ndarray:
            spend = state["spend"]
            if year > 1:
                spend = spend * (1.0 + inflation_rate)
            with np.errstate(divide="ignore", invalid="ignore"):
                rate = np.where(current > 0, spend / current, np.inf)
            # Capital-preservation rule: withdrawal rate too high → cut spending.
            spend = np.where(rate > ceiling_rate, spend * (1.0 - strategy.guardrail_cut_pct), spend)
            # Prosperity rule: withdrawal rate too low → raise spending.
            spend = np.where(rate < floor_rate, spend * (1.0 + strategy.guardrail_raise_pct), spend)
            state["spend"] = spend
            return np.minimum(spend, np.maximum(current, 0.0))   # never withdraw more than available

        events = [
            (week, partial(_guardrail_amount, year=yr))
            for yr, week in enumerate(weeks, start=1)
        ]
        return apply_cash_flow_schedule(paths, 1.0, events)

    raise ValueError(f"Unknown withdrawal strategy '{strategy.kind}'")


def _fixed_amount(amount: float):
    """An ``amount_fn`` that ignores the pot and always takes the same figure."""
    return lambda _wealth: amount


# ------------------------------------------------------------------ #
#  Success metrics                                                     #
# ------------------------------------------------------------------ #

def decumulation_metrics(
    paths_usd: np.ndarray,
    horizon_years: int,
    initial_value: float,
    longevity_years: Optional[int] = None,
) -> Dict[str, float]:
    """Compute retirement-specific success metrics from USD paths.

    Returns a dict with:
      prob_sustain_real_pct  — % of paths that NEVER ran dry over the horizon
                               (income sustained the whole way).
      prob_legacy_pct        — % of paths with a positive terminal value
                               (money left to leave behind). Since the 2026-08
                               fix ruin is absorbing, so "ends positive" and
                               "never ran dry" are the same event and this
                               equals ``prob_sustain_real_pct``. Kept for
                               ``mc_summary`` backward compatibility; the UI
                               shows ``prob_sustain_real_pct`` + ``median_legacy``
                               instead of two identical percentages.
      median_legacy          — median terminal value (USD).
      expected_depletion_year — among paths that DID run dry, the median year
                               in which depletion first occurred (0 if none).
      longevity_years        — the horizon the sustain metric refers to.
    """
    if paths_usd.size == 0:
        return {
            "prob_sustain_real_pct": 0.0,
            "prob_legacy_pct": 0.0,
            "median_legacy": 0.0,
            "expected_depletion_year": 0.0,
            "longevity_years": float(longevity_years or horizon_years),
        }

    longevity = int(longevity_years) if longevity_years else horizon_years
    n_cols = paths_usd.shape[1]
    cap_week = min(longevity * 52, n_cols - 1)
    window = paths_usd[:, : cap_week + 1]

    eps = max(initial_value, 1.0) * 1e-9
    min_vals = window.min(axis=1)
    depleted = min_vals <= eps

    terminal = window[:, -1]
    prob_sustain = float((~depleted).mean() * 100)
    prob_legacy = float((terminal > eps).mean() * 100)
    median_legacy = float(np.median(terminal))

    if depleted.any():
        zero_hit = window <= eps
        first_zero_week = np.argmax(zero_hit, axis=1)      # first depleted week per path
        dep_weeks = first_zero_week[depleted]
        expected_depletion_year = float(np.median(dep_weeks) / 52)
    else:
        expected_depletion_year = 0.0

    return {
        "prob_sustain_real_pct": round(prob_sustain, 2),
        "prob_legacy_pct": round(prob_legacy, 2),
        "median_legacy": round(median_legacy, 0),
        "expected_depletion_year": round(expected_depletion_year, 2),
        "longevity_years": float(longevity),
    }
