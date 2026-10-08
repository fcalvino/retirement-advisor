"""Oráculo EO-5b: la IA se calibra, no se modera (ADR 0001, bloque 6 del BACKLOG).

Decisiones del usuario (2026-10-08):

- fuera la redacción conservadora de los prompts («filosofía conservadora», «extremadamente
  … conservador», «Sé conservador», «asesor … conservador»): la instrucción es decir lo que
  la evidencia sostiene, con su incertidumbre; la prudencia es Postura del Perfil;
- el Portfolio Manager recibe la Postura del Perfil elegido y dimensiona dentro de ella; sin
  Perfil no hay Postura y no dimensiona (EO-1b);
- el Perfil entra a la clave de caché del comité;
- el Abogado del Diablo se queda como método: el voto es simétrico y su disparador de
  confianza no cambia;
- un barrido de los prompts impide que «conservador» vuelva como instrucción.

El barrido mira los **strings** de los módulos de prompts (no docstrings ni comentarios);
«Perfil Conservador», con mayúscula, es el nombre de un perfil y no se toca. Sin red.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis import committee_prompts as cp
from analysis.committee import (
    AgentOpinion,
    CommitteeAnalyzer,
    _postura_variant,
    aggregate,
)
from config import COMMITTEE, CRYPTO_COMMITTEE, EVAL
from data.product_ux import committee_postura
from tests.test_committee import (
    _agent_json,
    _fund_tech,
    _fundamental_json,
    make_fake,
)

ROOT = Path(__file__).resolve().parents[1]
PROMPT_MODULES = ("analysis/prompts.py", "analysis/committee_prompts.py", "analysis/chat_agent.py")
# «conservador/a/es/as» en minúscula (una instrucción o un adjetivo) y «conservative».
FORBIDDEN = re.compile(r"conservador(?:a|as|es)?\b|conservative|filosofía conservadora")


def _string_constants(source: str):
    """Los literales de string de un módulo, sin docstrings (los comentarios no son AST)."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None), ast.Constant
            ) and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [
        (n.lineno, n.value) for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]


# --------------------------------------------------------------------------- #
#  El barrido                                                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("module", PROMPT_MODULES)
def test_no_prompt_asks_the_model_to_be_conservative(module):
    hits = [
        (line, text[:60]) for line, text in
        _string_constants((ROOT / module).read_text(encoding="utf-8"))
        if FORBIDDEN.search(text)
    ]
    assert hits == [], f"{module}: «conservador» como instrucción volvió: {hits}"


def test_the_sweep_would_catch_it_and_spares_the_profile_name():
    """Anti-trampa: el barrido encuentra la palabra y no confunde el nombre del perfil."""
    bad = 'def f():\n    return "Sé conservador y filosofía conservadora"\n'
    assert any(FORBIDDEN.search(t) for _, t in _string_constants(bad))
    ok = 'def f():\n    """un docstring conservador"""\n    return "El perfil Conservador se beneficia"\n'
    assert not any(FORBIDDEN.search(t) for _, t in _string_constants(ok))
    sizes = {m: len(_string_constants((ROOT / m).read_text(encoding="utf-8"))) for m in PROMPT_MODULES}
    assert all(n > 20 for n in sizes.values()), sizes        # el barrido de verdad lee strings


def test_the_role_prompts_carry_the_evidence_register():
    fund, tech = _fund_tech()
    assert cp.EVIDENCE_REGISTER == (
        "Decí lo que la evidencia sostiene, con su incertidumbre: ni más cauto ni más optimista "
        "de lo que los datos justifican."
    )
    for prompt in (cp.portfolio_manager_prompt(fund, tech), cp.devils_advocate_prompt(fund, tech),
                   cp.behavioral_coach_prompt(fund, tech), cp.macro_strategist_prompt(fund, tech)):
        assert cp.EVIDENCE_REGISTER in prompt
        assert "conservador" not in prompt.lower().replace("perfil conservador", "")
    portfolio = cp.plan_strategist_prompt({})
    assert cp.EVIDENCE_REGISTER in portfolio


def test_the_devils_advocate_stays_and_asks_for_the_bear_case():
    fund, tech = _fund_tech()
    prompt = cp.devils_advocate_prompt(fund, tech)
    assert "Abogado del Diablo" in prompt and "No seas complaciente" in prompt


# --------------------------------------------------------------------------- #
#  El Abogado del Diablo: el voto es simétrico, y su disparador de confianza no se movió  #
# --------------------------------------------------------------------------- #

def _ops(fundamental, macro, devil, pm):
    mk = lambda role, stance: AgentOpinion(role, stance, "MEDIUM", ["p"], ["c"])  # noqa: E731
    return [mk("Analista Fundamental", fundamental), mk("Estratega Macro", macro),
            mk("Abogado del Diablo", devil), mk("Portfolio Manager", pm)]


def test_the_vote_is_symmetric_a_mirrored_panel_gives_the_mirrored_lean():
    up = aggregate("X", _ops("BUY", "BUY", "HOLD", "STRONG BUY"))
    # El espejo exacto de cada stance (±1 / ±2): BUY↔REDUCE, STRONG BUY↔SELL, HOLD↔HOLD.
    mirrored = aggregate("X", _ops("REDUCE", "REDUCE", "HOLD", "SELL"))
    assert up.lean > 0
    assert mirrored.lean == pytest.approx(-up.lean)


