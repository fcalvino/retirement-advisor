"""REITs are scored on funds from operations (oracle-first, CONTEXT §5).

The defect: a REIT was measured with the same earnings multiple and the same payout
ratio as an operating company. Depreciation is the largest charge on a REIT's income
statement and is not a cash outflow, so accounting profit understates the business and
inflates everything built on it; and a REIT distributes over 90% of taxable income by
law, out of FFO, so its payout against earnings routinely exceeds 100%.

Measured on the cached universe (2026-08-22) — note this is the only sector with
**100% input availability and the worst score in the product**: Real Estate averaged
60.0, zero BUY in 13 names, 3.5 of 10 on dividends. Nothing was missing; the wrong
ratio was applied.

    12 of 13 tripped the "unsustainable payout" warning
    O:   P/E 45.7 → P/FFO 16.5   ·   payout 236 % → 70 %
    EQR: P/E 28.5 → P/FFO 11.8   ·   payout 121 % → 63 %
    MAA: P/E 38.8 → P/FFO 14.7   ·   payout 178 % → 74 %

Per CONTEXT §5 the oracles below come from the definitions — FFO summed term by term,
the multiple as capitalisation over FFO, the payout as cash distributed over FFO —
never from the production helpers.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from unittest.mock import patch

import pandas as pd
import pytest

from analysis.company_type import OPERATING, REIT, classify_company, is_reit
from analysis.fundamental import (
    FundamentalAnalyzer,
    compute_ffo,
    compute_ffo_payout_pct,
)
from config import THRESHOLDS as T

# --------------------------------------------------------------------------- #
#  Oracles                                                                    #
# --------------------------------------------------------------------------- #

def oracle_ffo(net_income: float, depreciation: float) -> float:
    """Funds from operations, summed from its definition."""
    return net_income + depreciation


def oracle_p_ffo(market_cap: float, ffo: float) -> float:
    return market_cap / ffo


def oracle_payout_pct(dividends_paid: float, ffo: float) -> float:
    """Cash distributed over funds from operations. The cash-flow row is negative."""
    return abs(dividends_paid) / ffo * 100


# --------------------------------------------------------------------------- #
#  Fixtures                                                                   #
# --------------------------------------------------------------------------- #

def _statements(
    net_income: float,
    depreciation: Optional[float],
    dividends_paid: float,
    *,
    years: int = 4,
) -> Dict[str, pd.DataFrame]:
    columns = [f"{2025 - i}-12-31 00:00:00" for i in range(years)]
    income: Dict[str, List[float]] = {
        "Net Income": [net_income * (1 - 0.04 * i) for i in range(years)],
        "Total Revenue": [net_income * 4 * (1 - 0.03 * i) for i in range(years)],
    }
    cash: Dict[str, List[float]] = {
        "Cash Dividends Paid": [dividends_paid * (1 - 0.02 * i) for i in range(years)],
        "Free Cash Flow": [net_income * 1.2 for _ in range(years)],
    }
    if depreciation is not None:
        cash["Depreciation And Amortization"] = [
            depreciation * (1 - 0.02 * i) for i in range(years)
        ]
    return {
        "income_stmt": pd.DataFrame(income, index=columns).T,
        "balance_sheet": pd.DataFrame(
            {
                "Stockholders Equity": [net_income * 10 for _ in range(years)],
                "Total Assets": [net_income * 30 for _ in range(years)],
                "Current Assets": [net_income * 5 for _ in range(years)],
                "Current Liabilities": [net_income * 3 for _ in range(years)],
            },
            index=columns,
        ).T,
        "cashflow": pd.DataFrame(cash, index=columns).T,
    }


def _analyze(sector: str, market_cap: float, statements, **info_extra):
    info = {
        "longName": "Test Co",
        "sector": sector,
        "industry": "REIT - Retail" if sector == "Real Estate" else "Specialty Retail",
        "country": "United States",
        "currentPrice": 100.0,
        "regularMarketPrice": 100.0,
        "marketCap": market_cap,
    }
    info.update(info_extra)
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials", return_value=statements),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze("TEST")


# --------------------------------------------------------------------------- #
#  Classification                                                             #
# --------------------------------------------------------------------------- #

class TestCompanyType:
    def test_real_estate_sector_is_a_reit(self):
        assert classify_company("O", sector="Real Estate") == REIT

    def test_real_estate_services_is_operating(self):
        assert classify_company(
            "CBRE", sector="Real Estate", industry="Real Estate Services"
        ) == OPERATING
        assert classify_company(
            "JLL", sector="Real Estate", industry="Real Estate Services"
        ) == OPERATING

    def test_reit_industry_alone_is_enough(self):
        assert classify_company("X", sector="", industry="REIT - Industrial") == REIT

    def test_reit_industry_wins_over_any_sector(self):
        assert classify_company(
            "O", sector="Real Estate", industry="REIT - Retail"
        ) == REIT

    def test_everything_else_is_operating(self):
        assert classify_company("MSFT", sector="Technology", industry="Software") == OPERATING
        assert classify_company("JPM", sector="Financial Services") == OPERATING

    def test_case_and_whitespace_do_not_matter(self):
        assert classify_company("O", sector="  real estate  ") == REIT

    def test_missing_everything_is_operating(self):
        assert classify_company("") == OPERATING

    def test_is_reit_reads_a_result_shape(self):
        from types import SimpleNamespace

        assert is_reit(SimpleNamespace(symbol="O", sector="Real Estate", industry=""))
        assert not is_reit(SimpleNamespace(symbol="KO", sector="Consumer Defensive", industry=""))


# --------------------------------------------------------------------------- #
#  The metrics, against the oracles                                           #
# --------------------------------------------------------------------------- #

class TestFfoMetrics:
    def test_ffo_matches_the_oracle(self):
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        assert compute_ffo(st["income_stmt"], st["cashflow"]) == pytest.approx(
            oracle_ffo(1.06e9, 2.52e9)
        )

    def test_payout_matches_the_oracle(self):
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        ffo = oracle_ffo(1.06e9, 2.52e9)
        assert compute_ffo_payout_pct(st["cashflow"], ffo) == pytest.approx(
            oracle_payout_pct(-2.5e9, ffo)
        )

    def test_p_ffo_matches_the_oracle_end_to_end(self):
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        mc = 59e9
        result = _analyze("Real Estate", mc, st)
        assert result.p_ffo == pytest.approx(oracle_p_ffo(mc, oracle_ffo(1.06e9, 2.52e9)), rel=1e-3)

    def test_no_depreciation_means_no_ffo(self):
        """SPG shape: falls back to the accounting route and says so."""
        st = _statements(net_income=1.0e9, depreciation=None, dividends_paid=-0.5e9)
        assert compute_ffo(st["income_stmt"], st["cashflow"]) is None

        result = _analyze("Real Estate", 20e9, st, trailingPE=22.0)
        assert result.p_ffo is None
        assert "ffo" in result.notes

    def test_negative_ffo_is_not_a_multiple(self):
        st = _statements(net_income=-5.0e9, depreciation=1.0e9, dividends_paid=-0.2e9)
        assert compute_ffo(st["income_stmt"], st["cashflow"]) is None


# --------------------------------------------------------------------------- #
#  Regression: the real cases from the audit                                  #
# --------------------------------------------------------------------------- #

class TestAuditRegressions:
    def test_realty_income_shape_stops_tripping_the_payout_warning(self):
        """O: P/E 45.7 and a 236 % accounting payout, both artifacts of depreciation."""
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        result = _analyze("Real Estate", 59e9, st, trailingPE=45.7, payoutRatio=2.36)

        assert result.p_ffo == pytest.approx(16.5, abs=0.6)
        assert result.ffo_payout_pct == pytest.approx(70.0, abs=3.0)
        assert not any("ayout" in w for w in result.warnings)

    def test_the_earnings_multiple_no_longer_drives_the_band(self):
        """Same REIT, absurd P/E: the valuation band comes from P/FFO."""
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        cheap = _analyze("Real Estate", 40e9, st, trailingPE=244.7)
        assert cheap.p_ffo < T.p_ffo_good
        assert cheap.valuation_score > 0

    def test_a_genuinely_expensive_reit_still_reads_as_expensive(self):
        """WELL shape: P/FFO 53.5 must not be laundered into a good band."""
        st = _statements(net_income=0.94e9, depreciation=2.14e9, dividends_paid=-1.2e9)
        result = _analyze("Real Estate", 165e9, st)
        assert result.p_ffo > T.p_ffo_acceptable
        assert any("P/FFO" in w for w in result.warnings)


# --------------------------------------------------------------------------- #
#  The branch must not leak                                                   #
# --------------------------------------------------------------------------- #

class TestOperatingCompaniesAreUntouched:
    def test_identical_numbers_score_the_old_way(self):
        st = _statements(net_income=1.06e9, depreciation=2.52e9, dividends_paid=-2.5e9)
        info = dict(trailingPE=22.0, payoutRatio=0.55)

        operating = _analyze("Consumer Defensive", 59e9, st, **info)
        assert operating.p_ffo is None
        assert operating.ffo is None
        assert operating.ffo_payout_pct is None
        assert operating.pe_ratio == pytest.approx(22.0)

    def test_an_operating_company_with_a_high_payout_still_warns(self):
        """The warning is not gone — it is only redirected for REITs."""
        st = _statements(net_income=1.0e9, depreciation=0.2e9, dividends_paid=-0.9e9)
        result = _analyze("Consumer Defensive", 20e9, st,
                          trailingPE=20.0, payoutRatio=0.95, dividendYield=4.0)
        assert any("ayout" in w for w in result.warnings)


# --------------------------------------------------------------------------- #
#  Bands come from config                                                     #
# --------------------------------------------------------------------------- #

class TestBands:
    def test_config_fields_exist_and_are_ordered(self):
        assert T.p_ffo_excellent < T.p_ffo_good < T.p_ffo_acceptable

    @pytest.mark.parametrize("rung,expected_points", [
        ("p_ffo_excellent", 8.0),
        ("p_ffo_good", 5.0),
        ("p_ffo_acceptable", 2.0),
    ])
    def test_each_band_pays_what_it_should(self, rung, expected_points):
        target = getattr(T, rung)
        ffo = oracle_ffo(1.0e9, 2.0e9)
        st = _statements(net_income=1.0e9, depreciation=2.0e9, dividends_paid=-1.0e9)
        # Market cap chosen so P/FFO lands just inside the requested band.
        result = _analyze("Real Estate", ffo * (target - 0.1), st)
        assert result.valuation_score == expected_points

    def test_moving_the_band_moves_the_score(self):
        ffo = oracle_ffo(1.0e9, 2.0e9)
        st = _statements(net_income=1.0e9, depreciation=2.0e9, dividends_paid=-1.0e9)
        mc = ffo * 15.0
        before = _analyze("Real Estate", mc, st).valuation_score
        with patch.object(T, "p_ffo_excellent", 16.0):
            after = _analyze("Real Estate", mc, st).valuation_score
        assert after > before
