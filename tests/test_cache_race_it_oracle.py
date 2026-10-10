"""CACHE-RACE-IT: hilos que piden el mismo par FX vencido reciben todos su tipo de cambio.

``tests/test_cache_race_oracle.py`` prueba ``DataCache`` suelto. Esto prueba el camino
que rompía la cartera: el optimizador baja precios en un ``ThreadPoolExecutor``, cada
ticker en EUR llama a ``get_fx_history`` y todos encuentran ``history:EURUSD=X:…``
vencida a la vez. Antes de #251, ``set`` leía y después insertaba: uno chocaba con
``UNIQUE``, ``get_fx_history`` lo atrapaba como «no se pudo bajar», devolvía ``None`` y
el ticker salía de la cartera (QA en vivo del 2026-10-10: 44 posiciones en vez de 45).

La barrera vive dentro del stub de ``yf.Ticker(...).history``: todos los hilos ya
pasaron por el ``get`` vencido y salen juntos hacia ``cache.set``. Sin red y sobre una
base temporal.
"""

import threading
from datetime import timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from data import fetcher
from data import fx as fxmod
from data.cache import Base, CacheEntry, DataCache
from data.clock import utc_now

THREADS = 8
ROUNDS = 10
PERIOD, INTERVAL = "2y", "1wk"
KEY = f"history:EURUSD=X:{PERIOD}:{INTERVAL}"
RATES = [1.08, 1.09, 1.10, 1.11]


class _Ticker:
    def __init__(self, barrier: threading.Barrier):
        self._barrier = barrier

    def history(self, **_kw):
        self._barrier.wait(timeout=10)
        idx = pd.date_range("2024-01-01", periods=len(RATES), freq="W-MON", name="Date")
        return pd.DataFrame({"Open": RATES, "High": RATES, "Low": RATES,
                             "Close": RATES, "Volume": [0] * len(RATES)}, index=idx)


@pytest.fixture
def temp_cache(tmp_path, monkeypatch):
    cache = DataCache(ttl_hours=1)
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.db'}", poolclass=NullPool)
    Base.metadata.create_all(engine)
    cache._Session = sessionmaker(bind=engine)
    monkeypatch.setattr(fetcher, "cache", cache)
    return cache


def _expire(cache: DataCache) -> None:
    with cache._Session() as session:
        session.merge(CacheEntry(key=KEY, data="[]", cached_at=utc_now() - timedelta(hours=2)))
        session.commit()


def _round(monkeypatch) -> list:
    barrier = threading.Barrier(THREADS)
    monkeypatch.setattr(fetcher.yf, "Ticker", lambda _sym: _Ticker(barrier))
    results: list = [None] * THREADS

    def run(i):
        results[i] = fxmod.get_fx_history("EUR", period=PERIOD, interval=INTERVAL)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_threads_on_an_expired_fx_pair_all_get_the_rate(temp_cache, monkeypatch):
    warned: list[str] = []
    from loguru import logger
    sink = logger.add(lambda m: warned.append(str(m)), level="WARNING")
    try:
        for _ in range(ROUNDS):
            _expire(temp_cache)
            results = _round(monkeypatch)
            missing = [i for i, r in enumerate(results) if r is None]
            assert missing == [], f"hilos sin tipo de cambio: {missing}"
            for r in results:
                assert list(r.values) == pytest.approx(RATES)
            cached = temp_cache.get(KEY)
            assert cached and [row["close"] for row in cached] == pytest.approx(RATES)
    finally:
        logger.remove(sink)
    assert [m for m in warned if "IntegrityError" in m] == []
