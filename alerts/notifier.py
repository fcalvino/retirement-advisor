"""
Alert system — sends signal-change notifications via email or Telegram.

Usage:
    notifier = Notifier()
    notifier.send("AAPL signal changed: HOLD → BUY (score 71.3)")
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
from loguru import logger

from config import ALERTS


class Notifier:
    def send(self, message: str, title: str = "Retirement Advisor Alert") -> None:
        """Dispatch alert through all enabled channels."""
        if ALERTS.email_enabled:
            self._send_email(title, message)
        if ALERTS.telegram_enabled:
            self._send_telegram(f"*{title}*\n\n{message}")

    def _send_email(self, subject: str, body: str) -> None:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = ALERTS.email_from
            msg["To"] = ALERTS.email_to
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP(ALERTS.smtp_host, ALERTS.smtp_port) as server:
                server.starttls()
                server.login(ALERTS.email_from, ALERTS.smtp_password)
                server.send_message(msg)
            logger.info(f"Email alert sent to {ALERTS.email_to}")
        except Exception as exc:
            logger.error(f"Email alert failed: {exc}")

    def _send_telegram(self, message: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{ALERTS.telegram_token}/sendMessage"
            payload = {
                "chat_id": ALERTS.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info("Telegram alert sent")
        except Exception as exc:
            logger.error(f"Telegram alert failed: {exc}")


class SignalMonitor:
    """
    Tracks previous decisions and fires alerts when signals change.
    State is stored in memory — restart resets it (by design, avoids false alerts
    from cache cold-start).
    """

    def __init__(self):
        self._previous: dict = {}
        self._notifier = Notifier()

    def check_and_alert(self, symbol: str, new_action: str, score: float) -> Optional[str]:
        """
        Compare new decision against last known decision.
        Returns alert message if changed, None otherwise.
        """
        prev = self._previous.get(symbol)
        self._previous[symbol] = new_action

        if prev is None:
            return None  # First run — no baseline to compare against

        if prev != new_action:
            msg = (
                f"{symbol}: signal changed {prev} → {new_action} "
                f"(fundamental score: {score:.1f}/100)"
            )
            self._notifier.send(msg, title=f"⚡ Signal Change: {symbol}")
            logger.info(f"Alert fired: {msg}")
            return msg

        return None
