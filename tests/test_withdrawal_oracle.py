"""Oracle tests for the withdrawal / decumulation kernel.

Why this file exists
--------------------
The rest of the suite verifies that the withdrawal engine is *consistent with
itself* ("byte-identical to the legacy engine"). That is a regression guard, not
a validation: the 2026-08 audit found a +60% error in terminal wealth that every
existing test happily accepted, because the reference it compared against was
the same buggy code.

These tests compare the vectorised engine against an **independently written,
deliberately slow, sequential capital-accounting oracle**. The oracle models what
a withdrawal actually is: you sell assets, the money leaves the portfolio, and
only the *remaining* capital keeps tracking the market. If the two disagree, the
engine is wrong — not the oracle.

Covered
-------
  * D1 — withdrawal removes capital (not a constant nominal level).
  * D2 — ruin is absorbing: once a path hits zero it stays at zero.
  * All three strategies (fixed_real / constant_pct / guardrails) across bull,
    flat, bear and crash-then-recover regimes, several horizons and inflation
    rates.
  * The legacy ``MonteCarloSimulator._apply_withdrawals`` entry point, which must
    agree with the strategy engine (they share one kernel).

Pure NumPy — no network, no Streamlit.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio.decumulation import (
    WithdrawalStrategy,
    apply_withdrawal_strategy,
)
from portfolio.monte_carlo import MonteCarloSimulator

INIT = 100_000.0
EPS = 1e-6


# ------------------------------------------------------------------ #
#  Path builders (deterministic regimes)                              #
# ------------------------------------------------------------------ #

def _constant_growth_path(years: int, annual_return: float) -> np.ndarray:
    """Relative path (start=1.0) compounding at a fixed annual rate."""
    wk = (1.0 + annual_return) ** (1.0 / 52) - 1.0
    return np.concatenate([[1.0], np.cumprod(np.full(years * 52, 1.0 + wk))])


def _crash_then_recover(years: int, crash_years: int = 4,
                        crash_ann: float = -0.25,
                        recover_ann: float = 0.12) -> np.ndarray:
    """Sharp multi-year decline followed by a strong recovery."""
    rets = np.empty(years * 52)
    for w in range(years * 52):
        ann = crash_ann if (w // 52) < crash_years else recover_ann
        rets[w] = (1.0 + ann) ** (1.0 / 52) - 1.0
    return np.concatenate([[1.0], np.cumprod(1.0 + rets)])


REGIMES = {
    "bull_8pct": lambda y: _constant_growth_path(y, 0.08),
    "flat": lambda y: _constant_growth_path(y, 0.0),
    "bear_4pct": lambda y: _constant_growth_path(y, -0.04),
    "crash_recover": lambda y: _crash_then_recover(y),
}


# ------------------------------------------------------------------ #
#  The oracle — sequential capital accounting, one path at a time     #
# ------------------------------------------------------------------ #

def _oracle_path(
    path_rel: np.ndarray,
    initial: float,
    strategy: WithdrawalStrategy,
    years: int,
    inflation: float = 0.0,
) -> np.ndarray:
    """Return the full USD value series at each yearly mark, [year0 .. yearN].

    Deliberately a plain Python loop. A withdrawal removes capital; whatever is
    left compounds with the market. Once the capital reaches zero it can never
    recover — there is nothing left to compound.
    """
    values = [float(initial)]
    val = float(initial)

    # guardrails bookkeeping (spend tracked in USD)
    spend = float(strategy.pct) * float(initial)
    ceiling_rate = float(strategy.pct) * (1.0 + strategy.guardrail_ceiling_band)
    floor_rate = float(strategy.pct) * (1.0 - strategy.guardrail_floor_band)

    for yr in range(1, years + 1):
        growth = float(path_rel[yr * 52] / path_rel[(yr - 1) * 52])
        val *= growth  # only surviving capital participates

        if strategy.kind == "fixed_real":
            w = strategy.annual_amount * ((1.0 + inflation) ** (yr - 1))
        elif strategy.kind == "constant_pct":
            w = strategy.pct * val
        elif strategy.kind == "guardrails":
            if yr > 1:
                spend *= (1.0 + inflation)
            rate = (spend / val) if val > 0 else float("inf")
            if rate > ceiling_rate:
                spend *= (1.0 - strategy.guardrail_cut_pct)
            if rate < floor_rate:
                spend *= (1.0 + strategy.guardrail_raise_pct)
            w = min(spend, max(val, 0.0))
        else:  # pragma: no cover - guarded by WithdrawalStrategy
            raise AssertionError(strategy.kind)

        val = max(0.0, val - w)
        values.append(val)

    return np.array(values)


def _engine_yearly(
    path_rel: np.ndarray,
    initial: float,
    strategy: WithdrawalStrategy,
    years: int,
    inflation: float = 0.0,
) -> np.ndarray:
    """Run the real engine on one path and sample it at the yearly marks."""
    out = apply_withdrawal_strategy(
        np.array([path_rel], dtype=float),
        initial,
        strategy,
        years * 52,
        inflation_rate=inflation,
    )
    usd = out[0] * initial
    return np.array([usd[min(yr * 52, len(usd) - 1)] for yr in range(years + 1)])


def _assert_close(engine: np.ndarray, oracle: np.ndarray, label: str) -> None:
    assert engine.shape == oracle.shape, label
    for yr, (e, o) in enumerate(zip(engine, oracle)):
        if abs(o) < EPS:
            assert abs(e) < max(EPS, abs(o) + EPS), f"{label} @año {yr}: motor={e} oráculo={o}"
        else:
            assert e == pytest.approx(o, rel=1e-9, abs=1e-6), (
                f"{label} @año {yr}: motor={e:,.2f} oráculo={o:,.2f} "
                f"(error {100 * (e - o) / o:+.2f}%)"
            )


# ------------------------------------------------------------------ #
#  D1 — the engine must equal the oracle across the whole grid        #
# ------------------------------------------------------------------ #

STRATEGIES = {
    "fixed_real_4k": lambda: WithdrawalStrategy.fixed_real(4_000.0),
    "constant_pct_4": lambda: WithdrawalStrategy.constant_pct(0.04),
    "guardrails_4": lambda: WithdrawalStrategy.guardrails(0.04),
}


@pytest.mark.parametrize("regime", sorted(REGIMES))
@pytest.mark.parametrize("strategy_key", sorted(STRATEGIES))
@pytest.mark.parametrize("years", [5, 20, 30])
@pytest.mark.parametrize("inflation", [0.0, 0.03])
class TestEngineMatchesOracle:
    def test_yearly_values_match(self, regime, strategy_key, years, inflation):
        path = REGIMES[regime](years)
        strategy = STRATEGIES[strategy_key]()
        engine = _engine_yearly(path, INIT, strategy, years, inflation)
        oracle = _oracle_path(path, INIT, strategy, years, inflation)
        _assert_close(
            engine, oracle,
            f"{regime}/{strategy_key}/{years}y/infl={inflation}",
        )


class TestD1KnownRegression:
    """The exact case from docs/AUDITORIA_2026-08.md — must now be correct."""

    def test_bull_30y_4pct_matches_oracle(self):
        years = 30
        path = _constant_growth_path(years, 0.08)
        strategy = WithdrawalStrategy.fixed_real(4_000.0)

        engine = _engine_yearly(path, INIT, strategy, years)[-1]
        oracle = _oracle_path(path, INIT, strategy, years)[-1]

        assert oracle == pytest.approx(553_133, abs=5)
        assert engine == pytest.approx(oracle, rel=1e-9)
        # The pre-fix engine returned 886_266 here (+60.2%).
        assert engine < 600_000


# ------------------------------------------------------------------ #
#  D2 — ruin must be absorbing                                        #
# ------------------------------------------------------------------ #

class TestRuinIsAbsorbing:
    def test_zero_is_permanent_in_crash_recover(self):
        """A path wiped out early must not recover when the market does."""
        years = 30
        path = _crash_then_recover(years)
        strategy = WithdrawalStrategy.fixed_real(12_000.0)

        usd = apply_withdrawal_strategy(
            np.array([path], dtype=float), INIT, strategy, years * 52,
        )[0] * INIT

        assert float(usd.min()) == pytest.approx(0.0, abs=EPS)
        assert float(usd[-1]) == pytest.approx(0.0, abs=EPS), (
            "path resucitó tras tocar 0"
        )

    @pytest.mark.parametrize("regime", sorted(REGIMES))
    def test_dead_paths_never_revive(self, regime):
        """Across every regime: once at zero, always at zero."""
        years = 30
        path = REGIMES[regime](years)
        # Withdrawal large enough to bankrupt most regimes.
        strategy = WithdrawalStrategy.fixed_real(9_000.0)
        usd = apply_withdrawal_strategy(
            np.array([path], dtype=float), INIT, strategy, years * 52,
        )[0] * INIT

        dead = usd <= EPS
        if dead.any():
            first_dead = int(np.argmax(dead))
            assert dead[first_dead:].all(), (
                f"{regime}: el path volvió a ser positivo tras morir en la semana {first_dead}"
            )

    def test_multi_path_absorbing(self):
        """Vectorised case: mixed survivors and casualties in one array."""
        years = 30
        paths = np.array([
            _constant_growth_path(years, 0.10),   # survives
            _crash_then_recover(years),           # dies then market recovers
            _constant_growth_path(years, -0.06),  # dies
        ])
        out = apply_withdrawal_strategy(
            paths, INIT, WithdrawalStrategy.fixed_real(8_000.0), years * 52,
        ) * INIT

        for i in range(out.shape[0]):
            dead = out[i] <= EPS
            if dead.any():
                first = int(np.argmax(dead))
                assert dead[first:].all(), f"path {i} resucitó"


# ------------------------------------------------------------------ #
#  Structural properties                                              #
# ------------------------------------------------------------------ #

class TestWithdrawalProperties:
    @pytest.mark.parametrize("regime", sorted(REGIMES))
    def test_more_withdrawal_never_leaves_more(self, regime):
        years = 20
        path = REGIMES[regime](years)
        terminals = [
            _engine_yearly(path, INIT, WithdrawalStrategy.fixed_real(amt), years)[-1]
            for amt in (0.0, 2_000.0, 5_000.0, 10_000.0)
        ]
        for lower, higher in zip(terminals, terminals[1:]):
            assert higher <= lower + EPS, f"{regime}: retirar más dejó más capital"

    @pytest.mark.parametrize("regime", sorted(REGIMES))
    def test_zero_withdrawal_leaves_paths_untouched(self, regime):
        """No withdrawal → the accumulation path must be bit-for-bit unchanged."""
        years = 20
        path = REGIMES[regime](years)
        original = np.array([path], dtype=float)
        out = apply_withdrawal_strategy(
            original, INIT, WithdrawalStrategy.fixed_real(0.0), years * 52,
        )
        np.testing.assert_allclose(out, original, rtol=0, atol=0)

    def test_does_not_mutate_input(self):
        years = 10
        path = _constant_growth_path(years, 0.06)
        paths = np.array([path], dtype=float)
        before = paths.copy()
        apply_withdrawal_strategy(
            paths, INIT, WithdrawalStrategy.fixed_real(5_000.0), years * 52,
        )
        np.testing.assert_array_equal(paths, before)

    def test_constant_pct_is_exact_geometric_decay_in_flat_market(self):
        """Flat market, 10%/yr of current value → exactly 0.9**years."""
        years = 5
        path = _constant_growth_path(years, 0.0)
        out = _engine_yearly(
            path, INIT, WithdrawalStrategy.constant_pct(0.10), years,
        )
        assert out[-1] == pytest.approx(INIT * 0.9 ** years, rel=1e-12)


# ------------------------------------------------------------------ #
#  The legacy MC entry point shares the same kernel                   #
# ------------------------------------------------------------------ #

class TestMonteCarloEntryPoint:
    @pytest.mark.parametrize("regime", sorted(REGIMES))
    @pytest.mark.parametrize("inflation", [0.0, 0.03])
    def test_apply_withdrawals_matches_oracle(self, regime, inflation):
        years = 30
        path = REGIMES[regime](years)
        amount = 4_000.0

        usd = MonteCarloSimulator._apply_withdrawals(
            np.array([path], dtype=float), INIT, amount, years * 52,
            withdrawal_growth_rate=inflation,
        )[0] * INIT
        engine = np.array([usd[min(yr * 52, len(usd) - 1)] for yr in range(years + 1)])

        oracle = _oracle_path(
            path, INIT, WithdrawalStrategy.fixed_real(amount), years, inflation,
        )
        _assert_close(engine, oracle, f"MC/{regime}/infl={inflation}")

    def test_agrees_with_strategy_engine(self):
        """Both entry points must produce identical arrays (one shared kernel)."""
        years, amount, infl = 25, 4_000.0, 0.03
        path = _crash_then_recover(years)

        legacy = MonteCarloSimulator._apply_withdrawals(
            np.array([path], dtype=float), INIT, amount, years * 52,
            withdrawal_growth_rate=infl,
        )
        strategy = apply_withdrawal_strategy(
            np.array([path], dtype=float), INIT,
            WithdrawalStrategy.fixed_real(amount), years * 52, inflation_rate=infl,
        )
        np.testing.assert_allclose(legacy, strategy, rtol=0, atol=0)
