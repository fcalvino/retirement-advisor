"""CACHE-RACE: la caché aguanta hilos que tocan la misma clave a la vez.

El optimizador baja precios en un ``ThreadPoolExecutor`` y cada ticker en EUR pide el
mismo par ``history:EURUSD=X:…``. ``set`` hacía ``get`` y después ``INSERT``: dos hilos
que veían la clave ausente insertaban los dos y el segundo chocaba con ``UNIQUE``. Eso
le llegaba a ``get_fx_history`` como «no se pudo bajar». ``get`` borraba la fila vencida
con el ORM, y dos hilos que la borraban a la vez daban un ``SAWarning`` de 0 filas.
"""

import threading
import warnings
from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from data.cache import Base, CacheEntry, DataCache
from data.clock import utc_now

THREADS = 16
ROUNDS = 20


def _cache_at(tmp_path) -> DataCache:
    cache = DataCache(ttl_hours=1)
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.db'}", poolclass=NullPool)
    Base.metadata.create_all(engine)
    cache._Session = sessionmaker(bind=engine)
    return cache


def _hammer(fn) -> list[BaseException]:
    errors: list[BaseException] = []
    barrier = threading.Barrier(THREADS)

    def run(i):
        barrier.wait()
        try:
            fn(i)
        except BaseException as exc:  # noqa: BLE001 — el test junta todo
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_concurrent_set_same_key_never_raises(tmp_path):
    cache = _cache_at(tmp_path)
    for r in range(ROUNDS):
        key = f"history:EURUSD=X:{r}"
        errors = _hammer(lambda i: cache.set(key, {"writer": i}))
        assert errors == [], errors
        assert cache.get(key)["writer"] in range(THREADS)


def test_concurrent_get_of_expired_key_does_not_warn(tmp_path):
    cache = _cache_at(tmp_path)
    for r in range(ROUNDS):
        key = f"history:EURUSD=X:{r}"
        with cache._Session() as session:
            session.add(CacheEntry(key=key, data="[]", cached_at=utc_now() - timedelta(hours=2)))
            session.commit()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            errors = _hammer(lambda i: cache.get(key))
        assert errors == [], errors
        assert [w for w in caught if "expected to delete" in str(w.message)] == []
        assert cache.get(key) is None
