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

import sys
import time
from datetime import datetime
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def job_alert_check() -> None:
    logger.info("=== Alert check started ===")
    try:
        scored = _run_screener_for_alerts()
        if not scored:
            logger.warning("Alert check: no tickers analysed — skipping")
            return
        engine = AlertEngine()
        fired  = engine.run(scored)
        logger.info(f"Alert check complete — {len(fired)} alerts fired")
    except Exception as exc:
        logger.error(f"Alert check failed: {exc}")
    logger.info("=== Alert check finished ===")


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
    logger.info("Retirement Advisor Scheduler starting…")
    logger.info(f"  Alert interval : every {REPORT.alert_check_interval_hours}h")
    logger.info(f"  Monthly report : day {REPORT.report_day_of_month} of each month at 08:00")
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

    # Run alert check immediately on startup
    logger.info("Running initial alert check on startup…")
    job_alert_check()

    logger.info("Scheduler running — press Ctrl+C to stop")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
