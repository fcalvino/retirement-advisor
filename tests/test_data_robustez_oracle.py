"""AUDIT-DATOS — el CAGR cuenta años de calendario, y el corte del día local respeta el cambio de horario.

1. ``compute_cagr`` y ``compute_cagr_available`` hacían ``series.dropna()`` y después
   ``series.iloc[years]``: el exponente contaba *puntos*, no años. Un año que falta en el medio
   (``extract_financial_row`` ya descarta los NaN, así que el hueco llega como columna ausente)
   corría la ventana: ``[146.41, 133.1, 110, 100]`` con fechas 2024, 2023, 2021, 2020 son cuatro años
   de tramo, y el código viejo lo medía como tres (13,55 % en vez de 10,0 %). El ``years_used`` que
   informa ``compute_cagr_available`` también mentía. Ahora, con un índice de fechas, la ventana se
   mide en años transcurridos; sin fechas (índice entero) se conserva la cuenta por posición.

2. ``local_day_start_utc`` reemplazaba la hora a 00:00 sobre un offset fijo (el del instante
   ``now``), así que el día que cambia el horario de verano la medianoche local se convertía con el
   offset equivocado: una hora corrida dos días por año.

Los esperados salen de la definición (la tasa que compuesta N años lleva de la base al final; la
medianoche de Nueva York es 00:00 EDT = 04:00 UTC y 00:00 EST = 05:00 UTC), escritos a mano. Sin red.
"""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from config import THRESHOLDS
from data.clock import local_day_start_utc
from data.fetcher import compute_cagr, compute_cagr_available


def oracle_rate(start_value: float, end_value: float, n_years: int) -> float:
    """La tasa r tal que ``start_value`` compuesto ``n_years`` veces llega a ``end_value`` (bisección)."""
    def compound(rate: float) -> float:
        value = start_value
        for _ in range(n_years):
            value *= 1.0 + rate
        return value

    lo, hi = -0.9999, 100.0
    for _ in range(400):
        mid = (lo + hi) / 2.0
        if compound(mid) < end_value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _dated(pairs):
    """Serie newest-first con índice de fechas, como la deja ``extract_financial_row``."""
    return pd.Series([v for _, v in pairs], index=pd.DatetimeIndex([d for d, _ in pairs]), dtype=float)


GAP_2022 = _dated([
    ("2024-12-31", 146.41), ("2023-12-31", 133.1), ("2021-12-31", 110.0), ("2020-12-31", 100.0),
])


# --------------------------------------------------------------------------- #
#  compute_cagr_available                                                       #
# --------------------------------------------------------------------------- #


def test_a_missing_year_does_not_shorten_the_exponent():
    """2020 → 2024 son 4 años: 100 → 146,41 es 10,0 %/año, no 13,55 % sobre «3 años»."""
    cagr, years = compute_cagr_available(GAP_2022, target_years=5, min_years=3)
    assert years == 4
    assert cagr == pytest.approx(oracle_rate(100.0, 146.41, 4), rel=1e-9)
    assert cagr == pytest.approx(0.10, abs=1e-9)


def test_the_window_is_capped_at_the_target_in_calendar_years():
    """Seis puntos con un año faltante abarcan 6 años: con tope 5 se mide hasta 2019, no hasta 2018."""
    s = _dated([
        ("2024-12-31", 200.0), ("2023-12-31", 180.0), ("2021-12-31", 150.0),
        ("2020-12-31", 130.0), ("2019-12-31", 110.0), ("2018-12-31", 100.0),
    ])
    cagr, years = compute_cagr_available(s, target_years=5, min_years=3)
    assert years == 5
    assert cagr == pytest.approx(oracle_rate(110.0, 200.0, 5), rel=1e-9)


def test_a_gap_can_leave_the_span_below_the_minimum():
    """Cuatro puntos pero sólo dos años de tramo (2022-2024 y un punto repetido en el año) no alcanzan."""
    s = _dated([("2024-12-31", 130.0), ("2023-12-31", 120.0), ("2022-12-31", 110.0), ("2022-09-30", 100.0)])
    cagr, years = compute_cagr_available(s, target_years=5, min_years=3)
    assert (cagr, years) == (None, 0)


