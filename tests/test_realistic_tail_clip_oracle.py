"""Oracle for REALISTIC-TAIL-CLIP — la referencia realista no cobra lo que no simula.

``run(include_realistic_reference=True)`` corre una segunda pasada sobre los
retornos crudos para mostrar la mediana «realista» al lado de la conservadora.
Esa pasada sortea sólo el horizonte de proyección, pero hasta este cambio le
aplicaba el retiro de toda la longevidad: con una estrategia (o un retiro fijo)
y una longevidad mayor que el horizonte —los defaults son 20 y 30— los retiros
de los años que ese mercado no tiene caían todos en su última semana, que es la
del terminal. Medido en ``c639da5`` con ``_run(_noisy_history(), n_sims=2000,
withdrawal_strategy=FIXED_REAL, include_realistic_reference=True)`` (``fixed_real``
40 000 sobre 1 000 000, horizonte 20, inflación 3 %): conservadora 601 012 con
cualquier longevidad; realista 1 154 422 con 20, 326 220 con 30 y **0** con 45.
Después del arreglo, 1 154 422 en las tres.

## La referencia

``oracle_terminal`` camina la **riqueza** semana a semana desde la definición:
crece con el mercado y en cada semana de pago resta la cuota, con piso en cero.
No usa unidades, ``apply_cash_flow_schedule`` ni nada del motor. El mercado es
una curva de retorno constante, así que el bootstrap es determinista y todos los
caminos son el mismo. La realista lo camina sin el ajuste conservador; la
conservadora, con ``mean_haircut``.

Lo que pide la referencia es lo que el usuario lee: la riqueza **al final del
horizonte** depende de los retiros hasta ahí, no de cuántos años más se le pida
durar. Con una historia con ruido no hay referencia cerrada, así que ahí la
propiedad se prueba como invariancia: cada campo ``realistic_*`` con longevidad
mayor que el horizonte es, bit a bit, el de longevidad igual al horizonte.

Sin red, sin Streamlit.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from config import MONTE_CARLO
from portfolio.monte_carlo import MonteCarloSimulator

PAYMENTS = int(MONTE_CARLO.withdrawal_periods_per_year)
HORIZON = 20
CAPITAL = 1_000_000.0
AMOUNT = 40_000.0
INFLATION = 0.03
RATE = 0.07
LONGEVITIES = (HORIZON, 15, 25, 30, 45)


def _weekly_rate(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 52.0) - 1.0


def _flat_history(annual_rate: float, n_bars: int = 520) -> pd.DataFrame:
    prices = 100.0 * np.cumprod(np.full(n_bars, 1.0 + _weekly_rate(annual_rate)))
    return pd.DataFrame(
        {"close": prices}, index=pd.date_range("2016-01-03", periods=n_bars, freq="W")
    )


def _noisy_history(annual_rate: float = RATE, vol: float = 0.16, n_bars: int = 520) -> pd.DataFrame:
    """Ruido centrado: la media semanal es exactamente la de ``annual_rate``, así
    que la proyección no depende de la suerte de una semilla."""
    noise = np.random.default_rng(7).normal(0.0, vol / np.sqrt(52), n_bars)
    weekly = noise - noise.mean() + _weekly_rate(annual_rate)
    prices = 100.0 * np.cumprod(1.0 + weekly)
    return pd.DataFrame(
        {"close": prices}, index=pd.date_range("2016-01-03", periods=n_bars, freq="W")
    )


def oracle_terminal(
    weekly_return: float, *, years: int, capital: float, annual_amount: float,
    inflation: float, payments: int = PAYMENTS,
) -> float:
    """Riqueza al final de ``years`` años de un retiro fijo real, desde la definición.

    Cada año sale ``annual_amount`` en ``payments`` cuotas iguales, indexadas por
    ``inflation`` una vez por año; la cuota ``k`` del año ``y`` cae en la semana
    ``(y-1)·52 + round(k·52/payments)``. La riqueza crece con el mercado cada
    semana y la cuota se resta con piso en cero.
    """
    pay_weeks = {}
    for year in range(1, years + 1):
        for k in range(1, payments + 1):
            week = (year - 1) * 52 + round(k * 52 / payments)
            pay_weeks[week] = annual_amount / payments * (1 + inflation) ** (year - 1)
    wealth = capital
    for week in range(1, years * 52 + 1):
        wealth *= 1.0 + weekly_return
        if week in pay_weeks:
            wealth = max(wealth - pay_weeks[week], 0.0)
    return wealth


def _run(history: pd.DataFrame, *, longevity: int, n_sims: int = 50, **kw):
    sim = MonteCarloSimulator(["AAPL"], seed=11)
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda *a, **k: history):
        return sim.run(
            horizon_years=HORIZON, n_sims=n_sims, initial_value=CAPITAL,
            withdrawal_growth_rate=INFLATION, longevity_years=longevity, **kw,
        )


FIXED_REAL = {"kind": "fixed_real", "annual_amount": AMOUNT}
REALISTIC_FIELDS = (
    "realistic_median_terminal",
    "realistic_p10_terminal",
    "realistic_p90_terminal",
    "realistic_prob_achieve_target_pct",
)


class TestAgainstTheDefinition:
    """Mercado constante: la realista es la riqueza del oráculo a 20 años."""

    @pytest.mark.parametrize("longevity", LONGEVITIES)
    def test_realistic_terminal_is_the_horizon_wealth(self, longevity):
        mc = _run(
            _flat_history(RATE), longevity=longevity, withdrawal_strategy=FIXED_REAL,
            include_realistic_reference=True,
        )
        expected = oracle_terminal(
            _weekly_rate(RATE), years=HORIZON, capital=CAPITAL,
            annual_amount=AMOUNT, inflation=INFLATION,
        )
        assert expected > CAPITAL / 2  # el caso no se agota: 0 no es una respuesta trivial
        assert mc.realistic_median_terminal == pytest.approx(expected, rel=1e-9)
        assert mc.realistic_p10_terminal == pytest.approx(expected, rel=1e-9)
        assert mc.realistic_p90_terminal == pytest.approx(expected, rel=1e-9)

    @pytest.mark.parametrize("longevity", LONGEVITIES)
    def test_conservative_terminal_was_already_right(self, longevity):
        """La pasada conservadora simula toda la longevidad, así que nunca tuvo el
        defecto: lo pinea para que el arreglo no la mueva."""
        mc = _run(
            _flat_history(RATE), longevity=longevity, withdrawal_strategy=FIXED_REAL,
            include_realistic_reference=True,
        )
        expected = oracle_terminal(
            _weekly_rate(RATE) * MONTE_CARLO.mean_haircut, years=HORIZON,
            capital=CAPITAL, annual_amount=AMOUNT, inflation=INFLATION,
        )
        assert mc.median_terminal == pytest.approx(expected, rel=1e-9)

    def test_realistic_never_reads_below_conservative_on_the_same_market(self):
        """El síntoma que veía el usuario: «Dos escenarios» con la realista debajo
        de la conservadora, rotulada «~-46 % más baja… a propósito»."""
        for longevity in LONGEVITIES:
            mc = _run(
                _flat_history(RATE), longevity=longevity, withdrawal_strategy=FIXED_REAL,
                include_realistic_reference=True,
            )
            assert mc.realistic_median_terminal > mc.median_terminal, longevity


PLANS = {
    "fixed_real": {"withdrawal_strategy": FIXED_REAL},
    "constant_pct": {"withdrawal_strategy": {"kind": "constant_pct", "pct": 0.04}},
    "guardrails": {"withdrawal_strategy": {"kind": "guardrails", "pct": 0.05}},
    # Sin estrategia la longevidad también alarga la simulación, y el retiro fijo y
    # el ahorro pasan por el mismo recorte.
    "flujos": {"annual_withdrawal": AMOUNT, "annual_contribution": 12_000.0},
}


class TestLongevityDoesNotMoveTheRealisticReference:
    """Historia con ruido: cada campo realista es el de longevidad = horizonte."""

    @pytest.mark.parametrize("drags", [None, {"total_annual_drag_pct": 1.0}], ids=["sin_drags", "drags"])
    @pytest.mark.parametrize("plan", PLANS)
    @pytest.mark.parametrize("longevity", LONGEVITIES[1:])
    def test_bit_for_bit(self, plan, longevity, drags):
        kw = dict(PLANS[plan], target_value=CAPITAL, include_realistic_reference=True, drags=drags)
        base = _run(_noisy_history(), longevity=HORIZON, n_sims=500, **kw)
        longer = _run(_noisy_history(), longevity=longevity, n_sims=500, **kw)
        for name in REALISTIC_FIELDS:
            assert getattr(longer, name) == getattr(base, name), (plan, longevity, name)

    def test_the_phased_branch_was_already_invariant(self):
        """``_apply_phased_plan`` descarta los eventos posteriores a su mercado
        desde WD-PHASED: este caso no cambia con el arreglo."""
        kw = dict(
            withdrawal_strategy=FIXED_REAL, annual_contribution=24_000.0,
            years_to_retirement=10, target_value=CAPITAL, include_realistic_reference=True,
        )
        base = _run(_noisy_history(), longevity=10, n_sims=500, **kw)
        for longevity in (20, 30):
            longer = _run(_noisy_history(), longevity=longevity, n_sims=500, **kw)
            for name in REALISTIC_FIELDS:
                assert getattr(longer, name) == getattr(base, name), (longevity, name)


class TestTheReferenceDoesNotLeakIntoThePlan:
    """Pedir la referencia no mueve ningún número de la corrida conservadora."""

    @pytest.mark.parametrize("plan", PLANS)
    def test_conservative_and_decumulation_fields_are_identical(self, plan):
        kw = dict(PLANS[plan], target_value=CAPITAL, drags={"total_annual_drag_pct": 1.0})
        without = _run(_noisy_history(), longevity=30, n_sims=500, **kw)
        with_ref = _run(_noisy_history(), longevity=30, n_sims=500,
                        include_realistic_reference=True, **kw)
        for name in (
            "median_terminal", "p10_terminal", "p90_terminal", "prob_achieve_target_pct",
            "prob_ruin_pct", "p10_intra_min", "prob_sustain_real_pct",
            "expected_depletion_year", "median_legacy", "fan_paths",
            "base_median_terminal", "base_p10_terminal", "base_p90_terminal",
        ):
            assert getattr(with_ref, name) == getattr(without, name), (plan, name)
