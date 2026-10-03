#!/usr/bin/env python3
"""Where the repo stands: the state every session rebuilt before its first edit.

The 2026-10-03 retro (``docs/retro/2026-10-03.md``, item A) counted 18–40 tool
calls per session before the first edit, the same block each time: HEAD,
origin/main, the real clone, open PRs, worktrees, then the BACKLOG. This prints
it in one call. Read-only: no fetch, no checkout, no project import.

- the three SHAs decidir-proyecto asks for, and which of them differ;
- whether the local ``origin/main`` lags the remote (then ``git log origin/main``
  and ``close_row.py`` read old history);
- open PRs with their base branch, and the worktrees;
- BACKLOG ``## Orden actual``;
- the CONTEXT §9 ``(pending)`` row and, once merged, the SHA ``close_row.py``
  will give it.

``git ls-remote`` and ``gh`` need the network; without it they print a
«sin red» line instead of failing. ``--offline`` skips them.

Usage:
    make estado
    ~/retirement_advisor/venv/bin/python3 scripts/estado.py [--offline]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from scripts.close_row import (
    BACKLOG,
    CONTEXT,
    ORDEN_HEADING,
    CloseError,
    merge_sha_for,
    pending_title,
)

ROOT = Path(__file__).resolve().parent.parent
#: The clone whose database, venv and scheduler are the user's (decidir-proyecto).
REAL_CLONE = Path.home() / "retirement_advisor"


def _run(args: list[str], cwd: Path, timeout: float = 20) -> str | None:
    try:
        return subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=True
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _describe(cwd: Path, rev: str | None) -> str:
    if rev is None:
        return "?"
    line = _run(["git", "log", "-1", "--format=%h %cs %s", rev], cwd)
    return line[:90] if line else f"{rev[:7]} (no está en este clon: falta `git fetch`)"


def orden_actual(backlog: list[str]) -> list[str]:
    """The ``## Orden actual`` block of the BACKLOG, without its heading."""
    if ORDEN_HEADING not in backlog:
        return [f"(el BACKLOG no tiene «{ORDEN_HEADING}»)"]
    start = backlog.index(ORDEN_HEADING) + 1
    block = []
    for line in backlog[start:]:
        if line.startswith(("## ", "---")):
            break
        block.append(line)
    while block and not block[0].strip():
        block.pop(0)
    while block and not block[-1].strip():
        block.pop()
    return block


def drift(shas: dict[str, str | None]) -> list[str]:
    """Warnings for the SHA pairs that should match and don't."""
    remote, local = shas.get("remote"), shas.get("local")
    clone, head = shas.get("clone"), shas.get("head")
    main = remote or local
    out = []
    if remote and local and remote != local:
        out.append(
            "origin/main local no es el remoto: `git fetch` antes de leer historia "
            "o de correr close_row.py"
        )
    if clone and main and clone != main:
        out.append(
            "el clon real no está en origin/main: su base, su venv y su scheduler "
            "corren otro código"
        )
    if head and main and head != main:
        out.append("HEAD no es origin/main: lo que estudies acá no es «lo actual»")
    return out


def _pending(context: list[str], root: Path) -> str:
    try:
        title = pending_title(context)
    except CloseError as err:
        return str(err)
    if title is None:
        return "sin fila `(pending)`"
    try:
        sha = merge_sha_for(title, root)
    except CloseError:
        return f"`(pending)` {title}: todavía no está en origin/main (es de una rama abierta)"
    except subprocess.CalledProcessError:
        return f"`(pending)` {title}: no pude leer git"
    return f"`(pending)` {title} → `{sha}` (la resuelve el próximo PR con close_row.py)"


def _section(title: str, lines: list[str]) -> str:
    return "\n".join([f"## {title}", *(f"  {line}" if line else "" for line in lines), ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Estado del repo en una llamada.")
    parser.add_argument("--offline", action="store_true", help="sin ls-remote ni gh")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--clone", type=Path, default=REAL_CLONE)
    args = parser.parse_args(argv)
    root = args.root

    branch = _run(["git", "branch", "--show-current"], root) or "(HEAD suelto)"
    shas: dict[str, str | None] = {
        "head": _run(["git", "rev-parse", "HEAD"], root),
        "local": _run(["git", "rev-parse", "origin/main"], root),
        "clone": _run(["git", "rev-parse", "HEAD"], args.clone),
        "remote": None,
    }
    if not args.offline:
        listed = _run(["git", "ls-remote", "origin", "refs/heads/main"], root)
        shas["remote"] = listed.split()[0] if listed else None

    sha_lines = [
        f"HEAD ({branch}, {root}): {_describe(root, shas['head'])}",
        f"origin/main local: {_describe(root, shas['local'])}",
    ]
    if args.offline:
        sha_lines.append("origin/main remoto: (--offline)")
    elif shas["remote"] is None:
        sha_lines.append("origin/main remoto: sin red")
    else:
        sha_lines.append(f"origin/main remoto: {_describe(root, shas['remote'])}")
    clone_branch = _run(["git", "branch", "--show-current"], args.clone)
    if root.resolve() == args.clone.resolve():
        sha_lines.append("clon real: es este directorio")
    elif shas["clone"]:
        sha_lines.append(
            f"clon real ({clone_branch}, {args.clone}): {_describe(args.clone, shas['clone'])}"
        )
    else:
        sha_lines.append(f"clon real: no hay repo en {args.clone}")
    if shas["head"] and shas["local"]:
        counts = _run(["git", "rev-list", "--left-right", "--count", "origin/main...HEAD"], root)
        if counts:
            behind, ahead = counts.split()
            sha_lines.append(f"HEAD vs origin/main local: {ahead} adelante, {behind} atrás")
    sha_lines += [f"⚠ {warning}" for warning in drift(shas)]

    if args.offline:
        pr_lines = ["(--offline)"]
    else:
        raw = _run(
            ["gh", "pr", "list", "--state", "open",
             "--json", "number,title,headRefName,baseRefName,isDraft"],
            root,
        )
        if raw is None:
            pr_lines = ["sin red o sin gh"]
        else:
            prs = json.loads(raw)
            pr_lines = [
                f"#{pr['number']} {pr['title'][:70]} ({pr['headRefName']} → {pr['baseRefName']})"
                + (" [draft]" if pr["isDraft"] else "")
                + (" ⚠ base no es main" if pr["baseRefName"] != "main" else "")
                for pr in prs
            ] or ["ninguno"]

    worktrees = (_run(["git", "worktree", "list"], root) or "?").splitlines()

    def read(rel: str) -> list[str]:
        path = root / rel
        return path.read_text(encoding="utf-8").split("\n") if path.is_file() else []

    sys.stdout.write(
        "\n".join(
            [
                _section("SHA", sha_lines),
                _section("PR abiertos", pr_lines),
                _section("Worktrees", worktrees),
                _section(f"Orden actual ({BACKLOG})", orden_actual(read(BACKLOG))),
                _section(f"{CONTEXT} §9", [_pending(read(CONTEXT), root)]),
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
