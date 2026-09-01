"""Oráculo — la suite de tests no escribe en la base de alertas del usuario (N6c).

Hermano de `test_track_record_isolation_oracle.py`. Misma clase de fuga, otra
tabla, y una trampa más adentro que aquella no tenía.

**Medido el 2026-08-31 sobre `data/db/retirement_advisor.db`, en modo read-only:**

    alert_cooldowns   2 filas    AlertType.SIGNAL_CHANGE:TEST1  2026-05-24 20:39:46.231189
                                 AlertType.SCORE_DROP:TEST1     2026-05-24 20:39:46.233544
    alert_snapshots   0 filas
    alert_history     0 filas
    alert_mutes       0 filas

**Quién las escribió no fue un test, y no fue el engine.** `git log -S "TEST1"
--all` sobre toda la historia devuelve sólo los dos commits de *docs* que
mencionan el símbolo en `BACKLOG.md`: nunca hubo código commiteado que lo use.
Y la firma no cierra con `AlertEngine.run()` — `_fire` (`engine.py:585-586`)
escribe cooldown **y** history, `run()` guarda snapshot para todo símbolo que
procesa (`engine.py:171,215`), y no hay en el repo ningún camino que borre
`alert_snapshots`. Con snapshots en 0, la escritura entró por
`AlertStore.set_cooldown()` **directo**. Por eso lo que se fija acá es el store,
no sólo el engine.

**Qué escribe el camino de alertas.** Instrumentando `before_cursor_execute`
sobre una **copia** de la base:

    import alerts.store  (construye el singleton) → 2 escrituras
        ALTER TABLE alert_history ADD COLUMN explanation TEXT DEFAULT ''
        ALTER TABLE alert_history ADD COLUMN is_read BOOLEAN DEFAULT 0

    AlertEngine()  (sin pasar store)              → 1 escritura
        DELETE FROM alert_mutes WHERE expires_at IS NOT NULL AND expires_at <= ?

Los dos `ALTER` son inocuos sobre una base ya migrada (`_migrate` se los traga;
el `mtime` no se mueve). El `DELETE` no: sale de `purge_expired_mutes()` en
`AlertEngine.__init__`, así que **construir un engine sin store ya escribe**,
antes de correr un solo assert.

**Por qué no alcanza con la forma de N6.** `conftest.py` cierra el track record
reemplazando el singleton del módulo. Acá eso daría un verde falso: el default
`store: AlertStore = alert_store` de `alerts/engine.py:137` se evalúa al
importar y se queda con **el objeto**, no con el nombre. Medido —

    st.alert_store = st.AlertStore()          # la forma de N6
    AlertEngine.__init__.__defaults__[0] is orig  → True
    …y sigue apuntando a data/db/retirement_advisor.db

Por eso el conftest **muta el store en el lugar** en vez de reemplazarlo, y por
eso el primer test de abajo mira el default y no el nombre del módulo: es el
único que distingue las dos formas.

**Por qué estos tests no cuentan filas.** Igual que en N6: contar
`alert_cooldowns` antes y después no sirve dentro de la misma suite —el import
ya pasó— y una escritura real dejaría el daño hecho aunque el test la detecte.
Lo que se fija es la **propiedad estructural**: bajo pytest, ningún `AlertStore`
alcanzable puede resolver a `DB_PATH`.

Sin red. Sin tocar la base del usuario.
"""

from __future__ import annotations

import importlib
import sys

from alerts.store import AlertStore
from config import DB_PATH

#: La base del usuario. Ningún store alcanzable bajo pytest puede resolver acá.
PRODUCTION_DB = str(DB_PATH)

#: Módulos de primera mano que sostienen una referencia al store. `alerts.engine`
#: la toma como **default de argumento**, que es la forma que N6 no tenía;
#: `dashboard.shared` y `dashboard.app` la importan adentro de la función.
_STORE_HOLDERS = (
    "alerts.store",
    "alerts.engine",
    "dashboard.shared",
)


