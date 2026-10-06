"""Oráculo EO-4a: el Monte Carlo se recentra en la Estimación objetiva de cada Clase.

Antes, ``_conservative_adjustment`` aplicaba a la cartera entera ``(r − m)·1,10 +
m·0,80``: un −20 % al rendimiento sin Fuente. Decisiones del usuario (2026-10-05):

- acciones EE.UU.: Estimación objetiva (calibrada en EO-3);
- bonos EE.UU.: conservan el haircut, rotulado «no calibrado»;
- ex-EE.UU., emergentes y REITs: Estimación objetiva, rotulada «no calibrable»;
- cripto: 0 % real (el pesimista): en nominal, la inflación implícita;
- un ticker sin Clase: haircut sobre su historia, y se lo nombra.

El recentrado es compuesto, el contrato que pasó EO-3: se demean los
log-rendimientos semanales y se suma ``log(1 + E) / 52``. Con una historia de
rendimiento constante no hay desvíos, así que el camino es determinístico y el
terminal sale a mano.
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
    monkeypatch.setattr(est, "inflation_pct", lambda: INFLATION)


def _run(symbols, rates, *, weights=None, classes=None):
    from portfolio.monte_carlo import MonteCarloSimulator

    hist = {s: _flat(r) for s, r in zip(symbols, rates)}
    sim = MonteCarloSimulator(symbols, weights=weights, seed=3, asset_classes=classes)
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda s, **k: hist[s]):
        return sim.run(horizon_years=YEARS, n_sims=50, initial_value=1_000.0)


# --------------------------------------------------------------------------- #
#  El recentrado compuesto                                                     #
# --------------------------------------------------------------------------- #

def test_us_equity_projects_its_estimation_not_its_history(fuentes_fijas):
    # La historia rindió 15 %; la Estimación de la Clase es 6,7 %: 1,067¹⁰ × 1.000.
    res = _run(["AAPL"], [15.0], classes={"AAPL": "us_equity"})
    assert res.median_terminal == pytest.approx(1_000 * 1.067 ** YEARS, rel=1e-9)
    (e,) = res.estimations
    assert (e["symbol"], e["asset_class"], e["mode"]) == ("AAPL", "us_equity", "objetiva")
    assert "calibrada" in e["label"]


def test_a_mixed_portfolio_recentres_on_the_weighted_estimation(fuentes_fijas):
    res = _run(["AAPL", "TSM"], [15.0, -3.0], weights=np.array([0.5, 0.5]),
               classes={"AAPL": "us_equity", "TSM": "emerging"})
    # La cartera rinde el promedio ponderado de las Estimaciones: 0,5·6,7 + 0,5·7,225.
    assert res.median_terminal == pytest.approx(1_000 * 1.069625 ** YEARS, rel=1e-9)
    assert {e["symbol"]: e["label"] for e in res.estimations}["TSM"].endswith("no calibrable")


def test_bonds_keep_the_haircut_on_their_own_history(fuentes_fijas):
    from config import MONTE_CARLO

    res = _run(["BND"], [4.0], classes={"BND": "us_bonds"})
    w = _weekly(4.0) * MONTE_CARLO.mean_haircut          # sin desvíos: sólo el haircut
    assert res.median_terminal == pytest.approx(1_000 * (1 + w) ** 520, rel=1e-9)
    (e,) = res.estimations
    assert e["mode"] == "haircut" and "no calibrado" in e["label"]


def test_crypto_projects_zero_real_that_is_the_breakeven(fuentes_fijas):
    res = _run(["BTC-USD"], [60.0], classes={"BTC-USD": "crypto"})
    assert res.median_terminal == pytest.approx(1_000 * 1.0236 ** YEARS, rel=1e-9)


def test_a_ticker_without_class_keeps_the_haircut_and_is_named(fuentes_fijas):
    from config import MONTE_CARLO

    res = _run(["XYZ"], [8.0], classes={"XYZ": None})
    w = _weekly(8.0) * MONTE_CARLO.mean_haircut
    assert res.median_terminal == pytest.approx(1_000 * (1 + w) ** 520, rel=1e-9)
    assert any("XYZ" in msg and "sin Clase" in msg for msg in res.warnings)


def test_a_class_without_current_sources_falls_back_to_the_haircut(monkeypatch):
    import analysis.estimacion as est
    from config import MONTE_CARLO

    monkeypatch.setattr(est, "class_centrals", lambda: {**CENTRALS, "reits": None})
    monkeypatch.setattr(est, "inflation_pct", lambda: INFLATION)
    res = _run(["O"], [8.0], classes={"O": "reits"})
    w = _weekly(8.0) * MONTE_CARLO.mean_haircut
    assert res.median_terminal == pytest.approx(1_000 * (1 + w) ** 520, rel=1e-9)
    assert "sin Fuentes vigentes" in res.estimations[0]["label"]


def test_volatile_stocks_do_not_project_above_their_estimation(fuentes_fijas):
    """La QA en vivo: tres acciones volátiles, recentradas una por una, daban 8,3 %/año
    sobre una Estimación de 6,7 %. Recentrada la cartera, la mediana es la Estimación."""
    from portfolio.monte_carlo import MonteCarloSimulator

    rng = np.random.default_rng(9)
    idx = pd.date_range("2016-01-03", periods=520, freq="W")
    hist = {s: pd.DataFrame({"close": 100.0 * np.cumprod(1 + rng.normal(0.004, 0.045, 520))},
                            index=idx) for s in ("GOOGL", "INTU", "ADBE")}
    sim = MonteCarloSimulator(list(hist), seed=3,
                              asset_classes={s: "us_equity" for s in hist})
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda s, **k: hist[s]):
        res = sim.run(horizon_years=YEARS, n_sims=4000, initial_value=1_000.0)
    assert (res.median_terminal / 1_000) ** (1 / YEARS) - 1 == pytest.approx(0.067, abs=0.004)


def test_the_band_is_log_symmetric_around_the_estimation(fuentes_fijas):
    from portfolio.monte_carlo import MonteCarloSimulator

    rng = np.random.default_rng(5)
    prices = 100.0 * np.cumprod(1 + rng.normal(0.003, 0.03, 520))
    noisy = pd.DataFrame({"close": prices},
                         index=pd.date_range("2016-01-03", periods=520, freq="W"))
    sim = MonteCarloSimulator(["AAPL"], seed=3, asset_classes={"AAPL": "us_equity"})
    with patch("portfolio.monte_carlo.get_history", side_effect=lambda s, **k: noisy):
        res = sim.run(horizon_years=YEARS, n_sims=4000, initial_value=1_000.0)
    # Compuesto: la mediana rinde la Estimación (no ~1 pp más, como el aritmético).
    assert (res.median_terminal / 1_000) ** (1 / YEARS) - 1 == pytest.approx(0.067, abs=0.006)


# --------------------------------------------------------------------------- #
#  Sin Clases: el motor de antes, sin mover un float                           #
# --------------------------------------------------------------------------- #

def test_without_classes_the_engine_is_the_old_one_and_says_so():
    from config import MONTE_CARLO

    res = _run(["AAPL"], [7.0], classes=None)
    w = _weekly(7.0) * MONTE_CARLO.mean_haircut
    assert res.median_terminal == pytest.approx(1_000 * (1 + w) ** 520, rel=1e-12)
    assert res.estimations == []
    assert any("sin Clases" in msg for msg in res.warnings)


# --------------------------------------------------------------------------- #
#  Contratos                                                                   #
# --------------------------------------------------------------------------- #

def test_every_app_simulator_passes_asset_classes():
    """Un simulador de la app sin Clases proyectaría con el haircut en silencio."""
    missing = []
    for folder in ("analysis", "dashboard", "portfolio", "reports", "data", "alerts"):
        for path in (ROOT / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and getattr(node.func, "id", None)
                        == "MonteCarloSimulator"
                        and "asset_classes" not in {k.arg for k in node.keywords}):
                    missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert missing == []


def test_the_shipped_file_carries_the_breakeven_for_crypto():
    from analysis.fuentes import load_shipped_inflation

    infl = load_shipped_inflation()
    assert infl["series"] == "T10YIE" and 0 < infl["value_pct"] < 10
    assert infl["as_of"] and infl["source"].startswith("https://fred.stlouisfed.org")


def test_the_caption_says_where_each_number_comes_from():
    from data.product_ux import estimation_caption

    ests = [
        {"symbol": "GOOGL", "mode": "objetiva", "label": "Acciones EE.UU. 6.7% · calibrada"},
        {"symbol": "INTU", "mode": "objetiva", "label": "Acciones EE.UU. 6.7% · calibrada"},
        {"symbol": "BND", "mode": "haircut", "label": "Bonos EE.UU.: … no calibrado"},
    ]
    text = estimation_caption(ests)
    assert "Acciones EE.UU. 6.7% · calibrada (GOOGL, INTU)" in text
    assert "ajuste histórico" in text and "BND" in text and "Supuestos" in text
    assert estimation_caption([]) == ""


def test_engine_version_moves():
    from config import ENGINE_VERSION

    assert ENGINE_VERSION == "2026.10-tier20"
