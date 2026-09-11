"""The harness columns the fcf_yield/p_ffo currency series is measured with.

#114 moved scores with no before/after, because ``measure_symbol`` reported the
five dimensions but not the metric under measurement. These tests pin that the
row carries ``fcf_yield``, ``p_ffo`` and both currencies, and that
``render_comparison`` surfaces a metric change even when the score does not
move — a negative yield going to ``None`` pays 0 both ways. No cache, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.measure_score_impact as harness  # noqa: E402


def _fake_fund(fcf_yield, p_ffo=None):
    return SimpleNamespace(
        sector="Financial Services", asset_class="equity",
        total_score=60.0, adjusted_score=60.0, raw_adjusted_score=60.0,
        profitability_score=10.0, health_score=10.0, valuation_score=10.0,
        growth_score=10.0, dividend_score=10.0,
        graham_value=None, margin_of_safety_pct=None, is_value_stock=lambda: False,
        eps_cagr_5y=None, eps_cagr_years=0, revenue_cagr_5y=None,
        dividend_yield=None, debt_equity=None, data_quality={"level": "good"},
        moat_score=0.0, moat_bonus=0.0, moat_classification="None",
        moat_detail=None, fcf_yield=fcf_yield, p_ffo=p_ffo,
    )


def _row(monkeypatch, fund, info):
    import analysis.strategy
    import data.fetcher

    tech = SimpleNamespace(signal="NEUTRAL", adx=20.0, atr_pct=2.0)
    decision = SimpleNamespace(action="HOLD", confidence=50, blocked=False)
    monkeypatch.setattr(analysis.strategy, "full_analysis",
                        lambda sym, ai_config=None: (fund, tech, decision))
    monkeypatch.setattr(data.fetcher, "get_info", lambda sym: info)
    return harness.measure_symbol("CIB")


class TestLaFilaTraeLaMetricaBajoMedicion:
    def test_columnas_presentes(self, monkeypatch):
        row = _row(monkeypatch, _fake_fund(None, 11.2),
                   {"financialCurrency": "COP", "currency": "USD"})
        assert row["fcf_yield"] is None
        assert row["p_ffo"] == 11.2
        assert row["financial_currency"] == "COP"
        assert row["currency"] == "USD"

    def test_info_sin_monedas_da_none_no_string_vacio(self, monkeypatch):
        row = _row(monkeypatch, _fake_fund(1.4), {})
        assert row["financial_currency"] is None
        assert row["currency"] is None


class TestLaComparacion:
    def test_mismo_arbol_da_cero_movidos(self, monkeypatch):
        row = _row(monkeypatch, _fake_fund(1.4), {"financialCurrency": "USD", "currency": "USD"})
        report = harness.render_comparison({"KO": row}, {"KO": dict(row)})
        assert "Con score modificado: **0**" in report
        assert "Con `fcf_yield`/`p_ffo` modificado: **0**" in report

    def test_metrica_que_cambia_sin_mover_score_se_ve(self, monkeypatch):
        before = _row(monkeypatch, _fake_fund(-494.22), {"financialCurrency": "CLP", "currency": "USD"})
        after = dict(before, fcf_yield=None)
        report = harness.render_comparison({"BSAC": before}, {"BSAC": after})
        assert "Con score modificado: **0**" in report
        assert "Con `fcf_yield`/`p_ffo` modificado: **1**" in report
        assert "| BSAC | fcf_yield | -494.22 | None | CLP/USD |" in report

    def test_baseline_sin_las_columnas_no_cuenta_como_cambio(self, monkeypatch):
        after = _row(monkeypatch, _fake_fund(None), {"financialCurrency": "BRL", "currency": "USD"})
        before = {k: v for k, v in after.items() if k not in harness._MEASURED_METRICS}
        report = harness.render_comparison({"ITUB": before}, {"ITUB": after})
        assert "Con `fcf_yield`/`p_ffo` modificado: **0**" in report
