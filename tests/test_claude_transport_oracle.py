"""Oráculo: el branch Anthropic deja de rechazar los modelos actuales (PR 1).

`_call_claude` mandaba `temperature=0` incondicionalmente y leía
`message.content[0].text`. Las dos cosas eran correctas contra `claude-sonnet-4-6`
y **ninguna** lo es contra un modelo actual:

* los parámetros de sampling fueron removidos de la API y devuelven 400 en todo
  lo posterior a 4.6, así que cualquier otro ID del selector fallaba siempre;
* con thinking adaptativo —encendido por defecto en los modelos actuales— el
  primer bloque de `content` es un `thinking` block, no el texto.

Las dos fallas caían en el `except Exception` de PR 0 y se veían en la UI como
«la IA no anda», una con causa equivocada (`parametro_rechazado` para *toda*
llamada) y la otra sin causa (`otro`, desde un `AttributeError`).

Lo que este archivo fija son cuatro invariantes, no una lista de casos:

1. **El branch Anthropic no manda sampling; los OpenAI-compatible sí.** Es la
   divergencia de transporte que hace portable al prompt: ningún prompt cambia
   por proveedor.
2. **El texto se busca por tipo de bloque**, así que un `thinking` block delante
   no rompe nada.
3. **`stop_reason` se mira antes que el contenido**, y sus finales son causas
   propias — distinguibles de `json_invalido` y de `parametro_rechazado`.
4. **El catálogo del selector es el de `config.py`** y no contiene ningún modelo
   que rechace la llamada que el branch efectivamente hace.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from analysis.ai_analyzer import AIAnalyzer, AIUnavailable, classify_ai_failure
from config import (
    AI_FALLBACK,
    CLAUDE_MODEL_CATALOG,
    CLAUDE_MODELS_SIN_SAMPLING,
    CLAUDE_TRANSPORT,
    AIConfig,
)

_SAMPLING_PARAMS = ("temperature", "top_p", "top_k")


# --------------------------------------------------------------------------- #
#  Helpers — dobles de los objetos del SDK, no del SDK entero                  #
# --------------------------------------------------------------------------- #

def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _thinking_block(text: str = "razonando...") -> SimpleNamespace:
    return SimpleNamespace(type="thinking", thinking=text)


def _message(content, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=list(content), stop_reason=stop_reason)


def _claude_analyzer() -> AIAnalyzer:
    return AIAnalyzer(AIConfig(provider="claude", model="claude-sonnet-5", api_key="k"))


def _call_claude_capturing(message) -> dict:
    """Corre `_call_claude` con un cliente mockeado y devuelve los kwargs."""
    client = MagicMock()
    client.messages.create.return_value = message
    fake_sdk = SimpleNamespace(Anthropic=lambda **_kw: client)

    with patch.dict("sys.modules", {"anthropic": fake_sdk}):
        _claude_analyzer()._call_claude("prompt")

    return client.messages.create.call_args.kwargs


# --------------------------------------------------------------------------- #
#  1. Sampling: ausente en Anthropic, presente en los OpenAI-compatible        #
# --------------------------------------------------------------------------- #

class TestSamplingEsUnaDivergenciaDeTransporte:

    def test_claude_no_manda_ningun_parametro_de_sampling(self):
        kwargs = _call_claude_capturing(_message([_text_block("ok")]))
        for param in _SAMPLING_PARAMS:
            assert param not in kwargs, (
                f"`{param}` volvió a `_call_claude`: devuelve 400 en "
                f"{sorted(CLAUDE_MODELS_SIN_SAMPLING)}"
            )

    def test_claude_sigue_mandando_modelo_y_techo_de_tokens(self):
        kwargs = _call_claude_capturing(_message([_text_block("ok")]))
        assert kwargs["model"] == "claude-sonnet-5"
        assert kwargs["max_tokens"] == CLAUDE_TRANSPORT.resolve_max_tokens(None)

    def test_el_techo_deja_holgura_para_thinking_sobre_el_pedido_del_caller(self):
        # `max_tokens` es el techo de thinking + texto, no del texto: el número
        # del caller es un presupuesto de texto calibrado contra 4.6.
        resolved = CLAUDE_TRANSPORT.resolve_max_tokens(2500)
        assert resolved > 2500
        assert resolved - int(2500 * CLAUDE_TRANSPORT.tokenizer_inflation) == (
            CLAUDE_TRANSPORT.thinking_headroom_tokens
        )

    def test_el_branch_openai_compatible_sigue_mandando_temperature(self):
        # La contracara del invariante: si acá desaparece `temperature`, la
        # remoción se filtró de transporte a política y dejó de ser deliberada.
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
        )
        fake_sdk = SimpleNamespace(OpenAI=lambda **_kw: client)

        analyzer = AIAnalyzer(AIConfig(provider="xai", model="grok-4.3", api_key="k"))
        with patch.dict("sys.modules", {"openai": fake_sdk}):
            analyzer._call_openai_compatible(
                "https://api.x.ai/v1", lambda: (_ for _ in ()).throw(RuntimeError), "p",
            )

        assert "temperature" in client.chat.completions.create.call_args.kwargs


# --------------------------------------------------------------------------- #
#  2. El texto se busca por tipo de bloque                                     #
# --------------------------------------------------------------------------- #

class TestLecturaDelContenido:

    def test_un_thinking_block_adelante_no_rompe(self):
        client = MagicMock()
        client.messages.create.return_value = _message(
            [_thinking_block(), _text_block('{"action": "HOLD"}')]
        )
        fake_sdk = SimpleNamespace(Anthropic=lambda **_kw: client)

        with patch.dict("sys.modules", {"anthropic": fake_sdk}):
            out = _claude_analyzer()._call_claude("prompt")

        assert out == '{"action": "HOLD"}'

    def test_sin_bloque_de_texto_la_causa_es_propia_no_un_attributeerror(self):
        client = MagicMock()
        client.messages.create.return_value = _message([_thinking_block()])
        fake_sdk = SimpleNamespace(Anthropic=lambda **_kw: client)

        with patch.dict("sys.modules", {"anthropic": fake_sdk}):
            with pytest.raises(AIUnavailable) as exc:
                _claude_analyzer()._call_claude("prompt")

        assert exc.value.cause == AI_FALLBACK.RESPUESTA_VACIA


# --------------------------------------------------------------------------- #
#  3. `stop_reason` antes que el contenido                                     #
# --------------------------------------------------------------------------- #

class TestStopReasonEsUnaCausaPropia:

    @pytest.mark.parametrize(
        "stop_reason, esperada",
        [
            ("max_tokens", AI_FALLBACK.RESPUESTA_TRUNCADA),
            ("refusal",    AI_FALLBACK.RECHAZO_MODELO),
        ],
    )
    def test_se_clasifica_antes_de_leer_el_contenido(self, stop_reason, esperada):
        client = MagicMock()
        # Contenido *parcial pero legible*: sin el chequeo de `stop_reason` esto
        # se devolvía y el parser fallaba después con «JSON inválido».
        client.messages.create.return_value = _message(
            [_text_block('{"action": "BU')], stop_reason=stop_reason,
        )
        fake_sdk = SimpleNamespace(Anthropic=lambda **_kw: client)

        with patch.dict("sys.modules", {"anthropic": fake_sdk}):
            with pytest.raises(AIUnavailable) as exc:
                _claude_analyzer()._call_claude("prompt")

        assert exc.value.cause == esperada
        assert classify_ai_failure(exc.value) == esperada

    def test_las_causas_nuevas_son_distinguibles_de_las_de_pr0(self):
        nuevas = {
            AI_FALLBACK.RESPUESTA_TRUNCADA,
            AI_FALLBACK.RECHAZO_MODELO,
            AI_FALLBACK.RESPUESTA_VACIA,
        }
        viejas = {
            AI_FALLBACK.JSON_INVALIDO,
            AI_FALLBACK.PARAMETRO_RECHAZADO,
            AI_FALLBACK.OTRO,
        }
        assert not (nuevas & viejas)

        # Y cada una llega a la UI con su propio texto, no degradada a `otro`.
        for cause in nuevas:
            assert AI_FALLBACK.label(cause) != AI_FALLBACK.label(AI_FALLBACK.OTRO)
            msg = AI_FALLBACK.message(cause, "claude")
            assert msg != AI_FALLBACK.message(AI_FALLBACK.OTRO, "claude")
            assert "Claude" in msg

    def test_end_turn_devuelve_el_texto(self):
        client = MagicMock()
        client.messages.create.return_value = _message([_text_block("ok")], "end_turn")
        fake_sdk = SimpleNamespace(Anthropic=lambda **_kw: client)

        with patch.dict("sys.modules", {"anthropic": fake_sdk}):
            assert _claude_analyzer()._call_claude("p") == "ok"


# --------------------------------------------------------------------------- #
#  4. El catálogo del selector                                                 #
# --------------------------------------------------------------------------- #

class TestCatalogoDeModelos:

    def test_settings_usa_el_catalogo_de_config(self):
        # El selector no puede tener su propia lista: la que tenía ofrecía un ID
        # que la llamada rechazaba, alcanzable desde la UI sin tocar código.
        # Se miran sólo las líneas de código: los comentarios del PR nombran los
        # IDs viejos a propósito, para explicar por qué se fueron.
        path = Path(__file__).resolve().parents[1] / "dashboard/pages/9_Settings.py"
        codigo = [
            ln for ln in path.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")
        ]
        assert any("CLAUDE_MODEL_CATALOG" in ln for ln in codigo)
        for viejo in ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"):
            assert not any(viejo in ln for ln in codigo), f"{viejo} sigue en el selector"

    def test_ningun_id_del_catalogo_rechaza_la_llamada_que_el_branch_hace(self):
        # La llamada no manda sampling, así que los modelos que lo rechazan son
        # utilizables igual. El invariante real: la lista es consistente con lo
        # que `_call_claude` manda, no con lo que mandaba antes.
        kwargs = _call_claude_capturing(_message([_text_block("ok")]))
        rechazan_algo = set(kwargs) & set(_SAMPLING_PARAMS)
        assert not rechazan_algo, (
            f"{sorted(rechazan_algo)} vuelve inutilizable a "
            f"{sorted(set(CLAUDE_MODEL_CATALOG) & CLAUDE_MODELS_SIN_SAMPLING)}"
        )

    def test_el_default_de_aiconfig_esta_en_el_catalogo(self, monkeypatch):
        monkeypatch.delenv("AI_MODEL", raising=False)
        assert AIConfig(provider="claude", api_key="k").model in CLAUDE_MODEL_CATALOG