def test_the_devils_advocate_confidence_notch_is_unchanged():
    """Decisión del usuario: el disenso fuerte del abogado baja la confianza un escalón y
    nunca mueve la acción."""
    calm = aggregate("X", _ops("BUY", "BUY", "BUY", "BUY"))
    strong = aggregate("X", [
        AgentOpinion("Analista Fundamental", "BUY", "HIGH", ["p"], ["c"]),
        AgentOpinion("Estratega Macro", "BUY", "MEDIUM", ["p"], ["c"]),
        AgentOpinion("Abogado del Diablo", "REDUCE", "HIGH", ["p"], ["c"]),
        AgentOpinion("Portfolio Manager", "BUY", "MEDIUM", ["p"], ["c"]),
    ])
    assert strong.confidence == "MEDIUM"                    # HIGH del Fundamental, un escalón menos
    assert calm.action == "BUY"


# --------------------------------------------------------------------------- #
#  La Postura                                                                  #
# --------------------------------------------------------------------------- #

def _prefs(key, **over):
    return SimpleNamespace(chosen_profile_key=key, exigencia_pct=None, margin_pct=None,
                           planning_scenario=None, **over)


def test_committee_postura_reads_the_profile_and_the_user_overrides():
    p = committee_postura(_prefs("moderate"))
    assert p["profile_key"] == "moderate" and p["profile_name"] == "Moderado"
    assert p["max_position_pct"] == 12.0                    # ProfileConfig de config.py
    edited = committee_postura(SimpleNamespace(
        chosen_profile_key="moderate", exigencia_pct=85.0, margin_pct=15.0,
        planning_scenario="pesimista"))
    assert (edited["exigencia_pct"], edited["margin_pct"], edited["planning_scenario"]) == (
        85.0, 15.0, "pesimista")


def test_without_a_chosen_profile_there_is_no_postura():
    assert committee_postura(_prefs(None)) is None
    assert committee_postura(_prefs("no-existe")) is None


def test_the_pm_prompt_prints_the_postura_it_was_given():
    fund, tech = _fund_tech()
    postura = committee_postura(_prefs("aggressive"))
    prompt = cp.portfolio_manager_prompt(fund, tech, None, postura)
    assert cp.postura_line(postura) in prompt
    assert "no hay Postura" not in prompt
    assert "no hay Postura" in cp.portfolio_manager_prompt(fund, tech, None, None)


def test_the_analyzer_hands_the_postura_to_the_pm_only():
    fund, tech = _fund_tech()
    postura = committee_postura(_prefs("aggressive"))
    seen = {}

    base = make_fake(fundamental=_fundamental_json("BUY"), macro=_agent_json("BUY"),
                     devil=_agent_json("HOLD"), pm=_agent_json("BUY"), coach=_agent_json("HOLD"))

    def call_fn(prompt):
        seen[prompt[:60]] = prompt
        return base(prompt)

    CommitteeAnalyzer(call_fn=call_fn, use_cache=False).analyze(fund, tech, None, postura)
    with_postura = [p for p in seen.values() if cp.postura_line(postura) in p]
    assert len(with_postura) == 1 and "Portfolio Manager" in with_postura[0]


# --------------------------------------------------------------------------- #
#  La clave de caché                                                           #
# --------------------------------------------------------------------------- #

def test_the_cache_key_carries_the_postura_not_only_the_profile_name():
    a = committee_postura(_prefs("moderate"))
    b = committee_postura(SimpleNamespace(chosen_profile_key="moderate", exigencia_pct=90.0,
                                          margin_pct=None, planning_scenario=None))
    c = committee_postura(_prefs("aggressive"))
    assert _postura_variant(None) == "pos:sin-perfil"
    assert _postura_variant(a) == _postura_variant(committee_postura(_prefs("moderate")))
    assert len({_postura_variant(a), _postura_variant(b), _postura_variant(c), _postura_variant(None)}) == 4
    assert _postura_variant(a).startswith("pos:moderate:")


def test_a_verdict_cached_for_one_perfil_is_not_served_for_another(monkeypatch):
    fund, tech = _fund_tech()
    keys = []
    monkeypatch.setattr(CommitteeAnalyzer, "_get_cached", lambda self, s, v="": keys.append(v))
    monkeypatch.setattr(CommitteeAnalyzer, "_set_cached", lambda self, s, verdict, v="": None)
    fake = make_fake(fundamental=_fundamental_json("BUY"), macro=_agent_json("BUY"),
                     devil=_agent_json("HOLD"), pm=_agent_json("BUY"), coach=_agent_json("HOLD"))
    c = CommitteeAnalyzer(call_fn=fake, use_cache=True)
    c.analyze(fund, tech, None, committee_postura(_prefs("moderate")))
    c.analyze(fund, tech, None, committee_postura(_prefs("aggressive")))
    c.analyze(fund, tech)
    assert len(set(keys)) == 3


# --------------------------------------------------------------------------- #
#  Versión y residuales de EO-5a                                               #
# --------------------------------------------------------------------------- #

def test_the_prompt_version_moved_and_the_residuals_are_renamed():
    assert COMMITTEE.prompt_version == "2026-10-08b"
    assert EVAL.alloc_cap_pct == 15.0 and not hasattr(EVAL, "conservative_alloc_cap_pct")
    assert not hasattr(CRYPTO_COMMITTEE, "sizing_profile")
