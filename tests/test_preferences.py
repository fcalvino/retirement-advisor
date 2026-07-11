"""Tests for the personal-profile extension of UserPreferences (Fase A)."""

from __future__ import annotations

import json

import pytest

import data.preferences as prefs_module
from data.preferences import (
    RISK_TOLERANCE_TO_PROFILE_KEY,
    RISK_TOLERANCE_TO_PROFILE_NAME,
    UserPreferences,
)


@pytest.fixture
def tmp_prefs_path(tmp_path, monkeypatch):
    """Redirect preference persistence to a temp file."""
    p = tmp_path / "user_preferences.json"
    monkeypatch.setattr(prefs_module, "_PREFS_PATH", p)
    return p


# ------------------------------------------------------------------ #
#  Defaults / not-onboarded                                           #
# ------------------------------------------------------------------ #

def test_defaults_not_onboarded():
    prefs = UserPreferences()
    assert prefs.is_onboarded is False
    assert prefs.age == 0
    assert prefs.primary_horizon_years == 0
    assert prefs.annual_savings == 0.0
    assert prefs.profile_key == "conservative"
    assert prefs.default_profile == "Conservador"


def test_primary_horizon_requires_valid_ages():
    prefs = UserPreferences(age=40, retirement_age=65)
    # is_onboarded still needs the flag set, but horizon is computable
    assert prefs.primary_horizon_years == 25
    # Invalid: retirement before current age
    bad = UserPreferences(age=70, retirement_age=65)
    assert bad.primary_horizon_years == 0


# ------------------------------------------------------------------ #
#  apply_personal_profile                                             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tol", ["conservadora", "moderada", "agresiva"])
def test_apply_personal_profile_sets_and_maps_profile(tol, tmp_prefs_path):
    prefs = UserPreferences()
    prefs.apply_personal_profile(
        age=45,
        retirement_age=67,
        current_capital=250_000,
        monthly_savings=2_000,
        risk_tolerance=tol,
        primary_goal_type="retiro",
        dividend_preference="ingreso",
    )
    assert prefs.is_onboarded is True
    assert prefs.primary_horizon_years == 22
    assert prefs.annual_savings == 24_000
    assert prefs.profile_key == RISK_TOLERANCE_TO_PROFILE_KEY[tol]
    assert prefs.default_profile == RISK_TOLERANCE_TO_PROFILE_NAME[tol]
    # Persisted to disk
    assert tmp_prefs_path.exists()
    on_disk = json.loads(tmp_prefs_path.read_text())
    assert on_disk["onboarded"] is True
    assert on_disk["current_capital"] == 250_000


# ------------------------------------------------------------------ #
#  Backward compatibility                                             #
# ------------------------------------------------------------------ #

def test_load_legacy_file_without_personal_fields(tmp_prefs_path):
    """An old prefs file (only legacy keys) loads with safe defaults."""
    legacy = {
        "default_profile": "Moderado",
        "active_universe": "us_quality",
        "watched_tickers": ["AAPL"],
    }
    tmp_prefs_path.write_text(json.dumps(legacy), encoding="utf-8")

    prefs = UserPreferences.load()
    assert prefs.default_profile == "Moderado"
    assert prefs.active_universe == "us_quality"
    assert prefs.watched_tickers == ["AAPL"]
    # New fields fall back to defaults — user treated as not onboarded
    assert prefs.is_onboarded is False
    assert prefs.age == 0


def test_save_load_round_trip_preserves_personal_fields(tmp_prefs_path):
    prefs = UserPreferences()
    prefs.apply_personal_profile(
        age=30,
        retirement_age=60,
        current_capital=100_000,
        monthly_savings=1_500,
        risk_tolerance="moderada",
        primary_goal_type="fire",
        dividend_preference="crecimiento",
    )
    reloaded = UserPreferences.load()
    assert reloaded.is_onboarded is True
    assert reloaded.age == 30
    assert reloaded.retirement_age == 60
    assert reloaded.primary_goal_type == "fire"
    assert reloaded.dividend_preference == "crecimiento"
    assert reloaded.profile_key == "moderate"
    assert reloaded.primary_horizon_years == 30


# ------------------------------------------------------------------ #
#  Custom tickers (Item 3)                                           #
# ------------------------------------------------------------------ #

def test_custom_tickers_default_empty():
    assert UserPreferences().custom_tickers == []
    assert UserPreferences().custom_symbols() == []


def test_add_custom_ticker(tmp_prefs_path):
    prefs = UserPreferences()
    assert prefs.add_custom_ticker("vist", "Vaca Muerta") is True
    assert prefs.custom_symbols() == ["VIST"]
    entry = prefs.custom_tickers[0]
    assert entry["symbol"] == "VIST"
    assert entry["note"] == "Vaca Muerta"
    assert entry["added_at"]


def test_add_custom_ticker_dedup(tmp_prefs_path):
    prefs = UserPreferences()
    assert prefs.add_custom_ticker("VIST") is True
    assert prefs.add_custom_ticker("vist") is False  # case-insensitive dup
    assert prefs.custom_symbols() == ["VIST"]


def test_add_custom_ticker_rejects_invalid(tmp_prefs_path):
    prefs = UserPreferences()
    assert prefs.add_custom_ticker("") is False
    assert prefs.add_custom_ticker("bad ticker!") is False
    assert prefs.add_custom_ticker("TOOLONGSYMBOL12") is False
    assert prefs.custom_tickers == []


def test_remove_custom_ticker(tmp_prefs_path):
    prefs = UserPreferences()
    prefs.add_custom_ticker("VIST")
    prefs.add_custom_ticker("BMA")
    prefs.remove_custom_ticker("vist")
    assert prefs.custom_symbols() == ["BMA"]


def test_custom_tickers_persist_roundtrip(tmp_prefs_path):
    prefs = UserPreferences()
    prefs.add_custom_ticker("VIST", "tesis")
    reloaded = UserPreferences.load()
    assert reloaded.custom_symbols() == ["VIST"]


def test_old_prefs_file_without_custom_tickers_loads(tmp_prefs_path):
    """Backward-compat: a prefs file predating the field still loads."""
    tmp_prefs_path.write_text(json.dumps({"age": 40, "retirement_age": 65}), encoding="utf-8")
    prefs = UserPreferences.load()
    assert prefs.custom_tickers == []
    assert prefs.age == 40
