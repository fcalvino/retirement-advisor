"""
Data reconciliation + data-quality agent (Gran Salto — Fase 3A).

Takes the per-field values reported by several data sources (see
``data/data_sources.py``) and, for each canonical field:
  - lists every source's value,
  - picks a "chosen" value by configured source priority,
  - measures agreement (max relative difference between sources),
  - flags a conflict when that difference exceeds the threshold.

The ``data_quality_agent`` then folds this into the existing
``compute_data_quality`` badge: a material cross-source conflict downgrades the
badge one level, so a silently-wrong number surfaces in the UI instead of being
trusted blindly.

Pure functions, no network — fully unit-testable with injected/fake sources.
Conventions: thresholds from ``config.MULTI_SOURCE``; loguru.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from loguru import logger

from config import MULTI_SOURCE


@dataclass
class FieldReconciliation:
    field: str
    values: Dict[str, float]            # source -> value
    chosen_value: Optional[float]
    chosen_source: Optional[str]
    max_rel_diff_pct: float             # 0 when <2 sources
    conflict: bool
    as_of: Dict[str, Optional[str]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "values": self.values,
            "chosen_value": self.chosen_value,
            "chosen_source": self.chosen_source,
            "max_rel_diff_pct": round(self.max_rel_diff_pct, 2),
            "conflict": self.conflict,
            "as_of": self.as_of,
        }


@dataclass
class ReconciliationReport:
    symbol: str
    fields: List[FieldReconciliation]
    sources_used: List[str]

    @property
    def conflicts(self) -> List[FieldReconciliation]:
        return [f for f in self.fields if f.conflict]

    @property
    def n_conflicts(self) -> int:
        return len(self.conflicts)

    @property
    def cross_checked_fields(self) -> List[FieldReconciliation]:
        """Fields reported by 2+ sources (the ones agreement is meaningful for)."""
        return [f for f in self.fields if len(f.values) >= 2]

    @property
    def agreement_pct(self) -> Optional[float]:
        """Share of cross-checked fields that are NOT in conflict (0-100)."""
        cc = self.cross_checked_fields
        if not cc:
            return None
        agree = sum(1 for f in cc if not f.conflict)
        return round(100.0 * agree / len(cc), 1)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "sources_used": self.sources_used,
            "n_conflicts": self.n_conflicts,
            "agreement_pct": self.agreement_pct,
            "fields": [f.as_dict() for f in self.fields],
        }


def _max_rel_diff_pct(values: List[float]) -> float:
    """Max pairwise relative difference (%) using the largest magnitude as base."""
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return 0.0
    lo, hi = min(clean), max(clean)
    base = max(abs(hi), abs(lo))
    if base == 0:
        return 0.0
    return abs(hi - lo) / base * 100.0


def _choose(values_by_source: Dict[str, float]) -> tuple:
    """Pick a value by configured source priority; fall back to first available."""
    for src in MULTI_SOURCE.source_priority:
        if src in values_by_source:
            return values_by_source[src], src
    # not in priority list — take any
    src = next(iter(values_by_source))
    return values_by_source[src], src


def reconcile(symbol: str, source_results: Dict[str, Dict[str, "object"]]) -> ReconciliationReport:
    """Reconcile ``{source_name: {field: SourceValue}}`` into a report.

    ``SourceValue`` is duck-typed: any object with ``.value`` and ``.as_of``
    attributes works, which keeps this function decoupled and easy to test.
    """
    threshold = MULTI_SOURCE.discrepancy_pct
    sources_used = sorted(source_results.keys())

    # collect all fields seen across sources
    all_fields: List[str] = []
    for sv_map in source_results.values():
        for fld in sv_map:
            if fld not in all_fields:
                all_fields.append(fld)

    reconciliations: List[FieldReconciliation] = []
    for fld in all_fields:
        values_by_source: Dict[str, float] = {}
        as_of: Dict[str, Optional[str]] = {}
        for src, sv_map in source_results.items():
            if fld in sv_map:
                sv = sv_map[fld]
                val = getattr(sv, "value", None)
                if val is not None:
                    values_by_source[src] = float(val)
                    as_of[src] = getattr(sv, "as_of", None)
        if not values_by_source:
            continue
        chosen_value, chosen_source = _choose(values_by_source)
        max_diff = _max_rel_diff_pct(list(values_by_source.values()))
        conflict = len(values_by_source) >= 2 and max_diff > threshold
        if conflict:
            logger.info(f"reconcile[{symbol}]: conflict on {fld} — {values_by_source} ({max_diff:.1f}%)")
        reconciliations.append(FieldReconciliation(
            field=fld, values=values_by_source, chosen_value=chosen_value,
            chosen_source=chosen_source, max_rel_diff_pct=max_diff,
            conflict=conflict, as_of=as_of,
        ))

    return ReconciliationReport(symbol=symbol, fields=reconciliations, sources_used=sources_used)


def reconcile_sources(symbol: str, sources: List["object"]) -> ReconciliationReport:
    """Convenience: call each source's ``fetch_fundamentals`` then reconcile."""
    source_results: Dict[str, Dict[str, object]] = {}
    for src in sources:
        try:
            res = src.fetch_fundamentals(symbol)
        except Exception as exc:
            logger.warning(f"reconcile_sources: {getattr(src, 'name', src)} failed — {exc}")
            res = {}
        if res:
            source_results[getattr(src, "name", str(src))] = res
    return reconcile(symbol, source_results)


