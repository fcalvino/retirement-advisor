"""AUDIT-MOAT-IA — una respuesta de la IA que no midió nada no puntúa ni se cachea.

Tres defectos del tramo de IA del moat (acciones y cripto):

1. ``max(lo, min(hi, float(raw)))`` con ``NaN`` da ``hi``: un campo ``NaN`` del JSON de la IA
   puntuaba **lo máximo** (2,0), y ``inf`` también. Un campo inválido ya valía 0 con aviso; el
   no-finito tiene que valer lo mismo.
2. ``{}`` (o un objeto sin ningún campo de score) se parseaba como cuatro ceros *válidos*,
   ``ai_available = True``, y se cacheaba 168 h (cripto: 7 días). Una respuesta vacía o no-JSON,
   en cambio, lanzaba ``MoatParseError`` y no se cacheaba. Nadie midió nada: es lo mismo.
3. El prompt cripto del moat dice «Bitcoin (BTC)» y trae el suministro de BTC («21.000.000 máximo»)
   para cualquier símbolo, y ``ETH`` está en ``CRYPTO_TICKERS``. La rúbrica (halving, hash rate,
   Lightning) es de Bitcoin: para otro activo el moat queda *no medido*, no puntuado con una
   rúbrica ajena.

Los esperados están hechos a mano. Sin red ni LLM.
"""

from __future__ import annotations

import json

import pytest

from analysis.crypto_analyzer import CryptoAnalyzer
from analysis.moat import MoatAnalyzer, MoatDetail, MoatParseError, reported_moat_label
from config import AIConfig

EQUITY_KEYS = ("brand_strength", "network_effects", "switching_costs", "regulatory_ip")
CRYPTO_CAPS = {"network_adoption": 2.0, "monetary_scarcity": 2.0,
               "security_decentralization": 1.5, "institutional_regulatory": 1.5,
               "tech_resilience": 1.0}


class _MemCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


def _cfg():
    return AIConfig(provider="groq", model="m", api_key="k", enabled=True)


# --------------------------------------------------------------------------- #
#  1 — NaN / inf no puntúan el máximo                                         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_equity_non_finite_score_is_zero_not_the_maximum(bad):
    raw = ('{"brand_strength": %s, "network_effects": 1.0, "switching_costs": 0.5, '
           '"regulatory_ip": 1.5}' % bad)
    parsed = MoatAnalyzer()._parse_ai_response(raw, "AAPL")
    assert parsed["brand_strength"] == 0.0
    assert [parsed[k] for k in EQUITY_KEYS[1:]] == [1.0, 0.5, 1.5]      # el resto no se toca


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_crypto_non_finite_score_is_zero_not_the_maximum(bad):
    raw = json.dumps({k: 0.5 for k in CRYPTO_CAPS}).replace('"network_adoption": 0.5',
                                                          '"network_adoption": %s' % bad)
    parsed = CryptoAnalyzer()._parse_crypto_moat_response(raw, "BTC-USD")
    assert parsed["network_adoption"] == 0.0
    assert parsed["monetary_scarcity"] == 0.5


@pytest.mark.parametrize("field", ["moat_durability_years", "recommended_max_allocation"])
@pytest.mark.parametrize("bad", ["Infinity", "NaN"])
def test_a_non_finite_optional_field_falls_back_to_its_default(field, bad):
    """``int(inf)`` lanza ``OverflowError``, que el parser no atrapaba."""
    eq = '{"brand_strength": 1, "network_effects": 1, "switching_costs": 1, "regulatory_ip": 1, "%s": %s}'
    parsed = MoatAnalyzer()._parse_ai_response(eq % (field, bad), "AAPL")
    assert parsed["moat_durability_years"] == 0 and parsed["recommended_max_allocation"] == 8
    cr = json.dumps({k: 0.5 for k in CRYPTO_CAPS})[:-1] + ', "%s": %s}' % (field, bad)
    parsed = CryptoAnalyzer()._parse_crypto_moat_response(cr, "BTC-USD")
    assert parsed["moat_durability_years"] == 10 and parsed["recommended_max_allocation"] == 5


def test_finite_values_are_still_clamped_to_their_range():
    raw = '{"brand_strength": 9, "network_effects": -3, "switching_costs": 1.26, "regulatory_ip": "x"}'
    parsed = MoatAnalyzer()._parse_ai_response(raw, "AAPL")
    assert [parsed[k] for k in EQUITY_KEYS] == [2.0, 0.0, 1.3, 0.0]


# --------------------------------------------------------------------------- #
#  2 — una respuesta sin ningún score no es una medición                       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw", [
    "{}",
    '{"reasoning": "no sé"}',
    '{"brand_strength": NaN, "network_effects": "n/a", "switching_costs": null, "regulatory_ip": []}',
])
def test_equity_response_with_no_usable_score_is_a_parse_error(raw):
    with pytest.raises(MoatParseError):
        MoatAnalyzer()._parse_ai_response(raw, "AAPL")


@pytest.mark.parametrize("raw", ["{}", '{"reasoning": "no sé"}', '{"network_adoption": NaN}'])
def test_crypto_response_with_no_usable_score_is_a_parse_error(raw):
    with pytest.raises(ValueError):
        CryptoAnalyzer()._parse_crypto_moat_response(raw, "BTC-USD")


def test_a_partial_answer_is_still_a_measurement():
    parsed = MoatAnalyzer()._parse_ai_response('{"brand_strength": 1.5}', "AAPL")
    assert parsed["brand_strength"] == 1.5 and parsed["network_effects"] == 0.0


