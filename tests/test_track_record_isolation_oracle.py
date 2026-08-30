"""Oráculo — la suite de tests no escribe en el track record del usuario (N6).

`AlertEngine._log_opportunity` (`alerts/engine.py:512`) importa el **singleton de
módulo** `track_record_store`, que apunta a `config.DB_PATH`. El fixture `store`
de `tests/test_alert_engine.py` reemplaza el store de *alertas*, no el del track
record, así que todo test que dispare una alerta de oportunidad escribe una
recomendación real en la base del usuario.

**Medido el 2026-08-30 sobre `data/db/retirement_advisor.db`, en modo read-only:**

    470 filas en recommendation_log
     53 (11,3 %) con el rationale "Alerta de oportunidad: entró con señal …",
        todas source=rule_based y todas con price_at_rec NULL

    18 lotes en 16 días LOCALES distintos, del 2026-06-19 al 2026-08-30.
    Siempre los mismos tres símbolos: AAPL/BUY, MSFT/BUY, XOM/STRONG BUY.
    Un lote por día porque el dedup de U5-18 colapsa el resto: el 23 y el 28 de
    agosto la suite corrió dos veces cruzando las 21:00 local y quedaron 6 —de
    ahí salen 6 de los 80 duplicados de U5-18b. El lote del 19 de junio tiene 2
    (el test de MSFT todavía no existía).

**No es contaminación futura: ya está puntuada.** De los 22 outcomes scoreados
(los `rec_id` 1–22, únicos con más de 30 días), **11 son estas filas**:

                     n    hit rate   exceso medio
    publicado       22      68,2 %        +6,29
    escritas acá    11      90,9 %        +9,36
    reales          11      45,5 %        +3,21

El producto publica 68,2 % de acierto; sobre recomendaciones que el motor
realmente emitió va 45,5 %. Inflado **+22,7 pp a favor del motor**, sobre el
único juez que el motor tiene sobre sí mismo. Y las otras 42 todavía no
cumplieron 30 días: sin cortar la sangría, el sesgo crece solo.

**Qué escribe exactamente.** Instrumentando `log_recommendation` (bloqueada, sin
tocar la base) sobre `tests/test_alert_engine.py`: **cuatro** intentos, no tres
como decía la fila —

    TestSignalChange::test_signal_upgrade_fires_alert          AAPL BUY
    TestScoreSurge::test_surge_with_buy_signal_fires           MSFT BUY
    TestOpportunity::test_new_buy_entry_fires_opportunity      XOM STRONG BUY
    TestOpportunity::test_opportunity_strong_buy_with_space    XOM STRONG BUY

El cuarto lo colapsa el dedup del día, por eso aterrizan 3 filas y no 4. Y el
primero no es un test de oportunidad: es el de cambio de señal, que al cruzar a
BUY dispara el path igual. Reproducido contra una **copia** de la base el
2026-08-30: 467 → 470 corriendo sólo ese archivo.

**Por qué estos tests no cuentan filas.** Contar `recommendation_log` antes y
después no sirve dentro de la misma suite: el import ya pasó, el dedup de U5-18
esconde todo lote posterior al primero del día, y una escritura real dejaría el
daño hecho aunque el test la detecte. Lo que se fija acá es la **propiedad
estructural** que hace imposible la escritura: bajo pytest, ningún módulo puede
resolver un `TrackRecordStore` que apunte a `DB_PATH`. El de arriba lo verifica
en el camino de producción entero (`AlertEngine.run` → `_log_opportunity` →
import del singleton), observando a qué base habría escrito **sin escribirla**.

Sin red. Sin tocar la base del usuario.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

from alerts.store import AlertSeverity, AlertType
from analysis.track_record import TrackRecordStore
from config import DB_PATH

#: La base del usuario. Ningún store alcanzable bajo pytest puede resolver acá.
PRODUCTION_DB = str(DB_PATH)

#: Módulos de primera mano que sostienen una referencia al store. Los tres
#: primeros la toman del singleton de módulo; `dashboard.shared` la importa
#: adentro de la función, que es la misma forma que usa `alerts/engine.py`.
_STORE_HOLDERS = (
    "analysis.track_record",
    "analysis.track_record_scorer",
    "alerts.engine",
    "dashboard.shared",
)


def _db_of(store: TrackRecordStore) -> str:
    """Ruta del archivo SQLite detrás de un store (``:memory:`` si es de test)."""
    return str(store._engine.url.database or "")


class _StubAlertStore:
    """Store de alertas mínimo: deja pasar todo y no persiste nada.

    No es el `FakeAlertStore` de `test_alert_engine.py` a propósito — este
    oráculo tiene que seguir fallando aunque aquel fixture cambie.
    """

    def __init__(self, snapshot: SimpleNamespace | None = None) -> None:
        self._snapshot = snapshot

    def get_snapshot(self, symbol: str):
        return self._snapshot

    def save_snapshot(self, symbol: str, score: float, signal: str, moat_class: str) -> None:
        pass

    def is_on_cooldown(self, alert_type: AlertType, symbol: str) -> bool:
        return False

    def set_cooldown(self, alert_type: AlertType, symbol: str) -> None:
        pass

    def is_muted(self, symbol: str, alert_type: str) -> bool:
        return False

    def record(self, *args, **kwargs) -> None:
        pass

    def purge_expired_mutes(self) -> None:
        pass


# ------------------------------------------------------------------ #
#  El defecto: el camino de producción entero                          #
# ------------------------------------------------------------------ #

def test_opportunity_alert_never_resolves_to_the_users_database(monkeypatch):
    """El path real de la alerta de oportunidad no puede llegar a `DB_PATH`.

    `log_recommendation` queda reemplazada por un espía que **no escribe**: sólo
    anota a qué base habría escrito. Así el oráculo puede correr en rojo sin
    agregarle una fila más a la base del usuario.
    """
    seen: list[str] = []

    def spy(self, decision, **kwargs):
        seen.append(_db_of(self))
        return None

    monkeypatch.setattr(TrackRecordStore, "log_recommendation", spy)

    from alerts.engine import AlertEngine

    engine = AlertEngine.__new__(AlertEngine)
    engine._store = _StubAlertStore(
        SimpleNamespace(score=55.0, signal="HOLD", moat_class="Narrow")
    )
    engine._notifier = SimpleNamespace(send=lambda *a, **k: None)
    engine._min_severity = AlertSeverity.INFO

    fired = engine.run([{
        "symbol": "XOM",
        "adjusted_score": 72.0,
        "signal": "STRONG_BUY",
        "moat_classification": "Narrow",
        "company_name": "ExxonMobil",
    }])

    # Guarda contra un verde vacío: si el path dejara de loguear, la propiedad
    # se cumpliría por accidente y este archivo dejaría de vigilar nada.
    assert any(a.alert_type == AlertType.OPPORTUNITY for a in fired)
    assert seen, "el path de oportunidad dejó de escribir en el track record"

    assert PRODUCTION_DB not in seen, (
        f"la suite escribió una recomendación en la base del usuario: {seen}"
    )


# ------------------------------------------------------------------ #
#  La propiedad: nada resuelve a la base del usuario bajo pytest       #
# ------------------------------------------------------------------ #

def test_the_module_default_is_not_the_users_database():
    """Un `TrackRecordStore()` sin argumentos no puede caer en `DB_PATH`.

    Esto es lo que cubre al **caller futuro**: el que construya un store nuevo,
    no el que importe el singleton. El orden de los asserts importa — el primero
    falla antes de que el segundo llegue a abrir la base del usuario.
    """
    import analysis.track_record as track_record

    assert str(track_record.DB_PATH) != PRODUCTION_DB
    assert _db_of(TrackRecordStore()) != PRODUCTION_DB


def test_a_late_importer_gets_an_isolated_store():
    """La forma exacta de `alerts/engine.py:512`: import tardío del singleton."""
    from analysis.track_record import track_record_store

    assert _db_of(track_record_store) != PRODUCTION_DB


def test_no_imported_module_holds_a_store_on_the_users_database():
    """Barrido: ningún módulo importado expone un store apuntado a `DB_PATH`.

    Barre `sys.modules` entero, no una lista blanca, así que un caller nuevo que
    se ligue el singleton en tiempo de import queda cubierto sin tocar este
    archivo. Los `_STORE_HOLDERS` sólo garantizan que los de hoy estén cargados
    aunque este archivo corra solo.
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
            if isinstance(value, TrackRecordStore) and _db_of(value) == PRODUCTION_DB:
                offenders.append(f"{module_name}.{attr}")

    assert not offenders, f"stores apuntados a la base del usuario: {offenders}"
