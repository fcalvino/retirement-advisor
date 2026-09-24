"""Consistencia de unidades entre el feed y los estados — sin tipo de cambio.

Auditoría ``docs/AUDIT_UNIDADES_MONEDA_2026-09.md`` (UM-1, UM-2). yfinance entrega
ratios precalculados —``priceToBook``, ``enterpriseToEbitda``— que en la mayoría de
los listados son correctos, pero en ADRs de reportantes extranjeros, en SQM-B.SN y
en una clase de acción (BRK-B) salen de 4× a 900× de su valor, porque mezclan una
cifra por acción en la moneda de cotización con otra en la moneda de los estados,
o con otra clase de acción. Y la etiqueta ``financialCurrency`` no siempre dice la
verdad: PETR4.SA y VALE3.SA declaran BRL con estados en USD.

Este módulo contrasta esos ratios contra reconstrucciones que **no necesitan tipo
de cambio ni creerle a la etiqueta**:

* ``trailingPE`` es consistente en unidades (28 de 28 casos con monedas distintas,
  medido) y ``returnOnEquity`` es un cociente de estados, sin unidad. Su producto
  estima el P/B: ``P/B = P/E × ROE``. Contra un oráculo que convierte con el tipo
  de cambio del día, 164 de 165 equities quedan dentro de [0,5 ; 2].
* ``marketCap / (trailingPE × utilidad neta)`` y ``marketCap / (P/S × ingresos)``
  estiman el tipo de cambio implícito entre la cotización y los estados. Cerca de
  1 cuando comparten moneda; lejos de 1 cuando no, diga lo que diga la etiqueta.

Puro: sin red, sin caché, sin importar ``analysis.fundamental`` (que es quien lo
va a llamar). Los umbrales viven en ``config.UNIT_CONSISTENCY``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from analysis.utils import extract_financial_row
from config import QUOTE_MINOR_MAJOR, UNIT_CONSISTENCY

#: Relación entre la moneda de cotización y la de los estados.
SAME = "same"
DIFFERENT = "different"
UNKNOWN = "unknown"

#: Resultado de un chequeo de ratio.
OK = "ok"                          # el feed es consistente: se usa tal cual
REPLACED = "replaced"              # roto, misma moneda: reconstrucción exacta
NOT_MEASURABLE = "not_measurable"  # roto, monedas distintas: None
UNVERIFIABLE = "unverifiable"      # sin referencia (pérdidas, ROE ≤ 0): se usa el feed
NOT_CHECKED = "not_checked"        # el chequeo no aplica a este caso
MISSING = "missing"                # el feed no lo reporta


@dataclass(frozen=True)
class StatementLegs:
    """Las cifras de los estados que usan los chequeos, del ejercicio más reciente.

    Todas en la moneda de los estados, sea cual sea: los chequeos solo las usan en
    cocientes entre sí o contra un múltiplo del feed, nunca contra el precio.
    """

    net_income: Optional[float] = None
    revenue: Optional[float] = None
    equity: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    ebitda: Optional[float] = None


@dataclass(frozen=True)
class UnitCheck:
    """El valor que debe puntuar el motor, y por qué."""

    value: Optional[float]
    status: str
    feed: Optional[float] = None
    reference: Optional[float] = None


def _latest(df: Optional[pd.DataFrame], candidates: list) -> Optional[float]:
    row = extract_financial_row(df, candidates, ascending=False, as_float=True,
                                require_nonempty=True, missing=None)
    if row is None or row.empty:
        return None
    return float(row.iloc[0])


def statement_legs(
    income_stmt: Optional[pd.DataFrame], balance_sheet: Optional[pd.DataFrame]
) -> StatementLegs:
    """Extrae las patas de los estados con los mismos nombres de fila que el motor."""
    return StatementLegs(
        net_income=_latest(income_stmt, ["Net Income Common Stockholders", "Net Income"]),
        revenue=_latest(income_stmt, ["Total Revenue", "Operating Revenue"]),
        equity=_latest(balance_sheet, ["Stockholders Equity", "Total Stockholder Equity",
                                       "Common Stock Equity"]),
        total_debt=_latest(balance_sheet, ["Total Debt"]),
        cash=_latest(balance_sheet, ["Cash And Cash Equivalents",
                                     "Cash Cash Equivalents And Short Term Investments"]),
        ebitda=_latest(income_stmt, ["EBITDA", "Normalized EBITDA"]),
    )


def _positive(info: Dict[str, Any], key: str) -> Optional[float]:
    raw = info.get(key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        return None
    return value


def _in_band(ratio: Optional[float], band) -> bool:
    low, high = band
    return ratio is not None and low <= ratio <= high


def major_currency(code: Optional[str]) -> Optional[str]:
    """``GBp`` → ``GBP``: la cotización en subunidad comparte moneda con sus estados."""
    if not code:
        return None
    return QUOTE_MINOR_MAJOR.get(str(code), str(code).upper())


def implied_fx_by_earnings(info: Dict[str, Any], legs: StatementLegs) -> Optional[float]:
    """``marketCap / (trailingPE × utilidad neta)``: ≈ 1 si comparten moneda."""
    mc, pe = _positive(info, "marketCap"), _positive(info, "trailingPE")
    ni = legs.net_income
    if mc is None or pe is None or ni is None or ni <= 0:
        return None
    return mc / (pe * ni)


def implied_fx_by_sales(info: Dict[str, Any], legs: StatementLegs) -> Optional[float]:
    """``marketCap / (P/S × ingresos)``: segunda vía, menos volátil que la utilidad.

    No sirve como oráculo del P/B: en los ADRs el feed calcula el P/S con la misma
    mezcla de monedas (TSM da 1,17 con un tipo de cambio real de 31,7). Sirve para
    confirmar que la etiqueta miente, que es el único uso que tiene acá.
    """
    mc, ps = _positive(info, "marketCap"), _positive(info, "priceToSalesTrailing12Months")
    rev = legs.revenue
    if mc is None or ps is None or rev is None or rev <= 0:
        return None
    return mc / (ps * rev)


def statements_currency_relation(
    info: Dict[str, Any], legs: StatementLegs, *, config=None
) -> str:
    """¿Los estados vienen en la moneda de cotización? ``same``/``different``/``unknown``.

    Si la etiqueta dice que difieren, difieren. Si dice que coinciden, se le cree
    salvo que **las dos** vías sin tipo de cambio la desmientan (UM-2): una sola
    vía fuera de banda es ruido de ganancias (MRK, FEMSA), no una moneda distinta.
    Sin etiqueta no se puede afirmar nada.
    """
    cfg = config or UNIT_CONSISTENCY
    quote = major_currency(info.get("currency"))
    fin = major_currency(info.get("financialCurrency"))
    if not quote or not fin:
        return UNKNOWN
    if quote != fin:
        return DIFFERENT
    by_earnings = implied_fx_by_earnings(info, legs)
    by_sales = implied_fx_by_sales(info, legs)
    if (
        by_earnings is not None
        and by_sales is not None
        and not _in_band(by_earnings, cfg.implied_fx_band)
        and not _in_band(by_sales, cfg.implied_fx_band)
    ):
        return DIFFERENT
    return SAME


def pb_reference(info: Dict[str, Any]) -> Optional[float]:
    """``P/E × ROE``: el P/B sin tipo de cambio y sin cifras por acción."""
    pe, roe = _positive(info, "trailingPE"), _positive(info, "returnOnEquity")
    if pe is None or roe is None:
        return None
    return pe * roe


def check_price_to_book(
    info: Dict[str, Any], legs: StatementLegs, relation: str, *, config=None
) -> UnitCheck:
    """El P/B que debe puntuar el motor.

    Roto quiere decir fuera de ``ratio_band`` contra ``P/E × ROE``. Si los estados
    comparten moneda con la cotización, se reconstruye exacto como
    ``marketCap / patrimonio`` (BRK-B: el feed divide por el valor libro de la
    acción A). Si no, no se mide: convertir exigiría un tipo de cambio que el
    motor no fabrica (``docs/FIX_FCF_YIELD_MONEDA.md`` §3).
    """
    cfg = config or UNIT_CONSISTENCY
    feed = _positive(info, "priceToBook")
    if feed is None:
        return UnitCheck(None, MISSING)
    if not cfg.enabled:
        return UnitCheck(feed, NOT_CHECKED, feed=feed)
    reference = pb_reference(info)
    if reference is None:
        return UnitCheck(feed, UNVERIFIABLE, feed=feed)
    if _in_band(feed / reference, cfg.ratio_band):
        return UnitCheck(feed, OK, feed=feed, reference=reference)
    mc = _positive(info, "marketCap")
    if relation == SAME and mc is not None and legs.equity and legs.equity > 0:
        return UnitCheck(mc / legs.equity, REPLACED, feed=feed, reference=reference)
    return UnitCheck(None, NOT_MEASURABLE, feed=feed, reference=reference)


def ev_ebitda_reference(info: Dict[str, Any], legs: StatementLegs) -> Optional[float]:
    """EV/EBITDA en la moneda de los estados, con el market cap de ``P/E × ROE × patrimonio``."""
    pb = pb_reference(info)
    if pb is None or not legs.equity or legs.equity <= 0:
        return None
    if not legs.ebitda or legs.ebitda <= 0 or legs.total_debt is None:
        return None
    market_cap_in_statements = pb * legs.equity
    return (market_cap_in_statements + legs.total_debt - (legs.cash or 0.0)) / legs.ebitda


def check_ev_ebitda(
    info: Dict[str, Any], legs: StatementLegs, relation: str, *, config=None
) -> UnitCheck:
    """El EV/EBITDA que debe puntuar el motor.

    Solo se chequea cuando las monedas difieren: con la misma moneda, las
    diferencias contra la reconstrucción son de definición de EBITDA (NFLX, RWE.DE,
    8058.T — indeterminados en la auditoría), no de unidad. Nunca se reemplaza.
    """
    cfg = config or UNIT_CONSISTENCY
    feed = _positive(info, "enterpriseToEbitda")
    if feed is None:
        return UnitCheck(None, MISSING)
    if not cfg.enabled or relation != DIFFERENT:
        return UnitCheck(feed, NOT_CHECKED, feed=feed)
    reference = ev_ebitda_reference(info, legs)
    if reference is None or reference <= 0:
        return UnitCheck(feed, UNVERIFIABLE, feed=feed)
    if _in_band(feed / reference, cfg.ratio_band):
        return UnitCheck(feed, OK, feed=feed, reference=reference)
    return UnitCheck(None, NOT_MEASURABLE, feed=feed, reference=reference)
