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
* BACKLOG opens with ``## Orden actual``, a block short enough to read whole;
* the Orden and the rest of BACKLOG do not contradict each other, and every
  repriorización it replaced is in ROADMAP's archive (ORDEN-COHERENCIA, 2026-10-10).
"""

from __future__ import annotations

import re
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


# --------------------------------------------------------------------------- #
#  ORDEN-COHERENCIA (2026-10-10)                                               #
# --------------------------------------------------------------------------- #
# On `3dcfa3b` GOAL-PRIORITY-TEXT was step 2 of the Orden while «Abiertas hoy»
# said «no priorizado» and its block-4 bullet «sin orden»: an agent reading only
# the table saw nothing prioritised. And the ROADMAP archive stopped at the
# decimocuarta: the rule «the replaced repriorización goes to the archive» was
# written down and not checked, and four in a row were skipped.

STALE_STATUS_RE = re.compile(r"no priorizad|sin orden|sin alcance ni orden", re.IGNORECASE)
BOLD_ID_RE = re.compile(r"\*\*([A-Z][A-Z0-9.]*(?:-[A-Z0-9.]+)+|[A-Z]{2,}[0-9]*)\*\*")
STRUCK_RE = re.compile(r"~~.*?~~")
ARCHIVE_HEADING = "## Archivo del backlog"
REPRIO_HEADING = "### Repriorizaciones"

#: Feminine and masculine stems; the archive says «Tercer /decidir-proyecto» and
#: «Decimocuarta /decidir-proyecto». Index + 1 is the number.
ORDINAL_STEMS = (
    "primer", "segund", "tercer", "cuart", "quint", "sext", "séptim", "octav",
    "noven", "décim", "undécim", "duodécim", "decimotercer", "decimocuart",
    "decimoquint", "decimosext", "decimoséptim", "decimoctav", "decimonoven",
    "vigésim",
)
ORDINAL_RE = re.compile(
    r"\b(" + "|".join(ORDINAL_STEMS) + r")(?:a|o)?\b", re.IGNORECASE
)


def _ordinal(word: str) -> int | None:
    m = ORDINAL_RE.fullmatch(word.strip(" *`"))
    return ORDINAL_STEMS.index(m.group(1).lower()) + 1 if m else None


def _first_ordinal(text: str) -> int | None:
    m = ORDINAL_RE.search(text)
    return ORDINAL_STEMS.index(m.group(1).lower()) + 1 if m else None


def _orden_span(lines: list[str]) -> tuple[int, int]:
    start = lines.index(ORDEN_HEADING)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith(("## ", "---"))),
        len(lines),
    )
    return start, end


def orden_contradictions(backlog: list[str]) -> list[str]:
    """Lines outside the Orden that call one of its open steps unprioritised."""
    start, end = _orden_span(backlog)
    open_ids: list[str] = []
    for line in backlog[start + 1 : end]:
        step = re.match(r"\s*\d+\.\s+(.*)", line)
        if step:
            open_ids += BOLD_ID_RE.findall(STRUCK_RE.sub("", step.group(1)))
    found = []
    for rid in open_ids:
        named = re.compile(r"\*\*" + re.escape(rid) + r"(?![A-Za-z0-9-])")
        for n, line in enumerate(backlog, 1):
            if start <= n - 1 < end or not named.search(line):
                continue
            stale = STALE_STATUS_RE.search(line)
            if stale:
                found.append(f"BACKLOG:{n}: {rid} es paso abierto del Orden y la línea dice «{stale.group(0)}»")
    return found


def unarchived_reprioritizations(backlog: list[str], roadmap: str) -> list[str]:
    """Ordinals before the vigente one with no entry in ROADMAP's archive.

    The vigente lives only in BACKLOG; each one it replaced goes to the archive
    (BACKLOG «Cómo mantener este archivo»). Only the archive section counts —
    other ROADMAP entries name repriorizaciones in passing. The dump heading
    («de la primera a la decimotercera») covers its range; after it, each one is
    a bullet whose first ordinal is its own.
    """
    start, end = _orden_span(backlog)
    first = next(line for line in backlog[start + 1 : end] if line.strip())
    current = _ordinal(first.split()[0])
    assert current, f"el Orden no arranca con el ordinal de su repriorización: {first[:60]!r}"
    # The heading at the start of a line: entries may quote it in their prose.
    head = re.search(r"^" + re.escape(ARCHIVE_HEADING), roadmap, re.MULTILINE)
    assert head, f"ROADMAP.md perdió «{ARCHIVE_HEADING}»"
    archive = roadmap[head.start():]
    nxt = re.search(r"^## ", archive[1:], re.MULTILINE)
    archive = archive[: nxt.start() + 1] if nxt else archive
    sub = re.search(r"^" + re.escape(REPRIO_HEADING), archive, re.MULTILINE)
    assert sub, f"«{ARCHIVE_HEADING}» perdió «{REPRIO_HEADING}»"
    reprio = archive[sub.start():]
    heading, _, body = reprio.partition("\n")
    body = body.split("\n### ", 1)[0]
    covered: set[int] = set()
    span = re.search(r"de la (\w+) a la (\w+)", heading)
    if span:
        covered |= set(range(_ordinal(span.group(1)) or 1, (_ordinal(span.group(2)) or 0) + 1))
    for line in body.split("\n"):
        if line.startswith("- ") and (n := _first_ordinal(line)):
            covered.add(n)
    return [
        f"ROADMAP «{ARCHIVE_HEADING}»: falta la repriorización {ORDINAL_STEMS[n - 1]}(a) "
        f"(la vigente es la {ORDINAL_STEMS[current - 1]}a)"
        for n in range(1, current)
        if n not in covered
    ]


def test_orden_and_backlog_rows_agree():
    found = orden_contradictions(_lines("docs/BACKLOG.md"))
    assert found == [], "\n".join(found)


def test_every_replaced_reprioritization_is_archived():
    missing = unarchived_reprioritizations(
        _lines("docs/BACKLOG.md"), (ROOT / "docs/ROADMAP.md").read_text(encoding="utf-8")
    )
    assert missing == [], "\n".join(missing)


# The cases the two checks exist for, as they stood on `3dcfa3b`.
_BACKLOG_3DCFA3B = """## Orden actual

