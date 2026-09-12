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

from analysis.currency_metric_text import currency_metric_text
from analysis.fundamental import FundamentalResult, effective_payout_pct, max_payout_for
from analysis.technical import TechnicalResult
from config import DATA_QUALITY
from config import STRATEGY as CFG
from config import TECHNICAL as TECH_CFG
from data.product_ux import TREND_MA_LABEL_EN

_CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

#: Orden de las acciones, de la más prudente a la más agresiva. ``AVOID`` es un
#: veredicto de block, no un peldaño de la escalera, y queda fuera del cap.
_ACTION_RANK = {"AVOID": -1, "SELL": 0, "REDUCE": 1, "HOLD": 2, "BUY": 3, "STRONG BUY": 4}

_BUY_ACTIONS = ("STRONG BUY", "BUY")


def max_action_for_score(effective_score: float) -> str:
    """El peldaño más alto de la escalera que ese score alcanza.

    Es la escalera de ``decide()`` leída como techo en vez de como asignación:
    misma fuente (``STRATEGY``), un solo lugar donde vive el orden.
    """
    if effective_score >= CFG.strong_buy_score:
        return "STRONG BUY"
    if effective_score >= CFG.buy_score:
        return "BUY"
    if effective_score >= CFG.hold_score:
        return "HOLD"
    if effective_score >= CFG.reduce_score:
        return "REDUCE"
    return "SELL"


def technical_confirms_strong_buy(technical_signal: str) -> bool:
    """¿La señal técnica *confirma* la banda de máxima convicción?

    SIGNAL-5: una señal no medible no confirma nada. La lista vive en
    ``STRATEGY.strong_buy_technical_signals`` y deliberadamente no incluye
    ``TECHNICAL.signal_not_measurable``.
    """
    return technical_signal in tuple(CFG.strong_buy_technical_signals)


def technical_uptrend_confirmed(technical: TechnicalResult) -> bool:
    """Gate ``require_technical_uptrend``, compartido por decide() y el overlay."""
    return (
        getattr(technical, "signal", "") == "BULLISH"
        or getattr(technical, "above_sma200", None) is True
    )


