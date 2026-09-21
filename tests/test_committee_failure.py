"""A failed AI panel must never masquerade as an investment recommendation."""

import json

import pytest
from loguru import logger

from analysis.committee import (
    AgentOpinion,
    CommitteeAnalyzer,
    _parse_agent,
    _parse_fundamental,
    _verdict_from_dict,
    _verdict_to_dict,
    aggregate,
)
from config import AI_FALLBACK, COMMITTEE


class AuthenticationFailure(RuntimeError):
    status_code = 401


def test_authentication_failure_is_unavailable_and_does_not_expose_credentials():
    secret = "gsk_test_secret_do_not_expose"
    calls = []
    messages = []

    def fail(prompt):
        calls.append(prompt)
        raise AuthenticationFailure(f"Invalid API Key: {secret}")

    handler = logger.add(lambda message: messages.append(str(message)))
    try:
        analyzer = CommitteeAnalyzer(call_fn=fail, use_cache=False)
        jobs = {str(i): ("prompt", _parse_fundamental) for i in range(6)}
        opinions = analyzer._run_agents(jobs)
    finally:
        logger.remove(handler)
    verdict = aggregate("MSFT", opinions)

    assert len(calls) == 6  # Authentication failures are not retried.
    assert verdict.action == "UNAVAILABLE"
    assert verdict.confidence == "LOW"
    assert not verdict.available
    assert not verdict.complete
    assert verdict.failure_causes == [AI_FALLBACK.KEY_INVALIDA]
    assert all(op.error_cause == AI_FALLBACK.KEY_INVALIDA for op in opinions)
    assert secret not in json.dumps(_verdict_to_dict(verdict))
    assert secret not in "".join(messages)
    assert AI_FALLBACK.KEY_INVALIDA in "".join(messages)
    with pytest.raises(ValueError, match="unavailable"):
        verdict.to_decision()


@pytest.mark.parametrize("parser", [lambda raw: _parse_agent("Macro", raw), _parse_fundamental])
def test_unparseable_vote_reports_safe_classified_failure(parser):
    opinion = parser("not valid json")
    assert not opinion.ok
    assert opinion.error_cause == AI_FALLBACK.JSON_INVALIDO


def test_partial_panel_preserves_valid_vote_and_failure_cause_roundtrip():
    verdict = aggregate("MSFT", [
        AgentOpinion("Analista Fundamental", "BUY", "HIGH"),
        AgentOpinion("Macro", "HOLD", "LOW", error="key_invalida", error_cause=AI_FALLBACK.KEY_INVALIDA),
    ])
    restored = _verdict_from_dict(_verdict_to_dict(verdict))
    assert restored.available and not restored.complete
    assert restored.action == "BUY"
    assert restored.failure_causes == [AI_FALLBACK.KEY_INVALIDA]
    assert restored.to_decision().action == "BUY"


def test_legacy_cached_opinion_without_error_cause_still_loads():
    verdict = _verdict_from_dict({"symbol": "MSFT", "action": "BUY", "opinions": [
        {"role": "Analista Fundamental", "stance": "BUY", "confidence": "HIGH"},
    ]})
    assert verdict.available and verdict.complete
    assert verdict.failure_causes == []


def test_empty_panel_is_unavailable():
    verdict = aggregate("MSFT", [])
    assert verdict.action == "UNAVAILABLE"
    assert not verdict.available


# --------------------------------------------------------------------------- #
#  HOLD silencioso — un voto fuera del vocabulario no es un voto neutro        #
# --------------------------------------------------------------------------- #
#  `_parse_agent`/`_parse_fundamental` coercían a HOLD todo `stance`/`action`
#  ausente o fuera de `_STANCE_SCORE`, y lo devolvían con `ok=True`. El voto
#  entraba al promedio ponderado con su peso completo y score 0.0, así que un
#  fallo de formato del modelo arrastraba el lean al centro, `complete` seguía
#  en True y el veredicto se cacheaba 24 h y se registraba en el Track Record
#  sin una sola señal de fallo. Es el mismo patrón que `temperature=0` en la IA
#  de Ajustes: el fallo existe y el usuario ve un resultado plausible.

