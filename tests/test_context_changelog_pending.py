"""CONTEXT §9 — a row without a commit is resolved by the next PR, not never.

A PR cannot know its own merge SHA, so it writes its §9 row as ``(pending)``.
That is fine for exactly one PR: the next one knows the SHA and must fill it in.
Nothing enforced that, and ``(pending)`` piled up — 20 rows on 2026-09-28, one
of them re-introduced by the PR right after the one that had fixed the previous
(#187 resolved ``45e06b6``, #188 left its own row pending). The rule this pins:
at most one ``(pending)`` row, and only as the newest (first) row.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "docs" / "CONTEXT.md"

PENDING = "(pending)"
_SECTION_RE = re.compile(r"^## 9\. .*?$(.*?)^(?:## |### )", re.MULTILINE | re.DOTALL)


def changelog_commit_cells(text: str) -> list[str]:
    """First-column cells of the §9 table, newest first, header rows excluded."""
    match = _SECTION_RE.search(text)
    assert match, "CONTEXT.md no tiene la sección «## 9.» seguida de otra sección"
    cells = []
    for line in match.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cell = line.split("|")[1].strip()
        if cell in ("Commit", "") or set(cell) <= {"-", ":"}:
            continue
        cells.append(cell.strip("`"))
    return cells


def pending_violations(cells: list[str]) -> list[int]:
    """Row indexes (0 = newest) whose ``(pending)`` breaks the one-and-first rule."""
    return [i for i, cell in enumerate(cells) if cell == PENDING and i > 0]


def test_parser_reads_the_real_table():
    cells = changelog_commit_cells(CONTEXT.read_text(encoding="utf-8"))
    assert len(cells) > 10


def test_only_the_newest_row_may_be_pending():
    cells = changelog_commit_cells(CONTEXT.read_text(encoding="utf-8"))
    bad = pending_violations(cells)
    assert bad == [], (
        f"CONTEXT §9 tiene {len(bad)} fila(s) `(pending)` que no son la más nueva "
        f"(índices {bad}). Resolvé el SHA de la fila del PR anterior "
        "(`git log origin/main --oneline`) antes de agregar la tuya — ver docs/MAINTENANCE.md."
    )


def test_rule_on_synthetic_tables():
    assert pending_violations(["(pending)", "abc1234", "def5678"]) == []
    assert pending_violations(["abc1234", "(pending)"]) == [1]
    assert pending_violations(["(pending)", "(pending)"]) == [1]
    assert pending_violations(["abc1234"]) == []
