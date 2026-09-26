"""
Mean with a Student-t uncertainty band — pure, no project imports.

Lives outside ``analysis/track_record_scorer.py`` so the PIT-2 evidence report
(``analysis/synthetic_evidence.py``) can use the same band without importing
``analysis.track_record`` (the synthetic sample is kept out of the published
hit rate structurally, N6). The scorer re-exports both names; callers are
unchanged.
"""

from __future__ import annotations

import math
from typing import List


def mean_with_band(values: List[float]) -> dict:
    """Mean of *values* with the width of its 95 % uncertainty band.

    Pure. Exists because the mean alone invites a conclusion the sample cannot
    support. Measured on the real data (2026-08-22), the page showed:

        STRONG BUY   n=4    mean excess  +10.40 %
        BUY          n=13   mean excess   +4.08 %

    which reads as "STRONG BUY beats BUY by six points". But these excess returns
    have a standard deviation of 9.63 % and range from −23.5 % to +29.0 %; with
    four observations the band around that +10.40 % is roughly ±9 points, so the
    difference is indistinguishable from zero. Distinguishing a ~4-point gap needs
    something like fifty observations per group.

    ``band`` is the half-width: the mean is compatible with anything in
    ``mean ± band``. ``inconclusive`` is True when that interval contains zero,
    which is the flag the UI needs so a reader does not mistake noise for signal.

    Uses Student's t rather than 1.96, which matters precisely where this function
    is most needed: at n=4 the critical value is 3.18, not 1.96, so the normal
    approximation would understate the band by 60 % exactly when the sample is
    least trustworthy. A standard deviation estimated from four points is itself a
    noisy number, and t is what accounts for that.
    """
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "band": None, "inconclusive": True}
    mean = sum(values) / n
    if n < 2:
        return {"n": n, "mean": round(mean, 4), "band": None, "inconclusive": True}

    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    std_error = math.sqrt(variance / n)
    band = _t_critical(n - 1) * std_error
    return {
        "n": n,
        "mean": round(mean, 4),
        "band": round(band, 4),
        "inconclusive": abs(mean) <= band,
    }


def _t_critical(df: int) -> float:
    """Two-sided 95 % critical value for *df* degrees of freedom."""
    try:
        from scipy import stats

        return float(stats.t.ppf(0.975, df))
    except Exception:  # pragma: no cover - scipy is a hard dependency of the project
        return 1.96
