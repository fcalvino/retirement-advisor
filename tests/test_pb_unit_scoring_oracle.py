"""UM-1, P/B: el scorer deja de puntuar un P/B roto por unidad (PR 4a).

``docs/AUDIT_UNIDADES_MONEDA_2026-09.md``: el ``priceToBook`` del feed sale de 4× a
900× de su valor en ADRs de reportantes extranjeros, en SQM-B.SN y en BRK-B, y la
banda de P/B (5 puntos) lo puntuaba tal cual. CIB y BSBR cobraban la banda máxima
por un P/B de 0,002 y 0,43; SQM, TSM, HDB y KB perdían puntos que les tocaban.

**Oráculo**: el P/B desde su definición, ``marketCap × FX / patrimonio``, con el
tipo de cambio del 2026-09-23 (``tests/test_unit_consistency_oracle.py``). El motor
nunca ve ese FX. Lo que se exige:

* monedas distintas y P/B roto → **no se mide**: 0 puntos y una nota que lo dice,
  nunca la banda del número roto;
* misma moneda y P/B roto (BRK-B) → la banda del P/B verdadero;
* P/B sano → la banda de siempre, byte-idéntica.

Sin red.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from analysis.currency_metric_text import currency_metric_text
from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from config import THRESHOLDS
from tests.test_unit_consistency_oracle import CASES, oracle_pb

BROKEN_OTHER_CURRENCY = ["TSM", "SQM-B.SN", "HDB", "KB", "CIB", "BSBR"]
SANE = ["9988.HK", "BP.L", "MRK", "FEMSAUBD.MX", "GSK.L", "ABBN.SW",
        "CEMEXCPO.MX", "EQNR.OL", "PETR4.SA", "VALE3.SA", "AMT", "INFY"]


def band_points(pb: float) -> int:
    """La banda de P/B desde ``config.THRESHOLDS`` — lo que vale un P/B dado."""
    if pb <= THRESHOLDS.pb_excellent:
        return 5
    if pb <= THRESHOLDS.pb_good:
        return 3
    if pb <= THRESHOLDS.pb_acceptable:
        return 1
    return 0


def _info(symbol: str, **overrides):
    info = dict(CASES[symbol].info, sector="Technology", industry="Software")
    info.update(overrides)
    return info


def _valuation(symbol: str, **overrides):
    result = FundamentalResult(symbol=symbol)
    score = FundamentalAnalyzer()._score_valuation(
        _info(symbol, **overrides), result, legs=CASES[symbol].legs
    )
    return score, result


def pb_points_paid(symbol: str) -> float:
    """Puntos que aporta el P/B: el score con él menos el score sin él."""
    with_pb, _ = _valuation(symbol)
    without_pb, _ = _valuation(symbol, priceToBook=None)
    return with_pb - without_pb


class TestRotoConMonedasDistintas:
    @pytest.mark.parametrize("symbol", BROKEN_OTHER_CURRENCY)
    def test_no_se_mide(self, symbol):
        _, result = _valuation(symbol)
        assert result.pb_ratio is None
        assert "pb_ratio_currency" in result.notes
        assert pb_points_paid(symbol) == 0

    @pytest.mark.parametrize("symbol", ["CIB", "BSBR"])
    def test_ya_no_cobra_la_banda_maxima_por_un_numero_roto(self, symbol):
        case = CASES[symbol]
        assert band_points(case.info["priceToBook"]) == 5      # lo que cobraba
        assert band_points(oracle_pb(case)) < 5                 # lo que vale de verdad
        assert pb_points_paid(symbol) == 0

    def test_el_texto_de_superficie_lo_explica(self):
        _, result = _valuation("TSM")
        assert currency_metric_text(result, "pb_ratio").startswith("no medible (")
        assert currency_metric_text(result, "pb_ratio", rationale=True).startswith(
            "P/B not measurable:"
        )
        assert any("P/B no medible" in w for w in result.warnings)


class TestRotoConLaMismaMoneda:
    def test_brk_b_cobra_la_banda_de_su_pb_verdadero(self):
        case = CASES["BRK-B"]
        truth = oracle_pb(case)
        _, result = _valuation("BRK-B")
        assert result.pb_ratio == pytest.approx(truth, rel=0.01)
        assert pb_points_paid("BRK-B") == band_points(truth)
        assert band_points(case.info["priceToBook"]) == 5     # el feed regalaba 5
        assert "pb_ratio_source" in result.notes
        assert "pb_ratio_currency" not in result.notes


class TestSanoNoCambia:
    @pytest.mark.parametrize("symbol", SANE)
    def test_misma_banda_y_mismo_valor(self, symbol):
        feed = CASES[symbol].info["priceToBook"]
        _, result = _valuation(symbol)
        assert result.pb_ratio == feed
        assert pb_points_paid(symbol) == band_points(feed)
        assert "pb_ratio_currency" not in result.notes
        assert "pb_ratio_source" not in result.notes


class TestElPipelineLePasaLasPatas:
    """Sin las patas del balance, BRK-B no podría reconstruirse: se prueba el cableado."""

    def test_analyze_reconstruye_brk_b(self):
        case = CASES["BRK-B"]
        cols = ["2025-12-31", "2024-12-31"]
        legs = case.legs
        statements = {
            "income_stmt": pd.DataFrame(
                {"Net Income Common Stockholders": [legs.net_income] * 2,
                 "Total Revenue": [legs.revenue] * 2},
                index=cols,
            ).T,
            "balance_sheet": pd.DataFrame(
                {"Stockholders Equity": [legs.equity] * 2,
                 "Total Debt": [legs.total_debt] * 2,
                 "Cash And Cash Equivalents": [legs.cash] * 2,
                 "Total Assets": [legs.equity * 2] * 2,
                 "Current Assets": [legs.equity * 0.5] * 2,
                 "Current Liabilities": [legs.equity * 0.3] * 2},
                index=cols,
            ).T,
            "cashflow": pd.DataFrame({"Free Cash Flow": [1e10] * 2}, index=cols).T,
        }
        info = dict(_info("BRK-B"), longName="Berkshire", currentPrice=500.0,
                    regularMarketPrice=500.0, sector="Financial Services",
                    industry="Insurance - Diversified")
        # Símbolo ficticio y los getters de data.fetcher parchados también: la suite
        # no aísla la caché de datos, y un símbolo real que llegue a data.fetcher
        # borra sus filas vencidas de config.DB_PATH (visto con BRK-B).
        with (
            patch("analysis.fundamental.get_info", return_value=info),
            patch("analysis.fundamental.get_financials", return_value=statements),
            patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
            patch("data.fetcher.get_info", return_value=info),
            patch("data.fetcher.get_financials", return_value=statements),
            patch("data.fetcher.get_info_age_hours", return_value=1.0),
        ):
            result = FundamentalAnalyzer().analyze("TEST-UM1")
        assert result.pb_ratio == pytest.approx(oracle_pb(case), rel=0.01)


class TestLaIaVeQueNoSeMidio:
    """El prompt de decisión decía «P/B=91.4x» para TSM. Ahora dice por qué no hay número."""

    def test_el_prompt_dice_no_medible_y_no_na(self):
        from analysis.prompts import equity_decision_prompt
        from analysis.technical import TechnicalResult

        _, result = _valuation("TSM")
        result.company_name, result.total_score, result.adjusted_score = "TSMC", 90, 90
        prompt = equity_decision_prompt(result, TechnicalResult("TSM"))
        assert ("P/B=no medible (el del feed no cierra con P/E × ROE y los estados "
                "vienen en otra moneda)") in prompt
        assert "P/B=N/A" not in prompt

    def test_un_pb_medido_se_muestra_igual_que_siempre(self):
        from analysis.prompts import equity_decision_prompt
        from analysis.technical import TechnicalResult

        _, result = _valuation("MRK")
        prompt = equity_decision_prompt(result, TechnicalResult("MRK"))
        assert f"P/B={CASES['MRK'].info['priceToBook']:.1f}x" in prompt
