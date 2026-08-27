"""Oracle tests for portfolio drift (PORTFOLIO_DRIFT / PORTFOLIO_REBALANCE).

Backlog row U2-3 (oleada 2 · P0 · técnico · fuente P2)
-----------------------------------------------------
  hallazgo : Deriva agregada ignora holdings fuera del target; anidada bajo
             P&L; precio missing = 0.
  evidencia: portfolio_alerts vs compute_alignment_trades.
  fix      : Unión target ∪ actual; no exigir avg_cost; missing price != 0.
  oráculo  : posición 20 % off-plan mueve total_drift.

Why this file exists
--------------------
``PortfolioAlertDetector.run`` had three defects that all pointed the same way
— they made the mail quieter or louder than the screen:

1. The aggregate looped ``for sym, target_pct in weights.items()``, i.e. **only
   the plan's own symbols**. A position held entirely outside the plan (DOGE at
   20 % of the book) contributed exactly ``0`` to ``total_drift``. The Portfolio
   page, which iterates the union, said "rebalanceá"; the alert never fired.

2. ``PORTFOLIO_DRIFT`` lived *inside* the P&L loop, behind
   ``if avg_cost <= 0 or shares <= 0 or current_price <= 0: continue``. So a
   position with no cost basis loaded never drifted, and a symbol the plan asks
   for but that is not held at all was unreachable — it is not in ``positions``.

3. A missing quote became ``0.0``, which is not "worth nothing", it is
   "unknown". The position then read as 0 % of the portfolio (a false drift
   against its own target) while the shrunken ``total_value`` inflated every
   other weight.

The reference used here is an **independently written, deliberately slow drift
accumulator** derived from the definition (sum of absolute deviations over the
union, halved because every deviation is counted twice), not the engine's own
``drift_breakdown`` (``docs/CONTEXT.md §5``: engine tests are oracles, not
self-consistency checks).

Pure Python — no network, no Streamlit, no SQLite.
"""

from __future__ import annotations

import zlib
from typing import Dict, List

import pytest

from alerts.portfolio_alerts import PortfolioAlertDetector
from alerts.store import AlertSeverity, AlertType
from config import ALERTS
from data.plan_context import compute_alignment_trades, drift_breakdown
from data.plan_store import PlanSnapshot

# ------------------------------------------------------------------ #
#  Independent reference implementation                                #
# ------------------------------------------------------------------ #

def oracle_total_drift(target: Dict[str, float], actual: Dict[str, float]) -> float:
    """Aggregate drift between a target allocation and a real one.

    Straight off the definition, as a slow loop: every symbol that appears on
    *either* side is a symbol the portfolio can be wrong about — one missing
    from the plan is an unwanted holding, one missing from the book is an
    unfilled instruction. Sum the absolute deviations and halve, because a
    percentage point that is over on one symbol is under on another and would
    otherwise be charged twice.
    """
    names: List[str] = []
    for name in list(target.keys()) + list(actual.keys()):
        if name not in names:
            names.append(name)

    accumulated = 0.0
    for name in names:
        wanted = float(target.get(name, 0.0))
        have = float(actual.get(name, 0.0))
        deviation = have - wanted
        if deviation < 0:
            deviation = -deviation
        accumulated += deviation
    return accumulated / 2.0


def _weights_from_values(values: Dict[str, float]) -> Dict[str, float]:
    """USD values -> percent weights (the detector's own inputs, restated)."""
    total = sum(values.values())
    return {sym: v / total * 100.0 for sym, v in values.items()}


def _pseudo_random_weights(tag: str, symbols: List[str]) -> Dict[str, float]:
    """Deterministic pseudo-random allocation summing to 100.

    ``zlib.crc32`` rather than ``hash()``: the latter is salted per process and
    would make a failure impossible to reproduce (``docs/CONTEXT.md §5``).
    """
    raw = {s: 1 + zlib.crc32(f"{tag}:{s}".encode()) % 1000 for s in symbols}
    total = sum(raw.values())
    return {s: v / total * 100.0 for s, v in raw.items()}


def _drift_candidates(candidates) -> Dict[str, object]:
    return {c.symbol: c for c in candidates if c.alert_type == AlertType.PORTFOLIO_DRIFT}


def _rebalance(candidates):
    hits = [c for c in candidates if c.alert_type == AlertType.PORTFOLIO_REBALANCE]
    return hits[0] if hits else None


