"""Oráculo TEST-PREFS-ISOLATION: la suite no lee ni escribe el perfil del usuario.

``data/preferences.py`` resolvía ``data/user_preferences.json`` junto al código. El
archivo está en ``.gitignore``, así que el CI no lo tiene, y en la máquina del usuario
sí: con su perfil (36 años, retiro a los 60) cinco tests de Simulaciones sembraban un
horizonte de 25 años y fallaban con ``KeyError: 25`` (medido 2026-10-10: 16/16 sin el
archivo, 5 fallas con él), y un test que guardaba un perfil sin patch escribía el
archivo real. ``tests/conftest.py`` fija ``RETIREMENT_ADVISOR_PREFS_PATH`` a un
temporal antes del primer import del proyecto, como hace con la base.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
USER_FILE = REPO / "data" / "user_preferences.json"


def test_the_suite_does_not_resolve_the_users_profile_file():
    from data import preferences

    assert preferences._PREFS_PATH.resolve() != USER_FILE.resolve()
    assert REPO not in preferences._PREFS_PATH.resolve().parents


def test_the_redirect_is_the_variable_conftest_sets():
    from data import preferences

    assert str(preferences._PREFS_PATH) == os.environ["RETIREMENT_ADVISOR_PREFS_PATH"]


def test_saving_a_profile_in_a_test_does_not_touch_the_users_file(tmp_path):
    from data.preferences import UserPreferences

    before = USER_FILE.read_bytes() if USER_FILE.exists() else None
    UserPreferences(default_profile="Agresivo", profile_chosen=True).save()
    after = USER_FILE.read_bytes() if USER_FILE.exists() else None
    assert before == after


def test_child_processes_inherit_the_redirect():
    """``test_direct_page_entry`` corre páginas en subprocesos: heredan el entorno."""
    out = subprocess.run(
        [sys.executable, "-c", "from data import preferences; print(preferences._PREFS_PATH)"],
        cwd=REPO, capture_output=True, text=True, check=True,
        env={**os.environ, "RETIREMENT_ADVISOR_NO_DOTENV": "1"},
    ).stdout.strip()
    assert out == os.environ["RETIREMENT_ADVISOR_PREFS_PATH"]


def test_without_the_variable_the_app_uses_the_file_next_to_the_code():
    env = {k: v for k, v in os.environ.items() if k != "RETIREMENT_ADVISOR_PREFS_PATH"}
    out = subprocess.run(
        [sys.executable, "-c", "from data import preferences; print(preferences._PREFS_PATH)"],
        cwd=REPO, capture_output=True, text=True, check=True, env=env,
    ).stdout.strip()
    assert Path(out).resolve() == USER_FILE.resolve()