# --------------------------------------------------------------------------- #
#  Data-quality agent — folds reconciliation into the existing badge          #
# --------------------------------------------------------------------------- #

_LEVELS = ["good", "partial", "poor"]


def _downgrade(level: str, steps: int = 1) -> str:
    try:
        idx = _LEVELS.index(level)
    except ValueError:
        return level
    return _LEVELS[min(len(_LEVELS) - 1, idx + steps)]


def data_quality_agent(base_quality: dict, recon: Optional[ReconciliationReport]) -> dict:
    """Combine ``compute_data_quality`` output with cross-source reconciliation.

    Returns a new dict (does not mutate the input). Adds:
      cross_source_agreement_pct, n_source_conflicts, conflicts (field list),
      sources_used, and possibly a downgraded ``level`` + extra warnings.
    """
    out = dict(base_quality)
    out.setdefault("warnings", [])
    out["warnings"] = list(out["warnings"])  # copy

    _SCOPE_NOTE = (
        "Verificación cruzada sobre hechos crudos (revenue, NI, equity, assets), "
        "no sobre ratios del score (ROE/PE)."
    )

    if recon is None or not recon.cross_checked_fields:
        out["cross_source_agreement_pct"] = None
        out["n_source_conflicts"] = 0
        out["conflicts"] = []
        out["sources_used"] = recon.sources_used if recon else []
        out["cross_check_scope"] = "raw_facts"
        if recon is not None and len(recon.sources_used) < 2:
            out["warnings"].append(
                "Solo una fuente de datos disponible — sin verificación cruzada."
            )
        return out

    out["cross_source_agreement_pct"] = recon.agreement_pct
    out["n_source_conflicts"] = recon.n_conflicts
    out["conflicts"] = [
        {"field": f.field, "values": f.values, "max_rel_diff_pct": round(f.max_rel_diff_pct, 1)}
        for f in recon.conflicts
    ]
    out["sources_used"] = recon.sources_used
    out["cross_check_scope"] = "raw_facts"
    if _SCOPE_NOTE not in out["warnings"]:
        out["warnings"].append(_SCOPE_NOTE)

    if recon.n_conflicts > 0:
        fields = ", ".join(f.field for f in recon.conflicts)
        out["warnings"].append(
            f"Discrepancia entre fuentes en: {fields}. Revisar antes de confiar en el score."
        )
        if MULTI_SOURCE.conflict_downgrades_quality:
            out["level"] = _downgrade(out.get("level", "good"), steps=1)

    return out


def attach_cross_source_quality(result, sources=None) -> Optional[ReconciliationReport]:
    """Run multi-source reconciliation for ``result`` and fold it into its badge.

    This is how the *main analysis* consumes the reconciled view (Fase 3A close-out):
    the per-ticker ``FundamentalResult.data_quality`` dict gets the cross-source
    agreement, conflict list and a possibly-downgraded level. Mutates
    ``result.data_quality`` in place and returns the report (or None when disabled
    / crypto / no symbol). Defensive: any failure leaves the result untouched.

    Note: deliberately attaches *quality metadata* and surfaces discrepancies; it
    does NOT silently overwrite the scored numbers — surfacing a conflict to the
    user is the point, not hiding it behind an automatic correction.
    """
    if not MULTI_SOURCE.enabled:
        return None
    if getattr(result, "is_crypto", False):
        return None
    symbol = getattr(result, "symbol", "") or ""
    if not symbol:
        return None
    try:
        if sources is None:
            from data.data_sources import default_fundamental_sources

            sources = default_fundamental_sources()
        report = reconcile_sources(symbol, sources)
        base = result.data_quality if isinstance(getattr(result, "data_quality", None), dict) else {
            "level": "good", "warnings": [],
        }
        result.data_quality = data_quality_agent(base, report)
        # Surface fresh conflict warnings on the result too.
        for w in result.data_quality.get("warnings", []):
            if w not in getattr(result, "warnings", []):
                result.warnings.append(w)
        return report
    except Exception as exc:
        logger.warning(f"attach_cross_source_quality[{symbol}] skipped — {exc}")
        return None