def confidence_for(
    action: str,
    effective_score: float,
    technical_signal: str,
    *,
    blocked: bool,
    downgraded: bool,
    data_quality_level: str,
    negative_equity: bool,
) -> str:
    """Pure, deterministic confidence from first principles — no LLM input.

    Called as the final step of apply_safety_overlay so both the rule-based and
    AI paths produce the same label for identical (action, score, technical, dq)
    inputs. The LLM's own confidence lives in Decision.ai_confidence and is shown
    as an explanation, never as the operative label.

    ``action`` is part of the answer, not just of the signature (SIGNAL-3). The
    label is a statement about *that* action: a HIGH next to a buy claims the
    evidence supports buying. The score band alone cannot say that, because the
    bottom rung emits HIGH to mean the opposite — "high certainty the position
    should be exited".
    """
    if blocked:
        return "HIGH"

    if data_quality_level == "poor":
        return "LOW"

    score = effective_score
    sig = technical_signal
    if score >= CFG.strong_buy_score:
        base = "HIGH" if sig == "BULLISH" else "MEDIUM"
    elif score >= CFG.buy_score:
        base = "HIGH" if sig == "BULLISH" else "MEDIUM"
    elif score >= CFG.hold_score:
        base = "MEDIUM"
    elif score >= CFG.reduce_score:
        base = "MEDIUM"
    else:
        base = "HIGH"  # SELL: high certainty the position should be exited

    result = base
    for cap in (
        # SIGNAL-3: una compra cuyo score no llega a su banda no puede salir HIGH.
        # El HIGH de la banda SELL es certeza *de salir*; heredado por un BUY dice
        # lo contrario de lo que la evidencia sostiene, y era el mecanismo que
        # convertía la acción incoherente del camino AI en una fila convincente.
        # El techo sale de `max_action_for_score`: la misma escalera que `decide()`,
        # un solo lugar donde viven los umbrales.
        "MEDIUM"
        if action in _BUY_ACTIONS
        and _ACTION_RANK[action] > _ACTION_RANK[max_action_for_score(score)]
        else None,
        "MEDIUM" if downgraded else None,
        (getattr(DATA_QUALITY, "partial_max_confidence", "MEDIUM") or "MEDIUM")
        if data_quality_level == "partial"
        else None,
        "MEDIUM" if negative_equity else None,
    ):
        if cap and _CONFIDENCE_RANK.get(result, 1) > _CONFIDENCE_RANK.get(cap, 1):
            result = cap
    return result


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

    Single point where confidence is finalised via confidence_for(), so both
    the rule-based and AI paths always emit the same deterministic label for the
    same (action, score, technical, dq) inputs.
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
                decision.decisive_reason = f"Bloqueado: {reason}"
                decision.rationale = [f"BLOCKED (safety overlay): {reason}"] + list(
                    decision.rationale or []
                )
    else:
        blocked, reason = RetirementStrategy()._check_safety_blocks(fundamental, technical)
        if blocked and decision.action in ("STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"):
            decision.action = "AVOID"
            decision.blocked = True
            decision.block_reason = reason
            decision.decisive_reason = f"Bloqueado: {reason}"
            decision.rationale = [f"BLOCKED (safety overlay): {reason}"] + list(
                decision.rationale or []
            )

    # SIGNAL-2: las dos políticas blandas valen para las dos clases de activo, igual
    # que en `decide()` (que no las condiciona por clase). Vivían dentro del `else`
    # de equity, así que un STRONG BUY de IA sobre un crypto con data quality `poor`
    # sobrevivía intacto — y salía con confianza LOW, porque `confidence_for` sí lee
    # la data quality: la fila se contradecía a sí misma.
    if not decision.blocked:
        apply_negative_equity_policy(decision, fundamental)
        apply_data_quality_policy(decision, fundamental)

    # SIGNAL-1: el camino AI vuelve a pasar por la escalera y por los dos vetos
    # técnicos de la matriz. Un block ya dejó la acción en AVOID y no se toca.
    if not decision.blocked and CFG.ai_action_capped_by_score_ladder:
        _cap_action_to_matrix(decision, effective_decision_score(fundamental), technical)

    # SIGNAL-4: el motivo es uno solo y lo escribe el motor. El camino AI llega
    # sin `decisive_reason` (`_parse_response` no lo escribe, y no debe: duplicaría
    # las reglas), así que se lo pedimos al rule-based sobre el MISMO
    # (fundamental, technical). De eso dependen dos cosas visibles: el cap
    # `downgraded` de la confianza —abajo— y la celda «Motivo» del Screener.
    # Sólo se adopta cuando no hay motivo propio: un block o una política blanda
    # ya escribieron el suyo, que es más específico.
    if not decision.decisive_reason:
        decision.decisive_reason = RetirementStrategy().decide(fundamental, technical).decisive_reason

    decision.confidence = confidence_for(
        decision.action,
        decision.fundamental_score,
        technical.signal,
        blocked=decision.blocked,
        downgraded=bool(decision.decisive_reason),
        data_quality_level=(getattr(fundamental, "data_quality", {}) or {}).get("level", ""),
        negative_equity=getattr(fundamental, "negative_equity", False),
    )
    return decision


