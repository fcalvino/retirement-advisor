"""Un precio en su moneda de cotización, llevado a la moneda de la cartera (#154).

``global_quality`` tiene 90 tickers de 126 cotizando en algo que no es el dólar, y el
Optimizer, Backtesting y el Track Record leen precios crudos: un retorno en yenes, uno
en peniques y uno en dólares se promediaban como si fueran el mismo número. Este módulo
es la única implementación de la conversión; ninguna superficie la llama todavía, así
que este paso no mueve ningún número publicado.

Cuatro decisiones, cada una con su porqué:

**El destino es ``PORTFOLIO.base_currency``**, no un literal. El símbolo del par se arma
con esa moneda, y la subunidad (GBp → GBP, ÷ 100) sale de ``config.QUOTE_MINOR_UNITS``,
que ya usaba Graham.

**Una moneda desconocida no bloquea**, igual que en ``admission_skip_reason`` y
``position_currency_skip_reason``: el precio pasa como venía. Una moneda conocida **sin
cotización de FX es ``None``**, nunca un tipo de cambio de 1,0 (U2-4: un dato faltante
no es un dato bueno).

**Una fecha sin FX se descarta**, no se convierte a 1,0. Vale una cotización de hasta
``FX.max_staleness_days`` días antes de la fecha del precio; más vieja no hay conversión.

**El FX de Yahoo trae cotizaciones basura de un solo punto que revierten** (CLPUSD=X
valía 0,2 el 2016-12-22 y vale ~0,0015; NOKUSD=X subió 39 % el 2020-03-20; CADUSD=X, tres
semanas). ``drop_fx_spikes`` las descarta con el criterio y la calibración documentados
en ``config.FxConfig``: el punto se aparta del punto medio de sus vecinos y los vecinos
coinciden entre sí. Un escalón real y el rebote real de una crisis quedan intactos.

Sin Streamlit; la única red es ``get_history``, con su caché y sus reintentos.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from config import FX, PORTFOLIO, QUOTE_MINOR_MAJOR, QUOTE_MINOR_UNITS
from data.fetcher import get_history


def fx_pair_symbol(currency: Optional[str]) -> Optional[str]:
    """Símbolo de yfinance del par ``<moneda><base>=X``, o ``None`` si no hace falta.

    ``None`` para una moneda vacía y para la moneda de la cartera. Una subunidad usa la
    mayor (``GBp`` → ``GBPUSD=X``); el ÷ 100 lo aplica ``to_base_currency``.
    """
    ccy = str(currency or "").strip()
    if not ccy:
        return None
    major = QUOTE_MINOR_MAJOR.get(ccy, ccy.upper())
    if major == PORTFOLIO.base_currency:
        return None
    return f"{major}{PORTFOLIO.base_currency}=X"


def _naive_days(index) -> pd.DatetimeIndex:
    """Fechas sin zona horaria y sin hora: la clave común de precio y FX."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    return idx.normalize()


def drop_fx_spikes(series: pd.Series, *, label: str = "") -> pd.Series:
    """Saca de una serie de FX las cotizaciones basura de un solo punto.

    Un punto sobra si se aparta al menos ``FX.spike_dev_pct`` % del punto medio
    geométrico de sus dos vecinos **y** los vecinos difieren entre sí, como mucho,
    ``FX.spike_neighbor_agreement`` veces ese desvío. El primer y el último punto no se
    juzgan. Cada juicio se hace contra los vecinos originales, no en cascada. Los valores
    no positivos no son un tipo de cambio y también salen. Pura salvo por el log.
    """
    values = pd.to_numeric(series, errors="coerce").astype(float)
    values = values[values > 0]
    if len(values) < 3:
        return values
    v = values.to_numpy()
    prev, cur, nxt = v[:-2], v[1:-1], v[2:]
    dev = cur / np.sqrt(prev * nxt) - 1.0
    net = nxt / prev - 1.0
    bad = (np.abs(dev) >= FX.spike_dev_pct / 100.0) & (
        np.abs(net) <= FX.spike_neighbor_agreement * np.abs(dev)
    )
    if not bad.any():
        return values
    keep = np.ones(len(v), dtype=bool)
    keep[1:-1] = ~bad
    for pos in np.flatnonzero(bad) + 1:
        logger.warning(
            f"fx: {label or 'FX'} {str(values.index[pos])[:10]} = {v[pos]:.6g} se aparta "
            f"{dev[pos - 1]:+.1%} de sus vecinos — cotización descartada"
        )
    return values[keep]


