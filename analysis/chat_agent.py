"""
Conversational orchestrator — "Hablá con tu plan" (Gran Salto — Fase 4).

A chat where the user asks in natural language and this agent:
  1. ROUTES the question to the right deterministic tool (tool-calling), or to
     "none" for a general question.
  2. EXECUTES that tool — a real engine function returning real numbers.
  3. NARRATES an answer that uses ONLY those returned numbers.

The anti-hallucination guarantee is structural: the narrator only ever sees the
deterministic tool output and is explicitly told not to invent figures. The raw
data travels back in the response so the UI can show the hard number next to the
story (as the rest of the product already does).

``call_fn`` is the injection seam (``call_fn(prompt) -> str``): in production it
wraps the multi-provider ``AIAnalyzer._call_api``; in tests a fake is injected so
the whole agent — routing, dispatch, narration, error handling — runs offline.

Conventions: config from ``config.CHAT``; loguru.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from loguru import logger

from analysis.chat_tools import Tool, build_default_registry, registry_spec
from analysis.utils import extract_json_object
from config import CHAT

LLMCall = Callable[[str], str]


@dataclass
class ChatResponse:
    answer: str
    tool_used: str = "none"
    args: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "answer": self.answer, "tool_used": self.tool_used,
            "args": self.args, "data": self.data, "error": self.error,
        }


_ROUTER_MARKER = "TAREA-ROUTER"
_NARRATE_MARKER = "TAREA-NARRADOR"


class ChatAgent:
    def __init__(self, call_fn: Optional[LLMCall] = None, *, ai_config=None,
                 registry: Optional[Dict[str, Tool]] = None):
        if call_fn is None and ai_config is None:
            raise ValueError("ChatAgent needs either call_fn or ai_config")
        self._call_fn = call_fn or self._make_api_call_fn(ai_config)
        self._registry = registry if registry is not None else build_default_registry()

    @staticmethod
    def _make_api_call_fn(ai_config) -> LLMCall:
        from analysis.ai_analyzer import AIAnalyzer

        analyzer = AIAnalyzer(ai_config)
        return lambda prompt: analyzer._call_api(prompt, max_tokens=CHAT.max_narrate_tokens)

    # ------------------------------------------------------------------ #
    #  Public                                                             #
    # ------------------------------------------------------------------ #

    def ask(self, question: str) -> ChatResponse:
        question = (question or "").strip()
        if not question:
            return ChatResponse(answer="¿Sobre qué querés preguntar?", tool_used="none")

        tool_name, args = self._route(question)

        if tool_name == "none" or tool_name not in self._registry:
            answer = self._narrate(question, tool_name="none", data={
                "nota": "No se usó ninguna herramienta de datos; respondé de forma general y "
                        "NO inventes cifras concretas de mercado.",
            })
            return ChatResponse(answer=answer, tool_used="none")

        tool = self._registry[tool_name]
        try:
            data = tool.run(args)
        except Exception as exc:  # defensive — tools already guard, but double-safe
            logger.error(f"chat: tool {tool_name} raised — {exc}")
            data = {"ok": False, "error": str(exc)}

        if not data.get("ok", False):
            err = data.get("error", "No se pudo obtener el dato.")
            answer = self._narrate(question, tool_name, {"error": err})
            return ChatResponse(answer=answer, tool_used=tool_name, args=args, data=data, error=err)

        answer = self._narrate(question, tool_name, data)
        return ChatResponse(answer=answer, tool_used=tool_name, args=args, data=data)

    # ------------------------------------------------------------------ #
    #  Routing                                                            #
    # ------------------------------------------------------------------ #

    def _route(self, question: str) -> tuple:
        prompt = (
            f"{_ROUTER_MARKER}\n"
            "Sos el router de un asesor de inversiones para retiro. Elegí la herramienta que "
            "mejor responde la pregunta del usuario, o \"none\" si ninguna aplica.\n\n"
            "Herramientas disponibles:\n"
            f"{registry_spec(self._registry)}\n\n"
            f"Pregunta del usuario: \"{question}\"\n\n"
            "Respondé SOLO con un JSON: {\"tool\": \"<nombre o none>\", \"args\": {<parámetros>}}. "
            "Incluí en args solo los parámetros que puedas inferir de la pregunta."
        )
        try:
            raw = self._call_fn(prompt)
            data = extract_json_object(raw)
            tool = str(data.get("tool", "none")).strip()
            args = data.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            return tool, args
        except Exception as exc:
            logger.warning(f"chat router failed — {exc}")
            return "none", {}

    # ------------------------------------------------------------------ #
    #  Narration                                                          #
    # ------------------------------------------------------------------ #

    def _narrate(self, question: str, tool_name: str, data: dict) -> str:
        prompt = (
            f"{_NARRATE_MARKER}\n"
            "Sos un asesor de inversiones para retiro, conservador y claro. Respondé la pregunta "
            "del usuario en lenguaje natural, en español, breve y directo.\n"
            "REGLA CRÍTICA: usá EXCLUSIVAMENTE los datos provistos abajo. NO inventes ninguna "
            "cifra que no esté en los datos. Si los datos traen un error, explicá la limitación "
            "con amabilidad y sugerí qué hacer.\n\n"
            f"Pregunta: \"{question}\"\n"
            f"Herramienta usada: {tool_name}\n"
            f"Datos (deterministas):\n{json.dumps(data, ensure_ascii=False, indent=2)}\n\n"
            "Respuesta:"
        )
        try:
            return self._call_fn(prompt).strip()
        except Exception as exc:
            logger.error(f"chat narration failed — {exc}")
            if data.get("error"):
                return f"No pude completar la consulta: {data['error']}"
            return "Hubo un problema al redactar la respuesta. Probá de nuevo."
