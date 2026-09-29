"""Cuánto cambia el dictamen del comité entre corridas con el mismo input (#151).

La caché de 24 h hace que el dictamen *parezca* estable dentro del día. Esto
mide lo que hay debajo: el mismo panel congelado (`eval_cases.stability_cases`)
corrido N veces sin caché, y por caso la tasa de cambio de la acción —cruda y
después del overlay—, la dispersión del lean y qué voces cambian de postura.

Un panel incompleto (una voz cortada por rate limit, un JSON inválido) se
registra pero queda **fuera** de las métricas y se cuenta aparte: tiene otra
composición de votos, y leerlo como un cambio de opinión del modelo atribuiría
al modelo una falla del transporte.

Puro: el proveedor se inyecta (`eval_harness.CommitteeProvider`) y la escritura
a disco la hace el llamador con ``on_record``.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from loguru import logger


@dataclass(frozen=True)
class StabilityRecord:
    case_id: str
    run: int
    provider: str
    action: str                     # the panel's vote, before the overlay
    final_action: str               # what the user sees (`to_decision`, post-overlay)
    lean: Optional[float]
    confidence: str
    stances: Dict[str, str] = field(default_factory=dict)   # role -> stance, valid votes only
    complete: bool = False
    quorum_pct: float = 0.0
    failure_causes: List[str] = field(default_factory=list)
    abstentions: Dict[str, str] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def record_from_dict(d: dict) -> StabilityRecord:
    return StabilityRecord(**{k: d[k] for k in StabilityRecord.__dataclass_fields__ if k in d})


def _record(case, run: int, provider) -> StabilityRecord:
    name = getattr(provider, "name", "?")
    try:
        verdict = provider.get_verdict(case)
    except Exception as exc:  # one failed panel does not end a paid run
        logger.error(f"stability: {case.case_id} run {run} falló — {exc}")
        return StabilityRecord(case.case_id, run, name, "ERROR", "ERROR", None, "",
                               error=str(exc))
    final = verdict.to_decision(case.fund, case.tech).action if verdict.available else "UNAVAILABLE"
    return StabilityRecord(
        case_id=case.case_id, run=run, provider=name,
        action=verdict.action, final_action=final,
        lean=float(verdict.lean), confidence=verdict.confidence,
        stances={o.role: o.stance for o in verdict.opinions if o.ok},
        complete=bool(verdict.complete), quorum_pct=float(verdict.quorum_pct),
        failure_causes=list(verdict.failure_causes),
        abstentions=dict(verdict.abstentions),
    )


def run_stability(provider, cases, runs: int,
                  done: Iterable[Tuple[str, int]] = frozenset(),
                  on_record: Optional[Callable[[StabilityRecord], None]] = None,
                  ) -> List[StabilityRecord]:
    """Corrida × caso, en ese orden: un corte a mitad de camino deja corridas enteras.

    ``done`` son los pares ``(case_id, run)`` ya registrados (reanudar).
    """
    done = set(done)
    out: List[StabilityRecord] = []
    for run in range(runs):
        for case in cases:
            if (case.case_id, run) in done:
                continue
            rec = _record(case, run, provider)
            logger.info(f"stability: {rec.case_id} run {run} → {rec.action}/{rec.final_action} "
                        f"lean={rec.lean} complete={rec.complete}")
            out.append(rec)
            if on_record is not None:
                on_record(rec)
    return out


# --------------------------------------------------------------------------- #
#  Métricas                                                                   #
# --------------------------------------------------------------------------- #

def _agreement(values: List[str]) -> dict:
    """Modal value, change rate (share of runs that differ from it) and counts."""
    if not values:
        return {"modal": None, "change_rate": None, "distinct": 0, "counts": {}}
    counts = Counter(values)
    modal, n_modal = counts.most_common(1)[0]
    return {
        "modal": modal,
        "change_rate": 1 - n_modal / len(values),
        "distinct": len(counts),
        "counts": dict(counts),
    }


def _spread(values: List[float]) -> dict:
    if not values:
        return {"mean": None, "stdev": None, "min": None, "max": None}
    return {
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else None,  # n=1: no medido
        "min": min(values),
        "max": max(values),
    }


def _case_summary(records: List[StabilityRecord]) -> dict:
    ok = [r for r in records if r.complete]
    roles: Dict[str, List[str]] = {}
    for r in ok:
        for role, stance in r.stances.items():
            roles.setdefault(role, []).append(stance)
    return {
        "n_runs": len(records),
        "n_complete": len(ok),
        "n_incomplete": len(records) - len(ok),
        "incomplete_causes": dict(Counter(
            c for r in records if not r.complete for c in (r.failure_causes or ["error"])
        )),
        "action": _agreement([r.action for r in ok]),
        "final_action": _agreement([r.final_action for r in ok]),
        "lean": _spread([r.lean for r in ok if r.lean is not None]),
        "roles": {
            role: {
                "modal": (a := _agreement(stances))["modal"],
                "agreement": 1 - a["change_rate"],
                "distinct": a["distinct"],
                "n": len(stances),
            }
            for role, stances in sorted(roles.items())
        },
    }


def _provider_summary(records: List[StabilityRecord]) -> dict:
    by_case: Dict[str, List[StabilityRecord]] = {}
    for r in records:
        by_case.setdefault(r.case_id, []).append(r)
    cases = {cid: _case_summary(rs) for cid, rs in by_case.items()}
    rates = [c["action"]["change_rate"] for c in cases.values()
             if c["action"]["change_rate"] is not None]
    final_rates = [c["final_action"]["change_rate"] for c in cases.values()
                   if c["final_action"]["change_rate"] is not None]
    return {
        "n_cases": len(cases),
        "n_records": len(records),
        "n_complete": sum(c["n_complete"] for c in cases.values()),
        "cases_with_action_change": sum(1 for r in rates if r > 0),
        "cases_with_final_action_change": sum(1 for r in final_rates if r > 0),
        "mean_action_change_rate": statistics.mean(rates) if rates else None,
        "mean_final_action_change_rate": statistics.mean(final_rates) if final_rates else None,
        "cases": cases,
    }


def summarize_stability(records: List[StabilityRecord]) -> dict:
    """Por proveedor/modelo y, dentro, por caso. Sin mezclar modelos entre sí.

    ``cases`` repite la vista por caso cuando hay un solo proveedor; con varios
    queda vacío a propósito, para que nadie lea una tasa que mezcla modelos.
    """
    groups: Dict[str, List[StabilityRecord]] = {}
    for r in records:
        groups.setdefault(r.provider, []).append(r)
    by_provider = {name: _provider_summary(rs) for name, rs in groups.items()}
    only = next(iter(by_provider.values())) if len(by_provider) == 1 else None
    return {"by_provider": by_provider, "cases": only["cases"] if only else {}}