# ------------------------------------------------------------------ #
#  O1 — the row's own oracle: an off-plan position moves total_drift   #
# ------------------------------------------------------------------ #

class TestOffPlanPositionMovesTotalDrift:
    """AAPL 40 / KO 40 / DOGE 20, plan wants AAPL 50 / KO 50.

    DOGE is not in the plan at all. The old aggregate looped the plan's keys
    only, so it scored (|40-50| + |40-50|) / 2 = 10 % — half the truth — and a
    fifth of the capital sitting entirely off-plan was invisible to it.
    """

    TARGET = {"AAPL": 50.0, "KO": 50.0}
    # 40 sh @ $10 = $400 | 80 sh @ $5 = $400 | 200 sh @ $1 = $200  -> 40/40/20
    POSITIONS = {
        "AAPL": {"shares": 40, "sector": "Technology"},
        "KO": {"shares": 80, "sector": "Consumer Defensive"},
        "DOGE": {"shares": 200, "sector": "Crypto"},
    }
    PRICES = {"AAPL": 10.0, "KO": 5.0, "DOGE": 1.0}

    def test_oracle_counts_the_off_plan_position(self):
        actual = _weights_from_values({"AAPL": 400.0, "KO": 400.0, "DOGE": 200.0})
        assert oracle_total_drift(self.TARGET, actual) == pytest.approx(20.0)
        # And what the plan-only loop used to produce, for contrast:
        plan_only = sum(
            abs(actual.get(s, 0.0) - t) for s, t in self.TARGET.items()
        ) / 2.0
        assert plan_only == pytest.approx(10.0)

    def test_engine_matches_the_oracle(self):
        actual = _weights_from_values({"AAPL": 400.0, "KO": 400.0, "DOGE": 200.0})
        assert drift_breakdown(self.TARGET, actual)["total_drift_pct"] == pytest.approx(
            oracle_total_drift(self.TARGET, actual)
        )

    def test_detector_reports_the_full_drift(self):
        candidates = PortfolioAlertDetector().run(
            self.POSITIONS, self.PRICES, target_weights=self.TARGET,
        )
        reb = _rebalance(candidates)
        assert reb is not None, "20 % off-plan must trigger PORTFOLIO_REBALANCE"
        assert reb.context["total_drift_pct"] == "20.0%"
        assert float(reb.context["total_drift_pct"].rstrip("%")) > (
            ALERTS.portfolio_rebalance_threshold_pct
        )

    def test_the_off_plan_symbol_gets_its_own_drift_alert(self):
        candidates = PortfolioAlertDetector().run(
            self.POSITIONS, self.PRICES, target_weights=self.TARGET,
        )
        drifts = _drift_candidates(candidates)
        assert "DOGE" in drifts
        assert drifts["DOGE"].context["target_weight_pct"] == "0.0%"
        assert drifts["DOGE"].context["current_weight_pct"] == "20.0%"


# ------------------------------------------------------------------ #
#  O2 — a target symbol at 0 % real can alert                          #
# ------------------------------------------------------------------ #

def test_plan_symbol_with_no_position_can_alert():
    """KO is 30 % of the plan and simply is not held.

    Unreachable before U2-3: the drift check iterated ``positions``, and KO is
    not a position. "You own none of what your plan asks for" is exactly the
    case the alert exists for.
    """
    candidates = PortfolioAlertDetector().run(
        {"AAPL": {"shares": 10, "sector": "Technology"}},
        {"AAPL": 100.0},
        target_weights={"AAPL": 70.0, "KO": 30.0},
        target_label="tu Plan de Retiro «Retiro 2045»",
    )
    drifts = _drift_candidates(candidates)
    assert "KO" in drifts
    ko = drifts["KO"]
    assert ko.context["current_weight_pct"] == "0.0%"
    assert ko.context["target_weight_pct"] == "30.0%"
    assert ko.context["drift_pct"] == "30.0%"
    assert "no tenés posición" in ko.message
    assert "Retiro 2045" in ko.message


# ------------------------------------------------------------------ #
#  O3 — a missing price is unknown, not zero                           #
# ------------------------------------------------------------------ #

