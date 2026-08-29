"""Oracle tests for a missing benchmark in the track record scorer.

Backlog row U2-4 (oleada 2 · P0 · negocio · fuente P2)
-----------------------------------------------------
  hallazgo : Benchmark missing = 0 -> le gano al mercado.
  evidencia: track_record_scorer persiste excess == return.
  fix      : No persistir hit sin bench; flag benchmark_missing.
  oráculo  : lookup fail != hit.

Why this file exists
--------------------
``score_due_recommendations`` turned "I do not know what the market did" into
"the market did nothing"::

    if bench_then and bench_now:
        benchmark_return_pct = (bench_now / bench_then - 1.0) * 100.0
    else:
        benchmark_return_pct = 0.0          # <- missing becomes "flat market"
    excess = return_pct - benchmark_return_pct   # <- excess == return_pct

A BUY that rose 10 % while SPY rose 12 % is a *loss* against the market. With the
benchmark lookup failing, that recommendation was persisted as ``excess=+10.0,
hit=True`` — a win. The row is permanent, indistinguishable from a real one, and
it is read back by every aggregate on the Track Record page and by the honest
one-liner on the home screen. This is the same defect as U2-3 (a missing input
treated as a zero) one module further along, and it lands on the one table whose
entire purpose is to be believable.

The same coercion repeats one layer up, in the aggregates:
``float(r.get("excess_return_pct") or 0.0)`` averages an unknown as a zero, and
``equity_curve``'s ``r.get("benchmark_return_pct") or 0.0`` plots the model
against a flat benchmark line. Those are covered here too, because a flag nobody
reads would not change a single number on screen.

The reference used here is an **independently written, deliberately slow scorer**
derived from the definition (excess = asset return − benchmark return; a
directional call cannot be graded without the direction to grade it against), not
the engine's own helpers (``docs/CONTEXT.md §5``: engine tests are oracles, not
self-consistency checks).

Pure Python + in-memory SQLite — no network, no Streamlit.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Optional

import pytest

from analysis.track_record import RecommendationLog, TrackRecordStore
from analysis.track_record_scorer import (
    calibration_by_confidence,
    compute_hit,
    equity_curve,
    hit_rate_by_action,
    score_due_recommendations,
    summary_stats,
)
from data.clock import utc_now

BULLISH = ("STRONG BUY", "BUY")
BEARISH = ("REDUCE", "SELL", "AVOID")
HOLD_BAND_PCT = 5.0


# --------------------------------------------------------------------------- #
#  Reference implementation (independent, from the definition)                #
# --------------------------------------------------------------------------- #

def reference_outcome(
    action: str,
    price_then: float,
    price_now: float,
    bench_then: Optional[float],
    bench_now: Optional[float],
) -> dict:
    """What a scored outcome *should* be, written from the definitions alone.

    Deliberately verbose and independent of the engine:

    - The asset's return is always knowable from its own two prices.
    - The excess return is defined *relative to the benchmark*. With either end of
      the benchmark missing there is no such quantity — it is unknown, which is
      not the same number as zero.
    - A directional call (bullish / bearish) is graded against the market, so it
      cannot be graded at all when the market is unknown.
    - A HOLD is graded against an absolute band, so it stays gradable.
    """
    asset_return = (price_now / price_then - 1.0) * 100.0

    if bench_then is None or bench_now is None:
        benchmark_return = None
        excess = None
    else:
        benchmark_return = (bench_now / bench_then - 1.0) * 100.0
        excess = asset_return - benchmark_return

    a = action.upper()
    if a in BULLISH:
        hit = None if excess is None else excess > 0
    elif a in BEARISH:
        hit = None if excess is None else excess < 0
    else:
        hit = abs(asset_return) <= HOLD_BAND_PCT

    return {
        "return_pct": asset_return,
        "benchmark_return_pct": benchmark_return,
        "excess_return_pct": excess,
        "hit": hit,
        "benchmark_missing": benchmark_return is None,
    }


def reference_hit_rate(rows: list) -> Optional[float]:
    """Wins over gradable calls. A call that could not be graded is not a call."""
    gradable = [r for r in rows if r.get("hit") is not None]
    if not gradable:
        return None
    wins = 0
    for r in gradable:
        if r["hit"]:
            wins += 1
    return wins / len(gradable)


def reference_mean_excess(rows: list) -> Optional[float]:
    """Average of the excesses that exist. An unknown excess has no value to average."""
    known = []
    for r in rows:
        value = r.get("excess_return_pct")
        if value is not None:
            known.append(float(value))
    if not known:
        return None
    total = 0.0
    for v in known:
        total += v
    return total / len(known)


# --------------------------------------------------------------------------- #
#  Fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #

@pytest.fixture
def store():
    return TrackRecordStore(db_path=":memory:")


def _decision(symbol="NVDA", action="BUY", confidence="HIGH"):
    return SimpleNamespace(
        symbol=symbol,
        action=action,
        confidence=confidence,
        fundamental_score=72.0,
        technical_signal="BULLISH",
        rationale=["oráculo U2-4"],
    )


def _log_due(store, *, symbol, action, price_at_rec, created):
    """Log a recommendation and backdate it so the 30-day horizon has elapsed."""
    rid = store.log_recommendation(_decision(symbol=symbol, action=action), price_at_rec=price_at_rec)
    assert rid is not None
    with store._Session() as s:  # noqa: SLF001 - test introspection
        s.get(RecommendationLog, rid).created_at = created
        s.commit()
    return rid


def _lookup_from(table):
    """Price lookup over a ``{(symbol, date): price}`` table. Missing key -> None."""
    def lookup(symbol, when):
        return table.get((symbol, when.date()))
    return lookup


# --------------------------------------------------------------------------- #
#  A — the finding itself: a failed lookup is not a win                        #
# --------------------------------------------------------------------------- #

def test_a_benchmark_lookup_failure_is_never_persisted_as_beating_the_market(store):
    """NVDA +10 % while the market did +12 %: a loss, recorded as a 10-point win.

    The market leg is what the lookup fails on, so the engine never sees the +12 %.
    What it must not do is *invent* a 0 % market and call the result a hit.
    """
    created = utc_now() - timedelta(days=40)
    horizon_date = created + timedelta(days=30)
    _log_due(store, symbol="NVDA", action="BUY", price_at_rec=100.0, created=created)

    # NVDA is priceable; SPY is not (no rows for it at all).
    lookup = _lookup_from({("NVDA", horizon_date.date()): 110.0})

    score_due_recommendations(store, price_lookup=lookup)

    rows = store.get_scored_rows(30)
    assert len(rows) == 1, "la evidencia de precio no se descarta: la fila se persiste igual"
    row = rows[0]

    truth = reference_outcome("BUY", 100.0, 110.0, bench_then=None, bench_now=None)

    assert row["return_pct"] == pytest.approx(truth["return_pct"], abs=0.01)
    assert row["excess_return_pct"] is None, (
        "sin benchmark no existe el exceso; persistirlo como el retorno propio "
        "es afirmar que el mercado quedó plano"
    )
    assert row["excess_return_pct"] != row["return_pct"]
    assert row["benchmark_return_pct"] is None
    assert row["hit"] is None, "un lookup fallido no es un acierto"
    assert row["hit"] is not True
    assert row["benchmark_missing"] is True


def test_a2_the_counters_separate_partial_from_fully_scored(store):
    created = utc_now() - timedelta(days=40)
    horizon_date = created + timedelta(days=30)
    _log_due(store, symbol="NVDA", action="BUY", price_at_rec=100.0, created=created)

    res = score_due_recommendations(
        store, price_lookup=_lookup_from({("NVDA", horizon_date.date()): 110.0})
    )
    assert res["scored"] == 0, "una fila sin benchmark no está puntuada"
    assert res["partial"] == 1
    assert res["skipped"] == 0, "el precio del ticker sí estaba: no es un salteo"


# --------------------------------------------------------------------------- #
#  B — the resolvable case still matches the reference exactly                 #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "action, price_now, bench_now",
    [
        ("BUY", 110.0, 400.0),          # +10 % vs flat market -> win
        ("BUY", 110.0, 448.0),          # +10 % vs +12 % market -> loss
        ("STRONG BUY", 90.0, 380.0),    # -10 % vs -5 % market -> loss
        ("SELL", 90.0, 400.0),          # -10 % vs flat -> avoiding was right
        ("SELL", 130.0, 400.0),         # +30 % vs flat -> avoiding was wrong
        ("HOLD", 102.0, 440.0),         # small move -> holding was right
        ("HOLD", 130.0, 400.0),         # big move missed -> holding was wrong
    ],
)
def test_b_engine_agrees_with_the_reference_when_the_benchmark_resolves(
    store, action, price_now, bench_now
):
    created = utc_now() - timedelta(days=40)
    horizon_date = created + timedelta(days=30)
    _log_due(store, symbol="NVDA", action=action, price_at_rec=100.0, created=created)

    lookup = _lookup_from(
        {
            ("NVDA", horizon_date.date()): price_now,
            ("SPY", created.date()): 400.0,
            ("SPY", horizon_date.date()): bench_now,
        }
    )
    res = score_due_recommendations(store, price_lookup=lookup)
    assert res["scored"] == 1
    assert res["partial"] == 0

    row = store.get_scored_rows(30)[0]
    truth = reference_outcome(action, 100.0, price_now, 400.0, bench_now)

    assert row["return_pct"] == pytest.approx(truth["return_pct"], abs=0.01)
    assert row["benchmark_return_pct"] == pytest.approx(truth["benchmark_return_pct"], abs=0.01)
    assert row["excess_return_pct"] == pytest.approx(truth["excess_return_pct"], abs=0.01)
    assert row["hit"] is truth["hit"]
    assert row["benchmark_missing"] is False


# --------------------------------------------------------------------------- #
#  C — the aggregate cannot count an ungradable call as a win                  #
# --------------------------------------------------------------------------- #

def _mixed_rows():
    """Three BUYs: one real win, one real loss, one that could not be graded.

    The ungradable one is the shape the old scorer produced: a +18 % return with
    the market unknown. Read as a zero market it is the biggest win in the set.
    """
    return [
        {"action": "BUY", "hit": True, "return_pct": 10.0,
         "benchmark_return_pct": 4.0, "excess_return_pct": 6.0, "benchmark_missing": False},
        {"action": "BUY", "hit": False, "return_pct": 2.0,
         "benchmark_return_pct": 6.0, "excess_return_pct": -4.0, "benchmark_missing": False},
        {"action": "BUY", "hit": None, "return_pct": 18.0,
         "benchmark_return_pct": None, "excess_return_pct": None, "benchmark_missing": True},
    ]


def test_c_hit_rate_by_action_ignores_the_ungradable_row_entirely(store):
    rows = _mixed_rows()
    out = hit_rate_by_action(rows)["BUY"]

    assert out["hit_rate"] == pytest.approx(reference_hit_rate(rows), abs=0.001)
    assert out["hit_rate"] == pytest.approx(0.5, abs=0.001), "1 de 2 calificables, no 2 de 3"
    assert out["n"] == 2, "la fila sin benchmark no entra ni al numerador ni al denominador"


def test_c2_the_ungradable_row_does_not_inflate_the_mean_excess():
    rows = _mixed_rows()
    out = hit_rate_by_action(rows)["BUY"]

    assert out["mean_excess_pct"] == pytest.approx(reference_mean_excess(rows), abs=0.001)
    assert out["mean_excess_pct"] == pytest.approx(1.0, abs=0.001), "(6 + −4) / 2"
    assert out["n_excess"] == 2

    # The bug's signature: averaging the unknown as a zero drags the mean to 0.667.
    assert out["mean_excess_pct"] != pytest.approx(2 / 3, abs=0.001)


# --------------------------------------------------------------------------- #
#  D — an unknown excess is not a zero excess                                  #
# --------------------------------------------------------------------------- #

def test_d_summary_stats_averages_only_the_excesses_that_exist():
    rows = _mixed_rows()
    s = summary_stats(rows)

    assert s["n"] == 2, "recomendaciones calificables"
    assert s["n_excess"] == 2
    assert s["n_benchmark_missing"] == 1
    assert s["overall_hit_rate"] == pytest.approx(reference_hit_rate(rows), abs=0.001)
    assert s["mean_excess_pct"] == pytest.approx(reference_mean_excess(rows), abs=0.001)


def test_d2_summary_stats_reports_no_excess_rather_than_zero_excess():
    """Every row missing its benchmark: the honest answer is "—", not "+0.0 %"."""
    rows = [
        {"action": "BUY", "hit": None, "return_pct": 18.0,
         "benchmark_return_pct": None, "excess_return_pct": None, "benchmark_missing": True},
        {"action": "HOLD", "hit": True, "return_pct": 1.0,
         "benchmark_return_pct": None, "excess_return_pct": None, "benchmark_missing": True},
    ]
    s = summary_stats(rows)

    assert s["mean_excess_pct"] is None
    assert s["mean_excess_pct"] is not reference_mean_excess(rows) or reference_mean_excess(rows) is None
    assert s["n_excess"] == 0
    assert s["n_benchmark_missing"] == 2
    assert s["overall_hit_rate"] == pytest.approx(1.0, abs=0.001), "el HOLD sí es calificable"


def test_d3_calibration_by_confidence_does_not_average_an_unknown_as_zero():
    rows = [
        {"confidence": "HIGH", "hit": True, "excess_return_pct": 8.0, "benchmark_missing": False},
        {"confidence": "HIGH", "hit": False, "excess_return_pct": -2.0, "benchmark_missing": False},
        {"confidence": "HIGH", "hit": None, "excess_return_pct": None, "benchmark_missing": True},
    ]
    high = calibration_by_confidence(rows)["HIGH"]

    assert high["n"] == 2
    assert high["n_excess"] == 2
    assert high["hit_rate"] == pytest.approx(0.5, abs=0.001)
    assert high["mean_excess_pct"] == pytest.approx(3.0, abs=0.001), "(8 + −2) / 2, no /3"


# --------------------------------------------------------------------------- #
#  E — the equity curve cannot race a flat line                                #
# --------------------------------------------------------------------------- #

def test_e_equity_curve_drops_the_leg_it_cannot_compare():
    """A segment with no benchmark is not a segment where the benchmark did 0 %.

    Keeping it would let the model compound while its opponent stands still —
    the chart's whole claim ("vs SPY on the same stretches") stops being true.
    """
    now = utc_now()
    rows = [
        {"action": "BUY", "hit": True, "return_pct": 10.0, "benchmark_return_pct": 4.0,
         "excess_return_pct": 6.0, "benchmark_missing": False, "created_at": now - timedelta(days=3)},
        {"action": "BUY", "hit": None, "return_pct": 50.0, "benchmark_return_pct": None,
         "excess_return_pct": None, "benchmark_missing": True, "created_at": now - timedelta(days=2)},
        {"action": "BUY", "hit": False, "return_pct": 2.0, "benchmark_return_pct": 6.0,
         "excess_return_pct": -4.0, "benchmark_missing": False, "created_at": now - timedelta(days=1)},
    ]

    eq = equity_curve(rows)

    assert len(eq) == 2, "el tramo sin contraparte no se grafica"
    assert eq.iloc[-1]["model_equity"] == pytest.approx(1.10 * 1.02, abs=0.0001)
    assert eq.iloc[-1]["benchmark_equity"] == pytest.approx(1.04 * 1.06, abs=0.0001)
    # The bug's signature: +50 % compounded against a benchmark that stood still.
    assert eq.iloc[-1]["model_equity"] < 1.5


def test_e2_a_genuine_zero_percent_benchmark_is_still_plotted():
    """0.0 is a measurement; None is the absence of one. They must not share a path."""
    now = utc_now()
    rows = [
        {"action": "BUY", "hit": True, "return_pct": 10.0, "benchmark_return_pct": 0.0,
         "excess_return_pct": 10.0, "benchmark_missing": False, "created_at": now - timedelta(days=1)},
    ]
    eq = equity_curve(rows)

    assert len(eq) == 1
    assert eq.iloc[-1]["benchmark_equity"] == pytest.approx(1.0, abs=0.0001)


# --------------------------------------------------------------------------- #
#  F — a partial outcome stays pending and completes later                     #
# --------------------------------------------------------------------------- #

def test_f_a_partial_outcome_is_completed_by_a_later_run(store):
    """The benchmark lookup fails for transient reasons; the row must be retried.

    Persisting ``hit=None`` and walking away would freeze the recommendation as
    unscorable forever, because ``get_pending_scoring`` filters on the existence
    of an outcome row.
    """
    created = utc_now() - timedelta(days=40)
    horizon_date = created + timedelta(days=30)
    _log_due(store, symbol="NVDA", action="BUY", price_at_rec=100.0, created=created)

    prices = {("NVDA", horizon_date.date()): 110.0}

    first = score_due_recommendations(store, price_lookup=_lookup_from(prices))
    assert first["partial"] == 1
    assert store.get_scored_rows(30)[0]["benchmark_missing"] is True

    # SPY comes back.
    prices[("SPY", created.date())] = 400.0
    prices[("SPY", horizon_date.date())] = 448.0

    second = score_due_recommendations(store, price_lookup=_lookup_from(prices))
    assert second["scored"] == 1, "la fila parcial seguía pendiente"

    rows = store.get_scored_rows(30)
    assert len(rows) == 1, "se completa en el lugar, no se duplica"
    truth = reference_outcome("BUY", 100.0, 110.0, 400.0, 448.0)
    assert rows[0]["benchmark_missing"] is False
    assert rows[0]["excess_return_pct"] == pytest.approx(truth["excess_return_pct"], abs=0.01)
    assert rows[0]["hit"] is truth["hit"] is False, "+10 % contra un mercado de +12 % es perder"


def test_f2_a_completed_outcome_is_not_rescored(store):
    created = utc_now() - timedelta(days=40)
    horizon_date = created + timedelta(days=30)
    _log_due(store, symbol="NVDA", action="BUY", price_at_rec=100.0, created=created)

    lookup = _lookup_from(
        {
            ("NVDA", horizon_date.date()): 110.0,
            ("SPY", created.date()): 400.0,
            ("SPY", horizon_date.date()): 420.0,
        }
    )
    assert score_due_recommendations(store, price_lookup=lookup)["scored"] == 1
    again = score_due_recommendations(store, price_lookup=lookup)
    assert again["scored"] == 0 and again["partial"] == 0
    assert len(store.get_scored_rows(30)) == 1


# --------------------------------------------------------------------------- #
#  G — HOLD is graded against a band, not against the market                   #
# --------------------------------------------------------------------------- #

def test_g_hold_keeps_its_hit_without_a_benchmark(store):
    created = utc_now() - timedelta(days=40)
    horizon_date = created + timedelta(days=30)
    _log_due(store, symbol="KO", action="HOLD", price_at_rec=100.0, created=created)

    # +2 %: inside the hold band, and knowable without the market.
    score_due_recommendations(
        store, price_lookup=_lookup_from({("KO", horizon_date.date()): 102.0})
    )

    row = store.get_scored_rows(30)[0]
    truth = reference_outcome("HOLD", 100.0, 102.0, None, None)

    assert row["hit"] is truth["hit"] is True
    assert row["benchmark_missing"] is True
    assert row["excess_return_pct"] is None, "el hit es calificable; el exceso no"


def test_g2_compute_hit_refuses_only_the_rules_that_need_the_market():
    assert compute_hit("BUY", return_pct=10.0, excess_return_pct=None) is None
    assert compute_hit("STRONG BUY", return_pct=-4.0, excess_return_pct=None) is None
    assert compute_hit("SELL", return_pct=-5.0, excess_return_pct=None) is None
    assert compute_hit("REDUCE", return_pct=8.0, excess_return_pct=None) is None
    # HOLD's rule is |return| <= band — no market term in it.
    assert compute_hit("HOLD", return_pct=2.0, excess_return_pct=None) is True
    assert compute_hit("HOLD", return_pct=20.0, excess_return_pct=None) is False
