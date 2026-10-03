"""scripts/estado.py says where the repo stands, and flags the SHAs that drift.

Runs with ``--offline``: the network steps (``git ls-remote``, ``gh``) are the
only ones that leave the machine, and they are a subprocess the network guard
cannot see.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.estado import drift, main, orden_actual

ROOT = Path(__file__).resolve().parents[1]


def test_orden_actual_is_the_block_under_its_heading():
    backlog = ["# Backlog", "", "## Orden actual", "", "1. **A** — uno.", "", "---", "## Otro"]
    assert orden_actual(backlog) == ["1. **A** — uno."]
    assert orden_actual(["# Backlog"]) == ["(el BACKLOG no tiene «## Orden actual»)"]


def test_orden_actual_reads_the_real_backlog():
    block = orden_actual((ROOT / "docs/BACKLOG.md").read_text(encoding="utf-8").split("\n"))
    assert any(line.startswith("1. ") for line in block)


def test_drift_names_each_pair_that_differs():
    same = {"head": "a", "local": "a", "remote": "a", "clone": "a"}
    assert drift(same) == []
    stale = drift({**same, "local": "b"})
    assert len(stale) == 1 and "git fetch" in stale[0]
    assert drift({**same, "clone": "b"}) == [
        "el clon real no está en origin/main: su base, su venv y su scheduler "
        "corren otro código"
    ]
    # Without the network the local ref stands in for main.
    assert drift({**same, "remote": None, "head": "b"}) == [
        "HEAD no es origin/main: lo que estudies acá no es «lo actual»"
    ]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         *args],
        cwd=cwd, capture_output=True, check=True,
    )


def test_offline_run_prints_every_section(tmp_path: Path, capsys):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/BACKLOG.md").write_text(
        "# B\n\n## Orden actual\n\n1. **FIX-A** — banda 1.\n\n---\n", encoding="utf-8"
    )
    (tmp_path / "docs/CONTEXT.md").write_text(
        "## 9. Cambios\n\n| Commit | Cambio |\n|---|---|\n| `abc1234` | **X (X)**: x. |\n",
        encoding="utf-8",
    )
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")

    assert main(["--offline", "--root", str(tmp_path), "--clone", str(tmp_path / "nope")]) == 0
    out = capsys.readouterr().out
    for heading in ("## SHA", "## PR abiertos", "## Worktrees", "## Orden actual", "§9"):
        assert heading in out
    assert "1. **FIX-A** — banda 1." in out
    assert "sin fila `(pending)`" in out
    assert "clon real: no hay repo en" in out
