"""
Reading of the point-in-time evidence (PIT-2) — pure, rows in, summary out.

``synthetic_recommendation`` holds a Piotroski F-Score reconstructed at past
cutoffs and, once PIT-1 scored it, the excess return over the next year. This
module answers the question U5-1b needs before touching the Piotroski bonus:
**do the names the engine pays as "fuerte" beat the ones it calls "débil"?**

- Groups use the engine's own cuts (``PIOTROSKI.strong_threshold`` /
  ``good_threshold``), so the report measures the bonus as it is paid.
- The comparison is strong − weak **per cutoff**: rows of the same day share
  the market's move, so they are not independent observations (CONTEXT §8).
  The cutoff is the near-independent unit; the band is taken over those
  per-cutoff differences.
- The verdict is only one of three sentences and never a recommendation: the
  recalibration itself is U5-1b, a human decision.

Must not import ``analysis.track_record`` (N6 isolation): the band comes from
``analysis.stats_bands``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List

from analysis.stats_bands import mean_with_band
from config import PIOTROSKI

GROUP_STRONG = "fuerte"
GROUP_ACCEPTABLE = "aceptable"
GROUP_WEAK = "débil"
GROUPS = (GROUP_STRONG, GROUP_ACCEPTABLE, GROUP_WEAK)

VERDICT_INCONCLUSIVE = "inconcluso"
VERDICT_STRONG_WINS = "fuerte supera a débil"
VERDICT_WEAK_WINS = "débil supera a fuerte"

#: ``outcome_status`` of a row PIT-1 has not touched yet.
STATUS_PENDING = "pending"


def _get(row: Any, key: str) -> Any:
    return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def group_for(score: int) -> str:
    """The engine's Piotroski bucket for an F-Score (``analysis/scoring.py``)."""
    if score >= PIOTROSKI.strong_threshold:
        return GROUP_STRONG
    if score >= PIOTROSKI.good_threshold:
        return GROUP_ACCEPTABLE
    return GROUP_WEAK


def _mean(values: List[float]) -> float:
    return sum(values) / len(values)


def summarize(rows: Iterable[Any]) -> Dict[str, Any]:
    """Per-group stats, status counts, and the per-cutoff strong − weak comparison.

    ``rows`` are ``SyntheticRecommendation`` objects or dicts with
    ``as_of``, ``piotroski_score``, ``excess_return_pct``, ``outcome_status``.
    A row without an excess (pending, partial, delisted, no price) counts in
    ``n`` and in ``status_counts`` but not in any mean.
    """
    rows = list(rows)
    status_counts: Counter = Counter()
    members: Dict[str, int] = {g: 0 for g in GROUPS}
    excesses: Dict[str, List[float]] = {g: [] for g in GROUPS}
    by_cutoff: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: {g: [] for g in GROUPS})

    for row in rows:
        status_counts[_get(row, "outcome_status") or STATUS_PENDING] += 1
        group = group_for(int(_get(row, "piotroski_score")))
        members[group] += 1
        excess = _get(row, "excess_return_pct")
        if excess is None:
            continue
        excesses[group].append(float(excess))
        by_cutoff[str(_get(row, "as_of"))][group].append(float(excess))

    groups = {}
    for g in GROUPS:
        band = mean_with_band(excesses[g])
        values = excesses[g]
        groups[g] = {
            "n": members[g],
            "n_excess": len(values),
            "mean": band["mean"],
            "band": band["band"],
            "inconclusive": band["inconclusive"],
            "pct_positive": (round(100.0 * sum(1 for v in values if v > 0) / len(values), 2) if values else None),
        }

    cutoffs = sorted(c for c, per in by_cutoff.items() if per[GROUP_STRONG] and per[GROUP_WEAK])
    diffs = [
        round(_mean(by_cutoff[c][GROUP_STRONG]) - _mean(by_cutoff[c][GROUP_WEAK]), 4)
        for c in cutoffs
    ]
    diff_band = mean_with_band(diffs)
    if diff_band["inconclusive"]:
        verdict = VERDICT_INCONCLUSIVE
    else:
        verdict = VERDICT_STRONG_WINS if diff_band["mean"] > 0 else VERDICT_WEAK_WINS

    return {
        "n_rows": len(rows),
        "groups": groups,
        "status_counts": dict(status_counts),
        "strong_minus_weak": {
            "n_cutoffs": len(cutoffs),
            "cutoffs": cutoffs,
            "diffs": diffs,
            "mean": diff_band["mean"],
            "band": diff_band["band"],
            "inconclusive": diff_band["inconclusive"],
        },
        "verdict": verdict,
    }