_MALFORMED_VOTES = [
    ('{"stance": "STRONG_BUY", "confidence": "HIGH"}', "guion bajo en vez de espacio"),
    ('{"stance": "COMPRAR", "confidence": "HIGH"}', "vocabulario en español"),
    ('{"confidence": "HIGH", "key_points": ["p"]}', "sin la clave stance"),
    ('{"stance": ["BUY"], "confidence": "HIGH"}', "stance como lista"),
    ('{"stance": null, "confidence": "HIGH"}', "stance nulo"),
]


@pytest.mark.parametrize("raw,label", _MALFORMED_VOTES)
def test_vote_outside_the_stance_vocabulary_is_a_failure_not_a_hold(raw, label):
    opinion = _parse_agent("Estratega Macro", raw)
    assert not opinion.ok, label
    assert opinion.error_cause == AI_FALLBACK.JSON_INVALIDO, label


@pytest.mark.parametrize("raw,label", _MALFORMED_VOTES)
def test_fundamental_vote_outside_the_vocabulary_is_a_failure_too(raw, label):
    opinion = _parse_fundamental(raw.replace('"stance"', '"action"'))
    assert not opinion.ok, label
    assert opinion.error_cause == AI_FALLBACK.JSON_INVALIDO, label


def test_invalid_confidence_does_not_invalidate_an_otherwise_valid_vote():
    """`confidence` no entra al lean: descartar el voto tiraría lo que sí lo mueve."""
    opinion = _parse_agent("Estratega Macro", '{"stance": "BUY", "confidence": "SEGURO"}')
    assert opinion.ok
    assert opinion.stance == "BUY"
    assert opinion.confidence == "MEDIUM"


def _ticker_panel(macro_raw):
    return aggregate("ACME", [
        _parse_fundamental('{"action": "BUY", "confidence": "MEDIUM"}'),
        _parse_agent("Estratega Macro", macro_raw),
        _parse_agent("Abogado del Diablo", '{"stance": "REDUCE", "confidence": "MEDIUM"}'),
        _parse_agent("Portfolio Manager", '{"stance": "BUY", "confidence": "MEDIUM"}'),
        _parse_agent("Behavioral Coach", '{"stance": "HOLD", "confidence": "MEDIUM"}'),
    ])


def test_malformed_vote_never_passes_as_a_complete_panel():
    """El caso reproducible: un `STRONG_BUY` del Macro volteaba BUY → HOLD en silencio.

    Perder un votante alcista **sí** puede mover el lean — eso es correcto. Lo que
    no puede pasar es que el resultado se presente como un panel completo: sin
    `complete` no hay aviso en la UI, ni caché de 24 h, ni fila en el Track Record.
    """
    healthy = _ticker_panel('{"stance": "BUY", "confidence": "MEDIUM"}')
    assert healthy.action == "BUY" and healthy.complete
    assert healthy.failure_causes == []

    broken = _ticker_panel('{"stance": "STRONG_BUY", "confidence": "MEDIUM"}')
    assert not broken.complete, "un voto ilegible no puede rendir un panel completo"
    assert broken.failure_causes == [AI_FALLBACK.JSON_INVALIDO]
    assert broken.available, "los otros cuatro votos siguen siendo utilizables"