Decimoctava repriorización (2026-10-10, sobre `a7fe27a`): dos PRs chicos.

1. ~~**CACHE-RACE-IT**: banda 5. Un PR, solo tests.~~
2. **GOAL-PRIORITY-TEXT**: banda 5. Un PR.
3. Repriorización: PORTFOLIO-FX, IDEA-4 o IDEA-5, que decide el usuario.

---

| **GOAL-PRIORITY-TEXT** | 5 | Una meta importada a mano. Anotado el 2026-10-02, **no priorizado**. Ver bloque 4 |
| **PIT-TOOLS** | 5 | Prerrequisito de ReAct. Sin orden |
- **GOAL-PRIORITY-TEXT — una meta importada a mano con la prioridad en texto** (2026-10-02; banda 5, sin orden).
- ~~**CACHE-RACE-IT**~~ — cerrada, sin orden.
""".split("\n")

_ROADMAP_ARCHIVE = """## ORDEN-COHERENCIA — una entrada que cita «## Archivo del backlog» en su prosa

## Archivo del backlog (hasta 2026-10-02)

### Repriorizaciones (`/decidir-proyecto`), de la primera a la decimotercera

- **Decimocuarta `/decidir-proyecto` sobre `b3441aa` (2026-10-03)**: la reemplazó la decimoquinta.
- **Decimotercera `/decidir-proyecto` sobre `c0d959b` (2026-10-02)**: sin issues.

### Filas cerradas según el BACKLOG, en el orden del original

- **X** (paso de la decimosexta y la decimoséptima).
"""


def test_an_open_step_called_unprioritised_is_caught():
    found = orden_contradictions(_BACKLOG_3DCFA3B)
    assert [f.split(":")[1] for f in found] == ["11", "13"]
    assert all("GOAL-PRIORITY-TEXT" in f for f in found)


def test_a_reprioritization_named_only_in_passing_is_not_archived():
    """«la reemplazó la decimoquinta» and a closed row naming the decimosexta do not count."""
    missing = unarchived_reprioritizations(_BACKLOG_3DCFA3B, _ROADMAP_ARCHIVE)
    assert [m.split("repriorización ")[1].split(" ")[0] for m in missing] == [
        "decimoquint(a)", "decimosext(a)", "decimoséptim(a)",
    ]
