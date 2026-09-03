#!/usr/bin/env python3
"""Borra las 2 filas de cooldown que dejó la suite en la base del usuario (N6c) — dry-run por default.

    ./venv/bin/python3 scripts/migrations/purge_test_alert_rows.py            # sólo muestra
    ./venv/bin/python3 scripts/migrations/purge_test_alert_rows.py --apply    # borra

Idempotente: la segunda corrida no encuentra nada y lo dice.

**Acá borra, y en N6 se marcó.** No es incoherencia: aquella limpieza tocaba
`recommendation_log`, donde las filas tenían outcomes puntuados y lecturas que
preservar, así que marcar era reversible y borrar no. Un cooldown de un símbolo
que no existe no alimenta ninguna lectura ni ninguna métrica — `alert_cooldowns`
sólo se consulta por `key` exacta desde `is_on_cooldown` —, así que no hay nada
que un marcador preservaría.

De dónde salieron. Medido el 2026-08-31 sobre `data/db/retirement_advisor.db`:

    alert_cooldowns   2 filas    AlertType.SIGNAL_CHANGE:TEST1  2026-05-24 20:39:46.231189
                                 AlertType.SCORE_DROP:TEST1     2026-05-24 20:39:46.233544
    alert_snapshots   0 filas
    alert_history     0 filas
    alert_mutes       0 filas

No las escribió `AlertEngine.run()`: `_fire` escribe cooldown **y** history, y
`run()` guarda un snapshot por símbolo antes de poder disparar nada. Con
snapshots y history en 0, la escritura entró por `AlertStore.set_cooldown()`
directo. Y `TEST1` no aparece en ningún commit de código — `git log -S "TEST1"
--all` sólo devuelve los dos commits de docs que lo mencionan en `BACKLOG.md`.
El agujero se cerró en N6c (`tests/conftest.py`); esto limpia lo que quedó.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from alerts.store import AlertCooldown, AlertStore  # noqa: E402

# --------------------------------------------------------------------------- #
#  Las 2 keys                                                                  #
# --------------------------------------------------------------------------- #
#
# Enumeradas, no derivadas de un patrón. Un `LIKE '%TEST%'` barrería un símbolo
# real que lo contenga, y el error caro de este script es borrar un cooldown
# vivo: reabriría una alerta que el motor había silenciado a propósito, en
# silencio y sin forma de saberlo después.

#: Derivadas el 2026-08-31 contra `data/db/retirement_advisor.db`.
TEST_COOLDOWN_KEYS: tuple[str, ...] = (
    "AlertType.SIGNAL_CHANGE:TEST1",
    "AlertType.SCORE_DROP:TEST1",
)

#: Lo que las 2 tienen hoy. Si una key existe con otra fecha, no es la fila que
#: este script derivó y hay que parar: alguien la reescribió después.
EXPECTED_DATE_PREFIX = "2026-05-24"


class UnexpectedRowError(RuntimeError):
    """Una key de la lista no tiene la fecha esperada. No se borra nada."""


# --------------------------------------------------------------------------- #
#  Lectura                                                                     #
# --------------------------------------------------------------------------- #

def preview(store: AlertStore, keys: tuple[str, ...] = TEST_COOLDOWN_KEYS) -> list[dict]:
    """Lo que hay que poder revisar fila por fila antes de aplicar."""
    with store._Session() as session:
        filas = []
        for key in keys:
            row = session.get(AlertCooldown, key)
            if row is None:
                continue
            filas.append({"key": row.key, "last_fired": row.last_fired})
        return filas


def _render(filas: list[dict]) -> str:
    cab = f"{'key':<34} last_fired (UTC)"
    lineas = [cab, "-" * len(cab)]
    for f in filas:
        lineas.append(f"{f['key']:<34} {f['last_fired']}")
    return "\n".join(lineas)


def survey(store: AlertStore) -> dict[str, int]:
    """Filas en las cuatro tablas de alertas. Contexto para quien revise el dry-run."""
    from alerts.store import AlertHistory, AlertMute, AlertSnapshot

    with store._Session() as session:
        return {
            "alert_cooldowns": session.query(AlertCooldown).count(),
            "alert_snapshots": session.query(AlertSnapshot).count(),
            "alert_history": session.query(AlertHistory).count(),
            "alert_mutes": session.query(AlertMute).count(),
        }


# --------------------------------------------------------------------------- #
#  Escritura                                                                   #
# --------------------------------------------------------------------------- #

def purge_test_cooldowns(
    store: AlertStore,
    keys: tuple[str, ...] = TEST_COOLDOWN_KEYS,
    *,
    dry_run: bool = True,
) -> dict:
    """Borra ``keys`` de ``alert_cooldowns``. Por default no escribe.

    Devuelve ``{dry_run, deleted, missing, unexpected}``.

    El chequeo de ``EXPECTED_DATE_PREFIX`` corre sobre **todas** las keys antes
    de tocar la primera, para que un aborto no deje la base a medio limpiar.

    ``missing`` no es «nada que hacer»: una key que no está es una discrepancia
    entre esta lista y la base que se está tocando, y quien corra esto tiene que
    verla — puede ser la segunda corrida, o puede ser la base equivocada.
    """
    with store._Session() as session:
        presentes = {}
        faltantes = []
        for key in keys:
            row = session.get(AlertCooldown, key)
            if row is None:
                faltantes.append(key)
            else:
                presentes[key] = row

        inesperadas = [
            (k, str(r.last_fired))
            for k, r in presentes.items()
            if not str(r.last_fired).startswith(EXPECTED_DATE_PREFIX)
        ]
        if inesperadas:
            raise UnexpectedRowError(
                "no se borró nada — estas keys no tienen la fecha esperada "
                f"({EXPECTED_DATE_PREFIX}): {inesperadas}"
            )

        if not dry_run and presentes:
            for row in presentes.values():
                session.delete(row)
            session.commit()

        return {
            "dry_run": dry_run,
            "deleted": len(presentes),
            "missing": faltantes,
            "unexpected": [],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true",
        help="borrar de verdad (sin esto sólo muestra lo que haría)",
    )
    parser.add_argument(
        "--db", default=None,
        help="ruta a la base (default: config.DB_PATH)",
    )
    args = parser.parse_args(argv)

    store = AlertStore(args.db) if args.db else AlertStore()

    conteos = survey(store)
    print("Filas por tabla de alertas:")
    for tabla, n in conteos.items():
        print(f"  {tabla:<18} {n}")

    filas = preview(store)
    print()
    if filas:
        print(_render(filas))
    print(f"\n{len(filas)} de {len(TEST_COOLDOWN_KEYS)} keys presentes en la base.")

    try:
        report = purge_test_cooldowns(store, dry_run=not args.apply)
    except UnexpectedRowError as exc:
        print(f"\nABORTADO: {exc}", file=sys.stderr)
        return 2

    if report["missing"]:
        print(f"\nATENCIÓN: keys de la lista que no están en la base: {report['missing']}")

    if report["dry_run"]:
        print(
            f"\nDRY-RUN. Borraría {report['deleted']} filas. Nada se escribió.\n"
            "Revisá la tabla de arriba fila por fila y volvé a correr con --apply."
        )
    else:
        print(f"\nAplicado: {report['deleted']} filas borradas de alert_cooldowns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
