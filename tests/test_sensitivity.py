"""Tests for the sensitivity & scenario lab (Fase H.3).

Uses a deterministic fake ``run_fn`` so the engine is exercised fully offline
(no Monte Carlo, no network). The fake encodes the expected directional
relationships (more inflation/drags/vol → worse; more return → better).
"""

from __future__ import annotations

from types import SimpleNamespace

from config import SENSITIVITY
from portfolio.sensitivity import (
    METRIC_KEYS,
    SensitivityResult,
    run_sensitivity,
    tornado_rows,
)


def _fake_run(params: dict):
    """Deterministic, monotone surrogate for a MonteCarloResult."""
    infl = float(params.get("withdrawal_growth_rate", 0.0) or 0.0)
    drag = float(params.get("drags_total_pct", 0.0) or 0.0)
    rs = float(params.get("return_scale", 1.0) or 1.0)
    vs = float(params.get("vol_scale", 1.0) or 1.0)
    h = float(params.get("horizon_years", 20) or 20)

    median = 500_000.0 * rs - infl * 1_000_000.0 - drag * 50_000.0 + (h - 20) * 5_000.0
    p10 = median - vs * 100_000.0
    p90 = median + vs * 100_000.0
    ruin = max(0.0, 10.0 + infl * 100.0 + drag * 5.0 - (rs - 1.0) * 50.0 + (vs - 1.0) * 40.0)
    return SimpleNamespace(
        p10_terminal=p10, median_terminal=median, p90_terminal=p90, prob_ruin_pct=ruin
    )


def _base():
    return {
        "withdrawal_growth_rate": 0.03,
        "drags_total_pct": 0.25,
        "return_scale": 1.0,
        "vol_scale": 1.0,
        "horizon_years": 20,
        "longevity_years": 20,
    }


# ------------------------------------------------------------------ #
#  Structure / base                                                    #
# ------------------------------------------------------------------ #

class TestStructure:
    def test_returns_result_with_base_and_four_factors(self):
        res = run_sensitivity(_fake_run, _base())
        assert isinstance(res, SensitivityResult)
        assert set(res.base.keys()) == set(METRIC_KEYS)
        assert len(res.factors) == 4
        assert len(res.scenarios) == 4

    def test_base_params_not_mutated(self):
        base = _base()
        snapshot = dict(base)
        run_sensitivity(_fake_run, base)
        assert base == snapshot

    def test_base_metrics_match_direct_run(self):
        res = run_sensitivity(_fake_run, _base())
        direct = _fake_run(_base())
        assert res.base["median_terminal"] == direct.median_terminal


# ------------------------------------------------------------------ #
#  Factor directionality                                               #
# ------------------------------------------------------------------ #

class TestFactors:
    def _factor(self, res, key):
        return next(f for f in res.factors if f.key == key)

    def test_more_fees_lowers_terminal(self):
        res = run_sensitivity(_fake_run, _base())
        fees = self._factor(res, "fees")
        # high = more drag = lower median
        assert fees.high["median_terminal"] < fees.low["median_terminal"]

    def test_higher_return_raises_terminal(self):
        res = run_sensitivity(_fake_run, _base())
        rr = self._factor(res, "real_return")
        assert rr.high["median_terminal"] > rr.low["median_terminal"]

    def test_higher_inflation_raises_ruin(self):
        res = run_sensitivity(_fake_run, _base())
        infl = self._factor(res, "inflation")
        assert infl.high["prob_ruin_pct"] > infl.low["prob_ruin_pct"]

    def test_fee_floor_never_negative(self):
        # Base drag 0.1 with delta 0.30 → low would be -0.20, must floor at 0.
        base = _base()
        base["drags_total_pct"] = 0.1
        res = run_sensitivity(_fake_run, base)
        fees = self._factor(res, "fees")
        # At the floor (drag=0) the terminal is the highest possible for this factor.
        assert fees.low["median_terminal"] == _fake_run({**base, "drags_total_pct": 0.0}).median_terminal


# ------------------------------------------------------------------ #
#  Tornado ordering                                                    #
# ------------------------------------------------------------------ #

class TestTornado:
    def test_rows_sorted_by_swing_desc(self):
        res = run_sensitivity(_fake_run, _base())
        rows = tornado_rows(res)
        swings = [r["swing"] for r in rows]
        assert swings == sorted(swings, reverse=True)
        assert len(rows) == 4

    def test_rows_carry_base_and_labels(self):
        res = run_sensitivity(_fake_run, _base())
        row = tornado_rows(res, metric="median_terminal")[0]
        assert "base" in row and row["base"] == res.base["median_terminal"]
        assert row["low_label"] and row["high_label"]


# ------------------------------------------------------------------ #
#  Scenarios                                                           #
# ------------------------------------------------------------------ #

class TestScenarios:
    def _scn(self, res, key):
        return next(s for s in res.scenarios if s.key == key)

    def test_full_drags_scenario_lowers_terminal(self):
        res = run_sensitivity(_fake_run, _base())
        sc = self._scn(res, "drags_full")
        assert sc.deltas["median_terminal"] < 0
        assert sc.metrics["median_terminal"] < res.base["median_terminal"]

    def test_adverse_market_lowers_p10(self):
        res = run_sensitivity(_fake_run, _base())
        sc = self._scn(res, "adverse_market")
        assert sc.deltas["p10_terminal"] < 0

    def test_live_longer_changes_outcome(self):
        res = run_sensitivity(_fake_run, _base())
        sc = self._scn(res, "live_longer")
        # Horizon +5 in the surrogate raises terminal; delta is non-zero either way.
        assert sc.deltas["median_terminal"] != 0

    def test_can_disable_scenarios(self):
        res = run_sensitivity(_fake_run, _base(), include_scenarios=False)
        assert res.scenarios == []


# ------------------------------------------------------------------ #
#  Config wiring                                                       #
# ------------------------------------------------------------------ #

def test_uses_config_magnitudes():
    # Verify the inflation factor moves by exactly SENSITIVITY.inflation_delta_pct.
    res = run_sensitivity(_fake_run, _base())
    infl = next(f for f in res.factors if f.key == "inflation")
    base = _base()
    expected_high = _fake_run(
        {**base, "withdrawal_growth_rate": 0.03 + SENSITIVITY.inflation_delta_pct / 100.0}
    ).median_terminal
    assert infl.high["median_terminal"] == expected_high
