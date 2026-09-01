"""The age rule governs the defensive sleeve, not the bond sleeve (N9).

``config.recommended_bond_pct`` states the classic "bond % = age" rule of thumb,
tilted by ``ProfileConfig.bond_age_offset_pp``. ``AllocationAdvisor`` then holds
``CASH_BUFFER_PCT`` of it liquid for rebalancing and puts the rest in bonds. Both
screens printed the bond line next to a caption calling it "la regla por edad",
so at 30 a conservative investor read **25 %** where the rule says **30 %**.

The backlog filed that as a formula defect — the buffer being "carved out of the
bond sleeve" — and deferred it because moving the buffer would shift the default
investor's numbers. Measured, it is the opposite: the rule is satisfied exactly,
over **bonds plus cash**, for all three profiles across every age the sliders
reach and below. The sleeve was never short. It was named after its larger half.

So N9 is a relabel, like U1-1 (return vocabulary), U1-3 (the weekly SMA) and U1-4
(the cost-of-equity hurdle): **no rate, band, offset or formula moved**, and the
identifiers keep their legacy spelling — ``recommended_bond_pct`` still says
"bond" the way ``above_sma200`` still says 200.

**Why the oracle is differential.** ``test_allocation_profile_oracle`` states the
trap in its own docstring: asserting ``defensive_pct == 30.0`` would survive a
knob wired to nothing. So the contract below recomputes the rule from
``bond_age_offset_pp`` and, separately, moves that offset and requires the sleeve
to move with it.

**Why the floor is not an accident.** The buffer is a fixed ``CASH_BUFFER_PCT``,
not a share of the sleeve, so an investor whose rule lands below it still holds
it: at 13 aggressive the rule is 3 and the defensive sleeve is 5. Unreachable
from the 20–80 sliders, reachable from the function — pinned here so the next
reader does not "fix" the ``max(..., 0.0)`` into a silent contradiction.

No network, no Streamlit.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from config import (
    CASH_BUFFER_PCT,
    CONSERVATIVE_PROFILE,
    OPTIMIZER_PROFILES,
    recommended_bond_pct,
)
from data.product_ux import (
    DEFENSIVE_SLEEVE_HELP,
    DEFENSIVE_SLEEVE_LABEL,
    DEFENSIVE_SLEEVE_SHORT,
    defensive_sleeve_caption,
)
from portfolio.allocation import AllocationAdvisor

# Reuse the docs guard's regexes so the two never disagree about a catalog row.
from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]

SLIDER_AGES = range(20, 81)


def _advise(age: int, profile=None):
    return AllocationAdvisor().advise(age, max(age + 1, 65), profile=profile)


def _rule_from_definition(age: float, offset_pp: float) -> float:
    """The glide path, written from its definition rather than read from config.

    Deliberately not a call to ``recommended_bond_pct``: comparing the engine
    against itself would freeze the bug instead of detecting it (CONTEXT §8,
    audit D4).
    """
    return min(max(float(age) + offset_pp, 0.0), 80.0)


# --------------------------------------------------------------------------- #
#  1. The contract: the rule is bonds + cash, with a liquidity floor           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", sorted(OPTIMIZER_PROFILES))
@pytest.mark.parametrize("age", SLIDER_AGES)
def test_the_defensive_sleeve_is_the_rule(key, age):
    """bonds + cash == max(rule, buffer), for every profile and reachable age."""
    profile = OPTIMIZER_PROFILES[key]
    advice = _advise(age, profile)
    expected = max(
        _rule_from_definition(age, profile.bond_age_offset_pp), CASH_BUFFER_PCT
    )

    assert advice.defensive_pct == pytest.approx(expected)
    assert advice.bonds_pct + advice.cash_pct == pytest.approx(advice.defensive_pct)


@pytest.mark.parametrize("key", sorted(OPTIMIZER_PROFILES))
@pytest.mark.parametrize("age", SLIDER_AGES)
def test_the_bond_line_alone_is_never_the_rule(key, age):
    """The defect, stated as a test: bonds alone is a buffer short of the rule.

    This is what the screens used to show against a caption naming the rule. It
    is correct arithmetic and a wrong label, so it is asserted rather than fixed
    — if some future change makes ``bonds_pct`` equal the rule, the split has
    moved and the copy above it has to move too.
    """
    profile = OPTIMIZER_PROFILES[key]
    rule = _rule_from_definition(age, profile.bond_age_offset_pp)
    advice = _advise(age, profile)

    assert advice.bonds_pct == pytest.approx(max(rule - CASH_BUFFER_PCT, 0.0))


def test_the_conservative_thirty_year_old_from_the_backlog_row():
    """The row's own example: 25 on the screen, 30 in the rule, both right."""
    advice = _advise(30, CONSERVATIVE_PROFILE)

    assert recommended_bond_pct(30, CONSERVATIVE_PROFILE) == pytest.approx(30.0)
    assert advice.bonds_pct == pytest.approx(25.0)
    assert advice.cash_pct == pytest.approx(5.0)
    assert advice.defensive_pct == pytest.approx(30.0)
    assert advice.equity_pct == pytest.approx(70.0)


