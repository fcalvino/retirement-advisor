"""Integración del fix de moneda de `fcf_yield` en ``_score_growth`` (PR 2).

El oráculo (``test_fcf_yield_currency_oracle.py``) fija la lógica pura del gate.
Acá se prueba el cableado en el scoring, y sobre todo el **riesgo #1** del doc
(``docs/FIX_FCF_YIELD_MONEDA.md §6``): la mitad CAGR de la sub-sección FCF es
inmune —es un cociente de dos flujos de la MISMA moneda— y **tiene que seguir
puntuando** aunque el yield se descarte. Si el guard de moneda se metiera
demasiado arriba, envolvería también el CAGR y 14 tickers perderían 3 puntos más
en silencio. El test lo fija: con las monedas cruzadas, el yield da 0 pero el
CAGR sigue sumando sus puntos.

Sin red: se llama ``_score_growth`` directo con statements construidos a mano.
"""

from __future__ import annotations

import pandas as pd

from analysis.fundamental import FundamentalAnalyzer, FundamentalResult

_COLS = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]

#: FCF creciente en el tiempo (más reciente primero). El CAGR es fuertemente
#: positivo, así que la mitad CAGR aporta sus 3 puntos —independiente del yield—.
_FCF_GROWING = [4.0e9, 3.0e9, 2.0e9, 1.0e9]


def _cashflow(fcf_values):
    return pd.DataFrame({"Free Cash Flow": fcf_values}, index=_COLS).T


def _score(info, cashflow, *, market_cap):
    analyzer = FundamentalAnalyzer()
    result = FundamentalResult(symbol="X", company_name="X")
    result.market_cap = market_cap
    # income_stmt vacío: revenue/EPS no puntúan y aíslan la sub-sección FCF.
    score = analyzer._score_growth(info, pd.DataFrame(), cashflow, result)
    return score, result


class TestMonedasCruzadasNoMidenElYieldPeroSiElCagr:

    def test_mismatch_deja_el_yield_en_none_y_puntua_cero(self):
        info = {"financialCurrency": "COP", "currency": "USD"}
        # FCF 4e9 COP / market cap 100e9 USD = 4.0% crudo: caería en excellent (+3)
        # si el motor lo midiera. No debe.
        score, result = _score(info, _cashflow(_FCF_GROWING), market_cap=100e9)

        assert result.fcf_yield is None
        assert "fcf_yield_currency" in result.notes
        assert result.warnings, "el caso tiene que dejar rastro legible"
        assert result.financial_currency == "COP"

    def test_la_mitad_cagr_sigue_puntuando_pese_al_mismatch(self):
        """Riesgo #1: el guard envuelve SOLO el yield, no el CAGR."""
        info = {"financialCurrency": "COP", "currency": "USD"}
        score, _ = _score(info, _cashflow(_FCF_GROWING), market_cap=100e9)
        # income vacío ⇒ el único aporte posible es el CAGR del FCF. Si el guard
        # hubiera envuelto el CAGR, esto sería 0.
        assert score > 0, "la mitad CAGR se cayó con el yield — el guard subió de más"

    def test_el_yield_aporta_encima_del_cagr_cuando_la_moneda_coincide(self):
        """El control USD: mismo FCF y mismo market cap, monedas iguales. El yield
        se mide (4.0% ⇒ excellent) y suma 3 puntos EXACTOS por encima del CAGR."""
        cruzado = {"financialCurrency": "COP", "currency": "USD"}
        sano = {"financialCurrency": "USD", "currency": "USD"}
        cf = _cashflow(_FCF_GROWING)

        score_cruzado, _ = _score(cruzado, cf, market_cap=100e9)
        score_sano, r_sano = _score(sano, cf, market_cap=100e9)

        assert r_sano.fcf_yield == 4.0
        assert score_sano - score_cruzado == 3.0
        assert r_sano.financial_currency == "USD"


class TestBackstopDePlausibilidadCuandoFaltaLaMoneda:

    def test_sin_financial_currency_un_yield_absurdo_se_descarta(self):
        """Info cacheada vieja sin `financialCurrency`: el gate no puede afirmar el
        mismatch, así que el techo de 50% caza el caso grueso."""
        info = {"currency": "USD"}          # sin financialCurrency
        # FCF 4e9 / market cap 5e9 = 80% crudo, por encima del techo.
        score, result = _score(info, _cashflow(_FCF_GROWING), market_cap=5e9)

        assert result.fcf_yield is None
        assert "fcf_yield_currency" in result.notes
        assert result.warnings
        assert result.financial_currency == ""

    def test_un_yield_plausible_sin_moneda_se_mide_igual(self):
        """El techo no borra valores legítimos: un yield normal sin `financialCurrency`
        (info vieja de un emisor USD) sigue midiéndose."""
        info = {"currency": "USD"}
        # FCF 4e9 / market cap 200e9 = 2.0% ⇒ good (+2), por debajo del techo.
        score, result = _score(info, _cashflow(_FCF_GROWING), market_cap=200e9)

        assert result.fcf_yield == 2.0
        assert "fcf_yield_currency" not in result.notes
