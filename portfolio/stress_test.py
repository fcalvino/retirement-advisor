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


# ------------------------------------------------------------------ #
#  Scenario definitions                                                #
# ------------------------------------------------------------------ #

@dataclass
class StressScenario:
    name: str
    description: str
    # Sector peak-to-trough returns during the crisis period (%)
    sector_shocks: Dict[str, float]
    # Catch-all for sectors not listed above
    default_shock: float
    duration_months: int
    recovery_months_est: int   # typical months to recover to previous peak
    historical_spy_dd: float   # SPY peak-to-trough during same period (%)


# Six scenarios, calibrated from Bloomberg / FRED historical data
SCENARIOS: List[StressScenario] = [
    StressScenario(
        name="2008 — Crisis Financiera Global",
        description=(
            "Colapso del sistema bancario global. Caída del 56% en el S&P 500 "
            "desde el pico (oct-2007 a mar-2009). Correlaciones colapsan a 1."
        ),
        sector_shocks={
            "Financials":           -80.0,
            "Consumer Cyclical":    -60.0,
            "Real Estate":          -67.0,
            "Industrials":          -55.0,
            "Energy":               -55.0,
            "Technology":           -52.0,
            "Communication Services": -48.0,
            "Materials":            -53.0,
            "Healthcare":           -36.0,
            "Consumer Defensive":   -32.0,
            "Utilities":            -29.0,
            "ETF":                  -56.0,
        },
        default_shock=-50.0,
        duration_months=17,
        recovery_months_est=48,
        historical_spy_dd=-56.8,
    ),
    StressScenario(
        name="2020 — COVID-19",
        description=(
            "Caída más rápida de la historia: -34% en 33 días. "
            "Recuperación igualmente veloz (agosto 2020)."
        ),
        sector_shocks={
            "Energy":               -60.0,
            "Consumer Cyclical":    -42.0,
            "Industrials":          -40.0,
            "Financials":           -38.0,
            "Real Estate":          -37.0,
            "Materials":            -35.0,
            "Communication Services": -25.0,
            "Healthcare":           -22.0,
            "Utilities":            -20.0,
            "Consumer Defensive":   -16.0,
            "Technology":           -24.0,
            "ETF":                  -34.0,
        },
        default_shock=-30.0,
        duration_months=1,
        recovery_months_est=6,
        historical_spy_dd=-33.9,
    ),
    StressScenario(
        name="2022 — Inflación + Suba de Tasas",
        description=(
            "La Fed subió tasas 525bps en 15 meses. Bonos y acciones cayeron "
            "simultáneamente — el peor año para un portafolio 60/40 en 50 años."
        ),
        sector_shocks={
            "Technology":           -38.0,
            "Communication Services": -40.0,
            "Consumer Cyclical":    -37.0,
            "Real Estate":          -29.0,
            "Financials":           -15.0,
            "Healthcare":           -5.0,
            "Industrials":          -12.0,
            "Materials":            -14.0,
            "Consumer Defensive":   -3.0,
            "Utilities":            -1.0,
            "Energy":               +59.0,    # energy outperformed
            "ETF":                  -19.0,
        },
        default_shock=-18.0,
        duration_months=12,
        recovery_months_est=24,
        historical_spy_dd=-19.4,
    ),
    StressScenario(
        name="2000-2002 — Burbuja Dot-com",
        description=(
            "Colapso de la burbuja tecnológica. -78% en el NASDAQ, "
            "-49% en el S&P 500. Recuperación tardó 7 años."
        ),
        sector_shocks={
            "Technology":           -78.0,
            "Communication Services": -65.0,
            "Consumer Cyclical":    -45.0,
            "Industrials":          -40.0,
            "Financials":           -35.0,
            "Materials":            -30.0,
            "Real Estate":          -10.0,
            "Healthcare":           -25.0,
            "Consumer Defensive":   -15.0,
            "Utilities":            -28.0,
            "Energy":               -15.0,
            "ETF":                  -49.0,
        },
        default_shock=-40.0,
        duration_months=30,
        recovery_months_est=84,
        historical_spy_dd=-49.1,
    ),
    StressScenario(
        name="Recesión Severa (escenario hipotético)",
        description=(
            "Recesión profunda sin crisis bancaria sistémica. "
            "Similar a 1973-74 o 1980-82. Caída moderada y recuperación gradual."
        ),
        sector_shocks={
            "Consumer Cyclical":    -45.0,
            "Industrials":          -40.0,
            "Materials":            -38.0,
            "Financials":           -35.0,
            "Real Estate":          -30.0,
            "Technology":           -30.0,
            "Communication Services": -28.0,
            "Energy":               -20.0,
            "Healthcare":           -15.0,
            "Utilities":            -12.0,
            "Consumer Defensive":   -10.0,
            "ETF":                  -30.0,
        },
        default_shock=-28.0,
        duration_months=18,
        recovery_months_est=36,
        historical_spy_dd=-30.0,
    ),
    StressScenario(
        name="Stagflación Extrema (escenario hipotético)",
        description=(
            "Alta inflación sostenida + estancamiento económico. "
            "Peor entorno para activos financieros: bonos y acciones caen juntos."
        ),
        sector_shocks={
            "Technology":           -45.0,
            "Consumer Cyclical":    -40.0,
            "Communication Services": -38.0,
            "Financials":           -30.0,
            "Real Estate":          -25.0,
            "Industrials":          -22.0,
            "Materials":            -10.0,
            "Healthcare":           -18.0,
            "Consumer Defensive":   -5.0,
            "Utilities":            +5.0,
            "Energy":               +40.0,
            "ETF":                  -25.0,
        },
        default_shock=-22.0,
        duration_months=24,
        recovery_months_est=48,
        historical_spy_dd=-25.0,
    ),
]


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

        # Rough recovery estimate: assume SPY-like recovery rate (~15% p.a. from trough)
        recovery_years = round(scenario.recovery_months_est / 12, 1)

        # Estimate value after 1 year of recovery (8% annual from trough)
        recovery_1yr = trough_value * 1.08

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
