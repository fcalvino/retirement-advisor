"""Oráculo TELEGRAM-TOKEN: el validador resuelve el token de Telegram como el runtime.

Con un ``.env`` que define ``TELEGRAM_BOT_TOKEN`` y ``TELEGRAM_CHAT_ID`` —los nombres
de ``.env.example``—, cada arranque logueaba «TELEGRAM_CHAT_ID configurado pero falta
TELEGRAM_TOKEN». ``config.AlertConfig`` y ``scripts/test_telegram.py`` leen
``TELEGRAM_BOT_TOKEN`` y caen a ``TELEGRAM_TOKEN``; ``config_validator`` leía sólo el
alias, así que avisaba de una falta que el notifier no tenía. El nombre canónico es
``TELEGRAM_BOT_TOKEN``; el alias se sigue aceptando.
"""

from __future__ import annotations

import pytest

from config_validator import validate_config

TELEGRAM_VARS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID")


def _telegram_issues(monkeypatch, **env):
    for var in TELEGRAM_VARS:
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return [(lvl, msg) for lvl, msg in validate_config() if "TELEGRAM" in msg or "Telegram" in msg]


def _warnings(issues):
    return [msg for lvl, msg in issues if lvl == "warning"]


@pytest.mark.parametrize("token_var", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"])
def test_token_and_chat_id_are_configured_without_warning(monkeypatch, token_var):
    issues = _telegram_issues(monkeypatch, **{token_var: "123:abc", "TELEGRAM_CHAT_ID": "42"})
    assert _warnings(issues) == []
    assert ("info", "Telegram configurado.") in issues


def test_chat_id_without_token_names_the_canonical_variable(monkeypatch):
    warnings = _warnings(_telegram_issues(monkeypatch, TELEGRAM_CHAT_ID="42"))
    assert warnings == ["TELEGRAM_CHAT_ID configurado pero falta TELEGRAM_BOT_TOKEN."]


@pytest.mark.parametrize("token_var", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"])
def test_token_without_chat_id_warns(monkeypatch, token_var):
    warnings = _warnings(_telegram_issues(monkeypatch, **{token_var: "123:abc"}))
    assert warnings == ["TELEGRAM_BOT_TOKEN configurado pero falta TELEGRAM_CHAT_ID."]


def test_neither_variable_says_nothing(monkeypatch):
    assert _telegram_issues(monkeypatch) == []
