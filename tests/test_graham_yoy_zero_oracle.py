"""AUDIT-RESIDUALES (Graham) — un `earningsGrowth` de exactamente 0 es un cero medido, como uno de +0,04 %.

Sin estados de resultados que alcancen para un CAGR, el motor cae al ``earningsGrowth`` trimestral de yfinance
y sólo lo registraba si ``yoy > 0``. Un +0,04 % se redondea a 0,0 y se valuaba (g = 0, un cero medido: U3-3),
pero un 0,0 exacto —la misma medición— quedaba sin tasa y Graham no publicaba valor: un salto en el borde que
no dice nada del negocio. La rama de los estados ya lo trata bien (un CAGR de 0 se registra y se valúa).

Distinción que hay que conservar: la CLAVE AUSENTE no es un cero (``_safe_float(None)`` da 0,0); sin medición,
no hay valor. Y una caída medida sigue sin valuarse. Esperados con la fórmula de Graham de 1974 a mano,
como en ``test_graham_unknown_growth_oracle``. Sin red.
"""

from __future__ import annotations

import pytest

from config import THRESHOLDS
from tests.test_graham_unknown_growth_oracle import _analyze, oracle_graham


def _flat_value(eps: float) -> float:
    return oracle_graham(eps, 0.0, THRESHOLDS.graham_aaa_yield_pct, THRESHOLDS.graham_max_growth_pct)


@pytest.mark.parametrize("earnings_growth", [0.0004, 0.0])
def test_a_zero_or_nearly_zero_quarterly_growth_is_a_measured_zero_and_is_priced(earnings_growth):
    r = _analyze(eps=5.0, earnings_growth=earnings_growth)
    assert r.eps_cagr_5y == 0.0
    assert r.eps_growth_source == "yoy" and r.eps_cagr_years == 1
    assert r.graham_value == pytest.approx(_flat_value(5.0), abs=0.01)          # 41,56 con Y = 4,5


@pytest.mark.parametrize("not_a_measurement", [None, float("nan"), float("inf"), "N/A", True, False])
def test_what_is_not_a_measurement_is_not_a_zero(not_a_measurement):
    """La clave ausente, un NaN, un infinito, un texto o un booleano llegan a ``_safe_float`` como 0,0."""
    from tests.test_graham_unknown_growth_oracle import _analyze as analyze

    if not_a_measurement is None:
        r = analyze(eps=5.0)                                  # sin la clave
    else:
        r = analyze(eps=5.0, earnings_growth=not_a_measurement)
    assert r.eps_cagr_5y is None and r.eps_growth_source == ""
    assert r.graham_value is None


def test_a_falling_quarterly_growth_is_still_not_priced():
    r = _analyze(eps=5.0, earnings_growth=-0.0004)
    assert r.eps_cagr_5y is None
    assert r.graham_value is None