# --------------------------------------------------------------------------- #
#  2. Differential: the sleeve tracks the knob, it is not a pinned literal     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("delta", (-7.0, -3.0, 4.0))
@pytest.mark.parametrize("age", (30, 45, 60, 70))
def test_moving_the_offset_moves_the_defensive_sleeve(age, delta):
    before = _advise(age, CONSERVATIVE_PROFILE)
    tilted = dataclasses.replace(
        CONSERVATIVE_PROFILE,
        bond_age_offset_pp=CONSERVATIVE_PROFILE.bond_age_offset_pp + delta,
    )
    after = _advise(age, tilted)

    assert after.defensive_pct - before.defensive_pct == pytest.approx(delta)
    assert after.equity_pct - before.equity_pct == pytest.approx(-delta)


# --------------------------------------------------------------------------- #
#  3. The buffer is a floor, and it has exactly one home                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("age", (5, 10, 13, 14, 15))
def test_the_buffer_is_a_floor_below_the_rule(age):
    """Below the buffer the whole sleeve is cash — the investor still holds it.

    Aggressive at 13 puts the rule at 3 pp. The sliders stop at 20, so this only
    arrives through the function; it is pinned because ``max(..., 0.0)`` reads
    like a defensive clamp and is actually the floor the contract depends on.
    """
    profile = OPTIMIZER_PROFILES["aggressive"]
    advice = _advise(age, profile)
    rule = _rule_from_definition(age, profile.bond_age_offset_pp)

    assert advice.cash_pct == pytest.approx(CASH_BUFFER_PCT)
    assert advice.defensive_pct == pytest.approx(max(rule, CASH_BUFFER_PCT))
    if rule < CASH_BUFFER_PCT:
        assert advice.bonds_pct == 0.0


def test_the_buffer_has_a_single_home():
    """The literal that made N9 look like a formula error stays out of the code.

    Two spellings of 5 — the ``cash_pct`` default and the ``bond_pct - 5`` that
    carved it out — is what let the rule be stated in one place and contradicted
    in the other. Same guard shape as ``tests/test_decision_thresholds.py``.
    """
    src = (ROOT / "portfolio" / "allocation.py").read_text(encoding="utf-8")
    body = src[src.index("# ---- Target allocation ----") : src.index("# Equity sub-allocation")]

    assert "CASH_BUFFER_PCT" in body
    assert not re.search(r"-\s*5\b|=\s*5\.0\b", body), (
        "El buffer volvió a ser un literal en allocation.py — vive en "
        "config.CASH_BUFFER_PCT"
    )


# --------------------------------------------------------------------------- #
#  4. Label sweep — the three layers of U1-1                                   #
# --------------------------------------------------------------------------- #

