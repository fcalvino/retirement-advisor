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
  - Never buy a stock with D/E > STRATEGY.max_debt_equity (default 3.0)
  - Never buy when RSI weekly > 80 on parabolic extension (safety block)
  - Maximum 8% portfolio weight per position
  - Trigger review when fundamental score drops > 10 pts
  - AI path cannot bypass hard safety blocks (apply_safety_overlay)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from analysis.fundamental import FundamentalResult
from analysis.technical import TechnicalResult
from config import DATA_QUALITY
from config import STRATEGY as CFG

_CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def effective_decision_score(fundamental: FundamentalResult) -> float:
    """Score used by the decision matrix (P0 D2: align with portfolio layer).

    Crypto always uses adjusted_score (total_score is 0 by design).
    Equity uses adjusted_score when STRATEGY.use_adjusted_score_for_decision
    is True (default); otherwise legacy total_score.
    """
    if getattr(fundamental, "is_crypto", False) or CFG.use_adjusted_score_for_decision:
        return float(getattr(fundamental, "adjusted_score", 0.0) or 0.0)
    return float(getattr(fundamental, "total_score", 0.0) or 0.0)


def apply_safety_overlay(
    decision: "Decision",
    fundamental: FundamentalResult,
    technical: TechnicalResult,
) -> "Decision":
    """Re-apply hard safety blocks after any decision path (rule-based or AI).

    P0 audit D1: the LLM path must never upgrade past leverage / book-value /
    parabolic guards. Idempotent when decide() already blocked.
    """
    _is_crypto = getattr(fundamental, "is_crypto", False)

    if _is_crypto:
        if (
            technical.price_vs_52w_low_pct > 120
            and technical.rsi_weekly
            and technical.rsi_weekly > 80
        ):
            if decision.action in ("STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"):
                reason = (
                    f"Movimiento parabólico crypto (RSI={technical.rsi_weekly:.0f}, "
                    f"+{technical.price_vs_52w_low_pct:.0f}% desde 52w low)"
                )
                decision.action = "AVOID"
                decision.blocked = True
                decision.block_reason = reason
                decision.confidence = "HIGH"
                decision.rationale = [f"BLOCKED (safety overlay): {reason}"] + list(
                    decision.rationale or []
                )
        return decision

    blocked, reason = RetirementStrategy()._check_safety_blocks(fundamental, technical)
    if blocked and decision.action in ("STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"):
        decision.action = "AVOID"
        decision.blocked = True
        decision.block_reason = reason
        decision.confidence = "HIGH"
        decision.rationale = [f"BLOCKED (safety overlay): {reason}"] + list(
            decision.rationale or []
        )

    # Soft data-quality policy also on AI path (same as decide())
    if not decision.blocked:
        apply_data_quality_policy(decision, fundamental)

    return decision


