"""COMMITTEE-BANKS (2026-10-19): in a bank, a 0.0 ROIC or gross margin is not a fact.

The COMMITTEE-PROMPTS audit (D2) saw it in the committee prompt for BSBR:
``ROIC: 0.0%`` and the alerts «Low ROIC: 0.0%; Thin gross margin: 0.0%». The same
holds for JPM, ITUB, CIB, BAC and others. The causes, measured on the cache:

- **ROIC.** A bank's income statement has no ``EBIT`` or ``Operating Income`` row.
  ``FundamentalAnalyzer._row`` answers 0.0 for an absent row, and ``roic_pct`` turned
  that into 0 %.
- **Gross margin.** For a company with no cost of sales, the feed reports
  ``grossMargins = 0``.
- **Data quality.** Because 0.0 is not ``None``, ``compute_data_quality`` counted both
  as present: the bank showed «Datos 🟢» on data that does not exist.

User decision (2026-10-19): they **do not apply**, the same as D/E and current ratio
in U5-5. They are neither missing nor checked, they raise no alert, and the prompt says
«no aplica». The suppression is tied to the cause, not to the marker:

- A marked company (no ``Current Assets``) that does have EBIT keeps its ROIC
  (BRK-B, ZURN.SW).
- A marked company that reports a real gross margin keeps it (GS 81 %).

Nothing here changes a score: a 0.0 and a ``None`` both earn 0 points.
``measure_score_impact`` measured it over 197 tickers: no score, signal or quality
level changed.
"""

from __future__ import annotations

from typing import Tuple

import pandas as pd

from analysis.committee_prompts import committee_context_block
from analysis.eval_cases import golden_cases
from analysis.fundamental import (
    GROSS_MARGIN_NOT_APPLICABLE,
    ROIC_NOT_APPLICABLE,
    FundamentalAnalyzer,
    FundamentalResult,
    compute_data_quality,
    inapplicable_quality_fields,
    suppressed_quality_fields,
)
from analysis.prompts import not_applicable_text
from config import THRESHOLDS as T

COL = ["2025-12-31 00:00:00"]


def _info(**overrides):
    base = {"longName": "Test Bank", "sector": "Financial Services", "industry": "Banks - Regional",
            "country": "United States", "currentPrice": 30.0, "marketCap": 1e10,
            "returnOnEquity": 0.12, "profitMargins": 0.25}
    base.update(overrides)
    return base


def _statements(*, ebit=None, current_assets=False) -> Tuple[pd.DataFrame, pd.DataFrame]:
    income = {"Net Income": [1000.0], "Total Revenue": [4000.0]}
    if ebit is not None:
        income["EBIT"] = [ebit]
    balance = {"Stockholders Equity": [10000.0], "Long Term Debt": [5000.0]}
    if current_assets:
        balance["Current Assets"] = [3000.0]
    return pd.DataFrame(income, index=COL).T, pd.DataFrame(balance, index=COL).T


def _profitability(info, income, balance):
    result = FundamentalResult(symbol="TEST")
    score = FundamentalAnalyzer()._score_profitability(info, income, balance, result)
    result.data_quality = compute_data_quality(
        result, not_applicable=inapplicable_quality_fields(balance) + suppressed_quality_fields(result)
    )
    return score, result


# --------------------------------------------------------------------------- #
#  El banco: no aplica                                                         #
# --------------------------------------------------------------------------- #

def test_un_banco_no_tiene_roic_ni_margen_bruto_y_no_lo_alerta():
    income, balance = _statements()  # sin EBIT, sin Current Assets
    _, result = _profitability(_info(grossMargins=0.0), income, balance)
    assert result.roic is None and result.gross_margin is None
    assert not any("ROIC" in w or "gross margin" in w for w in result.warnings), result.warnings
    assert result.notes["roic_not_applicable"] == ROIC_NOT_APPLICABLE
    assert result.notes["gross_margin_not_applicable"] == GROSS_MARGIN_NOT_APPLICABLE
    assert "ROIC" not in result.notes.get("profitability_missing", "")


def test_no_aplica_no_es_faltante_ni_chequeado():
    income, balance = _statements()
    _, result = _profitability(_info(grossMargins=0.0), income, balance)
    dq = result.data_quality
    assert set(dq["not_applicable"]) == {"roic", "gross_margin", "debt_equity", "current_ratio"}
    assert "roic" not in dq["missing_fields"] and "gross_margin" not in dq["missing_fields"]
    assert dq["n_checked"] == 6