#: Files that render copy a person reads, plus the modules that write the rule
#: down beside the code applying it.
USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "config.py",
    "portfolio/allocation.py",
    "data/product_ux.py",
]

#: Catalog roles read as *current* truth (same set the U1-1/U1-3/U1-4 sweeps use).
LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

#: A line that states the glide path: "bond % = age", ``bond_pct = min(age, 80)``,
#: "regla por edad" and friends.
_RULE_RE = re.compile(
    r"bond[_ ]?(?:%|pct|percentage)\s*=\s*(?:age|min\(age)"
    r"|regla (?:por )?edad|age-based (?:bond|allocation) rule",
    re.IGNORECASE,
)

#: What makes such a line honest: it names the sleeve as bonds *plus* cash, or
#: says outright that the bond line alone is not the rule. ``[\s*]`` lets the
#: wording survive markdown emphasis.
_ABSOLVED_RE = re.compile(
    r"defensiv|bonds?[\s*]*\+[\s*]*(?:cash|efectivo)"
    r"|(?:cash|efectivo)[\s*]*\+[\s*]*bonos?"
    r"|bonos?[\s*]*\+[\s*]*efectivo",
    re.IGNORECASE,
)


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def living_docs() -> list[str]:
    """Markdown catalogued in ``docs/INDEX.md`` under a still-current role."""
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


def _unqualified_rule_offenders(paths: list[str]) -> list[str]:
    return [
        f"{rel}:{n}: {line.strip()}"
        for rel in paths
        for n, line in enumerate(_src(rel).splitlines(), start=1)
        if _RULE_RE.search(line) and not _ABSOLVED_RE.search(line)
    ]


def test_no_surface_states_the_rule_as_bonds_alone():
    offenders = _unqualified_rule_offenders(USER_FACING)
    assert not offenders, (
        "La regla por edad enunciada sin decir que cubre bonos + efectivo — es "
        "el defecto de N9, que hace leer 25 % donde la regla dice 30 %:\n"
        + "\n".join(offenders)
    )


def test_no_living_doc_states_the_rule_as_bonds_alone():
    offenders = _unqualified_rule_offenders(living_docs())
    assert not offenders, (
        "Documentación viva que todavía describe la regla como el tramo de "
        "bonos:\n" + "\n".join(offenders)
    )


def test_historical_records_are_left_alone():
    """History records what was true when written; it is not copy to correct.

    Same boundary as U1-1/U1-3/U1-4: the sweep derives its list from the catalog
    roles, so ``ROADMAP.md`` and the audits stay outside it on purpose.
    """
    swept = set(living_docs())

    for historical in ("docs/ROADMAP.md", "docs/AUDIT_REASONING_QUALITY.md"):
        assert (ROOT / historical).is_file()
        assert historical not in swept, (
            f"{historical} es registro histórico y no puede entrar al barrido"
        )


# --------------------------------------------------------------------------- #
#  5. The copy reads from the canonical constants, not from its own numbers    #
# --------------------------------------------------------------------------- #


def test_the_label_names_both_legs():
    assert _ABSOLVED_RE.search(DEFENSIVE_SLEEVE_LABEL)
    assert "Defensivo" in DEFENSIVE_SLEEVE_SHORT
    assert f"{CASH_BUFFER_PCT:g}" in DEFENSIVE_SLEEVE_HELP, (
        "El help escribe el buffer a mano en vez de leer config.CASH_BUFFER_PCT"
    )


def test_the_caption_agrees_with_the_metrics_beside_it():
    advice = _advise(30, CONSERVATIVE_PROFILE)
    caption = defensive_sleeve_caption(advice)

    assert "30 % defensivo" in caption
    assert "25 % en bonos" in caption
    assert "5 % de efectivo" in caption
    assert advice.profile_name in caption
    # The whole point of the caption: neither line is the rule on its own.
    assert "ninguna de las dos" in caption.lower()
