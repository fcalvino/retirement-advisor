"""Oráculo EO-4d: el riesgo país de Argentina entra a la Estimación de sus ADRs (ADR 0001).

Decisiones del usuario (2026-10-05 y 2026-10-07):

- el μ de un ADR argentino es la Estimación de su Clase menos el riesgo país en pp
  (655 pb = 6,55 pp), sin bajar del 0 % real (la inflación implícita);
- es un dato citado, no Desacuerdo: igual en los tres Escenarios;
- el dato «vieja» (más de 12 meses) se usa y se rotula; «fuera» (más de 24) o ausente
  no se resta y se avisa;
- con haircut (sin Clase o Clase sin Fuentes) no se resta: su historia ya trae el
  riesgo realizado, y se avisa;
- se va ``OPTIMIZER.ars_risk_discount``: el score ya no se descuenta por ser argentino.

Cuentas a mano con las Fuentes de hoy: emergentes 7,225 − 6,55 = 0,675 < 2,36 de
inflación, así que el piso manda y el ADR queda en 2,36 (0 % real). Con un spread de
300 pb: 7,225 − 3,00 = 4,225, sin piso.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from analysis.estimacion import (
    HAIRCUT,
    OBJETIVA,
    asset_estimations,
    country_warnings,
    estimate_asset,
)
from analysis.fuentes import CountryRisk

TODAY = date(2026, 10, 7)
CENTRALS = {"us_equity": 6.7, "developed_ex_us": 6.65, "emerging": 7.225,
            "us_bonds": 4.88, "reits": 8.72, "crypto": None}
INFLATION = 2.36


def _risk(bp=655, as_of=date(2026, 10, 2)):
    return {"Argentina": CountryRisk(country="Argentina", value_bp=bp, as_of=as_of,
                                     source="https://x.org")}


def _est(symbol="YPF", cls="emerging", *, country="Argentina", risks=None, centrals=None,
         scenario="central"):
    return estimate_asset(symbol, cls, centrals=centrals or CENTRALS, inflation=INFLATION,
                          scenario=scenario, country=country,
                          country_risks=_risk() if risks is None else risks, today=TODAY)


# --------------------------------------------------------------------------- #
#  La regla                                                                    #
# --------------------------------------------------------------------------- #

def test_the_floor_binds_with_todays_numbers():
    e = _est()
    assert e.mode == OBJETIVA
    assert e.annual_pct == pytest.approx(2.36)                  # max(7,225 − 6,55; 2,36)
    assert e.country_adj_pp == pytest.approx(7.225 - 2.36)
    assert "bajo el piso de 0 % real" in e.label and "655 pb" in e.label and "6.55 pp" in e.label


def test_a_smaller_spread_subtracts_pp_by_pp():
    e = _est(risks=_risk(300))
    assert e.annual_pct == pytest.approx(4.225)                 # 7,225 − 3,00
    assert e.country_adj_pp == pytest.approx(3.0)
    assert "piso" not in e.label


def test_a_non_argentine_issuer_keeps_its_class_estimation():
    e = _est("EEE", country="Brazil")
    assert e.annual_pct == pytest.approx(7.225) and e.country_adj_pp == 0.0
    assert e.country_note == ""


def test_a_row_without_country_is_not_assumed_argentine():
    assert _est(country=None).annual_pct == pytest.approx(7.225)


def test_the_discount_is_the_same_in_the_three_scenarios():
    pes = _est(risks=_risk(300), scenario="pesimista",
               centrals={**CENTRALS, "emerging": 3.0})
    opt = _est(risks=_risk(300), scenario="optimista",
               centrals={**CENTRALS, "emerging": 8.8})
    assert opt.country_adj_pp == pytest.approx(3.0)
    assert pes.annual_pct == pytest.approx(max(3.0 - 3.0, INFLATION))   # piso
    assert opt.annual_pct == pytest.approx(8.8 - 3.0)


# --------------------------------------------------------------------------- #
#  Antigüedad del dato                                                         #
# --------------------------------------------------------------------------- #

def test_an_old_datum_is_used_and_labelled():
    e = _est(risks=_risk(300, as_of=date(2025, 9, 1)))          # 13 meses: vieja
    assert e.annual_pct == pytest.approx(4.225)
    assert "dato viejo" in e.country_note


@pytest.mark.parametrize("risks", [_risk(300, as_of=date(2024, 9, 1)), {}],
                         ids=["fuera", "ausente"])
def test_a_stale_or_missing_datum_is_not_subtracted_and_says_so(risks):
    e = _est(risks=risks)                                        # fuera: 25 meses
    assert e.annual_pct == pytest.approx(7.225) and e.country_adj_pp == 0.0
    assert "no lo descuenta" in e.country_note


# --------------------------------------------------------------------------- #
#  Haircut: no se resta, se avisa                                              #
# --------------------------------------------------------------------------- #

def test_a_haircut_adr_is_not_discounted_and_is_named(monkeypatch):
    import analysis.estimacion as est

    monkeypatch.setattr(est, "class_estimates", lambda scenario="central": dict(CENTRALS))
    monkeypatch.setattr(est, "inflation_pct", lambda: INFLATION)
    monkeypatch.setattr(est, "country_risks", lambda: _risk())
    (e,) = asset_estimations(["YPF"], {"YPF": None}, countries={"YPF": "Argentina"})
    assert e.mode == HAIRCUT and e.annual_pct is None and e.country_adj_pp == 0.0
    assert any("YPF" in w and "no se resta" in w for w in country_warnings([e]))


# --------------------------------------------------------------------------- #
#  Optimizer y Monte Carlo dicen el mismo número                               #
# --------------------------------------------------------------------------- #

@pytest.fixture
def fuentes_fijas(monkeypatch):
    import analysis.estimacion as est

    monkeypatch.setattr(est, "class_estimates", lambda scenario="central": dict(CENTRALS))
    monkeypatch.setattr(est, "inflation_pct", lambda: INFLATION)
    monkeypatch.setattr(est, "country_risks", lambda: _risk(300))


def _flat(annual_pct, n=520):
    w = (1 + annual_pct / 100) ** (1 / 52) - 1
    return pd.DataFrame({"close": 100.0 * np.cumprod(np.full(n, 1.0 + w))},
                        index=pd.date_range("2016-01-03", periods=n, freq="W"))


def test_the_optimizer_mu_of_an_argentine_adr_is_the_discounted_estimation(fuentes_fijas):
    from portfolio.optimizer import PortfolioOptimizer

    rows = [{"symbol": "YPF", "country": "Argentina"}, {"symbol": "KO", "country": "United States"}]
    classes = {"YPF": "emerging", "KO": "us_equity"}
    prices = pd.DataFrame({s: _flat(5.0)["close"] for s in ("YPF", "KO")})
    mu = PortfolioOptimizer("aggressive", asset_classes=classes)._estimation_returns(rows, prices)
    assert mu[0] == pytest.approx(0.04225)       # 7,225 − 3,00
    assert mu[1] == pytest.approx(0.067)         # sin cambio: no es argentina


def test_the_optimizer_result_says_what_it_subtracted(fuentes_fijas):
    from portfolio.optimizer import OptimizationResult, PortfolioOptimizer

    rows = [{"symbol": "YPF", "country": "Argentina"}]
    prices = pd.DataFrame({"YPF": _flat(5.0)["close"]})
    res = OptimizationResult(profile_name="aggressive", method="mean-variance")
    PortfolioOptimizer("aggressive", asset_classes={"YPF": "emerging"})._estimation_returns(
        rows, prices, res)
    assert any("YPF" in w and "riesgo país de Argentina 300 pb" in w for w in res.warnings)
    assert not any("llega con EO-4d" in w for w in res.warnings)
    assert res.estimations[0]["country_adj_pp"] == pytest.approx(3.0)


def test_the_monte_carlo_projects_the_same_discounted_number(fuentes_fijas):
    from unittest.mock import patch

    from portfolio.monte_carlo import MonteCarloSimulator

    sim = MonteCarloSimulator(["YPF"], seed=3, asset_classes={"YPF": "emerging"},
                              countries={"YPF": "Argentina"})
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda s, **k: _flat(15.0)):
        res = sim.run(horizon_years=10, n_sims=50, initial_value=1_000.0)
    assert res.median_terminal == pytest.approx(1_000 * 1.04225 ** 10, rel=1e-9)
    assert any("riesgo país de Argentina" in w for w in res.warnings)


def test_without_countries_the_monte_carlo_is_unchanged(fuentes_fijas):
    from unittest.mock import patch

    from portfolio.monte_carlo import MonteCarloSimulator

    sim = MonteCarloSimulator(["YPF"], seed=3, asset_classes={"YPF": "emerging"})
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda s, **k: _flat(15.0)):
        res = sim.run(horizon_years=10, n_sims=50, initial_value=1_000.0)
    assert res.median_terminal == pytest.approx(1_000 * 1.07225 ** 10, rel=1e-9)


# --------------------------------------------------------------------------- #
#  Contratos                                                                   #
# --------------------------------------------------------------------------- #

def test_the_score_discount_and_its_config_knob_are_gone():
    import portfolio.optimizer as opt_mod
    from config import OPTIMIZER

    assert not hasattr(OPTIMIZER, "ars_risk_discount")
    assert not hasattr(opt_mod.PortfolioOptimizer, "_apply_ars_discount")
    assert "score_discounted" not in opt_mod.TickerAllocation.__dataclass_fields__


def test_every_app_simulator_passes_countries():
    """Un simulador de la app sin países proyectaría YPF en el central de emergentes."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    missing = []
    for folder in ("analysis", "dashboard", "portfolio", "reports", "data", "alerts"):
        for path in (root / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if (name in ("MonteCarloSimulator", "GoalPlanner")
                        and "countries" not in {k.arg for k in node.keywords}):
                    missing.append(f"{path.relative_to(root)}:{node.lineno}")
    assert missing == []


def test_engine_version_moves():
    from config import ENGINE_VERSION

    assert ENGINE_VERSION >= "2026.10-tier23"


def test_equal_notes_are_grouped_in_one_warning():
    a, b = _est("YPF"), _est("TEO")
    (line,) = country_warnings([a, b, _est("KO", "us_equity", country="United States")])
    assert line.startswith("YPF, TEO: riesgo país de Argentina")
