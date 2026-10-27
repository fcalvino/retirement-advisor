"""AUDIT-OPTIMIZER-LIMITES — el respaldo score-weighted y la frontera respetan los topes.

El camino SLSQP respeta el tope por posición (``max(max_position_pct/100, 1/n)``), el
de cripto y el de sector. El respaldo ``_score_weighted_optimize`` —al que se cae cuando
SLSQP no converge, y el usuario lo ve como «una cartera»— no:

* no tenía tope de sector;
* su water-filling no converge cuando ``n × tope < 1`` (con Conservador, n = 10 y scores
  desiguales devolvía [28 %, 8 %, 8 %, …]; Agresivo n = 5 daba 20,5 % contra 18 %);
* la nube de la frontera hacía ``clip`` + renormalizar, lo que vuelve a pasar el tope
  (500 de 500 muestras con n = 20 y tope 8 % lo superaban).

La referencia no es otro water-filling: es la solución cerrada del reparto proporcional con
topes, ``w_i = min(tope_i, λ·score_i)`` con ``Σ w_i = 1``, que se resuelve por bisección en λ.
"""

from __future__ import annotations

import numpy as np
import pytest

from config import OPTIMIZER_PROFILES
from portfolio.optimizer import OptimizationResult, PortfolioOptimizer

PROFILES = ["conservative", "moderate", "aggressive"]
EPS = 1e-9


def _t(symbol, score, sector=None):
    return {"symbol": symbol, "adjusted_score": score, "dividend_yield": 1.0,
            "moat_score": 5.0, "sector": sector or f"Sector-{symbol}"}


def _tickers(n, spread=1.0):
    """n tickers con scores desiguales y cada uno en su propio sector."""
    return [_t(f"T{i:02d}", 40.0 + spread * (n - i) ** 1.5) for i in range(n)]


def _reference(scores, ubs):
    """Reparto proporcional con topes por bisección: w_i = min(ub_i, λ s_i), Σ = 1."""
    scores = np.asarray(scores, float)
    ubs = np.asarray(ubs, float)
    assert ubs.sum() >= 1 - 1e-12, "el oráculo sólo vale si los topes alcanzan para sumar 1"
    lo, hi = 0.0, 1.0 / scores.min() + 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if np.minimum(ubs, mid * scores).sum() < 1:
            lo = mid
        else:
            hi = mid
    return np.minimum(ubs, hi * scores)


# --------------------------------------------------------------------------- #
#  Tope por posición                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("n", [4, 5, 8, 10, 12, 15, 25])
def test_fallback_is_the_capped_proportional_allocation(profile, n):
    opt = PortfolioOptimizer(profile)
    tickers = _tickers(n)
    w = opt._score_weighted_optimize(tickers)

    cap = OPTIMIZER_PROFILES[profile].max_position_pct / 100
    eff = max(cap, 1.0 / n)             # lo mismo que hace el SLSQP cuando n·tope < 1
    expected = _reference([t["adjusted_score"] for t in tickers], np.full(n, eff))

    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    assert np.all(w <= eff + EPS), f"{profile} n={n}: máx {w.max():.4f} > tope efectivo {eff:.4f}"
    np.testing.assert_allclose(w, expected, atol=1e-7)


def test_the_reported_bug_cases():
    """Los tres casos que reprodujo el revisor de la auditoría."""
    cons = PortfolioOptimizer("conservative")._score_weighted_optimize(_tickers(10))
    assert cons.max() <= 0.10 + EPS                      # era 28 %; 10 × 8 % = 80 % < 100 %
    agg = PortfolioOptimizer("aggressive")._score_weighted_optimize(_tickers(5))
    assert agg.max() <= 0.20 + EPS                       # 5 × 18 % = 90 %: el tope pasa a 1/n
    mod = PortfolioOptimizer("moderate")._score_weighted_optimize(_tickers(8))
    assert mod.max() <= 0.125 + EPS                      # 8 × 12 % = 96 %


def test_a_relaxed_position_cap_is_said_not_silent():
    opt = PortfolioOptimizer("conservative")
    opt._score_weighted_optimize(_tickers(10))
    assert any("tope por posición" in m for m in opt._fallback_notes)
    opt._score_weighted_optimize(_tickers(25))
    assert not any("tope por posición" in m for m in opt._fallback_notes)


