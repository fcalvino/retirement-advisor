"""Oráculo EO-4b: el Optimizer usa la misma Estimación objetiva por Clase que el Monte Carlo.

Antes, el μ de cada activo era un proxy —``score/100 × 0,18`` mezclado con el
dividendo, más el tilt de tailwind, con techo en ``er_absolute_cap``— y encima el
posterior de Black-Litterman, con la confianza de cada view tomada del score. U6-1
midió que ese número ordena pero no cotiza. Decisiones del usuario (2026-10-05 y
2026-10-06):

- el μ de cada activo es la Estimación de su Clase (``analysis.estimacion``), las
  mismas reglas que EO-4a: acciones EE.UU. calibrada; ex-EE.UU., emergentes y REITs
  «no calibrable»; cripto 0 % real (la inflación implícita);
- bonos EE.UU., un ticker sin Clase y una Clase sin Fuentes vigentes conservan el
  haircut sobre su propia historia, igual que en el Monte Carlo:
  ``(1 + media semanal × mean_haircut)^52 − 1``;
- sin contracción por score (opción a): el score ya no mueve μ, ni por la view ni
  por la confianza de Black-Litterman, que en este camino no corre;
- sin Clases el motor queda byte-idéntico al de antes y lo avisa.

La comprobación que discrimina: el ``expected_return_pct`` de la cartera es el
promedio ponderado de las Estimaciones, el mismo número en el que EO-4a recentra el
Monte Carlo.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import portfolio.optimizer as opt_mod
from config import MONTE_CARLO
from portfolio.optimizer import PortfolioOptimizer

ROOT = Path(__file__).resolve().parents[1]
CENTRALS = {"us_equity": 6.7, "developed_ex_us": 6.65, "emerging": 7.225,
            "us_bonds": 4.88, "reits": 8.72, "crypto": None}
INFLATION = 2.36
N = 260  # cinco años semanales: cubre price_history_years


def _frame(seed: int, drift: float, vol: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    r = drift + vol * rng.standard_normal(N)
    idx = pd.date_range(end=pd.Timestamp("2026-10-05"), periods=N, freq="W-MON")
    return pd.DataFrame({"close": 100.0 * np.cumprod(1.0 + r)}, index=idx)


PRICES = {
    "AAA": _frame(1, 0.0030, 0.030),
    "BBB": _frame(2, 0.0020, 0.025),
    "CCC": _frame(3, 0.0015, 0.020),
    "BNDX1": _frame(4, 0.0006, 0.005),
    "ZZZ": _frame(5, 0.0025, 0.035),
    "EEE": _frame(6, 0.0010, 0.028),
}


def _row(sym, score, *, div=2.5, sector="Technology", country="United States"):
    return {"symbol": sym, "adjusted_score": score, "dividend_yield": div,
            "moat_score": 10.0, "sector": sector, "country": country,
            "currency": "USD", "data_quality_level": "good", "market_cap": 1e11}


ROWS = [_row("AAA", 90), _row("BBB", 60, sector="Healthcare"),
        _row("CCC", 40, sector="Consumer Defensive"),
        _row("BNDX1", 50, div=3.5, sector="Utilities"),
        _row("ZZZ", 70, sector="Industrials"),
        _row("EEE", 55, sector="Financial Services", country="Brazil")]
CLASSES = {"AAA": "us_equity", "BBB": "us_equity", "CCC": "us_equity",
           "BNDX1": "us_bonds", "ZZZ": None, "EEE": "emerging"}


@pytest.fixture
def stub(monkeypatch):
    import analysis.estimacion as est

    monkeypatch.setattr(est, "class_centrals", lambda: dict(CENTRALS))
    monkeypatch.setattr(est, "inflation_pct", lambda: INFLATION)
    monkeypatch.setattr(opt_mod, "get_history",
                        lambda s, **k: PRICES.get(s, pd.DataFrame()).copy())


def _haircut_mu(sym: str, years: int) -> float:
    """El haircut del Monte Carlo sobre la misma ventana que lee el Optimizer."""
    weekly = PRICES[sym]["close"].pct_change().dropna()
    return (1.0 + weekly.mean() * MONTE_CARLO.mean_haircut) ** 52 - 1.0


def _optimize(classes, profile="aggressive"):
    opt = PortfolioOptimizer(profile, asset_classes=classes)
    return opt, opt.optimize([dict(r) for r in ROWS])


# --------------------------------------------------------------------------- #
#  μ por activo                                                                #
# --------------------------------------------------------------------------- #

def test_each_asset_gets_its_class_estimation_or_its_haircut(stub):
    opt, res = _optimize(CLASSES)
    mu = {t.symbol: t.expected_return_pct for t in res.tickers}
    years = opt.opt.price_history_years
    expected = {"AAA": 6.7, "BBB": 6.7, "CCC": 6.7, "EEE": 7.225,
                "BNDX1": _haircut_mu("BNDX1", years) * 100,
                "ZZZ": _haircut_mu("ZZZ", years) * 100}
    for sym, value in mu.items():
        assert value == pytest.approx(round(expected[sym], 1), abs=1e-9), sym


def test_the_score_no_longer_moves_mu(stub):
    """Opción (a): dos acciones EE.UU. con score 90 y 40 rinden lo mismo."""
    opt = PortfolioOptimizer("aggressive", asset_classes=CLASSES)
    rows = [r for r in ROWS if r["symbol"] in ("AAA", "CCC")]
    mu = opt._estimation_returns(rows, pd.DataFrame({s: PRICES[s]["close"] for s in ("AAA", "CCC")}))
    assert mu[0] == mu[1] == pytest.approx(0.067)


def test_the_portfolio_return_is_the_weighted_estimation(stub):
    """El mismo número en el que EO-4a recentra el Monte Carlo."""
    opt, res = _optimize(CLASSES)
    years = opt.opt.price_history_years
    by_sym = {"AAA": 0.067, "BBB": 0.067, "CCC": 0.067, "EEE": 0.07225,
              "BNDX1": _haircut_mu("BNDX1", years), "ZZZ": _haircut_mu("ZZZ", years)}
    weights = {t.symbol: t.weight_pct / 100 for t in res.tickers}
    weighted = sum(w * by_sym[s] for s, w in weights.items()) / sum(weights.values())
    assert res.method == "mean-variance"
    assert res.expected_return_pct == pytest.approx(round(weighted * 100, 1), abs=0.051)
    assert res.return_basis == "estimacion"


def test_black_litterman_does_not_run_on_the_estimation(stub, monkeypatch):
    called = []
    monkeypatch.setattr(PortfolioOptimizer, "_apply_black_litterman",
                        lambda self, mu, *a, **k: called.append(1) or mu)
    _optimize(CLASSES)
    assert called == []


def test_crypto_projects_zero_real(stub, monkeypatch):
    PRICES["BTC-USD"] = _frame(7, 0.01, 0.08)
    try:
        opt = PortfolioOptimizer("aggressive", asset_classes={"BTC-USD": "crypto"})
        mu = opt._estimation_returns([_row("BTC-USD", 50)],
                                     pd.DataFrame({"BTC-USD": PRICES["BTC-USD"]["close"]}))
    finally:
        del PRICES["BTC-USD"]
    assert mu[0] == pytest.approx(INFLATION / 100)


def test_the_result_names_each_estimation_and_the_unclassed(stub):
    _, res = _optimize(CLASSES)
    modes = {e["symbol"]: e["mode"] for e in res.estimations}
    assert modes["AAA"] == "objetiva" and modes["BNDX1"] == "haircut" and modes["ZZZ"] == "haircut"
    assert any("ZZZ" in w and "sin Clase" in w for w in res.warnings)


def test_ars_and_tailwind_are_named_while_they_wait_for_eo_4d(stub):
    rows = [dict(r) for r in ROWS] + [_row("YPF", 60, sector="Energy", country="Argentina")]
    PRICES["YPF"] = _frame(8, 0.002, 0.04)
    try:
        res = PortfolioOptimizer("aggressive",
                                 asset_classes={**CLASSES, "YPF": "emerging"}).optimize(rows)
    finally:
        del PRICES["YPF"]
    assert any("riesgo argentino" in w and "EO-4d" in w for w in res.warnings)


# --------------------------------------------------------------------------- #
#  Sin Clases: el motor de antes                                               #
# --------------------------------------------------------------------------- #

def test_without_classes_the_engine_is_the_old_one_and_says_so(stub):
    res = PortfolioOptimizer("aggressive").optimize([dict(r) for r in ROWS])
    assert res.return_basis == "proxy"
    assert res.estimations == []
    assert any("sin Clases" in w for w in res.warnings)
    # El proxy: el score todavía ordena el μ.
    mu = {t.symbol: t.expected_return_pct for t in res.tickers}
    if "AAA" in mu and "CCC" in mu:
        assert mu["AAA"] > mu["CCC"]


# --------------------------------------------------------------------------- #
#  Rótulos por base                                                            #
# --------------------------------------------------------------------------- #

def test_the_label_follows_the_basis():
    from data.product_ux import expected_return_label, fmt_expected_return

    assert fmt_expected_return(6.7, "estimacion") == "6.7 %/año"
    assert fmt_expected_return(7.0, "proxy") == "50"           # 7 % / cap 14 % × 100
    assert fmt_expected_return(7.0, None) == "50"              # un plan viejo: proxy
    assert fmt_expected_return(None, "estimacion") == "—"
    assert "Estimación" in expected_return_label("estimacion")
    assert "Índice" in expected_return_label("proxy")


def test_a_saved_plan_carries_its_basis():
    from types import SimpleNamespace

    from data.plan_store import optimizer_metrics

    opt = SimpleNamespace(expected_return_pct=6.7, volatility_pct=15.0, sharpe_ratio=0.3,
                          dividend_yield_pct=1.0, moat_score_avg=10.0, adjusted_score_avg=60.0,
                          tickers=[], return_basis="estimacion", profile_name="Agresivo",
                          method="mean-variance", sector_weights={})
    metrics = optimizer_metrics(opt)
    assert metrics["return_basis"] == "estimacion"


# --------------------------------------------------------------------------- #
#  Contratos                                                                   #
# --------------------------------------------------------------------------- #

def test_every_app_optimizer_passes_asset_classes():
    """Un Optimizer de la app sin Clases optimizaría el proxy en silencio."""
    missing = []
    for folder in ("analysis", "dashboard", "portfolio", "reports", "data", "alerts"):
        for path in (ROOT / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if (name == "PortfolioOptimizer"
                        and "asset_classes" not in {k.arg for k in node.keywords}):
                    missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert missing == []


def test_engine_version_moves():
    from config import ENGINE_VERSION

    assert ENGINE_VERSION == "2026.10-tier21"
