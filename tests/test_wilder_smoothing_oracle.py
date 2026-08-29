"""Oráculo de U3-2 — ATR y ADX se suavizan como Wilder los definió.

El defecto: `_atr` y `_adx` usaban `ewm(span=period)`, que es `alpha =
2/(period+1)`. Wilder es `alpha = 1/period`. Para el `period=14` que usa todo el
módulo eso es **0,0714 contra 0,1333**: el suavizado del motor era casi el doble
de reactivo que el del indicador que decía calcular. El RSI (`technical.py:304`)
ya estaba bien — la referencia correcta vivía en el mismo archivo.

**Por qué este archivo no busca la palabra `span`.** Un grep sobre el código
verifica que alguien escribió lo que se le pidió, no que el número esté bien;
si mañana el suavizado se reescribe con `rolling` o con un `apply`, un grep de
`span` pasa en verde sobre matemática rota. CONTEXT §5 lo pide explícito
("tests del motor = oráculo, no auto-consistencia"): acá abajo hay una
implementación de referencia **independiente**, escrita desde la definición de
Wilder con un bucle lento —`avg = (avg*(n-1) + x)/n`— y contra ella se mide el
motor. El bucle es deliberadamente ineficiente: es más fácil de leer contra el
libro que contra pandas.

**El anti-cheat.** El MACD (`technical.py:315-318`) usa `span` y eso está
**bien**: un MACD se define con EMA, no con Wilder. `TestElMACDNoEsWilder`
falla si alguien "termina el trabajo" convirtiéndolo también.

**Cuatro sitios, tres que mueven el número.** La fila del backlog citaba tres
suavizados del ADX y se quedaba corta: son cuatro. Pero medidos por mutación,
sólo tres cambian el resultado — el del TR dentro de `_adx` se **cancela**,
porque `S(TR)` es factor común de `DI⁺` y `DI⁻` y el `DX` los divide entre sí.
Se corrigió igual (es la formulación del libro), y hay un test que fija la
cancelación para que el mutante sobreviviente no se lea como falta de cobertura.

**Sobre el arranque de la serie.** Wilder siembra su promedio con la media
simple de las primeras `n` observaciones; `ewm(adjust=False)` lo siembra con la
primera observación sola. Las dos convergen: la diferencia se apaga como
`(1 - 1/n)^k`. Sobre las ~520 barras semanales de 10 años que el motor
realmente usa eso es 1e-17, o sea nada — pero es una convergencia, no una
identidad, así que `TestElArranqueConverge` la mide en vez de dejarla implícita.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.technical import TechnicalAnalyzer  # noqa: E402

PERIOD = 14


# ========================================================================== #
#  Implementación de referencia — desde la definición, no desde el motor      #
# ========================================================================== #

def wilder_smooth(values: List[float], n: int) -> List[Optional[float]]:
    """Suavizado de Wilder, bucle lento: `avg = (avg*(n-1) + x) / n`.

    Se siembra con la media simple de las primeras `n` observaciones, que es
    como Wilder lo define en *New Concepts in Technical Trading Systems*. Antes
    de tener `n` observaciones no hay promedio: `None`, no un cero.
    """
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < n:
        return out
    avg = sum(values[:n]) / n
    out[n - 1] = avg
    for i in range(n, len(values)):
        avg = (avg * (n - 1) + values[i]) / n
        out[i] = avg
    return out


def ema_smooth(values: List[float], span: int) -> List[float]:
    """EMA clásica, bucle lento: `alpha = 2/(span+1)`, sembrada en el primer valor.

    Es el `adjust=False` de pandas escrito a mano. Existe acá para el
    anti-cheat del MACD: sin una referencia de EMA, "el MACD no es Wilder" sólo
    se podría afirmar por descarte.
    """
    alpha = 2.0 / (span + 1.0)
    out = [values[0]]
    for x in values[1:]:
        out.append(alpha * x + (1 - alpha) * out[-1])
    return out


def true_range(df: pd.DataFrame) -> List[float]:
    """TR = max(h-l, |h-c_prev|, |l-c_prev|). La primera barra no tiene previo."""
    h, low, c = df["high"].tolist(), df["low"].tolist(), df["close"].tolist()
    tr = [h[0] - low[0]]
    for i in range(1, len(h)):
        tr.append(max(h[i] - low[i], abs(h[i] - c[i - 1]), abs(low[i] - c[i - 1])))
    return tr


def atr_reference(df: pd.DataFrame, n: int = PERIOD) -> Optional[float]:
    """ATR de Wilder: el suavizado de Wilder del True Range."""
    return wilder_smooth(true_range(df), n)[-1]


def adx_reference(df: pd.DataFrame, n: int = PERIOD) -> Optional[float]:
    """ADX de Wilder, entero, desde la definición.

    +DM/-DM por barra → los tres suavizados de Wilder (TR, +DM, -DM) →
    ±DI = 100 · S(DM)/S(TR) → DX = 100 · |+DI − −DI| / (+DI + −DI) →
    ADX = suavizado de Wilder del DX.
    """
    h, low = df["high"].tolist(), df["low"].tolist()
    dm_plus, dm_minus = [0.0], [0.0]
    for i in range(1, len(h)):
        up, down = h[i] - h[i - 1], low[i - 1] - low[i]
        dm_plus.append(up if up > down and up > 0 else 0.0)
        dm_minus.append(down if down > up and down > 0 else 0.0)

    s_tr = wilder_smooth(true_range(df), n)
    s_plus = wilder_smooth(dm_plus, n)
    s_minus = wilder_smooth(dm_minus, n)

    dx: List[float] = []
    for tr_v, p_v, m_v in zip(s_tr, s_plus, s_minus):
        if tr_v is None or tr_v == 0:
            continue
        di_p, di_m = 100.0 * p_v / tr_v, 100.0 * m_v / tr_v
        total = di_p + di_m
        dx.append(0.0 if total == 0 else 100.0 * abs(di_p - di_m) / total)

    return wilder_smooth(dx, n)[-1] if len(dx) >= n else None


def adx_reference_con_tr_ema(df: pd.DataFrame, n: int = PERIOD) -> Optional[float]:
    """`adx_reference` con el TR suavizado como EMA en vez de como Wilder.

    Sirve para una sola cosa: mostrar que ese suavizado se cancela. Ver
    `TestADXEsWilder.test_el_suavizado_del_TR_se_cancela_dentro_del_ADX`.
    """
    h, low = df["high"].tolist(), df["low"].tolist()
    dm_plus, dm_minus = [0.0], [0.0]
    for i in range(1, len(h)):
        up, down = h[i] - h[i - 1], low[i - 1] - low[i]
        dm_plus.append(up if up > down and up > 0 else 0.0)
        dm_minus.append(down if down > up and down > 0 else 0.0)

    ema = ema_smooth(true_range(df), n)
    s_tr: List[Optional[float]] = [None] * (n - 1) + ema[n - 1:]
    s_plus = wilder_smooth(dm_plus, n)
    s_minus = wilder_smooth(dm_minus, n)

    dx: List[float] = []
    for tr_v, p_v, m_v in zip(s_tr, s_plus, s_minus):
        if tr_v is None or tr_v == 0:
            continue
        di_p, di_m = 100.0 * p_v / tr_v, 100.0 * m_v / tr_v
        total = di_p + di_m
        dx.append(0.0 if total == 0 else 100.0 * abs(di_p - di_m) / total)

    return wilder_smooth(dx, n)[-1] if len(dx) >= n else None


def raw_dx_reference(df: pd.DataFrame, n: int = PERIOD) -> float:
    """El DX de la última barra, **sin** el cuarto suavizado.

    Existe para probar que ese cuarto suavizado hace algo. Reusa `adx_reference`
    hasta el paso anterior al último.
    """
    h, low = df["high"].tolist(), df["low"].tolist()
    dm_plus, dm_minus = [0.0], [0.0]
    for i in range(1, len(h)):
        up, down = h[i] - h[i - 1], low[i - 1] - low[i]
        dm_plus.append(up if up > down and up > 0 else 0.0)
        dm_minus.append(down if down > up and down > 0 else 0.0)

    tr_v = wilder_smooth(true_range(df), n)[-1]
    p_v, m_v = wilder_smooth(dm_plus, n)[-1], wilder_smooth(dm_minus, n)[-1]
    di_p, di_m = 100.0 * p_v / tr_v, 100.0 * m_v / tr_v
    return 100.0 * abs(di_p - di_m) / (di_p + di_m)


def macd_reference(close: List[float], fast: int, slow: int, signal: int):
    ema_fast = ema_smooth(close, fast)
    ema_slow = ema_smooth(close, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    return macd_line[-1], ema_smooth(macd_line, signal)[-1]


def macd_as_if_wilder(close: List[float], fast: int, slow: int, signal: int):
    """Lo que daría el MACD si alguien "completara" U3-2 sobre él. No debe dar."""
    def w(vals: List[float], n: int) -> List[float]:
        smoothed = wilder_smooth(vals, n)
        return [v for v in smoothed if v is not None]

    ema_fast, ema_slow = w(close, fast), w(close, slow)
    k = min(len(ema_fast), len(ema_slow))
    macd_line = [f - s for f, s in zip(ema_fast[-k:], ema_slow[-k:])]
    return macd_line[-1], w(macd_line, signal)[-1]


# ========================================================================== #
#  Series sintéticas, deterministas                                           #
# ========================================================================== #

def make_ohlc(n_bars: int = 520, seed: int = 20260829, drift: float = 0.0015) -> pd.DataFrame:
    """OHLC semanal reproducible. Sin `hash()` y sin red (CONTEXT §5)."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, 0.025, n_bars)
    close = 100.0 * np.exp(np.cumsum(steps))
    spread = np.abs(rng.normal(0.0, 0.012, n_bars)) + 0.004
    high = close * (1 + spread)
    low = close * (1 - spread)
    return pd.DataFrame(
        {"high": high, "low": low, "close": close,
         "volume": rng.integers(1_000, 10_000, n_bars)},
        index=pd.date_range("2016-01-03", periods=n_bars, freq="W"),
    )