# --------------------------------------------------------------------------- #
#  Tope de sector                                                              #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("profile", PROFILES)
def test_fallback_respects_the_sector_cap_when_it_can(profile):
    """Cinco tickers de un sector con los scores más altos: el sector no pasa su tope."""
    cfg = OPTIMIZER_PROFILES[profile]
    n = 24
    tickers = [_t(f"TECH{i}", 95.0 - i, sector="Technology") for i in range(5)]
    tickers += [_t(f"O{i:02d}", 50.0 - i, sector=f"Other-{i}") for i in range(n - 5)]
    opt = PortfolioOptimizer(profile)
    w = opt._score_weighted_optimize(tickers)

    tech = w[:5].sum()
    assert tech <= cfg.max_sector_pct / 100 + EPS, f"{profile}: Technology {tech:.3f}"
    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    assert np.all(w <= cfg.max_position_pct / 100 + EPS)
    assert not any("sector" in m for m in opt._fallback_notes)


def test_an_unsatisfiable_sector_cap_is_relaxed_and_said():
    """Todo el universo en un sector: ningún reparto suma 100 % bajo el tope de sector."""
    opt = PortfolioOptimizer("moderate")
    tickers = [_t(f"T{i:02d}", 90.0 - i, sector="Technology") for i in range(12)]
    w = opt._score_weighted_optimize(tickers)
    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    assert np.all(w <= 0.12 + EPS)                       # el tope por posición se mantiene
    assert any("sector" in m for m in opt._fallback_notes)


# --------------------------------------------------------------------------- #
#  Cripto                                                                      #
# --------------------------------------------------------------------------- #

def test_crypto_cap_survives_a_universe_too_small_for_the_position_cap():
    """BTC + 3 acciones con Conservador: 3 % + 3 × 8 % = 27 % no alcanza para sumar 100 %.

    Se afloja el tope de las acciones, no el de cripto.
    """
    opt = PortfolioOptimizer("conservative")
    tickers = [_t("BTC", 99.0, "Crypto / Digital Asset"), _t("AAPL", 60.0),
               _t("MSFT", 58.0), _t("JNJ", 55.0)]
    w = opt._score_weighted_optimize(tickers)
    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    assert w[0] <= OPTIMIZER_PROFILES["conservative"].max_crypto_pct / 100 + EPS


# --------------------------------------------------------------------------- #
#  Frontera                                                                    #
# --------------------------------------------------------------------------- #

def test_frontier_cloud_is_built_from_capped_portfolios():
    """Misma semilla, misma nube; cada muestra se topea con la referencia, no con clip+renorm."""
    n = 20
    opt = PortfolioOptimizer("conservative")
    tickers = _tickers(n)
    rng_mu = np.random.default_rng(7)
    mu = rng_mu.uniform(0.04, 0.12, n)
    a = rng_mu.normal(size=(n, n))
    cov = (a @ a.T) / (n * 40)

    result = OptimizationResult(profile_name="conservative", method="test")
    opt._compute_frontier(result, mu, cov, tickers)

    cap = OPTIMIZER_PROFILES["conservative"].max_position_pct / 100
    rng = np.random.default_rng(42)
    ref_rets, ref_vols = [], []
    for _ in range(opt.opt.frontier_points):
        raw = rng.dirichlet(np.ones(n))
        w = _reference(raw, np.full(n, max(cap, 1.0 / n)))
        assert w.max() <= max(cap, 1.0 / n) + EPS
        ref_rets.append(round(float(mu @ w) * 100, 2))
        ref_vols.append(round(float(np.sqrt(w @ cov @ w)) * 100, 2))

    np.testing.assert_allclose(result.frontier_returns, ref_rets, atol=0.011)
    np.testing.assert_allclose(result.frontier_vols, ref_vols, atol=0.011)


# --------------------------------------------------------------------------- #
#  El tope duro de _populate_result                                            #
# --------------------------------------------------------------------------- #

def test_populate_result_caps_by_redistributing_not_by_renormalising():
    """clip(0, tope) y dividir por la suma devuelve el exceso a la misma posición."""
    n = 15
    opt = PortfolioOptimizer("conservative")
    tickers = _tickers(n)
    weights = np.full(n, 0.05)
    weights[0] = 0.30
    weights[1:] = 0.70 / (n - 1)
    cov = np.eye(n) * 0.04
    mu = np.full(n, 0.07)
    result = OptimizationResult(profile_name="conservative", method="test")
    opt._populate_result(result, tickers, weights, mu, cov)

    cap = OPTIMIZER_PROFILES["conservative"].max_position_pct
    top = max(a.weight_pct for a in result.tickers)
    assert top <= cap + 1e-6, f"{top:.3f} % > {cap} %"
    # weight_pct se muestra con un decimal: 14 × 6,571 → 6,6 suma 100,4 sin que falte nada.
    assert sum(a.weight_pct for a in result.tickers) == pytest.approx(100.0, abs=1.0)
