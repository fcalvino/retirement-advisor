"""A rejected credential must never appear as an investment recommendation."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import openai
from streamlit.testing.v1 import AppTest

from analysis.eval_cases import golden_cases

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/15_Comite.py"


def test_auth_failure_is_visible_and_not_saved_as_last_verdict(monkeypatch):
    from analysis import committee, track_record
    from analysis.ai_analyzer import AIAnalyzer
    from dashboard import shared

    case = golden_cases()[0]
    monkeypatch.setattr(shared, "cached_full_analysis", lambda *a: (case.fund, case.tech, None))
    monkeypatch.setattr(committee.CommitteeAnalyzer, "_get_cached", lambda *a: None)
    response = Mock(status_code=401, headers={})
    failure = openai.AuthenticationError("Invalid API Key", response=response, body=None)
    monkeypatch.setattr(AIAnalyzer, "_call_api", Mock(side_effect=failure))
    record = Mock()
    monkeypatch.setattr(track_record, "track_record_store", SimpleNamespace(log_recommendation=record))
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    for key, value in dict(ai_enabled=True, ai_provider="groq", ai_model="openai/gpt-oss-120b", ai_api_key="test-key").items():
        app.session_state[key] = value
    app.run()
    next(b for b in app.button if "Convocar" in b.label).click().run()
    assert not app.exception
    assert any("API key inválida" in e.value for e in app.error)
    assert not any("Dictamen" in e.value for e in app.markdown)
    assert "comite_last_verdict" not in app.session_state
    record.assert_not_called()
    app.run()
    assert not any("Último dictamen" in e.value for e in app.success)


def test_portfolio_renderer_does_not_call_failed_panel_a_hold():
    app = AppTest.from_string('''
from analysis.committee import AgentOpinion, aggregate
from dashboard.shared import render_committee_verdict
verdict = aggregate("portfolio", [AgentOpinion("Estratega Macro", "HOLD", "LOW", error="key_invalida")])
render_committee_verdict(verdict)
''').run()
    assert not app.exception
    assert app.error
    assert not any("Veredicto:" in e.value for e in app.markdown)


def test_renderer_says_nobody_argued_instead_of_nobody_agreed():
    """COM-VOTO-VACÍO end-to-end through the real Streamlit renderer.

    Every agent returns a legible stance and not one word of prose, so consensus
    and dissent are both empty with nothing having failed. The verdict still
    renders (the votes are valid), but the captions must name the real cause.
    """
    app = AppTest.from_string('''
from analysis.committee import AgentOpinion, aggregate
from dashboard.shared import render_committee_verdict
verdict = aggregate("portfolio", [
    AgentOpinion("Estratega del Plan", "HOLD", "MEDIUM"),
    AgentOpinion("Gestor de Riesgo", "HOLD", "MEDIUM"),
    AgentOpinion("Abogado del Diablo", "HOLD", "MEDIUM"),
])
render_committee_verdict(verdict)
''').run()

    assert not app.exception
    assert not app.error  # nothing failed — the panel voted
    captions = " ".join(c.value for c in app.caption)
    assert "sin dar argumentos" in captions
    assert "Abogado del Diablo" in captions
    assert "Sin puntos de consenso claros." not in captions
