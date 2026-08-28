#!/usr/bin/env python3
"""Verify every first-party markdown file is listed in docs/INDEX.md.

Walks the real repo tree (same exclusions as the docs audit) and parses the
canonical role table in docs/INDEX.md. Exit 0 only when:

- every product .md is named in the catalog or sits under a named collection
- every catalog path / markdown link resolves to an existing file
- leftover no-value docs (RESUMEN_EJECUTIVO, docs/CHANGELOG.md) are gone
- no surviving first-party .md still points at those deleted paths

Prints keep / delete / role counts (stable, sorted) so two runs can be compared.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_DIR_NAMES = frozenset(
    {"venv", ".venv", "node_modules", ".git", ".pytest_cache", "__pycache__"}
)
# Session notes, not product docs — see docs/INDEX.md and the audit non-goals.
# ``.claude/`` holds harness scratch (resume checkpoints, local settings) written
# by the tooling, not documentation a maintainer curates.
EXCLUDE_PREFIXES = ("logs/", "qa/", ".claude/")

MUST_NOT_EXIST = (
    "RESUMEN_EJECUTIVO.md",
    "docs/CHANGELOG.md",
)
FORBIDDEN_SUBSTRINGS = (
    "docs/CHANGELOG.md",
    "RESUMEN_EJECUTIVO.md",
)

CATALOG_TABLE_RE = re.compile(
    r"<!-- catalog-table -->(.*?)<!-- /catalog-table -->",
    re.DOTALL,
)
ROW_RE = re.compile(
    r"^\|\s*(?P<role>[a-z][a-z0-9_-]*)\s*\|\s*`(?P<path>[^`]+)`\s*\|",
    re.MULTILINE,
)
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

VALID_ROLES = frozenset(
    {
        "catalog",
        "living-guide",
        "methodology",
        "how-to",
        "ai-context",
        "historical-audit",
        "historical-plan",
        "ideation",
        "archive",
    }
)


@dataclass
class CatalogReport:
    keep: int = 0
    delete: int = 0
    role_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    inventory: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary_lines(self) -> list[str]:
        lines = [f"keep={self.keep}", f"delete={self.delete}"]
        for role in sorted(self.role_counts):
            lines.append(f"role.{role}={self.role_counts[role]}")
        lines.append("ok" if self.ok else "FAIL")
        return lines

    def summary(self) -> str:
        return "\n".join(self.summary_lines()) + "\n"


def _posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def iter_first_party_md(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*.md"):
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        found.append(path)
    return sorted(found, key=lambda p: _posix(p, root))


def is_product_doc(rel: str) -> bool:
    return not any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in EXCLUDE_PREFIXES)


def parse_catalog_table(index_text: str) -> list[tuple[str, str]]:
    match = CATALOG_TABLE_RE.search(index_text)
    if not match:
        raise ValueError("docs/INDEX.md is missing the <!-- catalog-table --> block")
    rows: list[tuple[str, str]] = []
    for row in ROW_RE.finditer(match.group(1)):
        rows.append((row.group("role"), row.group("path").strip()))
    if not rows:
        raise ValueError("catalog table parsed zero rows")
    return rows


def extract_md_links(index_text: str) -> list[str]:
    links: list[str] = []
    for raw in MD_LINK_RE.findall(index_text):
        target = raw.strip().split()[0].strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        links.append(target.split("#", 1)[0])
    return links


def check_catalog(root: Path = ROOT) -> CatalogReport:
    report = CatalogReport()
    index_path = root / "docs" / "INDEX.md"
    if not index_path.is_file():
        report.errors.append("missing docs/INDEX.md")
        return report

    leftover_present = [rel for rel in MUST_NOT_EXIST if (root / rel).exists()]
    report.delete = len(leftover_present)
    if leftover_present:
        report.errors.append("leftover docs still present: " + ", ".join(leftover_present))

    try:
        index_text = index_path.read_text(encoding="utf-8")
        rows = parse_catalog_table(index_text)
    except (OSError, ValueError) as exc:
        report.errors.append(str(exc))
        return report

    file_roles: dict[str, str] = {}
    collections: list[tuple[str, str]] = []
    for role, path in rows:
        if role not in VALID_ROLES:
            report.errors.append(f"unknown role {role!r} for {path}")
        if path.endswith("/"):
            collections.append((role, path))
            continue
        if path in file_roles:
            report.errors.append(f"duplicate catalog path {path}")
        file_roles[path] = role

    for role, prefix in collections:
        if not (root / prefix).is_dir():
            report.errors.append(f"catalog collection missing on disk: {prefix}")

    for rel, _role in file_roles.items():
        if not (root / rel).is_file():
            report.errors.append(f"catalog path missing on disk: {rel}")

    all_md = iter_first_party_md(root)
    report.inventory = [_posix(p, root) for p in all_md]
    product = [rel for rel in report.inventory if is_product_doc(rel)]

    assigned: dict[str, str] = {}
    for rel in product:
        if rel in file_roles:
            assigned[rel] = file_roles[rel]
            continue
        collection_hits = [
            (role, prefix) for role, prefix in collections if rel.startswith(prefix)
        ]
        if len(collection_hits) == 1:
            assigned[rel] = collection_hits[0][0]
            continue
        if len(collection_hits) > 1:
            report.errors.append(f"{rel} matches multiple collections")
            continue
        report.errors.append(f"not in catalog: {rel}")

    for rel, role in file_roles.items():
        if rel not in assigned and is_product_doc(rel) and (root / rel).is_file():
            report.errors.append(f"catalog file not in inventory: {rel}")

    report.keep = len(assigned)
    report.role_counts = dict(sorted(Counter(assigned.values()).items()))

    for link in extract_md_links(index_text):
        resolved = (index_path.parent / link).resolve()
        if not resolved.exists():
            report.errors.append(f"broken catalog link: {link}")

    for md_path in all_md:
        rel = _posix(md_path, root)
        if not is_product_doc(rel):
            continue
        text = md_path.read_text(encoding="utf-8")
        for needle in FORBIDDEN_SUBSTRINGS:
            if needle in text:
                report.errors.append(f"{rel} still references {needle}")

    return report


def main(argv: list[str] | None = None) -> int:
    del argv
    report = check_catalog(ROOT)
    sys.stdout.write(report.summary())
    if report.errors:
        sys.stderr.write("\n".join(report.errors) + "\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
