"""AUDIT-RESIDUALES (optimizador) — el camino SLSQP no deja polvo, y no hacía falta un paso que lo anulara.

``_try_minimize`` hacía ``w[w < lb * 0.5] = 0`` después de ``np.clip(res.x, lb, ub)``: nada baja de ``lb``
después del clip, así que el paso no podía dispararse nunca y parecía decir que el polvo se anulaba. El polvo lo
evita la cota inferior de cada ticker (``min_weight_pct``), no ese paso. Se quita el paso (un cambio que no
mueve ninguna cartera); lo que fijan estos tests es lo que el paso pretendía garantizar:

* cada posición del resultado pesa al menos ``min_weight_pct`` (no hay polvo), los pesos suman 1;
* el paso quitado era la identidad sobre toda salida alcanzable: aplicarlo no cambia nada.

Los problemas son sintéticos (retornos y volatilidades sembrados), sin red.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio.optimizer import PortfolioOptimizer
from tests.test_optimizer import _ticker

SECTORS = ["Tech", "Health", "Staples", "Energy", "Utilities", "Fin"]


def _problem(profile: str, seed: int, n: int):
    rng = np.random.default_rng(seed)
    opt = PortfolioOptimizer(profile)
    tickers = [_ticker(f"S{i:02d}", div=float(rng.uniform(1.0, 5.0)), sector=SECTORS[i % 6]) for i in range(n)]
    sigma = rng.uniform(0.10, 0.35, n)
    mu = opt.opt.risk_free_rate + rng.uniform(0.01, 0.12, n)
    return opt, tickers, mu, np.diag(sigma**2)


# Moderado y Agresivo: SLSQP converge en estos problemas (Conservador casi nunca: sus topes por posición
# dejan pocos portafolios factibles, y un test que se saltea no dice nada). Se afirma que converge.
@pytest.mark.parametrize("profile", ["moderate", "aggressive"])
@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("n", [12, 18])
def test_no_position_is_dust_and_the_dropped_step_is_the_identity(profile, seed, n):
    opt, tickers, mu, cov = _problem(profile, seed, n)
    w = opt._run_slsqp(mu, cov, tickers)
    assert w is not None, "SLSQP no convergió: el problema sintético ya no sirve para este test"
    lb = opt.opt.min_weight_pct / 100
    assert w.sum() == pytest.approx(1.0, abs=1e-9)
    assert (w >= lb * (1 - 1e-6)).all(), f"dust: {w.min():.6f} < {lb}"
    stepped = w.copy()
    stepped[stepped < lb * 0.5] = 0     # el paso que se quitó
    assert np.array_equal(stepped, w)
