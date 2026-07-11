"""
Portfolio-specific alert detectors (Phase 6).

Detects:
  PORTFOLIO_LOSS      — position P&L < -threshold% vs avg_cost
  PORTFOLIO_DRIFT     — individual position weight deviates > threshold from optimizer target
  PORTFOLIO_REBALANCE — aggregate portfolio drift > threshold (global rebalance signal)

Usage:
    from alerts.portfolio_alerts import PortfolioAlertDetector
    detector = PortfolioAlertDetector()
    alerts = detector.run(portfolio, optimizer_weights)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from loguru import logger

from alerts.store import AlertSeverity, AlertType
from config import ALERTS


@dataclass
class PortfolioAlertCandidate:
    symbol: str
    alert_type: AlertType
    message: str
    severity: AlertSeverity
    context: dict  # passed to AI explanation prompt


class PortfolioAlertDetector:
    """
    Stateless detector — compares current portfolio positions against cost basis
    and optimizer target weights. State management (cooldowns, mutes) is handled
    by AlertEngine after receiving the candidates.
    """

    def run(
        self,
        positions: Dict[str, dict],
        current_prices: Dict[str, float],
        optimizer_weights: Optional[Dict[str, float]] = None,
        target_weights: Optional[Dict[str, float]] = None,
        target_label: str = "el objetivo del optimizer",
    ) -> List[PortfolioAlertCandidate]:
        """
        Parameters
        ----------
        positions : dict
            {symbol: {"shares": float, "avg_cost": float, "sector": str}}
        current_prices : dict
            {symbol: current_market_price}
        target_weights : dict | None
            {symbol: target_weight_pct (0–100)} the portfolio should track —
            e.g. the user's active retirement plan allocation. If None, drift
            alerts are skipped.
        optimizer_weights : dict | None
            Backward-compatible alias for ``target_weights`` (the last optimizer
            run). Used only when ``target_weights`` is not provided.
        target_label : str
            Human label for the drift target, woven into the alert message
            (e.g. "tu Plan de Retiro 'Retiro 2045'").

        Returns
        -------
        List of PortfolioAlertCandidate — unfiltered (engine handles mutes/cooldowns).
        """
        # target_weights is the generalized parameter; optimizer_weights is the
        # legacy alias kept so existing callers keep working unchanged.
        weights = target_weights if target_weights is not None else optimizer_weights

        candidates: List[PortfolioAlertCandidate] = []

        # --- Compute portfolio total value ---
        total_value = 0.0
        position_values: Dict[str, float] = {}
        for sym, pos in positions.items():
            price = current_prices.get(sym, 0.0)
            val = pos.get("shares", 0) * price
            position_values[sym] = val
            total_value += val

        # --- Individual position checks ---
        for sym, pos in positions.items():
            avg_cost = float(pos.get("avg_cost", 0) or 0)
            shares = float(pos.get("shares", 0) or 0)
            current_price = current_prices.get(sym, 0.0)
            sector = pos.get("sector", "Unknown")

            if avg_cost <= 0 or shares <= 0 or current_price <= 0:
                continue

            pnl_pct = (current_price - avg_cost) / avg_cost * 100

            # PORTFOLIO_LOSS
            if pnl_pct < -ALERTS.portfolio_loss_threshold_pct:
                severity = (
                    AlertSeverity.CRITICAL if pnl_pct < -(ALERTS.portfolio_loss_threshold_pct * 1.5)
                    else AlertSeverity.WARNING
                )
                msg = (
                    f"📉 {sym}: posición en pérdida **{pnl_pct:.1f}%** "
                    f"(precio actual ${current_price:.2f} vs costo promedio ${avg_cost:.2f})"
                )
                candidates.append(PortfolioAlertCandidate(
                    symbol=sym,
                    alert_type=AlertType.PORTFOLIO_LOSS,
                    message=msg,
                    severity=severity,
                    context={
                        "pnl_pct": f"{pnl_pct:.1f}%",
                        "current_price": f"${current_price:.2f}",
                        "avg_cost": f"${avg_cost:.2f}",
                        "shares": f"{shares:.2f}",
                        "sector": sector,
                    },
                ))

            # PORTFOLIO_DRIFT (only if target weights are available)
            if weights and total_value > 0:
                target_pct = weights.get(sym, 0.0)
                current_pct = (position_values.get(sym, 0.0) / total_value * 100) if total_value > 0 else 0.0
                drift = abs(current_pct - target_pct)

                if drift > ALERTS.portfolio_drift_threshold_pct:
                    direction = "excede" if current_pct > target_pct else "está por debajo de"
                    msg = (
                        f"⚖️ {sym}: peso actual **{current_pct:.1f}%** {direction} "
                        f"{target_label} **{target_pct:.1f}%** "
                        f"(drift: {drift:.1f}%)"
                    )
                    candidates.append(PortfolioAlertCandidate(
                        symbol=sym,
                        alert_type=AlertType.PORTFOLIO_DRIFT,
                        message=msg,
                        severity=AlertSeverity.WARNING,
                        context={
                            "current_weight_pct": f"{current_pct:.1f}%",
                            "target_weight_pct": f"{target_pct:.1f}%",
                            "drift_pct": f"{drift:.1f}%",
                            "sector": sector,
                        },
                    ))

        # --- Aggregate drift: PORTFOLIO_REBALANCE ---
        if weights and total_value > 0:
            total_drift = 0.0
            for sym, target_pct in weights.items():
                current_pct = (position_values.get(sym, 0.0) / total_value * 100) if total_value > 0 else 0.0
                total_drift += abs(current_pct - target_pct)
            # Halve because each deviation is counted twice (over + under)
            avg_drift = total_drift / 2

            if avg_drift > ALERTS.portfolio_rebalance_threshold_pct:
                msg = (
                    f"🔄 Portafolio: deriva total **{avg_drift:.1f}%** de {target_label}. "
                    f"Considerá rebalancear ({len(positions)} posiciones analizadas)."
                )
                candidates.append(PortfolioAlertCandidate(
                    symbol="PORTFOLIO",
                    alert_type=AlertType.PORTFOLIO_REBALANCE,
                    message=msg,
                    severity=AlertSeverity.WARNING,
                    context={
                        "total_drift_pct": f"{avg_drift:.1f}%",
                        "positions_count": len(positions),
                        "threshold_pct": f"{ALERTS.portfolio_rebalance_threshold_pct:.1f}%",
                    },
                ))

        logger.debug(
            f"PortfolioAlertDetector: {len(positions)} positions → "
            f"{len(candidates)} candidates"
        )
        return candidates