def _cap_action_to_matrix(
    decision: "Decision",
    effective_score: float,
    technical: TechnicalResult,
) -> None:
    """Bajar la acción hasta donde la matriz de ``decide()`` la sostiene (SIGNAL-1).

    ``apply_safety_overlay`` re-aplicaba los blocks duros y las dos políticas
    blandas, pero nada comparaba la acción del LLM contra la escalera de score ni
    contra los vetos técnicos: el camino AI podía emitir BUY sobre un score de
    banda SELL, con confianza HIGH y un motivo que afirmaba «zona de compra».

    Sólo baja, nunca sube: el LLM puede ser *más* prudente que la escalera (y
    cuando lo es, `decisive_reason` explica por qué), nunca menos. Al ser
    monótona decreciente la función es idempotente — el overlay corre dos veces
    sobre el mismo objeto en el pipeline real.
    """
    ceiling = max_action_for_score(effective_score)
    if _ACTION_RANK.get(decision.action, _ACTION_RANK["HOLD"]) > _ACTION_RANK[ceiling]:
        decision.action = ceiling

    sig = getattr(technical, "signal", "")

    # STRONG BUY pide confirmación técnica (`decide()` cae a BUY si no la tiene).
    if decision.action == "STRONG BUY" and not technical_confirms_strong_buy(sig):
        decision.action = "BUY"

    # Veto de técnico BEARISH sobre cualquier compra: `decide()` lo resuelve
    # dejando caer la banda a HOLD, que acá ya está por debajo del techo.
    if decision.action in _BUY_ACTIONS and sig == "BEARISH":
        decision.action = "HOLD"

    if (
        CFG.require_technical_uptrend
        and decision.action in _BUY_ACTIONS
        and not technical_uptrend_confirmed(technical)
    ):
        decision.action = "HOLD"


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
        note = "BUY degradado a HOLD por data quality pobre (datos incompletos)"
        decision.decisive_reason = note
        if note not in (decision.rationale or []):
            decision.rationale = [note] + list(decision.rationale or [])
        return decision

    if level == "partial":
        if getattr(config, "partial_caps_strong_buy", True) and decision.action == "STRONG BUY":
            decision.action = "BUY"
            note = "STRONG BUY capado a BUY por data quality partial (métricas incompletas)"
            decision.decisive_reason = note
            if note not in (decision.rationale or []):
                decision.rationale = [note] + list(decision.rationale or [])

    return decision


