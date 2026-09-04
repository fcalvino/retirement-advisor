"""Integration coverage for ``FundamentalAnalyzer.analyze()`` (backlog T2).

The specialized suites (``test_reit_ffo``, ``test_eps_growth_and_graham``,
``test_data_quality``, …) each pin one behaviour. None exercises the *whole*
pipeline end to end, so a regression in the orchestration — the crypto fast-path
bypass, asset-class propagation, the ``adjusted_score`` assembly, or the
no-statements fallback — would pass unnoticed. These tests hold that flow.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, FundamentalResult

# --------------------------------------------------------------------------- #
#  Fixture: a full set of financial statements                                #
# --------------------------------------------------------------------------- #

def _statements(*, net_income=2.0e9, depreciation=0.4e9, years=4):
    cols = [f"{2025 - i}-12-31" for i in range(years)]
    income = {
        "Net Income": [net_income * (1 - 0.05 * i) for i in range(years)],
        "Total Revenue": [net_income * 5 * (1 - 0.04 * i) for i in range(years)],
        "Gross Profit": [net_income * 3 * (1 - 0.04 * i) for i in range(years)],
        "EBIT": [net_income * 1.4 for _ in range(years)],
        "Diluted EPS": [3.0 * (1 - 0.05 * i) for i in range(years)],
        "Operating Income": [net_income * 1.3 for _ in range(years)],
    }
    balance = {
        "Stockholders Equity": [net_income * 6 for _ in range(years)],
        "Total Assets": [net_income * 18 for _ in range(years)],
        "Current Assets": [net_income * 5 for _ in range(years)],
        "Current Liabilities": [net_income * 2 for _ in range(years)],
        "Total Debt": [net_income * 3 for _ in range(years)],
        "Long Term Debt": [net_income * 2 for _ in range(years)],
    }
    cash = {
        "Free Cash Flow": [net_income * 1.1 for _ in range(years)],
        "Operating Cash Flow": [net_income * 1.5 for _ in range(years)],
        "Depreciation And Amortization": [depreciation for _ in range(years)],
        "Cash Dividends Paid": [-net_income * 0.3 for _ in range(years)],
    }
    return {
        "income_stmt": pd.DataFrame(income, index=cols).T,
        "balance_sheet": pd.DataFrame(balance, index=cols).T,
        "cashflow": pd.DataFrame(cash, index=cols).T,
    }


def _analyze(sector, *, industry="", market_cap=80e9, statements=None, **info_extra):
    info = {
        "longName": "Test Co",
        "sector": sector,
        "industry": industry or ("REIT - Retail" if sector == "Real Estate" else "Software"),
        "country": "United States",
        "currentPrice": 100.0,
        "regularMarketPrice": 100.0,
        "marketCap": market_cap,
        "trailingPE": 20.0,
        "dividendYield": 2.0,
    }
    info.update(info_extra)
    with (
        patch("analysis.fundamental.get_info", return_value=info),
        patch("analysis.fundamental.get_financials",
              return_value=statements if statements is not None else _statements()),
        patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
        patch("data.fetcher.get_info_age_hours", return_value=1.0),
    ):
        return FundamentalAnalyzer().analyze("TEST")


# --------------------------------------------------------------------------- #
#  One integration test per asset class                                        #
# --------------------------------------------------------------------------- #

class TestByAssetClass:
    def test_equity_standard(self):
        r = _analyze("Technology")
        assert isinstance(r, FundamentalResult)
        assert r.asset_class == "equity"
        assert not r.is_crypto
        assert 0.0 <= r.total_score <= 100.0
        # The five dimensions sum into total_score.
        dims = (r.profitability_score + r.health_score + r.valuation_score
                + r.growth_score + r.dividend_score)
        assert r.total_score == pytest.approx(min(dims, 100.0), abs=0.5)
        assert r.pe_ratio == pytest.approx(20.0)

    def test_reit_uses_the_ffo_route(self):
        r = _analyze("Real Estate", market_cap=59e9,
                     statements=_statements(net_income=1.06e9, depreciation=2.52e9))
        assert r.asset_class == "equity"
        assert r.ffo is not None and r.p_ffo is not None
        assert r.payout_basis == "ffo"

    def test_crypto_fast_path_returns_valid_result_without_equity_scorers(self):
        sentinel = FundamentalResult(symbol="BTC-USD", is_crypto=True, asset_class="crypto")
        sentinel.total_score = 61.0

        with (
            patch("analysis.fundamental.get_info") as m_info,
            patch("analysis.fundamental.get_financials") as m_fin,
            patch("analysis.crypto_analyzer.CryptoAnalyzer") as m_crypto,
            patch("data.fetcher.get_info_age_hours", return_value=2.0),
        ):
            m_crypto.return_value.analyze.return_value = sentinel
            r = FundamentalAnalyzer().analyze("BTC-USD")

        assert r is sentinel
        assert r.is_crypto and r.asset_class == "crypto"
        assert r.data_quality is not None          # fast-path still stamps quality
        m_info.assert_not_called()                 # equity path never touched
        m_fin.assert_not_called()


# --------------------------------------------------------------------------- #
#  Engine invariants                                                           #
# --------------------------------------------------------------------------- #

class TestEngineInvariants:
    def test_adjusted_score_assembly_formula(self):
        """``raw_adjusted_score`` is exactly base + the four bonuses (analysis/
        fundamental.py:920); ``adjusted_score`` is that clamped to [0, 100].

        Note ``tailwind_bonus`` *can* be negative (a headwind), so
        ``adjusted_score >= total_score`` is NOT a guarantee — only the assembly
        identity is.
        """
        r = _analyze("Consumer Defensive")
        assert r.consistency_score >= 0
        assert r.piotroski_bonus >= 0
        assert r.moat_bonus >= 0

        raw = (r.total_score + r.consistency_score + r.piotroski_bonus
               + r.moat_bonus + r.tailwind_bonus)
        assert r.raw_adjusted_score == pytest.approx(round(raw, 1), abs=0.05)
        assert r.adjusted_score == pytest.approx(
            round(min(max(raw, 0.0), 100.0), 1), abs=0.05
        )

    def test_positive_bonuses_lift_adjusted_above_total(self):
        """When the tailwind is not a headwind, the additive bonuses can only
        raise the score."""
        r = _analyze("Consumer Defensive")
        assert r.tailwind_bonus >= 0            # no curated headwind for this sector
        assert r.adjusted_score >= r.total_score - 1e-6

    def test_no_financial_statements_falls_back_to_poor(self):
        with (
            patch("analysis.fundamental.get_info", return_value={
                "longName": "Nodata Co", "sector": "Technology",
                "currentPrice": 50.0, "regularMarketPrice": 50.0, "marketCap": 1e9,
            }),
            patch("analysis.fundamental.get_financials", return_value={}),
            patch("analysis.fundamental.get_dividends", return_value=pd.Series(dtype=float)),
            patch("data.fetcher.get_info_age_hours", return_value=1.0),
        ):
            r = FundamentalAnalyzer().analyze("NODATA")

        assert isinstance(r, FundamentalResult)
        assert r.symbol == "NODATA"
        assert r.data_quality["level"] == "poor"
        assert any("estados financieros" in w for w in r.warnings)

    def test_empty_info_returns_a_result_not_an_exception(self):
        with (
            patch("analysis.fundamental.get_info", return_value={}),
            patch("data.fetcher.get_info_age_hours", return_value=1.0),
        ):
            r = FundamentalAnalyzer().analyze("GHOST")
        assert isinstance(r, FundamentalResult)
        assert any("No data" in w for w in r.warnings)
