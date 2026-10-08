"""Oráculo EO-5a: el tope de posición del modelo es ``recommended_max_allocation`` (ADR 0001).

La clave se llamaba ``recommended_max_allocation_conservative``: el Perfil lo decide la
Postura, no el nombre del campo. EO-5a es mecánico —ninguna acción ni tope cambia—:

- los prompts piden la clave nueva (y ya no la vieja);
- el parser, el caché del moat y las corridas guardadas de ``data/eval_runs/`` siguen
  leyendo la vieja como alias; la nueva gana si vienen las dos; la vieja nunca se escribe;
- el banco de evaluación emite la nueva;
- ``resolve_optimizer_profile`` sin nombre levanta ``ValueError`` (decisión del usuario,
  2026-10-08); un nombre no vacío y desconocido sigue cayendo en Conservador.

Los esperados están hechos a mano. Sin red.
"""

from __future__ import annotations

import json

import pytest

from analysis import prompts
from analysis.ai_analyzer import AIAnalyzer, resolve_optimizer_profile
from analysis.moat import MoatAnalyzer, MoatDetail
from analysis.utils import ALLOCATION_KEY, LEGACY_ALLOCATION_KEY, read_allocation
from config import CONSERVATIVE_PROFILE, STRATEGY, AIConfig
from tests.test_ai_path_equivalence_oracle import STRONG, _fund, _tech

NEW, OLD = "recommended_max_allocation", "recommended_max_allocation_conservative"


def test_the_two_keys_are_what_the_brief_says():
    assert (ALLOCATION_KEY, LEGACY_ALLOCATION_KEY) == (NEW, OLD)


# --------------------------------------------------------------------------- #
#  El alias de lectura                                                         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("data,expected", [
    ({NEW: 7}, 7), ({OLD: 6}, 6),
    ({NEW: 7, OLD: 6}, 7),            # la nueva gana
    ({NEW: 0, OLD: 6}, 0),            # un 0 es una respuesta, no un faltante
    ({NEW: None, OLD: 6}, 6),
    ({}, None), (None, None), ("no es un dict", None),
])
def test_read_allocation_prefers_the_new_key_and_accepts_the_old(data, expected):
    assert read_allocation(data) == expected


def test_read_allocation_default_only_when_neither_is_present():
    assert read_allocation({}, 8) == 8 and read_allocation({OLD: 3}, 8) == 3


def _decision(key: str, value):
    raw = json.dumps({"action": "BUY", "confidence": "HIGH", key: value})
    return AIAnalyzer(AIConfig(provider="groq", model="m", api_key="k"))._parse_response(
        raw, _fund(STRONG, dq={"level": "good"}), _tech())


@pytest.mark.parametrize("key", [NEW, OLD])
def test_the_decision_parser_reads_both_keys_and_clamps_the_same(key):
    assert _decision(key, 6).recommended_max_allocation_pct == 6.0
    assert _decision(key, 99).recommended_max_allocation_pct == STRATEGY.ai_max_allocation_pct


def test_the_decision_parser_without_either_key_leaves_it_unset():
    raw = json.dumps({"action": "BUY", "confidence": "HIGH"})
    d = AIAnalyzer(AIConfig(provider="groq", model="m", api_key="k"))._parse_response(
        raw, _fund(STRONG, dq={"level": "good"}), _tech())
    assert d.recommended_max_allocation_pct is None


_MOAT = {"brand_strength": 1.5, "network_effects": 1.0, "switching_costs": 0.5,
         "regulatory_ip": 0.0, "moat_durability_years": 10, "reasoning": "x" * 60,
         "macro_factors": []}


@pytest.mark.parametrize("key,raw,expected", [(NEW, 12, 12), (OLD, 12, 12), (NEW, 99, 25), (OLD, 0, 1)])
def test_the_moat_parser_normalises_into_the_new_key_only(key, raw, expected):
    out = MoatAnalyzer()._parse_ai_response(json.dumps({**_MOAT, key: raw}), "XYZ")
    assert out[NEW] == expected and OLD not in out


def test_the_moat_parser_defaults_to_eight_without_a_key():
    out = MoatAnalyzer()._parse_ai_response(json.dumps(_MOAT), "XYZ")
    assert out[NEW] == 8


def test_a_moat_cache_written_before_the_rename_still_loads():
    """El caché del moat trae la clave vieja: la lectura la acepta sin invalidarlo."""
    detail = MoatDetail()
    MoatAnalyzer._apply_cached(detail, {OLD: 9, "moat_durability_years": 10})
    assert detail.recommended_max_allocation == 9
    fresh = MoatDetail()
    MoatAnalyzer._apply_cached(fresh, {NEW: 11})
    assert fresh.recommended_max_allocation == 11
    assert not hasattr(fresh, OLD)


def test_a_saved_eval_run_with_the_old_key_is_still_readable():
    """Las corridas guardadas de data/eval_runs/ traen la respuesta cruda con la clave vieja."""
    saved = json.loads('{"raw": "{\\"action\\": \\"HOLD\\", \\"%s\\": 4}"}' % OLD)
    assert read_allocation(json.loads(saved["raw"])) == 4


# --------------------------------------------------------------------------- #
#  Los prompts y el banco de evaluación                                        #
# --------------------------------------------------------------------------- #

def test_the_prompt_module_asks_for_the_new_key_and_never_the_old():
    from pathlib import Path

    src = (Path(prompts.__file__)).read_text(encoding="utf-8")
    assert src.count(f'"{NEW}"') >= 4 and OLD not in src


def test_the_eval_bank_emits_the_new_key():
    from analysis import eval_cases

    payload = json.loads(eval_cases._moat_resp(1, 1, 1, 1, "x" * 60, alloc=6))
    assert payload[NEW] == 6 and OLD not in payload


# --------------------------------------------------------------------------- #
#  resolve_optimizer_profile                                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_profile_without_name_raises_instead_of_assuming_conservador(blank):
    with pytest.raises(ValueError, match="Perfil"):
        resolve_optimizer_profile(blank)


def test_a_known_name_still_resolves_and_an_unknown_one_keeps_the_old_fallback():
    assert resolve_optimizer_profile("Agresivo").max_position_pct == 18.0
    assert resolve_optimizer_profile("perfil-que-ya-no-existe") is CONSERVATIVE_PROFILE


def test_the_committee_prompt_version_moved_with_the_prompt_text():
    """La regla de ``CommitteeConfig.prompt_version``: un prompt del comité cambió (la clave
    del tope de posición), así que la versión sube y el caché de veredictos se reinicia."""
    from config import COMMITTEE

    assert COMMITTEE.prompt_version == "2026-10-08a"
