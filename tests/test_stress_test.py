"""Tests for StressTester — pure math, no network calls."""

import pytest

from portfolio.stress_test import SCENARIOS, StressTester, StressTestResult


class TestStressTesterRun:
    def test_returns_one_result_per_scenario(self, sample_sector_weights):
        tester = StressTester()
        results = tester.run(sample_sector_weights, initial_value=100_000)
        assert len(results) == len(SCENARIOS)

    def test_results_sorted_worst_first(self, sample_sector_weights):
        results = StressTester().run(sample_sector_weights)
        drawdowns = [r.portfolio_drawdown_pct for r in results]
        assert drawdowns == sorted(drawdowns)

    def test_portfolio_loss_consistent_with_drawdown(self, sample_sector_weights):
        results = StressTester().run(sample_sector_weights, initial_value=100_000)
        for r in results:
            expected_loss = 100_000 * (r.portfolio_drawdown_pct / 100)
            assert abs(r.portfolio_loss_usd - expected_loss) < 1.0

    def test_trough_value_never_negative(self, sample_sector_weights):
        results = StressTester().run(sample_sector_weights, initial_value=50_000)
        for r in results:
            assert r.portfolio_trough_value >= 0

    def test_relative_performance_is_portfolio_minus_spy(self, sample_sector_weights):
        results = StressTester().run(sample_sector_weights)
        for r in results:
            expected = round(r.portfolio_drawdown_pct - r.benchmark_drawdown_pct, 1)
            assert abs(r.relative_performance_pct - expected) < 0.01

    def test_better_than_spy_flag(self, sample_sector_weights):
        results = StressTester().run(sample_sector_weights)
        for r in results:
            assert r.better_than_spy == (r.relative_performance_pct > 0)

    def test_empty_weights_returns_empty(self):
        assert StressTester().run({}) == []

    def test_zero_total_weight_returns_empty(self):
        assert StressTester().run({"Technology": 0.0, "Financials": 0.0}) == []

    def test_sector_impact_keys_match_input(self, sample_sector_weights):
        results = StressTester().run(sample_sector_weights)
        for r in results:
            assert set(r.sector_impact.keys()) == set(sample_sector_weights.keys())

    def test_weights_normalised_before_calculation(self):
        """Weights don't need to sum to 100 — they are normalised internally."""
        weights_100 = {"Technology": 50.0, "ETF": 50.0}
        weights_200 = {"Technology": 100.0, "ETF": 100.0}
        r1 = StressTester().run(weights_100, initial_value=100_000)
        r2 = StressTester().run(weights_200, initial_value=100_000)
        for a, b in zip(r1, r2):
            assert abs(a.portfolio_drawdown_pct - b.portfolio_drawdown_pct) < 0.01

    def test_recovery_years_matches_scenario(self, sample_sector_weights):
        results = StressTester().run(sample_sector_weights)
        for r, scenario in zip(
            sorted(results, key=lambda x: x.scenario.name),
            sorted(SCENARIOS, key=lambda s: s.name),
        ):
            assert r.recovery_years_est == round(scenario.recovery_months_est / 12, 1)


class TestStressTesterMath:
    def test_single_sector_100pct_shock(self):
        """100% Tech allocation against 2008 GFC Tech shock = -52%."""
        results = StressTester().run({"Technology": 100.0}, initial_value=100_000)
        gfc = next(r for r in results if "2008" in r.scenario.name)
        # 2008 Tech shock = -52.0%
        assert abs(gfc.portfolio_drawdown_pct - (-52.0)) < 0.1

    def test_default_shock_applied_for_unknown_sector(self):
        """Unknown sector gets default_shock from each scenario."""
        results = StressTester().run({"AlienSector": 100.0}, initial_value=100_000)
        for r in results:
            assert r.portfolio_drawdown_pct == r.scenario.default_shock

    def test_2022_energy_positive_return(self):
        """Energy sector returned +59% in 2022 — portfolio should show positive return."""
        results = StressTester().run({"Energy": 100.0})
        scenario_2022 = next(r for r in results if "2022" in r.scenario.name)
        assert scenario_2022.portfolio_drawdown_pct > 0


class TestCustomScenario:
    def test_uniform_shock_equals_input(self):
        weights = {"Technology": 60.0, "ETF": 40.0}
        r = StressTester.custom_scenario(
            name="Test -20%",
            equity_shock_pct=-20.0,
            duration_months=6,
            recovery_months=12,
            sector_weights=weights,
            initial_value=100_000,
        )
        assert abs(r.portfolio_drawdown_pct - (-20.0)) < 0.1
        assert isinstance(r, StressTestResult)

    def test_loss_usd_for_custom_scenario(self):
        weights = {"Technology": 100.0}
        r = StressTester.custom_scenario(
            name="Crash",
            equity_shock_pct=-50.0,
            duration_months=12,
            recovery_months=24,
            sector_weights=weights,
            initial_value=200_000,
        )
        assert abs(r.portfolio_loss_usd - (-100_000)) < 1.0
        assert abs(r.portfolio_trough_value - 100_000) < 1.0
