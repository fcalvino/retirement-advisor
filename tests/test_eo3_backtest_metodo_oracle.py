"""Oráculo EO-3: el backtest point-in-time del método de Estimación (ADR 0001).

La pregunta: ¿el p10–p90 de la Estimación central contiene el rendimiento real a
10 años con la frecuencia que declara (80 %)? Decisiones del usuario (2026-10-05):

- términos reales; acciones EE.UU. (1/CAPE + Historia) y bonos EE.UU. (GS10 menos la
  inflación de los 10 años anteriores + Historia); el resto, no calibrable;
- el Azar, como el Monte Carlo: los 120 meses anteriores, bootstrap por bloques;
- recentrado compuesto: la mediana de los caminos rinde el central;
- pasa si el 80 % cae en el intervalo de Clopper-Pearson al 90 % de la cobertura en
  ventanas de 10 años sin superposición.

Series sintéticas y números hechos a mano; Clopper-Pearson se verifica contra su
definición (sumas binomiales con ``math.comb``), no contra ``scipy``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest


def _rows(n, *, cape=25.0, gs10=5.0, cpi_growth=0.0, eq_growth=0.0, bond_growth=0.0):
    """``n`` meses desde 1871-01 con crecimientos mensuales constantes."""
    from analysis.backtest_metodo import MonthlyRow

    out = []
    for i in range(n):
        y, m = 1871 + i // 12, i % 12 + 1
        out.append(MonthlyRow(
            year=y, month=m, cpi=100.0 * (1 + cpi_growth) ** i,
            real_tr_price=100.0 * (1 + eq_growth) ** i, cape=cape, gs10=gs10,
            real_bond_index=1.0 * (1 + bond_growth) ** i,
        ))
    return out


def _monthly(annual_pct):
    return (1 + annual_pct / 100) ** (1 / 12) - 1


# --------------------------------------------------------------------------- #
#  El central, sólo con lo que se sabía en t                                   #
# --------------------------------------------------------------------------- #

def test_equity_central_is_the_median_of_cape_yield_and_history():
    from analysis.backtest_metodo import central_at

    rows = _rows(241, cape=25.0, eq_growth=_monthly(6.0))
    # 1/CAPE = 4,0 % real; Historia real 6,0 %; mediana de dos = (4,0 + 6,0) / 2.
    assert central_at(rows, 240, "us_equity") == pytest.approx(5.0)


def test_bond_central_is_the_median_of_real_yield_and_history():
    from analysis.backtest_metodo import central_at

    rows = _rows(241, gs10=5.0, cpi_growth=_monthly(2.0), bond_growth=_monthly(2.0))
    # Valuación real (Fisher): 1,05 / 1,02 − 1 = 2,941 %; Historia 2,0 %.
    assert central_at(rows, 240, "us_bonds") == pytest.approx((2.941176 + 2.0) / 2, abs=1e-4)


def test_nothing_after_t_moves_the_central_or_the_band():
    from analysis.backtest_metodo import azar_band, central_at, trailing_returns

    rows = _rows(400, eq_growth=_monthly(6.0))
    rng = np.random.default_rng(1)
    noisy = list(rows)
    for j in range(241, 400):      # el futuro cambia por completo
        r = rows[j]
        noisy[j] = type(r)(r.year, r.month, r.cpi * 3, r.real_tr_price * rng.uniform(0.1, 9),
                           99.0, 1.0, r.real_bond_index * 7)
    assert central_at(noisy, 240, "us_equity") == central_at(rows, 240, "us_equity")
    assert trailing_returns(noisy, 240, "us_equity") == trailing_returns(rows, 240, "us_equity")
    band_a = azar_band(trailing_returns(rows, 240, "us_equity"), 5.0, rng=np.random.default_rng(7))
    band_b = azar_band(trailing_returns(noisy, 240, "us_equity"), 5.0, rng=np.random.default_rng(7))
    assert band_a == band_b


# --------------------------------------------------------------------------- #
#  El Azar: recentrado compuesto                                               #
# --------------------------------------------------------------------------- #

def test_with_zero_volatility_the_band_collapses_on_the_central():
    from analysis.backtest_metodo import azar_band

    flat = [_monthly(9.0)] * 120     # la historia rindió 9 %: el recentrado la lleva al central
    p10, p90 = azar_band(flat, 5.0, rng=np.random.default_rng(3))
    assert p10 == pytest.approx(5.0) and p90 == pytest.approx(5.0)


def test_the_median_path_earns_the_central_not_more():
    from analysis.backtest_metodo import azar_band

    rng = np.random.default_rng(11)
    noisy = list(rng.normal(0.007, 0.045, size=120))       # vol de acciones
    p10, p90 = azar_band(noisy, 5.0, rng=np.random.default_rng(5), n_sims=4000)
    # Compuesto: la banda queda alrededor del central (log-simétrica), no ~1 pp arriba.
    mid = math.sqrt((1 + p10 / 100) * (1 + p90 / 100)) - 1
    assert mid * 100 == pytest.approx(5.0, abs=0.35)
    assert p10 < 5.0 < p90


# --------------------------------------------------------------------------- #
#  Lo realizado                                                                #
# --------------------------------------------------------------------------- #

def test_realized_is_the_annualized_real_return_of_the_next_horizon():
    from analysis.backtest_metodo import realized_real_pct

    rows = _rows(30, eq_growth=0.0)
    rows[24] = type(rows[24])(rows[24].year, rows[24].month, 100.0, 121.0, 25.0, 5.0, 1.0)
    # 100 → 121 en 24 meses = 10 % anual.
    assert realized_real_pct(rows, 0, "us_equity", horizon_months=24) == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
#  Cobertura y Clopper-Pearson                                                 #
# --------------------------------------------------------------------------- #

def _tail_ge(k, n, p):
    return sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))


def _bisect(f, lo=0.0, hi=1.0):
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _cp_by_definition(k, n, alpha):
    # bajo: el p con P(X ≥ k | p) = α/2; alto: el p con P(X ≤ k | p) = α/2.
    low = 0.0 if k == 0 else _bisect(lambda p: _tail_ge(k, n, p) >= alpha / 2)
    high = 1.0 if k == n else _bisect(lambda p: 1 - _tail_ge(k + 1, n, p) <= alpha / 2)
    return low, high


@pytest.mark.parametrize("k, n, passes", [
    (11, 14, True),
    (14, 14, False),    # sobre-cubre: el bajo es (α/2)^(1/n) = 0,05^(1/14) = 0,807, arriba del 80 %
    (6, 14, False),     # sub-cubre
])
def test_coverage_uses_the_exact_clopper_pearson_interval(k, n, passes):
    from analysis.backtest_metodo import coverage

    res = coverage([True] * k + [False] * (n - k), target=0.80, confidence=0.90)
    low, high = _cp_by_definition(k, n, 0.10)
    assert (res.n, res.k) == (n, k)
    assert res.rate == pytest.approx(k / n)
    assert res.low == pytest.approx(low, abs=1e-6) and res.high == pytest.approx(high, abs=1e-6)
    assert res.passes is passes


# --------------------------------------------------------------------------- #
#  Las ventanas                                                                #
# --------------------------------------------------------------------------- #

def test_windows_start_when_there_is_enough_past_and_end_when_the_future_is_known():
    from analysis.backtest_metodo import evaluation_indexes, non_overlapping

    rows = _rows(120 + 240 + 5)           # 120 de pasado; inicios 120 … 244
    idx = evaluation_indexes(rows, "us_equity", horizon_months=120, window_months=120)
    assert idx[0] == 120 and idx[-1] == len(rows) - 1 - 120
    assert non_overlapping(idx, 120) == [120, 240]


def test_the_backtest_is_reproducible_and_reports_both_coverages():
    from analysis.backtest_metodo import run_backtest

    rng = np.random.default_rng(2)
    rows = _rows(481)
    for j in range(1, 481):   # rendimientos ruidosos alrededor del 5 % real
        r, prev = rows[j], rows[j - 1]
        rows[j] = type(r)(r.year, r.month, r.cpi,
                          prev.real_tr_price * (1 + rng.normal(_monthly(5.0), 0.04)),
                          20.0, r.gs10, r.real_bond_index)
    a = run_backtest(rows, "us_equity", seed=9, n_sims=300)
    b = run_backtest(rows, "us_equity", seed=9, n_sims=300)
    assert a == b
    # inicios 120 … 360: superpuestas 241, sin superposición 120, 240 y 360.
    assert a.non_overlapping.n == 3 and a.overlapping.n == 481 - 120 - 120
    assert all(w.p10 < w.p90 for w in a.windows)


def test_phase_sensitivity_runs_the_rule_on_every_starting_month():
    from analysis.backtest_metodo import BacktestResult, CoverageResult, Window, phase_sensitivity

    # 4 fases (step=4) sobre 16 ventanas: la fase 0 acierta 4/4, las demás 0/4.
    ws = tuple(Window(index=10 + j, date="x", central=0, p10=0, p90=0, realized=0,
                      hit=(j % 4 == 0)) for j in range(16))
    dummy = CoverageResult(n=0, k=0, rate=0, low=0, high=0, passes=False)
    res = BacktestResult(asset="us_equity", windows=ws, overlapping=dummy,
                         non_overlapping=dummy, non_overlapping_windows=(),
                         mean_bias_pp=0, mean_width_pp=0)
    ps = phase_sensitivity(res, step=4)
    # 4/4: el bajo de Clopper-Pearson es 0,05^(1/4) = 0,47 ≤ 0,80 ≤ 1 → pasa;
    # 0/4: el alto es 1 − 0,05^(1/4) = 0,53 < 0,80 → no pasa.
    assert (ps.phases, ps.passing, ps.k_min, ps.k_max) == (4, 1, 0, 4)


# --------------------------------------------------------------------------- #
#  Config y el informe versionado                                              #
# --------------------------------------------------------------------------- #

def test_the_users_parameters_live_in_config():
    from config import BACKTEST_METODO, MONTE_CARLO

    assert BACKTEST_METODO.coverage_target == 0.80 and BACKTEST_METODO.confidence == 0.90
    assert BACKTEST_METODO.horizon_months == 120 and BACKTEST_METODO.azar_window_months == 120
    assert BACKTEST_METODO.inflation_proxy_months == 120
    assert set(BACKTEST_METODO.not_calibrable) == {"developed_ex_us", "emerging", "reits"}
    # El haircut del MC no se toca: lo borra EO-4, y sólo si EO-3 pasa.
    assert (MONTE_CARLO.vol_adjustment, MONTE_CARLO.mean_haircut) == (1.10, 0.80)


def test_the_shipped_report_has_a_verdict_per_class_and_no_raw_series():
    from config import BACKTEST_METODO

    path = Path(__file__).resolve().parents[1] / BACKTEST_METODO.report_file
    report = json.loads(path.read_text(encoding="utf-8"))
    assert len(report["source"]["sha256"]) == 64
    for cls in ("us_equity", "us_bonds"):
        r = report["classes"][cls]
        assert r["verdict"] in ("pasa", "no pasa")
        nov = r["non_overlapping"]
        assert nov["n"] == len(nov["windows"]) and 0 <= nov["low"] <= nov["high"] <= 1
        assert {"date", "central", "p10", "p90", "realized", "hit"} <= set(nov["windows"][0])
        ps = r["phase_sensitivity"]
        assert ps["phases"] == 120 and 0 <= ps["passing"] <= 120 and ps["k_min"] <= nov["k"] <= ps["k_max"]
    assert set(report["not_calibrable"]) == {"developed_ex_us", "emerging", "reits"}
    text = path.read_text(encoding="utf-8")
    assert "real_tr_price" not in text and "cpi" not in text.lower().replace("ipc", "")
