"""
Portfolio-specific alert detectors (Phase 6).

Detects:
  PORTFOLIO_LOSS      — position P&L < -threshold% vs avg_cost
  PORTFOLIO_DRIFT     — a symbol's weight deviates > threshold from the target
  PORTFOLIO_REBALANCE — aggregate portfolio drift > threshold (global rebalance signal)

Drift is measured over the **union** of the target and what is actually held
(U2-3), through the canonical ``data.plan_context.drift_breakdown`` — the same
arithmetic the Portfolio page and ``compute_alignment_trades`` use, so the mail
and the screen can no longer disagree. It is independent of ``avg_cost`` (a
position with no cost basis loaded still drifts) and it refuses to run at all
when any tracked position has no usable price: an unpriced position is
*unknown*, not 0 %, and treating it as 0 deflates the total and inflates every
other weight.

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


def _as_float(value) -> float:
    """Best-effort float — missing / malformed inputs collapse to 0.0.

    Callers upstream are inconsistent: the scheduler may omit a quote entirely,
    a stored position may carry ``None`` shares. Both must read as "no usable
    number" without raising.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
    and target weights. State management (cooldowns, mutes) is handled
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
            {symbol: current_market_price}. A missing key or a non-positive
            price means *unknown*, never zero — see the coverage gate below.
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

        # --- Value the book, honestly (U2-3) ---------------------------- #
        # A position we cannot price is set aside, not valued at 0: a zero
        # would shrink total_value and inflate every other position's weight,
        # then fire drift alerts about weights nobody can actually know.
        priced_values: Dict[str, float] = {}
        unpriced: List[str] = []
        total_value = 0.0
        for sym, pos in positions.items():
            shares = _as_float(pos.get("shares"))
            price = _as_float(current_prices.get(sym))
            if shares <= 0:
                continue  # nothing held — not a coverage gap
            if price <= 0:
                unpriced.append(sym)
                continue
            priced_values[sym] = shares * price
            total_value += priced_values[sym]

        # --- PORTFOLIO_LOSS (per position, needs a cost basis) ---------- #
        for sym, pos in positions.items():
            avg_cost = _as_float(pos.get("avg_cost"))
            shares = _as_float(pos.get("shares"))
            current_price = _as_float(current_prices.get(sym))
            sector = pos.get("sector", "Unknown")

            if avg_cost <= 0 or shares <= 0 or current_price <= 0:
                continue

            pnl_pct = (current_price - avg_cost) / avg_cost * 100

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

        # --- Drift: PORTFOLIO_DRIFT + PORTFOLIO_REBALANCE (U2-3) -------- #
        # Its own block, no longer nested under the P&L loop: drift is a
        # statement about weights and must not require avg_cost.
        if unpriced and weights:
            logger.warning(
                f"PortfolioAlertDetector: sin precio para {', '.join(sorted(unpriced))} — "
                "los pesos reales son desconocidos; se omiten PORTFOLIO_DRIFT y "
                "PORTFOLIO_REBALANCE en esta corrida"
            )

        if weights and total_value > 0 and not unpriced:
            from data.plan_context import drift_breakdown

            actual = {s: v / total_value * 100.0 for s, v in priced_values.items()}
            breakdown = drift_breakdown(weights, actual)

            for row in breakdown["rows"]:
                sym = row["symbol"]
                target_pct = row["target_pct"]
                current_pct = row["actual_pct"]
                drift = abs(row["drift_pct"])

                if drift <= ALERTS.portfolio_drift_threshold_pct:
                    continue

                sector = (positions.get(sym) or {}).get("sector", "Unknown")
                if sym not in priced_values:
                    # In the plan, not held at all — reachable only since U2-3,
                    # because the loop used to iterate `positions`.
                    msg = (
                        f"⚖️ {sym}: no tenés posición; {target_label} pide "
                        f"**{target_pct:.1f}%** (drift: {drift:.1f}%)"
                    )
                else:
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

            total_drift = breakdown["total_drift_pct"]
            if total_drift > ALERTS.portfolio_rebalance_threshold_pct:
                msg = (
                    f"🔄 Portafolio: deriva total **{total_drift:.1f}%** de {target_label}. "
                    f"Considerá rebalancear ({breakdown['n_evaluated']} símbolos analizados)."
                )
                candidates.append(PortfolioAlertCandidate(
                    symbol="PORTFOLIO",
                    alert_type=AlertType.PORTFOLIO_REBALANCE,
                    message=msg,
                    severity=AlertSeverity.WARNING,
                    context={
                        "total_drift_pct": f"{total_drift:.1f}%",
                        "positions_count": len(priced_values),
                        "n_evaluated": breakdown["n_evaluated"],
                        "threshold_pct": f"{ALERTS.portfolio_rebalance_threshold_pct:.1f}%",
                    },
                ))

        logger.debug(
            f"PortfolioAlertDetector: {len(positions)} positions "
            f"({len(unpriced)} sin precio) → {len(candidates)} candidates"
        )
        return candidates
