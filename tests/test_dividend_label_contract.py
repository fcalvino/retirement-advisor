"""Contract of the dividend-growth vocabulary shown to a person (U1-5).

``_score_dividends`` walks ``annual_dividend_totals`` — closed calendar years of
payments as reported by the feed — and pays 3 points at ``streak >= 10``. The
note it attached called the company a **Dividend Aristocrat**, which is not a
description but the name of the S&P index: membership needs 25 consecutive years
of increases *plus* S&P 500 membership. The engine verifies neither, so a
ten-year streak measured off yfinance was being announced as index membership.

U1-5 is a relabel, like U1-3 and U1-4: the note now says what was counted — a
streak of N closed years, from the feed — and **no cut moved**. 10/5/2 still pay
3/2/1 points, and the streak arithmetic keeps its own oracle in
``tests/test_dividend_streak.py``.

Two scoping decisions this file locks:

* The sweep looks at what a *computed* result is called. The curated universe
  ``data/universes/dividend_focus.json`` and the "Alto Dividendo" preset that
  points at it are hand-picked lists that really do hold S&P Aristocrats, so
  their copy is a curatorial claim, not a measurement — allowlisted below, with
  a test that the claim is still grounded in the ticker list.
* Historical audits record what was true when written and are left alone, same
  as ``docs/AUDIT_REASONING_QUALITY.md`` in the U1-3 sweep.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from data.product_ux import (
    DIVIDEND_STREAK_HELP,
    SP_ARISTOCRAT_YEARS,
    dividend_streak_note,
)

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


#: Surfaces that render copy a person reads, plus the modules whose strings are
#: shown verbatim or injected into the prompts.
USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
    "data/product_ux.py",
]

#: "Aristocrat"/"Aristocrats"/"aristocrat" as prose. Deliberately NOT matching
#: the all-caps ``SP_ARISTOCRAT_YEARS``: this sweep is about copy, and the
#: identifier that *holds* the index's 25 years is what makes the denial
#: quotable. Same split as U1-3, where ``SMA200`` is copy and ``above_sma200``
#: is code.
_ARISTOCRAT_RE = re.compile(r"[Aa]ristocrat")

#: A line may name the index when it is denying membership — that is the whole
#: job of the canonical help text.
_DENIAL_RE = re.compile(
    r"\bno es\b|\bis not\b|membership needs|exige|nunca|never|no se verifica",
    re.IGNORECASE,
)

#: Lines allowed to say "Aristocrat": they describe a **hand-curated ticker
#: list**, not a number the engine computed. Kept as (path, marker) pairs so the
#: allowlist cannot quietly grow — every entry is asserted to still exist.
CURATED_UNIVERSE_ALLOWLIST = [
    ("dashboard/pages/5_Optimizer.py", '"description": "Dividend Aristocrats + REITs.'),
    ("data/universes/dividend_focus.json", '"description": "Dividend Aristocrats,'),
]

#: A handful of tickers in ``dividend_focus`` that really are S&P Dividend
#: Aristocrats. If the universe is ever rewritten into something else, the
#: curatorial claim stops being true and the allowlist above must be revisited.
KNOWN_ARISTOCRATS = ("JNJ", "PG", "KO", "MCD", "ADP", "AOS", "EMR", "ITW")


def _allowlisted(rel: str, line: str) -> bool:
    if _DENIAL_RE.search(line):
        return True
    return any(rel == path and marker in line for path, marker in CURATED_UNIVERSE_ALLOWLIST)


# --------------------------------------------------------------------------- #
#  U1-5 — the oracle: nothing computed is announced as index membership        #
# --------------------------------------------------------------------------- #


def test_no_computed_result_is_called_an_aristocrat():
    offenders = [
        f"{rel}:{n}: {line.strip()}"
        for rel in USER_FACING
        for n, line in enumerate(_src(rel).splitlines(), start=1)
        if _ARISTOCRAT_RE.search(line) and not _allowlisted(rel, line)
    ]
    assert not offenders, (
        "Una superficie llama «Aristocrat» a algo que el motor calculó — el "
        "índice exige 25 años y pertenencia al S&P 500, y acá el corte son 10 "
        "años del feed:\n" + "\n".join(offenders)
    )


def test_the_engine_note_says_what_it_counted():
    """The string ``_score_dividends`` writes must not name the index."""
    fundamental = _src("analysis/fundamental.py")
    emitted = [
        line.strip()
        for line in fundamental.splitlines()
        if "result.notes[" in line and "=" in line
    ]
    assert emitted, "no se encontró ninguna nota emitida en analysis/fundamental.py"
    offenders = [line for line in emitted if _ARISTOCRAT_RE.search(line)]
    assert not offenders, offenders

    # And it goes through the canonical formatter, not a local f-string.
    assert 'result.notes["div_growth"] = dividend_streak_note(streak)' in fundamental


def test_curated_allowlist_entries_still_exist():
    """An allowlist that stops matching is an allowlist that hides a defect."""
    for rel, marker in CURATED_UNIVERSE_ALLOWLIST:
        assert marker in _src(rel), f"{rel}: la línea curada cambió — revisar {marker!r}"


def test_the_curated_claim_is_still_grounded_in_the_ticker_list():
    universe = json.loads(_src("data/universes/dividend_focus.json"))
    tickers = set(universe["tickers"])
    missing = [t for t in KNOWN_ARISTOCRATS if t not in tickers]
    assert not missing, (
        "dividend_focus ya no contiene Aristocrats reales, así que su descripción "
        f"dejó de ser una curaduría honesta: faltan {missing}"
    )


# --------------------------------------------------------------------------- #
#  The canonical wording says what it counted, and what it is not              #
# --------------------------------------------------------------------------- #


def test_note_names_the_streak_and_its_source():
    note = dividend_streak_note(13)
    assert "13" in note
    assert "años" in note
    assert "cerrados" in note          # the partial year is excluded on purpose
    assert "feed" in note
    assert not _ARISTOCRAT_RE.search(note)


def test_note_formats_any_streak_the_scorer_can_produce():
    for streak in (2, 5, 10, 25, 63):
        assert str(streak) in dividend_streak_note(streak)


def test_help_states_the_gap_with_the_index():
    assert str(SP_ARISTOCRAT_YEARS) in DIVIDEND_STREAK_HELP
    assert SP_ARISTOCRAT_YEARS == 25
    assert "S&P 500" in DIVIDEND_STREAK_HELP
    # The help must name the cut that actually pays, so the two claims sit side
    # by side and the reader can see they are not the same test.
    assert "10 años" in DIVIDEND_STREAK_HELP


# --------------------------------------------------------------------------- #
#  no_hacer — U1-5 relabels; no cut and no point moved                         #
# --------------------------------------------------------------------------- #


def test_streak_cuts_and_points_are_untouched():
    """The CSV's fix is "racha >=10a en el feed" — a name, not a threshold."""
    src = _src("analysis/fundamental.py")
    assert "if streak >= 10:" in src
    assert "elif streak >= 5:" in src
    assert "elif streak >= 2:" in src
    # The three tiers still pay 3 / 2 / 1 points.
    block = src.split("if streak >= 10:", 1)[1].split("return min(score", 1)[0]
    assert block.count("score += 3") == 1
    assert block.count("score += 2") == 1
    assert block.count("score += 1") == 1


def test_the_streak_arithmetic_keeps_its_own_oracle():
    """U1-5 must not become the reason the streak oracle stops running."""
    oracle = _src("tests/test_dividend_streak.py")
    assert "def oracle_streak" in oracle
