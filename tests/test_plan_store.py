"""Tests for retirement-plan persistence (Fase B)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data.plan_store import PlanSnapshot, PlanStore, _slugify


def _fake_alloc(symbol, w, sector="Tech", div=1.0, score=80):
    return SimpleNamespace(
        symbol=symbol, weight_pct=w, sector=sector,
        dividend_yield_pct=div, adjusted_score=score,
    )


def _fake_opt_result():
    return SimpleNamespace(
        profile_name="Moderado",
        tickers=[_fake_alloc("AAPL", 40.0), _fake_alloc("KO", 60.0, "Staples", 3.2, 70)],
        expected_return_pct=8.5,
        volatility_pct=12.0,
        sharpe_ratio=0.55,
        dividend_yield_pct=2.4,
        adjusted_score_avg=75.0,
        moat_score_avg=14.0,
        max_drawdown_estimate_pct=18.0,
        sector_weights={"Tech": 40.0, "Staples": 60.0},
        profile_core_holdings=[{"symbol": "KO", "suggested_weight_pct": 60.0, "why": "income"}],
        grok_core_holdings=[],
        ai_grok_narrative="Cartera conservadora con foco en dividendos.",
    )


def _fake_prefs():
    return SimpleNamespace(
        is_onboarded=True, age=40, retirement_age=65, primary_horizon_years=25,
        current_capital=200_000, monthly_savings=1_500, primary_goal_type="retiro",
        profile_key="moderate",
    )


def test_slugify():
    assert _slugify("Retiro 2045!") == "retiro-2045"
    assert _slugify("   ") == "plan"


def test_from_session_builds_snapshot():
    snap = PlanSnapshot.from_session(
        name="Retiro 2045",
        opt_result=_fake_opt_result(),
        goals=[{"name": "Casa", "horizon_years": 5}],
        prefs=_fake_prefs(),
        universe_key="us_quality",
        universe_name="US Quality",
    )
    assert snap.id == "retiro-2045"
    assert snap.profile_name == "Moderado"
    assert snap.n_positions == 2
    assert snap.metrics["sharpe_ratio"] == 0.55
    assert snap.core_from_ai is False
    assert snap.core_holdings[0]["symbol"] == "KO"
    assert snap.personal["primary_horizon_years"] == 25
    assert snap.narrative.startswith("Cartera conservadora")
    assert {a["symbol"] for a in snap.allocation} == {"AAPL", "KO"}


def test_from_session_prefers_grok_core():
    opt = _fake_opt_result()
    opt.grok_core_holdings = [{"symbol": "AAPL", "suggested_weight_pct": 40.0, "why": "moat"}]
    snap = PlanSnapshot.from_session(name="x", opt_result=opt)
    assert snap.core_from_ai is True
    assert snap.core_holdings[0]["symbol"] == "AAPL"


def test_from_session_without_onboarded_prefs_has_no_personal():
    snap = PlanSnapshot.from_session(name="x", opt_result=_fake_opt_result())
    assert snap.personal is None


@pytest.fixture
def store(tmp_path):
    return PlanStore(path=tmp_path / "plans.json")


def test_upsert_get_list_delete_round_trip(store):
    snap = PlanSnapshot.from_session(name="Plan A", opt_result=_fake_opt_result(), prefs=_fake_prefs())
    store.upsert(snap)

    got = store.get(snap.id)
    assert got is not None
    assert got.name == "Plan A"
    assert got.n_positions == 2
    assert got.metrics["expected_return_pct"] == 8.5

    assert len(store.list()) == 1
    assert store.delete(snap.id) is True
    assert store.get(snap.id) is None
    assert store.delete("missing") is False


def test_upsert_replaces_same_id(store):
    s1 = PlanSnapshot.from_session(name="Mi Plan", opt_result=_fake_opt_result())
    store.upsert(s1)
    s2 = PlanSnapshot.from_session(
        name="Mi Plan", opt_result=_fake_opt_result(),
        existing_id=s1.id, existing_created_at=s1.created_at,
    )
    store.upsert(s2)
    plans = store.list()
    assert len(plans) == 1  # same id → replaced, not duplicated
    assert plans[0].created_at == s1.created_at


# ------------------------------------------------------------------ #
#  Fase C — living-plan fields                                         #
# ------------------------------------------------------------------ #

def test_new_fields_default_and_round_trip(store):
    """New optional Fase C fields default safely and survive save/load."""
    snap = PlanSnapshot.from_session(name="Plan C", opt_result=_fake_opt_result())
    assert snap.last_refreshed_at == ""
    assert snap.refreshed_metrics is None
    assert snap.macro_risks == []

    snap.last_refreshed_at = "2026-06-09T10:00:00"
    snap.macro_risks = [{"factor": "tasas", "impact": "alto"}]
    store.upsert(snap)

    got = store.get(snap.id)
    assert got.last_refreshed_at == "2026-06-09T10:00:00"
    assert got.macro_risks == [{"factor": "tasas", "impact": "alto"}]


def test_old_json_without_new_fields_loads(store):
    """A snapshot dict missing the Fase C keys still loads (backward-compat)."""
    legacy = PlanSnapshot.from_session(name="Legacy", opt_result=_fake_opt_result()).to_dict()
    legacy.pop("last_refreshed_at", None)
    legacy.pop("refreshed_metrics", None)
    legacy.pop("macro_risks", None)
    store._write_raw([legacy])
    got = store.get("legacy")
    assert got is not None
    assert got.macro_risks == []
    assert got.last_refreshed_at == ""


def test_superseded_and_missing_engine_versions_are_stale():
    """Every superseded tier is stale, and the literal is asserted on purpose.

    The assertion is here to make a bump a conscious act rather than a silent
    one: a change to the maths that forgets it leaves saved plans presenting
    numbers the engine no longer produces. U2-2 (tier1) moved the SORR figures
    the scheduler fires alerts off; U4-1/U4-2 (tier2) moved every projection
    that has contributions, and turned plans with no starting capital from a
    flat zero into real numbers. U5-9/U5-10 (tier5) moved μ: the moat's ROIC
    hurdle rose half a point when the risk-free rate stopped being declared
    twice, and a dividend yield between 15 % and 30 % stopped being scored and
    discarded at the same time — ABEV's μ goes from 7.65 % to 14.00 %. N5 (tier6)
    moved μ again and in both directions: eight tickers were scored on a dividend
    yield that was not theirs, because `rate / price` divides a local-currency
    dividend by a USD price on a LatAm ADR. ABEV's μ comes back down to 9.34 %.
    """
    from config import ENGINE_VERSION

    assert ENGINE_VERSION == "2026.08-tier6"

    current = PlanSnapshot.from_session(name="actual", opt_result=_fake_opt_result())
    assert current.engine_version == ENGINE_VERSION
    assert not current.is_engine_stale()

    for superseded in ("2026.08-tier0", "2026.08-tier1", "2026.08-tier2",
                       "2026.08-tier3", "2026.08-tier4", "2026.08-tier5"):
        old = PlanSnapshot.from_session(name="viejo", opt_result=_fake_opt_result())
        old.engine_version = superseded
        assert old.is_engine_stale() is True

    missing = PlanSnapshot(id="unsigned", name="unsigned", created_at="", updated_at="")
    assert missing.engine_version == ""
    assert missing.is_engine_stale() is True


def test_target_weights_from_allocation():
    snap = PlanSnapshot.from_session(name="x", opt_result=_fake_opt_result())
    tw = snap.target_weights()
    assert tw == {"AAPL": 40.0, "KO": 60.0}


def test_target_weights_falls_back_to_core():
    snap = PlanSnapshot(id="y", name="y", created_at="", updated_at="")
    snap.core_holdings = [{"symbol": "MSFT", "suggested_weight_pct": 55.0, "why": ""}]
    assert snap.target_weights() == {"MSFT": 55.0}


def test_price_lookup_captures_price_at_save():
    prices = {"AAPL": 200.0, "KO": 60.0}
    snap = PlanSnapshot.from_session(
        name="priced", opt_result=_fake_opt_result(),
        price_lookup=lambda s: prices.get(s),
    )
    by_sym = {a["symbol"]: a for a in snap.allocation}
    assert by_sym["AAPL"]["price_at_save"] == 200.0
    assert by_sym["KO"]["price_at_save"] == 60.0


def test_price_lookup_failure_is_tolerated():
    def _boom(_sym):
        raise RuntimeError("network down")

    snap = PlanSnapshot.from_session(
        name="nope", opt_result=_fake_opt_result(), price_lookup=_boom,
    )
    # No price captured, but the snapshot still builds.
    assert all("price_at_save" not in a for a in snap.allocation)


# ------------------------------------------------------------------ #
#  Economic drags persistence (Item 1)                               #
# ------------------------------------------------------------------ #

def _fake_mc_result(with_drags=False):
    base = dict(
        median_terminal=500_000.0, p10_terminal=200_000.0, p90_terminal=900_000.0,
        prob_achieve_target_pct=70.0, prob_ruin_pct=2.0, median_cagr_pct=6.5,
        sorr_early_drawdown_pct=22.5,
    )
    if with_drags:
        base.update(
            total_annual_drag_pct=1.25,
            base_median_terminal=560_000.0, base_p10_terminal=230_000.0,
            base_p90_terminal=980_000.0, base_prob_achieve_target_pct=74.0,
        )
    else:
        base.update(total_annual_drag_pct=0.0)
    return SimpleNamespace(**base)


def test_drags_captured_in_snapshot():
    drags = {"enabled": True, "annual_fee_pct": 0.2, "dividend_tax_drag_pct": 1.0,
             "rebalance_cost_annual_pct": 0.05, "ar_buffer_pct": 0.0,
             "total_annual_drag_pct": 1.25}
    snap = PlanSnapshot.from_session(
        name="con drags", opt_result=_fake_opt_result(),
        mc_result=_fake_mc_result(with_drags=True),
        mc_params={"horizon_years": 20, "initial_value": 100_000},
        drags=drags,
    )
    assert snap.drags_at_save == drags
    assert snap.mc_summary["total_annual_drag_pct"] == 1.25
    assert snap.mc_summary["base_median_terminal"] == 560_000.0
    assert snap.mc_summary["sorr_early_drawdown_pct"] == 22.5


def test_no_drags_leaves_snapshot_clean():
    snap = PlanSnapshot.from_session(
        name="sin drags", opt_result=_fake_opt_result(),
        mc_result=_fake_mc_result(with_drags=False),
        mc_params={"horizon_years": 20, "initial_value": 100_000},
        drags={"enabled": True, "total_annual_drag_pct": 0.0},
    )
    assert snap.drags_at_save is None
    assert "total_annual_drag_pct" not in snap.mc_summary


def test_drags_roundtrip_through_store(tmp_path):
    store = PlanStore(path=tmp_path / "plans.json")
    drags = {"enabled": True, "total_annual_drag_pct": 0.55,
             "annual_fee_pct": 0.5, "rebalance_cost_annual_pct": 0.05}
    snap = PlanSnapshot.from_session(
        name="roundtrip", opt_result=_fake_opt_result(),
        mc_result=_fake_mc_result(with_drags=True),
        mc_params={"horizon_years": 15, "initial_value": 50_000},
        drags=drags,
    )
    store.upsert(snap)
    loaded = store.get(snap.id)
    assert loaded is not None
    assert loaded.drags_at_save == drags
    assert loaded.export_version == "1.0"


# ------------------------------------------------------------------ #
#  Fase H.1 — withdrawal strategy persistence                          #
# ------------------------------------------------------------------ #

def _fake_mc_result_with_strategy():
    return SimpleNamespace(
        median_terminal=400_000.0, p10_terminal=50_000.0, p90_terminal=800_000.0,
        prob_achieve_target_pct=60.0, prob_ruin_pct=8.0, median_cagr_pct=5.0,
        total_annual_drag_pct=0.0,
        withdrawal_strategy_applied={"kind": "guardrails", "pct": 0.04, "label": "Guardrails 4.0%"},
        prob_sustain_real_pct=82.0, prob_legacy_pct=55.0, median_legacy=120_000.0,
        expected_depletion_year=27.5, longevity_years=30,
    )


def test_withdrawal_strategy_captured_in_snapshot():
    strat = {"kind": "guardrails", "pct": 0.04, "label": "Guardrails 4.0%"}
    snap = PlanSnapshot.from_session(
        name="con retiro", opt_result=_fake_opt_result(),
        mc_result=_fake_mc_result_with_strategy(),
        mc_params={"horizon_years": 30, "initial_value": 100_000},
        withdrawal_strategy=strat,
    )
    assert snap.withdrawal_strategy == strat
    assert snap.mc_summary["prob_sustain_real_pct"] == 82.0
    assert snap.mc_summary["longevity_years"] == 30


def test_withdrawal_strategy_falls_back_to_mc_result():
    """If no explicit strategy is passed but the MC result carries one, use it."""
    snap = PlanSnapshot.from_session(
        name="auto", opt_result=_fake_opt_result(),
        mc_result=_fake_mc_result_with_strategy(),
        mc_params={"horizon_years": 30, "initial_value": 100_000},
    )
    assert snap.withdrawal_strategy["kind"] == "guardrails"


def test_no_strategy_leaves_snapshot_clean():
    snap = PlanSnapshot.from_session(
        name="acumulacion", opt_result=_fake_opt_result(),
        mc_result=_fake_mc_result(with_drags=False),
        mc_params={"horizon_years": 20, "initial_value": 100_000},
    )
    assert snap.withdrawal_strategy is None
    assert "prob_sustain_real_pct" not in snap.mc_summary


def test_withdrawal_strategy_roundtrip_through_store(tmp_path):
    store = PlanStore(path=tmp_path / "plans.json")
    snap = PlanSnapshot.from_session(
        name="rt retiro", opt_result=_fake_opt_result(),
        mc_result=_fake_mc_result_with_strategy(),
        mc_params={"horizon_years": 30, "initial_value": 100_000},
        withdrawal_strategy={"kind": "constant_pct", "pct": 0.045},
    )
    store.upsert(snap)
    loaded = store.get(snap.id)
    assert loaded is not None
    assert loaded.withdrawal_strategy == {"kind": "constant_pct", "pct": 0.045}
    assert loaded.mc_summary["prob_sustain_real_pct"] == 82.0


def test_legacy_snapshot_without_withdrawal_field_loads(tmp_path):
    """A pre-H.1 plan JSON (no withdrawal_strategy key) must still load."""
    store = PlanStore(path=tmp_path / "plans.json")
    snap = PlanSnapshot.from_session(name="viejo", opt_result=_fake_opt_result())
    raw = snap.to_dict()
    raw.pop("withdrawal_strategy", None)
    store._write_raw([raw])
    loaded = store.get(snap.id)
    assert loaded is not None
    assert loaded.withdrawal_strategy is None


# ------------------------------------------------------------------ #
#  unique_plan_id — non-destructive import (audit bug 5)              #
# ------------------------------------------------------------------ #

class TestUniquePlanId:
    """Plan ids are name slugs, and ``upsert`` replaces by id.

    That is fine when saving (the page warns first), but importing a backup from
    another machine could silently destroy a homonymous local plan. This is the
    helper that lets the import offer a copy instead.
    """

    def test_free_id_is_returned_unchanged(self):
        from data.plan_store import unique_plan_id

        assert unique_plan_id("retiro-2045", lambda _pid: False) == "retiro-2045"

    def test_taken_id_gets_a_numeric_suffix(self):
        from data.plan_store import unique_plan_id

        taken = {"retiro-2045"}
        assert unique_plan_id("retiro-2045", lambda pid: pid in taken) == "retiro-2045-2"

    def test_suffix_walks_until_free(self):
        from data.plan_store import unique_plan_id

        taken = {"retiro-2045", "retiro-2045-2", "retiro-2045-3"}
        assert unique_plan_id("retiro-2045", lambda pid: pid in taken) == "retiro-2045-4"

    def test_unrelated_ids_do_not_push_the_suffix(self):
        from data.plan_store import unique_plan_id

        taken = {"otro-plan", "retiro-2046"}
        assert unique_plan_id("retiro-2045", lambda pid: pid in taken) == "retiro-2045"

    def test_empty_base_falls_back_like_slugify(self):
        from data.plan_store import unique_plan_id

        assert unique_plan_id("", lambda _pid: False) == "plan"

    def test_against_a_real_store_the_copy_keeps_both_plans(self, store):
        """The end state the import flow must reach: two plans, none destroyed."""
        from dataclasses import replace

        from data.plan_store import unique_plan_id

        local = PlanSnapshot(id="retiro-2045", name="Retiro 2045",
                             created_at="", updated_at="", n_positions=3)
        store.upsert(local)

        incoming = PlanSnapshot(id="retiro-2045", name="Retiro 2045",
                                created_at="", updated_at="", n_positions=9)
        copy_id = unique_plan_id(incoming.id, lambda pid: store.get(pid) is not None)
        store.upsert(replace(incoming, id=copy_id, name=f"{incoming.name} (copia)"))

        assert {p.id for p in store.list()} == {"retiro-2045", "retiro-2045-2"}
        assert store.get("retiro-2045").n_positions == 3   # untouched
        assert store.get("retiro-2045-2").n_positions == 9
