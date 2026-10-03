"""The living docs stay readable in pieces — ORDEN-ACTUAL (2026-10-03).

Agents read ``docs/BACKLOG.md`` and ``docs/CONTEXT.md`` with ``sed -n`` and
``Read(offset, limit)``. Both break on a line that keeps growing: by 2026-10-02
the CONTEXT header was one line of 32,905 characters (each update prepended its
summary to the previous one), the BACKLOG header 11,260 and its «Cerradas:»
paragraph 41,470, and the current order sat at the *end* of the 11,260. A
``Read`` of the first 90 lines of BACKLOG went over the tool's 25k-token limit.

The shape these tests pin:

* every living doc has no line past ``MAX_LINE`` — the backstop;
* the CONTEXT «Última actualización» line and the BACKLOG role line are short,
  because those are the two that accumulated;
* BACKLOG opens with ``## Orden actual``, a block short enough to read whole.
"""

from __future__ import annotations

from pathlib import Path

from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]

#: Same roles as the label-contract sweeps: docs read as current truth.
LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

#: Longest legitimate line on 2026-10-03 was a CONTEXT §6 table row (4,529).
#: A markdown table row cannot wrap, so the cap leaves it room; a paragraph
#: that crosses it is accumulating and belongs in ROADMAP or §9.
MAX_LINE = 6000
MAX_CONTEXT_HEADER = 300
MAX_BACKLOG_ROLE_LINE = 400
ORDEN_HEADING = "## Orden actual"
ORDEN_WITHIN_FIRST = 15
ORDEN_MAX_LINES = 15


def _lines(rel: str) -> list[str]:
    return (ROOT / rel).read_text(encoding="utf-8").split("\n")


def living_docs() -> list[str]:
    table = CATALOG_TABLE_RE.search((ROOT / "docs/INDEX.md").read_text(encoding="utf-8"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


def test_the_sweep_covers_backlog_and_context():
    docs = living_docs()
    assert "docs/BACKLOG.md" in docs
    assert "docs/CONTEXT.md" in docs


def test_no_living_doc_line_keeps_growing():
    long_lines = [
        f"{rel}:{n} ({len(line)} caracteres)"
        for rel in living_docs()
        for n, line in enumerate(_lines(rel), 1)
        if len(line) > MAX_LINE
    ]
    assert long_lines == [], "\n".join(long_lines)


def test_context_header_is_one_short_line():
    header = [line for line in _lines("docs/CONTEXT.md")[:10] if "Última actualización" in line]
    assert len(header) == 1, "CONTEXT.md perdió su línea «Última actualización»"
    assert len(header[0]) <= MAX_CONTEXT_HEADER, (
        f"«Última actualización» tiene {len(header[0])} caracteres: el resumen de "
        "cada cambio va a su fila de §9, no a la cabecera (CONTEXT §10)"
    )


def test_backlog_role_line_is_short():
    role = [line for line in _lines("docs/BACKLOG.md")[:5] if "**Rol:**" in line]
    assert len(role) == 1, "BACKLOG.md perdió su línea de rol"
    assert len(role[0]) <= MAX_BACKLOG_ROLE_LINE, (
        f"la línea de rol tiene {len(role[0])} caracteres: la historia de las "
        "repriorizaciones va al archivo del final de ROADMAP.md"
    )


def test_backlog_opens_with_a_short_orden_actual():
    lines = _lines("docs/BACKLOG.md")
    assert ORDEN_HEADING in lines, f"BACKLOG.md no tiene «{ORDEN_HEADING}»"
    start = lines.index(ORDEN_HEADING)
    assert start < ORDEN_WITHIN_FIRST, (
        f"«{ORDEN_HEADING}» está en la línea {start + 1}: tiene que verse con "
        f"`sed -n 1,25p docs/BACKLOG.md`"
    )
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith(("## ", "---"))),
        len(lines),
    )
    body = [line for line in lines[start + 1 : end] if line.strip()]
    assert 0 < len(body) <= ORDEN_MAX_LINES, (
        f"«{ORDEN_HEADING}» tiene {len(body)} líneas con texto: se reescribe, no "
        "se le agrega (BACKLOG «Cómo mantener este archivo»)"
    )


def test_claude_md_is_only_the_pointer():
    """``CLAUDE.md`` loads on every turn. It held a 138-line rtk block that the
    machine's ``~/.claude/RTK.md`` already loads, and that contradicted it (retro
    2026-10-03, item 5). ``rtk init`` writes the block back; this catches it."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").strip()
    assert text == "@docs/PROMPT_INSTRUCTIONS.md", (
        "CLAUDE.md es sólo el puntero a docs/PROMPT_INSTRUCTIONS.md "
        "(docs/MAINTENANCE.md §2); las instrucciones de rtk son de la máquina"
    )
