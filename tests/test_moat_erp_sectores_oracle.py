"""AUDIT-MOAT-ERP-SECTORES — un banco usa el ERP de su sector, no el genérico.

``MOAT.sector_erp_pct`` tiene la clave ``Financials`` pero yfinance entrega ``Financial Services``
(``yfinance.const``: de los 11 sectores, es el único sin clave; ``Basic Materials`` sí la tiene).
``MoatAnalyzer._wacc_proxy`` hacía ``erp_map.get(sector, default)`` con el sector crudo, así que un
banco recibía el ERP por defecto (5,0) en vez de 5,5: el umbral de ROIC (rf + ERP) quedaba 0,5 pt
más bajo y ``roic_sustained`` salía más generoso.

Los esperados están escritos a mano desde la tabla de la docstring de la config (Technology 5,0,
Healthcare 4,5, Financials 5,5, Energy 6,0, Utilities 4,0, Consumer Defensive 4,5, Consumer
Cyclical 5,5, Communication Services 5,0, Industrials 5,0, Real Estate 5,5, Basic Materials 5,5),
no leídos de la tabla de producción. Sin red.
"""

from __future__ import annotations

import pytest
import yfinance.const as yf_const

from analysis.moat import MoatAnalyzer
from config import MOAT

YF_SECTORS = sorted(yf_const.SECTOR_INDUSTY_MAPPING)

EXPECTED_ERP = {
    "Basic Materials": 5.5,
    "Communication Services": 5.0,
    "Consumer Cyclical": 5.5,
    "Consumer Defensive": 4.5,
    "Energy": 6.0,
    "Financial Services": 5.5,
    "Healthcare": 4.5,
    "Industrials": 5.0,
    "Real Estate": 5.5,
    "Technology": 5.0,
    "Utilities": 4.0,
}


def test_the_reference_covers_the_eleven_yfinance_sectors():
    assert sorted(EXPECTED_ERP) == YF_SECTORS, (
        "yfinance cambió su lista de sectores: agregá la clave nueva a MOAT.sector_erp_pct y a EXPECTED_ERP"
    )


@pytest.mark.parametrize("sector", YF_SECTORS)
def test_the_hurdle_of_every_yfinance_sector_is_rf_plus_its_own_erp(sector):
    ma = MoatAnalyzer()
    assert ma._wacc_proxy(sector) == pytest.approx(MOAT.risk_free_proxy_pct + EXPECTED_ERP[sector])


def test_a_bank_gets_a_stricter_hurdle_than_the_default():
    """El 5,5 de un banco es más alto que el 5,0 por defecto: el umbral de ROIC sube 0,5 pt."""
    ma = MoatAnalyzer()
    assert ma._wacc_proxy("Financial Services") == pytest.approx(MOAT.risk_free_proxy_pct + 5.5)
    assert ma._wacc_proxy("Financial Services") > ma._wacc_proxy("Sector Inexistente")


def test_roic_sustained_of_a_bank_between_the_two_hurdles_is_scored_with_its_own():
    """ROIC = rf + 5,2: supera el umbral por defecto (rf + 5,0, spread 0,2 → 0,5 pt) pero no el de
    un banco (rf + 5,5, spread −0,3 → 0 pt)."""
    ma = MoatAnalyzer()
    roic = MOAT.risk_free_proxy_pct + 5.2
    assert ma._score_roic_sustained(roic, sector="Financial Services") == 0.0
    assert ma._score_roic_sustained(roic, sector="Sector Inexistente") == 0.5


def test_a_sector_outside_the_table_still_uses_the_default():
    ma = MoatAnalyzer()
    assert ma._wacc_proxy("ETF") == pytest.approx(MOAT.risk_free_proxy_pct + MOAT.default_sector_erp_pct)
    assert ma._wacc_proxy("") == pytest.approx(MOAT.risk_free_proxy_pct + MOAT.default_sector_erp_pct)
