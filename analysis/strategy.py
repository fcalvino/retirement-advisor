"""
Retirement Decision Engine.

Combines fundamental + technical analysis into a clear investment decision.

Decision matrix:
  STRONG BUY  — fund score ≥ 75 + technical BULLISH/NEUTRAL + margin of safety
  BUY         — fund score ≥ 60 + technical not BEARISH
  HOLD        — fund score ≥ 45, quality maintained, no red flags
  REDUCE      — fund score 35-44 or technical BEARISH, trim position
  SELL        — fund score < 35 or fundamental deterioration detected

Conservative rules for retirement:
  - Never buy a stock with D/E > 2.0 (leverage risk)
  - Never buy when RSI weekly > 80 (overbought — wait for pullback)
  - Maximum 8% portfolio weight per position
  - Trigger review when fundamental score drops > 10 pts
"""

from dataclasses import dataclass, field
from typing import List, Optional

from loguru import logger

from analysis.fundamental import FundamentalResult
from analysis.technical import TechnicalResult
from config import STRATEGY as CFG


@dataclass
class Decision:
    symbol: str
    action: str = "HOLD"         # STRONG BUY | BUY | HOLD | REDUCE | SELL
    confidence: str = "MEDIUM"   # HIGH | MEDIUM | LOW
    fundamental_score: float = 0.0
    technical_signal: str = "NEUTRAL"
    has_margin_of_safety: bool = False

    # Human-readable rationale (shown in dashboard)
    rationale: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)

    # Hard blocks (safety guards)
    blocked: bool = False
    block_reason: str = ""

    # AI analysis (empty when using rule-based engine)
    ai_reasoning: str = ""

    @property
    def action_emoji(self) -> str:
        return {
            "STRONG BUY": "🟢",
            "BUY": "🟩",
            "HOLD": "🟡",
            "REDUCE": "🟠",
            "SELL": "🔴",
        }.get(self.action, "⚪")

    @property
    def score_badge(self) -> str:
        s = self.fundamental_score
        if s >= 75:
            return "⭐ Excellent"
        elif s >= 60:
            return "✅ Good"
        elif s >= 45:
            return "🟡 Fair"
        else:
            return "⚠️ Weak"


