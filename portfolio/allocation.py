"""
Asset allocation advisor for retirement portfolios.

Provides:
  - Age-based stock/bond allocation
  - Sector diversification analysis
  - Risk concentration warnings
  - Rebalancing recommendations
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from config import (
    CASH_BUFFER_PCT,
    ProfileConfig,
    profile_from_name,
    recommended_bond_pct,
)


@dataclass
class AllocationAdvice:
    age: int
    retirement_years: int          # years until retirement
    profile_name: str = ""         # profile that produced these numbers (U5-7)

    # Recommended allocation
    equity_pct: float = 0.0
    bonds_pct: float = 0.0
    cash_pct: float = CASH_BUFFER_PCT

    @property
    def defensive_pct(self) -> float:
        """Bonds plus the cash buffer — the sleeve the age rule governs (N9).

        Exposed so the two screens that show this number read it from one place
        instead of each summing the parts. See ``config.recommended_bond_pct``
        for the contract this satisfies.
        """
        return self.bonds_pct + self.cash_pct

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
        profile: Optional[Union[ProfileConfig, str]] = None,
    ) -> AllocationAdvice:
        """Age- and profile-appropriate allocation, plus concentration checks.

        ``profile`` takes a ``ProfileConfig`` or the stored profile name; None
        means conservative, which is what every caller got before U5-7. Both the
        glide path and the concentration limits read it: before U5-7 the first
        ignored the profile entirely and the second graded against the global
        ``STRATEGY`` caps, so the screen warned an aggressive investor about a
        position the optimizer had just built them under their own 18 % cap.
        """
        prof = profile if isinstance(profile, ProfileConfig) else profile_from_name(profile)
        years_to_retirement = max(retirement_age - age, 0)
        advice = AllocationAdvice(
            age=age, retirement_years=years_to_retirement, profile_name=prof.name
        )

        # ---- Target allocation ----
        # ``recommended_bond_pct`` gives the **defensive** sleeve for this age
        # and profile. ``CASH_BUFFER_PCT`` of it is held liquid for rebalancing
        # and the rest goes to bonds, so the rule is split across two lines on
        # the screen and neither line is the rule on its own (N9):
        #
        #     bonds_pct + cash_pct == max(defensive_pct, CASH_BUFFER_PCT)
        #
        # The ``max(..., 0.0)`` is what makes the buffer a floor rather than a
        # share: below CASH_BUFFER_PCT the whole sleeve is cash and the investor
        # still holds the buffer. Exact for every profile and age — pinned by
        # ``tests/test_defensive_sleeve_contract.py``.
        defensive_pct = recommended_bond_pct(age, prof)
        advice.cash_pct = CASH_BUFFER_PCT
        advice.bonds_pct = max(defensive_pct - CASH_BUFFER_PCT, 0.0)
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
                if pct > prof.max_sector_pct:
                    advice.concentration_warnings.append(
                        f"⚠️ {sector} representa el {pct:.1f}% del portafolio (límite: {prof.max_sector_pct:.0f}%) — reducir"
                    )
                    advice.rebalancing_actions.append(
                        f"Reducir exposición a {sector} de {pct:.1f}% a menos de {prof.max_sector_pct:.0f}%"
                    )

        # ---- Position concentration check ----
        if current_position_weights:
            for sym, pct in current_position_weights.items():
                if pct > prof.max_position_pct:
                    advice.concentration_warnings.append(
                        f"⚠️ {sym} representa el {pct:.1f}% del portafolio (límite: {prof.max_position_pct:.0f}%)"
                    )
                    advice.rebalancing_actions.append(
                        f"Reducir {sym} de {pct:.1f}% a menos de {prof.max_position_pct:.0f}%"
                    )

            n_positions = len(current_position_weights)
            if n_positions < prof.min_positions:
                advice.concentration_warnings.append(
                    f"El portafolio tiene solo {n_positions} posiciones — diversificar a al menos {prof.min_positions}"
                )

        return advice
