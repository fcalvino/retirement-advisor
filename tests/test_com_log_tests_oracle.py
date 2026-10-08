"""Oráculo COM-LOG-TESTS: la suite no escribe en el log de las corridas reales.

``dashboard/app.py`` agrega el sumidero ``logs/retirement_advisor.log`` cuando un ``AppTest``
corre la app, y loguru lo mantiene hasta el final de la sesión de pytest: desde ahí, todo lo
que loguea cualquier test posterior —los ``committee[...]`` de la suite, por ejemplo— terminaba
en el archivo de las corridas reales. **Medido el 2026-10-08** en el log del clon: de las 131
líneas ``committee[...]``, 126 eran de la suite (MSFT 70, ACME 7, AIR.PA 7, BTC-USD 7,
``portfolio:t/h/15ee…`` 35), todas del 2026-10-03; sólo 5 eran de una corrida real. Y
reproducido: ``test_committee.py`` solo no escribe nada; con un ``AppTest`` antes, 18 líneas.

COM-QUORUM-MEDICION cuenta las 200 corridas sobre ese log, así que no podía fiarse de él.

El arreglo es el de TEST-CACHE: ``RETIREMENT_ADVISOR_LOG_PATH`` (como ``..._DB_PATH``), fijado
en ``tests/conftest.py`` antes de cualquier import del proyecto; sin la variable, la app
escribe donde siempre. Los hijos heredan el entorno. Sin red.
"""

from __future__ import annotations

import ast
import os
import re
import uuid
from pathlib import Path

import pytest
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
REAL_LOG = ROOT / "logs" / "retirement_advisor.log"
APP = str(ROOT / "dashboard" / "app.py")


def _is_inside(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def test_the_suite_points_the_log_away_from_the_repo():
    target = Path(os.environ["RETIREMENT_ADVISOR_LOG_PATH"])
    assert target.name == "retirement_advisor.log"
    assert not _is_inside(target, ROOT), f"el log de la suite está dentro del repo: {target}"


def test_conftest_sets_the_variable_before_the_first_project_import():
    """Si alguien sube un import del proyecto por encima, el desvío llega tarde."""
    src = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    set_line = next(
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and "RETIREMENT_ADVISOR_LOG_PATH" in ast.unparse(n.targets[0])
    )
    project = {"config", "alerts", "analysis", "data", "dashboard", "portfolio", "scripts"}
    def root_module(n) -> str:
        name = n.module if isinstance(n, ast.ImportFrom) else n.names[0].name
        return (name or "").split(".")[0]

    first_import = min(
        n.lineno for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom)) and root_module(n) in project
    )
    assert set_line < first_import


def test_an_apptest_run_does_not_put_later_log_lines_in_the_real_log():
    """La corrida real del bug: un AppTest agrega el sumidero y un log posterior lo cruza."""
    from streamlit.testing.v1 import AppTest

    from data.preferences import UserPreferences

    before = REAL_LOG.stat().st_size if REAL_LOG.exists() else None
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["user_prefs"] = UserPreferences()
    at.run()
    assert not at.exception, [e.message for e in at.exception]

    probe = f"COM-LOG-TESTS probe {uuid.uuid4().hex}"
    logger.info(probe)
    logger.complete()

    target = Path(os.environ["RETIREMENT_ADVISOR_LOG_PATH"])
    assert probe in target.read_text(encoding="utf-8"), "la app no usó el sumidero desviado"
    after = REAL_LOG.stat().st_size if REAL_LOG.exists() else None
    assert after == before, "la suite escribió en logs/retirement_advisor.log del repo"
    if REAL_LOG.exists():
        assert probe not in REAL_LOG.read_text(encoding="utf-8", errors="replace")


def test_without_the_variable_the_app_still_logs_where_it_always_did():
    """Fuera de la suite nada cambia: el respaldo es ``logs/retirement_advisor.log`` del repo."""
    src = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    assert re.search(r'os\.environ\.get\("RETIREMENT_ADVISOR_LOG_PATH"\)', src)
    assert re.search(r'/ "logs" / "retirement_advisor\.log"', src)


def test_only_the_app_adds_a_file_sink_to_the_log_directory():
    """Un segundo sumidero a ``logs/`` reabriría el defecto por otra puerta."""
    offenders = []
    for folder in ("analysis", "dashboard", "data", "alerts", "portfolio", "reports", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "add" and ast.unparse(n.func.value) == "logger"
                        and n.args and "stderr" not in ast.unparse(n.args[0])):
                    offenders.append(f"{path.relative_to(ROOT)}:{n.lineno}")
    assert [o.split(":")[0] for o in offenders] == ["dashboard/app.py"], offenders


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
