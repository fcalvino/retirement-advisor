"""`p_ffo` se niega a medir cuando cruza monedas (serie fcf_yield, PR 3).

``p_ffo = market_cap / ffo`` divide una pata de mercado (``currency``, la moneda
de cotización) por una de estados (``financialCurrency``). Es la misma familia
que ``fcf_yield`` (``docs/FIX_FCF_YIELD_MONEDA.md`` §3), con la dirección
peligrosa: las bandas de ``p_ffo`` son **cotas superiores**, así que un FFO en
BRL contra un market cap en USD achica el múltiplo y el REIT cobra los 8 puntos
de la banda más grande de Valuación sin merecerlos.

Exposición en los universos versionados: cero (todos los REIT son USD). Por eso
la fixture es sintética: un REIT extranjero con ``p_ffo`` crudo de 10x (≤ 13,
banda excellent). Sin el guard, el motor lo mide; con él, queda en ``None``.

Sin backstop numérico: acá la corrupción *achica* el número y un piso borraría
REITs legítimamente baratos. Si falta ``financialCurrency`` no hay defensa —
límite aceptado, fijado abajo como test para que nadie lo "arregle" sin querer.

Sin red: mismo patrón que ``tests/test_reit_ffo.py::_analyze``.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer

_COLS = [f"{2025 - i}-12-31 00:00:00" for i in range(4)]

#: FFO = NI + D&A = 1.5e9 en la moneda de los estados. Con market cap 15e9 el
#: múltiplo crudo es 10x: banda excellent (≤ p_ffo_excellent).
_NET_INCOME = 1.0e9
_DA = 0.5e9
_MARKET_CAP = 15.0e9


def _statements(*, with_fcf: bool = True):
    income = {
        "Net Income": [_NET_INCOME] * 4,
        "Total Revenue": [_NET_INCOME * 4] * 4,
    }
    cash = {
        "Cash Dividends Paid": [-1.0e9] * 4,
        "Depreciation And Amortization": [_DA] * 4,
    }
    if with_fcf:
        cash["Free Cash Flow"] = [_NET_INCOME * 1.2] * 4
    return {
        "income_stmt": pd.DataFrame(income, index=_COLS).T,
        "balance_sheet": pd.DataFrame(
            {
                "Stockholders Equity": [_NET_INCOME * 10] * 4,
                "Total Assets": [_NET_INCOME * 30] * 4,
                "Current Assets": [_NET_INCOME * 5] * 4,
                "Current Liabilities": [_NET_INCOME * 3] * 4,
            },
            index=_COLS,
        ).T,
        "cashflow": pd.DataFrame(cash, index=_COLS).T,
    }


def _analyze(*, statements=None, **currencies):
    info = {
        "longName": "Test REIT",
        "sector": "Real Estate",
        "industry": "REIT - Retail",
        "country": "Brazil",
        "currentPrice": 100.0,
        "regularMarketPrice": 100.0,
        "marketCap": _MARKET_CAP,
    }
    info.update(currencies)
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=statements or _statements()),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze("TEST")


class TestReitExtranjeroNoMideElPFfo:

    def test_monedas_cruzadas_dejan_p_ffo_en_none(self):
        r = _analyze(financialCurrency="BRL", currency="USD")
        assert r.p_ffo is None, (
            f"FFO en BRL / market cap en USD dio p_ffo={r.p_ffo}x y cobró la banda "
            f"excellent; un múltiplo sólo existe si ambas patas comparten moneda."
        )
        assert "p_ffo_currency" in r.notes
        assert any("P/FFO no medible" in w for w in r.warnings)

    def test_ffo_y_payout_no_se_tocan(self):
        """FFO y payout son cocientes en la MISMA moneda: inmunes al guard."""
        cruzado = _analyze(financialCurrency="BRL", currency="USD")
        sano = _analyze(financialCurrency="USD", currency="USD")
        assert cruzado.ffo == sano.ffo == pytest.approx(_NET_INCOME + _DA)
        assert cruzado.ffo_payout_pct == sano.ffo_payout_pct

    def test_el_control_usd_mide_y_cobra_mas_valuacion(self):
        """Anti-cheat: el guard saca una corrupción, no borra un múltiplo legítimo."""
        sano = _analyze(financialCurrency="USD", currency="USD")
        cruzado = _analyze(financialCurrency="BRL", currency="USD")
        assert sano.p_ffo == pytest.approx(_MARKET_CAP / (_NET_INCOME + _DA))
        assert "p_ffo_currency" not in sano.notes
        assert sano.valuation_score > cruzado.valuation_score


class TestLaMonedaDeLosEstadosSeRegistraSiempre:

    def test_financial_currency_se_asigna_sin_serie_fcf(self):
        """Antes sólo se asignaba dentro de la rama FCF: sin esa serie quedaba ""."""
        r = _analyze(statements=_statements(with_fcf=False),
                     financialCurrency="BRL", currency="USD")
        assert r.financial_currency == "BRL"


class TestSinFinancialCurrencyNoHayDefensa:

    def test_sin_la_clave_p_ffo_se_sigue_midiendo(self):
        """Límite aceptado (doc §3): no hay backstop numérico para p_ffo."""
        r = _analyze(currency="USD")
        assert r.p_ffo == pytest.approx(_MARKET_CAP / (_NET_INCOME + _DA))
        assert "p_ffo_currency" not in r.notes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