def apply_negative_equity_policy(
    decision: "Decision",
    fundamental: FundamentalResult,
    *,
    config=None,
) -> "Decision":
    """Cap the action when shareholders' equity is negative (audit 2026-08-22, P1-3).

    Both hard guards in ``_check_safety_blocks`` key off fields that yfinance
    *omits* for exactly this population: ``debtToEquity`` (so ``> max_debt_equity``
    never fires) and ``priceToBook`` (so ``< 0`` never fires). Measured on the
    cached universe, MCD, SBUX, ABBV, YUM and LOW sailed through both — MCD with
    $54.8B of debt against −$1.79B of equity — and on top of that collected 7 of
    20 health points with the note "Very low debt D/E=0.00".

    Negative equity is not insolvency: in those names it is the accounting residue
    of years of buybacks. So this does not block. It states the fact, adds the risk
    and caps the action at HOLD, because "how levered is it" is a question the data
    cannot answer for these companies — and STRONG BUY is an answer.

    Same shape as :func:`apply_data_quality_policy`, and called from the same two
    places (``decide`` and ``apply_safety_overlay``) so the LLM path cannot skip it.
    """
    if config is None:
        config = CFG
    if not getattr(config, "negative_equity_caps_action", True):
        return decision
    if not getattr(fundamental, "negative_equity", False):
        return decision

    risk = "Patrimonio neto negativo — D/E indefinido, apalancamiento no verificable"
    if risk not in (decision.risks or []):
        decision.risks = list(decision.risks or []) + [risk]

    if decision.action in ("STRONG BUY", "BUY"):
        note = f"{decision.action} capado a HOLD por patrimonio neto negativo"
        decision.action = "HOLD"
        decision.decisive_reason = note
        if note not in (decision.rationale or []):
            decision.rationale = [note] + list(decision.rationale or [])

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

    # The one reason that explains *this* action, set wherever the engine blocks
    # or downgrades (audit item 04). `rationale` is a descriptive list whose order
    # is an implementation detail; this is the sentence a user needs to reconcile
    # "95.7/100" with "HOLD". Empty when the action follows straight from the score.
    decisive_reason: str = ""

    # AI analysis (empty when using rule-based engine)
    ai_reasoning: str = ""

    # Grok allocation recommendation (None when rule-based or when Grok didn't provide it)
    recommended_max_allocation_pct: Optional[float] = None

    # Structured macro factors (new in structural macro improvement).
    # Populated from LLM when AI is used; [] when rule-based, on error, or when LLM judged no material macro.
    # Each item: {"factor": str, "why_relevant": str, "impact": str, "effect_on_allocation_or_conviction": str}
    macro_factors: List[Dict[str, Any]] = field(default_factory=list)

    # AI provenance — what the LLM said and whether it was the decision-maker.
    # ai_confidence: the LLM's own confidence label (explanation only, NEVER the operative label).
    # ai_used: True only when the LLM produced this verdict (not fallback, not enrich_only).
    ai_confidence: str = ""
    ai_used: bool = False
    ai_provider: str = ""
    ai_model: str = ""

    @property
    def action_emoji(self) -> str:
        return {
            "STRONG BUY": "🟢",
            "BUY": "🟩",
            "HOLD": "🟡",
            "REDUCE": "🟠",
            "SELL": "🔴",
            # AVOID used to fall through to the "⚪" default — the most negative
            # verdict in the scale drawn more neutrally than HOLD (audit item 22).
            "AVOID": "⛔",
        }.get(self.action, "⚪")

    @property
    def score_badge(self) -> str:
        """Badge for the score, read off the same ladder that produced the action.

        These used to be the literals 75/60/45. Left alone when the thresholds were
        re-anchored (2026-08-22) the badge would have called a 76 "⭐ Excellent"
        while the engine no longer rated it STRONG BUY — verdict and badge
        contradicting each other on the same screen.
        """
        s = self.fundamental_score
        if s >= CFG.strong_buy_score:
            return "⭐ Excellent"
        elif s >= CFG.buy_score:
            return "✅ Good"
        elif s >= CFG.hold_score:
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
                decision.decisive_reason = f"Bloqueado: {reason}"
                decision.rationale.append(f"BLOCKED: {reason}")
                return decision
        else:
            # Crypto-specific safety: parabolic detection still applies
            if (technical.price_vs_52w_low_pct > 120 and
                    technical.rsi_weekly and technical.rsi_weekly > 80):
                decision.action = "AVOID"
                decision.blocked = True
                decision.block_reason = f"Movimiento parabólico crypto (RSI={technical.rsi_weekly:.0f}, +{technical.price_vs_52w_low_pct:.0f}% desde 52w low)"
                decision.decisive_reason = f"Bloqueado: {decision.block_reason}"
                decision.rationale.append(f"BLOCKED: {decision.block_reason}")
                return decision

        # --- Step 2: Decision matrix (action + decisive_reason only; confidence set later) ---
        score = effective_score
        tech = technical.signal

        if score >= CFG.strong_buy_score and technical_confirms_strong_buy(tech):
            if fundamental.is_value_stock() or not CFG.require_margin_of_safety:
                decision.action = "STRONG BUY"
            else:
                decision.action = "BUY"
                decision.decisive_reason = (
                    "Fundamentales de STRONG BUY, pero todavía sin margen de seguridad — "
                    "esperar una baja"
                )
                decision.rationale.append("Strong fundamentals but no margin of safety yet — wait for pullback")

        elif score >= CFG.buy_score and tech != "BEARISH":
            decision.action = "BUY"
            # Un score de banda STRONG BUY que cae acá es una degradación, no un BUY
            # de libro: la confirmación técnica que esa banda exige no existe. Sin
            # este motivo la celda «Motivo» decía "el técnico no lo contradice" —
            # que es justo lo que el estado no medible desmiente (SIGNAL-5).
            if score >= CFG.strong_buy_score and tech == TECH_CFG.signal_not_measurable:
                decision.decisive_reason = (
                    "Sin historia suficiente para confirmar el técnico — alcanza para "
                    "comprar, no para compra fuerte"
                )
                decision.rationale.append(
                    "Strong fundamentals but the technical signal is not measurable "
                    "(insufficient price history) — BUY, not STRONG BUY"
                )

        elif score >= CFG.hold_score:
            decision.action = "HOLD"
            if tech == "BEARISH":
                decision.decisive_reason = "Fundamentales sólidos pero técnico débil — mantener, no agregar"
                decision.rationale.append("Solid fundamentals but technical weakness — hold, do not add")

        elif score >= CFG.reduce_score:
            decision.action = "REDUCE"
            decision.decisive_reason = "Calidad fundamental en deterioro — reducir exposición"
            decision.rationale.append("Fundamental quality declining — reduce exposure gradually")

        else:
            decision.action = "SELL"
            # decisive_reason intentionally empty: action follows straight from the score.
            decision.rationale.append("Fundamental deterioration — exit position")

        # Technical confirmation for BUY / STRONG BUY (config-first)
        if CFG.require_technical_uptrend and decision.action in ("BUY", "STRONG BUY"):
            if not technical_uptrend_confirmed(technical):
                decision.action = "HOLD"
                decision.decisive_reason = (
                    "Los fundamentales dan para comprar, pero no hay tendencia alcista "
                    "confirmada — mantener, no agregar"
                )
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
                decision.decisive_reason = "BUY capado a HOLD por volatilidad extrema (perfil retiro)"
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
        apply_negative_equity_policy(decision, fundamental)
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
        fcf_currency_text = currency_metric_text(f, "fcf_yield", rationale=True)
        if fcf_currency_text:
            decision.rationale.append(fcf_currency_text)
        elif f.fcf_yield is not None and f.fcf_yield >= 3:
            decision.rationale.append(f"Attractive FCF yield: {f.fcf_yield:.1f}%")
        p_ffo_currency_text = currency_metric_text(f, "p_ffo", rationale=True)
        if p_ffo_currency_text:
            decision.rationale.append(p_ffo_currency_text)
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
        if t.above_sma200 is True:
            decision.rationale.append(f"Price above the {TREND_MA_LABEL_EN} (~3.8y) — long-term uptrend intact")
        if t.golden_cross:
            decision.rationale.append("Golden Cross — momentum confirming")
        if t.rsi_weekly is not None and t.rsi_weekly < 40:
            decision.rationale.append(f"RSI {t.rsi_weekly:.0f} — pullback offers entry opportunity")
        if t.sma200_slope_pct is not None and t.sma200_slope_pct > 3:
            decision.rationale.append(f"{TREND_MA_LABEL_EN} trending up +{t.sma200_slope_pct:.1f}% — secular uptrend")

        # Risks
        for w in fundamental.warnings:
            decision.risks.append(w)
        for w in technical.warnings:
            decision.risks.append(w)

        # The payout the *scorer* judged, at the *scorer's* cut (U2-6). This used to
        # read `payout_ratio` — dividends over accounting profit — against a literal
        # 80, so a REIT whose dividend the dividend dimension had just graded as
        # healthy on FFO was told in the same breath that it might cut it: measured on
        # the cached universe, 12 of 13. The basis is named because a payout quoted
        # without one cannot be checked.
        payout, basis = effective_payout_pct(fundamental)
        # U5-4: the cut depends on the basis. 75 % of earnings and 75 % of FFO are
        # not the same claim, and U2-6's invariant — one number for the score and
        # the warning — is preserved by both reading this helper.
        if payout is not None and payout > max_payout_for(basis):
            basis_label = "FFO" if basis == "ffo" else "earnings"
            decision.risks.append(
                f"High dividend payout ratio ({payout:.0f}% of {basis_label}) — may cut dividend"
            )
        # ``is False``, not ``not``: an unknown trend is not a downtrend. A
        # company listed two years ago has no 200-week mean to be under, and
        # filing that as a risk turns the length of its price series into a
        # statement about its business (U3-1).
        if t.above_sma200 is False:
            decision.risks.append(f"Price below the {TREND_MA_LABEL_EN} (~3.8y) — long-term downtrend caution")


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

    if ai_config and ai_config.enabled and not getattr(ai_config, "enrich_only", False):
        from analysis.ai_analyzer import AIAnalyzer
        decision = AIAnalyzer(ai_config).analyze(fund, tech)
    else:
        # enrich_only: the AI still fed the score through the cached moat and
        # tailwind layers; only the decision falls back here (U0-2).
        decision = RetirementStrategy().decide(fund, tech)

    # P0 D1: hard safety blocks always win (AI path included)
    decision = apply_safety_overlay(decision, fund, tech)

    return fund, tech, decision
