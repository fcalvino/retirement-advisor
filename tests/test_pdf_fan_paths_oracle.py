"""Oráculo PDF-FAN-PATHS: el fan chart del PDF dibuja la corrida, año por año.

`MonteCarloSimulator._fan_paths` devuelve `{año: {percentil: valor}}` y Simulaciones
lo lee así (`mc.fan_paths[y][p]`). `InvestmentPlanReport._fan_chart` lo leía como
`{percentil: {año: valor}}`: `10 in fp` encontraba el **año** 10 y `fp[10].get(y, 0)`
buscaba un percentil con el número del año. Con 10 años salía una línea «P10» con
picos en los años 5 y 10 y ceros en el resto, sin bandas ni mediana, y el
fallback del horizonte (`fan_paths.get(50, {})`) daba 0. Está así desde `5fb471c`.
Hoy sólo Mi Plan le pasa `mc_result` al PDF. Banda 1: el fan chart se lee como la
proyección del usuario.

Los datos salen del motor (`_fan_paths` sobre un array de caminos, y
`_apply_cash_flows` para el ahorrista sin capital), no de un dict armado a mano:
un dict a mano con la forma equivocada es justamente lo que dejó pasar el defecto.
Se llama a `_fan_chart` directo porque `_section_risk` lo envuelve en un `try` que
saca el gráfico sin aviso.
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.collections import PolyCollection

from portfolio.monte_carlo import MonteCarloResult, MonteCarloSimulator

HORIZON = 10
INITIAL = 100_000.0
BANDS = {"P5–P95": (5, 95), "P10–P90": (10, 90), "P25–P75": (25, 75)}


def _market(horizon: int = HORIZON, n_sims: int = 400, seed: int = 7) -> np.ndarray:
    """Caminos relativos como los de `_simulate_paths`: arrancan en 1.0."""
    rng = np.random.default_rng(seed)
    weekly = rng.normal(0.0012, 0.022, size=(n_sims, horizon * 52))
    return np.concatenate([np.ones((n_sims, 1)), np.cumprod(1.0 + weekly, axis=1)], axis=1)


def _mc(paths_usd: np.ndarray, horizon: int = HORIZON, initial: float = INITIAL) -> MonteCarloResult:
    mc = MonteCarloResult(
        n_sims=paths_usd.shape[0], horizon_years=horizon, initial_value=initial,
        annual_withdrawal=0.0, target_value=0.0,
    )
    mc.fan_paths = MonteCarloSimulator(["X"])._fan_paths(paths_usd, horizon)
    mc.years = list(range(0, horizon + 1))
    return mc


@pytest.fixture
def draw(monkeypatch):
    """Dibuja el fan chart y devuelve sus ejes, antes de que se vuelvan un PNG."""
    import matplotlib.pyplot as plt

    from reports import investment_plan
    from reports.investment_plan import InvestmentPlanReport

    figs = []

    def capture(fig, **_kw):
        figs.append(fig)
        return "image"

    monkeypatch.setattr(investment_plan, "_chart_to_image", capture)

    def _draw(mc, mc_params):
        assert InvestmentPlanReport()._fan_chart(mc, mc_params) == "image"
        return figs[-1].axes[0]

    yield _draw
    for fig in figs:
        plt.close(fig)


def _line(ax, label: str):
    lines = [ln for ln in ax.get_lines() if ln.get_label() == label]
    assert lines, f"falta la línea «{label}»: {[ln.get_label() for ln in ax.get_lines()]}"
    return lines[0]


def _series(mc, pct: int) -> list[float]:
    return [mc.fan_paths[y][pct] for y in mc.years]


# --------------------------------------------------------------------------- #
#  Acumulación con capital: el caso de Mi Plan                                #
# --------------------------------------------------------------------------- #

@pytest.fixture
def mc():
    return _mc(_market() * INITIAL)


PARAMS = {"horizon_years": HORIZON, "initial_value": INITIAL}


def test_the_median_follows_the_run_year_by_year(draw, mc):
    line = _line(draw(mc, PARAMS), "Mediana (P50)")
    assert list(line.get_xdata()) == mc.years
    assert list(line.get_ydata()) == pytest.approx(_series(mc, 50))


def test_the_p10_follows_the_run_year_by_year_without_zeros(draw, mc):
    line = _line(draw(mc, PARAMS), "Mala racha (p10)")
    ys = list(line.get_ydata())
    assert list(line.get_xdata()) == mc.years
    assert ys == pytest.approx(_series(mc, 10))
    assert min(ys) > 0


@pytest.mark.parametrize("label", list(BANDS))
def test_each_band_spans_its_two_percentiles_every_year(draw, mc, label):
    ax = draw(mc, PARAMS)
    bands = [c for c in ax.collections if isinstance(c, PolyCollection) and c.get_label() == label]
    assert len(bands) == 1, f"falta la banda {label}: {[c.get_label() for c in ax.collections]}"
    vertices = {(round(x), round(y)) for x, y in bands[0].get_paths()[0].vertices}
    lo, hi = BANDS[label]
    for y in mc.years:
        assert (y, round(mc.fan_paths[y][lo])) in vertices, (label, y, lo)
        assert (y, round(mc.fan_paths[y][hi])) in vertices, (label, y, hi)


def test_the_chart_ends_on_the_terminal_figures_the_pdf_prints(draw, mc):
    """El resumen ejecutivo imprime P50 y P10 del horizonte: el gráfico termina ahí."""
    ax = draw(mc, PARAMS)
    assert _line(ax, "Mediana (P50)").get_ydata()[-1] == mc.fan_paths[HORIZON][50]
    assert _line(ax, "Mala racha (p10)").get_ydata()[-1] == mc.fan_paths[HORIZON][10]


def test_without_a_horizon_in_params_the_chart_still_covers_the_run(draw, mc):
    """El fallback leía `fan_paths.get(50, {})`, que con 10 años da 0."""
    ax = draw(mc, {"initial_value": INITIAL})
    assert list(_line(ax, "Mediana (P50)").get_xdata()) == mc.years
    assert ax.get_xlim() == (0, HORIZON)


# --------------------------------------------------------------------------- #
#  Año 0 y el ahorrista sin capital                                           #
# --------------------------------------------------------------------------- #

def test_year_zero_is_the_run_starting_point(draw, mc):
    ax = draw(mc, PARAMS)
    assert mc.fan_paths[0][50] == INITIAL
    assert _line(ax, "Mediana (P50)").get_ydata()[0] == INITIAL


def test_a_saver_without_capital_is_drawn_from_the_engine_cash_flows(draw):
    """`initial_value=0` (U4-2): el pozo sale de los depósitos que pone el motor."""
    from portfolio.decumulation import wealth_basis

    contribution = 24_000.0
    basis = wealth_basis(0.0, contribution)
    paths_usd = MonteCarloSimulator._apply_cash_flows(
        _market(), 0.0, basis, 0.0, contribution, HORIZON * 52,
    ) * basis
    mc = _mc(paths_usd, initial=0.0)

    ax = draw(mc, {"horizon_years": HORIZON, "initial_value": 0.0})
    med = list(_line(ax, "Mediana (P50)").get_ydata())
    assert med == pytest.approx(_series(mc, 50))
    assert med[0] == 0.0 and min(med[1:]) > 0