SERIES = {
    "tendencia alcista": make_ohlc(seed=20260829, drift=0.0015),
    "tendencia bajista": make_ohlc(seed=7, drift=-0.0018),
    "lateral": make_ohlc(seed=1312, drift=0.0),
    "volátil": make_ohlc(seed=99, drift=0.0005),
}


@pytest.fixture(scope="module")
def ta() -> TechnicalAnalyzer:
    return TechnicalAnalyzer()


# ========================================================================== #
#  El oráculo                                                                 #
# ========================================================================== #

class TestATREsWilder:
    @pytest.mark.parametrize("nombre", sorted(SERIES))
    def test_el_atr_del_motor_iguala_la_referencia(self, ta, nombre):
        df = SERIES[nombre]
        esperado = atr_reference(df)
        obtenido = ta._atr(df, PERIOD)

        assert obtenido is not None
        assert obtenido == pytest.approx(esperado, rel=1e-6), (
            f"{nombre}: ATR del motor {obtenido:.6f} contra Wilder {esperado:.6f}"
        )

    def test_el_defecto_no_era_decimal(self, ta):
        """El tamaño del error que esta fila arregla, con número.

        `span=14` es `alpha=0,1333`; Wilder es `0,0714`. Si alguien vuelve a
        cambiarlo por span, este test dice cuánto se movió y no sólo que se
        movió.
        """
        df = SERIES["volátil"]
        wilder = atr_reference(df)
        con_span = float(df.pipe(true_range_series).ewm(span=PERIOD, adjust=False).mean().iloc[-1])

        error_pct = abs(con_span - wilder) / wilder * 100
        assert error_pct > 2.0, (
            "Si span y Wilder ya no se distinguen sobre esta serie, la serie "
            "dejó de ser un caso de prueba útil"
        )
        assert ta._atr(df, PERIOD) == pytest.approx(wilder, rel=1e-6)


