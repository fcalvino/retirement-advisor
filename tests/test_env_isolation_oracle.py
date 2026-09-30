"""Oráculo TEST-ENV-KEY: la suite corre con la configuración de IA del CI, no con la del usuario.

Con el ``.env`` real (una clave de proveedor y ``AI_ENABLED=true``), 13 tests de
``tests/test_alert_engine.py`` pedían la explicación de la alerta a la IA
(``alerts/engine.py``, ``_get_ai_explanation``) y el guard de red los cortaba: 30
passed / 13 errors en el clon, verde en el CI, que no tiene ``.env``. Así ``make
check`` local dejaba de ser evidencia. Es la familia de TEST-NET y TEST-CACHE: el
conftest aislaba la base y la red, pero no la configuración.

El conftest, antes del primer import del proyecto, pide a ``config`` que no cargue
el ``.env`` (``RETIREMENT_ADVISOR_NO_DOTENV``) y saca del entorno la llave y el
encendido de la IA por si vienen exportados de la shell. Los subprocesos heredan el
entorno, así que las páginas que ``test_direct_page_entry`` corre aparte quedan
cubiertas igual.

El oráculo corre pytest en un subproceso cuyo entorno trae una clave falsa, porque
dentro de este proceso el conftest ya corrió y no hay nada que medir.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE_KEY = "gsk_fake_key_for_the_oracle"


def _run_probe(**env_overrides: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/_env_probe.py", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )


def test_a_provider_key_in_the_environment_does_not_reach_the_suite():
    result = _run_probe(AI_ENABLED="true", AI_PROVIDER="groq", GROQ_API_KEY=FAKE_KEY,
                        AI_API_KEY=FAKE_KEY, RETIREMENT_ADVISOR_NO_DOTENV="")
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def test_every_provider_key_is_cleared_by_the_conftest():
    """El conftest no puede importar ``config`` antes de limpiar: la lista es propia."""
    from config import AI_PROVIDER_KEY_ENV
    from tests.conftest import AI_ENV_CLEARED

    assert set(AI_PROVIDER_KEY_ENV.values()) <= set(AI_ENV_CLEARED)
    assert {"AI_ENABLED", "AI_API_KEY"} <= set(AI_ENV_CLEARED)


def test_config_does_not_load_the_dotenv_when_asked(tmp_path):
    """El interruptor es de ``config``: sin él, el ``.env`` gana sobre un entorno sin clave."""
    code = (
        "import os, dotenv\n"
        "calls = []\n"
        "dotenv.load_dotenv = lambda *a, **k: calls.append(1)\n"
        "import config\n"
        "print(len(calls))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "RETIREMENT_ADVISOR_NO_DOTENV"}
    env["RETIREMENT_ADVISOR_DB_PATH"] = str(tmp_path / "ra.db")
    skipped = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                             text=True, env=dict(env, RETIREMENT_ADVISOR_NO_DOTENV="1"))
    loaded = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                            text=True, env=env)
    assert skipped.stdout.strip().splitlines()[-1] == "0", skipped.stderr[-1500:]
    assert loaded.stdout.strip().splitlines()[-1] == "1", loaded.stderr[-1500:]


def test_the_dashboard_neither_reads_nor_writes_the_dotenv_under_the_switch(tmp_path, monkeypatch):
    """``app.py`` siembra la IA de la sesión con ``_load_env_vars``, que lee el archivo
    sin pasar por ``load_dotenv``; ``_save_ai_config_to_env`` lo reescribe entero a
    partir de esa lectura. Bajo el interruptor, una lectura vacía seguida de un
    guardado dejaría el ``.env`` del usuario sólo con las claves de IA."""
    from dashboard import shared

    dotenv = tmp_path / ".env"
    original = "AI_ENABLED=true\nGROQ_API_KEY=real\nTELEGRAM_BOT_TOKEN=t\n"
    dotenv.write_text(original)
    monkeypatch.setattr(shared, "_ENV_PATH", dotenv)

    assert shared._load_env_vars() == {}
    shared._save_ai_config_to_env("claude", "m", "k", True)
    assert dotenv.read_text() == original

    monkeypatch.delenv("RETIREMENT_ADVISOR_NO_DOTENV")
    assert shared._load_env_vars()["GROQ_API_KEY"] == "real"   # control: sin el interruptor, lee