def test_excluded_vote_renormalises_instead_of_counting_as_zero():
    """La distinción que arregla el defecto: abstenerse ≠ votar HOLD.

    Es la misma regla que `_pays_dividend` ya aplica a la voz de Dividendo — una
    voz no convocada deja el lean intacto, un HOLD forzado lo diluye al centro.
    """
    broken = _ticker_panel('{"stance": "STRONG_BUY", "confidence": "MEDIUM"}')
    # Pesos: Fundamental 1.0 (+1), DA 0.7 (−1), PM 1.0 (+1), Coach 0.3 (0).
    excluded_lean = round((1.0 - 0.7 + 1.0) / (1.0 + 0.7 + 1.0 + 0.3), 4)
    counted_as_hold_lean = round((1.0 - 0.7 + 1.0) / 3.8, 4)  # el bug
    assert broken.lean == excluded_lean
    assert broken.lean > counted_as_hold_lean


# --------------------------------------------------------------------------- #
#  Quórum mínimo — un panel diezmado no publica el sesgo de un solo agente     #
# --------------------------------------------------------------------------- #

def _failed(role):
    return AgentOpinion(role, "HOLD", "LOW",
                        error=AI_FALLBACK.JSON_INVALIDO, error_cause=AI_FALLBACK.JSON_INVALIDO)


def test_devils_advocate_alone_does_not_produce_a_verdict():
    """Peso 0.7 de 3.8 = 18 %. Su mandato es direccional fijo: publicarlo como
    dictamen del comité sería publicar el bear case con el rótulo del panel."""
    verdict = aggregate("ACME", [
        _failed("Analista Fundamental"), _failed("Estratega Macro"),
        AgentOpinion("Abogado del Diablo", "REDUCE", "HIGH", concerns=["caro"]),
        _failed("Portfolio Manager"), _failed("Behavioral Coach"),
    ])
    assert verdict.quorum_pct < COMMITTEE.min_quorum_weight_pct
    assert not verdict.available
    assert verdict.action == "UNAVAILABLE"
    with pytest.raises(ValueError, match="unavailable"):
        verdict.to_decision()


def test_fundamental_plus_pm_clear_the_quorum():
    """2.0 de 3.8 = 53 %: mayoría del peso convocado, dictamen parcial válido."""
    verdict = aggregate("ACME", [
        AgentOpinion("Analista Fundamental", "BUY", "HIGH", key_points=["foso"]),
        _failed("Estratega Macro"),
        _failed("Abogado del Diablo"),
        AgentOpinion("Portfolio Manager", "BUY", "MEDIUM", key_points=["peso bajo"]),
        _failed("Behavioral Coach"),
    ])
    assert verdict.quorum_pct >= COMMITTEE.min_quorum_weight_pct
    assert verdict.available and not verdict.complete
    assert verdict.action == "BUY"


def test_portfolio_panel_quorum_uses_its_own_weights():
    """El panel de plan tiene otros pesos (total 3.5); el corte es el mismo %."""
    weights = COMMITTEE.portfolio_vote_weights
    alone = aggregate("plan", [
        _failed("Estratega del Plan"), _failed("Gestor de Riesgo"),
        _failed("Estratega Macro"),
        AgentOpinion("Abogado del Diablo", "REDUCE", "HIGH", concerns=["beta alto"]),
    ], weights=weights)
    assert not alone.available  # 0.8 / 3.5 = 23 %

    majority = aggregate("plan", [
        AgentOpinion("Estratega del Plan", "BUY", "MEDIUM", key_points=["alineado"]),
        AgentOpinion("Gestor de Riesgo", "BUY", "MEDIUM", key_points=["beta ok"]),
        _failed("Estratega Macro"), _failed("Abogado del Diablo"),
    ], weights=weights)
    assert majority.available and majority.action == "BUY"  # 2.0 / 3.5 = 57 %


def test_quorum_defaults_to_met_for_a_cached_verdict():
    """`_verdict_from_dict` no deserializa el quórum: el default tiene que ser
    «alcanzado», o cada hit de caché resucitaría como panel fallido."""
    restored = _verdict_from_dict({"symbol": "MSFT", "action": "BUY", "opinions": [
        {"role": "Analista Fundamental", "stance": "BUY", "confidence": "HIGH"},
    ]})
    assert restored.quorum_pct == 100.0
    assert restored.available and restored.complete
