"""Oráculo del chequeo de unidades de los ratios del feed (UM-1, UM-2).

``docs/AUDIT_UNIDADES_MONEDA_2026-09.md`` midió que ``priceToBook`` y
``enterpriseToEbitda`` salen de 4× a 900× de su valor en algunos tickers, y que
``financialCurrency`` miente en PETR4.SA y VALE3.SA. ``analysis/unit_consistency``
detecta esos casos **sin tipo de cambio**, con ``P/E × ROE``.

**La referencia de este oráculo no es el helper** (eso congelaría lo que el helper
haga, CONTEXT §5). Es la definición del ratio convertida con el tipo de cambio del
día: ``P/B = marketCap × FX / patrimonio``, con el FX de cotización a estados medido
el 2026-09-23. El helper nunca ve ese FX: si su veredicto coincide con el del
oráculo, detecta la unidad rota por un camino independiente.

Fixtures copiadas de la caché (22–23/09) salvo CIB y BSBR, medidos en vivo el
2026-09-24 porque no estaban cacheados. Sin red.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd
import pytest

from analysis.unit_consistency import (
    DIFFERENT,
    MISSING,
    NOT_CHECKED,
    NOT_MEASURABLE,
    OK,
    REPLACED,
    SAME,
    UNKNOWN,
    UNVERIFIABLE,
    StatementLegs,
    check_ev_ebitda,
    check_price_to_book,
    major_currency,
    statement_legs,
    statements_currency_relation,
)
from config import UNIT_CONSISTENCY, UnitConsistencyConfig


@dataclass(frozen=True)
class _Case:
    info: Dict[str, Any]
    legs: StatementLegs
    #: Tipo de cambio de la moneda de cotización (unidad mayor) a la de los
    #: estados. Solo lo usa el oráculo; el helper no lo recibe.
    fx: float


CASES: Dict[str, _Case] = {
    "TSM": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "TWD",
            "marketCap": 2.31618e+12,
            "trailingPE": 33.2772,
            "returnOnEquity": 0.39969,
            "priceToBook": 91.38897,
            "enterpriseToEbitda": 5.161,
            "priceToSalesTrailing12Months": 0.521603,
        },
        legs=StatementLegs(
            net_income=1.6976e+12,
            revenue=3.80905e+12,
            equity=5.35504e+12,
            total_debt=1.06458e+12,
            cash=2.76786e+12,
            ebitda=2.74212e+12,
        ),
        fx=31.679501,
    ),
    "SQM-B.SN": _Case(
        info={
            "currency": "CLP",
            "financialCurrency": "USD",
            "marketCap": 1.91706e+13,
            "trailingPE": 14.504076,
            "returnOnEquity": 0.2182,
            "priceToBook": 3037.5652,
            "enterpriseToEbitda": 6338.999,
            "priceToSalesTrailing12Months": 2850.4607,
        },
        legs=StatementLegs(
            net_income=5.88138e+08,
            revenue=4.57622e+09,
            equity=5.69126e+09,
            total_debt=4.72821e+09,
            cash=1.75032e+09,
            ebitda=1.1462e+09,
        ),
        fx=0.001056,
    ),
    "HDB": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "INR",
            "marketCap": 1.17654e+11,
            "trailingPE": 16.01049,
            "returnOnEquity": 0.13838,
            "priceToBook": 9.149627,
            "enterpriseToEbitda": None,
            "priceToSalesTrailing12Months": 0.039888,
        },
        legs=StatementLegs(
            net_income=7.04793e+11,
            revenue=1.92567e+12,
            equity=8.1674e+12,
            total_debt=6.64364e+12,
            cash=3.65067e+12,
            ebitda=None,
        ),
        fx=95.689796,
    ),
    "KB": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "KRW",
            "marketCap": 4.40989e+10,
            "trailingPE": 10.303528,
            "returnOnEquity": 0.10224,
            "priceToBook": 4.35018,
            "enterpriseToEbitda": None,
            "priceToSalesTrailing12Months": 0.002564,
        },
        legs=StatementLegs(
            net_income=5.63077e+12,
            revenue=2.12316e+13,
            equity=5.90482e+13,
            total_debt=1.31449e+14,
            cash=3.56498e+13,
            ebitda=None,
        ),
        fx=1350.359985,
    ),
    "BRK-B": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "USD",
            "marketCap": 1.07783e+12,
            "trailingPE": 12.66323,
            "returnOnEquity": 0.1212,
            "priceToBook": 0.000964,
            "enterpriseToEbitda": -1.79,
            "priceToSalesTrailing12Months": 2.801826,
        },
        legs=StatementLegs(
            net_income=6.6968e+10,
            revenue=4.10522e+11,
            equity=7.17419e+11,
            total_debt=1.29081e+11,
            cash=5.1877e+10,
            ebitda=None,
        ),
        fx=1.0,
    ),
    "CEMEXCPO.MX": _Case(
        info={
            "currency": "MXN",
            "financialCurrency": "USD",
            "marketCap": 2.50064e+11,
            "trailingPE": 28.409836,
            "returnOnEquity": 0.04015,
            "priceToBook": 1.17152,
            "enterpriseToEbitda": 81.856,
            "priceToSalesTrailing12Months": 14.677031,
        },
        legs=StatementLegs(
            net_income=9.6e+08,
            revenue=1.6132e+10,
            equity=1.333e+10,
            total_debt=6.779e+09,
            cash=1.822e+09,
            ebitda=2.573e+09,
        ),
        fx=0.057852,
    ),
    "EQNR.OL": _Case(
        info={
            "currency": "NOK",
            "financialCurrency": "USD",
            "marketCap": 9.62916e+11,
            "trailingPE": 11.692574,
            "returnOnEquity": 0.2127,
            "priceToBook": 2.466254,
            "enterpriseToEbitda": 23.309,
            "priceToSalesTrailing12Months": 8.472421,
        },
        legs=StatementLegs(
            net_income=5.043e+09,
            revenue=1.05828e+11,
            equity=4.0424e+10,
            total_debt=3.122e+10,
            cash=5.036e+09,
            ebitda=3.8393e+10,
        ),
        fx=0.105945,
    ),
    "PETR4.SA": _Case(
        info={
            "currency": "BRL",
            "financialCurrency": "BRL",
            "marketCap": 6.77572e+11,
            "trailingPE": 4.871316,
            "returnOnEquity": 0.30274,
            "priceToBook": 1.32892,
            "enterpriseToEbitda": 3.855,
            "priceToSalesTrailing12Months": 1.235334,
        },
        legs=StatementLegs(
            net_income=1.9634e+10,
            revenue=8.9195e+10,
            equity=7.5565e+10,
            total_debt=6.9793e+10,
            cash=6.471e+09,
            ebitda=4.6038e+10,
        ),
        fx=0.196082,
    ),
    "VALE3.SA": _Case(
        info={
            "currency": "BRL",
            "financialCurrency": "BRL",
            "marketCap": 3.04798e+11,
            "trailingPE": 27.976564,
            "returnOnEquity": 0.04115,
            "priceToBook": 1.550082,
            "enterpriseToEbitda": 5.107,
            "priceToSalesTrailing12Months": 1.397712,
        },
        legs=StatementLegs(
            net_income=2.352e+09,
            revenue=3.8403e+10,
            equity=3.3509e+10,
            total_debt=2.1801e+10,
            cash=7.372e+09,
            ebitda=9.799e+09,
        ),
        fx=0.196082,
    ),
    "AMT": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "USD",
            "marketCap": 7.99215e+10,
            "trailingPE": 23.592848,
            "returnOnEquity": 0.33914,
            "priceToBook": 21.485659,
            "enterpriseToEbitda": 18.654,
            "priceToSalesTrailing12Months": 7.304434,
        },
        legs=StatementLegs(
            net_income=2.5295e+09,
            revenue=1.06446e+10,
            equity=3.6525e+09,
            total_debt=4.49639e+10,
            cash=1.4748e+09,
            ebitda=6.4452e+09,
        ),
        fx=1.0,
    ),
    "INFY": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "USD",
            "marketCap": 4.3683e+10,
            "trailingPE": 13.314815,
            "returnOnEquity": 0.32,
            "priceToBook": 9.082105,
            "enterpriseToEbitda": 18.965,
            "priceToSalesTrailing12Months": 2.151976,
        },
        legs=StatementLegs(
            net_income=3.313e+09,
            revenue=2.0158e+10,
            equity=9.786e+09,
            total_debt=9.67e+08,
            cash=2.341e+09,
            ebitda=5.105e+09,
        ),
        fx=1.0,
    ),
    "9988.HK": _Case(
        info={
            "currency": "HKD",
            "financialCurrency": "CNY",
            "marketCap": 2.18337e+12,
            "trailingPE": 25.24138,
            "returnOnEquity": 0.0636,
            "priceToBook": 1.676848,
            "enterpriseToEbitda": 20.055,
            "priceToSalesTrailing12Months": 2.089409,
        },
        legs=StatementLegs(
            net_income=1.05904e+11,
            revenue=1.02367e+12,
            equity=1.06089e+12,
            total_debt=2.81722e+11,
            cash=1.3153e+11,
            ebitda=1.86298e+11,
        ),
        fx=0.854203,
    ),
    "BP.L": _Case(
        info={
            "currency": "GBp",
            "financialCurrency": "USD",
            "marketCap": 8.61009e+10,
            "trailingPE": 21.43077,
            "returnOnEquity": 0.08868,
            "priceToBook": 1.99424,
            "enterpriseToEbitda": 3.511,
            "priceToSalesTrailing12Months": 0.399605,
        },
        legs=StatementLegs(
            net_income=5.4e+07,
            revenue=1.89335e+11,
            equity=5.3052e+10,
            total_debt=7.2529e+10,
            cash=3.6556e+10,
            ebitda=3.0696e+10,
        ),
        fx=1.334312,
    ),
    "MRK": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "USD",
            "marketCap": 3.72321e+11,
            "trailingPE": 119.769844,
            "returnOnEquity": 0.06961,
            "priceToBook": 8.884376,
            "enterpriseToEbitda": 14.397,
            "priceToSalesTrailing12Months": 5.593007,
        },
        legs=StatementLegs(
            net_income=1.8254e+10,
            revenue=6.5011e+10,
            equity=5.2606e+10,
            total_debt=4.9339e+10,
            cash=1.4565e+10,
            ebitda=2.8262e+10,
        ),
        fx=1.0,
    ),
    "FEMSAUBD.MX": _Case(
        info={
            "currency": "MXN",
            "financialCurrency": "MXN",
            "marketCap": 8.68793e+11,
            "trailingPE": 16.287481,
            "returnOnEquity": 0.14746,
            "priceToBook": 3.288962,
            "enterpriseToEbitda": 9.045,
            "priceToSalesTrailing12Months": 0.995367,
        },
        legs=StatementLegs(
            net_income=1.9431e+10,
            revenue=8.40954e+11,
            equity=2.44982e+11,
            total_debt=2.57557e+11,
            cash=1.0798e+11,
            ebitda=1.15391e+11,
        ),
        fx=1.0,
    ),
    "GSK.L": _Case(
        info={
            "currency": "GBp",
            "financialCurrency": "GBP",
            "marketCap": 7.55458e+10,
            "trailingPE": 15.983052,
            "returnOnEquity": 0.33383,
            "priceToBook": 4.282471,
            "enterpriseToEbitda": 8.42,
            "priceToSalesTrailing12Months": 2.275271,
        },
        legs=StatementLegs(
            net_income=5.716e+09,
            revenue=3.2667e+10,
            equity=1.6377e+10,
            total_debt=1.772e+10,
            cash=3.15e+09,
            ebitda=1.0402e+10,
        ),
        fx=1.0,
    ),
    "ABBN.SW": _Case(
        info={
            "currency": "CHF",
            "financialCurrency": "USD",
            "marketCap": 1.49243e+11,
            "trailingPE": 36.794643,
            "returnOnEquity": 0.32575,
            "priceToBook": 11.460049,
            "enterpriseToEbitda": 21.631,
            "priceToSalesTrailing12Months": 4.174398,
        },
        legs=StatementLegs(
            net_income=4.734e+09,
            revenue=3.322e+10,
            equity=1.6087e+10,
            total_debt=9.09e+09,
            cash=4.64e+09,
            ebitda=7.118e+09,
        ),
        fx=1.218294,
    ),
    "CIB": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "COP",
            "marketCap": 2.22019e+10,
            "trailingPE": 9.438755,
            "returnOnEquity": 0.19219,
            "priceToBook": 0.002118,
            "enterpriseToEbitda": None,
            "priceToSalesTrailing12Months": None,
        },
        legs=StatementLegs(
            net_income=2.06087e+12,
            revenue=2.7568e+13,
            equity=3.97546e+13,
            total_debt=1.80912e+13,
            cash=2.52428e+13,
            ebitda=None,
        ),
        fx=3334.570068,
    ),
    "BSBR": _Case(
        info={
            "currency": "USD",
            "financialCurrency": "BRL",
            "marketCap": 4.26415e+10,
            "trailingPE": 16.27143,
            "returnOnEquity": 0.11151,
            "priceToBook": 0.427418,
            "enterpriseToEbitda": None,
            "priceToSalesTrailing12Months": 0.883087,
        },
        legs=StatementLegs(
            net_income=6.19757e+09,
            revenue=4.66803e+10,
            equity=1.25174e+11,
            total_debt=2.81139e+10,
            cash=2.01982e+11,
            ebitda=None,
        ),
        fx=5.1879,
    ),
}


# --------------------------------------------------------------------------- #
#  Oráculo: la definición, con tipo de cambio                                 #
# --------------------------------------------------------------------------- #

def oracle_pb(case: _Case) -> float:
    return case.info["marketCap"] * case.fx / case.legs.equity


def oracle_ev_ebitda(case: _Case) -> float:
    legs = case.legs
    market_cap = case.info["marketCap"] * case.fx
    return (market_cap + legs.total_debt - (legs.cash or 0.0)) / legs.ebitda


def _relation(symbol: str) -> str:
    case = CASES[symbol]
    return statements_currency_relation(case.info, case.legs)


def _pb(symbol: str, config=None):
    case = CASES[symbol]
    return check_price_to_book(case.info, case.legs, _relation(symbol), config=config)


def _ev(symbol: str, config=None):
    case = CASES[symbol]
    return check_ev_ebitda(case.info, case.legs, _relation(symbol), config=config)


#: Un error de unidad está lejos de cualquier ruido de definición (TTM vs FY).
def _unit_error(feed: float, truth: float) -> bool:
    return not 1 / 3 <= feed / truth <= 3


# --------------------------------------------------------------------------- #
#  UM-2 — de qué moneda son los estados                                       #
# --------------------------------------------------------------------------- #

class TestRelacionDeMonedas:
    @pytest.mark.parametrize("symbol", ["PETR4.SA", "VALE3.SA"])
    def test_la_etiqueta_que_miente_no_se_cree(self, symbol):
        """Dicen BRL y BRL; los estados vienen en USD (Petrobras: patrimonio 75,6 B)."""
        info = CASES[symbol].info
        assert info["currency"] == info["financialCurrency"] == "BRL"
        assert _relation(symbol) == DIFFERENT

    @pytest.mark.parametrize("symbol", ["MRK", "FEMSAUBD.MX", "INFY", "AMT", "BRK-B"])
    def test_una_sola_via_fuera_de_banda_es_ruido_no_moneda(self, symbol):
        """MRK y FEMSA tienen utilidad anómala: la vía por ventas los salva."""
        assert _relation(symbol) == SAME

    @pytest.mark.parametrize("symbol", [
        "TSM", "SQM-B.SN", "HDB", "KB", "CEMEXCPO.MX", "EQNR.OL",
        "9988.HK", "BP.L", "ABBN.SW", "CIB", "BSBR",
    ])
    def test_la_etiqueta_distinta_se_cree(self, symbol):
        assert _relation(symbol) == DIFFERENT

    def test_peniques_y_libras_son_la_misma_moneda(self):
        assert _relation("GSK.L") == SAME

    def test_sin_etiqueta_no_se_afirma_nada(self):
        info = dict(CASES["TSM"].info, financialCurrency=None)
        assert statements_currency_relation(info, CASES["TSM"].legs) == UNKNOWN

    @pytest.mark.parametrize("code,major", [
        ("GBp", "GBP"), ("ZAc", "ZAR"), ("ILA", "ILS"), ("usd", "USD"), (None, None),
    ])
    def test_subunidades(self, code, major):
        """``.upper()`` acierta GBp por casualidad y erra ZAc e ILA."""
        assert major_currency(code) == major


# --------------------------------------------------------------------------- #
#  UM-1 — P/B                                                                 #
# --------------------------------------------------------------------------- #

class TestPriceToBook:
    @pytest.mark.parametrize("symbol", ["TSM", "SQM-B.SN", "HDB", "KB", "CIB", "BSBR"])
    def test_roto_con_monedas_distintas_no_se_mide(self, symbol):
        case = CASES[symbol]
        assert _unit_error(case.info["priceToBook"], oracle_pb(case))  # la fixture es un caso roto
        check = _pb(symbol)
        assert check.status == NOT_MEASURABLE
        assert check.value is None

    def test_roto_con_la_misma_moneda_se_reconstruye_exacto(self):
        """BRK-B: el feed divide el precio B por el valor libro de la acción A."""
        case = CASES["BRK-B"]
        check = _pb("BRK-B")
        assert check.status == REPLACED
        assert check.value == pytest.approx(case.info["marketCap"] / case.legs.equity)
        assert check.value == pytest.approx(oracle_pb(case), rel=0.01)

    @pytest.mark.parametrize("symbol", [
        "9988.HK", "BP.L", "MRK", "FEMSAUBD.MX", "GSK.L", "ABBN.SW",
        "CEMEXCPO.MX", "EQNR.OL", "PETR4.SA", "VALE3.SA",
    ])
    def test_sano_se_usa_tal_cual(self, symbol):
        case = CASES[symbol]
        assert not _unit_error(case.info["priceToBook"], oracle_pb(case))
        check = _pb(symbol)
        assert check.status == OK
        assert check.value == case.info["priceToBook"]

    @pytest.mark.parametrize("symbol", ["AMT", "INFY"])
    def test_los_mas_cercanos_al_corte_no_se_tocan(self, symbol):
        """AMT (REIT, 2,69×) e INFY (2,13×): discrepancias de definición, no de unidad."""
        check = _pb(symbol)
        assert check.status == OK
        assert check.value == CASES[symbol].info["priceToBook"]

    def test_sin_referencia_se_usa_el_feed(self):
        """Con pérdidas no hay P/E: no se puede verificar, y no se inventa un veredicto."""
        case = CASES["TSM"]
        info = dict(case.info, trailingPE=None)
        check = check_price_to_book(info, case.legs, DIFFERENT)
        assert check.status == UNVERIFIABLE
        assert check.value == info["priceToBook"]

    @pytest.mark.parametrize("reported", [None, 0.0, -2.0])
    def test_sin_pb_positivo_no_hay_dato(self, reported):
        info = dict(CASES["MRK"].info, priceToBook=reported)
        check = check_price_to_book(info, CASES["MRK"].legs, SAME)
        assert check.status == MISSING and check.value is None


# --------------------------------------------------------------------------- #
#  UM-1 — EV/EBITDA                                                           #
# --------------------------------------------------------------------------- #

class TestEvEbitda:
    @pytest.mark.parametrize("symbol", ["TSM", "SQM-B.SN", "CEMEXCPO.MX", "EQNR.OL"])
    def test_roto_con_monedas_distintas_no_se_mide(self, symbol):
        case = CASES[symbol]
        assert _unit_error(case.info["enterpriseToEbitda"], oracle_ev_ebitda(case))
        check = _ev(symbol)
        assert check.status == NOT_MEASURABLE
        assert check.value is None

    @pytest.mark.parametrize("symbol", ["9988.HK", "BP.L", "ABBN.SW"])
    def test_sano_con_monedas_distintas_se_usa(self, symbol):
        case = CASES[symbol]
        assert not _unit_error(case.info["enterpriseToEbitda"], oracle_ev_ebitda(case))
        check = _ev(symbol)
        assert check.status == OK
        assert check.value == case.info["enterpriseToEbitda"]

    @pytest.mark.parametrize("symbol", ["MRK", "INFY", "AMT", "GSK.L"])
    def test_con_la_misma_moneda_no_se_chequea(self, symbol):
        """Ahí las diferencias son de definición de EBITDA, no de unidad."""
        check = _ev(symbol)
        assert check.status == NOT_CHECKED
        assert check.value == CASES[symbol].info["enterpriseToEbitda"]

    def test_nunca_se_reemplaza(self):
        statuses = {_ev(s).status for s in CASES}
        assert REPLACED not in statuses


# --------------------------------------------------------------------------- #
#  Configuración y extracción                                                 #
# --------------------------------------------------------------------------- #

class TestConfig:
    def test_la_banda_sale_de_config(self):
        """Diferencial: BSBR (0,24× la referencia) deja de estar roto si se abre la banda."""
        assert _pb("BSBR").status == NOT_MEASURABLE
        wide = UnitConsistencyConfig(ratio_band=(0.2, 5.0))
        assert _pb("BSBR", config=wide).status == OK

    def test_el_interruptor_apaga_el_chequeo(self):
        off = UnitConsistencyConfig(enabled=False)
        pb, ev = _pb("TSM", config=off), _ev("TSM", config=off)
        assert pb.status == ev.status == NOT_CHECKED
        assert pb.value == CASES["TSM"].info["priceToBook"]

    def test_defaults(self):
        assert UNIT_CONSISTENCY.enabled is True
        assert UNIT_CONSISTENCY.ratio_band == pytest.approx((1 / 3, 3.0))
        assert UNIT_CONSISTENCY.implied_fx_band == (0.5, 2.0)


def test_statement_legs_toma_el_ejercicio_mas_reciente():
    """Mismo formato que yfinance: filas por concepto, columnas por fecha."""
    cols = ["2025-12-31", "2024-12-31"]
    income = pd.DataFrame(
        {"Net Income Common Stockholders": [10.0, 8.0], "Total Revenue": [100.0, 90.0],
         "EBITDA": [float("nan"), 20.0]},
        index=pd.to_datetime(cols),
    ).T
    balance = pd.DataFrame(
        {"Stockholders Equity": [50.0, 45.0], "Total Debt": [30.0, 35.0],
         "Cash And Cash Equivalents": [5.0, 4.0]},
        index=pd.to_datetime(cols),
    ).T
    legs = statement_legs(income, balance)
    assert legs == StatementLegs(net_income=10.0, revenue=100.0, equity=50.0,
                                 total_debt=30.0, cash=5.0, ebitda=20.0)
    assert statement_legs(None, None) == StatementLegs()
