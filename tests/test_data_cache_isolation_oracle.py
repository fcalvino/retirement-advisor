"""Oráculo — la suite de tests no toca la base del usuario (TEST-CACHE).

N6 aisló el track record, las alertas y el backtest sintético, pero la caché de
datos (`data.cache`, tabla `cache`) vive en la misma base y seguía apuntando a
`config.DB_PATH`. `DataCache.get` **borra** la fila que encuentra vencida y el
fetcher la vuelve a bajar de la red, así que un test que llegaba a
`data.fetcher` con un símbolo real reescribía la caché del usuario.

**Medido el 2026-09-24 sobre una copia fresca de la base (730 filas, 22–23/09):**

    make test en main       4 filas borradas   (info/financials de AZN.L y SHEL.L)
                            7 reescritas       (BND, JNJ, KO, PG, SPY, SCHD, ARS=X)
                          113 tests abren el archivo de la base
                            4 subprocesos de páginas lo abren también
                            5 lecturas del portfolio.json real

Esas escrituras contaminaron el harness de la serie UM: el «cambio» de señal de
BND en #160 era la copia de la base refrescada entre baseline y compare.

Se evaluaron tres formas de cerrarlo sobre la misma copia:

    redirigir el singleton al importar (estilo N6)   0/0 filas, pero 4 subprocesos
                                                      siguen abriendo la base
    fixture autouse por test                          0/0 filas, 32 s → 78 s,
                                                      8 → 28 tests con red, y los
                                                      mismos 4 subprocesos
    RETIREMENT_ADVISOR_DB_PATH antes de importar      0/0 filas, 0 aperturas en
                                                      tests, colección y subprocesos

La tercera es la única que alcanza a los procesos hijos (heredan el entorno) y,
de paso, a todo lo que cuelga de `DB_PATH.parent`: el `portfolio.json` y los
backtests guardados. `tests/conftest.py` fija la variable antes del primer
import del proyecto; este archivo falla si eso se rompe — por ejemplo, si alguien
sube un `import config` por encima.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import config

# La ruta por defecto, recalculada desde la definición y no leída de config:
# config.DB_PATH es justamente lo que se está probando.
USER_DB_DIR = config.BASE_DIR / "data" / "db"
USER_DB = USER_DB_DIR / "retirement_advisor.db"


def _is_inside(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


class TestLaBaseDeLaSuiteEsTemporal:
    def test_config_no_apunta_a_la_base_del_usuario(self):
        assert config.DB_PATH != USER_DB
        assert not _is_inside(config.DB_PATH, USER_DB_DIR)

    def test_viene_de_la_variable_y_vive_en_un_temporal(self):
        assert config.DB_PATH == Path(os.environ["RETIREMENT_ADVISOR_DB_PATH"])
        assert _is_inside(config.DB_PATH, Path(tempfile.gettempdir()))


class TestCadaCacheDeDatosLaUsa:
    """El singleton se enlaza por nombre en dos módulos al importarse, y tres
    analizadores (moat, tailwind, cripto) construyen su propio `DataCache`."""

    @pytest.mark.parametrize("owner", ["data.cache", "data.fetcher", "data.data_sources"])
    def test_el_singleton_y_sus_copias(self, owner):
        module = __import__(owner, fromlist=["cache"])
        assert module.cache._Session.kw["bind"].url.database == str(config.DB_PATH)

    def test_una_cache_nueva(self):
        from data.cache import DataCache

        assert DataCache()._Session.kw["bind"].url.database == str(config.DB_PATH)


class TestLoQueCuelgaDeLaMismaCarpeta:
    def test_el_portfolio_no_es_el_del_usuario(self):
        from portfolio.tracker import PORTFOLIO_FILE

        assert not _is_inside(PORTFOLIO_FILE, USER_DB_DIR)

    def test_los_backtests_guardados_no_son_los_del_usuario(self):
        from analysis.backtesting import RESULTS_DIR

        assert not _is_inside(RESULTS_DIR, USER_DB_DIR)


def test_un_subproceso_hereda_la_misma_base():
    """`test_direct_page_entry` corre el dashboard en procesos hijos: sin la
    variable, esas páginas leían la caché y el portfolio reales."""
    out = subprocess.run(
        [sys.executable, "-c", "import config; print(config.DB_PATH)"],
        cwd=config.BASE_DIR, capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == str(config.DB_PATH)
