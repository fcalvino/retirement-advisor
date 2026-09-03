"""
Stress Testing — historical crisis scenarios applied to the current portfolio.

Each scenario defines sector-level shocks calibrated from real crisis data.
Sector weights come from the Portfolio Optimizer result (or can be supplied directly).

Usage:
    tester = StressTester()
    results = tester.run(sector_weights={"Technology": 25.0, "Financials": 18.0, ...},
                         initial_value=100_000)
    for r in results:
        print(r.scenario.name, r.portfolio_drawdown_pct)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import STRESS_SCENARIOS, STRESS_TEST, StressScenario

# S27: the six scenarios now live in config.py. Kept as ``SCENARIOS`` here for
# the existing callers and tests (``from portfolio.stress_test import SCENARIOS``).
SCENARIOS: List[StressScenario] = STRESS_SCENARIOS

# ------------------------------------------------------------------ #
#  Result dataclass                                                    #
# ------------------------------------------------------------------ #

@dataclass
class StressTestResult:
    scenario: StressScenario

    # Portfolio impact
    portfolio_drawdown_pct: float          # weighted average drawdown
    portfolio_loss_usd: float              # dollar loss from initial_value
    portfolio_trough_value: float          # value at trough

    # Benchmark comparison
    benchmark_drawdown_pct: float          # SPY drawdown in same scenario
    relative_performance_pct: float       # portfolio DD − SPY DD (positive = outperformed)

    # Sector-level breakdown
    sector_impact: Dict[str, float] = field(default_factory=dict)  # {sector: drawdown %}

    # Recovery estimate
    recovery_years_est: float = 0.0
    recovery_value_at_year1: float = 0.0  # estimated value after 1yr of recovery

    # Flags
    better_than_spy: bool = False


# ------------------------------------------------------------------ #
#  StressTester                                                        #
# ------------------------------------------------------------------ #

class StressTester:
    """
    Apply historical and hypothetical crisis scenarios to a portfolio.

    sector_weights: {sector_name: weight_pct} (weights should sum to ~100).
                    Can come directly from OptimizationResult.sector_weights.
    initial_value:  starting portfolio value in USD.
    """

    def __init__(self, scenarios: Optional[List[StressScenario]] = None) -> None:
        self.scenarios = scenarios or SCENARIOS

    def run(
        self,
        sector_weights: Dict[str, float],
        initial_value: float = 100_000.0,
    ) -> List[StressTestResult]:
        """Run all scenarios and return results sorted by portfolio drawdown (worst first)."""
        if not sector_weights:
            return []

        # Normalise weights to fractions
        total_w = sum(sector_weights.values())
        if total_w <= 0:
            return []
        weights_frac = {k: v / total_w for k, v in sector_weights.items()}

        results = [
            self._apply_scenario(scenario, weights_frac, initial_value)
            for scenario in self.scenarios
        ]
        return sorted(results, key=lambda r: r.portfolio_drawdown_pct)

    def _apply_scenario(
        self,
        scenario: StressScenario,
        weights_frac: Dict[str, float],
        initial_value: float,
    ) -> StressTestResult:
        """Compute weighted portfolio drawdown for a single scenario."""
        sector_impact: Dict[str, float] = {}
        portfolio_dd = 0.0

        for sector, weight in weights_frac.items():
            shock = scenario.sector_shocks.get(sector, scenario.default_shock)
            sector_impact[sector] = round(shock, 1)
            portfolio_dd += weight * shock

        portfolio_dd = round(portfolio_dd, 1)
        portfolio_loss_usd = initial_value * (portfolio_dd / 100)
        trough_value = initial_value + portfolio_loss_usd  # loss is negative

        bench_dd = scenario.historical_spy_dd
        relative = round(portfolio_dd - bench_dd, 1)  # negative = worse than SPY

        # Rough recovery estimate: assume SPY-like recovery rate from trough
        recovery_years = round(scenario.recovery_months_est / 12, 1)

        # Estimate value after 1 year of recovery (rate from config.STRESS_TEST)
        recovery_1yr = trough_value * (1 + STRESS_TEST.recovery_annual_rate)

        return StressTestResult(
            scenario=scenario,
            portfolio_drawdown_pct=portfolio_dd,
            portfolio_loss_usd=round(portfolio_loss_usd, 0),
            portfolio_trough_value=round(max(trough_value, 0), 0),
            benchmark_drawdown_pct=bench_dd,
            relative_performance_pct=relative,
            sector_impact=sector_impact,
            recovery_years_est=recovery_years,
            recovery_value_at_year1=round(recovery_1yr, 0),
            better_than_spy=relative > 0,
        )

    @staticmethod
    def custom_scenario(
        name: str,
        equity_shock_pct: float,
        duration_months: int,
        recovery_months: int,
        sector_weights: Dict[str, float],
        initial_value: float = 100_000.0,
    ) -> StressTestResult:
        """
        Quick custom scenario: apply a uniform equity shock to all sectors.
        Useful for 'what if equities drop X%' analysis.
        """
        tester = StressTester()
        scenario = StressScenario(
            name=name,
            description=f"Escenario personalizado: caída uniforme de {equity_shock_pct:.0f}%.",
            sector_shocks={},
            default_shock=equity_shock_pct,
            duration_months=duration_months,
            recovery_months_est=recovery_months,
            historical_spy_dd=equity_shock_pct,
        )
        total_w = sum(sector_weights.values())
        weights_frac = {k: v / total_w for k, v in sector_weights.items()} if total_w > 0 else {}
        return tester._apply_scenario(scenario, weights_frac, initial_value)
