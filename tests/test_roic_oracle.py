"""ROIC: one formula, the right country's tax, and never ROA wearing its name.

Backlog U3-8. ROIC feeds two things at once — the quality dimension in
``fundamental`` (7 points) and the moat's durability score — so an error here
enters the adjusted score twice. Three defects sat on it:

  * **two implementations.** ``fundamental._compute_roic`` and
    ``moat._compute_avg_roic`` each built NOPAT / invested capital from scratch,
    and each spelled the same tax rate differently: ``0.21`` in one, ``0.79`` in
    the other. Two copies of a formula drift; two spellings of one constant hide
    that they are the same constant.
  * **the tax rate was the United States', for everyone.** 25 of the 164 cached
    tickers are not US companies — 6 Argentine, 6 Brazilian, 3 Irish, 3 Chilean,
    2 Mexican, and more. An Argentine ADR taxed at 35 % had its NOPAT computed as
    if it kept 79 cents of every operating dollar. Ireland is the mirror case: at
    12.5 % the US rate *understates* what the company keeps.
  * **ROA reported under ROIC's name.** When the statements would not yield a
    ROIC, ``fundamental`` fell back to ``returnOnAssets`` and assigned it to
    ``result.roic`` — scored against the ROIC bands and printed as "ROIC" on
    every surface. Return on *assets* and return on *invested capital* have
    different denominators and are not interchangeable.

The references are written from the definitions, not the source. The tax rates
are statutory corporate rates, and they live in config precisely because they
change by law rather than by code.

No network, no Streamlit.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.utils import corporate_tax_rate_pct, roic_pct
from config import TAXES


def oracle_roic_pct(ebit: float, equity: float, ltd: float, tax_pct: float) -> float:
    """Reference: after-tax operating profit over the capital that funded it.

        NOPAT = EBIT × (1 − t)
        ROIC  = NOPAT / (equity + long-term debt)

    Spelled from the definition. The tax rate belongs to the jurisdiction that
    taxes the operating profit, which is why it is an argument and not a literal.
    """
    return ebit * (1 - tax_pct / 100.0) / (equity + ltd) * 100.0


# ================================================================== #
#  1. One formula                                                      #
# ================================================================== #

class TestOneImplementation:
    def test_matches_the_reference(self):
        assert roic_pct(ebit=1000.0, equity=4000.0, long_term_debt=1000.0,
                        tax_rate_pct=21.0) == pytest.approx(
            oracle_roic_pct(1000.0, 4000.0, 1000.0, 21.0), rel=1e-12)

    @pytest.mark.parametrize("tax_pct", [0.0, 12.5, 21.0, 35.0])
    def test_a_higher_tax_leaves_less_return(self, tax_pct):
        base = roic_pct(ebit=1000.0, equity=5000.0, long_term_debt=0.0, tax_rate_pct=0.0)
        taxed = roic_pct(ebit=1000.0, equity=5000.0, long_term_debt=0.0, tax_rate_pct=tax_pct)
        assert taxed == pytest.approx(base * (1 - tax_pct / 100.0), rel=1e-12)

    def test_capital_that_is_zero_or_negative_has_no_return_on_it(self):
        assert roic_pct(ebit=100.0, equity=0.0, long_term_debt=0.0, tax_rate_pct=21.0) is None
        assert roic_pct(ebit=100.0, equity=-500.0, long_term_debt=100.0, tax_rate_pct=21.0) is None

    def test_neither_module_still_spells_the_tax_rate_itself(self):
        """Two spellings of one constant is how the two copies stayed different."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for rel in ("analysis/fundamental.py", "analysis/moat.py"):
            src = (root / rel).read_text(encoding="utf-8")
            assert "0.79" not in src, f"{rel} sigue con el (1 − t) hardcodeado"
            assert "tax_rate = 0.21" not in src, f"{rel} sigue con la tasa de EE.UU."

    def test_both_callers_agree_on_the_same_single_year(self):
        """The window differs on purpose; the formula must not.

        ``fundamental`` reads the latest year to score what the company earns
        now; ``moat`` averages the available years to judge whether it lasts.
        Given one year of data, the two have to produce the same number.
        """
        from analysis.fundamental import FundamentalAnalyzer
        from analysis.moat import MoatAnalyzer

        cols = ["2025-12-31 00:00:00"]
        income = pd.DataFrame({"EBIT": [1000.0]}, index=cols).T
        balance = pd.DataFrame(
            {"Stockholders Equity": [4000.0], "Long Term Debt": [1000.0]}, index=cols
        ).T

        from_fundamental = FundamentalAnalyzer()._compute_roic(income, balance)
        from_moat = MoatAnalyzer()._compute_avg_roic(income, balance)
        assert from_fundamental == pytest.approx(from_moat, rel=1e-9)


