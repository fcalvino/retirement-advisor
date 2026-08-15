"""Tests for scripts/run_scheduler.py (audit D4).

The scheduler runs unattended. Everything it does is wrapped in
``try/except Exception``, so a bug here does not crash — it silently stops
sending the alerts the user is relying on. That combination (no tests + broad
excepts + no human watching) is why this file needed coverage most.

Every collaborator is stubbed: no network, no SMTP, no Telegram, no real store.
The tests assert on *decisions* — did drift get measured against the active
plan, did the SORR alert fire, did the GOAL baseline seed before firing — not on
log output.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.run_scheduler as sched  # noqa: E402

# ------------------------------------------------------------------ #
#  Doubles                                                             #
# ------------------------------------------------------------------ #

class _Plan:
    def __init__(self, name="Retiro 2045", mc_summary=None, weights=None, refreshed=None):
        self.id = "retiro-2045"
        self.name = name
        self.mc_summary = mc_summary
        self.refreshed_metrics = refreshed
        self._weights = weights if weights is not None else {"AAPL": 60.0, "KO": 40.0}

    def target_weights(self):
        return dict(self._weights)


class _Snapshot:
    def __init__(self, score):
        self.score = score


class _Store:
    def __init__(self, snapshots=None):
        self.snapshots = dict(snapshots or {})
        self.saved = []

    def get_snapshot(self, symbol):
        return self.snapshots.get(symbol)

    def save_snapshot(self, symbol, score, kind, note):
        self.snapshots[symbol] = _Snapshot(score)
        self.saved.append((symbol, score))


class _Engine:
    """Records which checks fired instead of dispatching notifications."""

    def __init__(self, fire=()):
        self._fire = set(fire)
        self._store = _Store()
        self.calls = {}

    def _record(self, _check, **kw):
        self.calls[_check] = kw
        return object() if _check in self._fire else None

    def run(self, scored):
        self.calls["run"] = {"scored": scored}
        return []

    def run_with_portfolio(self, scored, positions, prices, target_weights=None, target_label=""):
        self.calls["run_with_portfolio"] = {
            "positions": positions, "prices": prices,
            "target_weights": target_weights, "target_label": target_label,
        }
        return []

    def check_sorr(self, sorr, horizon, initial):
        return self._record("check_sorr", sorr=sorr, horizon=horizon, initial=initial)

    def check_goal_risk(self, name, prev, current, horizon):
        return self._record("check_goal_risk", name=name, prev=prev, current=current)

    def check_plan_health_degradation(self, name, drift):
        return self._record("check_plan_health_degradation", name=name, drift=drift)

    def check_market_drop_coach(self, portfolio_return_pct, plan_name, plan_prob_target_pct):
        return self._record(
            "check_market_drop_coach",
            portfolio_return_pct=portfolio_return_pct,
            plan_name=plan_name, prob=plan_prob_target_pct,
        )


@pytest.fixture
def stub_plan_context(monkeypatch):
    """Install a fake data.plan_context; the scheduler imports it lazily."""
    mod = types.ModuleType("data.plan_context")
    mod.get_active_plan = lambda: None
    mod.record_plan_health = lambda *a, **k: None
    mod.get_plan_health_history = lambda pid: []
    mod.compute_longitudinal_drift = lambda hist: {}
    monkeypatch.setitem(sys.modules, "data.plan_context", mod)
    return mod


@pytest.fixture
def stub_fetcher(monkeypatch):
    mod = types.ModuleType("data.fetcher")
    mod.get_info = lambda sym: {"currentPrice": 100.0}
    monkeypatch.setitem(sys.modules, "data.fetcher", mod)
    return mod


# ------------------------------------------------------------------ #
#  Drift inputs — "did we measure against the plan the user activated?" #
# ------------------------------------------------------------------ #

class TestActivePlanDriftInputs:
    def test_none_without_an_active_plan(self, stub_plan_context, stub_fetcher):
        assert sched._active_plan_drift_inputs() is None

    def test_none_when_nothing_is_tracked(self, monkeypatch, stub_plan_context, stub_fetcher):
        stub_plan_context.get_active_plan = lambda: _Plan()
        mod = types.ModuleType("portfolio.tracker")
        mod.Portfolio = lambda: types.SimpleNamespace(positions={})
        monkeypatch.setitem(sys.modules, "portfolio.tracker", mod)
        assert sched._active_plan_drift_inputs() is None

    def test_none_when_the_plan_has_no_target_weights(self, monkeypatch, stub_plan_context, stub_fetcher):
        stub_plan_context.get_active_plan = lambda: _Plan(weights={})
        self._install_tracker(monkeypatch)
        assert sched._active_plan_drift_inputs() is None

    @staticmethod
    def _install_tracker(monkeypatch):
        pos = types.SimpleNamespace(shares=10.0, avg_cost=150.0, sector="Technology")
        mod = types.ModuleType("portfolio.tracker")
        mod.Portfolio = lambda: types.SimpleNamespace(positions={"AAPL": pos})
        monkeypatch.setitem(sys.modules, "portfolio.tracker", mod)

    def test_returns_positions_prices_and_the_plan_label(self, monkeypatch, stub_plan_context, stub_fetcher):
        stub_plan_context.get_active_plan = lambda: _Plan(name="FIRE 2040")
        self._install_tracker(monkeypatch)

        positions, prices, weights, label = sched._active_plan_drift_inputs()
        assert positions["AAPL"]["shares"] == 10.0
        assert positions["AAPL"]["sector"] == "Technology"
        assert prices["AAPL"] == 100.0
        assert weights == {"AAPL": 60.0, "KO": 40.0}
        # The label is user-facing: it must name the plan, not "the optimizer".
        assert "FIRE 2040" in label

    def test_a_failing_price_lookup_does_not_lose_the_whole_check(
        self, monkeypatch, stub_plan_context, stub_fetcher
    ):
        stub_plan_context.get_active_plan = lambda: _Plan()
        self._install_tracker(monkeypatch)

        def boom(sym):
            raise RuntimeError("yfinance down")
        stub_fetcher.get_info = boom

        positions, prices, weights, _label = sched._active_plan_drift_inputs()
        assert positions                      # positions survive
        assert prices == {}                   # only the quote is missing
        assert weights


# ------------------------------------------------------------------ #
#  Alert check wiring                                                  #
# ------------------------------------------------------------------ #

class TestJobAlertCheck:
    @pytest.fixture(autouse=True)
    def _quiet(self, monkeypatch, stub_plan_context, stub_fetcher):
        monkeypatch.setattr(sched, "_check_plan_health", lambda e: None)
        monkeypatch.setattr(sched, "_check_plan_mc_alerts", lambda e: None)
        monkeypatch.setattr(sched, "_check_market_drop_coach", lambda e, d: None)

    def test_skips_everything_when_the_screener_returns_nothing(self, monkeypatch):
        engine = _Engine()
        monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [])
        monkeypatch.setattr(sched, "AlertEngine", lambda: engine)
        sched.job_alert_check()
        assert engine.calls == {}

    def test_uses_the_plain_run_without_an_active_plan(self, monkeypatch):
        engine = _Engine()
        monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [{"symbol": "AAPL"}])
        monkeypatch.setattr(sched, "AlertEngine", lambda: engine)
        monkeypatch.setattr(sched, "_active_plan_drift_inputs", lambda: None)
        sched.job_alert_check()
        assert "run" in engine.calls
        assert "run_with_portfolio" not in engine.calls

    def test_measures_drift_against_the_plan_when_one_is_active(self, monkeypatch):
        engine = _Engine()
        monkeypatch.setattr(sched, "_run_screener_for_alerts", lambda: [{"symbol": "AAPL"}])
        monkeypatch.setattr(sched, "AlertEngine", lambda: engine)
        monkeypatch.setattr(
            sched, "_active_plan_drift_inputs",
            lambda: ({"AAPL": {"shares": 1}}, {"AAPL": 100.0}, {"AAPL": 100.0}, "tu plan «X»"),
        )
        sched.job_alert_check()
        assert engine.calls["run_with_portfolio"]["target_weights"] == {"AAPL": 100.0}
        assert "run" not in engine.calls

    def test_a_screener_explosion_is_contained(self, monkeypatch):
        def boom():
            raise RuntimeError("universe fetch failed")
        monkeypatch.setattr(sched, "_run_screener_for_alerts", boom)
        sched.job_alert_check()          # must not propagate out of the cron job


# ------------------------------------------------------------------ #
#  Monte-Carlo derived alerts                                          #
# ------------------------------------------------------------------ #

class TestPlanMcAlerts:
    def test_no_op_without_an_active_plan(self, stub_plan_context):
        engine = _Engine()
        sched._check_plan_mc_alerts(engine)
        assert engine.calls == {}

    def test_no_op_when_the_plan_never_ran_a_simulation(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan(mc_summary={})
        engine = _Engine()
        sched._check_plan_mc_alerts(engine)
        assert engine.calls == {}

    def test_sorr_is_read_from_the_saved_summary(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan(mc_summary={
            "sorr_early_drawdown_pct": 42.0, "horizon_years": 30, "initial_value": 250_000.0,
        })
        engine = _Engine(fire={"check_sorr"})
        sched._check_plan_mc_alerts(engine)
        assert engine.calls["check_sorr"] == {
            "sorr": 42.0, "horizon": 30, "initial": 250_000.0,
        }

    def test_a_non_numeric_sorr_is_skipped_without_killing_the_goal_check(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan(mc_summary={
            "sorr_early_drawdown_pct": "n/a", "prob_target_pct": 70.0,
        })
        engine = _Engine()
        sched._check_plan_mc_alerts(engine)
        assert engine._store.saved == [("GOAL:Retiro 2045", 70.0)]

    def test_first_run_seeds_the_goal_baseline_instead_of_firing(self, stub_plan_context):
        """With nothing to compare against, an alert would be noise."""
        stub_plan_context.get_active_plan = lambda: _Plan(mc_summary={"prob_target_pct": 80.0})
        engine = _Engine(fire={"check_goal_risk"})
        sched._check_plan_mc_alerts(engine)
        assert "check_goal_risk" not in engine.calls
        assert engine._store.saved == [("GOAL:Retiro 2045", 80.0)]

    def test_second_run_compares_against_the_stored_baseline(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan(mc_summary={
            "prob_target_pct": 55.0, "horizon_years": 25,
        })
        engine = _Engine(fire={"check_goal_risk"})
        engine._store.snapshots["GOAL:Retiro 2045"] = _Snapshot(80.0)
        sched._check_plan_mc_alerts(engine)
        assert engine.calls["check_goal_risk"]["prev"] == 80.0
        assert engine.calls["check_goal_risk"]["current"] == 55.0

    def test_the_baseline_is_refreshed_after_comparing(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan(mc_summary={"prob_target_pct": 55.0})
        engine = _Engine()
        engine._store.snapshots["GOAL:Retiro 2045"] = _Snapshot(80.0)
        sched._check_plan_mc_alerts(engine)
        assert engine._store.snapshots["GOAL:Retiro 2045"].score == 55.0


# ------------------------------------------------------------------ #
#  Plan health                                                         #
# ------------------------------------------------------------------ #

class TestPlanHealth:
    def test_disabled_config_short_circuits(self, monkeypatch, stub_plan_context):
        import config
        monkeypatch.setattr(config.HEALTH, "enabled", False)
        engine = _Engine()
        sched._check_plan_health(engine)
        assert engine.calls == {}

    def test_no_op_without_an_active_plan(self, monkeypatch, stub_plan_context, stub_fetcher):
        import config
        monkeypatch.setattr(config.HEALTH, "enabled", True)
        engine = _Engine()
        sched._check_plan_health(engine)
        assert engine.calls == {}

    def test_auto_record_off_still_evaluates_existing_history(
        self, monkeypatch, stub_plan_context, stub_fetcher
    ):
        """Recording is opt-in; a trend already on disk must still be able to fire."""
        import config
        monkeypatch.setattr(config.HEALTH, "enabled", True)
        monkeypatch.setattr(config.HEALTH, "auto_record", False)

        recorded = []
        stub_plan_context.get_active_plan = lambda: _Plan()
        stub_plan_context.record_plan_health = lambda *a, **k: recorded.append(a)
        stub_plan_context.compute_longitudinal_drift = lambda hist: {"drift_pct": -20.0}

        engine = _Engine(fire={"check_plan_health_degradation"})
        sched._check_plan_health(engine)

        assert recorded == []
        assert engine.calls["check_plan_health_degradation"]["drift"] == {"drift_pct": -20.0}

    def test_auto_record_on_writes_a_snapshot(self, monkeypatch, stub_plan_context, stub_fetcher):
        import config
        monkeypatch.setattr(config.HEALTH, "enabled", True)
        monkeypatch.setattr(config.HEALTH, "auto_record", True)

        recorded = []
        stub_plan_context.get_active_plan = lambda: _Plan()
        stub_plan_context.record_plan_health = lambda *a, **k: recorded.append(k.get("source"))

        sched._check_plan_health(_Engine())
        assert recorded == ["scheduler"]


# ------------------------------------------------------------------ #
#  Market-drop coach                                                   #
# ------------------------------------------------------------------ #

class TestMarketDropCoach:
    def test_silent_without_a_plan_or_positions(self, stub_plan_context):
        engine = _Engine()
        sched._check_market_drop_coach(engine, None)
        assert engine.calls == {}

    def test_return_is_computed_from_cost_versus_market_value(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan(mc_summary={"prob_target_pct": 65.0})
        drift = (
            {"AAPL": {"shares": 10, "avg_cost": 200.0}},   # cost 2000
            {"AAPL": 150.0},                               # value 1500
            {}, "label",
        )
        engine = _Engine(fire={"check_market_drop_coach"})
        sched._check_market_drop_coach(engine, drift)
        assert engine.calls["check_market_drop_coach"]["portfolio_return_pct"] == pytest.approx(-25.0)
        assert engine.calls["check_market_drop_coach"]["prob"] == 65.0

    def test_falls_back_to_the_plans_weighted_delta(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan(
            refreshed={"summary": {"weighted_delta_pct": -18.5}}
        )
        engine = _Engine()
        sched._check_market_drop_coach(engine, None)
        assert engine.calls["check_market_drop_coach"]["portfolio_return_pct"] == pytest.approx(-18.5)

    def test_a_zero_cost_book_is_skipped_rather_than_dividing_by_zero(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan()
        drift = ({"X": {"shares": 0, "avg_cost": 0.0}}, {"X": 10.0}, {}, "l")
        engine = _Engine()
        sched._check_market_drop_coach(engine, drift)
        assert engine.calls == {}

    def test_unparseable_position_values_are_ignored(self, stub_plan_context):
        stub_plan_context.get_active_plan = lambda: _Plan()
        drift = (
            {"BAD": {"shares": "x", "avg_cost": None}, "OK": {"shares": 1, "avg_cost": 100.0}},
            {"OK": 80.0}, {}, "l",
        )
        engine = _Engine(fire={"check_market_drop_coach"})
        sched._check_market_drop_coach(engine, drift)
        assert engine.calls["check_market_drop_coach"]["portfolio_return_pct"] == pytest.approx(-20.0)


# ------------------------------------------------------------------ #
#  Screener adapter                                                    #
# ------------------------------------------------------------------ #

class TestScreenerAdapter:
    def test_one_bad_ticker_does_not_abort_the_run(self, monkeypatch):
        import analysis.strategy as strategy_mod

        def fake_full_analysis(sym, ai_config=None):
            if sym == "BOOM":
                raise RuntimeError("data source blew up")
            fund = types.SimpleNamespace(
                company_name=f"{sym} Inc", adjusted_score=70.0, total_score=65.0,
                moat_bonus=5.0, moat_classification="Wide", moat_score=10.0,
                dividend_yield=1.5, sector="Technology",
            )
            return fund, None, types.SimpleNamespace(action="BUY")

        monkeypatch.setattr(strategy_mod, "full_analysis", fake_full_analysis)
        monkeypatch.setattr(sched, "DEFAULT_TICKERS", ["AAPL", "BOOM", "KO"])

        scored = sched._run_screener_for_alerts()
        assert [s["symbol"] for s in scored] == ["AAPL", "KO"]
        assert scored[0]["signal"] == "BUY"
        assert scored[0]["moat_classification"] == "Wide"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
