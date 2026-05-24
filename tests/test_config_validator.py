"""Tests for config_validator.validate_config() — AI section focus."""

import pytest

from config_validator import validate_config


def _ai_issues(monkeypatch, **env):
    """Run validate_config() with a clean environment plus the given overrides."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_OAUTH_ENABLED", raising=False)
    monkeypatch.delenv("XAI_AUTH_TOKEN", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return [(lvl, msg) for lvl, msg in validate_config() if "AI" in msg or "rule-based" in msg or "proveedor" in msg or "OAuth" in msg or "inválida" in msg or "_API_KEY" in msg]


# ------------------------------------------------------------------ #
#  AI disabled                                                         #
# ------------------------------------------------------------------ #

class TestAIDisabled:
    def test_disabled_returns_info(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="false")
        assert any(lvl == "info" and "rule-based" in msg for lvl, msg in issues)

    def test_disabled_no_warnings(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="false")
        assert not any(lvl == "warning" for lvl, msg in issues)


# ------------------------------------------------------------------ #
#  API Key mode (traditional)                                          #
# ------------------------------------------------------------------ #

class TestAPIKeyMode:
    def test_claude_with_valid_key(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="claude",
                            ANTHROPIC_API_KEY="sk-ant-" + "x" * 30)
        assert any(lvl == "info" and "API Key" in msg for lvl, msg in issues)

    def test_openai_with_valid_key(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="openai",
                            OPENAI_API_KEY="sk-" + "x" * 40)
        assert any(lvl == "info" and "API Key" in msg for lvl, msg in issues)

    def test_xai_with_valid_api_key_no_oauth(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="xai",
                            XAI_API_KEY="xai-" + "x" * 40)
        assert any(lvl == "info" and "API Key" in msg for lvl, msg in issues)

    def test_missing_key_produces_warning(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="claude")
        assert any(lvl == "warning" and "ANTHROPIC_API_KEY" in msg for lvl, msg in issues)

    def test_short_key_produces_warning(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="claude",
                            ANTHROPIC_API_KEY="tooshort")
        assert any(lvl == "warning" and "inválida" in msg for lvl, msg in issues)


# ------------------------------------------------------------------ #
#  Hermes OAuth mode — xAI                                            #
# ------------------------------------------------------------------ #

class TestHermesOAuthXAI:
    def test_oauth_enabled_flag_skips_key_check(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="xai",
                            HERMES_OAUTH_ENABLED="true")
        assert not any(lvl == "warning" for lvl, msg in issues)

    def test_oauth_enabled_produces_info_with_oauth_label(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="xai",
                            HERMES_OAUTH_ENABLED="true")
        assert any(lvl == "info" and "Hermes OAuth" in msg for lvl, msg in issues)

    def test_auth_token_presence_skips_key_check(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="xai",
                            XAI_AUTH_TOKEN="oauth-token-abc123")
        assert not any(lvl == "warning" for lvl, msg in issues)

    def test_auth_token_produces_info_with_oauth_label(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="xai",
                            XAI_AUTH_TOKEN="oauth-token-abc123")
        assert any(lvl == "info" and "Hermes OAuth" in msg for lvl, msg in issues)

    def test_oauth_truthy_values(self, monkeypatch):
        for truthy in ("true", "1", "yes"):
            issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="xai",
                                HERMES_OAUTH_ENABLED=truthy)
            assert any(lvl == "info" and "Hermes OAuth" in msg for lvl, msg in issues), \
                f"HERMES_OAUTH_ENABLED={truthy!r} should activate OAuth mode"

    def test_oauth_false_without_key_still_warns(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="xai",
                            HERMES_OAUTH_ENABLED="false")
        assert any(lvl == "warning" and "XAI_API_KEY" in msg for lvl, msg in issues)

    def test_xai_without_oauth_and_without_key_warns(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="xai")
        assert any(lvl == "warning" and "XAI_API_KEY" in msg for lvl, msg in issues)


# ------------------------------------------------------------------ #
#  Hermes OAuth mode — Nous Research                                   #
# ------------------------------------------------------------------ #

class TestHermesOAuthNous:
    def test_nous_with_oauth_enabled(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="nous",
                            HERMES_OAUTH_ENABLED="true")
        assert any(lvl == "info" and "Hermes OAuth" in msg for lvl, msg in issues)

    def test_nous_with_auth_token(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="nous",
                            XAI_AUTH_TOKEN="some-token")
        assert any(lvl == "info" and "Hermes OAuth" in msg for lvl, msg in issues)

    def test_nous_without_oauth_and_without_key_warns(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="nous")
        assert any(lvl == "warning" and "NOUS_API_KEY" in msg for lvl, msg in issues)


# ------------------------------------------------------------------ #
#  OAuth does NOT apply to non-OAuth providers                         #
# ------------------------------------------------------------------ #

class TestOAuthDoesNotApplyToOtherProviders:
    def test_claude_ignores_hermes_oauth_flag(self, monkeypatch):
        # Claude requires ANTHROPIC_API_KEY regardless of OAuth flag
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="claude",
                            HERMES_OAUTH_ENABLED="true")
        assert any(lvl == "warning" and "ANTHROPIC_API_KEY" in msg for lvl, msg in issues)

    def test_openai_ignores_hermes_oauth_flag(self, monkeypatch):
        issues = _ai_issues(monkeypatch, AI_ENABLED="true", AI_PROVIDER="openai",
                            HERMES_OAUTH_ENABLED="true")
        assert any(lvl == "warning" and "OPENAI_API_KEY" in msg for lvl, msg in issues)
