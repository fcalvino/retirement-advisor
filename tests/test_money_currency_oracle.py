"""UM-3: un monto en moneda local no se imprime como dólares.

``docs/AUDIT_UNIDADES_MONEDA_2026-09.md``: 90 de 186 tickers cacheados cotizan
fuera de USD, y el prompt de decisión, la ficha y dos textos del motor anteponían
``$`` a montos en la moneda de cotización o de los estados. Toyota (7203.T) llegaba
al LLM como ``MARKET CAP: $35821.5B`` — 35,8 billones de yenes rotulados como
dólares, ~150× inflados.

**Oráculo**: la definición de un monto — número y unidad —. Un monto en USD (o sin
moneda conocida) se escribe como siempre, byte-idéntico; uno en otra moneda nombra
su código ISO y no lleva ``$``. La capitalización de un listado de Londres viene en
libras aunque el precio venga en peniques (``marketCap / (precio × acciones) =
0,01``, medido en la auditoría), así que se rotula GBP y el precio GBp.

Sin red.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from analysis.prompts import equity_decision_prompt
from analysis.strategy import RetirementStrategy
from analysis.technical import TechnicalResult
from data.product_ux import with_currency
from tests.test_currency_metric_page_runtime import render  # noqa: F401 — fixture


def _fund(currency: str, *, price: float, market_cap: float, graham: float = 0.0):
    fund = FundamentalResult(symbol="TEST", company_name="Test Co", currency=currency,
                             current_price=price, market_cap=market_cap,
                             total_score=65, adjusted_score=65,
                             sector="Consumer Cyclical", industry="Auto Manufacturers")
    if graham:
        fund.graham_value = graham
        fund.margin_of_safety_pct = round((graham - price) / graham * 100, 1)
    return fund


_DOLLAR_AMOUNT = re.compile(r"\$\s?-?\d")


class TestHelper:
    @pytest.mark.parametrize("currency", ["USD", "", None])
    def test_usd_o_desconocida_queda_igual(self, currency):
        assert with_currency("1234.50", currency) == "$1234.50"

    @pytest.mark.parametrize("currency", ["JPY", "GBp", "EUR", "BRL"])
    def test_otra_moneda_se_nombra_sin_signo_pesos(self, currency):
        assert with_currency("1234.50", currency) == f"1234.50 {currency}"


class TestPromptDeDecision:
    def test_toyota_no_llega_como_dolares(self):
        prompt = equity_decision_prompt(
            _fund("JPY", price=3025.0, market_cap=3.58215e13, graham=4000.0),
            TechnicalResult("TEST"),
        )
        assert "PRECIO: 3025.00 JPY | MARKET CAP: 35821.5B JPY" in prompt
        assert "Graham Value: 4000.00 JPY" in prompt
        money_lines = [ln for ln in prompt.splitlines()
                       if ln.startswith(("PRECIO:", "Graham Value:"))]
        assert money_lines and not any(_DOLLAR_AMOUNT.search(ln) for ln in money_lines)

    def test_londres_precio_en_peniques_y_capitalizacion_en_libras(self):
        prompt = equity_decision_prompt(
            _fund("GBp", price=1886.0, market_cap=7.55458e10), TechnicalResult("TEST")
        )
        assert "PRECIO: 1886.00 GBp | MARKET CAP: 75.5B GBP" in prompt

    def test_usd_byte_identico(self):
        prompt = equity_decision_prompt(
            _fund("USD", price=200.0, market_cap=3.0e12, graham=180.0),
            TechnicalResult("TEST"),
        )
        assert "PRECIO: $200.00 | MARKET CAP: $3000.0B" in prompt
        assert "Graham Value: $180.00" in prompt


class TestTextosDelMotor:
    def test_el_rationale_de_graham_nombra_la_moneda(self):
        fund = _fund("JPY", price=3025.0, market_cap=3.58e13, graham=4500.0)
        tech = TechnicalResult("TEST")
        decision = RetirementStrategy().decide(fund, tech)
        graham_lines = [r for r in decision.rationale if "Graham value" in r]
        assert graham_lines == ["Margin of Safety: 33% vs Graham value 4500.00 JPY"]

    def test_el_rationale_usd_queda_igual(self):
        fund = _fund("USD", price=100.0, market_cap=1e11, graham=150.0)
        decision = RetirementStrategy().decide(fund, TechnicalResult("TEST"))
        assert "Margin of Safety: 33% vs Graham value $150.00" in decision.rationale

    @pytest.mark.parametrize("financial,expected", [
        ("EUR", "Patrimonio neto negativo (-1.79B EUR)"),
        ("USD", "Patrimonio neto negativo ($-1.79B)"),
    ])
    def test_el_patrimonio_negativo_se_rotula_en_la_moneda_de_los_estados(
        self, financial, expected
    ):
        cols = ["2025-12-31", "2024-12-31"]
        balance = pd.DataFrame(
            {"Stockholders Equity": [-1.79e9] * 2, "Total Debt": [54.8e9] * 2,
             "Current Assets": [5e9] * 2, "Total Assets": [56e9] * 2},
            index=cols,
        ).T
        result = FundamentalResult(symbol="TEST", financial_currency=financial)
        FundamentalAnalyzer()._derive_debt_equity(balance, result)
        assert any(w.startswith(expected) for w in result.warnings), result.warnings


class TestFicha:
    def test_la_ficha_nombra_la_moneda(self, render):  # noqa: F811
        fund = _fund("JPY", price=3025.0, market_cap=3.58215e13, graham=4000.0)
        metrics = render(fund)
        graham = metrics["Graham Intrinsic Value"]
        assert graham.value == "4000.00 JPY"
        assert metrics["Margin of Safety"].proto.delta == "vs 3025.00 JPY current"

    def test_la_ficha_usd_queda_igual(self, render):  # noqa: F811
        fund = _fund("USD", price=100.0, market_cap=1e11, graham=150.0)
        metrics = render(fund)
        assert metrics["Graham Intrinsic Value"].value == "$150.00"
        assert metrics["Margin of Safety"].proto.delta == "vs $100.00 current"
