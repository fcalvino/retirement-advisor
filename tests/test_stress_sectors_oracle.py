"""AUDIT-STRESS-SECTORES — un banco o un minero recibe el shock de su sector, no el genérico.

Los seis escenarios de ``STRESS_SCENARIOS`` tienen las claves ``Financials`` y ``Materials``;
yfinance entrega ``Financial Services`` y ``Basic Materials`` (``yfinance.const``: de los 11
sectores, sólo esos dos no tienen clave). ``StressTester`` y el comité hacían
``sector_shocks.get(sector, default_shock)`` sin alias: un banco recibía el shock genérico
(en 2008, −50 % en vez de −80 %), y el estrés de una cartera con financieras quedaba por debajo
del que su propio escenario declara.

Los esperados son los números de cada escenario (2008: Financials −80, Technology −52,
Materials −53), a mano. Sin red.
"""

from __future__ import annotations

import pytest
import yfinance.const as yf_const

from analysis.committee_prompts import sector_stress_shocks
from config import STRESS_SCENARIOS
from portfolio.stress_test import StressTester

YF_SECTORS = sorted(yf_const.SECTOR_INDUSTY_MAPPING)
CRISIS_2008 = STRESS_SCENARIOS[0]


def test_the_reference_list_is_the_eleven_yfinance_sectors():
    assert YF_SECTORS == [
        "Basic Materials", "Communication Services", "Consumer Cyclical", "Consumer Defensive",
        "Energy", "Financial Services", "Healthcare", "Industrials", "Real Estate",
        "Technology", "Utilities",
    ]


@pytest.mark.parametrize("scenario", STRESS_SCENARIOS, ids=lambda s: s.name[:20])
@pytest.mark.parametrize("sector", YF_SECTORS)
def test_every_yfinance_sector_has_its_own_shock_in_every_scenario(scenario, sector):
    """Ningún sector real cae al genérico por un problema de nombre.

    Un sector sin entrada propia no es un error por sí mismo (el escenario puede decidir que no
    lo distingue), así que la pregunta es si el nombre de yfinance *alcanza* la entrada que el
    escenario escribió para ese sector con otro nombre.
    """
    names = {"Financial Services": "Financials", "Basic Materials": "Materials"}
    declared = scenario.sector_shocks.get(sector, scenario.sector_shocks.get(names.get(sector, sector)))
    assert declared is not None, f"{scenario.name}: ni {sector!r} ni su alias están declarados"
    assert scenario.shock_for(sector) == declared


def test_a_bank_gets_the_financials_shock_in_2008():
    r = StressTester().run({"Financial Services": 100.0}, initial_value=100_000)
    by_name = {x.scenario.name: x for x in r}
    assert by_name[CRISIS_2008.name].portfolio_drawdown_pct == -80.0      # no −50 (el genérico)


def test_a_miner_gets_the_materials_shock_in_2008():
    r = StressTester().run({"Basic Materials": 100.0}, initial_value=100_000)
    assert {x.scenario.name: x for x in r}[CRISIS_2008.name].portfolio_drawdown_pct == -53.0


def test_a_mixed_book_is_the_weighted_sum_of_its_sectors():
    """50 % Financial Services + 30 % Technology + 20 % Basic Materials en 2008."""
    r = StressTester().run(
        {"Financial Services": 50.0, "Technology": 30.0, "Basic Materials": 20.0},
        initial_value=100_000,
    )
    expected = 0.5 * -80.0 + 0.3 * -52.0 + 0.2 * -53.0           # = −66.2
    assert {x.scenario.name: x for x in r}[CRISIS_2008.name].portfolio_drawdown_pct == pytest.approx(
        expected, abs=0.05)


def test_the_old_names_still_work():
    r = StressTester().run({"Financials": 100.0, "Materials": 0.0001}, initial_value=100_000)
    assert {x.scenario.name: x for x in r}[CRISIS_2008.name].portfolio_drawdown_pct == pytest.approx(
        -80.0, abs=0.05)


def test_an_unknown_sector_still_takes_the_scenario_default():
    r = StressTester().run({"AlienSector": 100.0}, initial_value=100_000)
    assert {x.scenario.name: x for x in r}[CRISIS_2008.name].portfolio_drawdown_pct == -50.0


def test_the_committee_sees_the_same_shock_for_a_bank():
    """El Abogado del Diablo y el PM leen `sector_stress_shocks`: tampoco puede caer al genérico."""
    worst_name, worst = sector_stress_shocks("Financial Services")[0]
    assert (worst_name, worst) == (CRISIS_2008.name, -80.0)
    assert dict(sector_stress_shocks("Basic Materials"))[CRISIS_2008.name] == -53.0


# --------------------------------------------------------------------------- #
#  Otros nombres que llegan al estrés (hallados en la revisión)               #
# --------------------------------------------------------------------------- #

def _dd_2008(sector: str) -> float:
    r = StressTester().run({sector: 100.0}, initial_value=100_000)
    return {x.scenario.name: x for x in r}[CRISIS_2008.name].portfolio_drawdown_pct


@pytest.mark.parametrize("name, expected", [
    ("Consumer Staples", -32.0),        # = Consumer Defensive en 2008
    ("Consumer Discretionary", -60.0),  # = Consumer Cyclical
    ("Index", -56.0),                   # lo que `fundamental` le pone a un ETF sin sector = ETF
])
def test_names_the_repo_itself_produces_reach_their_sector_shock(name, expected):
    """``SECTOR_MAP`` (la rama sin optimizador de Simulaciones) y ``fundamental`` ("Index")."""
    assert _dd_2008(name) == expected


def test_a_combined_bucket_is_not_guessed():
    """«Telecom / REIT» junta Communication Services (−48) y Real Estate (−67): sin alias honesto."""
    assert _dd_2008("Telecom / REIT") == -50.0


def test_the_simulations_fallback_names_all_resolve_except_the_combined_one():
    from config import SECTOR_MAP

    resolved = {
        name for name in SECTOR_MAP
        if name in CRISIS_2008.sector_shocks or name in {
            "Consumer Staples", "Consumer Discretionary"}
    }
    assert set(SECTOR_MAP) - resolved == {"Telecom / REIT"}
