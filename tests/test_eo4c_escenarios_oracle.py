"""Oráculo EO-4c-1: tres Escenarios y el Escenario de planificación del Perfil.

ADR 0001: los Escenarios son Desacuerdo, no Azar. Decisiones del usuario
(2026-10-06):

- pesimista / optimista ponen cada Clase en su Fuente vigente más baja / más alta;
  central es la mediana (lo de EO-4a);
- bonos EE.UU. y los tickers sin Clase conservan el haircut, igual en los tres;
  cripto proyecta 0 % real en los tres;
- el Escenario de planificación sale del Perfil: Conservador planifica con el
  pesimista, Moderado y Agresivo con el central; el usuario lo puede cambiar; sin
  Perfil no hay Postura (None) y quien llama usa el central;
- el Optimizer no lee el Escenario: su μ sigue en el central (EO-4b).

Con una historia de rendimiento constante no hay desvíos, así que cada camino es
determinístico y el terminal sale a mano: ``1000 · (1 + E)^10``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
YEARS = 10
CENTRALS = {"us_equity": 6.7, "developed_ex_us": 6.65, "emerging": 7.225,
            "us_bonds": 4.88, "reits": 8.72, "crypto": None}
RANGES = {"us_equity": (4.2, 9.1), "developed_ex_us": (5.0, 8.0), "emerging": (5.5, 9.5),
          "us_bonds": (4.0, 5.5), "reits": (6.0, 10.0), "crypto": (None, None)}
INFLATION = 2.36


def _weekly(annual_pct):
    return (1 + annual_pct / 100) ** (1 / 52) - 1


def _flat(annual_pct, n=520):
    prices = 100.0 * np.cumprod(np.full(n, 1.0 + _weekly(annual_pct)))
    return pd.DataFrame({"close": prices}, index=pd.date_range("2016-01-03", periods=n, freq="W"))


@pytest.fixture
def fuentes_fijas(monkeypatch):
    import analysis.estimacion as est

    monkeypatch.setattr(est, "class_centrals", lambda: dict(CENTRALS))
    monkeypatch.setattr(est, "class_ranges", lambda: dict(RANGES))
    monkeypatch.setattr(est, "inflation_pct", lambda: INFLATION)


def _sim(symbols, rates, *, classes, scenario="central"):
    from portfolio.monte_carlo import MonteCarloSimulator

    hist = {s: _flat(r) for s, r in zip(symbols, rates)}
    sim = MonteCarloSimulator(symbols, seed=3, asset_classes=classes, scenario=scenario)
    return sim, hist


def _run(symbols, rates, *, classes, scenario="central", **kw):
    sim, hist = _sim(symbols, rates, classes=classes, scenario=scenario)
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda s, **k: hist[s]):
        return sim.run(horizon_years=YEARS, n_sims=50, initial_value=1_000.0, **kw)


def _terminal(annual_pct):
    return 1_000 * (1 + annual_pct / 100) ** YEARS


# --------------------------------------------------------------------------- #
#  La Estimación por Escenario                                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("scenario, expected", [
    ("pesimista", 4.2), ("central", 6.7), ("optimista", 9.1),
])
def test_us_equity_projects_each_scenario(fuentes_fijas, scenario, expected):
    res = _run(["AAPL"], [12.0], classes={"AAPL": "us_equity"}, scenario=scenario)
    assert res.median_terminal == pytest.approx(_terminal(expected), rel=1e-9)
    assert res.scenario == scenario


def test_haircut_and_crypto_are_the_same_in_the_three(fuentes_fijas):
    from config import MONTE_CARLO

    for scenario in ("pesimista", "central", "optimista"):
        bnd = _run(["BND"], [3.0], classes={"BND": "us_bonds"}, scenario=scenario)
        w = _weekly(3.0) * MONTE_CARLO.mean_haircut
        assert bnd.median_terminal == pytest.approx(1_000 * (1 + w) ** 520, rel=1e-9), scenario
        btc = _run(["BTC-USD"], [40.0], classes={"BTC-USD": "crypto"}, scenario=scenario)
        assert btc.median_terminal == pytest.approx(_terminal(INFLATION), rel=1e-9), scenario


def test_the_label_names_the_scenario_off_central(fuentes_fijas):
    from analysis.estimacion import asset_estimations

    [pes] = asset_estimations(["AAPL"], {"AAPL": "us_equity"}, scenario="pesimista")
    [cen] = asset_estimations(["AAPL"], {"AAPL": "us_equity"})
    assert pes.annual_pct == 4.2 and "(pesimista)" in pes.label
    assert cen.annual_pct == 6.7 and "(" not in cen.label.split("·")[0]


def test_an_unknown_scenario_is_refused(fuentes_fijas):
    from analysis.estimacion import class_estimates

    with pytest.raises(ValueError):
        class_estimates("realista")


def test_the_range_comes_only_from_current_sources():
    """Una Fuente de más de 24 meses sale del central y también del rango."""
    from datetime import date

    from analysis.fuentes import Fuente, summarize_class

    today = date(2026, 10, 6)
    def f(name, value, as_of):
        return Fuente(name=name, kind="gestora", asset_class="us_equity", value_pct=value,
                      basis="nominal", currency="USD", as_of=as_of, source="")

    srcs = [f("A", 5.0, date(2026, 1, 1)), f("B", 7.0, date(2026, 1, 1)),
            f("Vieja", 1.0, date(2023, 1, 1))]
    s = summarize_class("us_equity", srcs, today=today)
    assert (s.low_pct, s.high_pct) == (5.0, 7.0)


# --------------------------------------------------------------------------- #
#  Los tres a la vez                                                           #
# --------------------------------------------------------------------------- #

def test_include_scenarios_reports_the_three(fuentes_fijas):
    res = _run(["AAPL"], [12.0], classes={"AAPL": "us_equity"}, scenario="pesimista",
               include_scenarios=True, target_value=1_600.0)
    assert set(res.scenarios) == {"pesimista", "central", "optimista"}
    for name, pct in (("pesimista", 4.2), ("central", 6.7), ("optimista", 9.1)):
        assert res.scenarios[name]["median_terminal"] == pytest.approx(_terminal(pct), rel=1e-9)
        assert res.scenarios[name]["p10_terminal"] == pytest.approx(_terminal(pct), rel=1e-9)
    # El principal es el de planificación, el mismo número.
    assert res.scenarios["pesimista"]["median_terminal"] == res.median_terminal
    # 1.000 · 1,042^10 = 1.509 < 1.600 < 1.913 = 1.000 · 1,067^10
    assert res.scenarios["pesimista"]["prob_achieve_target_pct"] == 0.0
    assert res.scenarios["central"]["prob_achieve_target_pct"] == 100.0


def test_without_the_flag_there_are_no_scenarios(fuentes_fijas):
    res = _run(["AAPL"], [12.0], classes={"AAPL": "us_equity"})
    assert res.scenarios == {}


# --------------------------------------------------------------------------- #
#  El Escenario de planificación es Postura del Perfil                         #
# --------------------------------------------------------------------------- #

def test_planning_scenario_by_profile():
    from data.product_ux import profile_planning_scenario

    assert profile_planning_scenario("conservative") == "pesimista"
    assert profile_planning_scenario("moderate") == "central"
    assert profile_planning_scenario("aggressive") == "central"
    assert profile_planning_scenario("aggressive", "pesimista") == "pesimista"   # el usuario
    assert profile_planning_scenario(None) is None                               # sin Postura
    assert profile_planning_scenario(None, "optimista") is None
    assert profile_planning_scenario("moderate", "realista") == "central"        # basura → Perfil


def test_preferences_keep_the_override():
    from data.preferences import UserPreferences

    p = UserPreferences()
    assert p.planning_scenario is None
    p.planning_scenario = "optimista"
    from dataclasses import asdict

    assert UserPreferences._from_raw(asdict(p)).planning_scenario == "optimista"


def test_the_optimizer_does_not_read_the_scenario():
    import inspect

    from portfolio.optimizer import PortfolioOptimizer

    assert "scenario" not in inspect.signature(PortfolioOptimizer).parameters
    assert "scenario" not in inspect.getsource(PortfolioOptimizer._estimation_returns)


def test_a_saved_plan_carries_its_scenario():
    from types import SimpleNamespace

    from data.plan_store import PlanSnapshot

    mc = SimpleNamespace(median_terminal=1.0, p10_terminal=1.0, p90_terminal=1.0,
                         prob_achieve_target_pct=50.0, prob_ruin_pct=0.0, median_cagr_pct=1.0,
                         scenario="pesimista", estimations=[])
    snap = PlanSnapshot.from_session(name="x", opt_result=None, mc_result=mc,
                                     mc_params={"horizon_years": 10})
    assert snap.mc_summary["scenario"] == "pesimista"


def test_a_projection_names_its_scenario_and_an_old_plan_says_so():
    from data.product_ux import projection_scenario_label

    assert projection_scenario_label("pesimista") == "Escenario pesimista"
    assert "anterior a EO-4c" in projection_scenario_label(None)


# --------------------------------------------------------------------------- #
#  Contratos                                                                   #
# --------------------------------------------------------------------------- #

def _calls_missing(names: set, kwarg: str) -> list:
    missing = []
    for folder in ("analysis", "dashboard", "portfolio", "reports", "data", "alerts"):
        for path in (ROOT / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in names and kwarg not in {k.arg for k in node.keywords}:
                    missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return missing


def test_every_app_simulator_and_planner_passes_the_scenario():
    """Uno olvidado le daría el central a un Conservador en silencio (el modo de falla de EO-4a)."""
    assert _calls_missing({"MonteCarloSimulator", "GoalPlanner"}, "scenario") == []


def test_every_cached_projection_passes_the_scenario():
    assert _calls_missing({"cached_monte_carlo", "cached_goal_simulation",
                           "cached_goal_savings_target"}, "scenario") == []


def test_engine_version_moves():
    from config import ENGINE_VERSION

    assert ENGINE_VERSION >= "2026.10-tier22"
