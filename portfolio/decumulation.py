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
  - "fixed_real" replicates the legacy ``_apply_withdrawals`` math exactly, so
    a strategy run with the same amount + inflation is byte-identical to the
    pre-feature engine (guaranteed by tests).

Strategies
----------
fixed_real   : constant inflation-adjusted dollar amount (4%-rule style).
constant_pct : withdraw a fixed % of the *current* portfolio value each year.
guardrails   : modified Guyton-Klinger — start at a base rate, then cut
               spending when the withdrawal rate breaches the upper guardrail
               (portfolio fell) and raise it below the lower guardrail.
"""

from __future__ import annotations

from dataclasses import dataclass
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
            label=label or f"Guardrails {base_pct * 100:.1f}%",
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

    Returns a NEW array (input is copied) with withdrawals subtracted at each
    52-week mark, floored at 0. Mirrors the legacy convention of decrementing
    every week from the withdrawal point onward.
    """
    p = paths.copy()
    horizon_years = n_horizon_weeks // 52
    n_cols = p.shape[1]
    n_sims = p.shape[0]

    if strategy.kind == "fixed_real":
        # Byte-identical to MonteCarloSimulator._apply_withdrawals.
        withdrawal_fraction = (strategy.annual_amount / initial_value) if initial_value > 0 else 0.0
        for yr in range(1, horizon_years + 1):
            week_idx = min(yr * 52, n_cols - 1)
            grown = withdrawal_fraction * ((1 + inflation_rate) ** (yr - 1))
            p[:, week_idx:] -= grown
            p = np.maximum(p, 0)
        return p

    if strategy.kind == "constant_pct":
        pct = strategy.pct
        for yr in range(1, horizon_years + 1):
            week_idx = min(yr * 52, n_cols - 1)
            current = p[:, week_idx]                 # per-path relative value
            w = pct * current
            p[:, week_idx:] -= w[:, np.newaxis]
            p = np.maximum(p, 0)
        return p

    if strategy.kind == "guardrails":
        wr0 = strategy.pct                           # initial withdrawal rate (fraction of initial value)
        ceiling_rate = wr0 * (1.0 + strategy.guardrail_ceiling_band)
        floor_rate = wr0 * (1.0 - strategy.guardrail_floor_band)
        # Spending in relative units (start = wr0, since paths start at 1.0 == initial_value).
        spend = np.full(n_sims, wr0, dtype=float)
        for yr in range(1, horizon_years + 1):
            week_idx = min(yr * 52, n_cols - 1)
            if yr > 1:
                spend = spend * (1.0 + inflation_rate)
            current = p[:, week_idx]
            with np.errstate(divide="ignore", invalid="ignore"):
                rate = np.where(current > 0, spend / current, np.inf)
            # Capital-preservation rule: withdrawal rate too high → cut spending.
            spend = np.where(rate > ceiling_rate, spend * (1.0 - strategy.guardrail_cut_pct), spend)
            # Prosperity rule: withdrawal rate too low → raise spending.
            spend = np.where(rate < floor_rate, spend * (1.0 + strategy.guardrail_raise_pct), spend)
            w = np.minimum(spend, np.maximum(current, 0.0))   # never withdraw more than available
            p[:, week_idx:] -= w[:, np.newaxis]
            p = np.maximum(p, 0)
        return p

    raise ValueError(f"Unknown withdrawal strategy '{strategy.kind}'")


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
                               (money left to leave behind).
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
