"""The ticker typed in the Comité page must be the one the committee evaluates.

Regression (fixed): the key-less ``st.text_input`` takes ``value=comite_last_symbol``.
After a run that value changes, Streamlit sees a new widget and resets it, so
the ticker typed for the *second* convene is dropped and the previous one is
re-evaluated (a cache hit that repeats the previous verdict).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from analysis.committee import AgentOpinion, aggregate
from analysis.eval_cases import golden_cases

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/15_Comite.py"


def test_second_convene_evaluates_the_newly_typed_ticker(monkeypatch):
    from analysis import committee, track_record
    from dashboard import shared

    case = golden_cases()[0]
    analyzed: list[str] = []

    def _fake_analysis(symbol, *a, **k):
        analyzed.append(symbol)
        return case.fund, case.tech, None

    monkeypatch.setattr(shared, "cached_full_analysis", _fake_analysis)
    verdict = aggregate("X", [AgentOpinion("Analista Fundamental", "HOLD", "MEDIUM")])
    monkeypatch.setattr(committee.CommitteeAnalyzer, "analyze", lambda self, *a, **k: verdict)
    monkeypatch.setattr(track_record, "track_record_store", SimpleNamespace(log_recommendation=Mock()))

    app = AppTest.from_file(str(PAGE), default_timeout=30)
    for key, value in dict(ai_enabled=True, ai_provider="groq", ai_model="m", ai_api_key="k").items():
        app.session_state[key] = value
    app.run()

    for sym in ("NVDA", "KO"):
        app.text_input[0].set_value(sym)
        next(b for b in app.button if "Convocar" in b.label).click().run()
        assert not app.exception

    assert analyzed == ["NVDA", "KO"]
    assert any("Dictamen KO:" in e.value for e in app.markdown)


def test_demo_button_fills_the_ticker_input(monkeypatch):
    from data.product_ux import guided_empty_state

    demo = guided_empty_state("comite")["demo_ticker"]
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    for key, value in dict(ai_enabled=True, ai_provider="groq", ai_model="m", ai_api_key="k").items():
        app.session_state[key] = value
    app.run()
    app.text_input[0].set_value("ZZZZ").run()
    next(b for b in app.button if "Probar con" in b.label).click().run()
    assert not app.exception
    assert app.text_input[0].value == demo
