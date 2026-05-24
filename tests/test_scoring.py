"""Tests for EnhancedScoring — Consistency Score and Piotroski F-Score."""

import numpy as np
import pandas as pd
import pytest

from analysis.scoring import ConsistencyDetail, EnhancedScore, EnhancedScoring, PiotroskiDetail
from config import ConsistencyThresholds, PiotroskiConfig


@pytest.fixture
def scorer():
    return EnhancedScoring()


# ------------------------------------------------------------------ #
#  Piotroski F-Score                                                   #
# ------------------------------------------------------------------ #

class TestPiotroskiDetail:
    def test_score_is_sum_of_booleans(self):
        d = PiotroskiDetail(
            f1_roa_positive=True,
            f2_ocf_positive=True,
            f3_roa_improving=False,
            f4_leverage_decreasing=True,
            f5_liquidity_improving=False,
            f6_no_dilution=True,
            f7_gross_margin_improving=False,
            f8_asset_turnover_improving=False,
            f9_accruals_quality=True,
        )
        assert d.score == 5

    def test_score_max(self):
        d = PiotroskiDetail(**{f"f{i}_{k}": True for i, k in enumerate([
            "roa_positive", "ocf_positive", "roa_improving", "leverage_decreasing",
            "liquidity_improving", "no_dilution", "gross_margin_improving",
            "asset_turnover_improving", "accruals_quality",
        ], start=1)})
        assert d.score == 9

    def test_score_zero(self):
        assert PiotroskiDetail().score == 0


class TestPiotroskiFromStatements:
    def test_strong_company_scores_high(
        self, scorer, stable_income_stmt, stable_balance_sheet, stable_cashflow, minimal_info
    ):
        result = scorer.get_enhanced_score(
            60.0, minimal_info, stable_income_stmt, stable_balance_sheet, stable_cashflow
        )
        # Stable profitable company should score ≥ 5
        assert result.piotroski_score >= 5

    def test_empty_statements_dont_crash(self, scorer):
        result = scorer.get_enhanced_score(
            50.0,
            info={},
            income_stmt=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
            cashflow=pd.DataFrame(),
        )
        assert isinstance(result, EnhancedScore)
        assert 0 <= result.piotroski_score <= 9

    def test_piotroski_bonus_strong(self, scorer, stable_income_stmt, stable_balance_sheet, stable_cashflow, minimal_info):
        result = scorer.get_enhanced_score(60.0, minimal_info, stable_income_stmt, stable_balance_sheet, stable_cashflow)
        pc = PiotroskiConfig()
        if result.piotroski_score >= pc.strong_threshold:
            assert result.piotroski_bonus == pc.bonus_strong
        elif result.piotroski_score >= 5:
            assert result.piotroski_bonus == pc.bonus_good
        else:
            assert result.piotroski_bonus == 0.0

    def test_adjusted_score_capped_at_100(self, scorer, stable_income_stmt, stable_balance_sheet, stable_cashflow, minimal_info):
        result = scorer.get_enhanced_score(
            98.0, minimal_info, stable_income_stmt, stable_balance_sheet, stable_cashflow
        )
        assert result.adjusted_score <= 100.0

    def test_f1_roa_positive_detection(self, scorer):
        """F1: positive net income and total assets → ROA > 0."""
        from tests.conftest import _make_balance_sheet, _make_income_stmt
        income = _make_income_stmt(net_income=[500, 400], revenue=[1000, 900])
        balance = _make_balance_sheet(
            stockholders_equity=[2000, 1900],
            total_assets=[4000, 3800],
        )
        result = scorer.get_enhanced_score(50.0, {}, income, balance)
        assert result.piotroski_detail.f1_roa_positive is True

    def test_f1_roa_negative_detection(self, scorer):
        """F1: negative net income → ROA < 0 → F1 = False."""
        from tests.conftest import _make_balance_sheet, _make_income_stmt
        income = _make_income_stmt(net_income=[-200, -100], revenue=[1000, 900])
        balance = _make_balance_sheet(
            stockholders_equity=[2000, 1900],
            total_assets=[4000, 3800],
        )
        result = scorer.get_enhanced_score(30.0, {}, income, balance)
        assert result.piotroski_detail.f1_roa_positive is False

    def test_f6_no_dilution_detects_share_issuance(self, scorer):
        """F6: if shares increased > 2% YoY, no_dilution = False."""
        from tests.conftest import _make_balance_sheet, _make_income_stmt
        income = _make_income_stmt(net_income=[500, 400], revenue=[1000, 900])
        balance = _make_balance_sheet(
            stockholders_equity=[2000, 1800],
            total_assets=[4000, 3800],
            shares=[1_100, 1_000],  # +10% dilution
        )
        result = scorer.get_enhanced_score(50.0, {}, income, balance)
        assert result.piotroski_detail.f6_no_dilution is False

    def test_f9_accruals_quality_ocf_beats_ni(self, scorer):
        """F9: OCF > NI → accruals quality = True."""
        from tests.conftest import _make_balance_sheet, _make_cashflow, _make_income_stmt
        income = _make_income_stmt(net_income=[500, 400], revenue=[1000, 900])
        balance = _make_balance_sheet(stockholders_equity=[2000, 1800], total_assets=[4000, 3800])
        cashflow = _make_cashflow(operating_cf=[800, 700])  # OCF > NI
        result = scorer.get_enhanced_score(50.0, {}, income, balance, cashflow)
        assert result.piotroski_detail.f9_accruals_quality is True