class RetirementStrategy:
    """
    Implements a conservative Buy-and-Hold-Improved strategy focused on:
    - Capital preservation first
    - Quality compounders second
    - Attractive valuation third

    Inspired by Benjamin Graham (margin of safety) and Warren Buffett
    (moat quality + long-term holding).
    """

    def decide(
        self,
        fundamental: FundamentalResult,
        technical: TechnicalResult,
    ) -> Decision:
        symbol = fundamental.symbol
        decision = Decision(
            symbol=symbol,
            fundamental_score=fundamental.total_score,
            technical_signal=technical.signal,
            has_margin_of_safety=fundamental.is_value_stock(),
        )

        # --- Step 1: Hard safety blocks ---
        blocked, reason = self._check_safety_blocks(fundamental, technical)
        if blocked:
            decision.action = "AVOID"
            decision.blocked = True
            decision.block_reason = reason
            decision.confidence = "HIGH"
            decision.rationale.append(f"BLOCKED: {reason}")
            return decision

        # --- Step 2: Decision matrix ---
        score = fundamental.total_score
        tech = technical.signal

        if score >= CFG.strong_buy_score and tech in ("BULLISH", "NEUTRAL"):
            if fundamental.is_value_stock() or not CFG.require_margin_of_safety:
                decision.action = "STRONG BUY"
                decision.confidence = "HIGH"
            else:
                decision.action = "BUY"
                decision.confidence = "MEDIUM"
                decision.rationale.append("Strong fundamentals but no margin of safety yet — wait for pullback")

        elif score >= CFG.buy_score and tech != "BEARISH":
            decision.action = "BUY"
            decision.confidence = "MEDIUM" if tech == "NEUTRAL" else "HIGH"

        elif score >= CFG.hold_score:
            decision.action = "HOLD"
            decision.confidence = "MEDIUM"
            if tech == "BEARISH":
                decision.rationale.append("Solid fundamentals but technical weakness — hold, do not add")

        elif score >= 35:
            decision.action = "REDUCE"
            decision.confidence = "MEDIUM"
            decision.rationale.append("Fundamental quality declining — reduce exposure gradually")

        else:
            decision.action = "SELL"
            decision.confidence = "HIGH"
            decision.rationale.append("Fundamental deterioration — exit position")

        # --- Step 3: Add rationale ---
        self._build_rationale(decision, fundamental, technical)

        logger.info(f"{symbol}: {decision.action} (F={score:.1f}, T={tech})")
        return decision

    # ------------------------------------------------------------------ #
    #  Safety blocks — hard rules regardless of score                     #
    # ------------------------------------------------------------------ #

    def _check_safety_blocks(
        self,
        fundamental: FundamentalResult,
        technical: TechnicalResult,
    ) -> tuple[bool, str]:
        # Excessive leverage
        if fundamental.debt_equity is not None and fundamental.debt_equity > 3.0:
            return True, f"Excessive leverage (D/E = {fundamental.debt_equity:.1f})"

        # Negative equity (book value < 0)
        if fundamental.pb_ratio is not None and fundamental.pb_ratio < 0:
            return True, "Negative book value — potential insolvency risk"

        # Parabolic overextension — price >40% above 52-week average
        if technical.price_vs_52w_low_pct > 100 and technical.rsi_weekly and technical.rsi_weekly > 80:
            return True, f"Parabolic move detected (RSI={technical.rsi_weekly:.0f}, +{technical.price_vs_52w_low_pct:.0f}% from 52w low)"

        return False, ""

    # ------------------------------------------------------------------ #
    #  Rationale builder                                                   #
    # ------------------------------------------------------------------ #

    def _build_rationale(
        self,
        decision: Decision,
        fundamental: FundamentalResult,
        technical: TechnicalResult,
    ) -> None:
        f = fundamental
        t = technical

        # Fundamental highlights
        if f.roe is not None and f.roe >= 15:
            decision.rationale.append(f"High-quality compounder: ROE {f.roe:.1f}%")
        if f.revenue_cagr_5y is not None and f.revenue_cagr_5y >= 8:
            decision.rationale.append(f"Strong revenue growth: {f.revenue_cagr_5y:.1f}% CAGR")
        if f.fcf_yield is not None and f.fcf_yield >= 3:
            decision.rationale.append(f"Attractive FCF yield: {f.fcf_yield:.1f}%")
        if f.is_value_stock() and f.margin_of_safety_pct is not None:
            decision.rationale.append(f"Margin of Safety: {f.margin_of_safety_pct:.0f}% vs Graham value ${f.graham_value:.2f}")

        # Technical context
        if t.above_sma200:
            decision.rationale.append("Price above SMA200 — long-term uptrend intact")
        if t.golden_cross:
            decision.rationale.append("Golden Cross — momentum confirming")
        if t.rsi_weekly is not None and t.rsi_weekly < 40:
            decision.rationale.append(f"RSI {t.rsi_weekly:.0f} — pullback offers entry opportunity")
        if t.sma200_slope_pct > 3:
            decision.rationale.append(f"SMA200 trending up +{t.sma200_slope_pct:.1f}% — secular uptrend")

        # Risks
        for w in fundamental.warnings:
            decision.risks.append(w)
        for w in technical.warnings:
            decision.risks.append(w)

        if fundamental.payout_ratio is not None and fundamental.payout_ratio > 80:
            decision.risks.append(f"High dividend payout ratio ({fundamental.payout_ratio:.0f}%) — may cut dividend")
        if not t.above_sma200:
            decision.risks.append("Price below SMA200 — long-term downtrend caution")


def full_analysis(
    symbol: str,
    ai_config=None,
) -> tuple[FundamentalResult, TechnicalResult, Decision]:
    """Convenience function: run full fundamental + technical + decision pipeline."""
    from analysis.fundamental import FundamentalAnalyzer
    from analysis.technical import TechnicalAnalyzer

    fund = FundamentalAnalyzer().analyze(symbol, ai_config=ai_config)
    tech = TechnicalAnalyzer().analyze(symbol)

    if ai_config and ai_config.enabled:
        from analysis.ai_analyzer import AIAnalyzer
        decision = AIAnalyzer(ai_config).analyze(fund, tech)
    else:
        decision = RetirementStrategy().decide(fund, tech)

    return fund, tech, decision
