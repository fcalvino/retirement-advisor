"""Tests for config_validator.validate_config() — AI section focus."""

from unittest.mock import patch

import pytest

from config_validator import validate_config


def _ai_issues(monkeypatch, hermes_available=False, **env):
    """
    Run validate_config() with a clean environment plus the given overrides.
    hermes_available controls what _hermes_oauth_available() returns (avoids
    needing ~/.hermes/hermes-agent installed in CI).
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    with patch("config_validator._hermes_oauth_available", return_value=hermes_available):
        all_issues = validate_config()

    return [
        (lvl, msg) for lvl, msg in all_issues
        if any(kw in msg for kw in ("AI", "rule-based", "proveedor", "OAuth", "inválida", "_API_KEY"))
    ]


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

    def test_xai_with_valid_api_key(self, monkeypatch):
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
    def test_oauth_active_skips_key_check(self, monkeypatch):
        issues = _ai_issues(monkeypatch, hermes_available=True,
                            AI_ENABLED="true", AI_PROVIDER="xai")
        assert not any(lvl == "warning" for lvl, msg in issues)

    def test_oauth_active_produces_info_with_oauth_label(self, monkeypatch):
        issues = _ai_issues(monkeypatch, hermes_available=True,
                            AI_ENABLED="true", AI_PROVIDER="xai")
        assert any(lvl == "info" and "Hermes OAuth" in msg for lvl, msg in issues)

    def test_oauth_inactive_without_key_warns(self, monkeypatch):
        issues = _ai_issues(monkeypatch, hermes_available=False,
                            AI_ENABLED="true", AI_PROVIDER="xai")
        assert any(lvl == "warning" and "XAI_API_KEY" in msg for lvl, msg in issues)

    def test_api_key_takes_precedence_over_oauth_check(self, monkeypatch):
        # When API key is present, _hermes_oauth_available is never called
        issues = _ai_issues(monkeypatch, hermes_available=False,
                            AI_ENABLED="true", AI_PROVIDER="xai",
                            XAI_API_KEY="xai-" + "x" * 40)
        assert any(lvl == "info" and "API Key" in msg for lvl, msg in issues)
        assert not any(lvl == "warning" for lvl, msg in issues)


# ------------------------------------------------------------------ #
#  Hermes OAuth mode — Nous Research                                   #
# ------------------------------------------------------------------ #

class TestHermesOAuthNous:
    def test_oauth_active_skips_key_check(self, monkeypatch):
        issues = _ai_issues(monkeypatch, hermes_available=True,
                            AI_ENABLED="true", AI_PROVIDER="nous")
        assert not any(lvl == "warning" for lvl, msg in issues)

    def test_oauth_active_produces_info_with_oauth_label(self, monkeypatch):
        issues = _ai_issues(monkeypatch, hermes_available=True,
                            AI_ENABLED="true", AI_PROVIDER="nous")
        assert any(lvl == "info" and "Hermes OAuth" in msg for lvl, msg in issues)

    def test_oauth_inactive_without_key_warns(self, monkeypatch):
        issues = _ai_issues(monkeypatch, hermes_available=False,
                            AI_ENABLED="true", AI_PROVIDER="nous")
        assert any(lvl == "warning" and "NOUS_API_KEY" in msg for lvl, msg in issues)


# ------------------------------------------------------------------ #
#  OAuth does NOT apply to non-OAuth providers                         #
# ------------------------------------------------------------------ #

class TestOAuthDoesNotApplyToOtherProviders:
    def test_claude_requires_key_regardless_of_hermes(self, monkeypatch):
        # _hermes_oauth_available is never called for claude — still warns
        issues = _ai_issues(monkeypatch, hermes_available=True,
                            AI_ENABLED="true", AI_PROVIDER="claude")
        assert any(lvl == "warning" and "ANTHROPIC_API_KEY" in msg for lvl, msg in issues)

    def test_openai_requires_key_regardless_of_hermes(self, monkeypatch):
        issues = _ai_issues(monkeypatch, hermes_available=True,
                            AI_ENABLED="true", AI_PROVIDER="openai")
        assert any(lvl == "warning" and "OPENAI_API_KEY" in msg for lvl, msg in issues)


# ------------------------------------------------------------------ #
#  _hermes_oauth_available unit tests                                  #
# ------------------------------------------------------------------ #

class TestHermesOAuthAvailable:
    def test_returns_false_when_hermes_dir_missing(self, tmp_path):
        from config_validator import _hermes_oauth_available
        with patch("config_validator.os.path.expanduser", return_value=str(tmp_path / "nonexistent")):
            assert _hermes_oauth_available("xai") is False

    def test_returns_false_when_import_raises(self, tmp_path):
        from config_validator import _hermes_oauth_available
        hermes_dir = tmp_path / ".hermes" / "hermes-agent"
        hermes_dir.mkdir(parents=True)
        with patch("config_validator.os.path.expanduser", return_value=str(hermes_dir)), \
             patch("builtins.__import__", side_effect=ImportError("no module")):
            assert _hermes_oauth_available("xai") is False

    def test_returns_true_when_resolver_succeeds(self, tmp_path):
        from config_validator import _hermes_oauth_available
        hermes_dir = tmp_path / ".hermes" / "hermes-agent"
        hermes_dir.mkdir(parents=True)

        fake_creds = {"api_key": "fake-oauth-token"}
        mock_resolver = lambda: fake_creds  # noqa: E731

        with patch("config_validator.os.path.expanduser", return_value=str(hermes_dir)), \
             patch("config_validator.os.path.isdir", return_value=True):
            import importlib
            import types
            fake_auth = types.ModuleType("hermes_cli.auth")
            fake_auth.resolve_xai_oauth_runtime_credentials = mock_resolver
            fake_auth.resolve_nous_runtime_credentials = mock_resolver
            with patch.dict("sys.modules", {"hermes_cli": types.ModuleType("hermes_cli"),
                                            "hermes_cli.auth": fake_auth}):
                assert _hermes_oauth_available("xai") is True
                assert _hermes_oauth_available("nous") is True