# ================================================================== #
#  2. The right country's tax                                          #
# ================================================================== #

class TestTheTaxRateBelongsToTheCompany:
    def test_an_argentine_adr_is_not_taxed_like_a_us_company(self):
        ar = corporate_tax_rate_pct("Argentina")
        us = corporate_tax_rate_pct("United States")
        assert ar != us
        assert ar > us

    def test_ireland_is_the_mirror_case(self):
        """The US rate does not merely over-tax; it also under-taxes."""
        assert corporate_tax_rate_pct("Ireland") < corporate_tax_rate_pct("United States")

    @pytest.mark.parametrize("country", ["Argentina", "Brazil", "Chile", "Mexico", "Ireland"])
    def test_every_country_in_the_cached_universe_is_named(self, country):
        assert country in TAXES.corporate_tax_rate_pct

    def test_an_unknown_country_falls_back_loudly_not_to_the_us(self):
        """The default is a stated assumption, not "whatever the US charges"."""
        unknown = corporate_tax_rate_pct("Ruritania")
        assert unknown == pytest.approx(TAXES.default_corporate_tax_rate_pct)

    def test_the_rates_are_plausible_percentages(self):
        rates = list(TAXES.corporate_tax_rate_pct.values()) + [
            TAXES.default_corporate_tax_rate_pct
        ]
        assert all(0.0 <= r <= 60.0 for r in rates)

    def test_the_country_reaches_the_computation(self):
        """An Argentine issuer must actually get the Argentine rate end to end."""
        cols = ["2025-12-31 00:00:00"]
        income = pd.DataFrame({"EBIT": [1000.0]}, index=cols).T
        balance = pd.DataFrame(
            {"Stockholders Equity": [4000.0], "Long Term Debt": [1000.0]}, index=cols
        ).T

        from analysis.fundamental import FundamentalAnalyzer

        a = FundamentalAnalyzer()
        ar = a._compute_roic(income, balance, country="Argentina")
        us = a._compute_roic(income, balance, country="United States")
        assert ar < us
        assert ar == pytest.approx(
            oracle_roic_pct(1000.0, 4000.0, 1000.0, corporate_tax_rate_pct("Argentina")),
            rel=1e-9,
        )


# ================================================================== #
#  3. ROA is not ROIC                                                  #
# ================================================================== #

class TestRoaIsNeverCalledRoic:
    def test_the_fallback_is_gone_from_the_source(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "analysis" / "fundamental.py").read_text(
            encoding="utf-8"
        )
        assert 'roic = roa_reported * 100' not in src

    def test_a_company_without_the_statements_reports_no_roic(self):
        """Not a smaller number under the same name — no number."""
        from unittest.mock import patch

        from analysis.fundamental import FundamentalAnalyzer

        info = {
            "longName": "Test Co", "sector": "Technology", "industry": "Software",
            "country": "United States", "returnOnAssets": 0.11,
            "currentPrice": 100.0, "regularMarketPrice": 100.0, "marketCap": 1e10,
        }
        empty = {"income_stmt": pd.DataFrame(), "balance_sheet": pd.DataFrame(),
                 "cashflow": pd.DataFrame()}
        with (
            patch("analysis.fundamental.get_info", return_value=info),
            patch("analysis.fundamental.get_financials", return_value=empty),
            patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
            patch("data.fetcher.get_info_age_hours", return_value=1.0),
        ):
            result = FundamentalAnalyzer().analyze("TEST")

        assert result.roic is None
        assert "ROIC" in (result.notes.get("profitability_missing") or "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
