"""Exercise the actual Stock Analysis page offline, including metric help."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analysis.strategy import RetirementStrategy
from analysis.technical import TechnicalResult
from tests.test_currency_metric_surfaces import BACKSTOP, currency_note, fund_fixture

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/2_Stock_Analysis.py"


@pytest.fixture
def render(monkeypatch):
    import yfinance as yf

    from analysis.track_record import TrackRecordStore
    from config import MULTI_SOURCE
    from dashboard import shared

    def no_network(*args, **kwargs):
        raise AssertionError("This page test must not access yfinance")

    monkeypatch.setattr(yf, "Ticker", no_network)
    monkeypatch.setattr(MULTI_SOURCE, "enabled", False)
    monkeypatch.setattr(TrackRecordStore, "log_recommendation", lambda *a, **kw: None)
    monkeypatch.setattr(shared, "ensure_session_defaults", lambda: None)
    monkeypatch.setattr(shared, "get_price_history", lambda *a, **kw: pd.DataFrame())
    monkeypatch.setattr(shared, "_get_ai_config", lambda: SimpleNamespace(
        provider="none", model="", enabled=False, api_key="",
    ))

    def run(fund):
        tech = TechnicalResult("TEST")
        decision = RetirementStrategy().decide(fund, tech)
        monkeypatch.setattr(shared, "cached_full_analysis", lambda *a: (fund, tech, decision))
        app = AppTest.from_file(str(PAGE), default_timeout=30)
        app.session_state["analysis_target"] = "TEST"
        app.session_state["universe"] = ["TEST"]
        app.session_state["user_prefs"] = SimpleNamespace(watched_tickers=[])
        app.session_state["portfolio"] = SimpleNamespace(positions=[])
        app.run()
        assert not app.exception, [e.message for e in app.exception]
        run.app = app
        return {m.label: m for m in app.metric}

    return run


def test_both_currency_notes_render_not_measurable_with_full_tooltip(render):
    fund = fund_fixture()
    fund.notes = {f"{m}_currency": currency_note(m) for m in ("fcf_yield", "p_ffo")}
    metrics = render(fund)
    for label, metric in [("FCF Yield", "fcf_yield"), ("P/FFO", "p_ffo")]:
        assert metrics[label].value == "no medible"
        assert metrics[label].proto.help == fund.notes[f"{metric}_currency"]


def test_backstop_tooltip_keeps_actual_reason(render):
    fund = fund_fixture()
    fund.notes["fcf_yield_currency"] = BACKSTOP
    metrics = render(fund)
    assert metrics["FCF Yield"].value == "no medible"
    assert metrics["FCF Yield"].proto.help == BACKSTOP


def test_no_note_preserves_missing_display_and_hides_missing_p_ffo(render):
    metrics = render(fund_fixture())
    assert metrics["FCF Yield"].value == "N/A"
    assert not metrics["FCF Yield"].proto.help
    assert "P/FFO" not in metrics


def test_measurable_metrics_keep_formatting(render):
    fund = fund_fixture()
    fund.fcf_yield, fund.p_ffo = 4.5, 12.5
    metrics = render(fund)
    assert metrics["FCF Yield"].value == "4.50%"
    assert metrics["P/FFO"].value == "12.50x"


@pytest.mark.parametrize("market_cap, expected", [(0.0, "Market Cap: n/d"),
                                                  (2.5e12, "Market Cap: $2500.0B")])
def test_market_cap_absent_is_not_zero(render, market_cap, expected):
    """UM-GDR: SMSN.IL has no marketCap in the feed; «$0.0B» is a zero that is no datum."""
    fund = fund_fixture()
    fund.market_cap = market_cap
    render(fund)
    captions = [c.value for c in render.app.caption]
    assert any(expected in c for c in captions), captions
    assert not any("Market Cap: $0.0B" in c for c in captions)
