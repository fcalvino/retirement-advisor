"""
Oráculo — PIT-1: el outcome a 1 año de ``synthetic_recommendation``.

El motor point-in-time guarda F-Scores sintéticos con 8 columnas de outcome que
nada escribía (PR 5/N). PIT-1 las mide, con el alcance que decidió el usuario el
2026-09-26:

- un ticker deslistado antes del horizonte queda con outcome ``NULL`` **y
  marcado** — no se descarta (sesgo de supervivencia) y, sobre todo, no se
  puntúa contra su último cierre de años atrás;
- el benchmark es SPY total-return (``TRACK_RECORD.benchmark`` con el cierre
  ajustado de ``get_history``);
- un corte a menos de 1 año de hoy queda pendiente, no se estima.

Los valores esperados salen de la definición (retorno = P_h / P_0 − 1, exceso =
retorno − retorno del benchmark), escritos a mano sobre historias sintéticas
fijas — nunca preguntándole al motor. Sin red: la historia se inyecta.

El caso que un lookup ingenuo hace pasar mal es el del deslistado:
``track_record_scorer._price_on_or_before`` devuelve el último cierre ≤ fecha
sin límite de antigüedad, así que un ticker que dejó de cotizar en diciembre
«tendría» precio en junio del año siguiente.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from analysis.scoring import PiotroskiDetail
from analysis.synthetic_backtest import (
    OUTCOME_DELISTED,
    OUTCOME_NO_HISTORY,
    OUTCOME_PARTIAL,
    OUTCOME_SCORED,
    SyntheticBacktestStore,
)
from analysis.synthetic_outcome import price_near, score_due_outcomes
from config import SYNTHETIC_BACKTEST, TRACK_RECORD

BENCH = TRACK_RECORD.benchmark
HORIZON = timedelta(days=SYNTHETIC_BACKTEST.horizon_days)
STALE = SYNTHETIC_BACKTEST.max_price_staleness_days
TODAY = date(2026, 9, 26)


def _frame(prices: dict) -> pd.DataFrame:
    """Historia diaria con la forma de ``get_history``: ``DatetimeIndex``
    llamado ``Date`` y columnas en minúscula. ``prices`` mapea fecha → cierre.
    """
    idx = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in prices), name="Date")
    closes = [prices[d.date()] for d in idx]
    return pd.DataFrame({"close": closes, "open": closes, "high": closes, "low": closes, "volume": 1}, index=idx)


def _step(start: date, end: date, *, before: float, cut: date, after: float, horizon: date, at_h: float) -> dict:
    """Días hábiles de ``start`` a ``end``: ``before`` hasta ``cut`` inclusive,
    ``after`` en el medio, ``at_h`` desde ``horizon`` inclusive."""
    out = {}
    for ts in pd.bdate_range(start, end):
        d = ts.date()
        out[d] = before if d <= cut else (at_h if d >= horizon else after)
    return out


def _detail() -> PiotroskiDetail:
    return PiotroskiDetail(f1_roa_positive=True, f2_ocf_positive=True)


def _store_with(*pairs) -> SyntheticBacktestStore:
    store = SyntheticBacktestStore(":memory:")
    for symbol, as_of in pairs:
        store.log_piotroski(symbol, as_of, _detail())
    return store


def _history_from(frames: dict):
    calls = []

    def history(symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        return frames.get(symbol, pd.DataFrame())

    history.calls = calls
    return history


def _row(store, symbol):
    return store.get_all(symbol=symbol)[0]


# --------------------------------------------------------------------------- #
#  1. Retorno y exceso desde la definición                                     #
# --------------------------------------------------------------------------- #

def test_return_and_excess_follow_the_definition():
    cut = date(2021, 6, 1)
    hz = cut + HORIZON  # 2022-06-01, miércoles
    frames = {
        "AAPL": _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=100.0, cut=cut, after=110.0, horizon=hz, at_h=120.0)),
        BENCH: _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=400.0, cut=cut, after=420.0, horizon=hz, at_h=440.0)),
    }
    store = _store_with(("AAPL", cut))

    score_due_outcomes(store, today=TODAY, history=_history_from(frames))

    row = _row(store, "AAPL")
    assert row.outcome_status == OUTCOME_SCORED
    assert row.price_at_cutoff == pytest.approx(100.0)
    assert row.price_at_horizon == pytest.approx(120.0)
    assert row.horizon_date == hz.isoformat()
    assert row.return_pct == pytest.approx(20.0)              # 120/100 − 1
    assert row.benchmark_return_pct == pytest.approx(10.0)    # 440/400 − 1
    assert row.excess_return_pct == pytest.approx(10.0)       # 20 − 10
    assert row.benchmark_missing is False
    assert row.outcome_scored_at is not None


# --------------------------------------------------------------------------- #
#  2. Un corte a menos de 1 año queda pendiente                               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("days_before_today", [0, 1, 100])
def test_a_cutoff_whose_horizon_has_not_passed_is_left_untouched(days_before_today):
    """Pendiente mientras el horizonte no sea estrictamente anterior a hoy: el
    cierre del día del horizonte todavía no existe cuando ese día es hoy."""
    cut = TODAY - HORIZON + timedelta(days=days_before_today)
    frames = {"AAPL": _frame({cut: 100.0, TODAY - timedelta(days=1): 120.0}), BENCH: _frame({cut: 400.0})}
    store = _store_with(("AAPL", cut))

    summary = score_due_outcomes(store, today=TODAY, history=_history_from(frames))

    row = _row(store, "AAPL")
    assert row.outcome_status is None
    assert row.price_at_cutoff is None
    assert row.return_pct is None
    assert row.horizon_date is None
    assert summary["pending"] == 1


# --------------------------------------------------------------------------- #
#  3. Deslistado: NULL y marcado, nunca el último cierre                       #
# --------------------------------------------------------------------------- #

def test_a_ticker_delisted_before_the_horizon_is_marked_not_scored_at_its_last_close():
    cut = date(2021, 6, 1)
    hz = cut + HORIZON
    last = date(2021, 12, 31)  # deja de cotizar cinco meses antes del horizonte
    frames = {
        "GONE": _frame({d.date(): 50.0 for d in pd.bdate_range(date(2021, 5, 1), last)}),
        BENCH: _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=400.0, cut=cut, after=420.0, horizon=hz, at_h=440.0)),
    }
    store = _store_with(("GONE", cut))

    summary = score_due_outcomes(store, today=TODAY, history=_history_from(frames))

    row = _row(store, "GONE")
    assert row.outcome_status == OUTCOME_DELISTED
    assert row.price_at_horizon is None
    assert row.return_pct is None
    assert row.excess_return_pct is None
    assert row.price_at_cutoff == pytest.approx(50.0)  # lo que sí se sabe queda
    assert summary["delisted"] == 1


def test_staleness_boundary_is_the_config_value():
    """Una barra a exactamente ``max_price_staleness_days`` del horizonte se
    usa; una más vieja no."""
    cut = date(2021, 6, 1)
    hz = cut + HORIZON
    bench = _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=400.0, cut=cut, after=420.0, horizon=hz, at_h=440.0))

    ok = _frame({cut: 100.0, hz - timedelta(days=STALE): 130.0})
    stale = _frame({cut: 100.0, hz - timedelta(days=STALE + 1): 130.0})
    assert price_near(ok, hz, STALE) == pytest.approx(130.0)
    assert price_near(stale, hz, STALE) is None

    store = _store_with(("OK", cut), ("OLD", cut))
    score_due_outcomes(store, today=TODAY, history=_history_from({"OK": ok, "OLD": stale, BENCH: bench}))
    assert _row(store, "OK").outcome_status == OUTCOME_SCORED
    assert _row(store, "OK").return_pct == pytest.approx(30.0)
    assert _row(store, "OLD").outcome_status == OUTCOME_DELISTED


# --------------------------------------------------------------------------- #
#  4. Fin de semana: el cierre hábil anterior, nunca uno posterior             #
# --------------------------------------------------------------------------- #

def test_weekend_dates_use_the_previous_close_and_never_a_later_one():
    cut = date(2021, 6, 5)     # sábado → viernes 2021-06-04
    hz = cut + HORIZON         # 2022-06-05, domingo → viernes 2022-06-03
    assert cut.weekday() == 5 and hz.weekday() == 6
    prices = {
        date(2021, 6, 4): 80.0,
        date(2021, 6, 7): 999.0,   # lunes posterior al corte: no se puede usar
        date(2022, 6, 3): 100.0,
        date(2022, 6, 6): 999.0,   # lunes posterior al horizonte: tampoco
    }
    bench = {date(2021, 6, 4): 400.0, date(2021, 6, 7): 1.0, date(2022, 6, 3): 420.0, date(2022, 6, 6): 1.0}
    store = _store_with(("WKND", cut))

    score_due_outcomes(store, today=TODAY, history=_history_from({"WKND": _frame(prices), BENCH: _frame(bench)}))

    row = _row(store, "WKND")
    assert row.price_at_cutoff == pytest.approx(80.0)
    assert row.price_at_horizon == pytest.approx(100.0)
    assert row.return_pct == pytest.approx(25.0)           # 100/80 − 1
    assert row.benchmark_return_pct == pytest.approx(5.0)  # 420/400 − 1
    assert row.excess_return_pct == pytest.approx(20.0)


# --------------------------------------------------------------------------- #
#  5. Sin benchmark: desconocido, no cero (U2-4), y se completa después        #
# --------------------------------------------------------------------------- #

def test_missing_benchmark_is_unknown_not_zero_and_is_completed_later():
    cut = date(2021, 6, 1)
    hz = cut + HORIZON
    ticker = _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=100.0, cut=cut, after=110.0, horizon=hz, at_h=120.0))
    store = _store_with(("AAPL", cut))

    first = score_due_outcomes(store, today=TODAY, history=_history_from({"AAPL": ticker}))

    row = _row(store, "AAPL")
    assert row.outcome_status == OUTCOME_PARTIAL
    assert row.return_pct == pytest.approx(20.0)
    assert row.benchmark_return_pct is None
    assert row.excess_return_pct is None      # no 20.0: el mercado es desconocido, no plano
    assert row.benchmark_missing is True
    assert first["partial"] == 1

    bench = _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=400.0, cut=cut, after=420.0, horizon=hz, at_h=440.0))
    score_due_outcomes(store, today=TODAY, history=_history_from({"AAPL": ticker, BENCH: bench}))

    row = _row(store, "AAPL")
    assert row.outcome_status == OUTCOME_SCORED
    assert row.excess_return_pct == pytest.approx(10.0)
    assert row.benchmark_missing is False


# --------------------------------------------------------------------------- #
#  6. Sin historia: marcado y reintentable                                     #
# --------------------------------------------------------------------------- #

def test_no_history_is_marked_and_retried():
    cut = date(2021, 6, 1)
    store = _store_with(("NODATA", cut))

    score_due_outcomes(store, today=TODAY, history=_history_from({}))
    assert _row(store, "NODATA").outcome_status == OUTCOME_NO_HISTORY
    assert _row(store, "NODATA").return_pct is None

    hz = cut + HORIZON
    frames = {
        "NODATA": _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=10.0, cut=cut, after=11.0, horizon=hz, at_h=15.0)),
        BENCH: _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=400.0, cut=cut, after=420.0, horizon=hz, at_h=400.0)),
    }
    score_due_outcomes(store, today=TODAY, history=_history_from(frames))
    row = _row(store, "NODATA")
    assert row.outcome_status == OUTCOME_SCORED
    assert row.return_pct == pytest.approx(50.0)
    assert row.excess_return_pct == pytest.approx(50.0)  # benchmark plano medido, no desconocido


# --------------------------------------------------------------------------- #
#  7. Idempotencia                                                             #
# --------------------------------------------------------------------------- #

def test_a_scored_row_is_not_rescored():
    cut = date(2021, 6, 1)
    hz = cut + HORIZON
    frames = {
        "AAPL": _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=100.0, cut=cut, after=110.0, horizon=hz, at_h=120.0)),
        BENCH: _frame(_step(date(2021, 5, 1), date(2022, 7, 1), before=400.0, cut=cut, after=420.0, horizon=hz, at_h=440.0)),
    }
    store = _store_with(("AAPL", cut))
    score_due_outcomes(store, today=TODAY, history=_history_from(frames))
    stamp = _row(store, "AAPL").outcome_scored_at

    history = _history_from({})  # si se volviera a medir, quedaría no_history
    second = score_due_outcomes(store, today=TODAY + timedelta(days=30), history=history)

    row = _row(store, "AAPL")
    assert row.outcome_status == OUTCOME_SCORED
    assert row.outcome_scored_at == stamp
    assert history.calls == []
    assert second["scored"] == 0


# --------------------------------------------------------------------------- #
#  8. Aislamiento estructural del track record (N6)                            #
# --------------------------------------------------------------------------- #

def test_the_outcome_module_does_not_import_the_track_record():
    """Mismo argumento que ``analysis/synthetic_backtest.py``: una tabla que no
    está no puede filtrarse al hit rate publicado. Importar
    ``track_record_scorer`` para reusar su lookup arrastraría
    ``analysis.track_record`` — se verifica en un proceso limpio, porque en
    este la suite ya lo importó."""
    root = Path(__file__).resolve().parent.parent
    code = (
        "import sys; import analysis.synthetic_outcome; "
        "print(sorted(m for m in sys.modules if m.startswith('analysis.track_record')))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
