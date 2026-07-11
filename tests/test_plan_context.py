"""Tests for the living-plan context bridge (Fase C)."""

from __future__ import annotations

import pytest

import data.plan_context as pc
from data.plan_context import (
    activate_plan,
    compute_alignment_trades,
    compute_plan_vs_reality,
    deactivate_plan,
    get_active_plan,
    is_active,
)
from data.plan_store import PlanSnapshot, PlanStore

# ------------------------------------------------------------------ #
#  Fakes                                                              #
# ------------------------------------------------------------------ #

class FakePrefs:
    """Minimal stand-in for UserPreferences (no disk)."""

    def __init__(self, active_plan_id: str = ""):
        self.active_plan_id = active_plan_id
        self.saves = 0

    def set_active_plan(self, plan_id: str) -> None:
        self.active_plan_id = (plan_id or "").strip()
        self.saves += 1

    def clear_active_plan(self) -> None:
        self.active_plan_id = ""
        self.saves += 1


def _snap(plan_id="retiro-2045", name="Retiro 2045"):
    return PlanSnapshot(
        id=plan_id, name=name, created_at="", updated_at="",
        allocation=[
            {"symbol": "AAPL", "weight_pct": 40.0, "adjusted_score": 82.0, "price_at_save": 100.0},
            {"symbol": "KO", "weight_pct": 60.0, "adjusted_score": 70.0, "price_at_save": 50.0},
        ],
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = PlanStore(path=tmp_path / "plans.json")
    monkeypatch.setattr(pc, "plan_store", s)
    return s


# ------------------------------------------------------------------ #
#  Activate / deactivate / resolve                                    #
# ------------------------------------------------------------------ #

def test_activate_unknown_plan_returns_false(store):
    prefs = FakePrefs()
    assert activate_plan("does-not-exist", prefs) is False
    assert prefs.active_plan_id == ""


def test_activate_and_get_active_plan(store):
    store.upsert(_snap())
    prefs = FakePrefs()

    assert activate_plan("retiro-2045", prefs) is True
    assert prefs.active_plan_id == "retiro-2045"
    assert is_active("retiro-2045", prefs) is True

    got = get_active_plan(prefs)
    assert got is not None
    assert got.name == "Retiro 2045"


def test_deactivate(store):
    store.upsert(_snap())
    prefs = FakePrefs(active_plan_id="retiro-2045")
    deactivate_plan(prefs)
    assert prefs.active_plan_id == ""
    assert get_active_plan(prefs) is None


def test_get_active_plan_self_heals_stale_id(store):
    """If the active plan was deleted, the stale id is cleared."""
    prefs = FakePrefs(active_plan_id="ghost")
    assert get_active_plan(prefs) is None
    assert prefs.active_plan_id == ""  # self-healed


# ------------------------------------------------------------------ #
#  compute_plan_vs_reality                                            #
# ------------------------------------------------------------------ #

def test_compute_plan_vs_reality_deltas():
    snap = _snap()
    # AAPL 100 -> 120 (+20%), KO 50 -> 45 (-10%)
    prices = {"AAPL": 120.0, "KO": 45.0}
    health = compute_plan_vs_reality(snap, lambda s: prices.get(s))

    rows = {r["symbol"]: r for r in health["rows"]}
    assert rows["AAPL"]["delta_pct"] == 20.0
    assert rows["KO"]["delta_pct"] == -10.0

    s = health["summary"]
    # weighted: (40*20 + 60*-10) / 100 = (800 - 600)/100 = 2.0
    assert s["weighted_delta_pct"] == 2.0
    assert s["n_priced"] == 2
    assert s["n_with_baseline"] == 2
    assert s["gainers"] == 1
    assert s["losers"] == 1


def test_compute_plan_vs_reality_missing_baseline():
    """Allocation entries without price_at_save yield delta None but still price."""
    snap = PlanSnapshot(
        id="p", name="p", created_at="", updated_at="",
        allocation=[{"symbol": "AAPL", "weight_pct": 100.0, "adjusted_score": 80.0}],
    )
    health = compute_plan_vs_reality(snap, lambda s: 150.0)
    row = health["rows"][0]
    assert row["price_now"] == 150.0
    assert row["price_then"] is None
    assert row["delta_pct"] is None
    assert health["summary"]["weighted_delta_pct"] is None
    assert health["summary"]["n_priced"] == 1


def test_compute_plan_vs_reality_tolerates_lookup_errors():
    snap = _snap()

    def _flaky(sym):
        if sym == "AAPL":
            raise RuntimeError("boom")
        return 55.0

    health = compute_plan_vs_reality(snap, _flaky)
    rows = {r["symbol"]: r for r in health["rows"]}
    assert rows["AAPL"]["price_now"] is None
    assert rows["KO"]["price_now"] == 55.0
    assert health["summary"]["n_priced"] == 1


def test_compute_plan_vs_reality_core_only():
    snap = _snap()
    snap.core_holdings = [{"symbol": "AAPL", "suggested_weight_pct": 100.0, "why": ""}]
    health = compute_plan_vs_reality(snap, lambda s: 100.0, core_only=True)
    assert [r["symbol"] for r in health["rows"]] == ["AAPL"]


# ------------------------------------------------------------------ #
#  compute_alignment_trades (Fase E)                                  #
# ------------------------------------------------------------------ #

def _trades_snap():
    """Target: AAPL 40 / KO 30 / MSFT 30. Core: AAPL, MSFT."""
    return PlanSnapshot(
        id="p", name="p", created_at="", updated_at="",
        allocation=[
            {"symbol": "AAPL", "weight_pct": 40.0},
            {"symbol": "KO", "weight_pct": 30.0},
            {"symbol": "MSFT", "weight_pct": 30.0},
        ],
        core_holdings=[
            {"symbol": "AAPL", "suggested_weight_pct": 50.0, "why": ""},
            {"symbol": "MSFT", "suggested_weight_pct": 50.0, "why": ""},
        ],
    )


def test_alignment_trades_buy_and_sell_amounts():
    snap = _trades_snap()
    # AAPL under by 20pp -> comprar; KO over by 20pp -> vender; MSFT aligned.
    current = {"AAPL": 20.0, "KO": 50.0, "MSFT": 30.0}
    out = compute_alignment_trades(
        snap, current, total_value=100_000,
        drift_threshold_pct=5.0, min_trade_usd=100.0, max_trades=10,
    )
    by_sym = {t["symbol"]: t for t in out["trades"]}
    assert by_sym["AAPL"]["action"] == "comprar"
    assert by_sym["AAPL"]["amount_usd"] == 20_000
    assert by_sym["KO"]["action"] == "vender"
    assert by_sym["KO"]["amount_usd"] == 20_000
    assert "MSFT" not in by_sym
    assert out["summary"]["total_drift_pct"] == 20.0
    assert out["summary"]["buy_usd"] == 20_000
    assert out["summary"]["sell_usd"] == 20_000


def test_alignment_trades_below_threshold_is_empty():
    snap = _trades_snap()
    current = {"AAPL": 38.0, "KO": 32.0, "MSFT": 30.0}  # max drift 2pp
    out = compute_alignment_trades(
        snap, current, total_value=100_000,
        drift_threshold_pct=5.0, min_trade_usd=100.0, max_trades=10,
    )
    assert out["trades"] == []
    assert out["summary"]["n_suggested"] == 0


def test_alignment_trades_core_first_priority():
    snap = _trades_snap()
    # KO (non-core) drifts MORE than MSFT (core) — core must still come first.
    current = {"AAPL": 40.0, "KO": 45.0, "MSFT": 15.0}
    out = compute_alignment_trades(
        snap, current, total_value=100_000,
        drift_threshold_pct=5.0, min_trade_usd=100.0, max_trades=10,
    )
    assert [t["symbol"] for t in out["trades"]] == ["MSFT", "KO"]
    assert out["trades"][0]["is_core"] is True


def test_alignment_trades_min_trade_usd_filters_noise():
    snap = _trades_snap()
    current = {"AAPL": 20.0, "KO": 50.0, "MSFT": 30.0}
    # 20pp of a small account = $200 < min_trade_usd
    out = compute_alignment_trades(
        snap, current, total_value=1_000,
        drift_threshold_pct=5.0, min_trade_usd=500.0, max_trades=10,
    )
    assert out["trades"] == []
    assert out["summary"]["n_skipped_small"] == 2


def test_alignment_trades_max_trades_cap():
    snap = _trades_snap()
    current = {"AAPL": 10.0, "KO": 60.0, "MSFT": 10.0, "TSLA": 20.0}
    out = compute_alignment_trades(
        snap, current, total_value=100_000,
        drift_threshold_pct=5.0, min_trade_usd=100.0, max_trades=2,
    )
    assert len(out["trades"]) == 2
    # Core trades win the capped slots.
    assert all(t["is_core"] for t in out["trades"])


def test_alignment_trades_position_not_in_plan_is_sell():
    snap = _trades_snap()
    current = {"AAPL": 40.0, "KO": 30.0, "MSFT": 10.0, "DOGE": 20.0}
    out = compute_alignment_trades(
        snap, current, total_value=50_000,
        drift_threshold_pct=5.0, min_trade_usd=100.0, max_trades=10,
    )
    by_sym = {t["symbol"]: t for t in out["trades"]}
    assert by_sym["DOGE"]["action"] == "vender"
    assert by_sym["DOGE"]["target_pct"] == 0.0
    assert by_sym["MSFT"]["action"] == "comprar"


def test_alignment_trades_price_lookup_adds_shares_and_tolerates_errors():
    snap = _trades_snap()
    current = {"AAPL": 20.0, "KO": 50.0, "MSFT": 30.0}

    def _prices(sym):
        if sym == "KO":
            raise RuntimeError("boom")
        return 100.0

    out = compute_alignment_trades(
        snap, current, total_value=100_000, price_lookup=_prices,
        drift_threshold_pct=5.0, min_trade_usd=100.0, max_trades=10,
    )
    by_sym = {t["symbol"]: t for t in out["trades"]}
    assert by_sym["AAPL"]["est_shares"] == 200.0      # $20k / $100
    assert by_sym["KO"]["est_shares"] is None         # lookup failed gracefully


def test_alignment_trades_defaults_come_from_config():
    from config import ALERTS
    snap = _trades_snap()
    out = compute_alignment_trades(snap, {"AAPL": 40.0, "KO": 30.0, "MSFT": 30.0}, 100_000)
    assert out["summary"]["threshold_pct"] == ALERTS.portfolio_drift_threshold_pct
    assert out["summary"]["min_trade_usd"] == ALERTS.alignment_min_trade_usd


# ------------------------------------------------------------------ #
#  Plan portability — import helper (Item 2)                          #
# ------------------------------------------------------------------ #

from data.plan_context import import_plan_from_dict


def test_import_from_bare_snapshot_dict():
    snap = _snap()
    restored = import_plan_from_dict(snap.to_dict())
    assert restored.id == snap.id
    assert restored.name == snap.name
    assert restored.target_weights() == snap.target_weights()


def test_import_from_wrapped_bundle():
    snap = _snap("mi-plan", "Mi Plan")
    bundle = {"schema": "retirement_advisor.plan_bundle", "snapshot": snap.to_dict()}
    restored = import_plan_from_dict(bundle)
    assert restored.id == "mi-plan"
    assert restored.name == "Mi Plan"


def test_import_drops_unknown_keys():
    d = _snap().to_dict()
    d["totally_unknown_future_field"] = {"x": 1}
    restored = import_plan_from_dict(d)  # must not raise
    assert restored.id == "retiro-2045"


def test_import_missing_identity_raises():
    with pytest.raises(ValueError):
        import_plan_from_dict({"name": "no id"})
    with pytest.raises(ValueError):
        import_plan_from_dict({"id": "no-name"})


def test_import_non_dict_raises():
    with pytest.raises(ValueError):
        import_plan_from_dict(["not", "a", "dict"])


def test_export_import_roundtrip_through_store(tmp_path):
    """Simulate export → delete → import → identical plan (offline)."""
    store = PlanStore(path=tmp_path / "plans.json")
    snap = _snap("portable", "Portable")
    store.upsert(snap)
    # "export": serialize like export_plan_bundle would (snapshot dict).
    exported = {"snapshot": store.get("portable").to_dict()}
    store.delete("portable")
    assert store.get("portable") is None
    # "import": rebuild and re-upsert.
    restored = import_plan_from_dict(exported)
    store.upsert(restored)
    again = store.get("portable")
    assert again is not None
    assert again.name == "Portable"
    assert again.target_weights() == snap.target_weights()


# ------------------------------------------------------------------ #
#  Fase H.4 — bundled sample plans                                     #
# ------------------------------------------------------------------ #

class TestSamplePlans:
    def test_list_returns_bundled_samples(self):
        from data.plan_context import list_sample_plans

        samples = list_sample_plans()
        keys = {s["key"] for s in samples}
        assert {"conservador_30y", "fire_moderado", "retiro_ar_adrs"} <= keys
        for s in samples:
            assert s["name"] and s["description"]
            assert s["n_positions"] > 0

    @pytest.mark.parametrize("key", ["conservador_30y", "fire_moderado", "retiro_ar_adrs"])
    def test_each_sample_loads_into_valid_snapshot(self, key):
        from data.plan_context import load_sample_plan

        snap = load_sample_plan(key)
        assert isinstance(snap, PlanSnapshot)
        assert snap.id and snap.name
        # target weights present and sum to ~100 (valid allocation).
        tw = snap.target_weights()
        assert tw and abs(sum(tw.values()) - 100.0) < 0.5

    def test_samples_carry_withdrawal_strategy(self):
        from data.plan_context import load_sample_plan

        kinds = {load_sample_plan(k).withdrawal_strategy["kind"]
                 for k in ("conservador_30y", "fire_moderado", "retiro_ar_adrs")}
        # The three samples showcase the three decumulation strategies.
        assert kinds == {"fixed_real", "guardrails", "constant_pct"}

    def test_unknown_sample_raises(self):
        from data.plan_context import load_sample_plan

        with pytest.raises(ValueError):
            load_sample_plan("does_not_exist")

    def test_sample_roundtrips_through_store(self, store):
        from data.plan_context import load_sample_plan

        snap = load_sample_plan("conservador_30y")
        store.upsert(snap)
        loaded = store.get(snap.id)
        assert loaded is not None
        assert loaded.withdrawal_strategy["kind"] == "fixed_real"
