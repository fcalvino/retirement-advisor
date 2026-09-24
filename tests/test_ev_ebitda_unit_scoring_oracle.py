"""UM-1, EV/EBITDA: el scorer deja de puntuar un EV/EBITDA roto por unidad (PR 4b).

``docs/AUDIT_UNIDADES_MONEDA_2026-09.md``: cuando la cotización y los estados vienen
en monedas distintas, el ``enterpriseToEbitda`` del feed sale roto en TSM (0,20× su
valor: cobraba la banda máxima), SQM-B.SN (313×), CEMEXCPO.MX (10,8×) y EQNR.OL
(7,0×). La banda de EV/EBITDA (5 puntos) lo puntuaba tal cual.

**Oráculo**: EV/EBITDA desde su definición, ``(marketCap × FX + deuda − caja) /
EBITDA``, con el FX del 2026-09-23 (``tests/test_unit_consistency_oracle.py``). Lo
que se exige: roto con monedas distintas → **no se mide** (nunca se reemplaza: con
la misma moneda las diferencias son de definición de EBITDA, no de unidad); sano →
la banda de siempre.

Sin red.
"""

from __future__ import annotations

import pytest

from analysis.currency_metric_text import currency_metric_text
from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from config import THRESHOLDS
from tests.test_unit_consistency_oracle import CASES, oracle_ev_ebitda

BROKEN = ["TSM", "SQM-B.SN", "CEMEXCPO.MX", "EQNR.OL"]
SANE_OTHER_CURRENCY = ["9988.HK", "BP.L", "ABBN.SW"]
SAME_CURRENCY = ["MRK", "INFY", "AMT", "GSK.L", "FEMSAUBD.MX"]


def band_points(ev: float) -> int:
    """La banda de EV/EBITDA desde ``config.THRESHOLDS``."""
    if ev <= THRESHOLDS.ev_ebitda_excellent:
        return 5
    if ev <= THRESHOLDS.ev_ebitda_good:
        return 3
    if ev <= THRESHOLDS.ev_ebitda_acceptable:
        return 1
    return 0


def _valuation(symbol: str, **overrides):
    info = dict(CASES[symbol].info, sector="Industrials", industry="Conglomerates")
    info.update(overrides)
    result = FundamentalResult(symbol=symbol)
    score = FundamentalAnalyzer()._score_valuation(info, result, legs=CASES[symbol].legs)
    return score, result


def ev_points_paid(symbol: str) -> float:
    with_ev, _ = _valuation(symbol)
    without_ev, _ = _valuation(symbol, enterpriseToEbitda=None)
    return with_ev - without_ev


class TestRotoConMonedasDistintas:
    @pytest.mark.parametrize("symbol", BROKEN)
    def test_no_se_mide(self, symbol):
        case = CASES[symbol]
        feed, truth = case.info["enterpriseToEbitda"], oracle_ev_ebitda(case)
        assert not 1 / 3 <= feed / truth <= 3                 # la fixture es un caso roto
        _, result = _valuation(symbol)
        assert result.ev_ebitda is None
        assert "ev_ebitda_currency" in result.notes
        assert ev_points_paid(symbol) == 0

    def test_tsm_ya_no_cobra_la_banda_maxima_por_un_numero_roto(self):
        case = CASES["TSM"]
        assert band_points(case.info["enterpriseToEbitda"]) == 5    # lo que cobraba
        assert band_points(oracle_ev_ebitda(case)) < 5               # lo que vale
        assert ev_points_paid("TSM") == 0

    def test_el_texto_de_superficie_lo_explica(self):
        _, result = _valuation("EQNR.OL")
        assert currency_metric_text(result, "ev_ebitda").startswith("no medible (")
        assert currency_metric_text(result, "ev_ebitda", rationale=True).startswith(
            "EV/EBITDA not measurable:"
        )
        assert any("EV/EBITDA no medible" in w for w in result.warnings)


class TestSanoNoCambia:
    @pytest.mark.parametrize("symbol", SANE_OTHER_CURRENCY + SAME_CURRENCY)
    def test_misma_banda_y_mismo_valor(self, symbol):
        feed = CASES[symbol].info["enterpriseToEbitda"]
        _, result = _valuation(symbol)
        assert result.ev_ebitda == feed
        assert ev_points_paid(symbol) == band_points(feed)
        assert "ev_ebitda_currency" not in result.notes


class TestLaIaVeQueNoSeMidio:
    def test_el_prompt_dice_no_medible(self):
        from analysis.prompts import equity_decision_prompt
        from analysis.technical import TechnicalResult

        _, result = _valuation("EQNR.OL")
        prompt = equity_decision_prompt(result, TechnicalResult("EQNR.OL"))
        assert "EV/EBITDA=no medible (" in prompt
        assert "EV/EBITDA=N/A" not in prompt

    def test_un_ev_medido_se_muestra_igual_que_siempre(self):
        from analysis.prompts import equity_decision_prompt
        from analysis.technical import TechnicalResult

        _, result = _valuation("MRK")
        prompt = equity_decision_prompt(result, TechnicalResult("MRK"))
        assert f"EV/EBITDA={CASES['MRK'].info['enterpriseToEbitda']:.1f}x" in prompt
