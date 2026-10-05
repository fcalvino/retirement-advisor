"""scripts/close_row.py places a PR's closing edits where the docs expect them.

The fixtures are a miniature of the real trio: the parts the script reads
(CONTEXT header and §9, BACKLOG ``## Orden actual`` and «Abiertas hoy», the
ROADMAP anchor) with the shapes they had on 2026-10-03. ``--pending-sha`` and
``--date`` are always passed, so nothing depends on the repo's history or the
clock; the SHA lookup has its own test on a throwaway git repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.close_row import CloseError, main, merge_sha_for
from tests.test_context_changelog_pending import changelog_commit_cells, pending_violations

CONTEXT = """# Project Context

> Se lee por sección.
> Última actualización: 2026-10-02 (**OLD-ID** — un resumen largo que se acumulaba).

---

## 9. Últimos Cambios Importantes

| Commit | Cambio |
|--------|--------|
| `(pending)` | **Algo anterior (OLD-ID)**: texto. |
| `abc1234` | **Más viejo (OLDER)**: texto. |

---

## 10. Cómo Actualizar Este Archivo
"""

BACKLOG = """# Backlog

## Orden actual

1. **FIX-A** — banda 1.
2. **FIX-B, PR 2** — las superficies.

Esperan disparador: FIX-C.

---

## Estado verificado

**Abiertas hoy**, verificadas contra el código:

| id | banda | qué |
|---|---|---|
| **FIX-A** | 1 | El defecto A. |
| **FIX-B** | 4 | El defecto B. |
| **FIX-C** / **FIX-D** | 5 | Dos mediciones. |
| **IDEA-4 CHAT** | 5 | Una idea. |

## Bloque 1

- **FIX-A — el detalle** (2026-10-01).
"""

ROADMAP = """# Estado del Proyecto

## ✅ Todo implementado y en producción (GitHub main)

Trabajo ya completado.

---

## FIX-Z — lo último que cerró (2026-10-01)

Cuerpo.
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    for name, text in (("CONTEXT", CONTEXT), ("BACKLOG", BACKLOG), ("ROADMAP", ROADMAP)):
        (tmp_path / "docs" / f"{name}.md").write_text(text, encoding="utf-8")
    (tmp_path / "row.md").write_text("el arreglo,\nen dos líneas.\n", encoding="utf-8")
    (tmp_path / "body.md").write_text("Primer párrafo.\n\nOráculo `t.py`.\n", encoding="utf-8")
    return tmp_path


def _run(repo: Path, *extra: str) -> int:
    return main(
        [
            "FIX-A",
            "--title", "Volver a la pantalla funciona",
            "--context-row", str(repo / "row.md"),
            "--pending-sha", "d34e9d5",
            "--date", "2026-10-03",
            "--root", str(repo),
            *extra,
        ]
    )


def _doc(repo: Path, name: str) -> str:
    return (repo / "docs" / f"{name}.md").read_text(encoding="utf-8")


def test_dry_run_writes_nothing(repo: Path, capsys):
    assert _run(repo, "--roadmap-body", str(repo / "body.md")) == 0
    assert _doc(repo, "CONTEXT") == CONTEXT
    assert _doc(repo, "BACKLOG") == BACKLOG
    assert _doc(repo, "ROADMAP") == ROADMAP
    assert "+| `(pending)` | **Volver a la pantalla funciona (FIX-A)**" in capsys.readouterr().out


def test_closing_a_row_makes_the_four_edits(repo: Path, capsys):
    assert _run(repo, "--roadmap-body", str(repo / "body.md"), "--write") == 0

    context = _doc(repo, "CONTEXT")
    assert "> Última actualización: 2026-10-03 (**FIX-A**). El detalle de cada cambio es su fila de §9." in context
    assert changelog_commit_cells(context)[:3] == ["(pending)", "d34e9d5", "abc1234"]
    assert pending_violations(changelog_commit_cells(context)) == []
    assert (
        "| `(pending)` | **Volver a la pantalla funciona (FIX-A)**: el arreglo, en dos líneas. |"
        in context
    )

    roadmap = _doc(repo, "ROADMAP")
    assert roadmap.index("## FIX-A — volver a la pantalla funciona (2026-10-03)") < roadmap.index(
        "## FIX-Z"
    )
    assert "Primer párrafo.\n\nOráculo `t.py`.\n\n---\n\n## FIX-Z" in roadmap

    backlog = _doc(repo, "BACKLOG")
    assert "| **FIX-A** |" not in backlog
    assert "| **FIX-B** |" in backlog
    assert "1. ~~**FIX-A** — banda 1.~~" in backlog
    assert "2. **FIX-B, PR 2** — las superficies." in backlog
    # The Bloque detail is a judgment call: kept, and listed for the caller.
    assert "- **FIX-A — el detalle**" in backlog
    assert "- **FIX-A — el detalle**" in capsys.readouterr().out


def test_a_pr_without_a_row_only_touches_context(repo: Path):
    assert _run(repo, "--no-row", "--write") == 0
    assert "| `(pending)` | **Volver a la pantalla funciona (FIX-A)**" in _doc(repo, "CONTEXT")
    assert _doc(repo, "BACKLOG") == BACKLOG
    assert _doc(repo, "ROADMAP") == ROADMAP