def test_an_empty_object_is_not_cached_for_equity(monkeypatch):
    an = MoatAnalyzer()
    an._cache = _MemCache()
    monkeypatch.setattr(MoatAnalyzer, "_call_api", lambda self, prompt, cfg: "{}")
    monkeypatch.setattr(MoatAnalyzer, "_build_prompt", lambda self, q, s, i: "p")
    out = an.analyze_with_ai(MoatDetail(), "AAPL", {}, _cfg())
    assert out.ai_available is False
    assert an._cache.store == {}


def test_an_empty_object_is_not_cached_for_crypto(monkeypatch):
    import analysis.moat as moat_mod

    an = CryptoAnalyzer()
    an._cache = _MemCache()
    monkeypatch.setattr(moat_mod, "call_ai_api", lambda prompt, cfg, **kw: "{}")
    monkeypatch.setattr(CryptoAnalyzer, "_build_crypto_moat_prompt", lambda self, s, i, m: "p")
    moat = an._analyze_crypto_moat("BTC-USD", {}, {}, _cfg())
    assert moat.ai_available is False
    assert an._cache.store == {}


# --------------------------------------------------------------------------- #
#  3 — la rúbrica cripto es de Bitcoin                                        #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("symbol", ["ETH-USD", "ETH", "ETHEREUM"])
def test_a_non_bitcoin_crypto_moat_is_not_measured_and_never_asks_the_model(symbol, monkeypatch):
    import analysis.moat as moat_mod

    called = []
    monkeypatch.setattr(moat_mod, "call_ai_api", lambda *a, **k: called.append(a) or "{}")
    an = CryptoAnalyzer()
    an._cache = _MemCache()
    moat = an._analyze_crypto_moat(symbol, {}, {}, _cfg())
    assert called == [], "el prompt de Bitcoin se mandó para otro activo"
    assert moat.ai_available is False
    assert "Bitcoin" in moat.ai_reasoning


def test_a_stale_cached_eth_moat_is_not_applied(monkeypatch):
    """Un ETH cacheado hace < 7 días con la rúbrica de Bitcoin no puede seguir vigente."""
    an = CryptoAnalyzer()
    an._cache = _MemCache()
    an._cache.set("crypto_moat_ai_ETH-USD_groq_m", {k: v for k, v in CRYPTO_CAPS.items()})
    moat = an._analyze_crypto_moat("ETH-USD", {}, {}, _cfg())
    assert moat.ai_available is False and moat.network_adoption == 0.0


@pytest.mark.parametrize("symbol", ["BTC-USD", "BTC", "BITCOIN"])
def test_bitcoin_still_goes_through_the_ai_rubric(symbol, monkeypatch):
    import analysis.moat as moat_mod

    # 1,0 + 1,0 + 1,0 + 1,0 + 0,5 = 4,5 (cada campo se redondea a un decimal antes de sumar)
    answer = json.dumps({"network_adoption": 1.0, "monetary_scarcity": 1.0,
                         "security_decentralization": 1.0, "institutional_regulatory": 1.0,
                         "tech_resilience": 0.5})
    monkeypatch.setattr(moat_mod, "call_ai_api", lambda prompt, cfg, **kw: answer)
    monkeypatch.setattr(CryptoAnalyzer, "_build_crypto_moat_prompt", lambda self, s, i, m: "p")
    an = CryptoAnalyzer()
    an._cache = _MemCache()
    moat = an._analyze_crypto_moat(symbol, {}, {}, _cfg())
    assert moat.ai_available is True
    assert moat.ai_total == pytest.approx(4.5)


def test_unmeasured_eth_reports_no_moat_label_not_the_worst_bucket():
    """Con ``ai_available=False`` el comité lee «no medido», no «None» (ver el oráculo hermano)."""
    from types import SimpleNamespace

    from analysis.crypto_analyzer import CryptoMoatDetail

    fund = SimpleNamespace(is_crypto=True, asset_class="crypto", moat_detail=CryptoMoatDetail(),
                           moat_classification="None")
    assert reported_moat_label(fund) is None


# --------------------------------------------------------------------------- #
#  Lo que encontró la revisión                                                #
# --------------------------------------------------------------------------- #

HUGE_INT = "9" * 400        # un entero JSON válido que ``float()`` no puede representar


def test_an_integer_too_big_for_a_float_is_not_a_measurement():
    """``float('9' * 400)`` lanza ``OverflowError``: tampoco debe tumbar la respuesta entera."""
    raw = ('{"brand_strength": %s, "network_effects": 1.0, "switching_costs": 0.5, '
           '"regulatory_ip": 1.5}' % HUGE_INT)
    parsed = MoatAnalyzer()._parse_ai_response(raw, "AAPL")
    assert parsed["brand_strength"] == 0.0 and parsed["network_effects"] == 1.0
    crypto = json.dumps({k: 0.5 for k in CRYPTO_CAPS}).replace(
        '"network_adoption": 0.5', '"network_adoption": %s' % HUGE_INT)
    assert CryptoAnalyzer()._parse_crypto_moat_response(crypto, "BTC-USD")["network_adoption"] == 0.0


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", HUGE_INT])
def test_a_non_finite_allocation_cap_from_the_decision_is_no_cap(bad):
    """El mismo patrón en la decisión: ``min(15, nan)`` daba el máximo, 15 %."""
    from analysis.ai_analyzer import AIAnalyzer
    from tests.test_ai_path_equivalence_oracle import STRONG, _fund, _tech

    raw = '{"action": "BUY", "confidence": "HIGH", "recommended_max_allocation": %s}' % bad
    decision = AIAnalyzer(AIConfig(provider="groq", model="m", api_key="k"))._parse_response(
        raw, _fund(STRONG, dq={"level": "good"}), _tech())
    assert decision.recommended_max_allocation_pct is None
