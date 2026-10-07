"""Oráculo EO-4c-2: la UI de Escenarios.

Decisiones del usuario (2026-10-07):

- el p10 y el p90 de una proyección se llaman «Mala racha (p10)» y «Buena racha
  (p90)»: «pesimista» y «optimista» quedan sólo para los Escenarios, que son el
  Desacuerdo entre Fuentes (ADR 0001). Hasta acá los dos significados convivían en
  la misma pantalla («Escenario pesimista (P10)» al lado de la Postura «Escenario
  pesimista»);
- la pestaña Monte Carlo muestra un bloque «Tres Escenarios» en lugar de «Dos
  referencias», y una pestaña «Escenarios» reemplaza a «Comparar perfiles» y sus
  escalas sin Fuente (``_PROFILE_MC_SCALES``);
- los dos Escenarios que no se planifican corren con
  ``MONTE_CARLO.scenario_side_sims`` simulaciones y lo dicen;
- la historia reciente deja de ser una proyección (``realistic_*``): es una de las
  Fuentes de cada Clase, en «Supuestos».
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
SIM_PAGE = ROOT / "dashboard" / "views" / "7_Simulaciones.py"
CENTRALS = {"us_equity": 6.7, "us_bonds": 4.88, "crypto": None}
RANGES = {"us_equity": (4.2, 9.1), "us_bonds": (4.0, 5.5), "crypto": (None, None)}
_RAW_DOLLAR = re.compile(r"(?<!\\)\$")


def _flat(annual_pct, n=520):
    w = (1 + annual_pct / 100) ** (1 / 52) - 1
    prices = 100.0 * np.cumprod(np.full(n, 1.0 + w))
    return pd.DataFrame({"close": prices}, index=pd.date_range("2016-01-03", periods=n, freq="W"))


@pytest.fixture
def fuentes_fijas(monkeypatch):
    import analysis.estimacion as est

    monkeypatch.setattr(est, "class_centrals", lambda: dict(CENTRALS))
    monkeypatch.setattr(est, "class_ranges", lambda: dict(RANGES))
    monkeypatch.setattr(est, "inflation_pct", lambda: 2.36)


# --------------------------------------------------------------------------- #
#  Motor                                                                       #
# --------------------------------------------------------------------------- #

def test_the_recent_history_is_no_longer_a_projection():
    from portfolio.monte_carlo import MonteCarloResult, MonteCarloSimulator

    fields = MonteCarloResult.__dataclass_fields__
    assert not [f for f in fields if f.startswith("realistic")]
    assert "include_realistic_reference" not in inspect.signature(MonteCarloSimulator.run).parameters


def test_side_scenarios_use_fewer_sims_and_say_how_many(fuentes_fijas, monkeypatch):
    from config import MONTE_CARLO
    from portfolio.monte_carlo import MonteCarloSimulator

    monkeypatch.setattr(MONTE_CARLO, "scenario_side_sims", 30)
    sim = MonteCarloSimulator(["AAPL"], seed=3, asset_classes={"AAPL": "us_equity"},
                              scenario="pesimista")
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda s, **k: _flat(12.0)):
        res = sim.run(horizon_years=10, n_sims=50, initial_value=1_000.0, include_scenarios=True)
    assert res.scenarios["pesimista"]["n_sims"] == 50          # el de la Postura: la corrida
    assert res.scenarios["central"]["n_sims"] == 30
    assert res.scenarios["optimista"]["n_sims"] == 30
    # Con historia constante el terminal no depende de cuántas simulaciones.
    assert res.scenarios["optimista"]["median_terminal"] == pytest.approx(
        1_000 * 1.091 ** 10, rel=1e-9)


def test_the_side_count_lives_in_config():
    from config import MONTE_CARLO

    assert 0 < MONTE_CARLO.scenario_side_sims < MONTE_CARLO.default_n_sims


# --------------------------------------------------------------------------- #
#  Rótulos                                                                     #
# --------------------------------------------------------------------------- #

def test_the_percentile_labels():
    from data.product_ux import BAD_RUN_LABEL, GOOD_RUN_LABEL

    assert BAD_RUN_LABEL == "Mala racha (p10)"
    assert GOOD_RUN_LABEL == "Buena racha (p90)"


def _scenarios():
    return {
        "pesimista": {"median_terminal": 900_000.0, "p10_terminal": 400_000.0,
                      "p90_terminal": 1_900_000.0, "prob_achieve_target_pct": 60.0, "n_sims": 10_000},
        "central": {"median_terminal": 1_200_000.0, "p10_terminal": 550_000.0,
                    "p90_terminal": 2_500_000.0, "prob_achieve_target_pct": 75.0, "n_sims": 2_000},
        "optimista": {"median_terminal": 1_600_000.0, "p10_terminal": 700_000.0,
                      "p90_terminal": 3_300_000.0, "prob_achieve_target_pct": 85.0, "n_sims": 2_000},
    }


def test_the_block_shows_the_three_and_marks_the_planning_one():
    from data.product_ux import scenarios_block_text

    text = scenarios_block_text(_scenarios(), "pesimista")
    for name in ("Pesimista", "Central", "Optimista"):
        assert name in text
    assert "900,000" in text and "1,200,000" in text and "1,600,000" in text
    line = [ln for ln in text.splitlines() if "Pesimista" in ln][0]
    assert "tu Postura" in line and "10,000 simulaciones" in line
    assert "2,000 simulaciones" in text
    assert "Fuentes" in text and "Supuestos" in text            # la historia, como Fuente
    assert not _RAW_DOLLAR.search(text), "`$` sin escapar (KaTeX)"
    assert scenarios_block_text({}, "central") == ""


# --------------------------------------------------------------------------- #
#  La página                                                                   #
# --------------------------------------------------------------------------- #

def _fake_mc(*, with_scenarios: bool = True):
    from portfolio.monte_carlo import MonteCarloResult

    horizon = 20
    mc = MonteCarloResult(n_sims=100, horizon_years=horizon, initial_value=100_000.0,
                          annual_withdrawal=0.0, target_value=0.0)
    mc.median_terminal, mc.p10_terminal, mc.p90_terminal = 900_000.0, 400_000.0, 1_900_000.0
    mc.p25_terminal, mc.p75_terminal = 650_000.0, 1_300_000.0
    mc.median_cagr_pct = 6.7
    mc.years = list(range(horizon + 1))
    mc.fan_paths = {y: {p: 100_000.0 * ((1 + p / 1000) ** y) for p in (5, 10, 25, 50, 75, 90, 95)}
                    for y in range(horizon + 1)}
    mc.scenario = "pesimista"
    if with_scenarios:
        mc.scenarios = _scenarios()
    return mc


def _page(mc):
    at = AppTest.from_file(str(SIM_PAGE), default_timeout=120)
    at.session_state["mc_result"] = mc
    at.run()
    assert not at.exception, [str(e)[:400] for e in at.exception]
    return at


def test_the_monte_carlo_tab_draws_three_scenarios_not_two_references():
    at = _page(_fake_mc())
    infos = [i.value or "" for i in at.info]
    assert not [t for t in infos if "Dos referencias" in t]
    [block] = [t for t in infos if "Tres Escenarios" in t]
    assert not _RAW_DOLLAR.search(block)
    labels = [m.label for m in at.metric]
    assert "Mala racha (p10)" in labels and "Buena racha (p90)" in labels
    assert not [lb for lb in labels if re.search(r"pesimista|optimista", lb, re.I)]


def test_the_profiles_tab_is_replaced_by_scenarios():
    at = _page(_fake_mc())
    tabs = [t.label for t in at.tabs]
    assert any("Escenarios" in t for t in tabs)
    assert not any("Comparar Perfiles" in t for t in tabs)
    src = SIM_PAGE.read_text(encoding="utf-8")
    assert "_PROFILE_MC_SCALES" not in src


# --------------------------------------------------------------------------- #
#  El plan guardado                                                            #
# --------------------------------------------------------------------------- #

def test_a_saved_plan_keeps_the_three():
    from data.plan_store import PlanSnapshot

    snap = PlanSnapshot.from_session(name="x", opt_result=None, mc_result=_fake_mc(),
                                     mc_params={"horizon_years": 20})
    assert set(snap.mc_summary["scenarios"]) == {"pesimista", "central", "optimista"}
    assert snap.mc_summary["scenarios"]["central"]["median_terminal"] == 1_200_000.0


# --------------------------------------------------------------------------- #
#  Contrato: un percentil nunca se llama «pesimista»/«optimista»               #
# --------------------------------------------------------------------------- #

USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "reports").rglob("*.py")),
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
    "data/product_ux.py",
]
_ADJ = r"(pesimista|optimista|muy bueno)"
_PCT = r"(p10|p90|1 de cada 10|peor 10|mejor 10|o menos\b|o más\b)"
_MIXED = re.compile(rf"{_ADJ}.{{0,25}}{_PCT}|{_PCT}.{{0,8}}{_ADJ}", re.I)


def _offenders():
    out = []
    for rel in USER_FACING:
        for n, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            if _MIXED.search(line):
                out.append(f"{rel}:{n}: {line.strip()}")
    return out


def test_no_surface_calls_a_percentile_pessimistic():
    assert _offenders() == []


def test_the_sweep_catches_what_it_says():
    assert _MIXED.search('"⚠️ Escenario pesimista (peor 10%)"')
    assert _MIXED.search('rows.append(["Escenario optimista (P90)", x])')
    assert _MIXED.search("- Escenario muy bueno (1 de cada 10 casos)")
    assert _MIXED.search("- Escenario pesimista: **$x** o menos")
    assert not _MIXED.search("Cripto se proyecta a 0 % real, el escenario pesimista.")
    assert not _MIXED.search('"Pesimista y optimista ponen cada Clase de activo en la Fuente más baja"')


def test_no_app_code_reads_the_recent_history_projection():
    hits = []
    for folder in ("analysis", "dashboard", "portfolio", "reports", "data", "alerts"):
        for p in (ROOT / folder).rglob("*.py"):
            if "realistic_" in p.read_text(encoding="utf-8"):
                hits.append(str(p.relative_to(ROOT)))
    assert hits == []
