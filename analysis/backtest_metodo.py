"""Backtest point-in-time del método de Estimación (EO-3, ADR 0001).

La pregunta: ¿el p10–p90 de la Estimación central contiene el rendimiento real a
10 años con la frecuencia que declara (80 %)? Es la condición de EO-4.

En cada mes ``t`` de la serie de Shiller, sólo con lo que se sabía en ``t``:

- **central**: la mediana de las Fuentes con historia larga. Acciones de EE.UU.:
  1/CAPE y la Historia real del S&P desde 1871. Bonos de EE.UU.: el GS10 menos la
  inflación de los ``inflation_proxy_months`` previos (Fisher) y la Historia real de
  los bonos desde 1871. Todo real (decisiones del usuario, 2026-10-05).
- **Azar**: el mismo mecanismo que el Monte Carlo —bootstrap por bloques de los
  ``azar_window_months`` previos— recentrado en el central de forma **compuesta**:
  se demean los log-rendimientos y se suma ``log(1 + central) / 12``, así que la
  mediana de los caminos rinde el central. EO-4 tiene que recentrar igual.
- **resultado**: el rendimiento real anualizado de ``t`` a ``t + horizon``.

Puro: sin red, sin base, sin Streamlit. El script ``scripts/backtest_metodo.py`` lo
corre sobre ``ie_data.xls`` y versiona sólo números derivados.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.stats import beta

from analysis.fuentes import annualized_pct
from config import BACKTEST_METODO

_FIELD = {"us_equity": "real_tr_price", "us_bonds": "real_bond_index"}


@dataclass(frozen=True)
class MonthlyRow:
    """Un mes de ie_data.xls con lo que usa el backtest."""

    year: int
    month: int
    cpi: float
    real_tr_price: float              # «Real Total Return Price»
    cape: Optional[float]             # «P/E10 or CAPE»; None antes de 1881
    gs10: Optional[float]             # «Long Interest Rate GS10», % nominal
    real_bond_index: Optional[float]  # «Real Total Bond Returns», índice


@dataclass(frozen=True)
class CoverageResult:
    n: int
    k: int
    rate: float
    low: float      # Clopper-Pearson
    high: float
    passes: bool    # ``coverage_target`` dentro de [low, high]


@dataclass(frozen=True)
class Window:
    index: int
    date: str        # «AAAA-MM», el mes de la Estimación
    central: float   # % real anual
    p10: float
    p90: float
    realized: float
    hit: bool


@dataclass(frozen=True)
class BacktestResult:
    asset: str
    windows: Tuple[Window, ...]       # todas: las superpuestas
    overlapping: CoverageResult       # se informa, no se juzga
    non_overlapping: CoverageResult   # la que decide
    non_overlapping_windows: Tuple[Window, ...]
    mean_bias_pp: float               # promedio de (realizado − central)
    mean_width_pp: float              # promedio de (p90 − p10)


# --------------------------------------------------------------------------- #
#  El central en t                                                             #
# --------------------------------------------------------------------------- #

def _years(months: int) -> float:
    return months / 12.0


def history_real_pct(rows: Sequence[MonthlyRow], i: int, asset: str) -> float:
    """La Historia real de la Clase desde la primera fila hasta ``i``."""
    f = _FIELD[asset]
    return annualized_pct(getattr(rows[0], f), getattr(rows[i], f), _years(i))


def valuation_real_pct(rows: Sequence[MonthlyRow], i: int, asset: str) -> float:
    """La valuación en términos reales: 1/CAPE, o el GS10 menos la inflación previa."""
    if asset == "us_equity":
        return 100.0 / rows[i].cape
    w = BACKTEST_METODO.inflation_proxy_months
    inflation = annualized_pct(rows[i - w].cpi, rows[i].cpi, _years(w))
    return ((1 + rows[i].gs10 / 100.0) / (1 + inflation / 100.0) - 1.0) * 100.0


def central_at(rows: Sequence[MonthlyRow], i: int, asset: str) -> float:
    """La Estimación central en ``i``: la mediana de las Fuentes conocidas en ``i``."""
    return float(median([valuation_real_pct(rows, i, asset), history_real_pct(rows, i, asset)]))


# --------------------------------------------------------------------------- #
#  El Azar                                                                     #
# --------------------------------------------------------------------------- #

def trailing_returns(rows: Sequence[MonthlyRow], i: int, asset: str,
                     window_months: Optional[int] = None) -> List[float]:
    """Los ``window_months`` rendimientos reales mensuales que terminan en ``i``."""
    w = window_months or BACKTEST_METODO.azar_window_months
    f = _FIELD[asset]
    return [getattr(rows[j], f) / getattr(rows[j - 1], f) - 1.0 for j in range(i - w + 1, i + 1)]


def azar_band(returns: Sequence[float], central_pct: float, *, rng: np.random.Generator,
              n_sims: Optional[int] = None, horizon_months: Optional[int] = None,
              block_months: Optional[int] = None) -> Tuple[float, float]:
    """El p10 y el p90 del rendimiento anualizado a ``horizon_months``, en %.

    Bootstrap por bloques, como ``MonteCarloSimulator._simulate_paths``, sobre los
    log-rendimientos demeaned y recentrados en el central compuesto.
    """
    n_sims = n_sims or BACKTEST_METODO.n_sims
    h = horizon_months or BACKTEST_METODO.horizon_months
    b = block_months or BACKTEST_METODO.block_months
    logr = np.log1p(np.asarray(returns, dtype=float))
    shifted = logr - logr.mean() + math.log1p(central_pct / 100.0) / 12.0
    t = len(shifted)
    n_blocks = -(-h // b)
    starts = rng.integers(0, max(t - b + 1, 1), size=(n_sims, n_blocks))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(n_sims, -1)[:, :h]
    annual = np.expm1(shifted[np.clip(idx, 0, t - 1)].sum(axis=1) * 12.0 / h) * 100.0
    p10, p90 = np.percentile(annual, [10, 90])
    return float(p10), float(p90)


# --------------------------------------------------------------------------- #
#  Lo que pasó                                                                 #
# --------------------------------------------------------------------------- #

def realized_real_pct(rows: Sequence[MonthlyRow], i: int, asset: str,
                      horizon_months: Optional[int] = None) -> float:
    """El rendimiento real anualizado de ``i`` a ``i + horizon``. Sólo como resultado."""
    h = horizon_months or BACKTEST_METODO.horizon_months
    f = _FIELD[asset]
    return annualized_pct(getattr(rows[i], f), getattr(rows[i + h], f), _years(h))


# --------------------------------------------------------------------------- #
#  Cobertura                                                                   #
# --------------------------------------------------------------------------- #

def coverage(hits: Sequence[bool], *, target: Optional[float] = None,
             confidence: Optional[float] = None) -> CoverageResult:
    """Cobertura observada con su intervalo exacto de Clopper-Pearson."""
    target = BACKTEST_METODO.coverage_target if target is None else target
    confidence = BACKTEST_METODO.confidence if confidence is None else confidence
    n, k = len(hits), int(sum(bool(h) for h in hits))
    alpha = 1.0 - confidence
    low = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    high = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return CoverageResult(n=n, k=k, rate=k / n if n else 0.0, low=low, high=high,
                          passes=bool(n) and low <= target <= high)


# --------------------------------------------------------------------------- #
#  Las ventanas y la corrida                                                   #
# --------------------------------------------------------------------------- #

def _usable(row: MonthlyRow, asset: str) -> bool:
    if getattr(row, _FIELD[asset]) is None:
        return False
    return row.cape is not None if asset == "us_equity" else row.gs10 is not None


def evaluation_indexes(rows: Sequence[MonthlyRow], asset: str, *,
                       horizon_months: Optional[int] = None,
                       window_months: Optional[int] = None) -> List[int]:
    """Los meses con pasado suficiente para el Azar y futuro conocido para el resultado."""
    h = horizon_months or BACKTEST_METODO.horizon_months
    w = max(window_months or BACKTEST_METODO.azar_window_months,
            BACKTEST_METODO.inflation_proxy_months if asset == "us_bonds" else 0)
    return [i for i in range(w, len(rows) - h)
            if _usable(rows[i], asset) and getattr(rows[i + h], _FIELD[asset]) is not None]


def non_overlapping(indexes: Sequence[int], step: int) -> List[int]:
    """Uno cada ``step`` meses desde el primero: ventanas que no comparten un mes."""
    return [i for i in indexes if (i - indexes[0]) % step == 0] if indexes else []


def run_backtest(rows: Sequence[MonthlyRow], asset: str, *, seed: Optional[int] = None,
                 n_sims: Optional[int] = None) -> BacktestResult:
    """El backtest de una Clase sobre todas las fechas válidas."""
    rng = np.random.default_rng(BACKTEST_METODO.seed if seed is None else seed)
    h = BACKTEST_METODO.horizon_months
    windows = []
    for i in evaluation_indexes(rows, asset):
        central = central_at(rows, i, asset)
        p10, p90 = azar_band(trailing_returns(rows, i, asset), central, rng=rng, n_sims=n_sims)
        realized = realized_real_pct(rows, i, asset)
        windows.append(Window(index=i, date=f"{rows[i].year}-{rows[i].month:02d}",
                              central=central, p10=p10, p90=p90, realized=realized,
                              hit=p10 <= realized <= p90))
    chosen = set(non_overlapping([w.index for w in windows], h))
    nov = tuple(w for w in windows if w.index in chosen)
    return BacktestResult(
        asset=asset, windows=tuple(windows),
        overlapping=coverage([w.hit for w in windows]),
        non_overlapping=coverage([w.hit for w in nov]),
        non_overlapping_windows=nov,
        mean_bias_pp=float(np.mean([w.realized - w.central for w in windows])),
        mean_width_pp=float(np.mean([w.p90 - w.p10 for w in windows])),
    )


@dataclass(frozen=True)
class PhaseSensitivity:
    """Cuánto depende el veredicto del mes en que arrancan las ventanas sin superposición."""

    phases: int     # fases posibles (= el horizonte en meses)
    passing: int    # cuántas pasan la regla
    k_min: int
    k_max: int


def phase_sensitivity(result: BacktestResult, step: Optional[int] = None) -> PhaseSensitivity:
    """La regla sobre cada una de las ``step`` fases posibles; el veredicto usa la primera.

    Se informa, no se juzga: con unas 14 ventanas un mes de corrimiento puede cambiar
    k, y eso dice cuánta potencia tiene el backtest.
    """
    step = step or BACKTEST_METODO.horizon_months
    first = result.windows[0].index
    covs = [coverage([w.hit for w in result.windows if (w.index - first) % step == ph])
            for ph in range(step)]
    return PhaseSensitivity(phases=step, passing=sum(c.passes for c in covs),
                            k_min=min(c.k for c in covs), k_max=max(c.k for c in covs))
