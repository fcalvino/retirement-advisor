"""UX-QA: what the QA of 2026-09-25 saw on screen must match what happened.

Each case is a place where the UI said less (or something else) than the log:

1. Stock Analysis with AI on and a rejected key showed «sin IA» and nothing
   else; the log had ``AI fallback — causa=key_invalida``.
2. The chat answered «Probá de nuevo» to a rejected key — retrying cannot fix it.
3. A price alert created with the default target (the current price) fired on
   creation and claimed the stock «cayó por debajo».
4. The Watchlist banner put two ``$`` in one markdown line: KaTeX ate the text
   between them (CONTEXT §8).
5. Alertas ran with email enabled but incomplete and said nothing (SMTP-GUARD
   skips the send; the page must say so).

No network, no writes to the user's preferences.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import openai
import pytest
from streamlit.testing.v1 import AppTest

from analysis.chat_agent import ChatAgent
from analysis.eval_cases import golden_cases
from analysis.strategy import RetirementStrategy
from config import AI_FALLBACK, ALERTS
from data.preferences import UserPreferences

VIEWS = Path(__file__).resolve().parents[1] / "dashboard/views"


@pytest.fixture(autouse=True)
def _no_prefs_writes(monkeypatch):
    monkeypatch.setattr(UserPreferences, "save", lambda self: None)


def _auth_error():
    return openai.AuthenticationError("Invalid API Key", response=Mock(status_code=401, headers={}), body=None)


# 1 ----------------------------------------------------------------------------
def test_stock_analysis_names_the_ai_failure(monkeypatch):
    from analysis import track_record
    from dashboard import shared

    case = golden_cases()[0]
    decision = RetirementStrategy().decide(case.fund, case.tech)
    decision.ai_fallback_reason = AI_FALLBACK.KEY_INVALIDA
    monkeypatch.setattr(shared, "cached_full_analysis", lambda *a, **k: (case.fund, case.tech, decision))
    monkeypatch.setattr(track_record, "track_record_store", SimpleNamespace(log_recommendation=Mock()))
    app = AppTest.from_file(str(VIEWS / "2_Stock_Analysis.py"), default_timeout=60)
    for key, value in dict(ai_enabled=True, ai_provider="claude", ai_model="claude-sonnet-5",
                           ai_api_key="test-key", analysis_target=case.fund.symbol).items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    expected = AI_FALLBACK.message(AI_FALLBACK.KEY_INVALIDA, "claude")
    assert any(expected in w.value for w in app.warning)


# 2 ----------------------------------------------------------------------------
def test_chat_names_a_rejected_key_instead_of_asking_to_retry():
    agent = ChatAgent(call_fn=Mock(side_effect=_auth_error()), registry={})
    answer = agent.ask("¿Qué score tiene MSFT?").answer
    assert AI_FALLBACK.label(AI_FALLBACK.KEY_INVALIDA) in answer
    assert "Probá de nuevo" not in answer


# 3 ----------------------------------------------------------------------------
@pytest.mark.parametrize("condition", ["below", "above"])
def test_alert_at_the_current_price_has_not_crossed(condition):
    prefs = UserPreferences()
    prefs.price_alerts = [{"symbol": "MSFT", "condition": condition, "target": 497.93, "triggered": False}]
    assert prefs.check_price_alerts({"MSFT": 497.93}) == []
    moved = 497.0 if condition == "below" else 499.0
    assert len(prefs.check_price_alerts({"MSFT": moved})) == 1


# 4 ----------------------------------------------------------------------------
def test_watchlist_banner_escapes_dollars(monkeypatch):
    from dashboard import shared

    case = golden_cases()[0]
    fund = replace(case.fund, symbol="MSFT", current_price=497.0)
    decision = RetirementStrategy().decide(fund, case.tech)
    monkeypatch.setattr(shared, "_fetch_universe_parallel",
                        lambda *a, **k: [("MSFT", fund, case.tech, decision)])
    prefs = UserPreferences()
    prefs.watched_tickers = ["MSFT"]
    prefs.price_alerts = [{"symbol": "MSFT", "condition": "below", "target": 497.93, "triggered": False}]
    app = AppTest.from_file(str(VIEWS / "11_Watchlist.py"), default_timeout=60)
    app.session_state["user_prefs"] = prefs
    app.run()
    assert not app.exception
    banners = [w.value for w in app.warning if "MSFT" in w.value]
    assert banners
    for text in banners:
        assert "$" not in text.replace("\\$", "")


# 5 ----------------------------------------------------------------------------
def test_alertas_warns_when_email_is_enabled_but_incomplete(monkeypatch, tmp_path):
    import config
    from alerts import store

    monkeypatch.setattr(store, "alert_store", store.AlertStore(db_path=tmp_path / "alerts.db"))

    monkeypatch.setattr(config, "ALERTS", replace(
        ALERTS, email_enabled=True, email_from="me@example.com", email_to="me@example.com", smtp_password=""))
    app = AppTest.from_file(str(VIEWS / "8_Alertas.py"), default_timeout=60)
    app.run()
    assert not app.exception
    assert any("email" in w.value.lower() and "incompleta" in w.value.lower() for w in app.warning)
