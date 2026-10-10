"""Oráculo VENV-FROM-LOCK: el venv local se instala del mismo lock que el CI y Docker.

``run.sh`` instalaba ``-r requirements.txt`` (los rangos) y sólo cuando
``requirements.txt`` era más nuevo que el stamp, así que el venv quedó en Streamlit
1.57.0 con el lock en 1.61.1 y el CI en 1.65.0, y cinco tests fallaban sólo en local
(2026-10-10). STREAMLIT-ALIGN alineó el CI y Docker; esto cierra el camino local. Los
tests de comportamiento corren ``run.sh --setup`` en un directorio temporal con un
``pip`` falso: no instalan nada ni salen a la red.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _fake_repo(tmp_path: Path, *, shared: bool) -> tuple[Path, Path]:
    """Copia ``run.sh`` y los requirements; ``venv`` con un ``pip`` que anota sus args."""
    root = tmp_path / "repo"
    root.mkdir()
    for name in ("run.sh", "requirements.lock", "requirements-dev.txt", "requirements.txt"):
        shutil.copy(REPO / name, root / name)
    venv = tmp_path / "real-venv" if shared else root / "venv"
    (venv / "bin").mkdir(parents=True)
    log = tmp_path / "pip.log"
    (venv / "bin" / "activate").write_text(
        f'pip() {{ echo "$*" >> "{log}"; }}\n', encoding="utf-8"
    )
    if shared:
        (root / "venv").symlink_to(venv, target_is_directory=True)
    return root, log


def _setup(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "run.sh", "--setup"], cwd=root, capture_output=True, text=True,
        env={**os.environ, "PYTHON": "python3"}, check=True,
    )


def _calls(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_setup_installs_the_lock_then_the_dev_tools(tmp_path):
    root, log = _fake_repo(tmp_path, shared=False)
    _setup(root)
    installs = [c for c in _calls(log) if c.startswith("install") and "-r" in c]
    assert installs == [
        "install --quiet --require-hashes -r requirements.lock",
        "install --quiet -r requirements-dev.txt",
    ]


def test_nothing_installs_from_the_ranges():
    run_sh = (REPO / "run.sh").read_text(encoding="utf-8")
    make = (REPO / "Makefile").read_text(encoding="utf-8")
    [setup] = re.findall(r"^setup:\n((?:\t.*\n?)+)", make, flags=re.M)
    assert "-r requirements.txt" not in run_sh
    assert "requirements.txt" not in setup.replace("requirements-dev.txt", "")


def test_the_stamp_follows_the_locks_content_not_a_file_date(tmp_path):
    root, log = _fake_repo(tmp_path, shared=False)
    _setup(root)
    expected = hashlib.sha256(
        (root / "requirements.lock").read_bytes() + (root / "requirements-dev.txt").read_bytes()
    ).hexdigest()
    assert (root / "venv" / ".deps-installed").read_text().strip() == expected

    first = len(_calls(log))
    os.utime(root / "requirements.txt")      # a fresh checkout dates every file today
    os.utime(root / "requirements.lock")
    _setup(root)
    assert len(_calls(log)) == first          # same content: nothing reinstalled

    with (root / "requirements-dev.txt").open("a", encoding="utf-8") as fh:
        fh.write("\n# changed\n")
    _setup(root)
    assert len(_calls(log)) > first           # new content: reinstalled


def test_a_worktree_never_installs_into_the_shared_venv(tmp_path):
    root, log = _fake_repo(tmp_path, shared=True)
    out = _setup(root)
    assert _calls(log) == []
    assert "venv compartido" in out.stdout
    assert not (root / "venv" / ".deps-installed").exists()
