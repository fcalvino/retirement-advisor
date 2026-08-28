"""Negative shareholders' equity is visible to the decision layer (CONTEXT §5).

The defect: ``_check_safety_blocks`` has two hard guards — ``debt_equity >
max_debt_equity`` and ``pb_ratio < 0`` — and yfinance **omits** both fields for
exactly the companies they exist to catch. A company with negative equity has no
defined D/E, so ``info["debtToEquity"]`` is absent (the guard reads ``None`` and
skips), and ``priceToBook`` is absent rather than negative (same). Measured on the
cached universe (2026-08-22), five names passed both guards untouched *and*
collected 7 of 20 health points with the note "Very low debt D/E=0.00":

    MCD   equity −$1.79B  debt $54.81B
    SBUX  equity −$8.10B  debt $26.61B
    ABBV  equity −$3.27B  debt $67.50B
    YUM   equity −$7.33B  debt $13.19B
    LOW   equity −$9.92B  debt $44.68B

Per CONTEXT §5 the oracle is the definition of the ratio itself — total debt over
shareholders' equity, divided by hand — used to check the value the engine derives
from the statements when the feed omits it. Banks are the other half of that
population: the ratio is undefined-by-convention for them but both inputs are
reported, so it can simply be computed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from analysis.strategy import (
    Decision,
    RetirementStrategy,
    apply_negative_equity_policy,
    apply_safety_overlay,
)
from analysis.technical import TechnicalResult
from config import STRATEGY

# --------------------------------------------------------------------------- #
#  Oracle                                                                     #
# --------------------------------------------------------------------------- #

def oracle_debt_equity(total_debt: float, equity: float) -> Optional[float]:
    """The ratio from its definition; undefined when equity is not positive."""
    if equity <= 0:
        return None
    return total_debt / equity


def _balance_sheet(
    equity: float,
    total_debt: float,
    *,
    years: int = 4,
    current_assets: bool = True,
) -> pd.DataFrame:
    """Balance sheet shaped like yfinance's: annual columns, most recent first.

    ``current_assets=False`` is the bank shape. A deposit-taking bank does not
    classify assets as current or non-current, and that absence is what the
    derivation uses as its structural marker — see ``_derive_debt_equity``.
    """
    columns = [f"{2025 - i}-12-31 00:00:00" for i in range(years)]
    rows = {
        "Stockholders Equity": [equity * (1 - 0.05 * i) for i in range(years)],
        "Total Debt": [total_debt * (1 - 0.03 * i) for i in range(years)],
        "Total Assets": [abs(equity) + total_debt for _ in range(years)],
    }
    if current_assets:
        rows["Current Assets"] = [(abs(equity) + total_debt) * 0.3 for _ in range(years)]
        rows["Current Liabilities"] = [(abs(equity) + total_debt) * 0.2 for _ in range(years)]
    return pd.DataFrame(rows, index=columns).T


def _info(**overrides: Any) -> Dict[str, Any]:
    base = {
        "longName": "Test Co",
        "sector": "Consumer Cyclical",
        "currentPrice": 100.0,
        "regularMarketPrice": 100.0,
        "marketCap": 1e11,
    }
    base.update(overrides)
    return base


def _health(info: Dict[str, Any], bs: pd.DataFrame):
    result = FundamentalResult(symbol="TEST")
    score = FundamentalAnalyzer()._score_financial_health(info, bs, pd.DataFrame(), result)
    return score, result


# --------------------------------------------------------------------------- #
#  Derivation from the statements                                             #
# --------------------------------------------------------------------------- #

class TestDerivedDebtEquity:
    def test_operating_company_gets_the_ratio_computed(self):
        """No `debtToEquity`, but both inputs are on a normal balance sheet."""
        bs = _balance_sheet(equity=362_438e6, total_debt=499_982e6)
        score, result = _health(_info(), bs)

        expected = oracle_debt_equity(499_982e6, 362_438e6)
        assert result.debt_equity == pytest.approx(expected)
        assert result.negative_equity is False
        assert "derivado" in result.notes.get("debt_equity_source", "")
        assert score > 0  # 1.38 lands in the "acceptable" band instead of scoring nothing

    def test_bank_shape_is_not_derived_at_all(self):
        """JPM shape: `Total Debt / Equity` omits deposits, so it is not leverage.

        The ratio would be 1.38 — comfortably inside the paying bands and well under
        the 3.0 block — while JPM carries $4.06T of total liabilities against $362B of
        equity, i.e. 11.2x. Measured on the cache, BSBR (0.22) and CIB (0.46) were
        collecting the full 7 points for "very low debt" while levered 9:1 and 8.6:1.
        """
        bs = _balance_sheet(equity=362_438e6, total_debt=499_982e6, current_assets=False)
        score, result = _health(_info(), bs)

        assert result.debt_equity is None
        assert score == 0.0
        assert "debt_equity_source" not in result.notes
        assert "debt_equity" not in result.notes          # no "very low debt" claim
        assert "D/E" in result.notes.get("health_missing", "")

    def test_the_marker_is_structural_not_a_label(self):
        """Nothing here reads an industry string — only the shape of the balance sheet."""
        equity, debt = 100e9, 50e9
        with_ca = _health(_info(), _balance_sheet(equity, debt))[1]
        without_ca = _health(_info(), _balance_sheet(equity, debt, current_assets=False))[1]

        assert with_ca.debt_equity == pytest.approx(oracle_debt_equity(debt, equity))
        assert without_ca.debt_equity is None

    def test_the_feed_still_wins_when_it_reports_the_ratio(self):
        """No regression: a reported D/E is used as-is, statements untouched."""
        bs = _balance_sheet(equity=100e9, total_debt=50e9)
        _, result = _health(_info(debtToEquity=57.7), bs)
        assert result.debt_equity == pytest.approx(0.577)
        assert "debt_equity_source" not in result.notes

    @pytest.mark.parametrize("equity,debt", [
        (-1.79e9, 54.81e9),   # MCD
        (-8.10e9, 26.61e9),   # SBUX
        (-3.27e9, 67.50e9),   # ABBV
    ])
    def test_negative_equity_yields_no_ratio_and_no_points(self, equity, debt):
        score, result = _health(_info(), _balance_sheet(equity=equity, total_debt=debt))

        assert oracle_debt_equity(debt, equity) is None
        assert result.debt_equity is None
        assert result.negative_equity is True
        assert score == 0.0                      # was 7 of 20
        assert "debt_equity" not in result.notes  # the "Very low debt" claim is gone
        assert any("Patrimonio neto negativo" in w for w in result.warnings)

    def test_a_negative_reported_ratio_is_not_low_leverage(self):
        """Some feeds report D/E negative instead of omitting it — same trap."""
        bs = _balance_sheet(equity=-5e9, total_debt=40e9)
        score, result = _health(_info(debtToEquity=-820.0), bs)
        assert result.debt_equity is None
        assert result.negative_equity is True
        assert score == 0.0


# --------------------------------------------------------------------------- #
#  The decision layer must see it — on both paths                             #
# --------------------------------------------------------------------------- #

def _fund(*, negative: bool, score: Optional[float] = None) -> FundamentalResult:
    # Derived from the ladder, not written down: a literal 82 landed *exactly* on
    # strong_buy_score after the 2026-08-22 re-anchoring and would have passed by a
    # hair. What this fixture needs is "a score that clears STRONG BUY", whatever
    # that happens to be.
    score = STRATEGY.strong_buy_score + 8 if score is None else score
    f = FundamentalResult(symbol="MCD")
    f.total_score = score
    f.adjusted_score = score
    f.negative_equity = negative
    f.margin_of_safety_pct = 25.0   # would otherwise unlock STRONG BUY
    f.graham_value = 400.0
    f.current_price = 300.0
    return f


def _tech() -> TechnicalResult:
    t = TechnicalResult(symbol="MCD")
    t.signal = "BULLISH"
    t.signal_strength = 60
    t.above_sma200 = True
    t.rsi_weekly = 55.0
    return t


class TestDecisionIsCapped:
    def test_rule_based_path_caps_at_hold(self):
        decision = RetirementStrategy().decide(_fund(negative=True), _tech())
        assert decision.action == "HOLD"
        assert decision.blocked is False          # capped, not blocked
        assert any("patrimonio neto negativo" in r.lower() for r in decision.rationale)
        assert any("Patrimonio neto negativo" in r for r in decision.risks)

    def test_ai_path_cannot_bypass_it(self):
        """The LLM returning STRONG BUY must still come out HOLD."""
        llm = Decision(symbol="MCD", action="STRONG BUY", confidence="HIGH")
        out = apply_safety_overlay(llm, _fund(negative=True), _tech())
        assert out.action == "HOLD"
        assert out.confidence in ("MEDIUM", "LOW")

    def test_healthy_company_is_untouched(self):
        """No regression: positive equity ⇒ identical action and rationale."""
        before = RetirementStrategy().decide(_fund(negative=False), _tech())
        assert before.action == "STRONG BUY"
        assert not any("Patrimonio neto negativo" in r for r in before.risks)

    def test_policy_is_idempotent(self):
        decision = Decision(symbol="MCD", action="BUY", confidence="HIGH")
        fund = _fund(negative=True)
        once = apply_negative_equity_policy(decision, fund)
        twice = apply_negative_equity_policy(once, fund)
        assert twice.action == "HOLD"
        assert sum("Patrimonio neto negativo" in r for r in twice.risks) == 1

    def test_the_flag_turns_it_off(self):
        decision = Decision(symbol="MCD", action="STRONG BUY", confidence="HIGH")

        class _Off:
            negative_equity_caps_action = False

        out = apply_negative_equity_policy(decision, _fund(negative=True), config=_Off())
        assert out.action == "STRONG BUY"

    def test_config_flag_exists_and_defaults_on(self):
        assert STRATEGY.negative_equity_caps_action is True

    def test_a_lower_action_is_left_alone(self):
        """SELL/REDUCE are already below the cap — nothing to demote."""
        for action in ("HOLD", "REDUCE", "SELL"):
            decision = Decision(symbol="MCD", action=action, confidence="HIGH")
            out = apply_negative_equity_policy(decision, _fund(negative=True))
            assert out.action == action
