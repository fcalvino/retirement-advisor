"""Contract of the downside-volatility ratio (U1-9).

Two engines publish a number called "Sortino" and neither one is a Sortino
ratio. ``analysis/backtesting.py`` and ``portfolio/tracker.py`` both build the
denominator as ``returns[returns < 0].std()``: the standard deviation of the
losing weeks **around their own mean**. Sortino's denominator is the downside
deviation ``√E[mín(r − MAR, 0)²]``, taken over *every* return, with the gains
entering as zeros and the deviations measured from the MAR.

The gap is not a rounding artefact. Dropping the winning weeks shrinks the
sample, and centring on the mean of the losses instead of on the MAR discards
the *level* of the losses entirely — a run of uniformly bad weeks has a small
spread around its own mean, so this denominator falls exactly when the
portfolio is losing steadily, and the published ratio rises.

The U1-9 ``no_hacer`` is "Relabel + recalculo juntos", so **the formula is not
touched here** — that is oleada 5. This wave only stops the number from
claiming a name it has not earned. ``test_the_formula_was_left_alone`` is the
guard on that half of the bargain: it fails if this pass quietly recomputed
anything.

Sweep scope follows U1-1/U1-3/U1-4: the ``.py`` that render copy plus the
living markdown from ``docs/INDEX.md``. Historical roles stay out on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

from data.product_ux import (
    DOWNSIDE_RATIO_HELP,
    DOWNSIDE_RATIO_LABEL,
    DOWNSIDE_RATIO_SHORT,
)
from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
    "data/product_ux.py",
]

#: The two engines that compute the ratio. Not copy, but a field called
#: ``sortino`` is how the label grows back.
ENGINE_SOURCES = ["analysis/backtesting.py", "portfolio/tracker.py"]

LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

_SORTINO_RE = re.compile(r"sortino", re.IGNORECASE)
#: Naming Sortino is fine — claiming to *be* one is not. A denial on the line,
#: or in the few lines just above it, is what separates the two.
_DENIAL_RE = re.compile(
    r"no es (un |el )?(ratio de )?sortino"
    r"|no (es )?un sortino"
    r"|not (a |the )?sortino"
    r"|never (a |the )?sortino"
    r"|neither .{0,40}? (is|are) a sortino"
    r"|sin ser un sortino",
    re.IGNORECASE,
)
#: The honest name. A line that carries it alongside the old one is a migration
#: entry (``"sortino": "downside_vol_ratio"``) or a field comment pointing at the
#: canonical wording — either way it is not a label promising a Sortino.
_HONEST_NAME = "downside_vol_ratio"
#: A block header two or three lines up scopes the lines under it.
_CONTEXT_LINES = 4
#: Comment and docstring markers, so a denial split across two commented lines
#: reads as one sentence instead of two half-sentences.
_MARKER_RE = re.compile(r"^\s*(#:|#|\*)?\s*", re.MULTILINE)


def _normalise(text: str) -> str:
    """Strip comment markers and collapse newlines into spaces."""
    return " ".join(_MARKER_RE.sub(" ", text).split())


def living_docs() -> list[str]:
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


def _claims_to_be_sortino(line: str, context: str = "") -> bool:
    if not _SORTINO_RE.search(line) or _HONEST_NAME in line:
        return False
    return not _DENIAL_RE.search(_normalise(f"{context}\n{line}"))


def _sortino_offenders(paths: list[str], context_lines: int = _CONTEXT_LINES) -> list[str]:
    offenders: list[str] = []
    for rel in paths:
        lines = _src(rel).splitlines()
        for n, line in enumerate(lines, start=1):
            context = "\n".join(lines[max(0, n - 1 - context_lines):n - 1])
            if _claims_to_be_sortino(line, context):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    return offenders


# --------------------------------------------------------------------------- #
#  The canonical label                                                         #
# --------------------------------------------------------------------------- #


def test_the_label_names_the_denominator_it_actually_uses():
    assert "bajista" in DOWNSIDE_RATIO_LABEL.lower()
    assert "bajista" in DOWNSIDE_RATIO_SHORT.lower()
    assert "sortino" not in DOWNSIDE_RATIO_LABEL.lower()
    assert "sortino" not in DOWNSIDE_RATIO_SHORT.lower()


def test_the_help_says_which_definition_is_missing():
    """A denial is worth little without the definition it is denying."""
    assert _DENIAL_RE.search(DOWNSIDE_RATIO_HELP)
    assert "MAR" in DOWNSIDE_RATIO_HELP
    # The distinguishing detail: this one centres on the mean of the losses.
    assert "media" in DOWNSIDE_RATIO_HELP.lower()


# --------------------------------------------------------------------------- #
#  The sweep                                                                   #
# --------------------------------------------------------------------------- #


def test_no_user_facing_surface_claims_to_show_a_sortino():
    offenders = _sortino_offenders(USER_FACING)
    assert not offenders, (
        "«Sortino» sobre un número cuyo denominador es el desvío de las semanas "
        "perdedoras alrededor de su propia media:\n" + "\n".join(offenders)
    )


def test_no_living_doc_claims_the_project_computes_a_sortino():
    offenders = _sortino_offenders(living_docs(), context_lines=0)
    assert not offenders, (
        "markdown vivo prometiendo un Sortino que ningún motor calcula:\n"
        + "\n".join(offenders)
    )


def test_the_engines_do_not_carry_the_name_either():
    offenders = _sortino_offenders(ENGINE_SOURCES)
    assert not offenders, (
        "el motor sigue llamando Sortino a su propio número:\n" + "\n".join(offenders)
    )


def test_the_sweep_still_catches_the_labels_that_were_there():
    """Guard on the guard: the forms the product actually shipped."""
    assert _claims_to_be_sortino('col2.metric("Sortino Ratio", f"{x:.2f}")')
    assert _claims_to_be_sortino('    "Sortino": getattr(t, "sortino", 0),')
    assert _claims_to_be_sortino("    sortino_ratio: float = 0.0")
    assert _claims_to_be_sortino("| Backtesting | Sharpe, Sortino, Calmar |")
    # A denial passes, on the line or from the block just above it.
    assert not _claims_to_be_sortino('"Ratio retorno/vol bajista (no es Sortino)"')
    assert not _claims_to_be_sortino(
        '            help="El ratio que ves acá no es un Sortino.",'
    )
    # Even when the denial is split across two commented lines.
    assert not _claims_to_be_sortino(
        "    #: Sortino ratio** — see ``DOWNSIDE_RATIO_HELP``.",
        context="    #: (CAGR − Rf) / std of the losing weeks. **NOT a",
    )
    # A migration entry names both the old key and the honest one.
    assert not _claims_to_be_sortino('    "sortino": "downside_vol_ratio",')


# --------------------------------------------------------------------------- #
#  The formula stays where it is (the other half of the U1-9 bargain)          #
# --------------------------------------------------------------------------- #


def test_the_formula_was_left_alone():
    """U1-9 forbids relabelling and recomputing in one pass.

    Both engines must still divide by the std of the negative returns. When
    oleada 5 replaces this with ``√E[mín(r − MAR, 0)²]``, this test is what it
    has to come here and delete — deliberately, not by accident.
    """
    for rel in ENGINE_SOURCES:
        src = _src(rel)
        assert "returns[returns < 0]" in src, rel
        assert "downside.std()" in src, rel
        # And nothing resembling the real downside deviation snuck in.
        assert "clip(upper=0" not in src, rel
        assert "minimum(" not in src, rel


def test_every_surface_reads_the_label_from_the_one_source():
    for rel in ("dashboard/pages/6_Backtesting.py", "dashboard/pages/3_Portfolio.py",
                "analysis/committee_prompts.py"):
        assert "DOWNSIDE_RATIO_LABEL" in _src(rel), rel


def test_the_persisted_field_name_migrates_instead_of_lying():
    """Backtests saved as ``sortino`` still load — under the honest name."""
    from analysis.backtesting import LEGACY_FIELD_NAMES
    assert LEGACY_FIELD_NAMES["sortino"] == "downside_vol_ratio"
    assert LEGACY_FIELD_NAMES["portfolio_sortino"] == "portfolio_downside_vol_ratio"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