def to_base_currency(
    prices: pd.Series, currency: Optional[str], fx: Optional[pd.Series]
) -> Optional[pd.Series]:
    """``prices`` (en ``currency``) × unidades de la cartera por unidad de esa moneda.

    ``fx`` es la serie de ``fx_pair_symbol(currency)``, ya limpia. Moneda vacía o la de
    la cartera: el mismo ``prices``, salvo el ÷ 100 de una subunidad. Moneda ajena sin
    ``fx``: ``None``. Las fechas del precio que no tienen una cotización de a lo sumo
    ``FX.max_staleness_days`` días antes quedan afuera de la serie devuelta.
    """
    ccy = str(currency or "").strip()
    divisor = QUOTE_MINOR_UNITS.get(ccy, 1)
    if fx_pair_symbol(ccy) is None:
        return prices if divisor == 1 else prices / divisor
    if fx is None:
        return None
    rate = pd.to_numeric(fx, errors="coerce").dropna()
    rate = rate[rate > 0]
    if rate.empty:
        return None
    rate.index = _naive_days(rate.index)
    rate = rate[~rate.index.duplicated(keep="last")].sort_index()
    aligned = rate.reindex(
        _naive_days(prices.index),
        method="ffill",
        tolerance=pd.Timedelta(days=FX.max_staleness_days),
    )
    converted = pd.Series(
        prices.to_numpy(dtype=float) / divisor * aligned.to_numpy(),
        index=prices.index,
        name=prices.name,
    )
    return converted.dropna()


def _close_series(frame: pd.DataFrame) -> Optional[pd.Series]:
    """La serie de cierres de un frame de ``get_history``, con fechas normalizadas."""
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    df = frame
    for col in ("Date", "date"):  # forma en frío o en caliente de la caché
        if col in df.columns:
            df = df.set_index(pd.to_datetime(df[col]))
            break
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if close.empty:
        return None
    close.index = _naive_days(close.index)
    return close[~close.index.duplicated(keep="last")].sort_index()


def get_fx_history(currency: Optional[str], *, period: str, interval: str) -> Optional[pd.Series]:
    """Cierres del par de ``currency`` contra la moneda de la cartera, sin basura.

    Pide el par con el mismo ``period`` e ``interval`` que los precios que va a convertir,
    por ``get_history`` (caché, TTL y reintentos de siempre). ``None`` si no hace falta
    convertir (moneda vacía o la de la cartera) o si el proveedor no devolvió nada.
    """
    symbol = fx_pair_symbol(currency)
    if symbol is None:
        return None
    try:
        frame = get_history(symbol, period=period, interval=interval)
    except Exception as exc:
        logger.warning(f"fx: {symbol} no se pudo bajar — {exc}")
        return None
    close = _close_series(frame)
    if close is None:
        logger.warning(f"fx: {symbol} sin historia de cierres")
        return None
    return drop_fx_spikes(close, label=symbol)


def convert_history(
    prices: pd.Series, currency: Optional[str], *, period: str, interval: str
) -> Optional[pd.Series]:
    """Los precios de un ticker en la moneda de la cartera, o ``None`` si falta el FX.

    Es lo que llaman las superficies. ``period`` e ``interval`` son los del ``get_history``
    que produjo ``prices``: así las fechas del par y las del ticker se corresponden.
    """
    if fx_pair_symbol(currency) is None:
        return to_base_currency(prices, currency, None)
    rate = get_fx_history(currency, period=period, interval=interval)
    return to_base_currency(prices, currency, rate)