def test_id_with_a_suffix_in_its_cell_matches(repo: Path):
    assert main(
        ["IDEA-4", "--title", "x", "--context-row", str(repo / "row.md"),
         "--roadmap-body", str(repo / "body.md"), "--pending-sha", "d34e9d5",
         "--date", "2026-10-03", "--root", str(repo), "--write"]
    ) == 0
    assert "IDEA-4 CHAT" not in _doc(repo, "BACKLOG")


@pytest.mark.parametrize(
    ("row_id", "extra", "message"),
    [
        ("FIX-A", [], "--roadmap-body"),
        ("FIX-Y", ["--roadmap-body", "body.md"], "no está en «**Abiertas hoy**»"),
        ("FIX-C", ["--roadmap-body", "body.md"], "comparte fila"),
        ("FIX-Z", ["--roadmap-body", "body.md"], "ya tiene «## FIX-Z — …»"),
        ("OLD-ID", ["--no-row"], "ya es de OLD-ID"),
    ],
)
def test_refuses_and_writes_nothing(repo: Path, capsys, row_id, extra, message):
    extra = [str(repo / e) if e.endswith(".md") else e for e in extra]
    args = [row_id, "--title", "x", "--context-row", str(repo / "row.md"),
            "--pending-sha", "d34e9d5", "--date", "2026-10-03", "--root", str(repo),
            "--write", *extra]
    assert main(args) == 1
    assert message in capsys.readouterr().err
    assert _doc(repo, "CONTEXT") == CONTEXT
    assert _doc(repo, "BACKLOG") == BACKLOG
    assert _doc(repo, "ROADMAP") == ROADMAP


def test_unescaped_pipe_would_break_the_table(repo: Path, capsys):
    (repo / "row.md").write_text("a | b", encoding="utf-8")
    assert _run(repo, "--no-row", "--write") == 1
    assert "sin escapar" in capsys.readouterr().err


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_pending_sha_is_the_merge_that_brought_the_row(tmp_path: Path):
    """Not «the latest merge»: another PR merged after it must not win."""
    (tmp_path / "docs").mkdir()
    ctx = tmp_path / "docs" / "CONTEXT.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    ctx.write_text("| `abc1234` | **Viejo (OLD)**: x. |\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")

    _git(tmp_path, "switch", "-q", "-c", "pr-1")
    ctx.write_text("| `(pending)` | **Nuevo (NEW)**: x. |\n" + ctx.read_text(), encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "pr 1")
    _git(tmp_path, "switch", "-q", "main")
    _git(tmp_path, "merge", "-q", "--no-ff", "pr-1", "-m", "Merge pr-1")
    expected = _git(tmp_path, "rev-parse", "--short=7", "HEAD")

    _git(tmp_path, "switch", "-q", "-c", "pr-2")
    (tmp_path / "other.txt").write_text("y", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "pr 2")
    _git(tmp_path, "switch", "-q", "main")
    _git(tmp_path, "merge", "-q", "--no-ff", "pr-2", "-m", "Merge pr-2")

    assert merge_sha_for("**Nuevo (NEW)**", tmp_path, "main") == expected

    # A commit made on main itself (squash) is its own SHA.
    ctx.write_text("| `(pending)` | **Directo (DIR)**: x. |\n" + ctx.read_text(), encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "direct")
    assert merge_sha_for("**Directo (DIR)**", tmp_path, "main") == _git(
        tmp_path, "rev-parse", "--short=7", "HEAD"
    )

    with pytest.raises(CloseError, match="no está en main"):
        merge_sha_for("**Nunca (NEVER)**", tmp_path, "main")


def test_the_row_can_come_in_a_commit_that_is_not_the_branch_tip(tmp_path: Path):
    """EO-2a (2de5baa) and EO-2b (49221b7): the row came in the PR's first commit and
    a second commit followed. ``--first-parent`` with ``--ancestry-path`` only saw a
    merge whose second parent was the row's commit itself, so the lookup came back
    empty and ``estado.py`` called a merged PR «una rama abierta»."""
    (tmp_path / "docs").mkdir()
    ctx = tmp_path / "docs" / "CONTEXT.md"
    _git(tmp_path, "init", "-q", "-b", "main")
    ctx.write_text("| `abc1234` | **Viejo (OLD)**: x. |\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    # main moves on its own before the PR merges, so the merge's first parent is
    # not an ancestor of the row's commit.
    _git(tmp_path, "switch", "-q", "-c", "pr-1")
    ctx.write_text("| `(pending)` | **Dos commits (TWO)**: x. |\n" + ctx.read_text(),
                   encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "pr 1: la fila")
    (tmp_path / "fix.txt").write_text("y", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "pr 1: un arreglo después")
    _git(tmp_path, "switch", "-q", "main")
    (tmp_path / "main.txt").write_text("z", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "otro cambio en main")
    _git(tmp_path, "merge", "-q", "--no-ff", "pr-1", "-m", "Merge pr-1")
    expected = _git(tmp_path, "rev-parse", "--short=7", "HEAD")

    assert merge_sha_for("**Dos commits (TWO)**", tmp_path, "main") == expected
