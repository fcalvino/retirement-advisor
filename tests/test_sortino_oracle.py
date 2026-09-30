"""Oráculo U1-9b: el ratio bajista de los dos motores es un Sortino, con MAR = tasa libre de riesgo.

Hasta U1-9b los dos motores dividían por ``returns[returns < 0].std()``: el desvío
de las semanas perdedoras **alrededor de su propia media**. Con pérdidas parejas
ese desvío casi desaparece y el ratio publicado sube justo cuando la cartera pierde
de forma sostenida. El denominador de Sortino es la desviación bajista

    DD = √( (1/N) · Σ mín(rᵢ − MAR, 0)² ) · √52

sobre **todas** las semanas (las que superan el MAR entran como cero), medida desde
el MAR, que acá es la tasa libre de riesgo pasada a semanal:
``(1 + rf)^(1/52) − 1``. Decisión del usuario (2026-09-30): se llama Sortino y el
MAR es la misma tasa que ya resta el numerador.

Independiente del código bajo prueba: la referencia es un loop escrito desde la
definición, sin numpy vectorizado ni helpers del proyecto. El numerador de cada
motor no se toca (CAGR − rf en Backtesting, media anualizada − rf en el tracker:
el mismo que su Sharpe), así que el oráculo lo recalcula con la misma regla.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
import pytest

from analysis.backtesting import BacktestEngine
from config import RISK_FREE
from portfolio.tracker import Portfolio

WEEKS = 52


def _reference_downside_deviation(returns: list[float], rf_annual: float) -> float:
    mar = (1.0 + rf_annual) ** (1.0 / WEEKS) - 1.0
    total = 0.0
    for r in returns:
        shortfall = r - mar
        if shortfall < 0:
            total += shortfall * shortfall
    return math.sqrt(total / len(returns)) * math.sqrt(WEEKS)


def _series(prices: list[float]) -> pd.Series:
    idx = pd.date_range("2020-01-05", periods=len(prices), freq="W")
    return pd.Series(prices, index=idx, dtype=float)


def _returns(prices: list[float]) -> list[float]:
    return [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]


def _bt_reference(prices: list[float], rf: float) -> float | None:
    years = max((len(prices) - 1) / WEEKS, 0.1)
    cagr = (prices[-1] / prices[0]) ** (1.0 / years) - 1.0
    dd = _reference_downside_deviation(_returns(prices), rf)
    return None if dd == 0 else round((cagr - rf) / dd, 2)


def _prices_from(returns: list[float], start: float = 100.0) -> list[float]:
    out = [start]
    for r in returns:
        out.append(out[-1] * (1.0 + r))
    return out


#: Pérdidas parejas: 30 semanas de −1 % exacto con un poco de ruido. El desvío
#: alrededor de su propia media es minúsculo; la desviación bajista contra el MAR no.
STEADY_LOSSES = _prices_from([-0.010 + (0.0005 if i % 2 else -0.0005) for i in range(30)] + [0.004] * 10)
#: Ganancias y pérdidas mezcladas, determinístico.
MIXED = _prices_from([(0.03 if i % 4 == 0 else -0.012 if i % 3 == 0 else 0.006) for i in range(120)])
#: Ninguna semana por debajo del MAR: la desviación bajista es 0 y el ratio no se puede medir.
NEVER_BELOW_MAR = _prices_from([0.01] * 60)


# --------------------------------------------------------------------------- #
#  Backtesting                                                                 #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("prices", [STEADY_LOSSES, MIXED], ids=["steady_losses", "mixed"])
def test_backtesting_divides_by_the_downside_deviation_against_rf(prices):
    engine = BacktestEngine()
    got = engine._metrics(_series(prices))["downside_vol_ratio"]
    assert got == pytest.approx(_bt_reference(prices, engine.rf), abs=0.011)


def test_steady_losses_are_not_rewarded():
    """El defecto que la fila describía: el denominador viejo premiaba perder parejo."""
    engine = BacktestEngine()
    got = engine._metrics(_series(STEADY_LOSSES))["downside_vol_ratio"]
    old_den = pd.Series([r for r in _returns(STEADY_LOSSES) if r < 0]).std() * math.sqrt(WEEKS)
    years = (len(STEADY_LOSSES) - 1) / WEEKS
    cagr = (STEADY_LOSSES[-1] / STEADY_LOSSES[0]) ** (1 / years) - 1
    old = (cagr - engine.rf) / old_den
    # Viejo: −90,9. Sortino: −4,9.
    assert abs(got) < abs(old) / 5


def test_no_week_below_the_mar_is_not_measurable():
    engine = BacktestEngine()
    assert engine._metrics(_series(NEVER_BELOW_MAR))["downside_vol_ratio"] is None


def test_the_mar_is_the_risk_free_rate_not_zero():
    """Una semana que rinde +0,05 % gana algo pero queda debajo de un bono al 4,5 %/año."""
    engine = BacktestEngine(risk_free_rate=0.045)
    prices = _prices_from([0.0005] * 20 + [0.02] * 20)
    got = engine._metrics(_series(prices))["downside_vol_ratio"]
    assert got is not None  # con MAR = 0 no habría ninguna semana bajista
    assert got == pytest.approx(_bt_reference(prices, 0.045), abs=0.011)


# --------------------------------------------------------------------------- #
#  El tracker                                                                  #
# --------------------------------------------------------------------------- #

def _weekly_frame(prices: list[float]) -> pd.DataFrame:
    last = (datetime.now() + timedelta(weeks=1)).date()
    idx = pd.date_range(end=last, periods=len(prices), freq="W")
    return pd.DataFrame({"close": prices}, index=idx)


def test_tracker_divides_by_the_downside_deviation_against_rf(tmp_path, monkeypatch):
    hist = {"KO": _weekly_frame(MIXED), "SPY": _weekly_frame(_prices_from([0.002] * 120))}
    monkeypatch.setattr("portfolio.tracker.get_info", lambda sym: {})
    monkeypatch.setattr("portfolio.tracker.get_history",
                        lambda sym, period="5y", interval="1wk": hist[sym])
    p = Portfolio(file_path=tmp_path / "portfolio.json")
    p.add_position("KO", 10.0, 100.0,
                   purchase_date=(datetime.now() - timedelta(weeks=200)).date().isoformat())

    got = p.compute_metrics().downside_vol_ratio

    curve = p._build_equity_curve()
    rets = curve.pct_change().dropna().tolist()
    rf = RISK_FREE.annual_fraction
    mean_ret = sum(rets) / len(rets) * WEEKS
    expected = round((mean_ret - rf) / _reference_downside_deviation(rets, rf), 2)
    assert got == pytest.approx(expected, abs=0.011)
