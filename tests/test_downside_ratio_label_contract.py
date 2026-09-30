"""Contract of the downside-risk ratio (U1-9 → U1-9b).

U1-9 (2026-08-25) found that the two engines published a number called
"Sortino" that was not one: ``analysis/backtesting.py`` and
``portfolio/tracker.py`` divided by ``returns[returns < 0].std()``, the spread of
the losing weeks **around their own mean**, which shrinks when the portfolio
loses steadily. It relabelled the number and left the formula alone on purpose
(its ``no_hacer`` was "relabel + recálculo juntos"); the guard on that half was
``test_the_formula_was_left_alone``, deleted here deliberately.

U1-9b (2026-09-30) fixed the formula — ``analysis.utils.downside_deviation``,
√E[mín(r − MAR, 0)²] over every week with MAR = the risk-free rate, checked
against an independent loop in ``tests/test_sortino_oracle.py`` — and, by the
user's decision, gave the name back. The contract flips with it: the label is
«Sortino», the help states the definition, and a surface that still says the
number *is not* a Sortino is now the one that lies.

Sweep scope follows U1-1/U1-3/U1-4: the ``.py`` that render copy plus the
living markdown from ``docs/INDEX.md``. Historical roles stay out on purpose —
they describe the old ratio in the past tense.
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

#: The two engines that compute the ratio.
ENGINE_SOURCES = ["analysis/backtesting.py", "portfolio/tracker.py"]

LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

#: The present-tense denial U1-9 wrote everywhere. After U1-9b it is false; the
#: past tense («no era un Sortino») describes the old ratio and stays allowed.
_DENIAL_RE = re.compile(
    r"no es (un |el )?(ratio de )?sortino"
    r"|no (es )?un sortino"
    r"|not (a |the )?sortino"
    r"|never (a |the )?sortino"
    r"|neither .{0,40}? (is|are) a sortino"
    r"|sin ser un sortino",
    re.IGNORECASE,
)
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


def _denies_being_sortino(line: str) -> bool:
    return bool(_DENIAL_RE.search(_normalise(line)))


def _denial_offenders(paths: list[str]) -> list[str]:
    offenders: list[str] = []
    for rel in paths:
        for n, line in enumerate(_src(rel).splitlines(), start=1):
            if _denies_being_sortino(line):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    return offenders


# --------------------------------------------------------------------------- #
#  The canonical label                                                         #
# --------------------------------------------------------------------------- #


def test_the_label_is_sortino():
    assert DOWNSIDE_RATIO_LABEL == "Sortino"
    assert DOWNSIDE_RATIO_SHORT == "Sortino"


def test_the_help_states_the_definition_it_uses():
    """The name is only worth something next to the formula and the MAR."""
    assert "√E[mín(r − MAR, 0)²]" in DOWNSIDE_RATIO_HELP
    assert "todas" in DOWNSIDE_RATIO_HELP
    assert "MAR igual a la tasa libre de riesgo" in DOWNSIDE_RATIO_HELP
    assert not _denies_being_sortino(DOWNSIDE_RATIO_HELP)


# --------------------------------------------------------------------------- #
#  The sweep: no surface keeps the old denial                                  #
# --------------------------------------------------------------------------- #


def test_no_user_facing_surface_still_denies_the_sortino():
    offenders = _denial_offenders(USER_FACING)
    assert not offenders, (
        "copy que sigue diciendo que el ratio no es un Sortino (U1-9b lo es):\n"
        + "\n".join(offenders)
    )


def test_no_living_doc_still_denies_the_sortino():
    offenders = _denial_offenders(living_docs())
    assert not offenders, (
        "markdown vivo con la negación de U1-9, falsa desde U1-9b:\n" + "\n".join(offenders)
    )


def test_the_engines_do_not_deny_it_either():
    offenders = _denial_offenders(ENGINE_SOURCES)
    assert not offenders, "\n".join(offenders)


def test_the_sweep_still_catches_the_denials_that_were_there():
    """Guard on the guard: the forms U1-9 shipped, which are now false."""
    assert _denies_being_sortino('f"{DOWNSIDE_RATIO_LABEL} (no es Sortino): "')
    assert _denies_being_sortino('"retorno/vol bajista no es un Sortino — no lo compares"')
    assert _denies_being_sortino("    portfolio_downside_vol_ratio: float = 0.0   # NOT a Sortino ratio — U1-9")
    assert _denies_being_sortino('"las semanas negativas. **No es el ratio de Sortino**: el "')
    # The past tense describes the old ratio and is allowed.
    assert not _denies_being_sortino("el ratio de antes no era un Sortino")


# --------------------------------------------------------------------------- #
#  One formula, in one place                                                   #
# --------------------------------------------------------------------------- #


def test_both_engines_divide_by_the_shared_downside_deviation():
    """U1-9b: the denominator lives in ``analysis.utils.downside_deviation``.

    Replaces ``test_the_formula_was_left_alone`` (U1-9), deleted on purpose.
    """
    for rel in ENGINE_SOURCES:
        src = _src(rel)
        assert "downside_deviation(" in src, rel
        assert "returns[returns < 0]" not in src, rel


def test_every_surface_reads_the_label_from_the_one_source():
    for rel in ("dashboard/views/6_Backtesting.py", "dashboard/views/3_Portfolio.py",
                "analysis/committee_prompts.py"):
        assert "DOWNSIDE_RATIO_LABEL" in _src(rel), rel


def test_the_persisted_field_name_migrates_instead_of_lying():
    """Backtests saved as ``sortino`` still load — under the field name that stayed."""
    from analysis.backtesting import LEGACY_FIELD_NAMES
    assert LEGACY_FIELD_NAMES["sortino"] == "downside_vol_ratio"
    assert LEGACY_FIELD_NAMES["portfolio_sortino"] == "portfolio_downside_vol_ratio"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
