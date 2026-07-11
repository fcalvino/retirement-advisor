"""Tests for the conversational orchestrator (Gran Salto, Fase 4).

Injects a fake LLM (``call_fn``) and a fake tool registry, so routing, dispatch,
narration and error handling run fully offline. Also verifies the key invariant:
the narrator is only ever handed the deterministic tool data (no hallucinated
numbers can leak in because they're not in scope).
"""

from __future__ import annotations

import json

import pytest

from analysis.chat_agent import ChatAgent
from analysis.chat_tools import Tool, build_default_registry, registry_spec

# --------------------------------------------------------------------------- #
#  Fakes                                                                       #
# --------------------------------------------------------------------------- #

def _fake_registry():
    def _analyze(args):
        sym = str(args.get("symbol", "")).upper()
        if sym == "BADTICKER":
            return {"ok": False, "error": "ticker inexistente"}
        return {"ok": True, "symbol": sym, "action": "BUY", "fundamental_score": 72.0}

    return {
        "analyze_ticker": Tool(
            name="analyze_ticker", description="analiza una acción",
            parameters={"symbol": "ticker"}, required=["symbol"], run=_analyze,
        ),
    }


class _FakeLLM:
    """Routes by the markers embedded in the agent's prompts."""

    def __init__(self, *, route_tool="analyze_ticker", route_args=None, narration="Respuesta narrada."):
        self.route_tool = route_tool
        self.route_args = route_args if route_args is not None else {"symbol": "AAPL"}
        self.narration = narration
        self.last_narrate_prompt = ""

    def __call__(self, prompt: str) -> str:
        if "TAREA-ROUTER" in prompt:
            return json.dumps({"tool": self.route_tool, "args": self.route_args})
        # narration
        self.last_narrate_prompt = prompt
        return self.narration


# --------------------------------------------------------------------------- #
#  Routing + dispatch                                                          #
# --------------------------------------------------------------------------- #

def test_routes_and_runs_tool():
    llm = _FakeLLM(route_tool="analyze_ticker", route_args={"symbol": "AAPL"})
    agent = ChatAgent(call_fn=llm, registry=_fake_registry())
    resp = agent.ask("¿Conviene comprar AAPL?")
    assert resp.tool_used == "analyze_ticker"
    assert resp.args == {"symbol": "AAPL"}
    assert resp.data["ok"] is True
    assert resp.data["action"] == "BUY"
    assert resp.answer == "Respuesta narrada."


def test_unknown_tool_falls_back_to_none():
    llm = _FakeLLM(route_tool="does_not_exist")
    agent = ChatAgent(call_fn=llm, registry=_fake_registry())
    resp = agent.ask("contame un chiste")
    assert resp.tool_used == "none"
    assert resp.data == {}


def test_tool_error_is_handled_gracefully():
    llm = _FakeLLM(route_tool="analyze_ticker", route_args={"symbol": "BADTICKER"})
    agent = ChatAgent(call_fn=llm, registry=_fake_registry())
    resp = agent.ask("analizá BADTICKER")
    assert resp.tool_used == "analyze_ticker"
    assert resp.error == "ticker inexistente"
    assert resp.data["ok"] is False


def test_empty_question():
    agent = ChatAgent(call_fn=_FakeLLM(), registry=_fake_registry())
    resp = agent.ask("   ")
    assert resp.tool_used == "none"


def test_router_bad_json_falls_back():
    class _BadRouter(_FakeLLM):
        def __call__(self, prompt):
            if "TAREA-ROUTER" in prompt:
                return "no soy json"
            return "narración general"

    agent = ChatAgent(call_fn=_BadRouter(), registry=_fake_registry())
    resp = agent.ask("algo ambiguo")
    assert resp.tool_used == "none"


# --------------------------------------------------------------------------- #
#  Anti-hallucination invariant                                                #
# --------------------------------------------------------------------------- #

def test_narrator_only_sees_deterministic_data():
    llm = _FakeLLM(route_tool="analyze_ticker", route_args={"symbol": "AAPL"})
    agent = ChatAgent(call_fn=llm, registry=_fake_registry())
    agent.ask("¿Conviene comprar AAPL?")
    # The narration prompt must carry the real score and instruct against inventing.
    assert "72.0" in llm.last_narrate_prompt
    assert "NO inventes" in llm.last_narrate_prompt


# --------------------------------------------------------------------------- #
#  Default registry sanity                                                     #
# --------------------------------------------------------------------------- #

def test_default_registry_has_expected_tools():
    reg = build_default_registry()
    assert {"analyze_ticker", "plan_status", "retirement_projection"} <= set(reg)
    spec = registry_spec(reg)
    assert "analyze_ticker" in spec and "Parámetros" in spec


def test_requires_call_fn_or_config():
    with pytest.raises(ValueError):
        ChatAgent()
