"""The ARS risk discount, keyed off the company (backlog U5-16).

``optimizer.py`` carried ``_ARS_TICKERS = {"YPF", "PAM", "CEPU", "LOMA", "TEO",
"EDN"}`` as a literal, and every conservative/moderate optimisation multiplied
those six scores by a fixed discount.

**Measured, that list is exactly right for today's shipped universes** — the six
are precisely the tickers the feed marks ``country == "Argentina"`` across all
167. So this row is not a live mis-scoring, and the docs say so rather than
implying one.

It is live in one place and fragile in another:

  * **custom tickers.** ``UserPreferences.custom_tickers`` merges into the
    effective universe, so a user who adds GGAL, BMA, SUPV, BBAR, TGS, CRESY or
    IRS — none of which ship in any universe — gets no discount at all. The
    macro risk the discount exists for does not care whether the symbol was
    typed by hand.
  * **a list that must be maintained by hand against a field that already
    exists.** ``info["country"]`` is what the feed reports, and U3-8 already
    keyed the corporate tax rate off it. Two mechanisms for "which country is
    this company exposed to" is one too many.

What this row fixed is who is exposed: keyed off the company's country, not a
list. (The score discount itself, and its exemption for the aggressive profile,
are gone: EO-1a made it universal and EO-4d moved the country risk into the
Estimación, ``test_eo4d_riesgo_pais_estimacion_oracle``.)

No network.
"""

from __future__ import annotations

import pytest

from config import ARS_RISK
from portfolio.optimizer import is_ars_exposed


def _row(symbol: str, *, country: str = "United States", score: float = 80.0) -> dict:
    return {
        "symbol": symbol, "adjusted_score": score, "country": country,
        "dividend_yield": 1.0, "moat_score": 8.0, "sector": "Energy",
    }


class TestExposureComesFromTheCompany:
    def test_an_argentine_issuer_is_exposed(self):
        assert is_ars_exposed(_row("YPF", country="Argentina")) is True

    def test_a_us_issuer_is_not(self):
        assert is_ars_exposed(_row("KO")) is False

    @pytest.mark.parametrize("symbol", ["GGAL", "BMA", "SUPV", "BBAR", "TGS", "CRESY", "IRS"])
    def test_a_custom_argentine_adr_is_reached(self, symbol):
        """The live half: none of these ship in any universe, all can be added."""
        assert is_ars_exposed(_row(symbol, country="Argentina")) is True

    def test_the_six_shipped_tickers_still_qualify(self):
        """Anti-cheat: replacing the list must not drop what it covered."""
        for symbol in ("YPF", "PAM", "CEPU", "LOMA", "TEO", "EDN"):
            assert is_ars_exposed(_row(symbol, country="Argentina")) is True

    def test_a_row_without_a_country_is_not_assumed_exposed(self):
        """Unknown is not Argentina — the U3-1 rule, applied here."""
        row = _row("XYZ")
        row.pop("country")
        assert is_ars_exposed(row) is False

    def test_the_country_list_is_config_driven(self):
        assert "Argentina" in ARS_RISK.exposed_countries


class TestNoSecondMechanism:
    def test_the_hardcoded_set_is_gone(self):
        import portfolio.optimizer as opt

        assert not hasattr(opt, "_ARS_TICKERS")

    def test_the_country_reaches_the_optimizer_row(self):
        """A field that never arrives cannot be keyed off."""
        from pathlib import Path

        page = (Path(__file__).resolve().parents[1] / "dashboard" / "views" /
                "5_Optimizer.py").read_text(encoding="utf-8")
        assert '"country"' in page

        from analysis.fundamental import FundamentalResult

        assert hasattr(FundamentalResult(symbol="X"), "country")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