class TestMissingPriceIsNotZero:
    TARGET = {"AAPL": 50.0, "KO": 50.0}
    POSITIONS = {
        "AAPL": {"shares": 10, "avg_cost": 100.0, "sector": "Technology"},
        "KO": {"shares": 100, "avg_cost": 50.0, "sector": "Consumer Defensive"},
    }

    @pytest.mark.parametrize(
        "prices",
        [
            pytest.param({"AAPL": 100.0}, id="key-absent"),
            pytest.param({"AAPL": 100.0, "KO": 0.0}, id="zero-quote"),
            pytest.param({"AAPL": 100.0, "KO": None}, id="none-quote"),
        ],
    )
    def test_no_drift_claim_without_full_price_coverage(self, prices):
        candidates = PortfolioAlertDetector().run(
            self.POSITIONS, prices, target_weights=self.TARGET,
        )
        types = {c.alert_type for c in candidates}
        assert AlertType.PORTFOLIO_DRIFT not in types
        assert AlertType.PORTFOLIO_REBALANCE not in types

    def test_the_priced_position_is_not_reported_at_100_pct(self):
        """The old code valued KO at 0, so AAPL read as 100 % of the book."""
        candidates = PortfolioAlertDetector().run(
            self.POSITIONS, {"AAPL": 100.0}, target_weights=self.TARGET,
        )
        assert not any(
            c.alert_type == AlertType.PORTFOLIO_DRIFT and "100.0%" in c.message
            for c in candidates
        )

    def test_pnl_still_evaluated_for_the_priced_position(self):
        """The gate is about weights only — a real loss must still be reported."""
        candidates = PortfolioAlertDetector().run(
            self.POSITIONS, {"AAPL": 50.0}, target_weights=self.TARGET,  # -50 %
        )
        losses = [c for c in candidates if c.alert_type == AlertType.PORTFOLIO_LOSS]
        assert [c.symbol for c in losses] == ["AAPL"]
        assert losses[0].severity == AlertSeverity.CRITICAL

    def test_full_coverage_restores_the_drift_check(self):
        candidates = PortfolioAlertDetector().run(
            self.POSITIONS, {"AAPL": 100.0, "KO": 50.0}, target_weights=self.TARGET,
        )
        # $1 000 AAPL vs $5 000 KO -> 16.7 / 83.3 against a 50/50 plan.
        reb = _rebalance(candidates)
        assert reb is not None
        assert reb.context["total_drift_pct"] == "33.3%"

    def test_a_zero_share_position_is_not_a_coverage_gap(self):
        """Nothing held means nothing to price — it must not gate the run."""
        positions = dict(self.POSITIONS)
        positions["MSFT"] = {"shares": 0, "avg_cost": 0.0, "sector": "Technology"}
        candidates = PortfolioAlertDetector().run(
            positions, {"AAPL": 100.0, "KO": 50.0}, target_weights=self.TARGET,
        )
        assert _rebalance(candidates) is not None


# ------------------------------------------------------------------ #
#  O4 — drift never requires avg_cost                                  #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "cost_basis",
    [
        pytest.param({}, id="avg_cost-absent"),
        pytest.param({"avg_cost": 0.0}, id="avg_cost-zero"),
        pytest.param({"avg_cost": None}, id="avg_cost-none"),
    ],
)
def test_drift_does_not_require_a_cost_basis(cost_basis):
    """Drift is a statement about weights; what you paid is a different alert."""
    positions = {
        "AAPL": {"shares": 90, "sector": "Technology", **cost_basis},
        "KO": {"shares": 10, "sector": "Consumer Defensive", **cost_basis},
    }
    candidates = PortfolioAlertDetector().run(
        positions, {"AAPL": 1.0, "KO": 1.0},  # 90 / 10 against a 50/50 plan
        target_weights={"AAPL": 50.0, "KO": 50.0},
    )
    assert _rebalance(candidates) is not None
    assert set(_drift_candidates(candidates)) == {"AAPL", "KO"}
    # ...and no P&L alert was invented out of a missing cost basis.
    assert not any(c.alert_type == AlertType.PORTFOLIO_LOSS for c in candidates)


