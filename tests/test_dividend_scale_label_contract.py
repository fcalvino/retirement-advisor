"""Contract of the dividend-dimension denominator shown to a person (N7).

``_score_dividends`` pays 4 (yield) + 3 (payout) + 3 (streak) = 10. A fund
has no ``payoutRatio`` (13/13 cached funds missing, 130/130 equities present),
so the payout leg is unreachable and the real ceiling is 7. Showing
«Dividend x/10» on a fund promised a scale the asset cannot reach.

This is a relabel of the denominator. The scorer is untouched: 0 scores move.
Locked by the helpers in ``data/product_ux.py``.
"""

from __future__ import annotations

from pathlib import Path

from data.product_ux import (
    DIVIDEND_PAYOUT_POINTS,
    DIVIDEND_SCORE_MAX_EQUITY,
    DIVIDEND_SCORE_MAX_FUND,
    dividend_score_help,
    dividend_score_max,
    format_dividend_score,
)

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


USER_FACING = [
    "dashboard/pages/2_Stock_Analysis.py",
    "analysis/prompts.py",
    "main.py",
]


class TestDividendScoreMax:
    def test_fund_ceiling_is_seven(self):
        assert dividend_score_max("fund") == DIVIDEND_SCORE_MAX_FUND == 7
        assert DIVIDEND_SCORE_MAX_EQUITY - DIVIDEND_PAYOUT_POINTS == DIVIDEND_SCORE_MAX_FUND

    def test_equity_ceiling_stays_ten(self):
        assert dividend_score_max("equity") == 10
        assert dividend_score_max(None) == 10
        assert dividend_score_max("") == 10

    def test_format_does_not_show_ten_for_a_fund(self):
        assert format_dividend_score(2.0, "fund") == "2/7"
        assert "/10" not in format_dividend_score(2.0, "fund")
        assert format_dividend_score(8.0, "equity") == "8/10"

    def test_help_names_the_missing_payout_leg(self):
        help_fund = dividend_score_help("fund")
        assert "7" in help_fund
        assert "payout" in help_fund.lower()
        assert "inalcanzables" in help_fund


class TestSurfacesDoNotHardcodeTen:
    def test_no_hardcoded_dividend_over_ten(self):
        needle = "dividend_score:.0f}/10"
        for rel in USER_FACING:
            src = _src(rel)
            assert needle not in src, (
                f"{rel} still prints the dividend dimension over 10, which a "
                f"fund cannot reach"
            )
            assert "format_dividend_score" in src

    def test_equity_prompt_keeps_ten_and_fund_prompt_does_not(self):
        from analysis.fundamental import FundamentalResult
        from analysis.prompts import equity_decision_prompt
        from analysis.technical import TechnicalResult

        equity = FundamentalResult(symbol="AAPL")
        equity.asset_class = "equity"
        equity.dividend_score = 8.0
        fund = FundamentalResult(symbol="BND")
        fund.asset_class = "fund"
        fund.dividend_score = 2.0
        tech = TechnicalResult(symbol="X")
        assert "Dividendos (8/10)" in equity_decision_prompt(equity, tech)
        prompt_fund = equity_decision_prompt(fund, tech)
        assert "Dividendos (2/7)" in prompt_fund
        assert "Dividendos (2/10)" not in prompt_fund
