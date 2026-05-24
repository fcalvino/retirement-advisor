"""
Asset allocation advisor for retirement portfolios.

Provides:
  - Age-based stock/bond allocation
  - Sector diversification analysis
  - Risk concentration warnings
  - Rebalancing recommendations
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import STRATEGY as CFG
from config import recommended_bond_pct


@dataclass
class AllocationAdvice:
    age: int
    retirement_years: int          # years until retirement

    # Recommended allocation
    equity_pct: float = 0.0
    bonds_pct: float = 0.0
    cash_pct: float = 5.0

    # Equity breakdown
    us_large_cap_pct: float = 0.0
    international_pct: float = 0.0
    real_estate_pct: float = 0.0

    # Warnings and actions
    concentration_warnings: List[str] = field(default_factory=list)
    rebalancing_actions: List[str] = field(default_factory=list)
    inflation_note: str = ""


class AllocationAdvisor:
    """
    Generates age-appropriate asset allocation recommendations
    and checks portfolio diversification rules.
    """

    def advise(
        self,
        age: int,
        retirement_age: int = 65,
        current_sector_weights: Optional[Dict[str, float]] = None,
        current_position_weights: Optional[Dict[str, float]] = None,
    ) -> AllocationAdvice:
        years_to_retirement = max(retirement_age - age, 0)
        advice = AllocationAdvice(age=age, retirement_years=years_to_retirement)

        # ---- Target allocation ----
        bond_pct = recommended_bond_pct(age)
        # Reserve 5% cash for opportunities (rebalancing buffer)
        advice.bonds_pct = max(bond_pct - 5, 0)
        advice.cash_pct = 5.0
        advice.equity_pct = 100.0 - advice.bonds_pct - advice.cash_pct

        # Equity sub-allocation
        if age < 45:
            advice.us_large_cap_pct = advice.equity_pct * 0.70
            advice.international_pct = advice.equity_pct * 0.25
            advice.real_estate_pct = advice.equity_pct * 0.05
        elif age < 60:
            advice.us_large_cap_pct = advice.equity_pct * 0.65
            advice.international_pct = advice.equity_pct * 0.20
            advice.real_estate_pct = advice.equity_pct * 0.15
        else:
            advice.us_large_cap_pct = advice.equity_pct * 0.60
            advice.international_pct = advice.equity_pct * 0.15
            advice.real_estate_pct = advice.equity_pct * 0.25

        # ---- Inflation note ----
        if years_to_retirement > 15:
            advice.inflation_note = (
                "Long horizon: prioritize growth stocks and REITs as inflation hedge. "
                "Bonds are a drag on real returns at this stage."
            )
        elif years_to_retirement > 5:
            advice.inflation_note = (
                "Mid-term: gradually shift to dividend stocks and short-duration bonds. "
                "Aim for 60/40 by retirement."
            )
        else:
            advice.inflation_note = (
                "Near retirement: preserve capital. Focus on dividend income and "
                "TIPS/I-bonds to protect against inflation erosion."
            )

        # ---- Sector concentration check ----
        if current_sector_weights:
            for sector, pct in current_sector_weights.items():
                if pct > CFG.max_sector_pct:
                    advice.concentration_warnings.append(
                        f"⚠️ {sector} is {pct:.1f}% of portfolio (limit: {CFG.max_sector_pct:.0f}%) — reduce"
                    )
                    advice.rebalancing_actions.append(
                        f"Trim {sector} exposure from {pct:.1f}% to below {CFG.max_sector_pct:.0f}%"
                    )

        # ---- Position concentration check ----
        if current_position_weights:
            for sym, pct in current_position_weights.items():
                if pct > CFG.max_position_pct:
                    advice.concentration_warnings.append(
                        f"⚠️ {sym} is {pct:.1f}% of portfolio (limit: {CFG.max_position_pct:.0f}%)"
                    )
                    advice.rebalancing_actions.append(
                        f"Trim {sym} from {pct:.1f}% to below {CFG.max_position_pct:.0f}%"
                    )

            n_positions = len(current_position_weights)
            if n_positions < CFG.min_positions:
                advice.concentration_warnings.append(
                    f"Portfolio has only {n_positions} positions — diversify to at least {CFG.min_positions}"
                )

        return advice

    def format_summary(self, advice: AllocationAdvice) -> str:
        lines = [
            f"Age {advice.age} | {advice.retirement_years} years to retirement",
            "",
            "📊 Target Allocation:",
            f"  Equities:  {advice.equity_pct:.0f}%  "
            f"(US Large Cap {advice.us_large_cap_pct:.0f}% | Intl {advice.international_pct:.0f}% | REIT {advice.real_estate_pct:.0f}%)",
            f"  Bonds:     {advice.bonds_pct:.0f}%",
            f"  Cash:      {advice.cash_pct:.0f}%",
            "",
            f"💡 {advice.inflation_note}",
        ]
        if advice.concentration_warnings:
            lines += ["", "⚠️ Concentration Risks:"] + [f"  {w}" for w in advice.concentration_warnings]
        if advice.rebalancing_actions:
            lines += ["", "🔄 Rebalancing Actions:"] + [f"  {a}" for a in advice.rebalancing_actions]
        return "\n".join(lines)
