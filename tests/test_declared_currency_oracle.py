"""UM-2: la etiqueta ``financialCurrency`` puede mentir, y la guarda le creía.

``docs/AUDIT_UNIDADES_MONEDA_2026-09.md``: PETR4.SA y VALE3.SA declaran
``financialCurrency = BRL``, igual que su cotización, pero los estados vienen en
USD (el patrimonio de Petrobras, 75,6 B, es la cifra en dólares). La guarda de
``fcf_yield`` compara etiquetas, así que no se activaba y el motor publicaba un
yield 5,1× más bajo: FCF en USD dividido por un market cap en BRL.

**Oráculo derivado de la definición**: un yield es un flujo sobre un valor en la
misma moneda. Convertido con BRLUSD 0,196082 (cierre del 2026-09-23), el yield de
PETR4 es 12,44 %. El motor no puede convertir sin fabricar un tipo de cambio
(``FIX_FCF_YIELD_MONEDA.md`` §3), así que lo correcto es no medir. Lo que nunca
puede hacer es publicar el 2,44 % de las patas mezcladas.

Fixtures con las cifras de la caché (22–23/09). El caso P/FFO es sintético: no hay
un REIT con la etiqueta rota en la caché. Sin red.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from analysis.currency_metric_text import currency_metric_text
from analysis.fundamental import FundamentalAnalyzer, FundamentalResult

_COLS = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]
BRL_TO_USD = 0.196082


def _cashflow(fcf):
    return pd.DataFrame({"Free Cash Flow": [fcf, fcf * 0.9, fcf * 0.8, fcf * 0.7]},
                        index=_COLS).T


def _income(net_income, revenue):
    return pd.DataFrame(
        {"Net Income Common Stockholders": [net_income] * 4, "Total Revenue": [revenue] * 4},
        index=_COLS,
    ).T


def _score_growth(info, *, fcf, net_income, revenue):
    result = FundamentalResult(symbol="X", company_name="X")
    result.market_cap = info["marketCap"]
    score = FundamentalAnalyzer()._score_growth(
        info, _income(net_income, revenue), _cashflow(fcf), result
    )
    return score, result


#: Cifras reales. FCF, utilidad e ingresos vienen en USD aunque la etiqueta diga BRL.
PETR4 = dict(
    info={"currency": "BRL", "financialCurrency": "BRL", "marketCap": 6.77572e11,
          "trailingPE": 4.871316, "priceToSalesTrailing12Months": 1.235334},
    fcf=16.526e9, net_income=1.9634e10, revenue=8.9195e10,
)
VALE3 = dict(
    info={"currency": "BRL", "financialCurrency": "BRL", "marketCap": 3.04798e11,
          "trailingPE": 27.976564, "priceToSalesTrailing12Months": 1.397712},
    fcf=2.795e9, net_income=2.352e9, revenue=3.8403e10,
)
#: Controles: etiqueta igual y cierta. MRK tiene una utilidad anómala (P/E 119,8),
#: así que la vía por ganancias sale de banda; la de ventas no. Una sola vía es ruido.
MRK = dict(
    info={"currency": "USD", "financialCurrency": "USD", "marketCap": 3.72321e11,
          "trailingPE": 119.769844, "priceToSalesTrailing12Months": 5.593007},
    fcf=12.0e9, net_income=1.8254e10, revenue=6.5011e10,
)
FEMSA = dict(
    info={"currency": "MXN", "financialCurrency": "MXN", "marketCap": 8.68793e11,
          "trailingPE": 16.287481, "priceToSalesTrailing12Months": 0.995367},
    fcf=30.0e9, net_income=1.9431e10, revenue=8.40954e11,
)


def oracle_fcf_yield_pct(case) -> float:
    """El yield desde su definición, con las dos patas en USD."""
    return case["fcf"] / (case["info"]["marketCap"] * BRL_TO_USD) * 100


class TestLaEtiquetaQueMienteNoSeCree:
    @pytest.mark.parametrize("case", [PETR4, VALE3], ids=["PETR4.SA", "VALE3.SA"])
    def test_no_publica_el_yield_de_patas_mezcladas(self, case):
        mixed = case["fcf"] / case["info"]["marketCap"] * 100
        truth = oracle_fcf_yield_pct(case)
        assert truth / mixed > 3            # la fixture es un caso roto de verdad

        _, result = _score_growth(case["info"], **{k: case[k] for k in
                                                  ("fcf", "net_income", "revenue")})
        assert result.fcf_yield is None
        note = result.notes.get("fcf_yield_currency", "")
        assert "BRL" in note and "declara" in note
        assert any("FCF yield no medible" in w for w in result.warnings)

    def test_el_texto_de_superficie_nombra_la_causa(self):
        _, result = _score_growth(PETR4["info"], fcf=PETR4["fcf"],
                                  net_income=PETR4["net_income"], revenue=PETR4["revenue"])
        prompt = currency_metric_text(result, "fcf_yield")
        rationale = currency_metric_text(result, "fcf_yield", rationale=True)
        assert prompt.startswith("no medible (") and "BRL" in prompt
        assert rationale.startswith("FCF yield not measurable:") and "BRL" in rationale
        assert "la etiqueta declara" not in prompt  # no se pega la nota cruda

    def test_la_mitad_cagr_sigue_puntuando(self):
        """Igual que la guarda de etiqueta: se descarta el yield, no el crecimiento."""
        score, _ = _score_growth(PETR4["info"], fcf=PETR4["fcf"],
                                 net_income=PETR4["net_income"], revenue=PETR4["revenue"])
        assert score > 0


class TestUnaSolaViaFueraDeBandaEsRuido:
    @pytest.mark.parametrize("case", [MRK, FEMSA], ids=["MRK", "FEMSAUBD.MX"])
    def test_el_yield_se_mide(self, case):
        _, result = _score_growth(case["info"], **{k: case[k] for k in
                                                  ("fcf", "net_income", "revenue")})
        expected = case["fcf"] / case["info"]["marketCap"] * 100
        assert result.fcf_yield == pytest.approx(round(expected, 2))
        assert "fcf_yield_currency" not in result.notes

    def test_sin_los_campos_de_las_vias_se_cree_la_etiqueta(self):
        """Sin P/E ni P/S no hay contraste: no se inventa una sospecha."""
        info = {k: v for k, v in PETR4["info"].items()
                if k not in ("trailingPE", "priceToSalesTrailing12Months")}
        _, result = _score_growth(info, fcf=PETR4["fcf"],
                                  net_income=PETR4["net_income"], revenue=PETR4["revenue"])
        assert result.fcf_yield is not None


# --------------------------------------------------------------------------- #
#  P/FFO — la misma guarda, el mismo agujero                                  #
# --------------------------------------------------------------------------- #

_NI, _DA, _MC = 1.0e9, 0.5e9, 15.0e9


def _reit_statements():
    return {
        "income_stmt": pd.DataFrame(
            {"Net Income": [_NI] * 4, "Total Revenue": [_NI * 4] * 4}, index=_COLS
        ).T,
        "balance_sheet": pd.DataFrame(
            {"Stockholders Equity": [_NI * 10] * 4, "Total Assets": [_NI * 30] * 4,
             "Current Assets": [_NI * 5] * 4, "Current Liabilities": [_NI * 3] * 4},
            index=_COLS,
        ).T,
        "cashflow": pd.DataFrame(
            {"Cash Dividends Paid": [-1.0e9] * 4, "Depreciation And Amortization": [_DA] * 4},
            index=_COLS,
        ).T,
    }


def _reit(**info_overrides):
    info = {"longName": "Test REIT", "sector": "Real Estate", "industry": "REIT - Retail",
            "country": "Brazil", "currentPrice": 100.0, "regularMarketPrice": 100.0,
            "marketCap": _MC, "currency": "BRL", "financialCurrency": "BRL"}
    info.update(info_overrides)
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=_reit_statements()),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze("TEST")


class TestPFfoConEtiquetaQueMiente:
    def test_estados_en_otra_moneda_no_miden_p_ffo(self):
        """Sintético: estados en USD, cotización en BRL (×5). P/E 3 y P/S 0,75 son los
        múltiplos coherentes con esa cotización; las dos vías dan 5 y la desmienten."""
        r = _reit(trailingPE=3.0, priceToSalesTrailing12Months=0.75)
        assert r.p_ffo is None
        assert "BRL" in r.notes.get("p_ffo_currency", "")

    def test_con_la_moneda_de_verdad_igual_se_mide(self):
        """Control: P/E 15 y P/S 3,75 son coherentes con estados en BRL."""
        r = _reit(trailingPE=15.0, priceToSalesTrailing12Months=3.75)
        assert r.p_ffo == pytest.approx(_MC / (_NI + _DA))
        assert "p_ffo_currency" not in r.notes