def true_range_series(df: pd.DataFrame) -> pd.Series:
    return pd.Series(true_range(df), index=df.index)


class TestADXEsWilder:
    @pytest.mark.parametrize("nombre", sorted(SERIES))
    def test_el_adx_del_motor_iguala_la_referencia(self, ta, nombre):
        df = SERIES[nombre]
        esperado = adx_reference(df)
        obtenido = ta._adx(df, PERIOD)

        assert esperado is not None and obtenido is not None
        assert obtenido == pytest.approx(esperado, rel=1e-4), (
            f"{nombre}: ADX del motor {obtenido:.4f} contra Wilder {esperado:.4f}"
        )

    def test_el_suavizado_que_la_fila_no_citaba_es_el_que_manda(self, ta):
        """El suavizado final del DX — el que la fila del backlog dejó afuera.

        La fila citaba `:353-358`: TR, +DM y −DM. El cuarto, el del DX, quedaba
        fuera del rango, y es justamente el que produce el número que lee el
        gate de `:274`. Se verifica midiendo, no contando ocurrencias de `.ewm(`
        en el código: el DX **crudo** de la última barra y el ADX son valores
        distintos, así que esa llamada no es decorativa.
        """
        df = SERIES["lateral"]
        dx_crudo = raw_dx_reference(df)
        adx = ta._adx(df, PERIOD)

        assert abs(adx - dx_crudo) / adx > 0.10, (
            f"ADX {adx:.2f} contra DX crudo {dx_crudo:.2f}: si fueran casi "
            "iguales, el suavizado final no estaría haciendo nada"
        )

    @pytest.mark.parametrize("nombre", sorted(SERIES))
    def test_el_suavizado_del_TR_se_cancela_dentro_del_ADX(self, nombre):
        """Y el hallazgo inverso: dentro de `_adx`, el suavizado del TR **no puede**
        mover el resultado.

        `_adx` tiene cuatro llamadas a `ewm`, pero sólo tres pueden cambiar el
        número que devuelve. `DI± = 100·S(DM±)/S(TR)` y
        `DX = 100·|DI⁺−DI⁻|/(DI⁺+DI⁻)`: `S(TR)` es factor común del numerador y
        del denominador, así que se va. Queda escrito como Wilder igual —es la
        formulación del libro y `di_plus`/`di_minus` son valores con nombre
        propio— pero **revertir ese sitio solo no rompe ningún test, y eso es
        correcto**, no un agujero de cobertura. Sin este test, el próximo que
        corra mutación sobre `_adx` va a leer ese mutante sobreviviente como una
        falta.

        El ATR **publicado** (`_atr`, el que alimenta `atr_pct` en `:180`) es
        otra función y ahí el suavizado sí manda: `TestATREsWilder` lo cubre.
        """
        df = SERIES[nombre]
        con_wilder = adx_reference(df)
        con_span = adx_reference_con_tr_ema(df)

        assert con_wilder == pytest.approx(con_span, rel=1e-9), (
            f"{nombre}: si el TR dejara de cancelarse, este test es la señal de "
            "que la fórmula del DX cambió"
        )

    def test_el_gate_de_25_lo_ve(self, ta):
        """El ADX no es un número interno: `technical.py:274` paga +5 si cruza 25.

        Un ADX sistemáticamente más nervioso cruza el umbral por ruido. Sobre
        una serie lateral —donde la respuesta correcta es "no hay tendencia"— el
        suavizado viejo llega más arriba que Wilder.
        """
        df = SERIES["lateral"]
        wilder = adx_reference(df)
        motor = ta._adx(df, PERIOD)

        assert motor == pytest.approx(wilder, rel=1e-4)
        assert (motor >= 25) == (wilder >= 25), (
            "El motor y Wilder tienen que caer del mismo lado del gate"
        )


