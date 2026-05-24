"""
Alert detection engine — compares current analysis results against stored
snapshots and fires alerts through the Notifier when thresholds are crossed.

Usage:
    from alerts.engine import AlertEngine
    engine = AlertEngine()
    fired = engine.run(scored_tickers)   # returns list of alert messages

scored_tickers format (same as Optimizer input):
    [{"symbol": "AAPL", "adjusted_score": 72.3, "signal": "BUY",
      "moat_classification": "Wide", ...}, ...]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from loguru import logger

from alerts.notifier import Notifier
from alerts.store import AlertSeverity, AlertStore, AlertType, alert_store
from config import ALERTS

# Score change considered significant (points)
SCORE_CHANGE_THRESHOLD: float = 8.0

# Signals classified as "opportunity" (entered or upgraded)
OPPORTUNITY_SIGNALS = {"STRONG_BUY", "BUY"}

# Moat categories in degradation order (used to detect downgrade)
_MOAT_RANK = {"Wide": 3, "Narrow": 2, "Minimal": 1, "None": 0}


@dataclass
class FiredAlert:
    symbol: str
    alert_type: AlertType
    message: str
    severity: AlertSeverity


class AlertEngine:
    """
    Stateful alert detector. State persists in SQLite via AlertStore.

    First run per ticker: saves baseline only — no alert fired (cold start).
    Subsequent runs: compare against baseline, fire if threshold crossed and
    not on cooldown, then update baseline.
    """

    def __init__(self, store: AlertStore = alert_store) -> None:
        self._store = store
        self._notifier = Notifier()

    def run(self, scored_tickers: List[dict]) -> List[FiredAlert]:
        """
        Analyse scored_tickers, detect threshold crossings, dispatch alerts.
        Returns list of FiredAlert objects for logging/display.
        """
        fired: List[FiredAlert] = []

        for t in scored_tickers:
            symbol      = t.get("symbol", "")
            score       = float(t.get("adjusted_score", 0) or 0)
            signal      = str(t.get("signal", t.get("decision", "")) or "").upper()
            moat_class  = str(t.get("moat_classification", "None") or "None")
            company     = str(t.get("company_name", symbol) or symbol)

            if not symbol:
                continue

            snap = self._store.get_snapshot(symbol)

            if snap is None:
                # First run — save baseline, no alert
                self._store.save_snapshot(symbol, score, signal, moat_class)
                logger.debug(f"AlertEngine: baseline saved for {symbol}")
                continue

            prev_score  = snap.score
            prev_signal = snap.signal
            prev_moat   = snap.moat_class

            # 1 — Signal change
            if signal and prev_signal and signal != prev_signal:
                alert = self._check_signal_change(symbol, company, prev_signal, signal, score)
                if alert:
                    fired.append(alert)

            # 2 — Score drop
            if prev_score - score >= SCORE_CHANGE_THRESHOLD:
                alert = self._check_score_drop(symbol, company, prev_score, score)
                if alert:
                    fired.append(alert)

            # 3 — Score surge (new opportunity)
            elif score - prev_score >= SCORE_CHANGE_THRESHOLD and signal in OPPORTUNITY_SIGNALS:
                alert = self._check_score_surge(symbol, company, prev_score, score, signal)
                if alert:
                    fired.append(alert)

            # 4 — Opportunity: new BUY/STRONG_BUY entry
            if signal in OPPORTUNITY_SIGNALS and prev_signal not in OPPORTUNITY_SIGNALS:
                alert = self._check_opportunity(symbol, company, signal, score)
                if alert:
                    fired.append(alert)

            # 5 — Moat downgrade
            if _MOAT_RANK.get(moat_class, 0) < _MOAT_RANK.get(prev_moat, 0):
                alert = self._check_moat_change(symbol, company, prev_moat, moat_class)
                if alert:
                    fired.append(alert)

            # Update snapshot to current values
            self._store.save_snapshot(symbol, score, signal, moat_class)

        # Dispatch all fired alerts
        if fired:
            self._dispatch(fired)

        logger.info(f"AlertEngine: {len(scored_tickers)} tickers checked, {len(fired)} alerts fired")
        return fired

    # ------------------------------------------------------------------ #
    #  Alert check helpers                                                 #
    # ------------------------------------------------------------------ #

    def _check_signal_change(
        self, symbol: str, company: str,
        prev: str, current: str, score: float,
    ) -> FiredAlert | None:
        atype = AlertType.SIGNAL_CHANGE
        if self._store.is_on_cooldown(atype, symbol):
            return None
        severity = AlertSeverity.CRITICAL if current == "SELL" else AlertSeverity.WARNING
        msg = (
            f"📡 {company} ({symbol}): señal cambió **{prev} → {current}** "
            f"(Score Ajustado: {score:.1f}/100)"
        )
        return self._fire(atype, symbol, msg, severity)

    def _check_score_drop(
        self, symbol: str, company: str, prev: float, current: float
    ) -> FiredAlert | None:
        atype = AlertType.SCORE_DROP
        if self._store.is_on_cooldown(atype, symbol):
            return None
        drop = prev - current
        severity = AlertSeverity.CRITICAL if drop >= 15 else AlertSeverity.WARNING
        msg = (
            f"📉 {company} ({symbol}): score cayó {drop:.1f} pts "
            f"({prev:.1f} → {current:.1f}/100). Revisar fundamentals."
        )
        return self._fire(atype, symbol, msg, severity)

    def _check_score_surge(
        self, symbol: str, company: str,
        prev: float, current: float, signal: str,
    ) -> FiredAlert | None:
        atype = AlertType.SCORE_SURGE
        if self._store.is_on_cooldown(atype, symbol):
            return None
        gain = current - prev
        msg = (
            f"📈 {company} ({symbol}): score subió {gain:.1f} pts "
            f"({prev:.1f} → {current:.1f}/100) · señal: {signal}"
        )
        return self._fire(atype, symbol, msg, AlertSeverity.INFO)

    def _check_opportunity(
        self, symbol: str, company: str, signal: str, score: float
    ) -> FiredAlert | None:
        atype = AlertType.OPPORTUNITY
        if self._store.is_on_cooldown(atype, symbol):
            return None
        emoji = "🟢" if signal == "STRONG_BUY" else "🔵"
        msg = (
            f"{emoji} Nueva oportunidad: **{company} ({symbol})** entró con señal "
            f"**{signal}** (Score: {score:.1f}/100)"
        )
        return self._fire(atype, symbol, msg, AlertSeverity.INFO)

    def _check_moat_change(
        self, symbol: str, company: str, prev_moat: str, current_moat: str
    ) -> FiredAlert | None:
        atype = AlertType.MOAT_CHANGE
        if self._store.is_on_cooldown(atype, symbol):
            return None
        msg = (
            f"🏰 {company} ({symbol}): moat degradado "
            f"**{prev_moat} → {current_moat}**. Revisar ventaja competitiva."
        )
        return self._fire(atype, symbol, msg, AlertSeverity.WARNING)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _fire(
        self,
        atype: AlertType,
        symbol: str,
        message: str,
        severity: AlertSeverity,
    ) -> FiredAlert:
        self._store.record(atype, symbol, message, severity)
        self._store.set_cooldown(atype, symbol)
        logger.info(f"Alert [{atype}] {symbol}: {message}")
        return FiredAlert(symbol=symbol, alert_type=atype, message=message, severity=severity)

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
