"""Sonda de TEST-ENV-KEY, corrida por ``test_env_isolation_oracle.py`` en un subproceso.

No se llama ``test_*`` a propósito: sólo tiene sentido con el entorno que arma el
oráculo (una clave de proveedor y ``AI_ENABLED`` en el entorno del proceso).
"""

import os

from config import AI_CONFIG, AI_PROVIDER_KEY_ENV


def test_the_suite_sees_no_ai_configuration():
    assert AI_CONFIG.enabled is False
    assert AI_CONFIG.api_key == ""
    assert os.environ.get("AI_ENABLED", "") in ("", "false")
    for env_var in AI_PROVIDER_KEY_ENV.values():
        assert not os.environ.get(env_var), env_var


def test_the_dotenv_is_not_loaded():
    assert os.environ.get("RETIREMENT_ADVISOR_NO_DOTENV") == "1"
