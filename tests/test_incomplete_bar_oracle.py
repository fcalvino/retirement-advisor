"""La barra de la semana en curso no es una medición (U5-19).

El defecto, de punta a punta:

  1. yfinance devuelve una barra para la *semana en curso*. Pedida un domingo o un
     lunes temprano, vuelve con ``open/high/low/close`` en NaN y sólo un ``volume``
     parcial. ``data/fetcher.py::get_history`` la cacheaba tal cual.
  2. ``analysis/technical.py::_compute_trend`` hace ``price.rolling(200).mean()``.
     Un solo NaN al final envenena las **tres** ventanas a la vez, así que
     ``above_sma50/100/200`` y ``sma200_slope_pct`` caen a ``None``.
  3. ``_derive_signal`` se queda sin componentes de tendencia → ``NEUTRAL``.
  4. ``analysis/strategy.py``: ``require_technical_uptrend`` reescribe todo
     BUY / STRONG BUY como HOLD con el motivo «Sin tendencia alcista confirmada».

Es una **no-medición presentada como medición**, la misma clase de defecto que
U3-1 cerró para ``above_sma200`` y SIGNAL-5 para ``signal``: la fila pasa el
control de calidad (`Datos: OK`) y el usuario lee un juicio de mercado donde no
hay dato. Medido sobre la caché real: 84 de 108 historias.

El oráculo tiene dos mitades que **deben** convivir, y ese es el punto:

  * una serie sana con la última barra vacía vuelve a medir — el NaN era ruido;
  * una serie realmente corta sigue devolviendo ``None`` — ahí ``None`` es la
    respuesta correcta y el fix no puede borrarla.

Por eso cada aserción de la primera mitad tiene su espejo en la segunda.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import data.fetcher as fetcher
from analysis.strategy import (
    RetirementStrategy,
    technical_trend_not_measurable,
    technical_uptrend_confirmed,
)
from analysis.technical import TechnicalAnalyzer
from config import FETCH, STRATEGY, TECHNICAL

# --------------------------------------------------------------------------- #
#  Fixtures de precio                                                          #
# --------------------------------------------------------------------------- #

#: Suficiente para las tres medias (50 / 100 / 200) y para la pendiente a 26w.
_LONG = 300
#: Corre el análisis (>= 50 barras) pero no alcanza la media de 200 semanas.
_SHORT = 60


def _weekly(n: int, *, start: float = 50.0, end: float = 150.0) -> pd.DataFrame:
    """Serie semanal sana, en alza monotónica — una tendencia inequívoca."""
    index = pd.date_range("2020-01-05", periods=n, freq="W")
    index.name = "Date"
    close = pd.Series(np.linspace(start, end, n), index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": [1_000_000] * n,
        },
        index=index,
    )


def _short() -> pd.DataFrame:
    """Serie corta y *mansa*: sin historia de 200w, pero sin disparar el bloqueo
    parabólico de ``_check_safety_blocks`` — queremos aislar el gate de tendencia."""
    return _weekly(_SHORT, start=100.0, end=110.0)


def _with_empty_last_bar(df: pd.DataFrame) -> pd.DataFrame:
    """La barra en curso tal como llega del feed: OHLC en NaN, volumen parcial.

    Copiado de una entrada real de la caché (``history:AAPL:10y:1wk``,
    ``2026-09-21``): el ``volume`` **sí** viene, que es justo por qué filtrar por
    volumen conservaría la fila a descartar.
    """
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        out.iloc[-1, out.columns.get_loc(col)] = np.nan
    out.iloc[-1, out.columns.get_loc("volume")] = 34_913_171
    return out


def _as_cached(df: pd.DataFrame) -> list[dict]:
    """Lo que la caché guarda: records con la fecha ya stringificada."""
    records = df.reset_index().to_dict(orient="records")
    for row in records:
        row["Date"] = str(row["Date"])
    return records


# --------------------------------------------------------------------------- #
#  1. El técnico vuelve a medir — y sigue sin medir cuando no hay historia      #
# --------------------------------------------------------------------------- #

class TestTrendSurvivesTheIncompleteBar:
    """Una serie sana con la última barra vacía no puede perder la tendencia."""

    def test_the_defect_reproduces_without_the_fix(self):
        """Guarda del diagnóstico: el NaN al final realmente envenena las tres medias."""
        poisoned = _with_empty_last_bar(_weekly(_LONG))
        result = TechnicalAnalyzer().analyze("NANBAR", poisoned)

        assert result.above_sma50 is None
        assert result.above_sma100 is None
        assert result.above_sma200 is None
        assert result.sma200_slope_pct is None
        assert result.signal == "NEUTRAL"

    def test_the_fetcher_hands_the_analyzer_a_measurable_frame(self):
        """El fix, en el punto donde el motor lo consume de verdad."""
        clean = _weekly(_LONG)
        with patch.object(
            fetcher.cache, "get", return_value=_as_cached(_with_empty_last_bar(clean))
        ):
            served = fetcher.get_history("NANBAR", period="10y", interval="1wk")

        result = TechnicalAnalyzer().analyze("NANBAR", served)

        assert result.above_sma200 is True
        assert result.above_sma100 is True
        assert result.above_sma50 is True
        assert result.sma200_slope_pct is not None
        assert result.signal == "BULLISH"

    def test_the_verdict_matches_the_series_without_the_empty_bar(self):
        """El oráculo: descartar la no-medición debe dar *exactamente* lo mismo
        que si el feed nunca la hubiera emitido."""
        clean = _weekly(_LONG - 1)
        poisoned = _with_empty_last_bar(_weekly(_LONG))
        poisoned.iloc[:-1] = clean.iloc[:].to_numpy()

        with patch.object(fetcher.cache, "get", return_value=_as_cached(poisoned)):
            served = fetcher.get_history("NANBAR", period="10y", interval="1wk")

        pd.testing.assert_frame_equal(served, clean, check_freq=False)

    def test_current_price_is_a_price_again(self):
        """``current_price`` se leía ``nan`` y viajaba a la UI como precio."""
        clean = _weekly(_LONG)
        with patch.object(
            fetcher.cache, "get", return_value=_as_cached(_with_empty_last_bar(clean))
        ):
            served = fetcher.get_history("NANBAR", period="10y", interval="1wk")

        result = TechnicalAnalyzer().analyze("NANBAR", served)
        assert not pd.isna(result.current_price)
        assert result.current_price > 0


class TestShortSeriesStillAnswersNone:
    """La mitad que el fix no puede romper: sin historia, ``None`` es correcto."""

    def test_a_genuinely_short_series_has_no_200w_mean(self):
        result = TechnicalAnalyzer().analyze("SHORT", _short())

        assert result.above_sma50 is True       # esa ventana sí entra
        assert result.above_sma200 is None      # esta no, y debe decirlo
        assert result.sma200_slope_pct is None

    def test_dropping_the_empty_bar_does_not_invent_history(self):
        """Serie corta *y* con barra vacía: se descarta la barra y sigue sin medir."""
        with patch.object(
            fetcher.cache,
            "get",
            return_value=_as_cached(_with_empty_last_bar(_short())),
        ):
            served = fetcher.get_history("SHORT", period="10y", interval="1wk")

        assert len(served) == _SHORT - 1
        result = TechnicalAnalyzer().analyze("SHORT", served)
        assert result.above_sma200 is None

    def test_a_frame_below_the_analysis_floor_stays_not_measurable(self):
        """Menos de 50 barras: el analyzer ni corre. El default es NO medible.

        (No se puede pasar un frame vacío: ``analyze`` lo trata como "no me
        pasaron datos" y sale a la red.)"""
        result = TechnicalAnalyzer().analyze("NADA", _weekly(10))
        assert result.signal == TECHNICAL.signal_not_measurable
        assert result.above_sma200 is None


# --------------------------------------------------------------------------- #
#  2. El filtro del fetcher, acotado a propósito                                #
# --------------------------------------------------------------------------- #

class TestDropTrailingEmptyBars:
    def test_an_interior_nan_is_left_alone(self):
        """Un agujero en el feed es otra patología: borrarlo correría las ventanas."""
        df = _weekly(_LONG)
        df.iloc[10, df.columns.get_loc("close")] = np.nan

        out = fetcher._drop_trailing_empty_bars(df, "HOLE")
        assert len(out) == _LONG
        assert pd.isna(out["close"].iloc[10])

    def test_several_trailing_empty_bars_go_together(self):
        df = _weekly(_LONG)
        df.iloc[-3:, df.columns.get_loc("close")] = np.nan

        out = fetcher._drop_trailing_empty_bars(df, "TAIL")
        assert len(out) == _LONG - 3
        assert out["close"].notna().all()

    def test_a_frame_with_no_close_at_all_is_not_emptied(self):
        """"No hay datos" ya lo maneja el analyzer; vaciar acá sería un fallo de fetch."""
        df = _weekly(10)
        df["close"] = np.nan

        out = fetcher._drop_trailing_empty_bars(df, "VACIO")
        assert len(out) == 10

    def test_a_clean_frame_is_returned_unchanged(self):
        df = _weekly(_LONG)
        pd.testing.assert_frame_equal(
            fetcher._drop_trailing_empty_bars(df, "OK"), df, check_freq=False
        )

    def test_the_empty_frame_survives(self):
        assert fetcher._drop_trailing_empty_bars(pd.DataFrame(), "X").empty

    def test_the_flag_lives_in_config_and_turns_it_off(self):
        """CONTEXT §5: el flag va en ``config.py``, y apagarlo restaura lo previo."""
        assert FETCH.drop_trailing_empty_bars is True

        df = _with_empty_last_bar(_weekly(_LONG))
        with patch.object(FETCH, "drop_trailing_empty_bars", False):
            out = fetcher._drop_trailing_empty_bars(df, "OFF")
        assert len(out) == _LONG


class TestBothCachePathsAreFiltered:
    """El TTL de 24 h es la razón de filtrar también en lectura.

    Filtrar sólo antes de ``cache.set`` dejaría envenenadas las entradas que ya
    están en disco hasta que expiren solas — exactamente la ventana en la que el
    defecto se observó (84 historias cacheadas a las 00:27 UTC, vigentes 24 h).
    """

    def test_the_cache_hit_path_filters(self):
        with patch.object(
            fetcher.cache,
            "get",
            return_value=_as_cached(_with_empty_last_bar(_weekly(_LONG))),
        ):
            served = fetcher.get_history("WARM", period="10y", interval="1wk")

        assert len(served) == _LONG - 1
        assert served["close"].notna().all()

    def test_the_network_path_does_not_cache_the_empty_bar(self):
        poisoned = _with_empty_last_bar(_weekly(_LONG))

        with (
            patch.object(fetcher.cache, "get", return_value=None),
            patch.object(fetcher, "_fetch_with_retry", return_value=poisoned),
            patch.object(fetcher.cache, "set") as stored,
        ):
            out = fetcher.get_history("COLD", period="10y", interval="1wk")

        assert len(out) == _LONG - 1
        records = stored.call_args[0][1]
        assert len(records) == _LONG - 1
        assert not any(pd.isna(r["close"]) for r in records)


# --------------------------------------------------------------------------- #
#  3. La consecuencia que se veía: el muro de HOLD                              #
# --------------------------------------------------------------------------- #

def _fund(*, score: float, symbol: str = "TEST") -> SimpleNamespace:
    """Fundamentals de BUY holgado, con margen de seguridad."""
    return SimpleNamespace(
        symbol=symbol,
        total_score=score,
        adjusted_score=score,
        is_crypto=False,
        debt_equity=0.5,
        pb_ratio=2.0,
        margin_of_safety_pct=15.0,
        graham_value=100.0,
        is_value_stock=lambda: True,
        roe=20.0,
        revenue_cagr_5y=10.0,
        fcf_yield=4.0,
        payout_ratio=40.0,
        warnings=[],
        data_quality=None,
        tailwind_classification="Neutral",
        tailwind_detail=None,
    )


def _decide(technical) -> object:
    return RetirementStrategy().decide(_fund(score=STRATEGY.buy_score + 5), technical)


class TestBuyNoLongerDegradesOnAnEmptyBar:
    def test_the_defect_reproduces_on_the_poisoned_frame(self):
        """Guarda del diagnóstico: fundamentals de BUY + barra vacía = HOLD."""
        technical = TechnicalAnalyzer().analyze(
            "NANBAR", _with_empty_last_bar(_weekly(_LONG))
        )
        decision = _decide(technical)

        assert decision.action == "HOLD"

    def test_with_the_fetcher_filter_the_buy_survives(self):
        with patch.object(
            fetcher.cache,
            "get",
            return_value=_as_cached(_with_empty_last_bar(_weekly(_LONG))),
        ):
            served = fetcher.get_history("NANBAR", period="10y", interval="1wk")

        technical = TechnicalAnalyzer().analyze("NANBAR", served)
        assert technical_uptrend_confirmed(technical) is True

        decision = _decide(technical)
        assert decision.action in ("BUY", "STRONG BUY")
        assert "tendencia" not in (decision.decisive_reason or "").lower()


# --------------------------------------------------------------------------- #
#  4. El motivo distingue «no medible» de «no alcista»                          #
# --------------------------------------------------------------------------- #

class TestTheReasonToldToTheUser:
    def test_a_measured_downtrend_still_says_not_confirmed(self):
        """Acá sí hubo medición: la media de 200 existe y el precio está debajo."""
        technical = TechnicalAnalyzer().analyze(
            "BAJISTA", _weekly(_LONG, start=150.0, end=50.0)
        )
        assert technical.above_sma200 is False
        assert technical_trend_not_measurable(technical) is False

        decision = _decide(technical)
        assert decision.action == "HOLD"
        assert decision.decisive_reason == "Sin tendencia alcista confirmada — no agregar"

    def test_an_unmeasurable_trend_says_so(self):
        """Serie corta: el gate falla, pero no porque el mercado haya dicho algo."""
        technical = TechnicalAnalyzer().analyze("CORTA", _short())
        assert technical.above_sma200 is None
        assert technical_trend_not_measurable(technical) is True

        decision = _decide(technical)
        assert decision.action == "HOLD"
        assert decision.decisive_reason == (
            "Tendencia no medible — sin historia suficiente, no agregar"
        )
        assert any("not measurable" in r for r in decision.rationale)

    @pytest.mark.parametrize(
        "signal, above_sma200, expected",
        [
            (TECHNICAL.signal_not_measurable, None, True),
            ("NEUTRAL", None, True),      # 50–199 barras: momentum sí, 200w no
            ("NEUTRAL", False, False),
            ("BEARISH", False, False),
            ("BULLISH", True, False),
        ],
    )
    def test_the_predicate_separates_the_two_states(self, signal, above_sma200, expected):
        technical = SimpleNamespace(signal=signal, above_sma200=above_sma200)
        assert technical_trend_not_measurable(technical) is expected
