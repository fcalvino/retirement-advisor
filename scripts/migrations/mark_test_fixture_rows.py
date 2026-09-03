#!/usr/bin/env python3
"""Marca las 53 filas que escribió la suite de tests (U5-18d) — dry-run por default.

Pone ``source = 'test_fixture'`` sobre 53 filas **enumeradas por id**. No borra
nada: las filas y sus 11 outcomes quedan en la base, y las lecturas de
``analysis/track_record.py`` las excluyen por el marcador. Reversible mientras
nada se borre — hoy las 53 tienen ``source='rule_based'``, y eso se verifica
antes de escribir una sola.

    ./venv/bin/python3 scripts/migrations/mark_test_fixture_rows.py            # sólo muestra
    ./venv/bin/python3 scripts/migrations/mark_test_fixture_rows.py --apply    # escribe

Idempotente: la segunda corrida no cambia nada y lo dice.

De dónde salen estas filas: ``AlertEngine._log_opportunity`` importaba el
singleton del track record, y el fixture de ``tests/test_alert_engine.py``
reemplaza el store de *alertas*, no el de recomendaciones. Cada corrida de la
suite dejaba tres filas en la base del usuario. Cerrado en N6 (PR #50); esto
limpia lo que quedó.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analysis.track_record import (  # noqa: E402
    FIXTURE_SOURCE,
    RecommendationLog,
    RecommendationOutcome,
    TrackRecordStore,
)

# --------------------------------------------------------------------------- #
#  Los 53 ids                                                                  #
# --------------------------------------------------------------------------- #
#
# ¡NO REEMPLAZAR ESTA LISTA POR UNA CONSULTA POR PATRÓN!
#
# La tentación es obvia: las 53 comparten rationale ("Alerta de oportunidad: entró
# con señal …"), source ('rule_based') y price_at_rec (NULL), así que un WHERE con
# esa firma parece más limpio que 53 números. Es la peor variante posible, y es
# invisible cuando falla:
#
#   - El rationale lo escribe alerts/engine.py:521 y el source sale de :528. Los
#     dos son CÓDIGO DE PRODUCCIÓN. Una corrida real del alert engine produce una
#     fila byte-idéntica en las tres columnas, price_at_rec NULL incluido — el
#     loop de alertas no tiene precio, y el scorer lo resuelve en memoria sin
#     persistirlo (track_record_scorer.py:147).
#   - source='rule_based' tampoco distingue: 2_Stock_Analysis.py:180 lo escribe
#     cada vez que el usuario analiza un ticker con la IA apagada.
#   - Un patrón sobre el texto '%Alerta%' ya barrería una fila real: la id 166
#     (CME, source=screener, price_at_rec=278.63) lleva esa palabra adentro de un
#     rationale legítimo.
#
# La firma acierta 53/53 HOY por un accidente histórico: alert_snapshots tiene 0
# filas, o sea que el alert engine nunca completó una corrida real contra esta
# base (un arranque en frío guarda un baseline por ticker antes de poder disparar
# nada). Eso es un hecho sobre el pasado, no una regla sobre el futuro.
#
# Lo único que identifica con certeza es que el conjunto está CERRADO: la última
# fixture es la id 470, del 2026-08-30 13:45 UTC, y desde PR #50 la suite no puede
# escribir más. Derivado una vez, a mano, contra la base congelada.
#
# tests/test_track_record_fixture_exclusion_oracle.py::test_the_decoy_row_survives
# siembra las dos filas señuelo y falla si alguien cambia esto por un patrón.

#: 53 ids. Derivados el 2026-08-30 contra `data/db/retirement_advisor.db`.
FIXTURE_ROW_IDS: tuple[int, ...] = (
    7, 8, 9, 10, 11,
    14, 15, 16,
    20, 21, 22,
    24, 25, 26,
    36, 37, 38, 39, 40, 41,
    43, 44, 45,
    47, 48, 49,
    52, 53, 54, 55, 56, 57,
    137, 138, 139, 140, 141, 142, 143, 144, 145,
    223, 224, 225,
    303, 304, 305,
    395, 396, 397,
    468, 469, 470,
)

#: Lo que las 53 tienen hoy. Si un id no lo tiene, la lista está mal o la base
#: cambió — y en los dos casos hay que parar, porque el error caro de este script
#: es marcar una fila real: desaparecería de todas las lecturas, en silencio.
EXPECTED_SOURCE_BEFORE = "rule_based"


class UnexpectedRowError(RuntimeError):
    """Un id de la lista no tiene el ``source`` esperado. No se escribe nada."""


# --------------------------------------------------------------------------- #
#  Lectura                                                                     #
# --------------------------------------------------------------------------- #

def preview(store: TrackRecordStore, ids: tuple[int, ...] = FIXTURE_ROW_IDS) -> list[dict]:
    """Lo que hay que poder revisar fila por fila antes de aplicar."""
    with store._Session() as session:
        scored = {
            row[0]
            for row in session.query(RecommendationOutcome.rec_id)
            .filter(RecommendationOutcome.rec_id.in_(ids))
            .all()
        }
        filas = []
        for row_id in ids:
            row = session.get(RecommendationLog, row_id)
            if row is None:
                continue
            filas.append(
                {
                    "id": row.id,
                    "symbol": row.symbol,
                    "action": row.action,
                    "created_at": row.created_at,
                    "source": row.source,
                    "price_at_rec": row.price_at_rec,
                    "has_outcome": row.id in scored,
                }
            )
        return filas


def _render(filas: list[dict]) -> str:
    cab = f"{'id':>5}  {'símbolo':<9} {'acción':<11} {'created_at (UTC)':<20} {'source':<12} {'precio':>8}  outcome"
    lineas = [cab, "-" * len(cab)]
    for f in filas:
        precio = "NULL" if f["price_at_rec"] is None else f"{f['price_at_rec']:.2f}"
        lineas.append(
            f"{f['id']:>5}  {f['symbol']:<9} {f['action']:<11} "
            f"{str(f['created_at'])[:19]:<20} {f['source']:<12} {precio:>8}  "
            f"{'sí' if f['has_outcome'] else '—'}"
        )
    return "\n".join(lineas)


# --------------------------------------------------------------------------- #
#  Escritura                                                                   #
# --------------------------------------------------------------------------- #

def mark_fixture_rows(
    store: TrackRecordStore,
    ids: tuple[int, ...] = FIXTURE_ROW_IDS,
    *,
    dry_run: bool = True,
) -> dict:
    """Marca ``ids`` con ``FIXTURE_SOURCE``. Por default no escribe.

    Devuelve ``{dry_run, marked, already_marked, missing, unexpected}``.

    El chequeo de ``EXPECTED_SOURCE_BEFORE`` corre sobre **todos** los ids antes
    de tocar el primero, para que un aborto no deje la base a medio marcar.

    ``missing`` no es «nada que hacer»: un id que no está en la base es una
    discrepancia entre esta lista y la base que se está tocando, y quien corra
    esto tiene que verla.
    """
    with store._Session() as session:
        presentes = {}
        faltantes = []
        for row_id in ids:
            row = session.get(RecommendationLog, row_id)
            if row is None:
                faltantes.append(row_id)
            else:
                presentes[row_id] = row

        ya_marcadas = [i for i, r in presentes.items() if r.source == FIXTURE_SOURCE]
        inesperadas = [
            (i, r.source)
            for i, r in presentes.items()
            if r.source not in (EXPECTED_SOURCE_BEFORE, FIXTURE_SOURCE)
        ]
        if inesperadas:
            raise UnexpectedRowError(
                "no se escribió nada — estos ids no tienen el source esperado "
                f"({EXPECTED_SOURCE_BEFORE!r}): {inesperadas}"
            )

        a_marcar = [i for i in presentes if i not in set(ya_marcadas)]
        if not dry_run and a_marcar:
            for row_id in a_marcar:
                presentes[row_id].source = FIXTURE_SOURCE
            session.commit()

        return {
            "dry_run": dry_run,
            "marked": len(a_marcar),
            "already_marked": len(ya_marcadas),
            "missing": faltantes,
            "unexpected": [],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true",
        help="escribir de verdad (sin esto sólo muestra lo que haría)",
    )
    parser.add_argument(
        "--db", default=None,
        help="ruta a la base (default: config.DB_PATH)",
    )
    args = parser.parse_args(argv)

    store = TrackRecordStore(args.db) if args.db else TrackRecordStore()

    filas = preview(store)
    print(_render(filas))
    print(f"\n{len(filas)} de {len(FIXTURE_ROW_IDS)} ids presentes en la base.")
    con_outcome = sum(1 for f in filas if f["has_outcome"])
    print(f"{con_outcome} tienen outcome puntuado — no se tocan: caen con su fila al leer.")

    try:
        report = mark_fixture_rows(store, dry_run=not args.apply)
    except UnexpectedRowError as exc:
        print(f"\nABORTADO: {exc}", file=sys.stderr)
        return 2

    if report["missing"]:
        print(f"\nATENCIÓN: ids de la lista que no están en la base: {report['missing']}")

    if report["dry_run"]:
        print(
            f"\nDRY-RUN. Marcaría {report['marked']} filas "
            f"({report['already_marked']} ya estaban). Nada se escribió.\n"
            "Revisá la tabla de arriba fila por fila y volvé a correr con --apply."
        )
    else:
        print(
            f"\nAplicado: {report['marked']} filas marcadas como {FIXTURE_SOURCE!r} "
            f"({report['already_marked']} ya lo estaban)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
