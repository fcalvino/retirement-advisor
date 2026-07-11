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
                "Horizonte largo: priorizá acciones de crecimiento y REITs como cobertura contra inflación. "
                "Los bonos restan al retorno real en esta etapa."
            )
        elif years_to_retirement > 5:
            advice.inflation_note = (
                "Mediano plazo: pasá gradualmente a acciones con dividendos y bonos de corta duración. "
                "Apuntá a 60/40 al retiro."
            )
        else:
            advice.inflation_note = (
                "Cerca del retiro: preservá capital. Enfocate en ingresos por dividendos y "
                "TIPS/I-bonds para protegerte de la erosión por inflación."
            )

        # ---- Sector concentration check ----
        if current_sector_weights:
            for sector, pct in current_sector_weights.items():
                if pct > CFG.max_sector_pct:
                    advice.concentration_warnings.append(
                        f"⚠️ {sector} representa el {pct:.1f}% del portafolio (límite: {CFG.max_sector_pct:.0f}%) — reducir"
                    )
                    advice.rebalancing_actions.append(
                        f"Reducir exposición a {sector} de {pct:.1f}% a menos de {CFG.max_sector_pct:.0f}%"
                    )

        # ---- Position concentration check ----
        if current_position_weights:
            for sym, pct in current_position_weights.items():
                if pct > CFG.max_position_pct:
                    advice.concentration_warnings.append(
                        f"⚠️ {sym} representa el {pct:.1f}% del portafolio (límite: {CFG.max_position_pct:.0f}%)"
                    )
                    advice.rebalancing_actions.append(
                        f"Reducir {sym} de {pct:.1f}% a menos de {CFG.max_position_pct:.0f}%"
                    )

            n_positions = len(current_position_weights)
            if n_positions < CFG.min_positions:
                advice.concentration_warnings.append(
                    f"El portafolio tiene solo {n_positions} posiciones — diversificar a al menos {CFG.min_positions}"
                )

        return advice
