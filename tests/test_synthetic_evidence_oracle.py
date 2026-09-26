"""PIT-2 — la lectura de la evidencia point-in-time, contra su definición.

``analysis/synthetic_evidence.summarize`` agrupa las filas de
``synthetic_recommendation`` por F-Score con los **mismos cortes que el motor**
(fuerte ≥ ``PIOTROSKI.strong_threshold``, aceptable ≥ ``PIOTROSKI.good_threshold``,
débil el resto) y compara fuerte − débil **por corte**: filas del mismo día
comparten el mercado, así que la unidad casi-independiente es el corte, no la
fila (CONTEXT §8).

Las medias y bandas se recalculan acá desde la definición (media muestral,
desvío con n−1, t de Student al 97,5 %), no se le piden al módulo.
"""

from __future__ import annotations

import math

import pytest
from scipy import stats

from analysis.synthetic_evidence import (
    GROUP_ACCEPTABLE,
    GROUP_STRONG,
    GROUP_WEAK,
    VERDICT_INCONCLUSIVE,
    VERDICT_STRONG_WINS,
    VERDICT_WEAK_WINS,
    group_for,
    summarize,
)
from config import PIOTROSKI


def _ref(values):
    """Media y semiancho de banda al 95 % desde la definición."""
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    return mean, stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)


def _row(symbol, as_of, score, excess, status="scored"):
    return {
        "symbol": symbol,
        "as_of": as_of,
        "piotroski_score": score,
        "excess_return_pct": excess,
        "outcome_status": status,
    }


S = PIOTROSKI.strong_threshold
G = PIOTROSKI.good_threshold


def test_groups_use_the_engine_cuts():
    assert group_for(S) == GROUP_STRONG
    assert group_for(9) == GROUP_STRONG
    assert group_for(S - 1) == (GROUP_ACCEPTABLE if S - 1 >= G else GROUP_WEAK)
    assert group_for(G) == GROUP_ACCEPTABLE
    assert group_for(G - 1) == GROUP_WEAK
    assert group_for(0) == GROUP_WEAK


def test_group_means_bands_and_share_positive():
    strong = [4.0, -1.0, 7.5, 2.0]
    weak = [-3.0, 1.0, -6.0]
    rows = [_row(f"S{i}", "2015-06-01", 9, x) for i, x in enumerate(strong)]
    rows += [_row(f"W{i}", "2015-06-01", 2, x) for i, x in enumerate(weak)]
    rows.append(_row("P", "2015-06-01", 9, None, status="partial"))  # sin exceso: no entra

    out = summarize(rows)
    g = out["groups"][GROUP_STRONG]
    mean, band = _ref(strong)
    assert g["n"] == 5 and g["n_excess"] == 4
    assert g["mean"] == pytest.approx(mean, abs=1e-4)
    assert g["band"] == pytest.approx(band, abs=1e-4)
    assert g["pct_positive"] == pytest.approx(75.0)

    w = out["groups"][GROUP_WEAK]
    mean, band = _ref(weak)
    assert w["mean"] == pytest.approx(mean, abs=1e-4)
    assert w["band"] == pytest.approx(band, abs=1e-4)
    assert out["groups"][GROUP_ACCEPTABLE]["n"] == 0


def test_status_counts_include_pending():
    rows = [
        _row("A", "2015-06-01", 9, 1.0),
        _row("B", "2015-06-01", 9, None, status="delisted_before_horizon"),
        _row("C", "2025-06-01", 9, None, status=None),
    ]
    assert summarize(rows)["status_counts"] == {
        "scored": 1, "delisted_before_horizon": 1, "pending": 1,
    }


