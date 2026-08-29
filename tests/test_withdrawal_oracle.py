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

from config import MONTE_CARLO
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

def _payment_schedule(years: int, periods: int) -> dict[int, tuple[int, bool]]:
    """``{semana: (año, es_revisión)}``. Derivado de la definición: ``periods``
    cuotas por año, la primera de cada año es la que decide el presupuesto."""
    out: dict[int, tuple[int, bool]] = {}
    for yr in range(1, years + 1):
        for p in range(1, periods + 1):
            out[(yr - 1) * 52 + round(p * 52 / periods)] = (yr, p == 1)
    return out


def _oracle_path(
    path_rel: np.ndarray,
    initial: float,
    strategy: WithdrawalStrategy,
    years: int,
    inflation: float = 0.0,
    periods: int | None = None,
) -> np.ndarray:
    """Return the full USD value series at each yearly mark, [year0 .. yearN].

    Deliberately a plain Python loop, **week by week** rather than year by year
    (U4-1c): el gasto ya no sale una vez al año, así que una referencia que
    avanzara de a un año no podría expresar la cadencia que tiene que validar.

    Modela lo que un retiro es: se venden activos, la plata se va, y sólo el
    capital *restante* sigue al mercado. Una vez en cero no se recupera, porque
    no queda nada que componga.

    **Se decide una vez al año y se paga en cuotas.** El presupuesto se fija en
    la primera cuota del año y las demás lo repiten — los guardrails son una
    revisión anual, no una mensual.
    """
    if periods is None:
        periods = MONTE_CARLO.withdrawal_periods_per_year
    periods = max(1, int(periods))
    agenda = _payment_schedule(years, periods)

    values = [float(initial)]
    val = float(initial)
    cuota = 0.0

    # guardrails bookkeeping (spend tracked in USD)
    spend = float(strategy.pct) * float(initial)
    ceiling_rate = float(strategy.pct) * (1.0 + strategy.guardrail_ceiling_band)
    floor_rate = float(strategy.pct) * (1.0 - strategy.guardrail_floor_band)

    for week in range(1, years * 52 + 1):
        val *= float(path_rel[week] / path_rel[week - 1])   # sólo el capital vivo crece

        if week in agenda:
            yr, es_revision = agenda[week]
            if es_revision:
                if strategy.kind == "fixed_real":
                    anual = strategy.annual_amount * ((1.0 + inflation) ** (yr - 1))
                elif strategy.kind == "constant_pct":
                    anual = strategy.pct * val
                elif strategy.kind == "guardrails":
                    if yr > 1:
                        spend *= (1.0 + inflation)
                    rate = (spend / val) if val > 0 else float("inf")
                    if rate > ceiling_rate:
                        spend *= (1.0 - strategy.guardrail_cut_pct)
                    if rate < floor_rate:
                        spend *= (1.0 + strategy.guardrail_raise_pct)
                    anual = spend
                else:  # pragma: no cover - guarded by WithdrawalStrategy
                    raise AssertionError(strategy.kind)
                cuota = anual / periods

            w = min(cuota, max(val, 0.0))
            val = max(0.0, val - w)

        if week % 52 == 0:
            values.append(val)

    return np.array(values)


def _engine_yearly(
    path_rel: np.ndarray,
    initial: float,
    strategy: WithdrawalStrategy,
    years: int,
    inflation: float = 0.0,
    periods: int | None = None,
) -> np.ndarray:
    """Run the real engine on one path and sample it at the yearly marks."""
    out = apply_withdrawal_strategy(
        np.array([path_rel], dtype=float),
        initial,
        strategy,
        years * 52,
        inflation_rate=inflation,
        periods_per_year=periods,
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
@pytest.mark.parametrize("periods", [1, 12])   # U4-1c: las dos cadencias validan
class TestEngineMatchesOracle:
    def test_yearly_values_match(self, regime, strategy_key, years, inflation, periods):
        path = REGIMES[regime](years)
        strategy = STRATEGIES[strategy_key]()
        engine = _engine_yearly(path, INIT, strategy, years, inflation, periods=periods)
        oracle = _oracle_path(path, INIT, strategy, years, inflation, periods=periods)
        _assert_close(
            engine, oracle,
            f"{regime}/{strategy_key}/{years}y/infl={inflation}/{periods}cuotas",
        )


class TestD1KnownRegression:
    """The exact case from docs/AUDITORIA_2026-08.md — must now be correct."""

    def test_bull_30y_4pct_matches_oracle(self):
        """El caso D1, fijado bajo LAS DOS cadencias.

        El 553.133 es el número con el que se documentó la auditoría, y se
        calculó cuando los retiros eran anuales. U4-1c no lo invalida: lo deja
        como el resultado de esa cadencia, que sigue siendo reproducible. Lo que
        agrega es cuánto cuesta que el jubilado gaste todos los meses.
        """
        years = 30
        path = _constant_growth_path(years, 0.08)
        strategy = WithdrawalStrategy.fixed_real(4_000.0)

        # --- la cadencia con la que se documentó D1 ------------------------ #
        anual = _engine_yearly(path, INIT, strategy, years, periods=1)[-1]
        oraculo_anual = _oracle_path(path, INIT, strategy, years, periods=1)[-1]
        assert oraculo_anual == pytest.approx(553_133, abs=5)
        assert anual == pytest.approx(oraculo_anual, rel=1e-9)
        # The pre-fix engine returned 886_266 here (+60.2%).
        assert anual < 600_000

        # --- U4-1c: el jubilado gasta todos los meses ---------------------- #
        mensual = _engine_yearly(path, INIT, strategy, years, periods=12)[-1]
        oraculo_mensual = _oracle_path(path, INIT, strategy, years, periods=12)[-1]
        assert mensual == pytest.approx(oraculo_mensual, rel=1e-9)
        assert mensual == pytest.approx(536_748, abs=5)
        assert mensual < anual, (
            "repartir un gasto anual fijo no puede dejar más capital"
        )


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
        # Tolerancia en vez de identidad de bits: los dos caminos hacen la misma
        # aritmética en distinto orden —el legacy divide por las cuotas antes de
        # aplicar la inflación y el de estrategia después— y desde U4-1c eso deja
        # una diferencia de punto flotante de 7,8e-18. La afirmación que importa
        # es que no puedan divergir, no que redondeen igual.
        np.testing.assert_allclose(legacy, strategy, rtol=1e-12, atol=1e-15)
