"""SMTP-GUARD: an incomplete email config never opens an SMTP session.

QA on 2026-09-25: with ``EMAIL_FROM`` set and ``SMTP_PASSWORD`` empty,
«▶ Ejecutar análisis ahora» logged in to Gmail with an empty password
(``535 BadCredentials``), although ``config_validator`` had already reported
the config as incomplete. ``email_enabled`` only looked at ``EMAIL_FROM``.

No network: ``smtplib.SMTP`` is a mock and the config is replaced.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from alerts import notifier as notifier_mod
from config import ALERTS

_FULL = dict(email_enabled=True, email_from="me@example.com", email_to="me@example.com",
             smtp_password="app-password", telegram_enabled=False)


@pytest.fixture
def smtp(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(notifier_mod.smtplib, "SMTP", fake)
    return fake


def _use(monkeypatch, **overrides):
    monkeypatch.setattr(notifier_mod, "ALERTS", replace(ALERTS, **{**_FULL, **overrides}))


@pytest.mark.parametrize("missing", ["smtp_password", "email_to", "email_from"])
def test_incomplete_email_config_never_opens_smtp(monkeypatch, smtp, tmp_path, missing):
    _use(monkeypatch, **{missing: ""})
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    n = notifier_mod.Notifier()
    n.send("alerta")
    n.send_report(str(pdf))
    smtp.assert_not_called()


def test_complete_email_config_still_sends(monkeypatch, smtp):
    _use(monkeypatch)
    notifier_mod.Notifier().send("alerta")
    smtp.assert_called_once()