def _db_of(store: AlertStore) -> str:
    """Ruta del archivo SQLite detrás de un store (``:memory:`` si es de test)."""
    return str(store._engine.url.database or "")


# ------------------------------------------------------------------ #
#  El defecto que la forma de N6 no cubre: el default del engine       #
# ------------------------------------------------------------------ #

def test_the_engine_default_is_not_the_users_database():
    """El default de `AlertEngine.__init__` no puede apuntar a `DB_PATH`.

    Mira el objeto ligado en `__defaults__`, no `alerts.store.alert_store`.
    Reemplazar el singleton del módulo deja este assert en rojo, que es
    exactamente la diferencia entre cerrar N6c y creer que se cerró.
    """
    from alerts.engine import AlertEngine

    default = AlertEngine.__init__.__defaults__[0]

    assert isinstance(default, AlertStore), (
        "el default de `store` dejó de ser un AlertStore; este oráculo mira el "
        "objeto equivocado"
    )
    assert _db_of(default) != PRODUCTION_DB, (
        f"el default de AlertEngine apunta a la base del usuario: {_db_of(default)}"
    )


def test_constructing_an_engine_writes_nothing_to_the_users_database():
    """`AlertEngine()` sin store: el `DELETE` de `purge_expired_mutes` no cae en `DB_PATH`.

    Es el camino de `scripts/run_scheduler.py:162`, el único sitio de producción
    que construye un engine. Corre `__init__` entero a propósito — el resto de
    la suite lo saltea con `__new__`, que es lo que hoy tapa la fuga por
    convención en cinco archivos.
    """
    from alerts.engine import AlertEngine

    engine = AlertEngine()

    assert _db_of(engine._store) != PRODUCTION_DB, (
        f"AlertEngine() resolvió a la base del usuario: {_db_of(engine._store)}"
    )


# ------------------------------------------------------------------ #
#  La propiedad: nada resuelve a la base del usuario bajo pytest       #
# ------------------------------------------------------------------ #

def test_the_module_default_is_not_the_users_database():
    """Un `AlertStore()` sin argumentos no puede caer en `DB_PATH`.

    Esto cubre al **caller futuro**: el que construya un store nuevo en vez de
    importar el singleton. El orden de los asserts importa — el primero falla
    antes de que el segundo llegue a abrir la base del usuario.
    """
    import alerts.store as alert_store_module

    assert str(alert_store_module.DB_PATH) != PRODUCTION_DB
    assert _db_of(AlertStore()) != PRODUCTION_DB


def test_a_late_importer_gets_an_isolated_store():
    """La forma de `dashboard/shared.py:599`: import tardío del singleton."""
    from alerts.store import alert_store

    assert _db_of(alert_store) != PRODUCTION_DB


def test_set_cooldown_never_reaches_the_users_database():
    """El camino por el que entraron las dos filas `TEST1`.

    No pasa por el engine: es una llamada directa al store. Escribe de verdad
    —contra la base aislada— y verifica que la fila aterrizó ahí y no en la del
    usuario. Sin esto el oráculo fijaría dónde *apunta* el store pero no que
    escribir por el camino corto respete el redireccionamiento.
    """
    from alerts.store import AlertType, alert_store

    alert_store.set_cooldown(AlertType.SIGNAL_CHANGE, "TEST_ORACLE")

    assert _db_of(alert_store) != PRODUCTION_DB
    assert alert_store.is_on_cooldown(AlertType.SIGNAL_CHANGE, "TEST_ORACLE"), (
        "la escritura no aterrizó en el store aislado"
    )


def test_no_imported_module_holds_a_store_on_the_users_database():
    """Barrido: ningún módulo importado expone un `AlertStore` apuntado a `DB_PATH`.

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
            if isinstance(value, AlertStore) and _db_of(value) == PRODUCTION_DB:
                offenders.append(f"{module_name}.{attr}")

    assert not offenders, f"stores apuntados a la base del usuario: {offenders}"