def test_contiguous_annual_dates_match_the_positional_answer():
    """Sin huecos, las fechas dan lo mismo que la cuenta por posición (no se movió el caso normal)."""
    s = _dated([("2024-12-31", 200.0), ("2023-12-31", 150.0), ("2022-12-31", 120.0), ("2021-12-31", 100.0)])
    cagr, years = compute_cagr_available(s, target_years=5, min_years=3)
    assert years == 3
    assert cagr == pytest.approx(oracle_rate(100.0, 200.0, 3), rel=1e-9)


def test_fiscal_year_ends_that_drift_a_few_days_still_count_as_whole_years():
    """Año fiscal de 52/53 semanas: los cierres se corren unos días y siguen siendo años enteros."""
    s = _dated([
        ("2024-09-28", 200.0), ("2023-09-30", 170.0), ("2022-10-01", 140.0), ("2021-10-02", 100.0),
    ])
    cagr, years = compute_cagr_available(s, target_years=5, min_years=3)
    assert years == 3
    assert cagr == pytest.approx(oracle_rate(100.0, 200.0, 3), rel=1e-9)


def test_a_timezone_aware_index_works():
    s = GAP_2022.copy()
    s.index = s.index.tz_localize("UTC")
    cagr, years = compute_cagr_available(s, target_years=5, min_years=3)
    assert years == 4
    assert cagr == pytest.approx(0.10, abs=1e-9)


def test_an_unsorted_dated_series_is_read_newest_first():
    shuffled = GAP_2022.iloc[[2, 0, 3, 1]]
    cagr, years = compute_cagr_available(shuffled, target_years=5, min_years=3)
    assert years == 4
    assert cagr == pytest.approx(0.10, abs=1e-9)


def test_a_nonpositive_start_is_still_not_a_base():
    s = _dated([("2024-12-31", 200.0), ("2023-12-31", 150.0), ("2022-12-31", 120.0), ("2021-12-31", -5.0)])
    assert compute_cagr_available(s, target_years=5, min_years=3) == (None, 0)


def test_without_dates_the_positional_count_is_kept():
    """Un índice entero no dice cuántos años pasaron: se cuenta por puntos, como siempre."""
    s = pd.Series([200.0, 150.0, 120.0, 100.0])
    cagr, years = compute_cagr_available(s, target_years=5, min_years=3)
    assert years == 3
    assert cagr == pytest.approx(oracle_rate(100.0, 200.0, 3), rel=1e-9)


def test_a_transition_year_stub_is_not_rounded_into_a_whole_year():
    """Cambio de fin de ejercicio: dic-24, dic-23, jun-22 (6 meses de transición), jun-21.

    Los cierres de jun-22 y jun-21 están a 2,5 y 3,5 años: no son «2 o 3» ni «3 o 4». Se los trata
    como ausentes en vez de redondearlos (el redondeo daba `years=4` con un tramo real de 3,5).
    """
    s = _dated([
        ("2024-12-31", 200.0), ("2023-12-31", 170.0), ("2022-06-30", 140.0), ("2021-06-30", 100.0),
    ])
    assert compute_cagr_available(s, target_years=5, min_years=3) == (None, 0)


def test_the_point_exactly_n_years_back_wins_over_a_stub_that_rounds_to_n():
    """dic-24, dic-23, jun-22 (2,5 años) y dic-21 (3,0 exactos): a 3 años es dic-21, no el stub."""
    s = _dated([
        ("2024-12-31", 260.0), ("2023-12-31", 190.0), ("2022-06-30", 140.0), ("2021-12-31", 100.0),
    ])
    assert compute_cagr(s, years=3) == pytest.approx(oracle_rate(100.0, 260.0, 3), rel=1e-9)
    cagr, years = compute_cagr_available(s, target_years=5, min_years=3)
    assert years == 3
    assert cagr == pytest.approx(oracle_rate(100.0, 260.0, 3), rel=1e-9)


def test_two_points_two_and_a_half_years_apart_do_not_meet_a_three_year_minimum():
    s = _dated([("2024-12-31", 130.0), ("2022-06-30", 100.0)])
    assert compute_cagr_available(s, target_years=5, min_years=3) == (None, 0)


