"""Catalog completeness — drives scripts/check_doc_catalog.py on the real tree."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_doc_catalog.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_doc_catalog", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_shipped_checker_exists():
    assert SCRIPT.is_file()


def test_catalog_covers_every_first_party_product_md():
    checker = _load_checker()
    report = checker.check_catalog(ROOT)

    assert report.errors == [], "\n".join(report.errors)
    assert report.delete == 0
    assert report.keep == len(
        [rel for rel in report.inventory if checker.is_product_doc(rel)]
    )
    assert report.keep > 0
    for required_role in (
        "catalog",
        "living-guide",
        "methodology",
        "ai-context",
        "historical-audit",
        "historical-plan",
        "ideation",
        "archive",
    ):
        assert required_role in report.role_counts, required_role

    assert not (ROOT / "RESUMEN_EJECUTIVO.md").exists()
    assert not (ROOT / "docs" / "CHANGELOG.md").exists()


def test_summary_is_deterministic():
    checker = _load_checker()
    first = checker.check_catalog(ROOT).summary()
    second = checker.check_catalog(ROOT).summary()
    assert first == second
    assert first.startswith("keep=")
    assert "delete=0" in first
    assert first.endswith("ok\n")


def test_cli_entry_point_exits_zero_with_stable_counts():
    """Drive the shipped script the same way a maintainer would."""
    cmd = [sys.executable, str(SCRIPT)]
    runs = [
        subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        for _ in range(2)
    ]
    assert runs[0].returncode == 0, runs[0].stderr
    assert runs[1].returncode == 0, runs[1].stderr
    assert runs[0].stdout == runs[1].stdout
    assert "keep=" in runs[0].stdout
    assert "delete=0" in runs[0].stdout
    assert runs[0].stdout.strip().endswith("ok")