def test_the_comparison_is_per_cutoff_not_per_row():
    """Tres cortes; en cada uno la diferencia es media(fuerte) − media(débil).
    Un corte sin alguno de los dos grupos no aporta diferencia."""
    rows = [
        # 2014: fuerte (5, 7) → 6 ; débil (1) → 1 ; diff 5
        _row("A", "2014-06-01", 9, 5.0), _row("B", "2014-06-01", 8, 7.0), _row("C", "2014-06-01", 1, 1.0),
        # 2015: fuerte (2) ; débil (4, 0) → 2 ; diff 0
        _row("A", "2015-06-01", 7, 2.0), _row("C", "2015-06-01", 0, 4.0), _row("D", "2015-06-01", 3, 0.0),
        # 2016: fuerte (10) ; débil (−2) ; diff 12
        _row("A", "2016-06-01", 9, 10.0), _row("C", "2016-06-01", 2, -2.0),
        # 2017: sólo fuerte → no aporta
        _row("A", "2017-06-01", 9, 3.0),
    ]
    cmp_ = summarize(rows)["strong_minus_weak"]
    diffs = [5.0, 0.0, 12.0]
    mean, band = _ref(diffs)
    assert cmp_["n_cutoffs"] == 3
    assert cmp_["diffs"] == pytest.approx(diffs)
    assert cmp_["mean"] == pytest.approx(mean, abs=1e-4)
    assert cmp_["band"] == pytest.approx(band, abs=1e-4)


def test_verdict_is_inconclusive_when_the_band_contains_zero():
    rows = []
    for year, (s, w) in enumerate([(5.0, 1.0), (0.0, 2.0), (12.0, -2.0)]):
        rows += [_row("A", f"{2014 + year}-06-01", 9, s), _row("B", f"{2014 + year}-06-01", 1, w)]
    assert summarize(rows)["verdict"] == VERDICT_INCONCLUSIVE


def test_verdict_names_the_winner_only_when_the_band_excludes_zero():
    strong_wins, weak_wins = [], []
    for year, d in enumerate([4.0, 5.0, 6.0, 5.0, 4.5]):
        cut = f"{2010 + year}-06-01"
        strong_wins += [_row("A", cut, 9, d), _row("B", cut, 1, 0.0)]
        weak_wins += [_row("A", cut, 9, 0.0), _row("B", cut, 1, d)]
    assert summarize(strong_wins)["verdict"] == VERDICT_STRONG_WINS
    assert summarize(weak_wins)["verdict"] == VERDICT_WEAK_WINS


def test_no_rows_is_inconclusive_not_an_error():
    out = summarize([])
    assert out["verdict"] == VERDICT_INCONCLUSIVE
    assert out["strong_minus_weak"]["n_cutoffs"] == 0


def test_accepts_orm_like_objects():
    from types import SimpleNamespace

    rows = [SimpleNamespace(**_row("A", "2015-06-01", 9, 1.0))]
    assert summarize(rows)["groups"][GROUP_STRONG]["n_excess"] == 1


def test_the_engine_reads_good_threshold_from_config():
    """El corte «aceptable» era un literal 5 en analysis/scoring.py; el reporte
    necesita el mismo que el motor, así que vive en config."""
    import inspect

    import analysis.scoring as scoring

    src = inspect.getsource(scoring)
    assert "p_detail.score >= 5" not in src
    assert "good_threshold" in src


def test_the_report_does_not_import_the_live_track_record():
    """N6: la muestra sintética no toca el track record publicado, ni por import."""
    import subprocess
    import sys

    code = (
        "import sys, analysis.synthetic_evidence, analysis.price_lookup, analysis.synthetic_outcome;"
        "print('analysis.track_record' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_the_report_renders_the_summary_and_its_caveats():
    import sys as _sys
    from pathlib import Path

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.pit_evidence_report import SURVIVORSHIP_WARNING, render_markdown

    rows = []
    for year, (s, w) in enumerate([(5.0, 1.0), (0.0, 2.0), (12.0, -2.0)]):
        rows += [_row("A", f"{2014 + year}-06-01", 9, s), _row("B", f"{2014 + year}-06-01", 1, w)]
    md = render_markdown(summarize(rows), generated_at="2026-09-26 12:00 UTC", sha="abc1234",
                         universes=["default"], cutoffs=["2014-06-01", "2016-06-01"])

    assert SURVIVORSHIP_WARNING in md
    assert "abc1234" in md
    assert f"**Veredicto: {VERDICT_INCONCLUSIVE}.**" in md
    assert "| 2016-06-01 | +14.00 pp |" in md
