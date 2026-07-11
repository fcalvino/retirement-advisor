"""
Tests for analysis/utils.py — shared AI response parsing utilities.

Covers the failure modes that previously caused Grok analysis to be silently
dropped for out-of-universe tickers (ADRs, foreign companies).
"""

from __future__ import annotations

import json

import pytest

from analysis.utils import extract_json_object

# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

_DECISION_JSON = {
    "action": "HOLD",
    "confidence": "MEDIUM",
    "rationale": ["Factor positivo 1", "Factor positivo 2"],
    "risks": ["Riesgo 1"],
    "recommended_max_allocation_conservative": 5,
    "reasoning": "Tesis: empresa sólida. Riesgos: riesgo país. Catalizadores: crecimiento LATAM. Asignación: 5%",
}

_MOAT_JSON = {
    "brand_strength": 1.5,
    "network_effects": 1.0,
    "switching_costs": 0.5,
    "regulatory_ip": 0.0,
    "moat_durability_years": 10,
    "recommended_max_allocation_conservative": 6,
    "reasoning": "El moat de la empresa es sólido.",
}


# ------------------------------------------------------------------ #
#  Happy-path tests                                                    #
# ------------------------------------------------------------------ #

def test_clean_json_string():
    """Pure JSON string with no surrounding text."""
    raw = json.dumps(_DECISION_JSON)
    assert extract_json_object(raw) == _DECISION_JSON


def test_clean_json_with_whitespace():
    """JSON with leading/trailing whitespace."""
    raw = f"\n  {json.dumps(_DECISION_JSON)}  \n"
    assert extract_json_object(raw) == _DECISION_JSON


def test_pretty_printed_json():
    """Pretty-printed JSON across multiple lines."""
    raw = json.dumps(_DECISION_JSON, indent=2, ensure_ascii=False)
    assert extract_json_object(raw) == _DECISION_JSON


# ------------------------------------------------------------------ #
#  Prose-wrapping tests (common with verbose AI responses)             #
# ------------------------------------------------------------------ #

def test_prose_before_json():
    """AI adds introductory text before the JSON block."""
    raw = f"Aquí está mi análisis:\n\n{json.dumps(_DECISION_JSON)}"
    assert extract_json_object(raw) == _DECISION_JSON


def test_prose_after_json_no_braces():
    """AI adds a plain-text note after the JSON (no curly braces in the note)."""
    raw = f"{json.dumps(_DECISION_JSON)}\n\nNota: considerar el contexto macroeconómico."
    assert extract_json_object(raw) == _DECISION_JSON


def test_prose_after_json_with_braces():
    """
    AI adds a note after the JSON that contains curly braces.

    This is the PRIMARY bug: the old greedy regex r'\\{.*\\}' captured
    everything up to the last '}' in the note, making json.loads() fail.
    """
    raw = (
        f"{json.dumps(_DECISION_JSON)}\n\n"
        "Nota: Para tickers {como MELI} en mercados emergentes {LATAM}, "
        "considerar riesgo país."
    )
    assert extract_json_object(raw) == _DECISION_JSON


def test_prose_before_and_after_json_with_braces():
    """Braces in both preceding and trailing prose."""
    raw = (
        "Contexto {Argentina}: análisis completo.\n\n"
        f"{json.dumps(_DECISION_JSON)}\n\n"
        "Retorno esperado: {5-10}% anual."
    )
    assert extract_json_object(raw) == _DECISION_JSON


# ------------------------------------------------------------------ #
#  Braces inside JSON string values                                    #
# ------------------------------------------------------------------ #

def test_braces_inside_reasoning_string():
    """
    JSON where the 'reasoning' field contains curly braces.

    The old non-greedy regex r'\\{.*?\\}' stopped at the first '}' it found
    (inside the string value), returning a truncated invalid JSON.
    """
    data = dict(_DECISION_JSON)
    data["reasoning"] = "Retorno {5-8}% anual. Contexto {e-commerce} en LATAM."
    raw = json.dumps(data)
    assert extract_json_object(raw) == data


def test_braces_inside_rationale_items():
    """Array items that contain curly braces."""
    data = dict(_DECISION_JSON)
    data["rationale"] = ["Crecimiento {15-20}% YoY", "Margen {30-35}%"]
    raw = json.dumps(data)
    assert extract_json_object(raw) == data


def test_empty_braces_in_string():
    """Edge case: '{}' as a literal substring within a string value."""
    data = dict(_MOAT_JSON)
    data["reasoning"] = "Sin moat {} identificable en este momento."
    raw = json.dumps(data)
    assert extract_json_object(raw) == data


# ------------------------------------------------------------------ #
#  Markdown fences                                                     #
# ------------------------------------------------------------------ #

def test_markdown_fence_json():
    """AI wraps JSON in ```json ... ``` code fences."""
    inner = json.dumps(_MOAT_JSON, indent=2)
    raw = f"```json\n{inner}\n```"
    assert extract_json_object(raw) == _MOAT_JSON


def test_plain_markdown_fence():
    """AI wraps JSON in plain ``` ... ``` code fences (no language tag)."""
    inner = json.dumps(_MOAT_JSON)
    raw = f"```\n{inner}\n```"
    assert extract_json_object(raw) == _MOAT_JSON


# ------------------------------------------------------------------ #
#  Error cases                                                         #
# ------------------------------------------------------------------ #

def test_no_json_raises():
    """Response contains no JSON object at all."""
    with pytest.raises((ValueError, json.JSONDecodeError)):
        extract_json_object("No hay JSON aquí. Solo texto plano.")


def test_empty_string_raises():
    """Empty response raises."""
    with pytest.raises((ValueError, json.JSONDecodeError)):
        extract_json_object("")


def test_unclosed_brace_raises():
    """Malformed JSON with no closing brace raises."""
    with pytest.raises((ValueError, json.JSONDecodeError)):
        extract_json_object('{"action": "HOLD"')


def test_nested_objects():
    """Nested JSON objects are handled correctly."""
    data = {"outer": {"inner": 1}, "value": 2}
    raw = json.dumps(data)
    assert extract_json_object(raw) == data


def test_unicode_content():
    """Unicode characters in string values (including Spanish accents)."""
    data = dict(_DECISION_JSON)
    data["reasoning"] = "Análisis: empresa sólida con posición líder en Latinoamérica."
    raw = json.dumps(data, ensure_ascii=False)
    assert extract_json_object(raw) == data
