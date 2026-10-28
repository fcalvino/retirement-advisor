"""AUDIT-UI-ESTADO (mensajes) — el mensaje de Macro RAG sobrevive al rerun y el chat no lee `$` como LaTeX.

1. ``17_Macro_RAG.py`` dibujaba ``st.success(...)`` y llamaba a ``st.rerun()`` a continuación: el rerun
   borra la salida de la corrida, así que el mensaje («Listo: N documentos…», «Ingeridos N desde FRED»,
   y el aviso de FRED sin datos) no se llegaba a ver. El rerun hace falta (el contador de arriba se
   calcula antes de los botones); el mensaje ahora se guarda en la sesión y se muestra después.
2. ``18_Chat.py`` pasaba el texto del modelo, el historial y lo que escribe el usuario a ``st.markdown``
   sin ``escape_dollars``: «entre $300 y $500» se dibuja como una fórmula (CONTEXT §8). El historial queda
   guardado sin escapar; se escapa al dibujar.

Con AppTest; sin red y sin tocar el índice macro real.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

VIEWS = Path(__file__).resolve().parents[1] / "dashboard" / "views"
MACRO = str(VIEWS / "17_Macro_RAG.py")
CHAT = str(VIEWS / "18_Chat.py")


# --------------------------------------------------------------------------- #
#  1 — Macro RAG                                                               #
# --------------------------------------------------------------------------- #

@pytest.fixture
def macro(monkeypatch):
    """``macro(fred=...)`` abre la página con un índice en memoria; ``fred`` es lo que devuelve la ingesta."""
    import analysis.macro_rag as macro_rag
    from config import MULTI_SOURCE

    state = {"n": 0}
    monkeypatch.setattr(macro_rag.macro_rag_store, "count", lambda: state["n"])
    monkeypatch.setattr(macro_rag.macro_rag_store, "all_docs", lambda: [])
    monkeypatch.setattr(macro_rag.macro_rag_store, "ingest_many",
                        lambda docs: state.__setitem__("n", len(docs)) or len(docs))
    monkeypatch.setattr(MULTI_SOURCE, "fred_api_key", "k")

    def open_page(fred: int = 0) -> AppTest:
        monkeypatch.setattr(macro_rag, "ingest_from_fred", lambda store: fred)
        at = AppTest.from_file(MACRO, default_timeout=30)
        at.run()
        assert not at.exception, [str(e)[:300] for e in at.exception]
        return at

    return open_page


def _click(at: AppTest, label_start: str) -> AppTest:
    next(b for b in at.button if b.label.startswith(label_start)).click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def test_the_example_set_message_survives_the_rerun(macro):
    at = _click(macro(), "🌱 Cargar set de ejemplo")
    assert [s.value for s in at.success if "documentos de ejemplo cargados" in s.value]
    # y el contador de arriba ya cuenta los documentos cargados (por eso el rerun)
    assert next(m for m in at.metric if m.label == "Documentos macro indexados").value != "0"


def test_the_message_is_shown_once_and_not_on_the_next_rerun(macro):
    at = _click(macro(), "🌱 Cargar set de ejemplo")
    at.run()
    assert not [s.value for s in at.success if "documentos de ejemplo cargados" in s.value]


def test_the_fred_success_message_survives_the_rerun(macro):
    at = _click(macro(fred=4), "📡 Ingerir desde FRED")
    assert [s.value for s in at.success if "Ingeridos 4 documentos desde FRED" in s.value]


def test_the_fred_warning_survives_the_rerun(macro):
    at = _click(macro(fred=0), "📡 Ingerir desde FRED")
    assert [w.value for w in at.warning if "No se pudo ingerir desde FRED" in w.value]


# --------------------------------------------------------------------------- #
#  2 — Chat                                                                    #
# --------------------------------------------------------------------------- #

ANSWER = "Necesitás entre $300 y $500 por mes."
ESCAPED = "Necesitás entre \\$300 y \\$500 por mes."


@pytest.fixture
def chat(monkeypatch):
    from analysis import chat_agent
    from dashboard import shared

    monkeypatch.setattr(shared, "_get_ai_config", lambda *a, **k: SimpleNamespace(
        enabled=True, provider="claude", model="m", api_key="k"))
    monkeypatch.setattr(shared, "get_user_prefs", lambda: SimpleNamespace(active_plan_id=""))
    monkeypatch.setattr(chat_agent.ChatAgent, "ask", lambda self, q: chat_agent.ChatResponse(
        answer=ANSWER, tool_used="none"))

    def open_page(history=None) -> AppTest:
        at = AppTest.from_file(CHAT, default_timeout=30)
        if history is not None:
            at.session_state["chat_history"] = history
        at.run()
        assert not at.exception, [str(e)[:300] for e in at.exception]
        return at

    return open_page


def _texts(at: AppTest) -> list[str]:
    return [m.value for cm in at.chat_message for m in cm.markdown]


def test_a_new_answer_is_drawn_with_the_dollars_escaped(chat):
    at = chat()
    at.chat_input[0].set_value("¿cuánto necesito?").run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    assert ESCAPED in _texts(at)
    assert ANSWER not in _texts(at)


def test_the_replayed_history_is_drawn_with_the_dollars_escaped(chat):
    at = chat([{"role": "user", "content": "tengo $1000 y quiero $2000"},
               {"role": "assistant", "content": ANSWER}])
    assert ESCAPED in _texts(at)
    assert "tengo \\$1000 y quiero \\$2000" in _texts(at)


def test_what_the_user_types_is_escaped_too(chat):
    at = chat()
    at.chat_input[0].set_value("ahorro $100 por mes y $50 extra").run()
    assert "ahorro \\$100 por mes y \\$50 extra" in _texts(at)


def test_the_history_keeps_the_raw_text(chat):
    at = chat()
    at.chat_input[0].set_value("¿cuánto necesito?").run()
    assert [m["content"] for m in at.session_state["chat_history"]] == ["¿cuánto necesito?", ANSWER]
