#!/usr/bin/env python3
"""Close a BACKLOG row, or log a PR, in the docs every PR touches.

Each PR ends with the same edits, and each session rediscovered them by reading
the previous entry; four of the ten sessions in the 2026-10-03 retro wrote
throwaway Python to make them. The edits:

1. CONTEXT §9: the previous PR's ``(pending)`` row gets its merge SHA, and this
   PR's row goes on top as ``(pending)`` (docs/MAINTENANCE.md §1).
2. CONTEXT «Última actualización»: one line, date and id (CONTEXT §10).
3. ROADMAP: the entry ``## ID — title (date)`` above the newest one.
4. BACKLOG: the row leaves «Abiertas hoy» and its step in ``## Orden actual``
   is struck through.

The prose — the §9 cell and the ROADMAP body — is the caller's; this script
only places it. Dry run by default: prints the diff. ``--write`` applies it and
then lists the BACKLOG lines that still name the id, which are judgment calls
(the Bloque detail, «Esperan disparador», a rewrite of ``## Orden actual``).

Usage:
    ./venv/bin/python3 scripts/close_row.py ID --title "frase" \\
        --context-row fila.md --roadmap-body entrada.md [--write]
    # A PR that closes no row (docs, a partial PR): only CONTEXT
    ./venv/bin/python3 scripts/close_row.py ID --title "frase" \\
        --context-row fila.md --no-row [--write]
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONTEXT = "docs/CONTEXT.md"
BACKLOG = "docs/BACKLOG.md"
ROADMAP = "docs/ROADMAP.md"

PENDING_ROW_PREFIX = "| `(pending)` |"
HEADER_PREFIX = "> Última actualización:"
ROADMAP_ANCHOR_PREFIX = "## ✅"
OPEN_TABLE_MARKER = "**Abiertas hoy**"
ORDEN_HEADING = "## Orden actual"


class CloseError(Exception):
    """A precondition failed; nothing was written."""


def _first_upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _first_lower(text: str) -> str:
    # «PDF del plan» keeps its acronym; «Volver a…» becomes «volver a…».
    if len(text) > 1 and text[1].isupper():
        return text
    return text[:1].lower() + text[1:]


def _section_9(lines: list[str]) -> tuple[int, int]:
    start = next((i for i, line in enumerate(lines) if line.startswith("## 9.")), None)
    if start is None:
        raise CloseError(f"{CONTEXT} no tiene la sección «## 9.»")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
    )
    return start, end


def pending_title(context: list[str]) -> str | None:
    """Bold title of the §9 ``(pending)`` row, or None when every row has a SHA."""
    start, end = _section_9(context)
    rows = [line for line in context[start:end] if line.startswith(PENDING_ROW_PREFIX)]
    if len(rows) > 1:
        raise CloseError(
            f"CONTEXT §9 tiene {len(rows)} filas `(pending)`: resolvelas a mano primero "
            "(tests/test_context_changelog_pending.py)"
        )
    if not rows:
        return None
    match = re.search(r"\*\*.+?\*\*", rows[0])
    if not match:
        raise CloseError("la fila `(pending)` de CONTEXT §9 no abre con un título en negrita")
    return match.group(0)


def _git(root: Path, *args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    return out.split()


def merge_sha_for(title: str, root: Path, ref: str = "origin/main") -> str:
    """SHA that brought the §9 row titled ``title`` into ``ref``.

    The commit that introduced the title, then the first merge on ``ref``'s
    first-parent chain that contains it. «The latest merge» would be wrong as
    soon as anything else merged in between. A commit made on ``ref`` itself
    (squash, direct push) is its own answer.

    The descendant merges are listed without ``--first-parent`` and then
    filtered to ``ref``'s chain: combined with ``--ancestry-path``, that flag
    only follows first parents, so it found the merge only when the row came in
    the branch's last commit (EO-2a and EO-2b came back empty).
    """
    introduced = _git(root, "log", ref, "--format=%H", f"-S{title}", "--", CONTEXT)
    if not introduced:
        raise CloseError(
            f"la fila `(pending)` {title} no está en {ref}: ¿es de esta rama? "
            "Hacé `git fetch` o pasá --pending-sha"
        )
    commit = introduced[-1]
    chain = set(_git(root, "rev-list", "--first-parent", ref))
    if commit in chain:
        return commit[:7]
    merges = _git(
        root, "rev-list", "--reverse", "--merges", "--ancestry-path", f"{commit}..{ref}",
    )
    on_chain = [m for m in merges if m in chain]
    if not on_chain:
        raise CloseError(f"no encontré el merge de {commit[:7]} en {ref}; pasá --pending-sha")
    return on_chain[0][:7]


def update_context(
    context: list[str], row_id: str, title: str, text: str, today: str, pending_sha: str | None
) -> list[str]:
    lines = list(context)
    start, end = _section_9(lines)

    pending = [i for i in range(start, end) if lines[i].startswith(PENDING_ROW_PREFIX)]
    if pending:
        if pending_sha is None:
            raise CloseError("hay una fila `(pending)` y no sé su SHA")
        old = lines[pending[0]]
        if f"({row_id})" in old or f"({row_id}," in old:
            raise CloseError(
                f"la fila `(pending)` ya es de {row_id}: editala en vez de agregar otra"
            )
        lines[pending[0]] = f"| `{pending_sha}` |" + old[len(PENDING_ROW_PREFIX):]

    cell = " ".join(part.strip() for part in text.strip().splitlines() if part.strip())
    if not cell:
        raise CloseError("--context-row está vacío")
    if re.search(r"(?<!\\)\|", cell):
        raise CloseError("la fila de §9 tiene un `|` sin escapar: rompe la tabla (usá `\\|`)")
    separator = next(
        (i for i in range(start, end) if re.fullmatch(r"\|[-: |]+\|", lines[i].strip())), None
    )
    if separator is None:
        raise CloseError("no encontré la tabla de CONTEXT §9")
    lines.insert(separator + 1, f"| `(pending)` | **{_first_upper(title)} ({row_id})**: {cell} |")

    header = next((i for i, line in enumerate(lines[:10]) if line.startswith(HEADER_PREFIX)), None)
    if header is None:
        raise CloseError(f"{CONTEXT} perdió su línea «Última actualización»")
    lines[header] = (
        f"{HEADER_PREFIX} {today} (**{row_id}**). El detalle de cada cambio es su fila de §9."
    )
    return lines


def update_roadmap(
    roadmap: list[str], row_id: str, title: str, body: str, today: str
) -> list[str]:
    if any(line.startswith(f"## {row_id} — ") for line in roadmap):
        raise CloseError(f"{ROADMAP} ya tiene «## {row_id} — …»: ¿la fila ya estaba cerrada?")
    anchor = next(
        (i for i, line in enumerate(roadmap) if line.startswith(ROADMAP_ANCHOR_PREFIX)), None
    )
    if anchor is None:
        raise CloseError(f"{ROADMAP} perdió la sección «{ROADMAP_ANCHOR_PREFIX} Todo implementado…»")
    newest = next(
        (i for i in range(anchor + 1, len(roadmap)) if roadmap[i].startswith("## ")), None
    )
    if newest is None:
        raise CloseError(f"{ROADMAP} no tiene entradas después de «{ROADMAP_ANCHOR_PREFIX}»")
    body_lines = [line.rstrip() for line in body.strip().splitlines()]
    if not body_lines:
        raise CloseError("--roadmap-body está vacío")
    entry = [f"## {row_id} — {_first_lower(title)} ({today})", "", *body_lines, "", "---", ""]
    return roadmap[:newest] + entry + roadmap[newest:]


def _cell_ids(line: str) -> list[str]:
    cells = line.split("|")
    return re.findall(r"\*\*(.+?)\*\*", cells[1]) if len(cells) > 2 else []


def update_backlog(backlog: list[str], row_id: str) -> list[str]:
    lines = list(backlog)
    marker = next((i for i, line in enumerate(lines) if OPEN_TABLE_MARKER in line), None)
    if marker is None:
        raise CloseError(f"{BACKLOG} perdió la tabla «{OPEN_TABLE_MARKER}»")
    table_start = next(i for i in range(marker, len(lines)) if lines[i].startswith("|"))
    table_end = next(
        (i for i in range(table_start, len(lines)) if not lines[i].startswith("|")), len(lines)
    )
    hits = [
        i
        for i in range(table_start, table_end)
        if any(x == row_id or x.startswith(f"{row_id} ") for x in _cell_ids(lines[i]))
    ]
    if not hits:
        raise CloseError(
            f"{row_id} no está en «{OPEN_TABLE_MARKER}» de {BACKLOG}. "
            "Si el PR no cierra una fila, usá --no-row"
        )
    if len(_cell_ids(lines[hits[0]])) > 1:
        raise CloseError(
            f"{row_id} comparte fila con {_cell_ids(lines[hits[0]])}: editala a mano"
        )
    del lines[hits[0]]

    orden = lines.index(ORDEN_HEADING) if ORDEN_HEADING in lines else None
    if orden is not None:
        step_re = re.compile(rf"^(\d+)\. (\*\*{re.escape(row_id)}(?=[\s*,]).*)$")
        for i in range(orden + 1, len(lines)):
            if lines[i].startswith(("## ", "---")):
                break
            match = step_re.match(lines[i])
            if match:
                lines[i] = f"{match.group(1)}. ~~{match.group(2)}~~"
    return lines


def remaining_mentions(backlog: list[str], row_id: str) -> list[str]:
    return [
        f"  {BACKLOG}:{n}: {line[:140]}"
        for n, line in enumerate(backlog, 1)
        if row_id in line
    ]


def _diff(rel: str, old: list[str], new: list[str]) -> str:
    return "".join(
        difflib.unified_diff(
            [f"{line}\n" for line in old],
            [f"{line}\n" for line in new],
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )


def _read(root: Path, rel: str) -> list[str]:
    return (root / rel).read_text(encoding="utf-8").split("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cierra una fila del BACKLOG o registra un PR en CONTEXT §9 y ROADMAP."
    )
    parser.add_argument("id", help="id de la fila, p. ej. KATEX-DOLLAR-PLAN")
    parser.add_argument("--title", required=True, help="la frase del título, sin el id")
    parser.add_argument("--context-row", required=True, type=Path, help="texto de la celda de §9")
    parser.add_argument("--roadmap-body", type=Path, help="cuerpo de la entrada de ROADMAP")
    parser.add_argument("--no-row", action="store_true", help="el PR no cierra una fila del BACKLOG")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--pending-sha", help="SHA para la fila `(pending)` (default: lo busca en git)")
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true", help="aplicar (default: mostrar el diff)")
    args = parser.parse_args(argv)

    try:
        if not args.no_row and args.roadmap_body is None:
            raise CloseError("cerrar una fila lleva entrada en ROADMAP: pasá --roadmap-body")
        files = {rel: _read(args.root, rel) for rel in (CONTEXT, BACKLOG, ROADMAP)}
        new = dict(files)

        pending_sha = args.pending_sha
        title_of_pending = pending_title(files[CONTEXT])
        if title_of_pending and pending_sha is None:
            pending_sha = merge_sha_for(title_of_pending, args.root, args.ref)
        new[CONTEXT] = update_context(
            files[CONTEXT],
            args.id,
            args.title,
            args.context_row.read_text(encoding="utf-8"),
            args.date,
            pending_sha,
        )
        if args.roadmap_body is not None:
            new[ROADMAP] = update_roadmap(
                files[ROADMAP],
                args.id,
                args.title,
                args.roadmap_body.read_text(encoding="utf-8"),
                args.date,
            )
        if not args.no_row:
            new[BACKLOG] = update_backlog(files[BACKLOG], args.id)
    except CloseError as err:
        sys.stderr.write(f"close_row: {err}\n")
        return 1

    for rel in (CONTEXT, BACKLOG, ROADMAP):
        if new[rel] != files[rel]:
            if args.write:
                (args.root / rel).write_text("\n".join(new[rel]), encoding="utf-8")
            else:
                sys.stdout.write(_diff(rel, files[rel], new[rel]))

    if title_of_pending:
        sys.stdout.write(f"\n`(pending)` {title_of_pending} → `{pending_sha}`\n")
    left = remaining_mentions(new[BACKLOG], args.id)
    if left:
        sys.stdout.write(f"\n{args.id} sigue nombrado en el BACKLOG; revisá cada línea:\n")
        sys.stdout.write("\n".join(left) + "\n")
    if not args.write:
        sys.stdout.write("\n(dry run: nada escrito; --write para aplicar)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