# ------------------------------------------------------------------ #
#  O5 — engine vs. the independent accumulator, over many shapes       #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize(
    "target_syms, actual_syms",
    [
        (["AAPL", "KO", "MSFT"], ["AAPL", "KO", "MSFT"]),          # identical sets
        (["AAPL", "KO", "MSFT"], ["AAPL", "KO", "MSFT", "DOGE"]),  # extra holding
        (["AAPL", "KO", "MSFT", "JNJ"], ["AAPL", "KO"]),           # unfilled plan
        (["AAPL"], ["DOGE", "GME"]),                               # disjoint
        (["AAPL", "KO"], []),                                      # nothing held
        ([], ["AAPL", "KO"]),                                      # no plan
    ],
)
def test_engine_matches_the_slow_reference(target_syms, actual_syms):
    target = _pseudo_random_weights("target", target_syms) if target_syms else {}
    actual = _pseudo_random_weights("actual", actual_syms) if actual_syms else {}
    assert drift_breakdown(target, actual)["total_drift_pct"] == pytest.approx(
        oracle_total_drift(target, actual)
    )


def test_breakdown_rows_cover_the_union_and_carry_signed_drift():
    bd = drift_breakdown({"AAPL": 60.0, "KO": 40.0}, {"AAPL": 80.0, "DOGE": 20.0})
    assert bd["symbols"] == ["AAPL", "DOGE", "KO"]
    assert bd["n_evaluated"] == 3
    by_sym = {r["symbol"]: r for r in bd["rows"]}
    assert by_sym["AAPL"]["drift_pct"] == pytest.approx(20.0)    # over the target
    assert by_sym["KO"]["drift_pct"] == pytest.approx(-40.0)     # under the target
    assert by_sym["DOGE"]["drift_pct"] == pytest.approx(20.0)    # off-plan holding


# ------------------------------------------------------------------ #
#  O6 — the two surfaces can no longer disagree                        #
# ------------------------------------------------------------------ #

def test_detector_and_alignment_trades_report_the_same_drift():
    """`portfolio_alerts` vs `compute_alignment_trades` is the row's evidence."""
    target = {"AAPL": 50.0, "KO": 50.0}
    snap = PlanSnapshot(
        id="p", name="p", created_at="", updated_at="",
        allocation=[{"symbol": s, "weight_pct": w} for s, w in target.items()],
    )
    positions = {
        "AAPL": {"shares": 40, "sector": "Technology"},
        "KO": {"shares": 80, "sector": "Consumer Defensive"},
        "DOGE": {"shares": 200, "sector": "Crypto"},
    }
    prices = {"AAPL": 10.0, "KO": 5.0, "DOGE": 1.0}
    actual = _weights_from_values({"AAPL": 400.0, "KO": 400.0, "DOGE": 200.0})

    reb = _rebalance(PortfolioAlertDetector().run(positions, prices, target_weights=target))
    trades = compute_alignment_trades(snap, actual, total_value=1_000.0)

    assert reb is not None
    detector_drift = float(reb.context["total_drift_pct"].rstrip("%"))
    assert detector_drift == pytest.approx(trades["summary"]["total_drift_pct"])
    assert detector_drift == pytest.approx(oracle_total_drift(target, actual))


# ------------------------------------------------------------------ #
#  O7 — PORTFOLIO_LOSS survived being un-nested                        #
# ------------------------------------------------------------------ #

class TestLossIsUnchanged:
    POSITIONS = {"AAPL": {"shares": 10, "avg_cost": 100.0, "sector": "Technology"}}

    def test_warning_band(self):
        drop = ALERTS.portfolio_loss_threshold_pct * 1.2
        candidates = PortfolioAlertDetector().run(
            self.POSITIONS, {"AAPL": 100.0 * (1 - drop / 100)},
        )
        loss = [c for c in candidates if c.alert_type == AlertType.PORTFOLIO_LOSS][0]
        assert loss.severity == AlertSeverity.WARNING
        assert set(loss.context) == {
            "pnl_pct", "current_price", "avg_cost", "shares", "sector",
        }
        assert loss.context["shares"] == "10.00"
        assert loss.context["avg_cost"] == "$100.00"
        assert "posición en pérdida" in loss.message

    def test_critical_band(self):
        drop = ALERTS.portfolio_loss_threshold_pct * 1.6
        candidates = PortfolioAlertDetector().run(
            self.POSITIONS, {"AAPL": 100.0 * (1 - drop / 100)},
        )
        loss = [c for c in candidates if c.alert_type == AlertType.PORTFOLIO_LOSS][0]
        assert loss.severity == AlertSeverity.CRITICAL

    def test_silent_above_threshold(self):
        candidates = PortfolioAlertDetector().run(self.POSITIONS, {"AAPL": 99.0})
        assert not [c for c in candidates if c.alert_type == AlertType.PORTFOLIO_LOSS]
