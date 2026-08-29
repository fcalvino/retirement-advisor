"""El payout que el motor juzga es el que persiste y el que leen los riesgos (U2-6).

El defecto: la auditoría por industria (2026-08-22) arregló el **score** de dividendos
de un REIT — lo gradúa contra el payout sobre FFO — pero ese número vivía en una
variable local de ``_score_dividends``. El campo que quedaba en el resultado,
``FundamentalResult.payout_ratio``, seguía siendo el payout contable, y todo consumidor
que juzga sostenibilidad leía ese campo viejo:

    O:   payout contable 236 %  →  payout sobre FFO  70 %
    EQR: payout contable 121 %  →  payout sobre FFO  63 %
    MAA: payout contable 178 %  →  payout sobre FFO  74 %

``analysis/strategy.py`` comparaba ese 236 % contra un ``80`` literal y publicaba
«High dividend payout ratio (236%) — may cut dividend» en ``decision.risks`` para un
REIT cuyo dividendo el propio motor acababa de puntuar como sano. Medido en el universo
cacheado, 12 de 13 REITs disparaban esa línea.

Per CONTEXT §5 los oráculos de abajo salen de la definición — efectivo distribuido sobre
funds from operations — nunca de los helpers de producción, y el umbral se lee de
``config.py`` en vez de repetir el literal.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from unittest.mock import patch

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, FundamentalResult, effective_payout_pct
from analysis.strategy import RetirementStrategy
from analysis.technical import TechnicalResult
from config import THRESHOLDS as T

#: Fragmentos del riesgo que esta fila existe para sacar de un REIT sano.
_CUT_DIVIDEND = ("may cut dividend", "High dividend payout")


# --------------------------------------------------------------------------- #
#  Oráculos — desde la definición                                             #
# --------------------------------------------------------------------------- #

def oracle_ffo(net_income: float, depreciation: float) -> float:
    """Funds from operations: utilidad neta + D&A."""
    return net_income + depreciation


def oracle_payout_pct(dividends_paid: float, ffo: float) -> float:
    """Efectivo distribuido sobre FFO, en porcentaje. La fila de caja es negativa."""
    return abs(dividends_paid) / ffo * 100


def oracle_says_unsustainable(payout_pct: Optional[float], cut: float) -> bool:
    """Un payout es insostenible cuando supera el corte. Un desconocido no lo es."""
    return payout_pct is not None and payout_pct > cut


# --------------------------------------------------------------------------- #
#  Fixtures                                                                   #
# --------------------------------------------------------------------------- #

def _statements(
    net_income: float,
    depreciation: Optional[float],
    dividends_paid: float,
    *,
    years: int = 4,
) -> Dict[str, pd.DataFrame]:
    columns = [f"{2025 - i}-12-31 00:00:00" for i in range(years)]
    income: Dict[str, List[float]] = {
        "Net Income": [net_income * (1 - 0.04 * i) for i in range(years)],
        "Total Revenue": [net_income * 4 * (1 - 0.03 * i) for i in range(years)],
    }
    cash: Dict[str, List[float]] = {
        "Cash Dividends Paid": [dividends_paid * (1 - 0.02 * i) for i in range(years)],
        "Free Cash Flow": [net_income * 1.2 for _ in range(years)],
    }
    if depreciation is not None:
        cash["Depreciation And Amortization"] = [
            depreciation * (1 - 0.02 * i) for i in range(years)
        ]
    return {
        "income_stmt": pd.DataFrame(income, index=columns).T,
        "balance_sheet": pd.DataFrame(
            {
                "Stockholders Equity": [net_income * 10 for _ in range(years)],
                "Total Assets": [net_income * 30 for _ in range(years)],
                "Current Assets": [net_income * 5 for _ in range(years)],
                "Current Liabilities": [net_income * 3 for _ in range(years)],
            },
            index=columns,
        ).T,
        "cashflow": pd.DataFrame(cash, index=columns).T,
    }


def _statements_for_payout(
    ffo_payout_pct: float,
    *,
    net_income: float = 1.0e9,
    depreciation: float = 2.0e9,
) -> Dict[str, pd.DataFrame]:
    """Estados cuyo payout **sobre FFO** es exactamente el pedido."""
    ffo = oracle_ffo(net_income, depreciation)
    return _statements(
        net_income=net_income,
        depreciation=depreciation,
        dividends_paid=-ffo * ffo_payout_pct / 100,
    )


def _analyze(sector: str, market_cap: float, statements, **info_extra) -> FundamentalResult:
    info = {
        "longName": "Test Co",
        "sector": sector,
        "industry": "REIT - Retail" if sector == "Real Estate" else "Specialty Retail",
        "country": "United States",
        "currentPrice": 100.0,
        "regularMarketPrice": 100.0,
        "marketCap": market_cap,
        "dividendYield": 3.0,          # ya en porcentaje — dentro del sweet spot
    }
    info.update(info_extra)
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=statements),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze("TEST")


def _tech() -> TechnicalResult:
    return TechnicalResult(
        symbol="TEST",
        signal="BULLISH",
        above_sma200=True,
        rsi_weekly=55.0,
        price_vs_52w_low_pct=20.0,
    )


def _risks(fundamental: FundamentalResult) -> List[str]:
    return RetirementStrategy().decide(fundamental, _tech()).risks


def _payout_risks(risks: List[str]) -> List[str]:
    return [r for r in risks if any(frag in r for frag in _CUT_DIVIDEND)]


# --------------------------------------------------------------------------- #
#  1. El payout efectivo se persiste, con su base                             #
# --------------------------------------------------------------------------- #

class TestPersistedPayout:
    def test_a_reit_persists_the_ffo_payout_and_names_its_base(self):
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        result = _analyze("Real Estate", 59e9, st, payoutRatio=2.36)

        expected = oracle_payout_pct(-2.5e9, oracle_ffo(1.06e9, 2.52e9))
        assert result.payout_ratio_effective == pytest.approx(expected)
        assert result.payout_basis == "ffo"

    def test_the_accounting_payout_is_still_reported_untouched(self):
        """El número que se compara contra un filing no se toca — se le suma contexto."""
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        result = _analyze("Real Estate", 59e9, st, payoutRatio=2.36)

        assert result.payout_ratio == pytest.approx(236.0)
        assert result.payout_ratio_effective < result.payout_ratio

    def test_an_operating_company_measures_against_earnings(self):
        st = _statements(net_income=1.0e9, depreciation=0.2e9, dividends_paid=-0.55e9)
        result = _analyze("Consumer Defensive", 20e9, st, payoutRatio=0.55)

        assert result.payout_basis == "earnings"
        assert result.payout_ratio_effective == pytest.approx(result.payout_ratio)

    def test_no_dividend_still_populates_the_pair(self):
        """El return temprano de yield 0 no puede dejar los campos sin definir."""
        st = _statements(net_income=1.0e9, depreciation=0.2e9, dividends_paid=0.0)
        result = _analyze("Technology", 50e9, st, dividendYield=0.0)

        assert result.payout_basis == "earnings"
        assert result.payout_ratio_effective is None

    def test_a_reit_without_ffo_falls_back_to_earnings(self):
        """Forma SPG: sin D&A no hay FFO, y el motor lo dice en vez de inventarlo."""
        st = _statements(net_income=1.0e9, depreciation=None, dividends_paid=-0.5e9)
        result = _analyze("Real Estate", 20e9, st, payoutRatio=0.50)

        assert result.ffo_payout_pct is None
        assert result.payout_basis == "earnings"
        assert result.payout_ratio_effective == pytest.approx(50.0)

    def test_the_helper_is_pure_and_reads_any_result_shape(self):
        from types import SimpleNamespace

        reit = SimpleNamespace(payout_ratio=236.0, ffo_payout_pct=70.0)
        assert effective_payout_pct(reit) == (70.0, "ffo")

        operating = SimpleNamespace(payout_ratio=55.0, ffo_payout_pct=None)
        assert effective_payout_pct(operating) == (55.0, "earnings")

        empty = SimpleNamespace()
        assert effective_payout_pct(empty) == (None, "earnings")


# --------------------------------------------------------------------------- #
#  2. El oráculo de la fila: un REIT sano deja de decir «cut dividend»        #
# --------------------------------------------------------------------------- #

class TestHealthyReitsStopSayingCutDividend:
    @pytest.mark.parametrize("name,accounting_payout,ffo_payout", [
        ("O", 236.0, 70.0),
        ("EQR", 121.0, 63.0),
        ("MAA", 178.0, 74.0),
    ])
    def test_the_audited_shapes(self, name, accounting_payout, ffo_payout):
        st = _statements_for_payout(ffo_payout)
        result = _analyze("Real Estate", 40e9, st, payoutRatio=accounting_payout / 100)

        assert result.payout_ratio_effective == pytest.approx(ffo_payout, abs=0.5)
        assert _payout_risks(_risks(result)) == [], name

    @pytest.mark.parametrize("ffo_payout", [10.0, 40.0, 60.0, 70.0, 74.9])
    def test_every_healthy_ffo_payout_is_silent(self, ffo_payout):
        """Barrido bajo el corte: ningún payout sano sobre FFO produce el riesgo."""
        st = _statements_for_payout(ffo_payout)
        result = _analyze("Real Estate", 40e9, st, payoutRatio=2.36)

        assert _payout_risks(_risks(result)) == []

    def test_the_dividend_dimension_agrees_with_the_decision(self):
        """Un REIT sano tampoco arrastra el warning de scoring hasta los riesgos."""
        st = _statements_for_payout(70.0)
        result = _analyze("Real Estate", 40e9, st, payoutRatio=2.36)

        assert not any("ayout alto" in w for w in result.warnings)
        assert not any("ayout" in r for r in _risks(result))


# --------------------------------------------------------------------------- #
#  3. No es un mute: lo insostenible sigue diciéndose, y dice contra qué      #
# --------------------------------------------------------------------------- #

class TestUnsustainableStillFires:
    def test_a_reit_paying_above_its_ffo_is_flagged_on_ffo(self):
        st = _statements_for_payout(110.0)
        result = _analyze("Real Estate", 40e9, st, payoutRatio=1.10)

        flagged = _payout_risks(_risks(result))
        assert len(flagged) == 1
        assert "110" in flagged[0]
        assert "FFO" in flagged[0]

    def test_an_operating_company_with_a_high_payout_still_warns(self):
        st = _statements(net_income=1.0e9, depreciation=0.2e9, dividends_paid=-0.95e9)
        result = _analyze("Consumer Defensive", 20e9, st, payoutRatio=0.95)

        flagged = _payout_risks(_risks(result))
        assert len(flagged) == 1
        assert "95" in flagged[0]
        assert "earnings" in flagged[0]

    def test_the_risk_quotes_the_payout_the_engine_judged(self):
        """El riesgo nunca vuelve a citar el 236 % contable de un REIT."""
        st = _statements_for_payout(110.0)
        result = _analyze("Real Estate", 40e9, st, payoutRatio=2.36)

        flagged = _payout_risks(_risks(result))
        assert flagged and "236" not in flagged[0]


# --------------------------------------------------------------------------- #
#  4. El corte vive en config y es el mismo que el del scoring                #
# --------------------------------------------------------------------------- #

class TestThresholdComesFromConfig:
    @pytest.mark.parametrize("cut,fires", [(60.0, True), (95.0, False)])
    def test_moving_the_config_cut_moves_the_risk(self, cut, fires):
        """U5-4: for a REIT the config knob is the FFO one, not the earnings one."""
        st = _statements_for_payout(80.0)
        with patch.object(T, "reit_max_payout_ratio", cut):
            result = _analyze("Real Estate", 40e9, st, payoutRatio=2.36)
            assert bool(_payout_risks(_risks(result))) is fires

    @pytest.mark.parametrize("ffo_payout", [
        T.reit_max_payout_ratio - 0.5,
        T.reit_max_payout_ratio + 0.5,
    ])
    def test_score_and_decision_cut_at_the_same_place(self, ffo_payout):
        """No existe un payout que dispare el warning del score y no el riesgo.

        U2-6's invariant, re-checked at U5-4's threshold: the cut is now the FFO
        one for a REIT, and both sites still read exactly the same number.
        """
        st = _statements_for_payout(ffo_payout)
        result = _analyze("Real Estate", 40e9, st, payoutRatio=2.36)

        scored = any("ayout alto" in w for w in result.warnings)
        decided = bool(_payout_risks(_risks(result)))
        assert scored == decided == oracle_says_unsustainable(
            result.payout_ratio_effective, T.reit_max_payout_ratio
        )

    def test_no_literal_governs_the_cut(self):
        """Ni el 80 viejo ni el 75 de las industriales gobiernan a un REIT.

        78 % sobre FFO está por encima de los dos y **no** debe disparar: la ley
        obliga a un REIT a distribuir más del 90 % de su renta gravable, así que
        su corte es el de FFO (U5-4). Un 92 % sí lo supera.
        """
        comodo = _analyze("Real Estate", 40e9, _statements_for_payout(78.0), payoutRatio=2.36)
        assert not _payout_risks(_risks(comodo)), "78 % sobre FFO es normal para un REIT"

        estirado = _analyze("Real Estate", 40e9, _statements_for_payout(92.0), payoutRatio=2.36)
        assert _payout_risks(_risks(estirado)), "92 % sobre FFO sí supera el corte de FFO"


# --------------------------------------------------------------------------- #
#  5. El score no se movió                                                    #
# --------------------------------------------------------------------------- #

class TestScoresAreUnchanged:
    def test_the_dividend_dimension_scores_a_reit_on_reit_bands(self):
        """U2-6 prometía que la persistencia no movía puntos, y no los movió.

        U5-4 sí los mueve, a propósito: con las bandas industriales un payout del
        70 % sobre FFO caía en la banda media (2 pts) porque ≤40 % es
        estructuralmente inalcanzable para un REIT. Con la banda de FFO (≤70 %)
        entra en la superior, que es exactamente lo que esta fila corrige.
        """
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        result = _analyze("Real Estate", 59e9, st, payoutRatio=2.36)

        # yield 3.0 % en el sweet spot (4) + payout 70 % en la banda REIT (3)
        assert result.dividend_score == pytest.approx(7.0)

    def test_an_operating_company_is_untouched_end_to_end(self):
        st = _statements(net_income=1.0e9, depreciation=0.2e9, dividends_paid=-0.55e9)
        result = _analyze("Consumer Defensive", 20e9, st, payoutRatio=0.55)

        assert result.ffo_payout_pct is None
        assert result.dividend_score == pytest.approx(6.0)


# --------------------------------------------------------------------------- #
#  6. El camino AI recibe el mismo número                                     #
# --------------------------------------------------------------------------- #

class TestPromptCarriesTheEffectivePayout:
    def test_a_reit_prompt_shows_the_ffo_payout(self):
        from analysis.prompts import equity_decision_prompt

        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        result = _analyze("Real Estate", 59e9, st, payoutRatio=2.36)
        prompt = equity_decision_prompt(result, _tech())
        dividends_block = prompt.split("Graham")[0]

        expected = oracle_payout_pct(-2.5e9, oracle_ffo(1.06e9, 2.52e9))
        assert f"s/FFO={expected:.1f}%" in dividends_block
        # El contable sigue a la vista, pero etiquetado como lo que es.
        assert "s/ganancias=236.0%" in dividends_block

    def test_an_operating_prompt_does_not_invent_one(self):
        from analysis.prompts import equity_decision_prompt

        st = _statements(net_income=1.0e9, depreciation=0.2e9, dividends_paid=-0.55e9)
        result = _analyze("Consumer Defensive", 20e9, st, payoutRatio=0.55)
        prompt = equity_decision_prompt(result, _tech())

        assert "s/FFO" not in prompt
