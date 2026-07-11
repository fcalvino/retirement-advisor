#!/usr/bin/env python3
"""
Genera bloques de texto listos para pegar en docs/CONTEXT.md.
NO sobreescribe el archivo — imprime a stdout para revisión manual.

Uso: ./venv/bin/python3 scripts/refresh_context.py
"""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def extract_config_classes(config_path: Path) -> list[tuple[str, str]]:
    """Extrae dataclasses e instancias globales de config.py."""
    source = config_path.read_text()
    tree = ast.parse(source)

    dataclasses = []
    assignments = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Buscar clases decoradas con @dataclass
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
                    dataclasses.append(node.name)
                    break
                if isinstance(decorator, ast.Attribute) and decorator.attr == "dataclass":
                    dataclasses.append(node.name)
                    break

        if isinstance(node, ast.Assign):
            # Instancias module-level (ALL_CAPS)
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    assignments.append(target.id)

    return dataclasses, sorted(set(assignments))


def get_git_log(n: int = 10) -> list[str]:
    """Retorna los últimos N commits como líneas."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-{n}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip().splitlines()
    except Exception as e:
        return [f"[error obteniendo git log: {e}]"]


def get_last_roadmap_phase(roadmap_path: Path) -> str:
    """Extrae la última fase completada del ROADMAP.md."""
    try:
        content = roadmap_path.read_text()
        lines = content.splitlines()
        phases = [l for l in lines if l.startswith("### Fase") or l.startswith("## Fase")]
        return phases[-1] if phases else "(no encontrado)"
    except Exception:
        return "(error leyendo ROADMAP.md)"


def print_section(title: str, content: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(content)


def main() -> None:
    config_path = ROOT / "config.py"
    roadmap_path = ROOT / "docs" / "ROADMAP.md"

    if not config_path.exists():
        print(f"ERROR: No se encontró {config_path}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  refresh_context.py — Bloques para docs/CONTEXT.md")
    print("  Revisá y pegá manualmente en las secciones correspondientes")
    print("=" * 60)

    # --- Sección §7: config.py ---
    dataclasses, singletons = extract_config_classes(config_path)

    section7 = "### Dataclasses encontradas en config.py\n\n"
    for cls in dataclasses:
        section7 += f"| `{cls}` | — |\n"

    section7 += "\n### Singletons module-level\n\n```python\n"
    for name in singletons:
        section7 += f"{name}\n"
    section7 += "```"

    print_section("§7 — config.py (pegar en 'Fuente de Verdad')", section7)

    # --- Sección §9: Últimos cambios ---
    commits = get_git_log(10)
    section9 = "| Commit | Cambio |\n|--------|--------|\n"
    for line in commits:
        if " " in line:
            sha, msg = line.split(" ", 1)
            section9 += f"| `{sha}` | {msg} |\n"

    print_section("§9 — Últimos cambios (pegar en 'Últimos Cambios Importantes')", section9)

    # --- Resumen ---
    last_phase = get_last_roadmap_phase(roadmap_path)
    print(f"\n{'='*60}")
    print(f"  Última fase en ROADMAP.md: {last_phase}")
    print("  Fecha de hoy para el encabezado de CONTEXT.md:")
    from datetime import date
    print(f"  > Última actualización: {date.today().isoformat()}")
    print(f"{'='*60}")
    print("\nNOTA: Este script NO modifica docs/CONTEXT.md.")
    print("Revisá el output y pegá lo relevante manualmente.\n")


if __name__ == "__main__":
    main()
