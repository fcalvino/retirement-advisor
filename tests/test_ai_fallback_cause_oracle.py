"""Oráculo: el fallback rule-based deja de mentir sobre su causa (PR 0).

Antes, `AIAnalyzer.analyze` y las tres `generate_*` envolvían todo en un
`except Exception` con un solo `logger.warning`: en la UI, **un 400 de la API,
una API key ausente y una key inválida se veían exactamente igual** — un
veredicto rule-based sin ninguna señal de que la IA no corrió.

Lo que este archivo fija no es una lista de casos sino tres invariantes:

1. **La key se resuelve por proveedor.** `AIConfig(provider="claude")` con sólo
   `XAI_API_KEY` seteada no tiene key — antes le mandaba la key de xAI a
   Anthropic, cobraba un 401 y lo escondía detrás del fallback.
2. **La causa viaja, y es distinguible.** `sin_api_key` ≠ `parametro_rechazado`
   ≠ `key_invalida` ≠ `rate_limit` ≠ `json_invalido`, en las cuatro superficies.
3. **La visibilidad cambia; el comportamiento no.** La acción del camino de
   fallback sigue siendo **idéntica** a la de `RetirementStrategy().decide(...)`
   sobre el mismo input.

Más la invariante de UI que hace cumplir *«ningún string nombra un proveedor
distinto del configurado»*.

**Limitación anotada:** `parametro_rechazado` no se puede verificar contra la
API real mientras `_call_claude` mande `temperature=0` (§0.2 del plan, es PR 1),
porque *toda* llamada a un modelo actual vuelve 400. Acá se verifica con cliente
mockeado, que es exactamente el mecanismo que la UI va a ver.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from analysis.ai_analyzer import AIAnalyzer, AIUnavailable, classify_ai_failure
from analysis.strategy import RetirementStrategy, apply_safety_overlay
from config import (
    AI_FALLBACK,
    AI_OAUTH_PROVIDERS,
    AI_PROVIDER_DISPLAY,
    AI_PROVIDER_KEY_ENV,
    AIConfig,
)

_ALL_CAUSES = [
    AI_FALLBACK.SIN_API_KEY,
    AI_FALLBACK.KEY_INVALIDA,
    AI_FALLBACK.PARAMETRO_RECHAZADO,
    AI_FALLBACK.RATE_LIMIT,
    AI_FALLBACK.JSON_INVALIDO,
    AI_FALLBACK.OTRO,
]


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _clear_ai_env(monkeypatch) -> None:
    for var in set(AI_PROVIDER_KEY_ENV.values()) | {"AI_API_KEY"}:
        monkeypatch.delenv(var, raising=False)


def _cfg(provider: str = "claude", **kw) -> AIConfig:
    return AIConfig(provider=provider, model="test-model", enabled=True, **kw)


def _fund(score: float = 72.0) -> SimpleNamespace:
    return SimpleNamespace(
        symbol="TEST",
        company_name="Test Co",
        sector="Technology",
        total_score=score,
        adjusted_score=score,
        is_crypto=False,
        debt_equity=0.5,
        pb_ratio=2.0,
        negative_equity=False,
        margin_of_safety_pct=25.0,
        graham_value=100.0,
        is_value_stock=lambda: True,
        roe=20.0,
        revenue_cagr_5y=10.0,
        fcf_yield=4.0,
        payout_ratio=40.0,
        warnings=[],
        data_quality=None,
        tailwind_classification="Neutral",
        tailwind_detail=None,
    )


def _tech(signal: str = "BULLISH") -> SimpleNamespace:
    return SimpleNamespace(
        signal=signal,
        above_sma200=True,
        price_vs_52w_low_pct=20.0,
        rsi_weekly=55.0,
        golden_cross=False,
        sma200_slope_pct=2.0,
        warnings=[],
    )


class _FakeStatusError(Exception):
    """Lo que hacen `anthropic` y `openai`: exponer `status_code` en la excepción."""

    def __init__(self, status_code: int):
        super().__init__(f"api error {status_code}")
        self.status_code = status_code


def _raiser(exc: BaseException):
    def _inner(*_a, **_kw):
        raise exc
    return _inner


# Causa → excepción que la produce, para barrer las cuatro superficies con una
# sola tabla. `sin_api_key` no está: no es una excepción, es un pre-chequeo.
_EXC_FOR_CAUSE = {
    AI_FALLBACK.KEY_INVALIDA:        _FakeStatusError(401),
    AI_FALLBACK.PARAMETRO_RECHAZADO: _FakeStatusError(400),
    AI_FALLBACK.RATE_LIMIT:          _FakeStatusError(429),
    AI_FALLBACK.JSON_INVALIDO:       ValueError("Unmatched '{' in AI response"),
    AI_FALLBACK.OTRO:                ConnectionResetError("socket closed"),
}


# --------------------------------------------------------------------------- #
#  1. La key se resuelve por proveedor (criterio de aceptación)                 #
# --------------------------------------------------------------------------- #

class TestLaKeySeResuelvePorProveedor:

    @pytest.mark.parametrize("provider,env_var", sorted(AI_PROVIDER_KEY_ENV.items()))
    def test_cada_proveedor_lee_solo_su_variable(self, monkeypatch, provider, env_var):
        _clear_ai_env(monkeypatch)
        monkeypatch.setenv(env_var, "k-" + provider)
        assert _cfg(provider).api_key == "k-" + provider

    def test_gate_claude_con_solo_xai_api_key_no_tiene_key(self, monkeypatch):
        """El defecto original, exacto: `ANTHROPIC_API_KEY or XAI_API_KEY or ...`."""
        _clear_ai_env(monkeypatch)
        monkeypatch.setenv("XAI_API_KEY", "xai-secret")
        cfg = _cfg("claude")
        assert cfg.api_key == "", (
            "con provider='claude' y sólo XAI_API_KEY seteada, la config resolvió "
            f"{cfg.api_key!r} — le está mandando una key de xAI a Anthropic"
        )

    def test_ai_api_key_sigue_siendo_el_override_generico(self, monkeypatch):
        _clear_ai_env(monkeypatch)
        monkeypatch.setenv("AI_API_KEY", "generic")
        assert _cfg("openai").api_key == "generic"

    def test_la_key_explicita_gana(self, monkeypatch):
        """Settings y varios tests construyen `AIConfig(api_key="k")` a mano."""
        _clear_ai_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "del-entorno")
        assert _cfg("claude", api_key="explicita").api_key == "explicita"

    def test_config_validator_usa_la_misma_tabla(self):
        """Validador y runtime discrepaban; ahora comparten el objeto."""
        import config_validator

        assert config_validator.AI_PROVIDER_KEY_ENV is AI_PROVIDER_KEY_ENV
        assert config_validator.AI_OAUTH_PROVIDERS is AI_OAUTH_PROVIDERS


# --------------------------------------------------------------------------- #
#  2. classify_ai_failure                                                      #
# --------------------------------------------------------------------------- #

class TestClasificacionDeLaExcepcion:

    @pytest.mark.parametrize("status,cause", [
        (400, AI_FALLBACK.PARAMETRO_RECHAZADO),
        (401, AI_FALLBACK.KEY_INVALIDA),
        (403, AI_FALLBACK.KEY_INVALIDA),
        (429, AI_FALLBACK.RATE_LIMIT),
    ])
    def test_status_code_por_duck_typing(self, status, cause):
        assert classify_ai_failure(_FakeStatusError(status)) == cause

    def test_status_code_anidado_en_response(self):
        exc = Exception("boom")
        exc.response = SimpleNamespace(status_code=429)
        assert classify_ai_failure(exc) == AI_FALLBACK.RATE_LIMIT

    @pytest.mark.parametrize("name,cause", [
        ("AuthenticationError", AI_FALLBACK.KEY_INVALIDA),
        ("BadRequestError", AI_FALLBACK.PARAMETRO_RECHAZADO),
        ("RateLimitError", AI_FALLBACK.RATE_LIMIT),
    ])
    def test_nombre_de_clase_cuando_no_viaja_status_code(self, name, cause):
        klass = type(name, (Exception,), {})
        assert classify_ai_failure(klass("sin status")) == cause

    def test_tipos_reales_del_sdk_de_anthropic(self):
        """Se prefiere el tipado del SDK sobre el string-matching."""
        anthropic = pytest.importorskip("anthropic")
        for attr, cause in [
            ("AuthenticationError", AI_FALLBACK.KEY_INVALIDA),
            ("BadRequestError", AI_FALLBACK.PARAMETRO_RECHAZADO),
            ("RateLimitError", AI_FALLBACK.RATE_LIMIT),
        ]:
            klass = getattr(anthropic, attr, None)
            if klass is None:      # SDK más viejo: el caso ya lo cubre el fake
                continue
            exc = klass.__new__(klass)          # sin tocar el __init__ del SDK
            Exception.__init__(exc, attr)
            assert classify_ai_failure(exc) == cause, attr

    @pytest.mark.parametrize("exc", [
        ValueError("Could not extract JSON from AI response"),
        json.JSONDecodeError("Expecting value", "{", 0),
        RuntimeError("Incomplete JSON: unmatched '{'"),
    ])
    def test_respuesta_no_parseable(self, exc):
        assert classify_ai_failure(exc) == AI_FALLBACK.JSON_INVALIDO

    def test_lo_desconocido_no_se_disfraza(self):
        assert classify_ai_failure(ConnectionResetError("socket")) == AI_FALLBACK.OTRO

    def test_el_preflight_no_se_reclasifica(self):
        assert classify_ai_failure(AIUnavailable(AI_FALLBACK.SIN_API_KEY)) == AI_FALLBACK.SIN_API_KEY


# --------------------------------------------------------------------------- #
#  3. analyze end-to-end: la causa viaja y la acción no se mueve               #
# --------------------------------------------------------------------------- #

class TestAnalyzePropagaLaCausaSinCambiarElVeredicto:

    @pytest.fixture(autouse=True)
    def _prompt_neutro(self):
        """El texto del prompt es materia de PR 2; acá sólo importa el embudo."""
        with patch.object(AIAnalyzer, "_build_prompt", lambda *a, **k: "PROMPT"):
            yield

    @pytest.mark.parametrize("cause", sorted(_EXC_FOR_CAUSE))
    def test_cada_causa_llega_a_la_decision(self, monkeypatch, cause):
        _clear_ai_env(monkeypatch)
        cfg = _cfg("claude", api_key="k")
        fund, tech = _fund(), _tech()
        with patch.object(AIAnalyzer, "_call_api", _raiser(_EXC_FOR_CAUSE[cause])):
            decision = AIAnalyzer(cfg).analyze(fund, tech)
        assert decision.ai_fallback_reason == cause
        assert decision.ai_used is False

    @pytest.mark.parametrize("cause", sorted(_EXC_FOR_CAUSE))
    @pytest.mark.parametrize("signal", ["BULLISH", "BEARISH", "NEUTRAL"])
    def test_la_accion_es_identica_a_la_del_motor(self, monkeypatch, cause, signal):
        """El fallback cambia de visibilidad, no de comportamiento."""
        _clear_ai_env(monkeypatch)
        cfg = _cfg("claude", api_key="k")
        # Inputs equivalentes pero independientes: `decide()` escribe en
        # `fund.warnings`, así que reusar el objeto compararía dos estados.
        _f, _t = _fund(), _tech(signal)
        _rule = RetirementStrategy().decide(_f, _t)
        # El overlay ya corría sobre el veredicto del motor antes de este PR
        # (es el `rule_decision=` de `analyze`); la referencia es esa, entera.
        esperada = apply_safety_overlay(_rule, _f, _t, rule_decision=_rule)
        with patch.object(AIAnalyzer, "_call_api", _raiser(_EXC_FOR_CAUSE[cause])):
            obtenida = AIAnalyzer(cfg).analyze(_fund(), _tech(signal))
        assert obtenida.action == esperada.action, (
            f"causa={cause} signal={signal}: el fallback devolvió {obtenida.action} "
            f"y el motor {esperada.action} — el fallback cambió de comportamiento"
        )
        assert obtenida.confidence == esperada.confidence
        assert obtenida.decisive_reason == esperada.decisive_reason

    def test_sin_api_key_no_gasta_la_llamada(self, monkeypatch):
        _clear_ai_env(monkeypatch)
        cfg = _cfg("claude")
        assert cfg.api_key == ""
        llamadas = []
        with patch.object(AIAnalyzer, "_call_api", lambda *a, **k: llamadas.append(1)):
            decision = AIAnalyzer(cfg).analyze(_fund(), _tech())
        assert decision.ai_fallback_reason == AI_FALLBACK.SIN_API_KEY
        assert llamadas == [], "el pre-chequeo debería evitar el round-trip"

    def test_el_exito_no_deja_causa(self, monkeypatch):
        _clear_ai_env(monkeypatch)
        cfg = _cfg("claude", api_key="k")
        raw = json.dumps({"action": "HOLD", "confidence": "MEDIUM", "rationale": []})
        with patch.object(AIAnalyzer, "_call_api", lambda *a, **k: raw):
            decision = AIAnalyzer(cfg).analyze(_fund(), _tech())
        assert decision.ai_used is True
        assert decision.ai_fallback_reason == ""


# --------------------------------------------------------------------------- #
#  4. sin_api_key ≠ parametro_rechazado, y OAuth no es "sin key"               #
# --------------------------------------------------------------------------- #

class TestLasCausasSonDistinguibles:

    @pytest.fixture(autouse=True)
    def _prompt_neutro(self):
        with patch.object(AIAnalyzer, "_build_prompt", lambda *a, **k: "PROMPT"):
            yield

    def test_sin_api_key_no_se_confunde_con_parametro_rechazado(self, monkeypatch):
        _clear_ai_env(monkeypatch)
        sin_key = AIAnalyzer(_cfg("claude")).analyze(_fund(), _tech())
        with patch.object(AIAnalyzer, "_call_api", _raiser(_FakeStatusError(400))):
            con_400 = AIAnalyzer(_cfg("claude", api_key="k")).analyze(_fund(), _tech())
        assert sin_key.ai_fallback_reason == AI_FALLBACK.SIN_API_KEY
        assert con_400.ai_fallback_reason == AI_FALLBACK.PARAMETRO_RECHAZADO
        assert sin_key.ai_fallback_reason != con_400.ai_fallback_reason

    @pytest.mark.parametrize("provider", sorted(AI_OAUTH_PROVIDERS))
    def test_los_proveedores_oauth_sin_key_no_caen_en_sin_api_key(self, monkeypatch, provider):
        """`xai`/`nous` autentican por Hermes OAuth: key vacía es su estado normal."""
        _clear_ai_env(monkeypatch)
        cfg = _cfg(provider)
        assert cfg.api_key == ""
        with patch.object(AIAnalyzer, "_call_api", _raiser(_FakeStatusError(429))):
            decision = AIAnalyzer(cfg).analyze(_fund(), _tech())
        assert decision.ai_fallback_reason == AI_FALLBACK.RATE_LIMIT


# --------------------------------------------------------------------------- #
#  5. json_invalido nace en _parse_response                                    #
# --------------------------------------------------------------------------- #

class TestJsonInvalido:

    @pytest.fixture(autouse=True)
    def _prompt_neutro(self):
        with patch.object(AIAnalyzer, "_build_prompt", lambda *a, **k: "PROMPT"):
            yield

    def test_parse_response_con_raw_sin_json(self, monkeypatch):
        _clear_ai_env(monkeypatch)
        analyzer = AIAnalyzer(_cfg("claude", api_key="k"))
        with pytest.raises(ValueError) as err:
            analyzer._parse_response("lo siento, no puedo ayudarte", _fund(), _tech())
        assert classify_ai_failure(err.value) == AI_FALLBACK.JSON_INVALIDO

    def test_llega_a_la_decision_como_json_invalido(self, monkeypatch):
        _clear_ai_env(monkeypatch)
        cfg = _cfg("claude", api_key="k")
        with patch.object(AIAnalyzer, "_call_api", lambda *a, **k: "no soy json"):
            decision = AIAnalyzer(cfg).analyze(_fund(), _tech())
        assert decision.ai_fallback_reason == AI_FALLBACK.JSON_INVALIDO


# --------------------------------------------------------------------------- #
#  6. Invariante de UI: ningún mensaje nombra otro proveedor                   #
# --------------------------------------------------------------------------- #

class TestNingunStringNombraOtroProveedor:

    @pytest.mark.parametrize("provider", sorted(AI_PROVIDER_DISPLAY))
    @pytest.mark.parametrize("cause", _ALL_CAUSES)
    def test_el_mensaje_solo_nombra_al_proveedor_configurado(self, provider, cause):
        msg = AI_FALLBACK.message(cause, provider)
        assert AI_PROVIDER_DISPLAY[provider] in msg
        for otro, display in AI_PROVIDER_DISPLAY.items():
            if otro == provider:
                continue
            # "Grok (xAI)" vs "Claude (Anthropic)": se comparan las marcas, que
            # es lo que el usuario lee.
            marca = display.split(" (")[0]
            assert marca.lower() not in msg.lower(), (
                f"el mensaje de {cause} para {provider} nombra a {otro}: {msg!r}"
            )

    @pytest.mark.parametrize("cause", _ALL_CAUSES)
    def test_toda_causa_tiene_etiqueta_y_mensaje(self, cause):
        assert AI_FALLBACK.label(cause)
        assert "{provider}" not in AI_FALLBACK.message(cause, "claude")

    def test_una_causa_desconocida_degrada_al_generico(self):
        assert AI_FALLBACK.label("inventada") == AI_FALLBACK.label(AI_FALLBACK.OTRO)
        assert AI_FALLBACK.message("inventada", "claude") == AI_FALLBACK.message(
            AI_FALLBACK.OTRO, "claude"
        )


# --------------------------------------------------------------------------- #
#  Las tres generate_* reciben el mismo barrido                                #
# --------------------------------------------------------------------------- #

_OPT_RESULT = SimpleNamespace(
    tickers=[SimpleNamespace(
        symbol="AAPL", weight_pct=50.0, adjusted_score=80.0, moat_score=9.0,
        dividend_yield_pct=1.0, expected_return_pct=8.0, volatility_pct=18.0,
        sector="Technology", is_ars=False, tailwind_score=0.0,
        tailwind_classification="Neutral",
    )],
    sector_weights={"Technology": 100.0},
    profile_core_holdings=[{"symbol": "AAPL", "suggested_weight_pct": 50.0, "why": "moat"}],
    profile_name="Moderado",
    expected_return_pct=8.0, volatility_pct=18.0, sharpe_ratio=0.4,
    dividend_yield_pct=1.0, moat_score_avg=9.0,
    rebalance_rationale="", warnings=[],
)

_SNAPSHOT = SimpleNamespace(
    name="Mi Plan", profile_name="Moderado", personal=None, metrics={},
    core_holdings=[], allocation=[], sector_weights={}, goals=[],
    mc_summary=None, withdrawal_strategy=None,
)

_LONG_TERM_CTX = {"profile_name": "Moderado", "tickers": ["AAPL"], "weights": [100.0]}


class TestLasTresNarrativasPropaganLaCausa:

    @pytest.mark.parametrize("cause", sorted(_EXC_FOR_CAUSE))
    @pytest.mark.parametrize("surface", [
        "generate_long_term_narrative", "generate_plan_narrative", "generate_optimizer_advice",
    ])
    def test_cada_superficie_devuelve_la_causa(self, monkeypatch, cause, surface):
        _clear_ai_env(monkeypatch)
        analyzer = AIAnalyzer(_cfg("claude", api_key="k"))
        arg = {
            "generate_long_term_narrative": _LONG_TERM_CTX,
            "generate_plan_narrative": _SNAPSHOT,
            "generate_optimizer_advice": _OPT_RESULT,
        }[surface]
        with patch.object(AIAnalyzer, "_call_api", _raiser(_EXC_FOR_CAUSE[cause])):
            out = getattr(analyzer, surface)(arg)
        assert isinstance(out, dict), f"{surface} debe devolver dict"
        assert out["ai_fallback_reason"] == cause
        assert out["narrative"] == AI_FALLBACK.message(cause, "claude")

    @pytest.mark.parametrize("surface", [
        "generate_long_term_narrative", "generate_plan_narrative", "generate_optimizer_advice",
    ])
    def test_sin_api_key_tambien_viaja(self, monkeypatch, surface):
        _clear_ai_env(monkeypatch)
        analyzer = AIAnalyzer(_cfg("claude"))
        arg = {
            "generate_long_term_narrative": _LONG_TERM_CTX,
            "generate_plan_narrative": _SNAPSHOT,
            "generate_optimizer_advice": _OPT_RESULT,
        }[surface]
        out = getattr(analyzer, surface)(arg)
        assert out["ai_fallback_reason"] == AI_FALLBACK.SIN_API_KEY

    def test_el_optimizer_conserva_el_nucleo_deterministico(self, monkeypatch):
        """El fallback no puede costarle al usuario la parte que sí se calculó."""
        _clear_ai_env(monkeypatch)
        analyzer = AIAnalyzer(_cfg("claude", api_key="k"))
        with patch.object(AIAnalyzer, "_call_api", _raiser(_FakeStatusError(400))):
            out = analyzer.generate_optimizer_advice(_OPT_RESULT)
        assert out["core_holdings"] == _OPT_RESULT.profile_core_holdings