class TestElMACDNoEsWilder:
    """Anti-cheat: el MACD se define con EMA. Convertirlo a Wilder es un bug.

    Esta fila cambia dos funciones, no tres. Si el próximo lector barre el
    archivo reemplazando cada `span` por `alpha=1/n`, acá se entera.
    """

    @pytest.mark.parametrize("nombre", sorted(SERIES))
    def test_el_macd_sigue_siendo_una_ema(self, ta, nombre):
        close = SERIES[nombre]["close"]
        linea, senal = ta._macd(close, 12, 26, 9)
        esperada_linea, esperada_senal = macd_reference(close.tolist(), 12, 26, 9)

        assert float(linea) == pytest.approx(esperada_linea, rel=1e-9)
        assert float(senal) == pytest.approx(esperada_senal, rel=1e-9)

    def test_un_macd_wilderizado_falla(self, ta):
        """Y la otra mitad: que la referencia de EMA no sea trivialmente igual.

        Sin esto, `test_el_macd_sigue_siendo_una_ema` pasaría también con un
        MACD de Wilder si las dos fórmulas dieran casi lo mismo — y entonces no
        estaría protegiendo nada.
        """
        close = SERIES["volátil"]["close"]
        linea, _ = ta._macd(close, 12, 26, 9)
        wilder_linea, _ = macd_as_if_wilder(close.tolist(), 12, 26, 9)

        assert float(linea) != pytest.approx(wilder_linea, rel=1e-3), (
            "EMA y Wilder dan lo mismo sobre esta serie: el anti-cheat no "
            "distingue nada y hay que cambiar la serie"
        )


class TestElArranqueConverge:
    """La siembra de Wilder (media de las primeras n) contra la de `ewm` (x0).

    No son idénticas; convergen. Sobre el largo real de la serie del motor la
    diferencia es ruido de punto flotante, y esto lo mide en vez de asumirlo.
    """

    def test_a_520_barras_la_siembra_ya_no_importa(self, ta):
        df = make_ohlc(n_bars=520, seed=4)
        assert ta._atr(df, PERIOD) == pytest.approx(atr_reference(df), rel=1e-9)

    def test_con_pocas_barras_la_siembra_todavia_se_nota(self, ta):
        """Y el caso honesto: un ticker recién listado no tiene 10 años.

        A 40 barras la siembra pesa **1,0 %**. Es dos órdenes de magnitud menos
        que la brecha que separaba span de Wilder, pero no es cero, así que
        queda escrito en vez de asumido.
        """
        df = make_ohlc(n_bars=40, seed=4)
        motor, referencia = ta._atr(df, PERIOD), atr_reference(df)

        brecha = abs(motor - referencia) / referencia
        assert brecha < 0.03, f"la siembra pesa {brecha:.1%} a 40 barras"
        assert brecha > 0, "a 40 barras las dos siembras no pueden coincidir"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
