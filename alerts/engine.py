"""
Alert detection engine — compares current analysis results against stored
snapshots and fires alerts through the Notifier when thresholds are crossed.

Phase 6 additions:
  - Profile-aware severity filtering (Conservador: WARNING+ only)
  - Mute system (skip silenced symbol/type combinations)
  - Portfolio alerts (PORTFOLIO_LOSS, PORTFOLIO_DRIFT, PORTFOLIO_REBALANCE)
  - SORR_HIGH and GOAL_RISK alerts
  - AI-generated explanations via alert_explanation_prompt()

Usage:
    from alerts.engine import AlertEngine
    engine = AlertEngine()
    fired = engine.run(scored_tickers)

    # With portfolio data:
    fired = engine.run_with_portfolio(
        scored_tickers, positions, current_prices, optimizer_weights
    )

scored_tickers format (same as Optimizer input):
    [{"symbol": "AAPL", "adjusted_score": 72.3, "signal": "BUY",
      "moat_classification": "Wide", ...}, ...]
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from loguru import logger

from alerts.notifier import Notifier
from alerts.portfolio_alerts import PortfolioAlertCandidate, PortfolioAlertDetector
from alerts.store import AlertSeverity, AlertStore, AlertType, alert_store
from config import ALERTS

# Score change considered significant (points)
SCORE_CHANGE_THRESHOLD: float = ALERTS.score_change_threshold

# Signals classified as "opportunity" (entered or upgraded)
OPPORTUNITY_SIGNALS = {"STRONG_BUY", "BUY"}

# Moat categories in degradation order (used to detect downgrade)
_MOAT_RANK = {"Wide": 3, "Narrow": 2, "Minimal": 1, "None": 0}


def _normalize_signal(signal: str) -> str:
    """Canonical signal vocabulary for alerts (P0 audit D8).

    Decision.action uses spaces (\"STRONG BUY\"); OPPORTUNITY_SIGNALS and many
    tests use underscores (\"STRONG_BUY\"). Production scheduler passes
    getattr(dec, \"action\"), so without normalization STRONG BUY never matches.
    """
    s = (signal or "").upper().strip().replace(" ", "_")
    if s == "STRONGBUY":
        s = "STRONG_BUY"
    return s

# Severity ordering for profile filtering
_SEVERITY_RANK = {
    AlertSeverity.INFO:     0,
    AlertSeverity.WARNING:  1,
    AlertSeverity.CRITICAL: 2,
}


@dataclass
class FiredAlert:
    symbol: str
    alert_type: AlertType
    message: str
    severity: AlertSeverity
    explanation: str = ""


def _min_severity_for_profile(profile_name: str) -> AlertSeverity:
    """Return minimum severity threshold for the given profile."""
    name = (profile_name or "").lower()
    if "conservador" in name or "conservative" in name:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _get_ai_explanation(
    alert_type: str, symbol: str, context: dict,
    severity: AlertSeverity = AlertSeverity.INFO,
) -> str:
    """Call AI to generate a natural-language explanation for the alert."""
    if not ALERTS.ai_explanations_enabled:
        return ""
    min_sev_rank = _SEVERITY_RANK.get(AlertSeverity(ALERTS.ai_explanations_min_severity), 1)
    if _SEVERITY_RANK.get(severity, 0) < min_sev_rank:
        return ""
    try:
        from analysis.ai_analyzer import AIAnalyzer
        from analysis.prompts import alert_explanation_prompt
        from config import AI_CONFIG

        if not AI_CONFIG.enabled or not AI_CONFIG.api_key:
            return ""

        prompt = alert_explanation_prompt(alert_type, symbol, context)
        analyzer = AIAnalyzer(AI_CONFIG)
        raw = analyzer._call_api(prompt)
        if not raw:
            return ""

        # Extract JSON from response
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return ""
        data = json.loads(match.group())
        explanation = data.get("explanation", "")
        action = data.get("action_suggested", "")
        if action:
            return f"{explanation} {action}"
        return explanation
    except Exception as exc:
        logger.debug(f"AI explanation failed for {symbol}/{alert_type}: {exc}")
        return ""


class AlertEngine:
    """
    Stateful alert detector. State persists in SQLite via AlertStore.

    First run per ticker: saves baseline only — no alert fired (cold start).
    Subsequent runs: compare against baseline, fire if threshold crossed and
    not on cooldown and not muted, then update baseline.
    """

    def __init__(
        self,
        store: AlertStore = alert_store,
        active_profile: str = "Moderado",
    ) -> None:
        self._store = store
        self._notifier = Notifier()
        self._min_severity = _min_severity_for_profile(active_profile)
        self._store.purge_expired_mutes()

    def run(self, scored_tickers: List[dict]) -> List[FiredAlert]:
        """
        Analyse scored_tickers, detect threshold crossings, dispatch alerts.
        Returns list of FiredAlert objects for logging/display.
        """
        if not ALERTS.alerts_enabled:
            logger.info("AlertEngine.run skipped — ALERTS.alerts_enabled is False")
            return []

        fired: List[FiredAlert] = []

        for t in scored_tickers:
            symbol      = t.get("symbol", "")
            score       = float(t.get("adjusted_score", 0) or 0)
            signal      = _normalize_signal(str(t.get("signal", t.get("decision", "")) or ""))
            moat_class  = str(t.get("moat_classification", "None") or "None")
            company     = str(t.get("company_name", symbol) or symbol)
            sector      = str(t.get("sector", "Unknown") or "Unknown")

            if not symbol:
                continue

            snap = self._store.get_snapshot(symbol)

            if snap is None:
                self._store.save_snapshot(symbol, score, signal, moat_class)
                logger.debug(f"AlertEngine: baseline saved for {symbol}")
                continue

            prev_score  = snap.score
            prev_signal = _normalize_signal(snap.signal)
            prev_moat   = snap.moat_class

            # 1 — Signal change
            if signal and prev_signal and signal != prev_signal:
                alert = self._check_signal_change(
                    symbol, company, prev_signal, signal, score, sector
                )
                if alert:
                    fired.append(alert)

            # 2 — Score drop
            if prev_score - score >= SCORE_CHANGE_THRESHOLD:
                alert = self._check_score_drop(
                    symbol, company, prev_score, score, signal, sector
                )
                if alert:
                    fired.append(alert)

            # 3 — Score surge (new opportunity)
            elif score - prev_score >= SCORE_CHANGE_THRESHOLD and signal in OPPORTUNITY_SIGNALS:
                alert = self._check_score_surge(symbol, company, prev_score, score, signal, sector)
                if alert:
                    fired.append(alert)

            # 4 — Opportunity: new BUY/STRONG_BUY entry
            if signal in OPPORTUNITY_SIGNALS and prev_signal not in OPPORTUNITY_SIGNALS:
                alert = self._check_opportunity(symbol, company, signal, score, sector)
                if alert:
                    fired.append(alert)
                    self._log_track_record(symbol, signal, score)

            # 5 — Moat downgrade
            if _MOAT_RANK.get(moat_class, 0) < _MOAT_RANK.get(prev_moat, 0):
                alert = self._check_moat_change(symbol, company, prev_moat, moat_class, score)
                if alert:
                    fired.append(alert)

            # Update snapshot to current values
            self._store.save_snapshot(symbol, score, signal, moat_class)

        # Dispatch all fired alerts
        if fired:
            self._dispatch(fired)

        logger.info(f"AlertEngine: {len(scored_tickers)} tickers checked, {len(fired)} alerts fired")
        return fired

    def run_with_portfolio(
        self,
        scored_tickers: List[dict],
        positions: Dict[str, dict],
        current_prices: Dict[str, float],
        optimizer_weights: Optional[Dict[str, float]] = None,
        target_weights: Optional[Dict[str, float]] = None,
        target_label: str = "el objetivo del optimizer",
    ) -> List[FiredAlert]:
        """
        Full run: universe analysis + portfolio-specific alerts.

        Parameters
        ----------
        scored_tickers    : same as run()
        positions         : {symbol: {"shares", "avg_cost", "sector"}}
        current_prices    : {symbol: price}
        target_weights    : {symbol: target_pct} the portfolio should track —
                            e.g. the user's active retirement plan allocation.
        optimizer_weights : backward-compatible alias for ``target_weights``.
        target_label      : human label for the drift target woven into messages
                            (e.g. "tu Plan de Retiro 'Retiro 2045'").
        """
        fired = self.run(scored_tickers)

        if positions:
            detector = PortfolioAlertDetector()
            candidates = detector.run(
                positions, current_prices,
                optimizer_weights=optimizer_weights,
                target_weights=target_weights,
                target_label=target_label,
            )
            for c in candidates:
                alert = self._fire_candidate(c)
                if alert:
                    fired.append(alert)

            if candidates:
                self._dispatch([a for a in fired if a.alert_type in (
                    AlertType.PORTFOLIO_LOSS,
                    AlertType.PORTFOLIO_DRIFT,
                    AlertType.PORTFOLIO_REBALANCE,
                )])

        return fired

    def check_sorr(
        self,
        sorr_early_drawdown_pct: float,
        horizon_years: int,
        initial_value: float,
    ) -> Optional[FiredAlert]:
        """Fire SORR_HIGH if early drawdown probability exceeds threshold."""
        if sorr_early_drawdown_pct < ALERTS.sorr_high_threshold_pct:
            return None
        symbol = "PORTFOLIO"
        atype = AlertType.SORR_HIGH
        if self._store.is_on_cooldown(atype, symbol):
            return None
        if self._store.is_muted(symbol, atype.value):
            return None
        msg = (
            f"⚠️ SORR elevado: **{sorr_early_drawdown_pct:.1f}%** de probabilidad de drawdown "
            f"severo en los primeros 5 años (horizonte: {horizon_years} años, "
            f"capital: ${initial_value:,.0f}). Revisá la estrategia de retiros."
        )
        context = {
            "sorr_pct": f"{sorr_early_drawdown_pct:.1f}%",
            "threshold_pct": f"{ALERTS.sorr_high_threshold_pct:.1f}%",
            "horizon_years": horizon_years,
            "initial_value": f"${initial_value:,.0f}",
        }
        explanation = _get_ai_explanation(atype.value, symbol, context, AlertSeverity.CRITICAL)
        return self._fire(atype, symbol, msg, AlertSeverity.CRITICAL, explanation)

    def check_goal_risk(
        self,
        goal_name: str,
        prev_prob_pct: float,
        current_prob_pct: float,
        horizon_years: int,
    ) -> Optional[FiredAlert]:
        """Fire GOAL_RISK if probability of achieving a goal dropped significantly."""
        drop = prev_prob_pct - current_prob_pct
        if drop < ALERTS.goal_risk_prob_drop_pct:
            return None
        symbol = f"GOAL:{goal_name}"
        atype = AlertType.GOAL_RISK
        if self._store.is_on_cooldown(atype, symbol):
            return None
        if self._store.is_muted(symbol, atype.value):
            return None
        msg = (
            f"🎯 Meta en riesgo: **{goal_name}** — probabilidad de alcanzarla cayó "
            f"**{drop:.1f}%** ({prev_prob_pct:.1f}% → {current_prob_pct:.1f}%, "
            f"horizonte: {horizon_years} años)"
        )
        context = {
            "goal_name": goal_name,
            "prev_prob_pct": f"{prev_prob_pct:.1f}%",
            "current_prob_pct": f"{current_prob_pct:.1f}%",
            "prob_drop_pct": f"{drop:.1f}%",
            "horizon_years": horizon_years,
        }
        explanation = _get_ai_explanation(atype.value, symbol, context, AlertSeverity.WARNING)
        return self._fire(atype, symbol, msg, AlertSeverity.WARNING, explanation)

    def check_plan_health_degradation(
        self,
        plan_name: str,
        drift_summary: dict,
    ) -> Optional[FiredAlert]:
        """Fire PLAN_HEALTH_DEGRADATION when a plan shows sustained structural drift.

        ``drift_summary`` is the output of
        ``data.plan_context.compute_longitudinal_drift``. Only fires when its
        ``degraded`` flag is set (thresholds live in ``config.HEALTH``).
        """
        if not drift_summary or not drift_summary.get("degraded"):
            return None
        symbol = f"PLAN:{plan_name}"
        atype = AlertType.PLAN_HEALTH_DEGRADATION
        if not self._should_fire(atype, symbol, AlertSeverity.WARNING):
            return None
        reason = drift_summary.get("degraded_reason", "")
        latest = drift_summary.get("latest_drift_pct")
        latest_str = f"{float(latest):+.1f}%" if latest is not None else "n/d"
        msg = (
            f"📉 Plan «{plan_name}»: salud degradada — {reason} "
            f"Deriva actual {latest_str}. Revisá si conviene rebalancear o regenerar el plan."
        )
        context = {
            "plan_name": plan_name,
            "latest_drift_pct": latest_str,
            "n_records": drift_summary.get("n_records"),
            "reason": reason,
        }
        explanation = _get_ai_explanation(atype.value, symbol, context, AlertSeverity.WARNING)
        return self._fire(atype, symbol, msg, AlertSeverity.WARNING, explanation)

    def check_market_drop_coach(
        self,
        portfolio_return_pct: float,
        plan_name: str = "",
        plan_prob_target_pct: Optional[float] = None,
        drop_threshold_pct: Optional[float] = None,
        plan_prob_floor_pct: Optional[float] = None,
    ) -> Optional[FiredAlert]:
        """Proactive coach after a portfolio drop (backlog 12).

        Uses ``data.product_ux.coach_should_fire_on_drop`` (pure predicate) and
        the existing fire/cooldown path. Message reassures when the plan still
        looks OK, or escalates when probability of goal is weak.
        """
        from data.product_ux import coach_should_fire_on_drop

        thr = (
            float(drop_threshold_pct)
            if drop_threshold_pct is not None
            else float(getattr(ALERTS, "coach_drop_threshold_pct", 8.0))
        )
        floor = (
            float(plan_prob_floor_pct)
            if plan_prob_floor_pct is not None
            else float(getattr(ALERTS, "coach_plan_prob_floor_pct", 40.0))
        )
        symbol = f"COACH:{(plan_name or 'portfolio').strip() or 'portfolio'}"
        atype = AlertType.MARKET_DROP_COACH
        on_cd = self._store.is_on_cooldown(atype, symbol)
        decision = coach_should_fire_on_drop(
            portfolio_return_pct=float(portfolio_return_pct),
            drop_threshold_pct=thr,
            plan_prob_target_pct=plan_prob_target_pct,
            plan_prob_floor_pct=floor,
            already_on_cooldown=on_cd,
        )
        if not decision.get("should_fire"):
            return None
        severity = (
            AlertSeverity.WARNING
            if decision.get("severity") == "warning"
            else AlertSeverity.INFO
        )
        if self._store.is_muted(symbol, atype.value):
            return None
        msg = str(decision.get("message") or "")
        context = dict(decision.get("context") or {})
        context["plan_name"] = plan_name
        explanation = _get_ai_explanation(atype.value, symbol, context, severity)
        return self._fire(atype, symbol, msg, severity, explanation)

    # ------------------------------------------------------------------ #
    #  Alert check helpers                                                 #
    # ------------------------------------------------------------------ #

    def _check_signal_change(
        self, symbol: str, company: str,
        prev: str, current: str, score: float, sector: str,
    ) -> Optional[FiredAlert]:
        atype = AlertType.SIGNAL_CHANGE
        severity = AlertSeverity.CRITICAL if current == "SELL" else AlertSeverity.WARNING
        if not self._should_fire(atype, symbol, severity):
            return None
        msg = (
            f"📡 {company} ({symbol}): señal cambió **{prev} → {current}** "
            f"(Score Ajustado: {score:.1f}/100)"
        )
        context = {
            "prev_signal": prev, "current_signal": current,
            "score": f"{score:.1f}/100", "sector": sector,
        }
        explanation = _get_ai_explanation(atype.value, symbol, context, severity)
        return self._fire(atype, symbol, msg, severity, explanation)

    def _check_score_drop(
        self, symbol: str, company: str,
        prev: float, current: float, signal: str, sector: str,
    ) -> Optional[FiredAlert]:
        atype = AlertType.SCORE_DROP
        drop = prev - current
        severity = AlertSeverity.CRITICAL if drop >= 15 else AlertSeverity.WARNING
        if not self._should_fire(atype, symbol, severity):
            return None
        msg = (
            f"📉 {company} ({symbol}): score cayó {drop:.1f} pts "
            f"({prev:.1f} → {current:.1f}/100). Revisar fundamentals."
        )
        context = {
            "prev_score": f"{prev:.1f}", "current_score": f"{current:.1f}",
            "drop_pts": f"{drop:.1f}", "signal": signal, "sector": sector,
        }
        explanation = _get_ai_explanation(atype.value, symbol, context, severity)
        return self._fire(atype, symbol, msg, severity, explanation)

    def _check_score_surge(
        self, symbol: str, company: str,
        prev: float, current: float, signal: str, sector: str,
    ) -> Optional[FiredAlert]:
        atype = AlertType.SCORE_SURGE
        if not self._should_fire(atype, symbol, AlertSeverity.INFO):
            return None
        gain = current - prev
        msg = (
            f"📈 {company} ({symbol}): score subió {gain:.1f} pts "
            f"({prev:.1f} → {current:.1f}/100) · señal: {signal}"
        )
        context = {
            "prev_score": f"{prev:.1f}", "current_score": f"{current:.1f}",
            "gain_pts": f"{gain:.1f}", "signal": signal, "sector": sector,
        }
        explanation = _get_ai_explanation(atype.value, symbol, context, AlertSeverity.INFO)
        return self._fire(atype, symbol, msg, AlertSeverity.INFO, explanation)

    def _check_opportunity(
        self, symbol: str, company: str, signal: str, score: float, sector: str,
    ) -> Optional[FiredAlert]:
        atype = AlertType.OPPORTUNITY
        if not self._should_fire(atype, symbol, AlertSeverity.INFO):
            return None
        emoji = "🟢" if signal == "STRONG_BUY" else "🔵"
        msg = (
            f"{emoji} Nueva oportunidad: **{company} ({symbol})** entró con señal "
            f"**{signal}** (Score: {score:.1f}/100)"
        )
        context = {
            "signal": signal, "score": f"{score:.1f}/100", "sector": sector,
        }
        explanation = _get_ai_explanation(atype.value, symbol, context, AlertSeverity.INFO)
        return self._fire(atype, symbol, msg, AlertSeverity.INFO, explanation)

    def _log_track_record(self, symbol: str, signal: str, score: float) -> None:
        """Persist an opportunity as a recommendation for the track record (Fase 1).

        The alert engine speaks the underscore signal vocabulary ("STRONG_BUY");
        the Decision/track-record vocabulary uses a space ("STRONG BUY"). Price is
        omitted here — the scorer backfills it from historical data at created_at.
        Defensive: never let logging break alert dispatch.
        """
        try:
            from types import SimpleNamespace

            from analysis.track_record import track_record_store

            action = {"STRONG_BUY": "STRONG BUY", "BUY": "BUY"}.get(signal, signal)
            rec = SimpleNamespace(
                symbol=symbol,
                action=action,
                confidence="MEDIUM",
                fundamental_score=float(score),
                technical_signal="",
                rationale=[f"Alerta de oportunidad: entró con señal {signal}"],
            )
            track_record_store.log_recommendation(rec, source="rule_based")
        except Exception as exc:
            logger.debug(f"track_record: opportunity log skipped for {symbol} — {exc}")

    def _check_moat_change(
        self, symbol: str, company: str,
        prev_moat: str, current_moat: str, score: float,
    ) -> Optional[FiredAlert]:
        atype = AlertType.MOAT_CHANGE
        if not self._should_fire(atype, symbol, AlertSeverity.WARNING):
            return None
        msg = (
            f"🏰 {company} ({symbol}): moat degradado "
            f"**{prev_moat} → {current_moat}**. Revisar ventaja competitiva."
        )
        context = {
            "prev_moat": prev_moat, "current_moat": current_moat,
            "score": f"{score:.1f}/100",
        }
        explanation = _get_ai_explanation(atype.value, symbol, context, AlertSeverity.WARNING)
        return self._fire(atype, symbol, msg, AlertSeverity.WARNING, explanation)

    def _fire_candidate(self, c: PortfolioAlertCandidate) -> Optional[FiredAlert]:
        """Convert a PortfolioAlertCandidate into a FiredAlert, respecting cooldowns/mutes/profile."""
        if not self._should_fire(c.alert_type, c.symbol, c.severity):
            return None
        explanation = _get_ai_explanation(c.alert_type.value, c.symbol, c.context, c.severity)
        return self._fire(c.alert_type, c.symbol, c.message, c.severity, explanation)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _should_fire(
        self, atype: AlertType, symbol: str, severity: AlertSeverity
    ) -> bool:
        """Return True if alert passes cooldown, mute and profile-severity checks."""
        if self._store.is_on_cooldown(atype, symbol):
            return False
        if self._store.is_muted(symbol, atype.value):
            logger.debug(f"Alert muted: {atype} / {symbol}")
            return False
        if _SEVERITY_RANK.get(severity, 0) < _SEVERITY_RANK.get(self._min_severity, 0):
            logger.debug(f"Alert below profile threshold: {severity} < {self._min_severity}")
            return False
        return True

    def _fire(
        self,
        atype: AlertType,
        symbol: str,
        message: str,
        severity: AlertSeverity,
        explanation: str = "",
    ) -> FiredAlert:
        self._store.record(atype, symbol, message, severity, explanation)
        self._store.set_cooldown(atype, symbol)
        logger.info(f"Alert [{atype}] {symbol}: {message}")
        return FiredAlert(
            symbol=symbol, alert_type=atype,
            message=message, severity=severity, explanation=explanation,
        )

    def _dispatch(self, alerts: List[FiredAlert]) -> None:
        """Send all alerts as a single digest message through enabled channels."""
        if not (ALERTS.email_enabled or ALERTS.telegram_enabled):
            return

        critical = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        warnings = [a for a in alerts if a.severity == AlertSeverity.WARNING]
        info     = [a for a in alerts if a.severity == AlertSeverity.INFO]

        lines = ["*Retirement Advisor — Resumen de alertas*\n"]
        if critical:
            lines.append("🔴 *CRÍTICAS*")
            lines.extend(f"  • {a.message}" for a in critical)
        if warnings:
            lines.append("\n🟡 *ADVERTENCIAS*")
            lines.extend(f"  • {a.message}" for a in warnings)
        if info:
            lines.append("\n🔵 *INFORMACIÓN*")
            lines.extend(f"  • {a.message}" for a in info)

        body = "\n".join(lines)
        self._notifier.send(body, title=f"Retirement Advisor — {len(alerts)} alertas")
