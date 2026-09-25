#!/usr/bin/env python3
"""Marca las 4 filas del comité que el track record no puede calificar (LLM-2) — dry-run por default.

Pone ``source = 'inadmissible'`` sobre 4 filas **enumeradas por id**. No borra ni
reescribe nada más: las filas quedan en la base y las lecturas de
``analysis/track_record.py`` las excluyen por el marcador, igual que a las
fixtures de U5-18d. Reversible — hoy las 4 tienen ``source='committee'``, y eso
se verifica antes de escribir una sola.

    ./venv/bin/python3 scripts/migrations/mark_inadmissible_rows.py            # sólo muestra
    ./venv/bin/python3 scripts/migrations/mark_inadmissible_rows.py --apply    # escribe

Idempotente: la segunda corrida no cambia nada y lo dice.

De dónde salen: hasta LLM-2 la página del Comité registraba sin los filtros del
Screener (``docs/AUDIT_LLM_2026-09.md``). Desde LLM-2 ``admission_skip_reason``
rechaza las tres clases al escribir, para todo escritor; esto limpia lo que entró
antes.

Lo que **no** hace: reescribir el ``fundamental_score`` de las otras 36 filas del
comité. Guardan ``total_score`` y el ``adjusted_score`` de ese momento no se puede
reconstruir; la fecha del merge de LLM-2 separa las dos escalas.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analysis.track_record import (  # noqa: E402
    INADMISSIBLE_SOURCE,
    RecommendationLog,
    RecommendationOutcome,
    TrackRecordStore,
)

# --------------------------------------------------------------------------- #
#  Los 4 ids                                                                   #
# --------------------------------------------------------------------------- #
#
# Derivados el 2026-09-25 contra una copia de `data/db/retirement_advisor.db`
# (auditoría LLM, `sqlite3 .backup` en modo solo lectura):
#
#   1021  ABVE               2026-09-15  REDUCE  score 0, señal NOT_MEASURABLE — feed vacío
#   1350  BTC-USD — BITCOIN  2026-09-21  SELL    no es un ticker
#   1507  AIR.PA             2026-09-24  HOLD    cotiza en EUR
#   1509  NOVN.SW            2026-09-24  BUY     cotiza en CHF
#
# Ninguna tenía outcome puntuado ese día; 1507 y 1509 vencían a 30 días el
# 2026-10-24 y habrían calificado el tipo de cambio contra SPY.
#
# No reemplazar por un WHERE sobre moneda o símbolo: el log no guarda la moneda,
# y un patrón sobre el símbolo (`.PA`, `.SW`) barrería filas de otros escritores
# que sí eran admisibles cuando se escribieron o que se decidan en otra fila.
# Es el mismo razonamiento que `mark_test_fixture_rows.py`.

#: 4 ids. Derivados el 2026-09-25.
INADMISSIBLE_ROW_IDS: tuple[int, ...] = (1021, 1350, 1507, 1509)

#: Lo que las 4 tienen hoy. Si un id no lo tiene, la lista está mal o la base
#: cambió — hay que parar: marcar una fila real la saca de todas las lecturas.
EXPECTED_SOURCE_BEFORE = "committee"


class UnexpectedRowError(RuntimeError):
    """Un id de la lista no tiene el ``source`` esperado. No se escribe nada."""


# --------------------------------------------------------------------------- #
#  Lectura                                                                     #
# --------------------------------------------------------------------------- #

def preview(store: TrackRecordStore, ids: tuple[int, ...] = INADMISSIBLE_ROW_IDS) -> list[dict]:
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
                    "fundamental_score": row.fundamental_score,
                    "has_outcome": row.id in scored,
                }
            )
        return filas


def _render(filas: list[dict]) -> str:
    cab = (f"{'id':>5}  {'símbolo':<18} {'acción':<7} {'created_at (UTC)':<20} "
           f"{'source':<13} {'score':>6}  outcome")
    lineas = [cab, "-" * len(cab)]
    for f in filas:
        lineas.append(
            f"{f['id']:>5}  {f['symbol']:<18} {f['action']:<7} "
            f"{str(f['created_at'])[:19]:<20} {f['source']:<13} "
            f"{f['fundamental_score'] or 0:>6.1f}  {'sí' if f['has_outcome'] else '—'}"
        )
    return "\n".join(lineas)


# --------------------------------------------------------------------------- #
#  Escritura                                                                   #
# --------------------------------------------------------------------------- #

def mark_inadmissible_rows(
    store: TrackRecordStore,
    ids: tuple[int, ...] = INADMISSIBLE_ROW_IDS,
    *,
    dry_run: bool = True,
) -> dict:
    """Marca ``ids`` con ``INADMISSIBLE_SOURCE``. Por default no escribe.

    Devuelve ``{dry_run, marked, already_marked, missing}``. El chequeo de
    ``EXPECTED_SOURCE_BEFORE`` corre sobre **todos** los ids antes de tocar el
    primero, para que un aborto no deje la base a medio marcar.
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

        ya_marcadas = [i for i, r in presentes.items() if r.source == INADMISSIBLE_SOURCE]
        inesperadas = [
            (i, r.source)
            for i, r in presentes.items()
            if r.source not in (EXPECTED_SOURCE_BEFORE, INADMISSIBLE_SOURCE)
        ]
        if inesperadas:
            raise UnexpectedRowError(
                "no se escribió nada — estos ids no tienen el source esperado "
                f"({EXPECTED_SOURCE_BEFORE!r}): {inesperadas}"
            )

        a_marcar = [i for i in presentes if i not in set(ya_marcadas)]
        if not dry_run and a_marcar:
            for row_id in a_marcar:
                presentes[row_id].source = INADMISSIBLE_SOURCE
            session.commit()

        return {
            "dry_run": dry_run,
            "marked": len(a_marcar),
            "already_marked": len(ya_marcadas),
            "missing": faltantes,
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
    print(f"\n{len(filas)} de {len(INADMISSIBLE_ROW_IDS)} ids presentes en la base.")

    try:
        report = mark_inadmissible_rows(store, dry_run=not args.apply)
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
            f"\nAplicado: {report['marked']} filas marcadas como {INADMISSIBLE_SOURCE!r} "
            f"({report['already_marked']} ya lo estaban)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
