#!/usr/bin/env python3
"""
Background scheduler — runs alert checks and monthly PDF reports.

Run from project root:
    python scripts/run_scheduler.py

Environment variables (via .env):
    ALERT_INTERVAL_HOURS   — how often to run alert checks (default: 24)
    REPORT_DAY             — day of month to generate PDF report (default: 1)
    AI_ENABLED             — set to "true" to use AI for moat in scheduler runs

The scheduler performs two jobs:
  1. Alert check (every ALERT_INTERVAL_HOURS): runs the screener on the full
     universe, feeds results into AlertEngine, dispatches notifications.
  2. Monthly report (on REPORT_DAY at 08:00): generates a full PDF report
     and sends it via email/Telegram.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

import _bootstrap  # noqa: F401
import schedule
from loguru import logger

from alerts.engine import AlertEngine
from alerts.notifier import Notifier
from alerts.reporter import ReportGenerator
from config import AI_CONFIG, ALERTS, DEFAULT_TICKERS, REPORT


def _run_screener_for_alerts() -> list[dict]:
    """Run fundamental analysis on the default universe and return scored tickers."""
    from analysis.strategy import full_analysis

    ai_cfg = AI_CONFIG if AI_CONFIG.enabled else None
    scored = []
    logger.info(f"Scheduler: analysing {len(DEFAULT_TICKERS)} tickers…")

    for sym in DEFAULT_TICKERS:
        try:
            fund, _tech, dec = full_analysis(sym, ai_config=ai_cfg)
            scored.append({
                "symbol":              sym,
                "company_name":        fund.company_name,
                "adjusted_score":      fund.adjusted_score,
                "total_score":         fund.total_score,
                "fundamental_score":   getattr(fund, "total_score", 0),
                "moat_bonus":          getattr(fund, "moat_bonus", 0),
                "signal":              getattr(dec, "action", ""),
                "moat_classification": getattr(fund, "moat_classification", "None"),
                "moat_score":          getattr(fund, "moat_score", 0),
                "dividend_yield":      fund.dividend_yield or 0,
                "sector":              fund.sector or "Unknown",
            })
        except Exception as exc:
            logger.error(f"Scheduler: failed to analyse {sym}: {exc}")

    logger.info(f"Scheduler: {len(scored)} tickers analysed")
    return scored


def _active_plan_drift_inputs():
    """Resolve the active retirement plan + live portfolio for drift checks.

    Returns (positions, current_prices, target_weights, target_label) or None
    when there's no active plan / no tracked positions. Drift is measured
    against the plan the user *activated* (Fase C) — not an ephemeral optimizer
    run — so alerts say "te alejaste de tu Plan de Retiro 'X'".
    """
    try:
        from data.fetcher import get_info
        from data.plan_context import get_active_plan
        from portfolio.tracker import Portfolio

        plan = get_active_plan()
        if plan is None:
            return None

        portfolio = Portfolio()
        if not portfolio.positions:
            return None

        positions = {
            sym: {"shares": pos.shares, "avg_cost": pos.avg_cost,
                  "sector": getattr(pos, "sector", "Unknown")}
            for sym, pos in portfolio.positions.items()
        }
        current_prices: dict[str, float] = {}
        for sym in positions:
            try:
                info = get_info(sym)
                px = float(
                    info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
                )
            except Exception as exc:
                logger.debug(f"Scheduler drift: price lookup failed for {sym}: {exc}")
                continue
            # U2-3: a missing quote leaves the key absent. Writing 0.0 made the
            # detector read the position as 0 % of the portfolio and inflated
            # every other weight; "unknown" must look like "unknown".
            if px > 0:
                current_prices[sym] = px
            else:
                logger.debug(f"Scheduler drift: no usable quote for {sym}")

        target_weights = plan.target_weights()
        if not target_weights:
            return None
        label = f"tu Plan de Retiro «{plan.name}»"
        return positions, current_prices, target_weights, label
    except Exception as exc:
        logger.error(f"Scheduler: could not resolve active plan drift inputs: {exc}")
        return None


def job_score_track_record() -> None:
    """Score recommendations whose horizon has elapsed.

    Nothing ran this before: the scorer existed and was wired to nothing, so of the
    three configured horizons (30/90/252 days) only the 30-day one ever had data —
    and only because someone typed the command by hand. The 252-day horizon is the
    one that matches a retirement product, and it fills in only if this runs every
    day for a year.

    Idempotent by construction (an outcome is written once per recommendation and
    horizon), so a missed day costs nothing and a repeated day does nothing.
    """
    logger.info("=== Track record scoring started ===")
    try:
        from analysis.track_record_scorer import score_due_recommendations

        result = score_due_recommendations()
        logger.info(
            f"Track record: scored={result.get('scored', 0)} "
            f"skipped={result.get('skipped', 0)}"
        )
    except Exception as exc:
        logger.error(f"Track record scoring failed: {exc}")


def job_alert_check() -> None:
    logger.info("=== Alert check started ===")
    try:
        scored = _run_screener_for_alerts()
        if not scored:
            logger.warning("Alert check: no tickers analysed — skipping")
            return
        engine = AlertEngine()

        drift_inputs = None
        try:
            drift_inputs = _active_plan_drift_inputs()
        except Exception as exc:
            logger.debug(f"drift inputs unavailable: {exc}")
            drift_inputs = None
        if drift_inputs is not None:
            positions, current_prices, target_weights, label = drift_inputs
            logger.info(f"Alert check: measuring portfolio drift vs {label}")
            fired = engine.run_with_portfolio(
                scored, positions, current_prices,
                target_weights=target_weights, target_label=label,
            )
        else:
            fired = engine.run(scored)

        # Fase H.2 — longitudinal plan health: optionally record a health
        # snapshot for the active plan and fire a degradation alert if the
        # plan has been drifting structurally over recent records.
        try:
            _check_plan_health(engine)
        except Exception as exc:
            logger.error(f"Plan-health check failed: {exc}")

        # SORR_HIGH / GOAL_RISK from the active plan's last MC summary
        # (persisted when the plan was saved; prev goal-prob via alert snapshots).
        try:
            _check_plan_mc_alerts(engine)
        except Exception as exc:
            logger.error(f"Plan MC alert check failed: {exc}")

        # Backlog 12 — proactive coach after portfolio drop
        try:
            _check_market_drop_coach(engine, drift_inputs)
        except Exception as exc:
            logger.error(f"Market-drop coach check failed: {exc}")

        logger.info(f"Alert check complete — {len(fired)} alerts fired")
    except Exception as exc:
        logger.error(f"Alert check failed: {exc}")
    logger.info("=== Alert check finished ===")


def _check_market_drop_coach(engine, drift_inputs) -> None:
    """Proactive coach when the tracked portfolio has dropped hard (backlog 12).

    Uses positions + current prices when available; falls back to weighted
    plan drift from the active plan refresh metrics.
    """
    from data.plan_context import get_active_plan

    plan = get_active_plan()
    plan_name = getattr(plan, "name", "") if plan is not None else ""
    prob = None
    if plan is not None:
        mc = getattr(plan, "mc_summary", None) or {}
        if mc.get("prob_target_pct") is not None:
            try:
                prob = float(mc["prob_target_pct"])
            except (TypeError, ValueError):
                prob = None

    portfolio_return_pct = None
    if drift_inputs is not None:
        positions, current_prices, _tw, _label = drift_inputs
        cost = 0.0
        value = 0.0
        for sym, pos in (positions or {}).items():
            try:
                shares = float(pos.get("shares") or 0)
                avg = float(pos.get("avg_cost") or 0)
                px = float((current_prices or {}).get(sym) or 0)
            except (TypeError, ValueError):
                continue
            cost += shares * avg
            value += shares * px
        if cost > 0:
            portfolio_return_pct = (value / cost - 1.0) * 100.0

    if portfolio_return_pct is None and plan is not None:
        refreshed = getattr(plan, "refreshed_metrics", None) or {}
        summary = refreshed.get("summary") if isinstance(refreshed, dict) else None
        if isinstance(summary, dict) and summary.get("weighted_delta_pct") is not None:
            try:
                portfolio_return_pct = float(summary["weighted_delta_pct"])
            except (TypeError, ValueError):
                portfolio_return_pct = None

    if portfolio_return_pct is None:
        return

    fired = engine.check_market_drop_coach(
        portfolio_return_pct=portfolio_return_pct,
        plan_name=plan_name or "portfolio",
        plan_prob_target_pct=prob,
    )
    if fired is not None:
        logger.info(f"Market-drop coach fired ({portfolio_return_pct:.1f}%).")


def _check_plan_health(engine) -> None:
    """Record + evaluate longitudinal health of the active plan (Fase H.2).

    No-op unless there is an active plan. Recording is gated behind
    ``HEALTH.auto_record``; degradation alerts always evaluate the existing
    history so a previously recorded trend can still fire.
    """
    from config import HEALTH

    if not HEALTH.enabled:
        return

    from data.plan_context import (
        compute_longitudinal_drift,
        get_active_plan,
        get_plan_health_history,
        plan_price_lookup,
        record_plan_health,
    )

    plan = get_active_plan()
    if plan is None:
        return

    if HEALTH.auto_record:
        record_plan_health(
            plan, plan_price_lookup, source="scheduler",
            min_days_between=HEALTH.min_days_between_records,
        )

    drift = compute_longitudinal_drift(get_plan_health_history(plan.id))
    fired = engine.check_plan_health_degradation(plan.name, drift)
    if fired is not None:
        logger.info(f"Plan-health degradation alert fired for «{plan.name}».")


def _check_plan_mc_alerts(engine) -> None:
    """Fire SORR_HIGH / GOAL_RISK from the active plan's saved Monte Carlo summary.

    SORR uses ``mc_summary.sorr_early_drawdown_pct`` (persisted at plan save).
    GOAL_RISK tracks ``prob_target_pct`` across runs via the alert snapshot store
    (symbol ``GOAL:<plan_name>``, score field = last known probability).
    """
    from data.plan_context import get_active_plan

    plan = get_active_plan()
    if plan is None:
        return
    mc = getattr(plan, "mc_summary", None) or {}
    if not mc:
        return

    sorr = mc.get("sorr_early_drawdown_pct")
    if sorr is not None:
        try:
            sorr_f = float(sorr)
            horizon = int(mc.get("horizon_years") or 0)
            initial = float(mc.get("initial_value") or 0.0)
            fired = engine.check_sorr(sorr_f, horizon, initial)
            if fired is not None:
                logger.info(f"SORR_HIGH alert fired for plan «{plan.name}» ({sorr_f:.1f}%).")
        except (TypeError, ValueError) as exc:
            logger.debug(f"SORR check skipped — {exc}")

    prob = mc.get("prob_target_pct")
    if prob is None:
        return
    try:
        current_prob = float(prob)
    except (TypeError, ValueError):
        return

    goal_symbol = f"GOAL:{plan.name}"
    store = engine._store
    prev_snap = store.get_snapshot(goal_symbol)
    if prev_snap is None:
        # Seed baseline; only fire on subsequent drops.
        store.save_snapshot(goal_symbol, current_prob, "GOAL", "")
        return

    prev_prob = float(prev_snap.score)
    horizon = int(mc.get("horizon_years") or 0)
    fired = engine.check_goal_risk(plan.name, prev_prob, current_prob, horizon)
    store.save_snapshot(goal_symbol, current_prob, "GOAL", "")
    if fired is not None:
        logger.info(
            f"GOAL_RISK alert fired for plan «{plan.name}» "
            f"({prev_prob:.1f}% → {current_prob:.1f}%)."
        )


def job_monthly_report() -> None:
    logger.info("=== Monthly report generation started ===")
    try:
        scored = _run_screener_for_alerts()
        if not scored:
            logger.warning("Monthly report: no tickers — skipping")
            return

        gen  = ReportGenerator()
        path = gen.generate(scored)

        if ALERTS.email_enabled or ALERTS.telegram_enabled:
            Notifier().send_report(
                path,
                title=f"Retirement Advisor — Reporte {datetime.now().strftime('%B %Y').capitalize()}",
            )
        logger.info(f"Monthly report complete: {path}")
    except Exception as exc:
        logger.error(f"Monthly report failed: {exc}")
    logger.info("=== Monthly report generation finished ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="Retirement Advisor alert scheduler")
    parser.add_argument("--once", action="store_true", help="Run one alert check and exit (for cron)")
    parser.add_argument("--quiet", action="store_true", help="Suppress INFO logs (WARNING+ only)")
    args = parser.parse_args()

    if args.quiet:
        logger.remove()
        logger.add(sys.stderr, level="WARNING")

    if args.once:
        logger.info("=== One-shot alert check (--once) ===")
        job_alert_check()
        return

    logger.info("Retirement Advisor Scheduler starting…")
    logger.info(f"  Alert interval : every {REPORT.alert_check_interval_hours}h")
    logger.info(f"  Monthly report : day {REPORT.report_day_of_month} of each month at 08:00")
    logger.info("  Track record   : daily at 07:00")
    logger.info(f"  Email enabled  : {ALERTS.email_enabled}")
    logger.info(f"  Telegram enabled: {ALERTS.telegram_enabled}")

    # Schedule alert checks
    schedule.every(REPORT.alert_check_interval_hours).hours.do(job_alert_check)

    # Schedule monthly report on the configured day at 08:00
    schedule.every().day.at("08:00").do(
        lambda: job_monthly_report()
        if datetime.now().day == REPORT.report_day_of_month
        else None
    )

    # Score the track record daily — the horizons only fill in if this runs.
    schedule.every().day.at("07:00").do(job_score_track_record)

    # Run alert check immediately on startup
    logger.info("Running initial alert check on startup…")
    job_alert_check()

    logger.info("Scheduler running — press Ctrl+C to stop")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
