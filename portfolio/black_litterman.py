"""
Black-Litterman expected returns + Ledoit-Wolf covariance shrinkage
(Gran Salto — Fase 5, profundidad de modelo).

Two canonical model upgrades over the current proxy:

1. **Ledoit-Wolf shrinkage** of the covariance matrix toward a scaled identity
   (Ledoit & Wolf 2004b, "A well-conditioned estimator..."). More stable than the
   raw sample covariance when there are few observations, which means fewer
   extreme optimizer weights.

2. **Black-Litterman** posterior expected returns. The market-implied equilibrium
   returns (reverse-optimised from market-cap weights) are the prior; the
   product's score-derived expected-return proxy is treated as *views* — exactly
   the framing the vision calls for ("el score ajustado **es** una view"). Mixing
   a sensible equilibrium baseline with the views resolves the known problem that
   the Conservative profile is mathematically infeasible with a pure score proxy
   (the equilibrium gives every asset a non-degenerate return even when scores are
   flat).

Pure NumPy, no network, no Streamlit — fully unit-testable. The optimizer wires
these in behind ``config.BLACK_LITTERMAN`` flags, with a graceful fallback so the
deterministic path stays valid when data is thin.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from loguru import logger


def ledoit_wolf_shrinkage(returns: np.ndarray, periods_per_year: float = 52.0) -> Tuple[np.ndarray, float]:
    """Ledoit-Wolf shrinkage covariance (shrink to scaled identity).

    Parameters
    ----------
    returns : (T, N) array of periodic returns (e.g. weekly).
    periods_per_year : annualisation factor applied to the shrunk covariance.

    Returns
    -------
    (cov_annualised, shrinkage_intensity) — ``shrinkage`` in [0, 1] is the weight
    placed on the structured target (1 = fully shrunk).
    """
    X = np.asarray(returns, dtype=float)
    if X.ndim != 2 or X.shape[0] < 2:
        n = X.shape[1] if X.ndim == 2 else 1
        return np.eye(n) * 0.04, 1.0

    t, n = X.shape
    X = X - X.mean(axis=0, keepdims=True)
    sample = (X.T @ X) / t                      # MLE sample covariance (1/T)

    mu = np.trace(sample) / n
    target = mu * np.eye(n)                      # F = μ·I

    # d² = ||S - F||²_F / n
    d2 = np.sum((sample - target) ** 2) / n

    # b̄² = (1/T²) Σ_t ||x_t x_tᵀ - S||²_F / n   (Frobenius, per-element)
    b2 = 0.0
    for k in range(t):
        xk = X[k][:, None]
        diff = xk @ xk.T - sample
        b2 += np.sum(diff ** 2) / n
    b2 = b2 / (t ** 2)
    b2 = min(b2, d2)                             # b̄² capped by d²

    shrinkage = float(b2 / d2) if d2 > 0 else 1.0
    shrinkage = max(0.0, min(1.0, shrinkage))

    shrunk = shrinkage * target + (1.0 - shrinkage) * sample
    cov_annual = shrunk * periods_per_year
    # tiny ridge for numerical safety
    cov_annual = cov_annual + np.eye(n) * 1e-8
    return cov_annual, shrinkage


def implied_equilibrium_returns(cov: np.ndarray, market_weights: np.ndarray,
                                risk_aversion: float = 2.5) -> np.ndarray:
    """Reverse-optimisation: Π = δ · Σ · w_market.

    That product is a CAPM-equilibrium **excess** return. The views ``q`` this
    module receives from the optimizer are **total** (score + dividend proxy),
    not excess. The two legs are not in the same unit (U5-19); this function
    does not convert them.
    """
    cov = np.asarray(cov, dtype=float)
    w = np.asarray(market_weights, dtype=float)
    w = w / w.sum() if w.sum() > 0 else np.ones(len(w)) / len(w)
    return float(risk_aversion) * (cov @ w)


def black_litterman_posterior(
    cov: np.ndarray,
    market_weights: np.ndarray,
    view_returns: np.ndarray,
    *,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
    view_confidence: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Black-Litterman posterior expected returns with absolute views (P = I).

    Each asset's ``view_returns[i]`` is an absolute view on that asset (the
    score-derived expected return) in **total** return units. Π from
    :func:`implied_equilibrium_returns` is **excess**. They are mixed as-is
    (U5-19): this function does not subtract Rf from ``q``.

    Ω is the standard diagonal ``tau·diag(Σ)``, optionally scaled per-view by
    ``1/view_confidence`` (higher confidence → lower uncertainty → the view
    pulls harder).

    Returns the posterior expected-returns vector (same units as ``cov`` returns).
    Falls back to ``view_returns`` on any numerical failure.
    """
    cov = np.asarray(cov, dtype=float)
    q = np.asarray(view_returns, dtype=float)
    n = len(q)
    if n == 0:
        return q
    if n == 1 or cov.shape != (n, n):
        return q

    try:
        w = np.asarray(market_weights, dtype=float)
        w = w / w.sum() if w.sum() > 0 else np.ones(n) / n
        pi = implied_equilibrium_returns(cov, w, risk_aversion)

        tau_cov = tau * cov
        p = np.eye(n)
        omega_diag = np.diag(tau_cov).copy()
        if view_confidence is not None:
            conf = np.asarray(view_confidence, dtype=float)
            conf = np.clip(conf, 1e-3, None)
            omega_diag = omega_diag / conf
        omega_diag = np.clip(omega_diag, 1e-10, None)
        omega = np.diag(omega_diag)

        inv_tau_cov = np.linalg.pinv(tau_cov)
        inv_omega = np.linalg.pinv(omega)

        a = inv_tau_cov + p.T @ inv_omega @ p
        b = inv_tau_cov @ pi + p.T @ inv_omega @ q
        posterior = np.linalg.pinv(a) @ b
        if not np.all(np.isfinite(posterior)):
            return q
        return posterior
    except Exception as exc:
        logger.warning(f"black_litterman_posterior failed — {exc}; falling back to views")
        return q


def bl_expected_returns(
    view_mu: np.ndarray,
    cov: np.ndarray,
    *,
    market_weights: Optional[np.ndarray] = None,
    view_confidence: Optional[np.ndarray] = None,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> np.ndarray:
    """Convenience wrapper used by the optimizer.

    ``view_mu`` is the existing score-derived expected-return proxy (the views).
    ``market_weights`` defaults to equal-weight when caps aren't available.
    """
    view_mu = np.asarray(view_mu, dtype=float)
    n = len(view_mu)
    if n <= 1:
        return view_mu
    if market_weights is None:
        market_weights = np.ones(n) / n
    return black_litterman_posterior(
        cov, market_weights, view_mu,
        risk_aversion=risk_aversion, tau=tau, view_confidence=view_confidence,
    )
