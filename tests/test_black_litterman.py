"""Tests for Black-Litterman + Ledoit-Wolf shrinkage (Gran Salto, Fase 5).

Pure numpy, no network. Verifies the shrinkage estimator's properties, the BL
equilibrium and posterior behaviour, and the graceful fallbacks.
"""

from __future__ import annotations

import numpy as np

from portfolio.black_litterman import (
    bl_expected_returns,
    black_litterman_posterior,
    implied_equilibrium_returns,
    ledoit_wolf_shrinkage,
)

# --------------------------------------------------------------------------- #
#  Ledoit-Wolf shrinkage                                                       #
# --------------------------------------------------------------------------- #

def test_shrinkage_returns_psd_symmetric():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.02, size=(120, 5))
    cov, intensity = ledoit_wolf_shrinkage(returns, periods_per_year=52.0)
    assert cov.shape == (5, 5)
    assert np.allclose(cov, cov.T)                       # symmetric
    eigvals = np.linalg.eigvalsh(cov)
    assert np.all(eigvals > 0)                            # positive definite
    assert 0.0 <= intensity <= 1.0


def _factor_returns(rng, t, n_assets=6):
    """Correlated returns via a common factor, so the scaled-identity target is
    genuinely wrong (d² > 0) and shrinkage intensity is meaningful."""
    loadings = rng.normal(0.0, 1.0, size=n_assets)
    factor = rng.normal(0.0, 0.02, size=(t, 1))
    idio = rng.normal(0.0, 0.01, size=(t, n_assets))
    return factor * loadings + idio


def test_shrinkage_intensity_high_when_few_observations():
    rng = np.random.default_rng(1)
    few = ledoit_wolf_shrinkage(_factor_returns(rng, 8))[1]
    many = ledoit_wolf_shrinkage(_factor_returns(rng, 800))[1]
    # With fewer observations the sample cov is noisier → more shrinkage.
    assert few > many


def test_shrinkage_annualisation_scales():
    rng = np.random.default_rng(2)
    r = _factor_returns(rng, 200, n_assets=3)
    c1, _ = ledoit_wolf_shrinkage(r, periods_per_year=1.0)
    c52, _ = ledoit_wolf_shrinkage(r, periods_per_year=52.0)
    # Linear in the annualisation factor, modulo the tiny constant numerical ridge.
    assert np.allclose(c52, c1 * 52, rtol=1e-3, atol=1e-6)


def test_shrinkage_degenerate_input():
    cov, intensity = ledoit_wolf_shrinkage(np.zeros((1, 4)))
    assert cov.shape == (4, 4)
    assert intensity == 1.0


# --------------------------------------------------------------------------- #
#  Equilibrium + posterior                                                     #
# --------------------------------------------------------------------------- #

def test_implied_equilibrium_positive_for_positive_cov():
    cov = np.array([[0.04, 0.01], [0.01, 0.05]])
    w = np.array([0.6, 0.4])
    pi = implied_equilibrium_returns(cov, w, risk_aversion=2.5)
    assert pi.shape == (2,)
    assert np.all(pi > 0)


def test_posterior_between_prior_and_views():
    cov = np.array([[0.04, 0.0], [0.0, 0.04]])
    w = np.array([0.5, 0.5])
    views = np.array([0.20, 0.20])  # bullish views above equilibrium
    pi = implied_equilibrium_returns(cov, w, risk_aversion=2.5)
    post = black_litterman_posterior(cov, w, views, risk_aversion=2.5, tau=0.05)
    # Posterior should sit between the (lower) equilibrium prior and the (higher) views.
    for i in range(2):
        lo, hi = sorted([pi[i], views[i]])
        assert lo - 1e-9 <= post[i] <= hi + 1e-9


def test_higher_confidence_pulls_toward_view():
    cov = np.array([[0.04, 0.0], [0.0, 0.04]])
    w = np.array([0.5, 0.5])
    views = np.array([0.25, 0.05])
    low_conf = black_litterman_posterior(cov, w, views, view_confidence=np.array([0.1, 0.1]))
    high_conf = black_litterman_posterior(cov, w, views, view_confidence=np.array([10.0, 10.0]))
    # Asset 0's view (0.25) is well above equilibrium; higher confidence → closer to it.
    assert high_conf[0] > low_conf[0]


def test_single_asset_returns_views():
    cov = np.array([[0.04]])
    out = black_litterman_posterior(cov, np.array([1.0]), np.array([0.1]))
    assert np.allclose(out, [0.1])


def test_bl_expected_returns_defaults_equal_weight():
    cov = np.eye(3) * 0.04
    mu = np.array([0.10, 0.12, 0.08])
    post = bl_expected_returns(mu, cov)
    assert post.shape == (3,)
    assert np.all(np.isfinite(post))


def test_bl_expected_returns_size_mismatch_falls_back():
    mu = np.array([0.1, 0.1, 0.1])
    bad_cov = np.eye(2) * 0.04  # wrong size
    out = bl_expected_returns(mu, bad_cov)
    assert np.allclose(out, mu)  # graceful fallback to views
