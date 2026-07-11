"""Tests for AlertEngine — mocked AlertStore to avoid SQLite dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock

import pytest

from alerts.engine import SCORE_CHANGE_THRESHOLD, AlertEngine
from alerts.store import AlertSeverity, AlertType

# ------------------------------------------------------------------ #
#  Fake AlertStore                                                     #
# ------------------------------------------------------------------ #

@dataclass
class _Snapshot:
    score: float
    signal: str
    moat_class: str


class FakeAlertStore:
    """In-memory store stub — no SQLite, no file system."""

    def __init__(self):
        self._snapshots: dict[str, _Snapshot] = {}
        self._cooldowns: set[str] = set()
        self._muted: set[tuple] = set()
        self.recorded: list[tuple] = []

    def get_snapshot(self, symbol: str) -> Optional[_Snapshot]:
        return self._snapshots.get(symbol)

    def save_snapshot(self, symbol: str, score: float, signal: str, moat_class: str):
        self._snapshots[symbol] = _Snapshot(score=score, signal=signal, moat_class=moat_class)

    def is_on_cooldown(self, alert_type: AlertType, symbol: str) -> bool:
        return f"{alert_type}:{symbol}" in self._cooldowns

    def set_cooldown(self, alert_type: AlertType, symbol: str):
        self._cooldowns.add(f"{alert_type}:{symbol}")

    def record(self, alert_type: AlertType, symbol: str, message: str,
               severity: AlertSeverity, explanation: str = ""):
        self.recorded.append((alert_type, symbol, message, severity))

    def is_muted(self, symbol: str, alert_type: str) -> bool:
        return (symbol, alert_type) in self._muted or ("*", alert_type) in self._muted

    def purge_expired_mutes(self) -> None:
        pass

    def seed(self, symbol: str, score: float, signal: str, moat_class: str = "Narrow"):
        """Pre-populate a snapshot as if a previous run already happened."""
        self._snapshots[symbol] = _Snapshot(score=score, signal=signal, moat_class=moat_class)


# ------------------------------------------------------------------ #
#  Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def store():
    return FakeAlertStore()


@pytest.fixture
def engine(store):
    from alerts.store import AlertSeverity
    eng = AlertEngine.__new__(AlertEngine)
    eng._store = store
    eng._notifier = MagicMock()
    eng._min_severity = AlertSeverity.INFO  # no profile filtering in tests
    return eng


# ------------------------------------------------------------------ #
#  Cold start                                                          #
# ------------------------------------------------------------------ #

class TestColdStart:
    def test_first_run_saves_baseline_no_alerts(self, engine, store, sample_ticker_data):
        fired = engine.run(sample_ticker_data)
        assert fired == []

    def test_baseline_saved_for_each_ticker(self, engine, store, sample_ticker_data):
        engine.run(sample_ticker_data)
        for ticker in sample_ticker_data:
            assert store.get_snapshot(ticker["symbol"]) is not None

    def test_second_run_without_change_fires_nothing(self, engine, store, sample_ticker_data):
        engine.run(sample_ticker_data)   # baseline
        fired = engine.run(sample_ticker_data)  # same data
        assert fired == []


# ------------------------------------------------------------------ #
#  Signal change                                                       #
# ------------------------------------------------------------------ #

class TestSignalChange:
    def test_signal_upgrade_fires_alert(self, engine, store):
        store.seed("AAPL", score=60.0, signal="HOLD")
        fired = engine.run([{"symbol": "AAPL", "adjusted_score": 65.0, "signal": "BUY",
                             "moat_classification": "Narrow", "company_name": "Apple"}])
        assert any(a.alert_type == AlertType.SIGNAL_CHANGE for a in fired)

    def test_signal_to_sell_is_critical(self, engine, store):
        store.seed("AAPL", score=65.0, signal="BUY")
        fired = engine.run([{"symbol": "AAPL", "adjusted_score": 35.0, "signal": "SELL",
                             "moat_classification": "Narrow", "company_name": "Apple"}])
        sell_alert = next(a for a in fired if a.alert_type == AlertType.SIGNAL_CHANGE)
        assert sell_alert.severity == AlertSeverity.CRITICAL

    def test_same_signal_no_alert(self, engine, store):
        store.seed("AAPL", score=72.0, signal="BUY")
        fired = engine.run([{"symbol": "AAPL", "adjusted_score": 74.0, "signal": "BUY",
                             "moat_classification": "Wide", "company_name": "Apple"}])
        assert not any(a.alert_type == AlertType.SIGNAL_CHANGE for a in fired)


# ------------------------------------------------------------------ #
#  Score drop                                                          #
# ------------------------------------------------------------------ #

class TestScoreDrop:
    def test_drop_above_threshold_fires(self, engine, store):
        prev = 75.0
        current = prev - SCORE_CHANGE_THRESHOLD - 1  # just over threshold
        store.seed("JPM", score=prev, signal="BUY")
        fired = engine.run([{"symbol": "JPM", "adjusted_score": current, "signal": "HOLD",
                             "moat_classification": "Narrow", "company_name": "JPMorgan"}])
        assert any(a.alert_type == AlertType.SCORE_DROP for a in fired)

    def test_drop_below_threshold_does_not_fire(self, engine, store):
        store.seed("JPM", score=75.0, signal="BUY")
        fired = engine.run([{"symbol": "JPM", "adjusted_score": 70.0, "signal": "BUY",
                             "moat_classification": "Narrow", "company_name": "JPMorgan"}])
        assert not any(a.alert_type == AlertType.SCORE_DROP for a in fired)

    def test_large_drop_is_critical(self, engine, store):
        store.seed("JPM", score=80.0, signal="BUY")
        fired = engine.run([{"symbol": "JPM", "adjusted_score": 60.0, "signal": "HOLD",
                             "moat_classification": "Narrow", "company_name": "JPMorgan"}])
        drop_alert = next((a for a in fired if a.alert_type == AlertType.SCORE_DROP), None)
        assert drop_alert is not None
        assert drop_alert.severity == AlertSeverity.CRITICAL


# ------------------------------------------------------------------ #
#  Score surge                                                         #
# ------------------------------------------------------------------ #

class TestScoreSurge:
    def test_surge_with_buy_signal_fires(self, engine, store):
        store.seed("MSFT", score=50.0, signal="HOLD")
        fired = engine.run([{"symbol": "MSFT", "adjusted_score": 65.0, "signal": "BUY",
                             "moat_classification": "Wide", "company_name": "Microsoft"}])
        assert any(a.alert_type == AlertType.SCORE_SURGE for a in fired)

    def test_surge_without_buy_signal_no_surge_alert(self, engine, store):
        store.seed("MSFT", score=50.0, signal="HOLD")
        fired = engine.run([{"symbol": "MSFT", "adjusted_score": 65.0, "signal": "HOLD",
                             "moat_classification": "Wide", "company_name": "Microsoft"}])
        assert not any(a.alert_type == AlertType.SCORE_SURGE for a in fired)


# ------------------------------------------------------------------ #
#  Opportunity                                                         #
# ------------------------------------------------------------------ #

class TestOpportunity:
    def test_new_buy_entry_fires_opportunity(self, engine, store):
        store.seed("XOM", score=55.0, signal="HOLD")
        fired = engine.run([{"symbol": "XOM", "adjusted_score": 72.0, "signal": "STRONG_BUY",
                             "moat_classification": "Narrow", "company_name": "ExxonMobil"}])
        assert any(a.alert_type == AlertType.OPPORTUNITY for a in fired)

    def test_staying_in_buy_no_opportunity_alert(self, engine, store):
        store.seed("XOM", score=70.0, signal="BUY")
        fired = engine.run([{"symbol": "XOM", "adjusted_score": 72.0, "signal": "BUY",
                             "moat_classification": "Narrow", "company_name": "ExxonMobil"}])
        assert not any(a.alert_type == AlertType.OPPORTUNITY for a in fired)


# ------------------------------------------------------------------ #
#  Moat downgrade                                                      #
# ------------------------------------------------------------------ #

class TestMoatDowngrade:
    def test_wide_to_narrow_fires_alert(self, engine, store):
        store.seed("AAPL", score=72.0, signal="BUY", moat_class="Wide")
        fired = engine.run([{"symbol": "AAPL", "adjusted_score": 70.0, "signal": "BUY",
                             "moat_classification": "Narrow", "company_name": "Apple"}])
        assert any(a.alert_type == AlertType.MOAT_CHANGE for a in fired)

    def test_upgrade_wide_to_wide_no_alert(self, engine, store):
        store.seed("AAPL", score=72.0, signal="BUY", moat_class="Narrow")
        fired = engine.run([{"symbol": "AAPL", "adjusted_score": 75.0, "signal": "STRONG_BUY",
                             "moat_classification": "Wide", "company_name": "Apple"}])
        assert not any(a.alert_type == AlertType.MOAT_CHANGE for a in fired)

    def test_same_moat_no_alert(self, engine, store):
        store.seed("AAPL", score=72.0, signal="BUY", moat_class="Wide")
        fired = engine.run([{"symbol": "AAPL", "adjusted_score": 73.0, "signal": "BUY",
                             "moat_classification": "Wide", "company_name": "Apple"}])
        assert not any(a.alert_type == AlertType.MOAT_CHANGE for a in fired)


# ------------------------------------------------------------------ #
#  Cooldown                                                            #
# ------------------------------------------------------------------ #

class TestCooldown:
    def test_cooldown_prevents_duplicate_score_drop(self, engine, store):
        store.seed("T", score=70.0, signal="BUY")
        ticker = {"symbol": "T", "adjusted_score": 55.0, "signal": "HOLD",
                  "moat_classification": "Narrow", "company_name": "AT&T"}

        engine.run([ticker])
        store.seed("T", score=70.0, signal="BUY")  # reset snapshot as if cooldown test
        # Manually put the cooldown in place
        store.set_cooldown(AlertType.SCORE_DROP, "T")

        fired2 = engine.run([{"symbol": "T", "adjusted_score": 55.0, "signal": "HOLD",
                               "moat_classification": "Narrow", "company_name": "AT&T"}])
        # Second run should not fire SCORE_DROP because cooldown is active
        assert not any(a.alert_type == AlertType.SCORE_DROP for a in fired2)


# ------------------------------------------------------------------ #
#  Snapshot updated after run                                          #
# ------------------------------------------------------------------ #

class TestSnapshotUpdate:
    def test_snapshot_updated_after_run(self, engine, store):
        store.seed("AAPL", score=72.0, signal="BUY", moat_class="Wide")
        engine.run([{"symbol": "AAPL", "adjusted_score": 80.0, "signal": "STRONG_BUY",
                     "moat_classification": "Wide", "company_name": "Apple"}])
        snap = store.get_snapshot("AAPL")
        assert abs(snap.score - 80.0) < 0.01
        assert snap.signal == "STRONG_BUY"

    def test_unknown_symbol_skipped(self, engine, store):
        fired = engine.run([{"symbol": "", "adjusted_score": 70.0, "signal": "BUY",
                              "moat_classification": "Wide", "company_name": "???"}])
        assert fired == []


# ------------------------------------------------------------------ #
#  Fase C — drift vs active retirement plan (PortfolioAlertDetector)   #
# ------------------------------------------------------------------ #

class TestPlanDrift:
    def _positions_and_prices(self):
        # 100% concentrated in AAPL, plan wants 40/60 AAPL/KO → big drift.
        positions = {
            "AAPL": {"shares": 10, "avg_cost": 100.0, "sector": "Tech"},
        }
        prices = {"AAPL": 100.0, "KO": 50.0}
        return positions, prices

    def test_target_weights_drives_drift_alert(self):
        from alerts.portfolio_alerts import PortfolioAlertDetector
        from alerts.store import AlertType

        positions, prices = self._positions_and_prices()
        detector = PortfolioAlertDetector()
        candidates = detector.run(
            positions, prices,
            target_weights={"AAPL": 40.0, "KO": 60.0},
            target_label="tu Plan de Retiro «Retiro 2045»",
        )
        types = {c.alert_type for c in candidates}
        assert AlertType.PORTFOLIO_DRIFT in types
        drift = next(c for c in candidates if c.alert_type == AlertType.PORTFOLIO_DRIFT)
        assert "Retiro 2045" in drift.message  # uses the plan label, not "optimizer"

    def test_optimizer_weights_still_works_as_alias(self):
        from alerts.portfolio_alerts import PortfolioAlertDetector
        from alerts.store import AlertType

        positions, prices = self._positions_and_prices()
        detector = PortfolioAlertDetector()
        # Legacy call path: optimizer_weights only.
        candidates = detector.run(positions, prices, optimizer_weights={"AAPL": 40.0, "KO": 60.0})
        assert AlertType.PORTFOLIO_DRIFT in {c.alert_type for c in candidates}

    def test_target_weights_takes_precedence_over_optimizer_weights(self):
        from alerts.portfolio_alerts import PortfolioAlertDetector
        from alerts.store import AlertType

        positions, prices = self._positions_and_prices()
        detector = PortfolioAlertDetector()
        # Plan says AAPL 100% (aligned with reality → no drift); optimizer alias
        # would have fired, but target_weights must win.
        candidates = detector.run(
            positions, prices,
            target_weights={"AAPL": 100.0},
            optimizer_weights={"AAPL": 40.0, "KO": 60.0},
        )
        assert AlertType.PORTFOLIO_DRIFT not in {c.alert_type for c in candidates}

    def test_no_weights_skips_drift(self):
        from alerts.portfolio_alerts import PortfolioAlertDetector
        from alerts.store import AlertType

        positions, prices = self._positions_and_prices()
        detector = PortfolioAlertDetector()
        candidates = detector.run(positions, prices)
        assert AlertType.PORTFOLIO_DRIFT not in {c.alert_type for c in candidates}
        assert AlertType.PORTFOLIO_REBALANCE not in {c.alert_type for c in candidates}


# ------------------------------------------------------------------ #
#  SORR_HIGH / GOAL_RISK (wired from plan MC summary via scheduler)    #
# ------------------------------------------------------------------ #

class TestSorrAndGoalRisk:
    def test_check_sorr_fires_above_threshold(self, engine, store):
        out = engine.check_sorr(
            sorr_early_drawdown_pct=45.0,
            horizon_years=20,
            initial_value=100_000,
        )
        assert out is not None
        assert out.alert_type == AlertType.SORR_HIGH
        assert out.severity == AlertSeverity.CRITICAL
        assert any(r[0] == AlertType.SORR_HIGH for r in store.recorded)

    def test_check_sorr_silent_below_threshold(self, engine, store):
        out = engine.check_sorr(
            sorr_early_drawdown_pct=10.0,
            horizon_years=20,
            initial_value=100_000,
        )
        assert out is None
        assert store.recorded == []

    def test_check_goal_risk_fires_on_drop(self, engine, store):
        out = engine.check_goal_risk(
            goal_name="Retiro 2045",
            prev_prob_pct=80.0,
            current_prob_pct=50.0,
            horizon_years=20,
        )
        assert out is not None
        assert out.alert_type == AlertType.GOAL_RISK
        assert "Retiro 2045" in out.message

    def test_check_goal_risk_silent_on_small_drop(self, engine, store):
        out = engine.check_goal_risk(
            goal_name="Casa",
            prev_prob_pct=70.0,
            current_prob_pct=65.0,
            horizon_years=5,
        )
        assert out is None

