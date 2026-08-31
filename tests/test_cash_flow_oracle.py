"""Oracle tests for how money ENTERS the pot (backlog U4-2 and U4-1).

``tests/test_withdrawal_oracle.py`` pinned the way money leaves (audit D1/D2).
Nothing pinned the way it arrives, and two defects lived there:

  * **U4-2** — the cash flow is expressed as a fraction of ``initial_value``
    (``monte_carlo.py``, ``_apply_withdrawals``), so a plan that starts with no
    capital has no unit to express its savings in. The code turned that into
    ``0.0`` and the whole plan projected zero: 0 % probability of success for
    the one question a young saver asks. A silent zero, not an error.
  * **U4-1** — a monthly saving was multiplied by twelve and deposited whole in
    week 52, so eleven of the twelve deposits lost their partial year of growth.

Both are cash-flow *accounting*, so both are testable the way the audit demands:
against a slow reference written from the financial definition — a saver who
deposits on a date and whose money only compounds from that date — never against
the engine's own previous output, which would freeze the bug rather than find it.

The market model is not under test here, so it is made deterministic: a history
whose weekly return is constant resamples to itself, so every bootstrapped path
is the same geometric curve and the reference can be written in closed form.

No network, no Streamlit, no fixtures shared with the production modules.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from config import MONTE_CARLO
from portfolio.monte_carlo import MonteCarloSimulator

# ------------------------------------------------------------------ #
#  Deterministic market (shared inputs, not shared logic)              #
# ------------------------------------------------------------------ #

MONTHS_PER_YEAR = 12


def _weekly_rate(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 52.0) - 1.0


def _flat_history(annual_rate: float, n_bars: int = 520):
    """A price series whose weekly return never varies.

    Resampling a constant series returns the constant, so the bootstrap becomes
    deterministic and the projection is a plain geometric curve. That removes
    the stochastic model from the picture and leaves only the cash-flow
    accounting, which is what these tests are about.
    """
    weekly = _weekly_rate(annual_rate)
    prices = 100.0 * np.cumprod(np.full(n_bars, 1.0 + weekly))
    dates = pd.date_range("2016-01-03", periods=n_bars, freq="W")
    return pd.DataFrame({"close": prices}, index=dates)


def _effective_weekly(annual_rate: float) -> float:
    """The weekly rate the engine actually projects with.

    ``_conservative_adjustment`` keeps ``mean_haircut`` of the historical mean
    and widens deviations by ``vol_adjustment``. With a constant history there
    are no deviations, so only the haircut survives. Read from config rather
    than hardcoded — the haircut is an input to these tests, not their subject.
    """
    return _weekly_rate(annual_rate) * MONTE_CARLO.mean_haircut


def _index(annual_rate: float, years: int) -> np.ndarray:
    """The relative market curve the engine projects, starting at 1.0."""
    w = _effective_weekly(annual_rate)
    return np.concatenate([[1.0], np.cumprod(np.full(years * 52, 1.0 + w))])


def _contribution_weeks(years: int) -> list[int]:
    """Week index of each monthly deposit. Month 12 lands exactly on week 52."""
    return [
        round(m * 52 / MONTHS_PER_YEAR) + (yr - 1) * 52
        for yr in range(1, years + 1)
        for m in range(1, MONTHS_PER_YEAR + 1)
    ]


# ================================================================== #
#  References — written from the definition, not from the source       #
# ================================================================== #

def oracle_monthly_contribution_sequence(
    index: np.ndarray,
    initial: float,
    annual_contribution: float,
    years: int,
    growth_rate: float = 0.0,
) -> float:
    """Reference: a saver who deposits one twelfth on the first bar of a month.

    Walks the market curve one deposit at a time. Each deposit joins the pot at
    the level of the week it arrives and compounds only from there — which is
    what depositing money means. The annual raise is applied once per year, so
    the twelve deposits of a year sum to exactly the year's nominal total.
    """
    wealth = initial
    previous_week = 0
    for week in _contribution_weeks(years):
        year = min(max((week - 1) // 52 + 1, 1), years)
        wealth *= index[week] / index[previous_week]
        wealth += (annual_contribution / MONTHS_PER_YEAR) * (
            (1.0 + growth_rate) ** (year - 1)
        )
        previous_week = week
    wealth *= index[-1] / index[previous_week]
    return wealth


def oracle_annual_lump_sequence(
    index: np.ndarray,
    initial: float,
    annual_contribution: float,
    years: int,
) -> float:
    """Reference for the PRE-FIX instrument: one deposit per year, at week 52.

    Kept as a reference so the direction of the change is provable rather than
    asserted: the same money deposited later can never be worth more.
    """
    wealth = initial
    for yr in range(1, years + 1):
        wealth *= index[yr * 52] / index[(yr - 1) * 52]
        wealth += annual_contribution
    return wealth


# ================================================================== #
#  1. A plan that starts empty (U4-2)                                  #
# ================================================================== #

class TestZeroCapitalAccumulationOracle:
    """"¿Llego si ahorro X por mes?" must be answerable without seed capital."""

    HORIZON = 20
    RATE = 0.07
    CONTRIB = 12_000.0

    def _run(self, initial: float, contribution: float, **kw):
        sim = MonteCarloSimulator(["AAPL"], seed=42)
        with patch(
            "portfolio.monte_carlo.get_history",
            side_effect=lambda *a, **k: _flat_history(self.RATE),
        ):
            return sim.run(
                horizon_years=self.HORIZON,
                n_sims=200,
                initial_value=initial,
                annual_withdrawal=-contribution,
                **kw,
            )

    def test_a_plan_that_starts_empty_still_compounds_its_savings(self):
        result = self._run(initial=0.0, contribution=self.CONTRIB)

        expected = oracle_monthly_contribution_sequence(
            _index(self.RATE, self.HORIZON), 0.0, self.CONTRIB, self.HORIZON
        )
        assert result.median_terminal > 0.0
        assert result.median_terminal == pytest.approx(expected, rel=1e-9)

    def test_savings_only_plan_can_reach_its_target(self):
        result = self._run(initial=0.0, contribution=self.CONTRIB, target_value=100_000.0)
        assert result.prob_achieve_target_pct > 0.0

    def test_ruin_does_not_count_the_weeks_before_the_first_deposit(self):
        """Starting empty is the accumulation phase, not bankruptcy.

        The pot is worth 0 until the first contribution lands. Reading that
        prefix as ruin would report 100 % failure for every saver who begins
        with nothing — the opposite of the truth about their plan.
        """
        result = self._run(initial=0.0, contribution=self.CONTRIB)
        assert result.prob_ruin_pct == 0.0

    def test_a_plan_with_neither_capital_nor_savings_is_still_zero(self):
        """Anti-cheat: the fix must not be "never report a zero"."""
        result = self._run(initial=0.0, contribution=0.0)
        assert result.median_terminal == 0.0

    def test_annualised_growth_stays_a_finite_number_without_capital(self):
        """Pot growth divides by ``initial_value``; with no capital it is undefined.

        It must degrade to something a caller can render, not to ``inf``.
        """
        result = self._run(initial=0.0, contribution=self.CONTRIB)
        assert np.isfinite(result.median_cagr_pct)
        assert np.isfinite(result.p10_cagr_pct)


# ================================================================== #
#  2. Cadence (U4-1)                                                   #
# ================================================================== #

class TestMonthlyCadenceOracle:
    """A monthly saving must arrive monthly, not as a lump every December."""

    HORIZON = 15
    CONTRIB = 12_000.0

    def _run(self, annual_rate: float, initial: float, contribution: float, **kw):
        sim = MonteCarloSimulator(["AAPL"], seed=7)
        with patch(
            "portfolio.monte_carlo.get_history",
            side_effect=lambda *a, **k: _flat_history(annual_rate),
        ):
            return sim.run(
                horizon_years=self.HORIZON,
                n_sims=200,
                initial_value=initial,
                annual_withdrawal=-contribution,
                **kw,
            )

    @pytest.mark.parametrize("annual_rate", [-0.04, 0.0, 0.05, 0.09])
    def test_engine_matches_the_monthly_reference(self, annual_rate):
        result = self._run(annual_rate, initial=50_000.0, contribution=self.CONTRIB)

        expected = oracle_monthly_contribution_sequence(
            _index(annual_rate, self.HORIZON), 50_000.0, self.CONTRIB, self.HORIZON
        )
        assert result.median_terminal == pytest.approx(expected, rel=1e-9)

    def test_twelve_monthly_deposits_beat_one_annual_lump(self):
        """The same money, deposited earlier, is worth more. That is the bug."""
        index = _index(0.07, self.HORIZON)
        monthly = oracle_monthly_contribution_sequence(
            index, 0.0, self.CONTRIB, self.HORIZON
        )
        lump = oracle_annual_lump_sequence(index, 0.0, self.CONTRIB, self.HORIZON)

        assert monthly > lump
        result = self._run(0.07, initial=0.0, contribution=self.CONTRIB)
        assert result.median_terminal == pytest.approx(monthly, rel=1e-9)

    def test_cadence_cannot_matter_in_a_market_that_does_not_move(self):
        """With no growth to lose, timing is worth exactly nothing."""
        index = _index(0.0, self.HORIZON)
        monthly = oracle_monthly_contribution_sequence(
            index, 0.0, self.CONTRIB, self.HORIZON
        )
        lump = oracle_annual_lump_sequence(index, 0.0, self.CONTRIB, self.HORIZON)
        assert monthly == pytest.approx(lump, rel=1e-12)

    def test_the_annual_raise_moves_the_timing_not_the_yearly_total(self):
        """Inflation-adjusted savings still deposit the year's nominal total.

        The raise steps once a year, so the twelve deposits of year *k* sum to
        the same amount the old yearly lump would have deposited. Only *when*
        the money arrives changes — which is what makes the direction of the
        fix provable instead of merely different.
        """
        growth, rate = 0.03, 0.0
        index = _index(rate, self.HORIZON)
        with_raise = oracle_monthly_contribution_sequence(
            index, 0.0, self.CONTRIB, self.HORIZON, growth_rate=growth
        )
        expected_nominal = sum(
            self.CONTRIB * (1.0 + growth) ** (yr - 1) for yr in range(1, self.HORIZON + 1)
        )
        assert with_raise == pytest.approx(expected_nominal, rel=1e-12)

        result = self._run(
            rate, initial=0.0, contribution=self.CONTRIB, withdrawal_growth_rate=growth
        )
        assert result.median_terminal == pytest.approx(with_raise, rel=1e-9)


# ================================================================== #
#  3. The invariants the fix must not break                            #
# ================================================================== #

class TestDepletionIsStillAbsorbing:
    """U4-2 makes an empty pot fundable. It must not make a ruined pot revivable."""

    def test_market_growth_never_revives_a_pot_that_was_spent(self):
        sim = MonteCarloSimulator(["AAPL"], seed=3)
        with patch(
            "portfolio.monte_carlo.get_history",
            side_effect=lambda *a, **k: _flat_history(0.05),
        ):
            result = sim.run(
                horizon_years=30,
                n_sims=200,
                initial_value=100_000.0,
                annual_withdrawal=50_000.0,   # spends the pot within a few years
            )
        assert result.prob_ruin_pct == 100.0
        assert result.median_terminal == 0.0

    def test_a_cash_flow_never_mutates_the_market_series(self):
        """U2-2 holds because drawdown is read off an untouched market curve.

        Today that is true only because ``run`` computes the drawdown before
        calling the kernel — the legacy kernel writes through its input. Making
        it structurally true is what lets the ordering stop being load-bearing.
        """
        path = np.array([_index(0.06, 10)])
        before = path.copy()
        MonteCarloSimulator._apply_withdrawals(path, 100_000.0, 5_000.0, 10 * 52)
        np.testing.assert_array_equal(path, before)


# ================================================================== #
#  4. One unit, one source (U4-1's second oracle)                      #
# ================================================================== #

class TestTheBasisIsAnImplementationDetail:
    """The internal scale must never reach a reported number.

    Wealth is held in multiples of a positive basis. The projection is
    homogeneous of degree 1 in it, so any positive choice gives the same answer
    — and a mutation test that swapped the basis for another positive value went
    undetected, which is the right outcome for a free parameter but only if it
    is stated. What is NOT free is the basis being positive: that is the whole
    of U4-2, and a basis of zero collapses every projection back to nothing.
    """

    HORIZON = 12
    RATE = 0.06
    CONTRIB = 9_000.0

    def _terminal(self, basis: float) -> float:
        market = np.array([_index(self.RATE, self.HORIZON)])
        wealth = MonteCarloSimulator._apply_cash_flows(
            market, 0.0, basis, 0.0, self.CONTRIB, self.HORIZON * 52,
        )
        return float(wealth[0, -1] * basis)

    @pytest.mark.parametrize("basis", [1.0, 250.0, 1e6])
    def test_the_answer_does_not_depend_on_the_scale_it_was_computed_in(self, basis):
        assert self._terminal(basis) == pytest.approx(self._terminal(1.0), rel=1e-9)

    def test_the_scale_chosen_for_a_savings_only_plan_is_positive(self):
        from portfolio.decumulation import wealth_basis

        assert wealth_basis(0.0, 9_000.0) > 0.0
        assert wealth_basis(0.0) > 0.0
        assert wealth_basis(50_000.0, 9_000.0) == 50_000.0


class TestContributionUnitsContract:
    """Simulaciones y Metas tienen que pedirle al mismo ahorrista la misma plata.

    U4-1 puso el ×12 en un solo lugar —``contribution_inputs``— porque cada
    pantalla hacía el suyo y el mismo ahorrista salía cotizado distinto según
    dónde mirara.

    Cuando se escribió este contrato la pestaña principal **no tenía widget de
    aporte**: su único input de flujo era un retiro con piso en cero, así que la
    pantalla que contesta «¿llego?» no podía representar que alguien ahorre
    (U4-5). Ahora lo tiene, y el contrato se extiende a ella: la palanca escribe
    el ahorro en la unidad que el helper lee, y la corrida lo resuelve con el
    helper en vez de multiplicar por su cuenta.
    """

    PAGE = "dashboard/pages/7_Simulaciones.py"

    def _page(self) -> str:
        from pathlib import Path

        return Path(self.PAGE).read_text(encoding="utf-8")

    def test_the_helper_converts_in_one_place(self):
        from data.product_ux import contribution_inputs

        resolved = contribution_inputs(personal={"monthly_savings": 500.0})
        assert resolved["monthly"] == pytest.approx(500.0)
        assert resolved["annual"] == pytest.approx(6_000.0)
        assert resolved["source"]

    def test_no_surface_multiplies_savings_by_twelve_on_its_own(self):
        assert "contribution_inputs" in self._page()

    def test_no_surface_reads_a_session_key_no_widget_writes(self):
        """``annual_contribution`` se leía de session state y ningún widget lo
        escribía. Una clave que nadie escribe resuelve siempre a su fallback, que
        es un cero silencioso disfrazado de input del usuario."""
        assert 'st.session_state.get("annual_contribution")' not in self._page()

    # -- U4-5: la palanca de la pestaña principal ---------------------- #

    def test_la_pestania_principal_tiene_una_palanca_de_aporte(self):
        """El defecto: el único widget de flujo era un retiro con piso en cero.

        La clave del widget tiene que ser la que ``contribution_inputs`` lee como
        primera opción, o el número quedaría escrito donde nadie lo busca.
        """
        page = self._page()
        assert 'key="monthly_savings"' in page, (
            "no hay palanca de aporte con la clave que el helper lee"
        )

    def test_la_corrida_principal_recibe_el_aporte(self):
        """Que el widget exista no alcanza: el número tiene que llegar al motor.

        Se mira la llamada a ``cached_monte_carlo`` y no cualquier aparición de
        ``annual_contribution=`` en la página — la palanca de «cuánto me falta»
        ya pasaba uno, así que un `in page` a secas pasa sobre el código roto.
        """
        import re

        page = self._page()
        llamadas = [
            m for m in re.finditer(r"cached_monte_carlo\((.*?)\n\s*\)", page, re.S)
        ]
        assert llamadas, "no se encontró la llamada al motor"
        assert any("annual_contribution" in m.group(1) for m in llamadas), (
            "ninguna llamada a cached_monte_carlo pasa annual_contribution: la "
            "palanca sería decorativa"
        )

    def test_el_aporte_de_la_corrida_sale_del_helper_y_no_de_una_cuenta_propia(self):
        """La restricción que U4-1 dejó: nadie multiplica por doce por su cuenta.

        No se mide por proximidad —una ventana de líneas marca código legítimo
        cuando la asignación y el uso quedan lejos, y tapa al culpable cuando
        quedan cerca (la lección de U7-3)—. Se mide por la propiedad: todo valor
        pasado como ``annual_contribution`` tiene que ser un nombre que en algún
        lado se asignó desde ``contribution_inputs``, o un cero literal.
        """
        import re

        page = self._page()
        del_helper = set(
            re.findall(r"(\w+)\s*=\s*contribution_inputs\(", page)
        )
        assert del_helper, "nadie resuelve el ahorro con el helper"

        pasados = re.findall(r"annual_contribution\s*=\s*([^,\n]+)", page)
        assert pasados, "la corrida no pasa el aporte"
        for expr in pasados:
            expr = expr.strip().rstrip(",").strip()
            ok = (
                any(nombre in expr for nombre in del_helper)
                or re.fullmatch(r"(float\()?0(\.0)?\)?", expr)
                or "contribution_inputs" in expr
                # Metas construye su Goal con el aporte que el usuario tipeó en
                # ESE formulario, que es otro número y tiene su propio widget.
                or "new_contribution" in expr
                or "goal." in expr
            )
            assert ok, (
                f"`annual_contribution={expr}` no salió de contribution_inputs: "
                f"si alguien hace su propio ×12, dos pantallas vuelven a "
                f"cotizarle plata distinta al mismo ahorrista"
            )

    def test_la_pagina_no_hace_su_propia_conversion_mensual_anual(self):
        """Barrido: ningún ×12 ni ÷12 sobre el ahorro fuera del helper."""
        import re

        ofensas = [
            f"{n + 1}: {l.strip()}"
            for n, l in enumerate(self._page().splitlines())
            if re.search(r"(monthly_savings|ahorro)\w*\s*[*/]\s*12", l, re.IGNORECASE)
        ]
        assert not ofensas, (
            "la página convierte el ahorro por su cuenta:\n  " + "\n  ".join(ofensas)
        )


class TestSinAporteCargadoNadaSeMueve:
    """El alcance del cambio, medido: una corrida sin ahorro es la de siempre."""

    HORIZON = 15
    RATE = 0.06

    def _run(self, contribution: float):
        sim = MonteCarloSimulator(["AAPL"], seed=11)
        with patch(
            "portfolio.monte_carlo.get_history",
            side_effect=lambda *a, **k: _flat_history(self.RATE),
        ):
            return sim.run(
                horizon_years=self.HORIZON,
                n_sims=200,
                initial_value=100_000.0,
                annual_withdrawal=0.0,
                annual_contribution=contribution,
            )

    def test_un_aporte_de_cero_deja_el_terminal_intacto(self):
        """Lo que el helper devuelve cuando no hay ahorro cargado es 0.0, y con
        0.0 el motor tiene que dar exactamente lo de antes."""
        from data.product_ux import contribution_inputs

        assert contribution_inputs()["annual"] == 0.0
        assert self._run(0.0).median_terminal == pytest.approx(
            100_000.0 * _index(self.RATE, self.HORIZON)[-1], rel=1e-9
        )

    def test_con_aporte_la_proyeccion_si_se_mueve(self):
        """Anti-cheat: que no se mueva sin aporte no puede ser porque el
        parámetro se ignore."""
        sin = self._run(0.0).median_terminal
        con = self._run(6_000.0).median_terminal
        assert con > sin

        esperado = oracle_monthly_contribution_sequence(
            _index(self.RATE, self.HORIZON), 100_000.0, 6_000.0, self.HORIZON
        )
        assert con == pytest.approx(esperado, rel=1e-9)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
