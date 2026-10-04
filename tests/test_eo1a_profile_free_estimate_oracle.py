"""Oráculo EO-1a: el Perfil no toca la Estimación del optimizador (ADR 0001).

Dos caminos dejaban entrar el perfil en el rendimiento esperado de un activo:

* **El δ del prior de Black-Litterman.** ``_apply_black_litterman`` usaba
  ``ProfileConfig.risk_aversion`` (4,0 / 2,5 / 1,5). En Π = δ·Σ·w el δ multiplica:
  el δ = 4,0 de Conservador daba el equilibrio **más** optimista de los tres, al
  revés de lo que decía su comentario. D3 (auditoría 2026-08) había sacado al perfil
  de las vistas y lo dejó entrar por acá; el ADR 0001 lo saca también de acá. El δ
  es el del mercado, ``BLACK_LITTERMAN.risk_aversion``.
* **El descuento por riesgo argentino.** ``_apply_ars_discount`` lo salteaba con
  Agresivo. El riesgo de un emisor argentino no depende de quién mira: rige para
  todos (el valor sigue siendo ``OPTIMIZER.ars_risk_discount``, pendiente de Fuente
  hasta EO-2).

Referencia independiente del optimizador: un Σ de 2×2 y unos pesos de mercado
armados a mano, con Π = 2,5·Σ·w calculado en el docstring de abajo. Si las vistas
son exactamente ese Π, el posterior de Black-Litterman es Π —el prior y la vista
coinciden— para cualquier Ω, así que el posterior sólo puede devolver Π si el δ que
usó el optimizador es el de mercado.
"""

from __future__ import annotations

import numpy as np
import pytest

from config import BLACK_LITTERMAN
from portfolio.optimizer import PortfolioOptimizer

PROFILES = ("conservative", "moderate", "aggressive")

# Σ anual y capitalizaciones, a mano. w = caps / Σcaps = (0,75; 0,25).
COV = np.array([[0.04, 0.006],
                [0.006, 0.09]])
CAPS = (3e12, 1e12)
# Σ·w = (0,04·0,75 + 0,006·0,25 ; 0,006·0,75 + 0,09·0,25) = (0,0315 ; 0,027)
# Π   = 2,5 · Σ·w                                          = (0,07875 ; 0,0675)
PI_MARKET = np.array([0.07875, 0.0675])


def _tickers() -> list[dict]:
    return [
        {"symbol": "AAA", "adjusted_score": 70.0, "market_cap": CAPS[0]},
        {"symbol": "BBB", "adjusted_score": 70.0, "market_cap": CAPS[1]},
    ]


def test_the_hand_built_prior_uses_the_market_delta():
    assert BLACK_LITTERMAN.risk_aversion == 2.5          # el δ de los libros de texto


@pytest.mark.parametrize("profile", PROFILES)
def test_views_equal_to_the_market_prior_come_back_unchanged(profile):
    posterior = PortfolioOptimizer(profile)._apply_black_litterman(
        PI_MARKET.copy(), COV, _tickers(), True
    )
    # main: Conservador mezcla la vista con 4,0·Σ·w y Agresivo con 1,5·Σ·w.
    assert posterior == pytest.approx(PI_MARKET, rel=1e-9)


@pytest.mark.parametrize("profile", PROFILES)
def test_an_argentine_issuer_is_discounted_for_every_profile(profile):
    """80 puntos × 0,85 = 68: la cuenta a mano con el valor de config hoy."""
    from config import OPTIMIZER

    assert OPTIMIZER.ars_risk_discount == 0.85           # el número que pide Fuente (EO-2)
    row = {"symbol": "YPF", "adjusted_score": 80.0, "country": "Argentina"}
    [scored] = PortfolioOptimizer(profile)._apply_ars_discount([row])
    assert scored["adjusted_score"] == pytest.approx(68.0)   # main: 80 con Agresivo
    assert scored["_ars_discounted"] is True