def test_a_nat_in_the_index_is_ignored_not_fatal():
    idx = pd.DatetimeIndex(["2024-12-31", "2023-12-31", pd.NaT, "2021-12-31", "2020-12-31"])
    s = pd.Series([146.41, 133.1, 120.0, 110.0, 100.0], index=idx)
    cagr, years = compute_cagr_available(s, target_years=5, min_years=3)
    assert years == 4
    assert cagr == pytest.approx(0.10, abs=1e-9)
    assert compute_cagr(s, years=4) == pytest.approx(0.10, abs=1e-9)


def test_the_tolerance_comes_from_config():
    assert THRESHOLDS.cagr_date_tolerance_years == 0.25


def test_a_statement_with_a_missing_year_scores_the_real_window():
    """De punta a punta: el estado trae 2024, 2023, 2021 y 2020; el CAGR de ingresos es el de 4 años."""
    income = pd.DataFrame(
        {"Total Revenue": [146.41, 133.1, 110.0, 100.0]},
        index=["2024-12-31", "2023-12-31", "2021-12-31", "2020-12-31"],
    ).T
    result = FundamentalResult(symbol="GAP")
    FundamentalAnalyzer()._score_growth({}, income, pd.DataFrame(), result)
    assert result.revenue_cagr_years == 4
    assert result.revenue_cagr_5y == pytest.approx(10.0, abs=0.05)


# --------------------------------------------------------------------------- #
#  compute_cagr (ventana fija)                                                  #
# --------------------------------------------------------------------------- #


def test_fixed_window_uses_the_point_that_is_exactly_n_years_back():
    """A 4 años, 2020; a 3 años, 2021 (110). El código viejo tomaba ``iloc[3]`` = 2020 para los 3."""
    assert compute_cagr(GAP_2022, years=4) == pytest.approx(oracle_rate(100.0, 146.41, 4), rel=1e-9)
    assert compute_cagr(GAP_2022, years=3) == pytest.approx(oracle_rate(110.0, 146.41, 3), rel=1e-9)


def test_fixed_window_without_a_point_at_that_distance_gives_nothing():
    """Falta 2021 y se piden 3 años: no hay dato a esa distancia, y no se inventa uno cercano."""
    assert compute_cagr(GAP_2022.drop(pd.Timestamp("2021-12-31")), years=3) is None


def test_fixed_window_longer_than_the_history_gives_nothing():
    assert compute_cagr(GAP_2022, years=5) is None


def test_fixed_window_on_contiguous_dates_matches_the_positional_answer():
    s = _dated([("2024-12-31", 200.0), ("2023-12-31", 150.0), ("2022-12-31", 120.0), ("2021-12-31", 100.0)])
    assert compute_cagr(s, years=3) == pytest.approx(oracle_rate(100.0, 200.0, 3), rel=1e-9)


def test_fixed_window_without_dates_is_unchanged():
    s = pd.Series([200.0, 150.0, 120.0, 100.0])
    assert compute_cagr(s, years=3) == pytest.approx(oracle_rate(100.0, 200.0, 3), rel=1e-9)
    assert compute_cagr(s, years=5) is None


# --------------------------------------------------------------------------- #
#  local_day_start_utc en el cambio de horario                                  #
# --------------------------------------------------------------------------- #


@pytest.fixture
def new_york(monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.parametrize(
    "now_utc,expected_utc",
    [
        (datetime(2026, 1, 15, 18, 0), datetime(2026, 1, 15, 5, 0)),    # invierno: 00:00 EST
        (datetime(2026, 6, 1, 18, 0), datetime(2026, 6, 1, 4, 0)),      # verano: 00:00 EDT
        (datetime(2026, 3, 8, 18, 0), datetime(2026, 3, 8, 5, 0)),      # empieza el verano a las 02:00: la medianoche fue EST
        (datetime(2026, 11, 1, 18, 0), datetime(2026, 11, 1, 4, 0)),    # termina el verano a las 02:00: la medianoche fue EDT
        (datetime(2026, 3, 9, 3, 0), datetime(2026, 3, 8, 5, 0)),       # 23:00 EDT del 8: sigue siendo el día 8
    ],
)
def test_local_midnight_is_converted_with_the_offset_of_that_midnight(new_york, now_utc, expected_utc):
    assert local_day_start_utc(now_utc) == expected_utc
