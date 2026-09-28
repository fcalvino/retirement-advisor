"""Oráculo de TR-DEDUP-SOURCE: «una por día» es una por día **y por fuente**.

El defecto (QA de LLM-2, 2026-09-25): la clave del dedup era
``(símbolo, acción, día local)``, sin ``source``. El dictamen del comité de INTU
HOLD del 2026-09-22 (19:58 UTC, ``complete=True``) no dejó fila porque el Screener
había registrado INTU HOLD a las 19:55 (id 1364). Con esa clave, las filas
``committee`` sólo existen cuando el comité *disiente* del Screener del día, y
``hit_rate_by_source`` compara una muestra sesgada. Medido el 2026-09-26: 1 de 28
dictámenes completos sin fila.

Son dos preguntas distintas, y cada una tiene su clave:

1. **¿Esta fuente ya lo dijo hoy?** — la escritura, el pendiente de puntuación y
   la lectura por fuente. La clave lleva ``source``: el comité coincidiendo con el
   Screener es una medición del comité, no una repetición.
2. **¿Es el mismo movimiento de mercado?** — ``summary_stats``, ``equity_curve``,
   ``calibration_by_confidence`` y ``hit_rate_by_action``. La clave **no** lleva
   ``source``: contar dos veces AAPL BUY del mismo día es el doble conteo que
   U5-18b sacó, y ``equity_curve`` compone.

El oráculo es independiente del código: cuenta a mano cuántas filas tiene que
haber en cada lectura para un escenario de dos fuentes.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from analysis.track_record import TrackRecordStore, collapse_same_local_day
from analysis.track_record_scorer import (
    calibration_by_confidence,
    equity_curve,
    hit_rate_by_action,
    hit_rate_by_source,
    summary_stats,
)
from data.clock import local_day_start_utc

#: Las cuatro zonas de `test_clock_oracle.py` (UTC es la del CI; Kolkata, el
#: offset de media hora).
ZONAS = [
    "America/Argentina/Buenos_Aires",
    "Asia/Tokyo",
    "UTC",
    "Asia/Kolkata",
]

HORIZONTE = 30


@pytest.fixture
def zona():
    previa = os.environ.get("TZ")

    def _set(nombre: str):
        os.environ["TZ"] = nombre
        time.tzset()

    yield _set
    if previa is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previa
    time.tzset()


@pytest.fixture
def store():
    return TrackRecordStore(db_path=":memory:")


def _decision(symbol="AAPL", action="BUY"):
    return SimpleNamespace(
        symbol=symbol, action=action, confidence="HIGH", fundamental_score=72.0,
        technical_signal="", rationale=[],
    )


def _log_at(store, instante, monkeypatch, *, source, symbol="AAPL", action="BUY"):
    """Escribe con el reloj del módulo en ``instante`` — el mismo que usa el dedup."""
    import analysis.track_record as tr

    monkeypatch.setattr(tr, "utc_now", lambda: instante)
    return store.log_recommendation(_decision(symbol, action), source=source)


def _mismo_dia_local(hora_1: float, hora_2: float) -> tuple[datetime, datetime]:
    medianoche = local_day_start_utc(datetime(2026, 9, 22, 12, 0, 0))
    return medianoche + timedelta(hours=hora_1), medianoche + timedelta(hours=hora_2)


def _puntuar_todo(store, *, hit=True):
    despues = datetime(2026, 11, 30, 12, 0, 0)
    for rec in store.get_pending_scoring(HORIZONTE, now=despues):
        store.save_outcome(
            rec_id=rec.id, horizon_days=HORIZONTE, price_at_horizon=110.0,
            return_pct=10.0, benchmark_return_pct=2.0, excess_return_pct=8.0, hit=hit,
        )


def _screener_y_comite_el_mismo_dia(store, monkeypatch):
    """El caso INTU: el Screener registra primero, el comité coincide después."""
    t_screener, t_comite = _mismo_dia_local(15.9, 16.0)
    ids = [
        _log_at(store, t_screener, monkeypatch, source="screener"),
        _log_at(store, t_comite, monkeypatch, source="committee"),
    ]
    monkeypatch.undo()
    return ids


# --------------------------------------------------------------------------- #
#  1. La escritura: una por día y por fuente                                   #
# --------------------------------------------------------------------------- #

class TestEscritura:

    @pytest.mark.parametrize("tz", ZONAS)
    def test_el_comite_que_coincide_con_el_screener_deja_su_fila(
        self, store, zona, monkeypatch, tz
    ):
        zona(tz)
        ids = _screener_y_comite_el_mismo_dia(store, monkeypatch)
        assert all(ids), f"{tz}: la fila del comité no se escribió (ids={ids})"
        fuentes = sorted(r.source for r in store.get_recommendations())
        assert fuentes == ["committee", "screener"]

    @pytest.mark.parametrize("tz", ZONAS)
    def test_la_misma_fuente_sigue_deduplicada(self, store, zona, monkeypatch, tz):
        zona(tz)
        t1, t2 = _mismo_dia_local(9, 22)
        assert _log_at(store, t1, monkeypatch, source="committee")
        assert _log_at(store, t2, monkeypatch, source="committee") is None
        assert len(store.get_recommendations()) == 1

    def test_la_fuente_se_compara_como_se_guarda(self, store, zona, monkeypatch):
        """La fuente se guarda tal cual la pasa el escritor; la comparación del
        dedup no puede ser más estricta que la de la lectura (que la pasa a
        minúsculas)."""
        zona("UTC")
        t1, t2 = _mismo_dia_local(9, 10)
        assert _log_at(store, t1, monkeypatch, source="committee")
        assert _log_at(store, t2, monkeypatch, source="Committee") is None

    def test_logged_today_pregunta_por_la_fuente(self, store, zona, monkeypatch):
        zona("UTC")
        t1, _ = _mismo_dia_local(9, 10)
        _log_at(store, t1, monkeypatch, source="screener")
        assert store.logged_today("AAPL", "BUY", source="screener") is True
        assert store.logged_today("AAPL", "BUY", source="committee") is False


# --------------------------------------------------------------------------- #
#  2. El pendiente: cada fuente consigue su outcome                            #
# --------------------------------------------------------------------------- #

def test_las_dos_filas_quedan_pendientes_de_puntuar(store, zona, monkeypatch):
    zona("America/Argentina/Buenos_Aires")
    _screener_y_comite_el_mismo_dia(store, monkeypatch)
    pend = store.get_pending_scoring(HORIZONTE, now=datetime(2026, 11, 30))
    assert sorted(r.source for r in pend) == ["committee", "screener"], (
        "la fila del comité quedó sin outcome: el pendiente la colapsa con la del "
        "Screener y nunca se puntúa"
    )


# --------------------------------------------------------------------------- #
#  3. La lectura: por fuente para comparar fuentes, sin fuente para el resto   #
# --------------------------------------------------------------------------- #

class TestLectura:

    @pytest.mark.parametrize("tz", ZONAS)
    def test_hit_rate_by_source_ve_al_comite(self, store, zona, monkeypatch, tz):
        zona(tz)
        _screener_y_comite_el_mismo_dia(store, monkeypatch)
        _puntuar_todo(store)
        por_fuente = hit_rate_by_source(store.get_scored_rows(HORIZONTE, per_source=True))
        assert por_fuente["committee"]["n"] == 1
        assert por_fuente["screener"]["n"] == 1

    @pytest.mark.parametrize("tz", ZONAS)
    def test_las_metricas_agregadas_no_cuentan_dos_veces(self, store, zona, monkeypatch, tz):
        zona(tz)
        _screener_y_comite_el_mismo_dia(store, monkeypatch)
        _puntuar_todo(store)
        rows = store.get_scored_rows(HORIZONTE)
        assert summary_stats(rows)["n"] == 1
        assert len(equity_curve(rows)) == 1
        assert hit_rate_by_action(rows)["BUY"]["n"] == 1
        assert calibration_by_confidence(rows)["HIGH"]["n"] == 1
        # Sobrevive la primera, como en U5-18b: la del Screener.
        assert [r["source"] for r in rows] == ["screener"]

    def test_colapsar_por_fuente_y_despues_entre_fuentes_es_lo_mismo(
        self, store, zona, monkeypatch
    ):
        """La página lee por fuente, filtra, y colapsa entre fuentes para el
        titular: el resultado tiene que ser el de colapsar directo."""
        zona("Asia/Kolkata")
        _screener_y_comite_el_mismo_dia(store, monkeypatch)
        _puntuar_todo(store)
        directo = store.get_scored_rows(HORIZONTE)
        en_dos_pasos = collapse_same_local_day(
            store.get_scored_rows(HORIZONTE, per_source=True)
        )
        assert [r["rec_id"] for r in en_dos_pasos] == [r["rec_id"] for r in directo]


# --------------------------------------------------------------------------- #
#  4. Escritura y lectura por fuente deciden lo mismo, en toda zona            #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tz", ZONAS)
@pytest.mark.parametrize("h1,h2", [(9, 22), (9, 33), (22, 33), (1, 47)])
@pytest.mark.parametrize("fuente_2", ["screener", "committee"])
def test_escritura_y_lectura_por_fuente_no_derivan(
    store, zona, monkeypatch, tz, h1, h2, fuente_2
):
    zona(tz)
    import analysis.track_record as tr

    t1, t2 = _mismo_dia_local(h1, h2)
    rid1 = _log_at(store, t1, monkeypatch, source="screener")
    monkeypatch.setattr(tr, "utc_now", lambda: t2)
    rechaza = store.logged_today("AAPL", "BUY", source=fuente_2)
    monkeypatch.undo()

    filas = [
        {"rec_id": rid1, "symbol": "AAPL", "action": "BUY", "source": "screener",
         "created_at": t1},
        {"rec_id": rid1 + 1, "symbol": "AAPL", "action": "BUY", "source": fuente_2,
         "created_at": t2},
    ]
    colapsa = len(collapse_same_local_day(filas, per_source=True)) == 1
    assert rechaza == colapsa, (
        f"{tz} {h1}h/{h2}h {fuente_2}: la escritura "
        f"{'rechaza' if rechaza else 'acepta'} y la lectura por fuente "
        f"{'colapsa' if colapsa else 'conserva'}"
    )
