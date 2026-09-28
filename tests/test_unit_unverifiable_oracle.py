"""UM-GDR: entre monedas distintas, un múltiplo que no se puede verificar no puntúa.

UM-1 contrasta ``priceToBook`` y ``enterpriseToEbitda`` contra ``P/E × ROE``; cuando
esa referencia no existe (pérdidas, sin P/E, sin EBITDA o deuda en los estados) el
chequeo devolvía ``UNVERIFIABLE`` y **puntuaba el feed**, también con los estados en
otra moneda. Es justo el caso de un GDR con pérdidas: SMSN.IL trae
``priceToBook=0.0039`` (el ×1000 de PB-CURRENCY) y hoy lo salva sólo que tiene P/E.

Medido el 2026-09-28 sobre la caché (194 tickers, 35 con monedas distintas): de los
EV/EBITDA que sí se podían verificar entre monedas, **8 de 27** estaban rotos; de los
P/B, 4 de 34. Un feed sin verificar entre monedas tiene esa probabilidad previa de
estar roto, y un roto hacia abajo cobra la banda máxima.

**Oráculo**: el ratio desde su definición, convertido con el tipo de cambio del día
(``oracle_pb`` / ``oracle_ev_ebitda`` de ``tests/test_unit_consistency_oracle.py``).
Las fixtures rotas siguen rotas aunque se les quite el P/E: lo que se exige es que ese
número roto deje de cobrar puntos. Sin red.
"""

from __future__ import annotations

import pytest

from analysis.currency_metric_text import currency_metric_text
from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from analysis.unit_consistency import (
    DIFFERENT,
    NOT_MEASURABLE,
    SAME,
    UNKNOWN,
    UNVERIFIABLE,
    check_ev_ebitda,
    check_price_to_book,
)
from config import THRESHOLDS
from tests.test_unit_consistency_oracle import CASES, oracle_ev_ebitda, oracle_pb

#: Sin referencia: pérdidas (sin P/E) o ROE negativo, como CSL.AX (ROE −15,8 %).
NO_REFERENCE = [{"trailingPE": None}, {"returnOnEquity": -0.158}]


def _broken(feed: float, truth: float) -> bool:
    return not 1 / 3 <= feed / truth <= 3


def _valuation(symbol: str, **overrides):
    info = dict(CASES[symbol].info, sector="Financial Services", industry="Banks")
    info.update(overrides)
    result = FundamentalResult(symbol=symbol)
    score = FundamentalAnalyzer()._score_valuation(info, result, legs=CASES[symbol].legs)
    return score, result


def _points_paid(symbol: str, key: str, **overrides) -> float:
    with_it, _ = _valuation(symbol, **overrides)
    without, _ = _valuation(symbol, **{**overrides, key: None})
    return with_it - without


class TestPriceToBook:
    @pytest.mark.parametrize("overrides", NO_REFERENCE)
    def test_sin_referencia_entre_monedas_no_se_mide(self, overrides):
        case = CASES["CIB"]
        info = dict(case.info, **overrides)
        check = check_price_to_book(info, case.legs, DIFFERENT)
        assert check.status == NOT_MEASURABLE
        assert check.value is None
        assert check.feed == case.info["priceToBook"]
        assert check.reference is None

    @pytest.mark.parametrize("relation", [SAME, UNKNOWN])
    def test_sin_referencia_con_la_misma_moneda_o_sin_etiqueta_se_usa_el_feed(self, relation):
        """La regla no se extiende: moneda desconocida no bloquea (LLM-2, PORTFOLIO-CCY)."""
        case = CASES["MRK"]
        info = dict(case.info, trailingPE=None)
        check = check_price_to_book(info, case.legs, relation)
        assert check.status == UNVERIFIABLE
        assert check.value == info["priceToBook"]

    def test_cib_con_perdidas_ya_no_cobra_la_banda_maxima_por_un_numero_roto(self):
        case = CASES["CIB"]
        assert _broken(case.info["priceToBook"], oracle_pb(case))      # la fixture es rota
        assert case.info["priceToBook"] <= THRESHOLDS.pb_excellent      # lo que cobraba
        assert _points_paid("CIB", "priceToBook", trailingPE=None) == 0

    def test_la_nota_lo_explica_y_no_cuenta_como_faltante(self):
        _, result = _valuation("CIB", trailingPE=None)
        assert result.pb_ratio is None
        note = result.notes["pb_ratio_currency"]
        assert "no se puede verificar contra P/E × ROE" in note
        assert currency_metric_text(result, "pb_ratio") == (
            "no medible (el del feed no se puede verificar contra P/E × ROE y los "
            "estados vienen en otra moneda)"
        )
        assert currency_metric_text(result, "pb_ratio", rationale=True) == (
            "P/B not measurable: feed ratio unverifiable against P/E × ROE, "
            "statements in another currency"
        )


class TestEvEbitda:
    @pytest.mark.parametrize("overrides", NO_REFERENCE)
    def test_sin_referencia_entre_monedas_no_se_mide(self, overrides):
        case = CASES["TSM"]
        info = dict(case.info, **overrides)
        check = check_ev_ebitda(info, case.legs, DIFFERENT)
        assert check.status == NOT_MEASURABLE
        assert check.value is None
        assert check.feed == case.info["enterpriseToEbitda"]

    def test_sin_ebitda_en_los_estados_tampoco(self):
        """ZURN.SW y 1299.HK: aseguradoras, sin fila de EBITDA."""
        from dataclasses import replace

        case = CASES["TSM"]
        check = check_ev_ebitda(case.info, replace(case.legs, ebitda=None), DIFFERENT)
        assert check.status == NOT_MEASURABLE
        assert check.value is None

    def test_tsm_con_perdidas_ya_no_cobra_la_banda_maxima_por_un_numero_roto(self):
        case = CASES["TSM"]
        assert _broken(case.info["enterpriseToEbitda"], oracle_ev_ebitda(case))
        assert case.info["enterpriseToEbitda"] <= THRESHOLDS.ev_ebitda_excellent
        assert _points_paid("TSM", "enterpriseToEbitda", trailingPE=None) == 0

    def test_la_nota_lo_explica(self):
        _, result = _valuation("TSM", trailingPE=None)
        assert result.ev_ebitda is None
        assert "no se puede verificar contra el reconstruido desde P/E × ROE" in (
            result.notes["ev_ebitda_currency"]
        )
        assert currency_metric_text(result, "ev_ebitda") == (
            "no medible (el del feed no se puede verificar contra P/E × ROE y los "
            "estados vienen en otra moneda)"
        )


def test_con_referencia_el_mensaje_no_cambia():
    """El texto de UM-1 que ya reconocen la UI y el prompt sigue igual, byte a byte."""
    _, result = _valuation("CIB")
    assert result.notes["pb_ratio_currency"].startswith(
        f"P/B no medible: el del feed ({CASES['CIB'].info['priceToBook']:.4g}) no cierra con "
        "P/E × ROE ("
    )
    assert currency_metric_text(result, "pb_ratio") == (
        "no medible (el del feed no cierra con P/E × ROE y los estados vienen en otra moneda)"
    )
