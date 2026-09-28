"""Oráculo LLM-6: cada llamada a un LLM registra sus tokens y su costo.

`AIAnalyzer._call_api` devolvía el texto y descartaba la respuesta con su
``usage``: ninguna superficie sabía cuánto gastaba, y #151 (30 dictámenes del
comité en vivo) no podía medir su costo, sólo estimarlo.

Invariantes:

1. Una línea ``llm_usage`` y un registro por llamada, en las tres ramas
   (Anthropic, OpenAI, OpenAI-compatible → Groq/xAI/Nous).
2. Se registra **antes** de extraer el texto: una respuesta truncada se cobra
   aunque levante `AIUnavailable`.
3. Lo que no se midió es ``None``, no 0 (sin ``usage``, modelo sin precio).
4. `USAGE.capture()` junta las llamadas de todos los hilos (el comité corre sus
   voces en un pool).
5. Medir no rompe la llamada.
6. Una corrida del banco de eval guarda su ``usage``.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

from analysis import llm_usage
from analysis.ai_analyzer import AIAnalyzer, AIUnavailable
from analysis.eval_harness import EvalReport, report_to_dict
from analysis.llm_usage import USAGE, UsageRecord, cost_usd, extract_usage, summarize
from config import LLM_PRICES, AIConfig

# --------------------------------------------------------------------------- #
#  Dobles de las respuestas del SDK                                            #
# --------------------------------------------------------------------------- #

def _claude_message(stop_reason="end_turn", usage=True):
    msg = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="ok")],
        stop_reason=stop_reason,
    )
    if usage:
        msg.usage = SimpleNamespace(input_tokens=1200, output_tokens=300,
                                    cache_read_input_tokens=0,
                                    cache_creation_input_tokens=0)
    return msg


def _openai_response(finish_reason="stop", usage=True):
    resp = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content="ok"), finish_reason=finish_reason,
    )])
    if usage:
        resp.usage = SimpleNamespace(prompt_tokens=2000, completion_tokens=500,
                                     total_tokens=2500)
    return resp


def _run_claude(message, model="claude-sonnet-5"):
    client = MagicMock()
    client.messages.create.return_value = message
    with patch.dict("sys.modules", {"anthropic": SimpleNamespace(Anthropic=lambda **_k: client)}):
        return AIAnalyzer(AIConfig(provider="claude", model=model, api_key="k"))._call_api("p")


def _run_openai_like(provider, model, response):
    client = MagicMock()
    client.chat.completions.create.return_value = response
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=lambda **_k: client)}):
        return AIAnalyzer(AIConfig(provider=provider, model=model, api_key="k"))._call_api("p")


@pytest.fixture
def log_lines():
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="INFO", format="{message}")
    yield lines
    logger.remove(sink)


def _usage_lines(lines):
    return [ln for ln in lines if ln.startswith("llm_usage ")]


# --------------------------------------------------------------------------- #
#  1. Una línea y un registro por llamada, en cada rama                        #
# --------------------------------------------------------------------------- #

class TestCadaRamaRegistra:

    def test_claude(self, log_lines):
        with USAGE.capture() as cap:
            assert _run_claude(_claude_message()) == "ok"
        assert cap == [UsageRecord("claude", "claude-sonnet-5", 1200, 300, "end_turn",
                                   cost_usd("claude-sonnet-5", 1200, 300))]
        assert len(_usage_lines(log_lines)) == 1
        assert "in=1200 out=300" in _usage_lines(log_lines)[0]

    def test_openai(self, log_lines):
        with USAGE.capture() as cap:
            _run_openai_like("openai", "gpt-x", _openai_response())
        assert [(r.provider, r.input_tokens, r.output_tokens, r.stop) for r in cap] == [
            ("openai", 2000, 500, "stop")]
        assert len(_usage_lines(log_lines)) == 1

    def test_groq_por_el_camino_openai_compatible(self, log_lines):
        with USAGE.capture() as cap:
            _run_openai_like("groq", "openai/gpt-oss-120b", _openai_response())
        (rec,) = cap
        assert (rec.provider, rec.model, rec.input_tokens, rec.output_tokens) == (
            "groq", "openai/gpt-oss-120b", 2000, 500)
        # 2000 × 0,15 + 500 × 0,60 por millón
        assert rec.cost_usd == pytest.approx(0.0006)
        assert len(_usage_lines(log_lines)) == 1


# --------------------------------------------------------------------------- #
#  2. Se cobra aunque la respuesta no sirva                                    #
# --------------------------------------------------------------------------- #

class TestUnaRespuestaTruncadaIgualSeRegistra:

    def test_claude_max_tokens(self):
        with USAGE.capture() as cap, pytest.raises(AIUnavailable):
            _run_claude(_claude_message(stop_reason="max_tokens"))
        assert [(r.stop, r.output_tokens) for r in cap] == [("max_tokens", 300)]

    def test_groq_length(self):
        with USAGE.capture() as cap, pytest.raises(AIUnavailable):
            _run_openai_like("groq", "openai/gpt-oss-120b", _openai_response(finish_reason="length"))
        assert [(r.stop, r.output_tokens) for r in cap] == [("length", 500)]


# --------------------------------------------------------------------------- #
#  3. No medido es None, no 0                                                  #
# --------------------------------------------------------------------------- #

class TestNoMedidoEsNone:

    def test_sin_usage(self):
        with USAGE.capture() as cap:
            _run_claude(_claude_message(usage=False))
        (rec,) = cap
        assert (rec.input_tokens, rec.output_tokens, rec.cost_usd) == (None, None, None)

    def test_un_mock_no_es_un_conteo(self):
        assert extract_usage(SimpleNamespace(usage=MagicMock())) == (None, None)

    def test_modelo_sin_precio(self):
        assert LLM_PRICES.get("modelo-inventado") is None
        with USAGE.capture() as cap:
            _run_openai_like("openai", "modelo-inventado", _openai_response())
        assert cap[0].input_tokens == 2000 and cap[0].cost_usd is None

    def test_el_resumen_no_esconde_lo_que_falta(self):
        recs = [
            UsageRecord("groq", "openai/gpt-oss-120b", 1000, 100, "stop", 0.00021),
            UsageRecord("openai", "modelo-inventado", 10, 1, "stop", None),
            UsageRecord("claude", "claude-sonnet-5", None, None, "end_turn", None),
        ]
        s = summarize(recs)
        assert s["n_calls"] == 3 and s["n_calls_without_usage"] == 1
        assert s["input_tokens"] is None and s["cost_usd"] is None
        assert s["cost_usd_known"] == pytest.approx(0.00021)
        assert s["by_model"]["groq/openai/gpt-oss-120b"]["cost_usd"] == pytest.approx(0.00021)

    def test_sin_llamadas_el_costo_es_cero_medido(self):
        assert summarize([])["cost_usd"] == 0.0

    def test_los_precios_cubren_los_dos_catalogos(self):
        from config import CLAUDE_MODEL_CATALOG, GROQ_MODEL_CATALOG
        for model in (*CLAUDE_MODEL_CATALOG, *GROQ_MODEL_CATALOG):
            price = LLM_PRICES.get(model)
            assert price is not None, model
            assert price.as_of and price.source


# --------------------------------------------------------------------------- #
#  4–5. Hilos, y medir no rompe                                                #
# --------------------------------------------------------------------------- #

def test_capture_junta_las_llamadas_de_todos_los_hilos():
    with USAGE.capture() as cap:
        threads = [threading.Thread(target=_run_openai_like,
                                    args=("groq", "openai/gpt-oss-120b", _openai_response()))
                   for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert len(cap) == 6
    assert summarize(cap)["input_tokens"] == 12000


def test_fuera_de_un_capture_no_se_acumula_nada():
    _run_claude(_claude_message())
    with USAGE.capture() as cap:
        pass
    assert cap == []


def test_si_registrar_falla_la_llamada_sigue(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("medidor roto")
    monkeypatch.setattr(llm_usage, "extract_usage", _boom)
    assert _run_claude(_claude_message()) == "ok"


# --------------------------------------------------------------------------- #
#  6. El JSON de una corrida trae su usage                                     #
# --------------------------------------------------------------------------- #

def test_report_to_dict_incluye_usage():
    report = EvalReport(results=[])
    assert report_to_dict(report, bank="committee", provider_name="groq")["usage"] is None
    report.usage = summarize([UsageRecord("groq", "openai/gpt-oss-120b", 10, 5, "stop", 0.1)])
    assert report_to_dict(report, bank="committee", provider_name="groq")["usage"]["n_calls"] == 1
