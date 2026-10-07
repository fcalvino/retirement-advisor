"""Oracle for WD-PHASED — ahorrar hasta el retiro y gastar después.

Hasta este cambio una estrategia de retiro significaba «ya estás retirado»: el
motor gastaba desde hoy sobre el capital de hoy y dejaba el ahorro afuera, con
un aviso (WD-STRATEGY-CONTRIB). El modelo por fases, con el alcance que acordó
el usuario en la decimotercera repriorización (``docs/BACKLOG.md``):

1. la fase cambia en la edad de retiro del perfil (``years_to_retirement``);
2. se ahorra hasta ahí y la estrategia corre después durante la longevidad,
   **contada desde el retiro**;
3. el retiro se calcula sobre el pozo de **cada camino** al retirarse;
4. una edad de retiro alcanzada (``years_to_retirement`` ≤ 0 o ``None``) es el
   «ya retirado» de hoy, byte a byte.

Y una decisión del usuario del 2026-10-02: el monto de ``fixed_real`` está en
**dólares de hoy**, así que el primer retiro ya trae ``R`` años de inflación.

## La referencia

``oracle_phased_wealth`` camina la **riqueza** semana a semana desde la
definición: crece con el mercado, suma cada aporte y resta cada retiro con piso
en cero. No usa unidades, ``apply_cash_flow_schedule`` ni nada del motor. El
mercado es una curva de retorno constante (``_flat_history``), así que el
bootstrap es determinista y todos los caminos son el mismo: lo que se prueba es
la contabilidad de las fases, no el modelo estocástico.

Sin red, sin Streamlit.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from config import MONTE_CARLO, WITHDRAWAL
from portfolio.decumulation import WithdrawalStrategy
from portfolio.monte_carlo import MonteCarloSimulator

DEPOSITS = int(MONTE_CARLO.contribution_periods_per_year)
PAYMENTS = int(MONTE_CARLO.withdrawal_periods_per_year)


def _weekly_rate(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 52.0) - 1.0


def _flat_history(annual_rate: float, n_bars: int = 520) -> pd.DataFrame:
    weekly = _weekly_rate(annual_rate)
    prices = 100.0 * np.cumprod(np.full(n_bars, 1.0 + weekly))
    dates = pd.date_range("2016-01-03", periods=n_bars, freq="W")
    return pd.DataFrame({"close": prices}, index=dates)


def _index(annual_rate: float, years: int, *, haircut: bool = True) -> np.ndarray:
    """The market curve the engine projects. A constant history has no
    deviations, so of the conservative adjustment only ``mean_haircut``
    survives; the realistic reference does not apply it."""
    w = _weekly_rate(annual_rate) * (MONTE_CARLO.mean_haircut if haircut else 1.0)
    return np.concatenate([[1.0], np.cumprod(np.full(years * 52, 1.0 + w))])


# ================================================================== #
#  Reference — written from the definition, not from the source        #
# ================================================================== #

def oracle_phased_wealth(
    index: np.ndarray,
    *,
    initial: float,
    annual_contribution: float,
    years_to_retirement: int,
    decumulation_years: int,
    strategy: dict,
    inflation: float,
    contribution_growth: float = 0.0,
) -> np.ndarray:
    """Wealth at the end of every week of a saver who retires and then spends.

    * Saving: one instalment of the year's savings per period
      (``MONTE_CARLO.contribution_periods_per_year``, monthly: the last one on
      week 52), for ``years_to_retirement`` years, raised by
      ``contribution_growth`` once a year.
    * Retiring: the pot at week ``52 R`` — after that week's deposit — is what
      the strategy starts from.
    * Spending: ``MONTE_CARLO.withdrawal_periods_per_year`` instalments a year
      from the period after retirement. The
      year's figure is decided on its first instalment and repeated on the
      other eleven. ``fixed_real`` is in today's dollars: year ``y`` of
      retirement pays ``A (1 + i)^(R + y - 1)``. ``constant_pct`` takes ``pct``
      of the pot at the review. ``guardrails`` starts at ``pct`` of the pot at
      retirement, indexes it every year after the first, cuts it when the rate
      on the current pot is above ``pct (1 + band)`` and raises it when it is
      below ``pct (1 - band)``.
    * A withdrawal never takes the pot below zero.
    """
    n_cols = len(index)
    retirement_week = 52 * years_to_retirement
    deposits: dict[int, list[float]] = {}
    for yr in range(1, years_to_retirement + 1):
        for m in range(1, DEPOSITS + 1):
            week = (yr - 1) * 52 + round(m * 52 / DEPOSITS)
            deposits.setdefault(week, []).append(
                annual_contribution / DEPOSITS * (1.0 + contribution_growth) ** (yr - 1)
            )
    payments: dict[int, tuple[int, bool]] = {}
    for y in range(1, decumulation_years + 1):
        for p in range(1, PAYMENTS + 1):
            payments[retirement_week + (y - 1) * 52 + round(p * 52 / PAYMENTS)] = (y, p == 1)

    wealth = float(initial)
    out = np.empty(n_cols)
    pot_at_retirement = None
    spend = None
    instalment = 0.0
    for t in range(n_cols):
        if t > 0:
            wealth *= index[t] / index[t - 1]
        for amount in deposits.get(t, []):
            wealth += amount
        if t == retirement_week:
            pot_at_retirement = wealth
        if t in payments:
            year, review = payments[t]
            if review:
                kind = strategy["kind"]
                if kind == "fixed_real":
                    instalment = strategy["annual_amount"] * (1.0 + inflation) ** (
                        years_to_retirement + year - 1) / PAYMENTS
                elif kind == "constant_pct":
                    instalment = strategy["pct"] * wealth / PAYMENTS
                elif kind == "guardrails":
                    wr0 = strategy["pct"]
                    if spend is None:
                        spend = wr0 * pot_at_retirement
                    if year > 1:
                        spend *= 1.0 + inflation
                    rate = spend / wealth if wealth > 0 else float("inf")
                    if rate > wr0 * (1.0 + WITHDRAWAL.guardrail_ceiling_band):
                        spend *= 1.0 - WITHDRAWAL.guardrail_cut_pct
                    if rate < wr0 * (1.0 - WITHDRAWAL.guardrail_floor_band):
                        spend *= 1.0 + WITHDRAWAL.guardrail_raise_pct
                    instalment = spend / PAYMENTS
            wealth = max(wealth - instalment, 0.0)
        out[t] = wealth
    return out


# ================================================================== #
#  Harness                                                             #
# ================================================================== #

RATE = 0.06
INFLATION = 0.03


def _run(*, annual_rate: float = RATE, horizon: int, **kw):
    sim = MonteCarloSimulator(["AAPL"], seed=11)
    with patch(
        "portfolio.monte_carlo.get_history",
        side_effect=lambda *a, **k: _flat_history(annual_rate),
    ):
        return sim.run(horizon_years=horizon, n_sims=50, withdrawal_growth_rate=INFLATION, **kw)


def _oracle(*, annual_rate: float = RATE, years: int, haircut: bool = True, **kw) -> np.ndarray:
    return oracle_phased_wealth(
        _index(annual_rate, years, haircut=haircut), inflation=INFLATION, **kw
    )


STRATEGIES = {
    "fixed_real": {"kind": "fixed_real", "annual_amount": 15_000.0},
    "constant_pct": {"kind": "constant_pct", "pct": 0.045},
    "guardrails": {"kind": "guardrails", "pct": 0.045},
}


# ================================================================== #
#  1. Ahorra hasta el retiro, gasta después                            #
# ================================================================== #

class TestPhasedPlanMatchesTheReference:
    """El plan entero, semana a semana, contra la referencia."""

    R, L = 15, 25
    INITIAL, CONTRIB = 100_000.0, 18_000.0

    @pytest.mark.parametrize("kind", sorted(STRATEGIES))
    def test_wealth_at_the_end_of_retirement(self, kind):
        strategy = STRATEGIES[kind]
        result = _run(
            horizon=self.R + self.L, initial_value=self.INITIAL,
            annual_contribution=self.CONTRIB, withdrawal_strategy=strategy,
            longevity_years=self.L, years_to_retirement=self.R,
        )
        expected = _oracle(
            years=self.R + self.L, initial=self.INITIAL, annual_contribution=self.CONTRIB,
            years_to_retirement=self.R, decumulation_years=self.L, strategy=strategy,
        )
        assert expected[-1] > 0  # el caso no es trivialmente un pozo vacío
        assert result.median_terminal == pytest.approx(expected[-1], rel=1e-9)
        assert result.median_legacy == pytest.approx(expected[-1], abs=1.0)

    @pytest.mark.parametrize("kind", sorted(STRATEGIES))
    def test_the_fan_chart_follows_both_phases(self, kind):
        """Año por año: sube con el ahorro hasta R y después sigue a la estrategia."""
        strategy = STRATEGIES[kind]
        result = _run(
            horizon=self.R + self.L, initial_value=self.INITIAL,
            annual_contribution=self.CONTRIB, withdrawal_strategy=strategy,
            longevity_years=self.L, years_to_retirement=self.R,
        )
        expected = _oracle(
            years=self.R + self.L, initial=self.INITIAL, annual_contribution=self.CONTRIB,
            years_to_retirement=self.R, decumulation_years=self.L, strategy=strategy,
        )
        for year in (1, self.R - 1, self.R, self.R + 1, self.R + self.L // 2):
            assert result.fan_paths[year][50] == pytest.approx(expected[52 * year], abs=1.0)

    def test_the_savings_are_in_and_nobody_is_told_otherwise(self):
        result = _run(
            horizon=self.R, initial_value=self.INITIAL, annual_contribution=self.CONTRIB,
            withdrawal_strategy=STRATEGIES["fixed_real"], longevity_years=self.L,
            years_to_retirement=self.R,
        )
        pot = _oracle(
            years=self.R, initial=self.INITIAL, annual_contribution=self.CONTRIB,
            years_to_retirement=self.R, decumulation_years=0,
            strategy=STRATEGIES["fixed_real"],
        )[-1]
        assert result.median_terminal == pytest.approx(pot, rel=1e-9)
        assert result.contribution_ignored_by_strategy == 0.0
        assert not any("no incluye tu ahorro" in w for w in result.warnings)
        assert result.retirement_years == self.R
        assert result.longevity_years == self.L

    def test_savings_grow_with_their_own_rate_until_retirement(self):
        result = _run(
            horizon=self.R, initial_value=self.INITIAL, annual_contribution=self.CONTRIB,
            contribution_growth_rate=0.02, withdrawal_strategy=STRATEGIES["constant_pct"],
            longevity_years=self.L, years_to_retirement=self.R,
        )
        pot = _oracle(
            years=self.R, initial=self.INITIAL, annual_contribution=self.CONTRIB,
            contribution_growth=0.02, years_to_retirement=self.R, decumulation_years=0,
            strategy=STRATEGIES["constant_pct"],
        )[-1]
        assert result.median_terminal == pytest.approx(pot, rel=1e-9)


class TestFixedRealIsInTodaysDollars:
    """Decisión del usuario (2026-10-02): el monto «real» está en dólares de hoy."""

    def test_the_first_withdrawal_already_carries_the_years_of_inflation(self):
        R, L = 20, 5
        strategy = STRATEGIES["fixed_real"]
        # Mercado plano: lo único que mueve el pozo son los flujos, así que lo que
        # sale el primer año de retiro se lee como una resta.
        result = _run(
            annual_rate=0.0, horizon=R + 1, initial_value=1_000_000.0,
            withdrawal_strategy=strategy, longevity_years=L, years_to_retirement=R,
        )
        first_year = 1_000_000.0 - result.median_terminal
        assert first_year == pytest.approx(strategy["annual_amount"] * (1.0 + INFLATION) ** R, rel=1e-9)


class TestGuardrailsStartFromEachPathsPot:
    """El 4,5 % de los guardrails es del pozo al retirarse, no del capital de hoy."""

    def test_the_base_rate_applies_to_the_pot_at_retirement(self):
        R = 10
        strategy = STRATEGIES["guardrails"]
        result = _run(
            annual_rate=0.0, horizon=R + 1, initial_value=200_000.0,
            annual_contribution=24_000.0, withdrawal_strategy=strategy,
            longevity_years=20, years_to_retirement=R,
        )
        pot = 200_000.0 + 24_000.0 * R
        # Mercado plano: la tasa del primer año es exactamente la base, ninguna
        # banda se cruza, y sale 4,5 % del pozo de ese momento.
        assert pot - result.median_terminal == pytest.approx(0.045 * pot, rel=1e-9)


# ================================================================== #
#  2. Sin capital: el pozo arranca en cero y no es una ruina           #
# ================================================================== #

class TestSaverWithoutCapital:
    """Capital 0 + ahorro + estrategia: hoy el motor devolvía ceros."""

    R, L = 20, 25
    CONTRIB = 24_000.0

    @pytest.mark.parametrize("kind", sorted(STRATEGIES))
    def test_projects_what_the_savings_build(self, kind):
        strategy = STRATEGIES[kind]
        result = _run(
            horizon=self.R + self.L, initial_value=0.0, annual_contribution=self.CONTRIB,
            withdrawal_strategy=strategy, longevity_years=self.L,
            years_to_retirement=self.R,
        )
        expected = _oracle(
            years=self.R + self.L, initial=0.0, annual_contribution=self.CONTRIB,
            years_to_retirement=self.R, decumulation_years=self.L, strategy=strategy,
        )
        assert result.fan_paths[self.R][50] == pytest.approx(expected[52 * self.R], abs=1.0)
        assert result.median_terminal == pytest.approx(expected[-1], rel=1e-9)

    def test_the_empty_weeks_before_the_first_deposit_are_not_an_exhausted_income(self):
        """Las semanas 0–3 valen 0. Leídas como agotamiento, el ingreso «no dura»
        en el 100 % de los caminos de alguien que nunca empezó a gastar."""
        result = _run(
            horizon=self.R + self.L, initial_value=0.0, annual_contribution=self.CONTRIB,
            withdrawal_strategy=STRATEGIES["constant_pct"], longevity_years=self.L,
            years_to_retirement=self.R,
        )
        assert result.prob_sustain_real_pct == 100.0
        assert result.expected_depletion_year == 0.0
        assert result.prob_ruin_pct == 0.0


# ================================================================== #
#  3. La longevidad se cuenta desde el retiro                          #
# ================================================================== #

class TestLongevityCountsFromRetirement:
    R, L = 20, 30

    def test_the_simulation_reaches_the_end_of_retirement(self):
        """Horizonte 10: el motor igual simula hasta R + L y mide ahí."""
        strategy = {"kind": "fixed_real", "annual_amount": 45_000.0}
        result = _run(
            horizon=10, initial_value=300_000.0, annual_contribution=12_000.0,
            withdrawal_strategy=strategy, longevity_years=self.L,
            years_to_retirement=self.R,
        )
        expected = _oracle(
            years=self.R + self.L, initial=300_000.0, annual_contribution=12_000.0,
            years_to_retirement=self.R, decumulation_years=self.L, strategy=strategy,
        )
        assert result.median_legacy == pytest.approx(expected[-1], abs=1.0)
        assert result.longevity_years == self.L

    def test_the_depletion_year_is_counted_from_today(self):
        """«Año X» en Simulaciones, Mi Plan, el PDF y el prompt cuenta desde hoy;
        el motor lo sigue reportando así para que esas frases no mientan."""
        strategy = {"kind": "fixed_real", "annual_amount": 90_000.0}
        result = _run(
            horizon=10, initial_value=300_000.0, annual_contribution=12_000.0,
            withdrawal_strategy=strategy, longevity_years=self.L,
            years_to_retirement=self.R,
        )
        expected = _oracle(
            years=self.R + self.L, initial=300_000.0, annual_contribution=12_000.0,
            years_to_retirement=self.R, decumulation_years=self.L, strategy=strategy,
        )
        eps = 300_000.0 * 1e-9
        first_empty = int(np.argmax(expected <= eps))
        assert expected[52 * self.R] > 0 and first_empty > 52 * self.R
        assert result.prob_sustain_real_pct == 0.0
        assert result.expected_depletion_year == pytest.approx(round(first_empty / 52, 2))

    def test_without_a_longevity_the_config_default_is_used(self):
        result = _run(
            horizon=5, initial_value=300_000.0, annual_contribution=12_000.0,
            withdrawal_strategy=STRATEGIES["constant_pct"], years_to_retirement=self.R,
        )
        assert result.longevity_years == WITHDRAWAL.default_longevity_years


# ================================================================== #
#  4. El mercado realista sólo dibuja el horizonte                     #
# ================================================================== #

class TestHorizonBeyondRetirement:
    """Horizonte > R + longevidad: el gasto sigue hasta el final del horizonte,
    pero las métricas de retiro leen la longevidad pedida."""

    def test_terminal_reads_the_horizon_and_legacy_reads_the_longevity(self):
        R, L, horizon = 10, 20, 40
        strategy = STRATEGIES["constant_pct"]
        result = _run(
            horizon=horizon, initial_value=100_000.0, annual_contribution=18_000.0,
            withdrawal_strategy=strategy, longevity_years=L, years_to_retirement=R,
        )
        expected = _oracle(
            years=horizon, initial=100_000.0, annual_contribution=18_000.0,
            years_to_retirement=R, decumulation_years=horizon - R, strategy=strategy,
        )
        assert result.median_terminal == pytest.approx(expected[-1], rel=1e-9)
        assert result.median_legacy == pytest.approx(expected[52 * (R + L)], abs=1.0)


class TestEachPathKeepsItsOwnPot:
    """Con un mercado plano todos los caminos son el mismo, y un pozo común o
    escalar pasaría igual. Acá cada camino tiene su mercado y se compara contra
    la referencia corrida camino por camino."""

    R, L = 8, 12

    @staticmethod
    def _market(n_sims: int, years: int) -> np.ndarray:
        rng = np.random.default_rng(20261002)
        weekly = rng.normal(0.0012, 0.02, size=(n_sims, years * 52))
        return np.concatenate([np.ones((n_sims, 1)), np.cumprod(1.0 + weekly, axis=1)], axis=1)

    @pytest.mark.parametrize("kind", sorted(STRATEGIES))
    def test_every_path_matches_its_own_reference(self, kind):
        strategy = STRATEGIES[kind]
        market = self._market(40, self.R + self.L)
        initial, contrib = 80_000.0, 12_000.0
        basis = initial
        wealth = MonteCarloSimulator._apply_phased_plan(
            market, initial, basis, contrib, WithdrawalStrategy.coerce(strategy),
            self.R, (self.R + self.L) * 52, withdrawal_growth_rate=INFLATION,
        ) * basis
        pots = wealth[:, 52 * self.R]
        assert np.ptp(pots) > 0.1 * pots.mean()  # los pozos sí difieren
        for i in range(market.shape[0]):
            expected = oracle_phased_wealth(
                market[i], initial=initial, annual_contribution=contrib,
                years_to_retirement=self.R, decumulation_years=self.L,
                strategy=strategy, inflation=INFLATION,
            )
            np.testing.assert_allclose(wealth[i], expected, rtol=1e-9, atol=1e-6)


# ================================================================== #
#  5. Lo que no cambia                                                 #
# ================================================================== #

def _same(a, b):
    assert a.fan_paths == b.fan_paths
    for field in ("median_terminal", "p10_terminal", "prob_ruin_pct", "prob_sustain_real_pct",
                  "median_legacy", "expected_depletion_year", "longevity_years",
                  "contribution_ignored_by_strategy", "retirement_years"):
        assert getattr(a, field) == getattr(b, field), field
    assert a.warnings == b.warnings


class TestAlreadyRetiredIsTodaysEngine:
    """Edad desconocida o ya alcanzada: «ya estás retirado», el ahorro afuera.

    Esto prueba que el parámetro no cambia nada cuando no hay fase. Que esa rama
    sea la de antes de WD-PHASED lo sostienen los oráculos que ya la fijaban
    (``test_withdrawal_oracle``, ``test_longevity_horizon_oracle``,
    ``test_cash_flow_oracle``, ``test_decumulation``), que no se tocaron, y una
    comparación de 144 corridas bit a bit contra el motor de ``feba226`` hecha al
    implementar (tres estrategias y sin estrategia × capital × aporte ×
    longevidad × R en {None, 0, −3})."""

    @pytest.mark.parametrize("kind", sorted(STRATEGIES))
    @pytest.mark.parametrize("years", [0, -4])
    def test_identical_to_the_call_without_a_retirement_age(self, kind, years):
        kw = dict(horizon=20, initial_value=500_000.0, annual_contribution=12_000.0,
                  withdrawal_strategy=STRATEGIES[kind], longevity_years=30)
        _same(_run(**kw, years_to_retirement=years), _run(**kw))

    def test_the_savings_stay_out_and_it_is_said(self):
        result = _run(horizon=20, initial_value=500_000.0, annual_contribution=12_000.0,
                      withdrawal_strategy=STRATEGIES["fixed_real"], longevity_years=30,
                      years_to_retirement=0)
        assert result.contribution_ignored_by_strategy == 12_000.0
        assert any("no incluye tu ahorro" in w for w in result.warnings)
        assert result.retirement_years == 0


class TestWithoutAStrategyTheAgeMeansNothing:
    def test_accumulation_ignores_the_retirement_age(self):
        kw = dict(horizon=20, initial_value=50_000.0, annual_contribution=12_000.0)
        _same(_run(**kw, years_to_retirement=15), _run(**kw))


# ================================================================== #
#  6. Simulaciones le pasa la edad al motor                            #
# ================================================================== #

class TestSimulacionesWiring:
    """Simulaciones es el único lugar que corre el motor con estrategia, y Mi Plan
    guarda esa corrida: si la edad no llega desde ahí, el modelo por fases no
    existe para el usuario."""

    @staticmethod
    def _page() -> str:
        from pathlib import Path

        return (Path(__file__).resolve().parents[1]
                / "dashboard" / "views" / "7_Simulaciones.py").read_text(encoding="utf-8")

    def test_the_age_comes_from_the_profile(self):
        import re

        profile = re.search(r"def _profile_saving_years\(\).*?\n\n\n", self._page(), re.S)
        assert profile and "primary_horizon_years" in profile.group(0)
        # WD-PHASED PR 2: un plan cargado manda con su R; si no, el perfil.
        helper = re.search(r"def _saving_years\(\).*?\n\n\n", self._page(), re.S)
        assert helper and "LOADED_PLAN_RETIREMENT_KEY" in helper.group(0)
        assert "_profile_saving_years()" in helper.group(0)

    def test_the_main_run_and_the_lab_pass_it(self):
        page = self._page()
        assert page.count("years_to_retirement=_saving_years() if _wd else None") == 1
        assert page.count('"years_to_retirement": _saving_years() if _wd else None') == 1

    def test_the_page_only_says_the_savings_stay_out_when_they_do(self):
        """Los dos avisos que la página calcula por su cuenta tienen que saber de la
        fase; el resto de las superficies leen ``contribution_ignored_by_strategy``
        del resultado, que el motor pone en 0 cuando hay fase."""
        import re

        page = self._page()
        guards = re.findall(r"if ([^:]*?):\s*\n(?:\s*#[^\n]*\n)*\s*\S*caption\(STRATEGY_IGNORES_SAVINGS_CAPTION\)",
                            page, re.S)
        assert len(guards) == 2
        assert all("not _saving_years()" in g for g in guards)

    def test_the_lab_forwards_it_to_the_engine(self, monkeypatch):
        import dashboard.shared as shared

        seen = {}
        monkeypatch.setattr(shared, "cached_monte_carlo", lambda **kw: seen.update(kw))
        shared._sensitivity_run_fn({"symbols": ("SPY",), "weights": None, "years_to_retirement": 17})
        assert seen["years_to_retirement"] == 17
