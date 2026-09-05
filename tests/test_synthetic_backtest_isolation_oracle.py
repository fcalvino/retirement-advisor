"""
Oráculo — el store de backtesting sintético nunca resuelve a la base del
usuario (mismo patrón que N6, ``tests/test_track_record_isolation_oracle.py``).

``analysis/synthetic_backtest.py`` (Idea 2, PR 3/N) fue diseñado como tabla y
clase **separadas** de ``analysis.track_record`` precisamente para que una
corrida de backtesting nunca pueda contaminar el hit rate publicado — pero
``SyntheticBacktestStore`` sigue siendo un singleton de módulo apuntado a
``config.DB_PATH``, la misma forma que hizo N6 posible. Este archivo fija la
propiedad estructural equivalente para la clase nueva: bajo pytest, ningún
módulo puede resolver un ``SyntheticBacktestStore`` que apunte a la base real.

Independiente de ``test_track_record_isolation_oracle.py`` a propósito — ese
archivo barre por instancias de ``TrackRecordStore``, no de
``SyntheticBacktestStore``, así que uno pasando no dice nada sobre el otro; el
comentario de ``_StubAlertStore`` en aquel archivo ya advierte contra acoplar
oráculos entre sí.
"""

from __future__ import annotations

import importlib
import sys

from analysis.synthetic_backtest import SyntheticBacktestStore
from config import DB_PATH

#: La base del usuario. Ningún store alcanzable bajo pytest puede resolver acá.
PRODUCTION_DB = str(DB_PATH)

#: Módulos de primera mano que sostienen (o podrían sostener) una referencia
#: al store nuevo, hoy y en la iteración que lo conecte a una corrida real.
_STORE_HOLDERS = ("analysis.synthetic_backtest",)


def _db_of(store: SyntheticBacktestStore) -> str:
    return str(store._engine.url.database or "")


def test_the_module_default_is_not_the_users_database():
    """Un ``SyntheticBacktestStore()`` sin argumentos no puede caer en
    ``DB_PATH`` — cubre al caller futuro que construya un store nuevo, no solo
    al que importe el singleton.
    """
    import analysis.synthetic_backtest as synthetic_backtest

    assert str(synthetic_backtest.DB_PATH) != PRODUCTION_DB
    assert _db_of(SyntheticBacktestStore()) != PRODUCTION_DB


def test_a_late_importer_gets_an_isolated_store():
    from analysis.synthetic_backtest import synthetic_backtest_store

    assert _db_of(synthetic_backtest_store) != PRODUCTION_DB


def test_no_imported_module_holds_a_store_on_the_users_database():
    """Barrido: ningún módulo importado expone un store apuntado a
    ``DB_PATH``. Barre ``sys.modules`` entero, no una lista blanca — el mismo
    argumento que ``test_track_record_isolation_oracle.py`` ya hace para su
    propia clase: un caller nuevo que se ligue el singleton en tiempo de
    import queda cubierto sin tocar este archivo.
    """
    for name in _STORE_HOLDERS:
        importlib.import_module(name)

    offenders = []
    for module_name, module in list(sys.modules.items()):
        if module is None:
            continue
        try:
            attrs = list(vars(module).items())
        except TypeError:
            continue
        for attr, value in attrs:
            if isinstance(value, SyntheticBacktestStore) and _db_of(value) == PRODUCTION_DB:
                offenders.append(f"{module_name}.{attr}")

    assert not offenders, f"stores sintéticos apuntados a la base del usuario: {offenders}"
