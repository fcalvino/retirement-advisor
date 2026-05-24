"""
Notification dispatcher — email (HTML) and Telegram.

Usage:
    notifier = Notifier()
    notifier.send("AAPL signal changed: HOLD → BUY (score 71.3)")
    notifier.send_report(pdf_path)   # attaches PDF to email
"""

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

from config import ALERTS


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body  {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; }}
  .hdr  {{ background: #1B3A6B; color: white; padding: 14px 20px; }}
  .hdr h2 {{ margin: 0; font-size: 18px; }}
  .body {{ padding: 16px 20px; }}
  .alert {{ border-left: 4px solid #17A2B8; padding: 8px 12px;
             margin-bottom: 10px; background: #F5F5F5; border-radius: 3px; }}
  .alert.critical {{ border-color: #DC3545; }}
  .alert.warning  {{ border-color: #FFC107; }}
  .footer {{ font-size: 11px; color: #999; padding: 12px 20px;
              border-top: 1px solid #ddd; }}
</style>
</head>
<body>
<div class="hdr"><h2>📊 {title}</h2></div>
<div class="body">
{body_html}
</div>
<div class="footer">
  Este correo es generado automáticamente por Retirement Advisor.<br>
  No constituye asesoramiento financiero.
</div>
</body>
</html>
"""


def _markdown_to_html(text: str) -> str:
    """Minimal markdown → HTML: bold, line breaks, bullet points."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            lines.append("<br>")
            continue
        # Bold: **text**
        while "**" in line:
            line = line.replace("**", "<b>", 1).replace("**", "</b>", 1)
        # Bullet: "  • text"
        if line.startswith("•") or line.startswith("-"):
            line = f"<li>{line[1:].strip()}</li>"
        lines.append(line)
    return "\n".join(lines)


class Notifier:
    def send(self, message: str, title: str = "Retirement Advisor Alert") -> None:
        """Dispatch alert through all enabled channels."""
        if ALERTS.email_enabled:
            self._send_email(title, message)
        if ALERTS.telegram_enabled:
            self._send_telegram(f"*{title}*\n\n{message}")

    def send_report(self, pdf_path: str, title: str = "Retirement Advisor — Reporte mensual") -> None:
        """Send email with PDF attached. Telegram gets a text-only notification."""
        if ALERTS.email_enabled:
            self._send_email_with_attachment(title, pdf_path)
        if ALERTS.telegram_enabled:
            self._send_telegram(
                f"📄 *{title}*\n\nEl reporte mensual fue generado y enviado por email."
            )

    # ------------------------------------------------------------------ #
    #  Email                                                               #
    # ------------------------------------------------------------------ #

    def _send_email(self, subject: str, body: str) -> None:
        body_html = _markdown_to_html(body)
        html = _HTML_TEMPLATE.format(title=subject, body_html=body_html)
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = ALERTS.email_from
            msg["To"]      = ALERTS.email_to
            msg.attach(MIMEText(body, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))
            self._smtp_send(msg)
            logger.info(f"Email alert sent to {ALERTS.email_to}")
        except Exception as exc:
            logger.error(f"Email alert failed: {exc}")

    def _send_email_with_attachment(self, subject: str, pdf_path: str) -> None:
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            logger.warning(f"PDF not found for email attachment: {pdf_path}")
            return
        try:
            body_html = (
                "<p>Adjunto encontrás el reporte periódico de tu portafolio de retiro.</p>"
                "<p>Este reporte incluye el scorecard completo, señales activas y "
                "sugerencias de rebalanceo.</p>"
            )
            html = _HTML_TEMPLATE.format(title=subject, body_html=body_html)
            msg = MIMEMultipart("mixed")
            msg["Subject"] = subject
            msg["From"]    = ALERTS.email_from
            msg["To"]      = ALERTS.email_to
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText("Adjunto el reporte mensual de Retirement Advisor.", "plain", "utf-8"))
            alt.attach(MIMEText(html, "html", "utf-8"))
            msg.attach(alt)
            with open(pdf_file, "rb") as f:
                pdf_part = MIMEApplication(f.read(), _subtype="pdf")
            pdf_part.add_header(
                "Content-Disposition", "attachment", filename=pdf_file.name
            )
            msg.attach(pdf_part)
            self._smtp_send(msg)
            logger.info(f"Report email sent to {ALERTS.email_to} with {pdf_file.name}")
        except Exception as exc:
            logger.error(f"Report email failed: {exc}")

    def _smtp_send(self, msg: MIMEMultipart) -> None:
        with smtplib.SMTP(ALERTS.smtp_host, ALERTS.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(ALERTS.email_from, ALERTS.smtp_password)
            server.send_message(msg)

    # ------------------------------------------------------------------ #
    #  Telegram                                                            #
    # ------------------------------------------------------------------ #

    def _send_telegram(self, message: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{ALERTS.telegram_token}/sendMessage"
            payload = {
                "chat_id": ALERTS.telegram_chat_id,
                "text":    message,
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
    State stored in memory — use AlertEngine for persistent tracking.
    Kept for backwards compatibility with existing screener code.
    """

    def __init__(self):
        self._previous: dict = {}
        self._notifier = Notifier()

    def check_and_alert(self, symbol: str, new_action: str, score: float) -> Optional[str]:
        prev = self._previous.get(symbol)
        self._previous[symbol] = new_action
        if prev is None:
            return None
        if prev != new_action:
            msg = (
                f"{symbol}: señal cambió {prev} → {new_action} "
                f"(score: {score:.1f}/100)"
            )
            self._notifier.send(msg, title=f"⚡ Cambio de señal: {symbol}")
            logger.info(f"Alert fired: {msg}")
            return msg
        return None