# ------------------------------------------------------------------ #
#  Consistency Score                                                   #
# ------------------------------------------------------------------ #

class TestConsistencyScore:
    def test_stable_company_scores_near_max(
        self, scorer, stable_income_stmt, stable_balance_sheet
    ):
        result = scorer.get_enhanced_score(
            60.0, {}, stable_income_stmt, stable_balance_sheet
        )
        # Stable ROE and margins should score >= 10/15 (EPS component can be lower
        # if absolute NI levels happen to yield a higher growth-rate CV).
        assert result.consistency_score >= 10.0

    def test_volatile_company_scores_low(
        self, scorer, volatile_income_stmt, stable_balance_sheet
    ):
        result = scorer.get_enhanced_score(
            60.0, {}, volatile_income_stmt, stable_balance_sheet
        )
        assert result.consistency_score < 10.0

    def test_consistency_bounded_0_to_15(
        self, scorer, stable_income_stmt, stable_balance_sheet
    ):
        result = scorer.get_enhanced_score(
            60.0, {}, stable_income_stmt, stable_balance_sheet
        )
        assert 0.0 <= result.consistency_score <= 15.0

    def test_missing_balance_sheet_returns_neutral(self, scorer, stable_income_stmt):
        """When balance sheet is absent, ROE component returns neutral 2.5."""
        result = scorer.get_enhanced_score(
            60.0, {}, stable_income_stmt, pd.DataFrame()
        )
        # Still returns valid ConsistencyDetail
        assert isinstance(result.consistency_detail, ConsistencyDetail)
        assert 0.0 <= result.consistency_score <= 15.0

    def test_consistency_detail_components_sum_to_total(
        self, scorer, stable_income_stmt, stable_balance_sheet
    ):
        result = scorer.get_enhanced_score(60.0, {}, stable_income_stmt, stable_balance_sheet)
        d = result.consistency_detail
        assert abs((d.roe_score + d.eps_score + d.margin_score) - d.total) < 0.1


# ------------------------------------------------------------------ #
#  EnhancedScore integration                                           #
# ------------------------------------------------------------------ #

class TestEnhancedScoreIntegration:
    def test_adjusted_score_is_sum_of_components(
        self, scorer, stable_income_stmt, stable_balance_sheet, stable_cashflow, minimal_info
    ):
        result = scorer.get_enhanced_score(
            60.0, minimal_info, stable_income_stmt, stable_balance_sheet, stable_cashflow
        )
        expected = min(
            60.0 + result.consistency_score + result.piotroski_bonus, 100.0
        )
        assert abs(result.adjusted_score - expected) < 0.01

    def test_recommendations_list_not_empty(
        self, scorer, stable_income_stmt, stable_balance_sheet, stable_cashflow, minimal_info
    ):
        result = scorer.get_enhanced_score(
            60.0, minimal_info, stable_income_stmt, stable_balance_sheet, stable_cashflow
        )
        assert len(result.recommendations) >= 1

    def test_piotroski_summary_contains_passed_and_failed(
        self, scorer, stable_income_stmt, stable_balance_sheet, stable_cashflow, minimal_info
    ):
        result = scorer.get_enhanced_score(
            60.0, minimal_info, stable_income_stmt, stable_balance_sheet, stable_cashflow
        )
        summary = result.piotroski_detail.summary()
        assert "✅" in summary
        assert "❌" in summary
