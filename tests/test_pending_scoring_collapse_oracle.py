"""Oracle for U5-18c — el pending puntúa lo que la lectura después descarta.

U5-18b colapsó las repeticiones del mismo día local **al leer**, y U5-18d sacó
las 53 fixtures de los tres sitios. Queda el tercero de los flujos:
``get_pending_scoring`` sigue devolviendo las duplicadas, así que el scorer va a
puntuarlas —una llamada de red por cada una— y a escribir outcomes que
``get_scored_rows`` descarta acto seguido.

## No rompe ningún número, y tiene fecha

Es la diferencia con las otras dos filas de la familia: acá no hay una cifra
falsa. La lectura ya filtra, así que el hit rate y la curva no se mueven. Lo que
se gasta es red y prolijidad — **74 lookups** y 74 filas basura en
``recommendation_outcome``.

Pero llega solo. Medido el 2026-08-31 con `get_pending_scoring(30)`:

    hoy                       0 pendientes
    2026-09-23 en adelante    las duplicadas del 23/08 cumplen 30 días
    2026-09-28                las del 28/08

Hoy no se puede ver el defecto ejecutando el motor: **cero pendientes**. Por eso
el oráculo inyecta el `now`, que la firma ya acepta.

## La restricción: una sola clave

La fila advierte el orden — «colapsar el pending sin colapsar la lectura dejaría
de nuevo dos políticas conviviendo». La lectura ya colapsa (U5-18b), así que la
precondición está. Lo que queda es que **las tres usen literalmente la misma
clave**: ``same_local_day_key`` existe justamente para que escritura y lectura no
puedan derivar, y este sitio tiene que pasar por ella y no por una copia.

Verificado antes de tocar nada: de los 74 pares, **ninguna segunda tiene outcome
todavía**, así que colapsar el pending no deja ningún outcome huérfano.

Sin red, sin Streamlit.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from analysis.track_record import TrackRecordStore, same_local_day_key


def _store():
    return TrackRecordStore(db_path=":memory:")


def _decision(symbol="AAPL", action="BUY"):
    from types import SimpleNamespace

    return SimpleNamespace(
        symbol=symbol, action=action, confidence="HIGH", total_score=72.0,
        adjusted_score=72.0, reasons=[], risks=[], notes={}, warnings=[],
    )


def _log_at(store, instante, monkeypatch, **kw):
    """Escribe una recomendación con el reloj puesto en ``instante``.

    Se inyecta el reloj del módulo, que es el mismo que ``_exists_today`` usa
    para cortar el día — si se inyectara otro, el test estaría probando una
    política distinta de la que corre en producción.
    """
    import analysis.track_record as tr

    monkeypatch.setattr(tr, "utc_now", lambda: instante)
    return store.log_recommendation(_decision(**kw), source="test")


#: Mañana y noche del MISMO día local en UTC−3, a los dos lados del corte UTC.
#: Es el par real que motivó U5-18b: AAPL BUY del 2026-08-23, 09:32 y 21:12.
MANANA = datetime(2026, 8, 23, 12, 32)
NOCHE = datetime(2026, 8, 24, 0, 12)
#: Bien pasado el horizonte de 30 días, para que las dos estén vencidas.
DESPUES = datetime(2026, 10, 15, 12, 0)


@pytest.fixture
def zona_ar(monkeypatch):
    """Zona fijada: un test que hereda la del entorno pasa en una máquina y
    falla en CI (la lección de U5-18)."""
    import os
    import time

    previa = os.environ.get("TZ")
    os.environ["TZ"] = "America/Argentina/Buenos_Aires"
    time.tzset()
    yield
    if previa is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previa
    time.tzset()


# --------------------------------------------------------------------------- #
#  El defecto                                                                  #
# --------------------------------------------------------------------------- #


class TestElPendingNoDevuelveLoQueLaLecturaDescarta:

    def test_dos_filas_del_mismo_dia_local_dejan_una_sola_pendiente(
        self, zona_ar, monkeypatch
    ):
        """El defecto, aislado. Las dos filas existen en el log —U5-18b no borra
        nada— pero sólo una merece un lookup de red y un outcome."""
        store = _store()
        # Se escriben con el reloj de la regla VIEJA para reproducir el par que
        # quedó en la base: hoy `_exists_today` rechazaría la segunda.
        import analysis.track_record as tr

        for instante in (MANANA, NOCHE):
            monkeypatch.setattr(tr, "utc_now", lambda i=instante: i)
            monkeypatch.setattr(tr, "local_day_start_utc", lambda dt: dt.date())
            store.log_recommendation(_decision(), source="test")
        monkeypatch.undo()

        pend = store.get_pending_scoring(30, now=DESPUES)
        assert len(pend) == 1, (
            f"quedaron {len(pend)} pendientes para la misma recomendación del "
            f"mismo día local — cada una gasta un lookup y escribe un outcome "
            f"que get_scored_rows después descarta"
        )

    def test_sobrevive_la_primera_igual_que_en_la_lectura(self, zona_ar, monkeypatch):
        """Si el pending eligiera la última y la lectura la primera, el motor
        puntuaría una fila y mostraría otra."""
        store = _store()
        import analysis.track_record as tr

        ids = []
        for instante in (MANANA, NOCHE):
            monkeypatch.setattr(tr, "utc_now", lambda i=instante: i)
            monkeypatch.setattr(tr, "local_day_start_utc", lambda dt: dt.date())
            ids.append(store.log_recommendation(_decision(), source="test"))
        monkeypatch.undo()

        (pendiente,) = store.get_pending_scoring(30, now=DESPUES)
        assert pendiente.id == ids[0], (
            "el pending eligió la segunda; la lectura elige la primera, así que "
            "el motor puntuaría una fila y mostraría otra"
        )

    def test_dos_dias_locales_distintos_siguen_pendientes_los_dos(
        self, zona_ar, monkeypatch
    ):
        """Anti-cheat: colapsar no puede ser dejar de puntuar."""
        store = _store()
        _log_at(store, datetime(2026, 8, 23, 12, 32), monkeypatch)
        _log_at(store, datetime(2026, 8, 24, 12, 32), monkeypatch)
        monkeypatch.undo()

        assert len(store.get_pending_scoring(30, now=DESPUES)) == 2

    def test_dos_acciones_distintas_del_mismo_dia_siguen_siendo_dos(
        self, zona_ar, monkeypatch
    ):
        """Un BUY y un HOLD del mismo ticker el mismo día son dos
        recomendaciones distintas, no una repetida."""
        store = _store()
        _log_at(store, MANANA, monkeypatch, action="BUY")
        _log_at(store, MANANA, monkeypatch, action="HOLD")
        monkeypatch.undo()

        assert len(store.get_pending_scoring(30, now=DESPUES)) == 2


# --------------------------------------------------------------------------- #
#  Una sola clave para los tres sitios                                         #
# --------------------------------------------------------------------------- #


class TestLaClaveEsLaMismaQueEscrituraYLectura:

    def test_el_pending_pasa_por_la_clave_compartida(self):
        """``same_local_day_key`` existe para que escritura y lectura no puedan
        derivar. Si este sitio hiciera su propia tupla, el día que alguien mueva
        la definición quedarían dos políticas otra vez — que es el defecto que
        U5-18 tardó dos PRs en cerrar."""
        from pathlib import Path

        src = Path("analysis/track_record.py").read_text(encoding="utf-8")
        cuerpo = src[src.index("def get_pending_scoring"):]
        cuerpo = cuerpo[: cuerpo.index("def save_outcome")]
        assert "same_local_day_key" in cuerpo, (
            "get_pending_scoring no usa la clave compartida"
        )

    def test_la_clave_no_distingue_por_hora_dentro_del_dia_local(self, zona_ar):
        assert same_local_day_key("AAPL", "BUY", MANANA) == same_local_day_key(
            "AAPL", "BUY", NOCHE
        )


# --------------------------------------------------------------------------- #
#  La puerta de auditoría, y lo que no puede romperse                          #
# --------------------------------------------------------------------------- #


class TestLoQueNoPuedeRomperse:

    def test_el_flag_apagado_devuelve_el_crudo(self, zona_ar, monkeypatch):
        """Misma forma que ``get_scored_rows(collapse_same_day=False)``: la
        puerta para auditar lo que el motor efectivamente escribió."""
        store = _store()
        import analysis.track_record as tr

        for instante in (MANANA, NOCHE):
            monkeypatch.setattr(tr, "utc_now", lambda i=instante: i)
            monkeypatch.setattr(tr, "local_day_start_utc", lambda dt: dt.date())
            store.log_recommendation(_decision(), source="test")
        monkeypatch.undo()

        assert len(store.get_pending_scoring(30, now=DESPUES, collapse_same_day=False)) == 2

    def test_una_fila_ya_puntuada_sigue_sin_aparecer(self, zona_ar, monkeypatch):
        """El filtro de outcomes existentes no se toca."""
        store = _store()
        rec = _log_at(store, MANANA, monkeypatch)
        monkeypatch.undo()
        store.save_outcome(
            rec_id=rec, horizon_days=30, price_at_horizon=110.0, return_pct=10.0,
            benchmark_return_pct=5.0, excess_return_pct=5.0, hit=True,
        )
        assert store.get_pending_scoring(30, now=DESPUES) == []

    def test_ninguna_fila_sin_fecha_llega_al_colapso(self, zona_ar):
        """Por qué el colapso no necesita una guarda para filas sin fecha.

        La primera versión traía un `if created_at is None` y la mutación que lo
        borraba **sobrevivía**: era inalcanzable. Dos razones independientes lo
        garantizan, y este test fija las dos —si alguna cae, la guarda hace falta
        y el test avisa antes que un usuario.
        """
        import datetime

        from analysis.track_record import RecommendationLog

        store = _store()
        with store._Session() as s:
            s.add(RecommendationLog(symbol="AAPL", action="BUY", confidence="HIGH",
                                    source="test", created_at=None))
            s.commit()
            # (1) la columna tiene default, así que el None ni siquiera se guarda
            assert s.query(RecommendationLog).filter(
                RecommendationLog.created_at.is_(None)
            ).count() == 0, "un created_at NULL llegó a la base"

        # (2) y aun si llegara, el filtro por cutoff lo descarta: en SQL
        #     `NULL <= x` es NULL, que en un WHERE es falso.
        assert all(
            r.created_at is not None
            for r in store.get_pending_scoring(30, now=DESPUES, collapse_same_day=False)
        )

    def test_una_fila_sin_vencer_no_aparece(self, zona_ar, monkeypatch):
        store = _store()
        _log_at(store, MANANA, monkeypatch)
        monkeypatch.undo()
        assert store.get_pending_scoring(30, now=MANANA + timedelta(days=5)) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
