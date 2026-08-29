"""Plan drift is unknown when the plan is not fully priced (backlog U5-14).

U2-3 established the rule for the alert detector, in its own words:

    "it refuses to run at all when any tracked position has no usable price: an
    unpriced position is *unknown*, not 0 %, and treating it as 0 deflates the
    total and inflates every other weight."

``compute_plan_vs_reality`` — the other path, the one feeding
``PLAN_HEALTH_DEGRADATION`` — never got that gate. It divides the weighted price
move by ``weighted_delta_den``, the sum of the weights **it managed to price**, so
the covered part of the plan is silently rescaled to 100 %.

The direction is what makes it serious. On a four-position plan where a 10 %
holding falls 40 % and cannot be priced:

    real drift, everything priced        +1.20 %
    renormalised to the 90 % covered     +5.78 %

The crash does not merely go missing — the number moves the **reassuring** way,
and it is a health metric. A plan is reported as drifting less at exactly the
moment part of it stopped being trackable.

``drift_breakdown`` already says a missing price is the caller's job to exclude
("Symbols priced as *unknown* must be left out entirely"). One caller did the job
and the other did not.

No network: prices are injected.
"""

from __future__ import annotations

import pytest

from data.plan_context import compute_plan_vs_reality
from data.plan_store import PlanSnapshot


def _snapshot() -> PlanSnapshot:
    snap = PlanSnapshot(id="p1", name="Plan", created_at="", updated_at="")
    # ``price_at_save`` lives on each allocation row, not in a separate map.
    snap.allocation = [
        {"symbol": "AAPL", "weight_pct": 40.0, "adjusted_score": 80.0, "price_at_save": 100.0},
        {"symbol": "KO", "weight_pct": 30.0, "adjusted_score": 75.0, "price_at_save": 100.0},
        {"symbol": "O", "weight_pct": 20.0, "adjusted_score": 70.0, "price_at_save": 100.0},
        {"symbol": "XYZ", "weight_pct": 10.0, "adjusted_score": 60.0, "price_at_save": 100.0},
    ]
    return snap


#: Today's prices. XYZ has collapsed 40 % and is the one that cannot be quoted.
FULL = {"AAPL": 112.0, "KO": 102.0, "O": 99.0, "XYZ": 60.0}


def _lookup(prices):
    return lambda sym: prices.get(sym)


def oracle_weighted_move(weights, moves) -> float:
    """Reference: the plan's move is each holding's move at its plan weight."""
    return sum(weights[s] * moves[s] for s in weights) / sum(weights.values())


class TestFullCoverageIsUnchanged:
    def test_it_matches_the_reference(self):
        out = compute_plan_vs_reality(_snapshot(), _lookup(FULL))
        expected = oracle_weighted_move(
            {"AAPL": 40.0, "KO": 30.0, "O": 20.0, "XYZ": 10.0},
            {"AAPL": 12.0, "KO": 2.0, "O": -1.0, "XYZ": -40.0},
        )
        assert out["summary"]["weighted_delta_pct"] == pytest.approx(expected, abs=0.05)

    def test_the_rows_still_carry_every_symbol(self):
        out = compute_plan_vs_reality(_snapshot(), _lookup(FULL))
        assert len(out["rows"]) == 4


class TestAGapMakesTheDriftUnknown:
    def _gap(self):
        partial = {k: v for k, v in FULL.items() if k != "XYZ"}
        return compute_plan_vs_reality(_snapshot(), _lookup(partial))

    def test_the_drift_is_not_reported_at_all(self):
        """U2-3's rule, applied to the other caller: unknown, not rescaled."""
        assert self._gap()["summary"]["weighted_delta_pct"] is None

    def test_it_is_not_quietly_rescaled_to_the_covered_part(self):
        """The renormalised answer would be +5.78 %, and reassuring."""
        assert self._gap()["summary"]["weighted_delta_pct"] != pytest.approx(5.78, abs=0.1)

    def test_the_coverage_gap_is_reported_rather_than_hidden(self):
        summary = self._gap()["summary"]
        assert summary["n_priced"] == 3
        assert summary["n_total"] == 4
        assert summary.get("unpriced") == ["XYZ"]

    def test_the_rows_still_show_what_could_not_be_priced(self):
        """Suppressing the aggregate must not suppress the evidence."""
        rows = {r["symbol"]: r for r in self._gap()["rows"]}
        assert rows["XYZ"]["price_now"] is None
        assert rows["AAPL"]["delta_pct"] == pytest.approx(12.0, abs=0.1)


class TestTheHealthRecordCarriesTheGap:
    def test_a_record_without_drift_is_skipped_by_the_trend(self):
        """``compute_longitudinal_drift`` already filters ``None`` — verify it."""
        from data.plan_context import compute_longitudinal_drift

        history = [
            {"recorded_at": "2026-01-01", "weighted_delta_pct": 3.0, "data_quality_pct": 100.0},
            {"recorded_at": "2026-02-01", "weighted_delta_pct": None, "data_quality_pct": 75.0},
        ]
        out = compute_longitudinal_drift(history)
        assert out["max_drift_pct"] == pytest.approx(3.0)
        assert out["latest_drift_pct"] is None

    def test_a_plan_that_cannot_be_priced_is_not_flagged_as_degraded(self):
        """Anti-cheat: absence of evidence must not become evidence of decay."""
        from data.plan_context import compute_longitudinal_drift

        history = [
            {"recorded_at": f"2026-0{i}-01", "weighted_delta_pct": None,
             "data_quality_pct": 50.0}
            for i in range(1, 5)
        ]
        assert compute_longitudinal_drift(history)["degraded"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