def apply_data_quality_policy(
    decision: "Decision",
    fundamental: FundamentalResult,
    *,
    config=None,
) -> "Decision":
    """Apply soft data-quality gates to a decision (rule-based and AI paths).

    Policy (P0 — from ``DATA_QUALITY``, never rewrites scores):
      - ``poor``: STRONG BUY / BUY → HOLD, confidence LOW
      - ``partial``: STRONG BUY → BUY (optional), confidence capped
      - risks already annotated by decide() for missing fields; this helper
        focuses on action/confidence demotions
    """
    if config is None:
        config = DATA_QUALITY
    dq = getattr(fundamental, "data_quality", None) or {}
    if not isinstance(dq, dict):
        return decision
    level = dq.get("level") or ""

    if level == "poor" and decision.action in ("STRONG BUY", "BUY"):
        decision.action = "HOLD"
        decision.confidence = "LOW"
        note = "BUY degradado a HOLD por data quality pobre (datos incompletos)"
        if note not in (decision.rationale or []):
            decision.rationale = [note] + list(decision.rationale or [])
        return decision

    if level == "partial":
        if getattr(config, "partial_caps_strong_buy", True) and decision.action == "STRONG BUY":
            decision.action = "BUY"
            note = "STRONG BUY capado a BUY por data quality partial (métricas incompletas)"
            if note not in (decision.rationale or []):
                decision.rationale = [note] + list(decision.rationale or [])
        cap = getattr(config, "partial_max_confidence", "MEDIUM") or "MEDIUM"
        cur = decision.confidence or "MEDIUM"
        if _CONFIDENCE_RANK.get(cur, 1) > _CONFIDENCE_RANK.get(cap, 1):
            decision.confidence = cap
            note = f"Confianza capada a {cap} por data quality partial"
            if note not in (decision.rationale or []):
                decision.rationale = list(decision.rationale or []) + [note]

    return decision


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

    # Grok allocation recommendation (None when rule-based or when Grok didn't provide it)
    recommended_max_allocation_pct: Optional[float] = None

    # Structured macro factors (new in structural macro improvement).
    # Populated from LLM when AI is used; [] when rule-based, on error, or when LLM judged no material macro.
    # Each item: {"factor": str, "why_relevant": str, "impact": str, "effect_on_allocation_or_conviction": str}
    macro_factors: List[Dict[str, Any]] = field(default_factory=list)

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

        _is_crypto = getattr(fundamental, "is_crypto", False)
        effective_score = effective_decision_score(fundamental)

        decision = Decision(
            symbol=symbol,
            fundamental_score=effective_score,
            technical_signal=technical.signal,
            has_margin_of_safety=fundamental.is_value_stock(),
        )

        # --- Step 1: Hard safety blocks (most equity blocks don't apply to crypto) ---
        if not _is_crypto:
            blocked, reason = self._check_safety_blocks(fundamental, technical)
            if blocked:
                decision.action = "AVOID"
                decision.blocked = True
                decision.block_reason = reason
                decision.confidence = "HIGH"
                decision.rationale.append(f"BLOCKED: {reason}")
                return decision
        else:
            # Crypto-specific safety: parabolic detection still applies
            if (technical.price_vs_52w_low_pct > 120 and
                    technical.rsi_weekly and technical.rsi_weekly > 80):
                decision.action = "AVOID"
                decision.blocked = True
                decision.block_reason = f"Movimiento parabólico crypto (RSI={technical.rsi_weekly:.0f}, +{technical.price_vs_52w_low_pct:.0f}% desde 52w low)"
                decision.confidence = "HIGH"
                decision.rationale.append(f"BLOCKED: {decision.block_reason}")
                return decision

        # --- Step 2: Decision matrix ---
        score = effective_score
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

        # Technical confirmation for BUY / STRONG BUY (config-first)
        if CFG.require_technical_uptrend and decision.action in ("BUY", "STRONG BUY"):
            uptrend = tech == "BULLISH" or bool(getattr(technical, "above_sma200", False))
            if not uptrend:
                decision.action = "HOLD"
                decision.confidence = "MEDIUM"
                decision.rationale.append(
                    "Fundamentals support buying but technical uptrend not confirmed "
                    "(require_technical_uptrend) — hold, do not add"
                )

        # --- Step 3: Add rationale ---
        self._build_rationale(decision, fundamental, technical)

        # Crypto high-vol cap (P1 D9): extreme vol → never BUY for retirement
        if _is_crypto and decision.action in ("STRONG BUY", "BUY"):
            if any("Volatilidad extrema" in (w or "") for w in (fundamental.warnings or [])):
                decision.action = "HOLD"
                decision.confidence = "MEDIUM"
                decision.rationale.append(
                    "BUY capado a HOLD por volatilidad extrema crypto (perfil retiro)"
                )

        # Data quality: risks for incomplete fill + soft policy (partial/poor)
        dq = getattr(fundamental, "data_quality", None) or {}
        if isinstance(dq, dict) and dq.get("level") in ("partial", "poor"):
            missing = ", ".join((dq.get("missing_fields") or [])[:5]) or "métricas clave"
            decision.risks.append(
                f"Calidad de datos {dq['level']}: faltan {missing}"
            )
        apply_data_quality_policy(decision, fundamental)

        logger.info(f"{symbol}: {decision.action} (F={score:.1f}, T={tech}{'  🪙crypto' if _is_crypto else ''})")
        return decision

    # ------------------------------------------------------------------ #
    #  Safety blocks — hard rules regardless of score                     #
    # ------------------------------------------------------------------ #

    def _check_safety_blocks(
        self,
        fundamental: FundamentalResult,
        technical: TechnicalResult,
    ) -> tuple[bool, str]:
        # Excessive leverage (threshold from STRATEGY.max_debt_equity — P0 D3)
        if (
            fundamental.debt_equity is not None
            and fundamental.debt_equity > CFG.max_debt_equity
        ):
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

        # Sector-country structural tailwind (Idea 2) — surface only when material
        tw_class = getattr(f, "tailwind_classification", "Neutral")
        tw_detail = getattr(f, "tailwind_detail", None)
        if tw_detail is not None:
            _tw_expl = (getattr(tw_detail, "explanation", "") or "")[:160]
            _tw_dur = getattr(tw_detail, "durability_years", 0)
            _dur_txt = f" (~{_tw_dur} años)" if _tw_dur else ""
            if tw_class == "Strong":
                decision.rationale.append(
                    f"Cola de viento estructural sector-país fuerte{_dur_txt}: {_tw_expl}"
                )
            elif tw_class == "Headwind":
                decision.risks.append(
                    f"Viento de frente estructural sector-país{_dur_txt}: {_tw_expl}"
                )

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
    from config import is_crypto, normalize_crypto_ticker

    fund = FundamentalAnalyzer().analyze(symbol, ai_config=ai_config)

    # For crypto, CryptoAnalyzer already ran TechnicalAnalyzer internally — reuse it.
    # This avoids a redundant yfinance call (10y weekly history) per crypto ticker.
    if is_crypto(symbol) and getattr(fund, "_cached_tech", None) is not None:
        tech = fund._cached_tech
    else:
        tech_symbol = normalize_crypto_ticker(symbol) if is_crypto(symbol) else symbol
        tech = TechnicalAnalyzer().analyze(tech_symbol)

    if ai_config and ai_config.enabled:
        from analysis.ai_analyzer import AIAnalyzer
        decision = AIAnalyzer(ai_config).analyze(fund, tech)
    else:
        decision = RetirementStrategy().decide(fund, tech)

    # P0 D1: hard safety blocks always win (AI path included)
    decision = apply_safety_overlay(decision, fund, tech)

    return fund, tech, decision