def _oracle_band(value, bands):
    """Puntos por la definición: sin valor no hay banda; con valor, la primera
    banda cuyo piso alcanza paga. No comparte código con el motor."""
    if value is None:
        return 0.0
    for floor, points in bands:
        if value >= floor:
            return points
    return 0.0


def test_el_score_de_rentabilidad_no_cambia():
    """ROE 12 % y margen neto 25 % pagan sus bandas; ROIC y margen bruto, que no
    aplican, no pagan nada, igual que pagaba su 0,0 antes del cambio."""
    income, balance = _statements()
    score, _ = _profitability(_info(grossMargins=0.0), income, balance)
    expected = (
        _oracle_band(12.0, [(T.roe_excellent, 8.0), (T.roe_good, 5.0), (T.roe_min, 2.0)])
        + _oracle_band(25.0, [(T.net_margin_excellent, 5.0), (T.net_margin_good, 3.0),
                              (T.net_margin_min, 1.0)])
    )
    assert score == expected


def test_una_fila_ebit_vacia_no_tapa_el_resultado_operativo():
    """Si EBIT viene todo NaN y Operating Income tiene valor, el ROIC se calcula con
    este último en vez de valer 0,0."""
    income = pd.DataFrame({"EBIT": [float("nan")], "Operating Income": [2000.0],
                           "Net Income": [1000.0]}, index=COL).T
    _, balance = _statements()
    _, result = _profitability(_info(grossMargins=0.30), income, balance)
    assert result.roic is not None and result.roic > 0
    assert "roic_not_applicable" not in result.notes


# --------------------------------------------------------------------------- #
#  La causa, no el marcador                                                    #
# --------------------------------------------------------------------------- #

def test_un_marcado_con_ebit_conserva_su_roic():
    """BRK-B y ZURN.SW no tienen Current Assets pero sí EBIT."""
    income, balance = _statements(ebit=2000.0)
    _, result = _profitability(_info(grossMargins=0.30), income, balance)
    assert result.roic is not None and result.roic > 0
    assert "roic_not_applicable" not in result.notes
    assert "roic" not in result.data_quality["not_applicable"]


def test_un_marcado_con_margen_bruto_real_lo_conserva():
    """GS: sin Current Assets ni EBIT, y el feed informa un margen bruto de 81 %."""
    income, balance = _statements()
    _, result = _profitability(_info(grossMargins=0.81287), income, balance)
    assert round(result.gross_margin, 2) == 81.29
    assert "gross_margin" not in result.data_quality["not_applicable"]


def test_sin_ebit_y_sin_marcador_el_roic_falta():
    """Un 0,0 inventado tampoco vale fuera de un banco: ahí el dato falta."""
    income, balance = _statements(current_assets=True)
    _, result = _profitability(_info(grossMargins=0.40), income, balance)
    assert result.roic is None
    assert "roic" in result.data_quality["missing_fields"]
    assert "roic_not_applicable" not in result.notes


def test_un_margen_bruto_cero_reportado_fuera_de_un_banco_sigue_siendo_un_hecho():
    income, balance = _statements(ebit=2000.0, current_assets=True)
    _, result = _profitability(_info(grossMargins=0.0), income, balance)
    assert result.gross_margin == 0.0
    assert any("Thin gross margin: 0.0%" in w for w in result.warnings)


# --------------------------------------------------------------------------- #
#  Lo que ve el prompt                                                         #
# --------------------------------------------------------------------------- #

def _bank_fund():
    case = golden_cases()[0]
    import copy
    fund = copy.deepcopy(case.fund)
    fund.roic = None
    fund.gross_margin = None
    fund.debt_equity = None
    fund.data_quality = {"level": "good", "missing_fields": [], "n_missing": 0, "n_checked": 6,
                         "not_applicable": ["roic", "gross_margin", "debt_equity", "current_ratio"]}
    return fund, case.tech


def test_el_comite_ve_no_aplica():
    fund, tech = _bank_fund()
    block = committee_context_block(fund, tech)
    assert "ROIC: no aplica" in block
    assert "D/E: no aplica" in block


def test_el_fundamental_ve_no_aplica():
    from analysis.prompts import equity_decision_prompt
    fund, tech = _bank_fund()
    prompt = equity_decision_prompt(fund, tech)
    assert "ROIC=no aplica" in prompt and "Margen Bruto=no aplica" in prompt


def test_solo_un_valor_vacio_se_rotula_no_aplica():
    fund, _ = _bank_fund()
    fund.debt_equity = 1.4
    assert not_applicable_text(fund, "debt_equity", "1.4") == "1.4"
    fund.data_quality = None  # fixtures sin calidad de datos
    fund.roic = None
    assert not_applicable_text(fund, "roic", "n/d") == "n/d"
