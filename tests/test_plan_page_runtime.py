"""Runtime tests for the "Mi Plan de Retiro" page (audit bugs 1, 2, 3, 5, 6).

These drive the shipped `12_Plan.py` through Streamlit's AppTest — clicking the
real buttons and reading the real store — because every one of these bugs lived
in the gap between a helper that worked and a page that never called it or never
persisted its result. Unit tests on the helpers alone are exactly what let the
bugs ship: `tests/test_product_ux.py` and `tests/test_scheduler.py` hand-built
`refreshed_metrics`, a field production never wrote.

No network and no yfinance: the price lookup, the AI config and the track-record
line are stubbed, and both JSON stores point at tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from data.plan_store import PlanSnapshot

ROOT = Path(__file__).resolve().parents[1]
PAGE = str(ROOT / "dashboard" / "pages" / "12_Plan.py")

# Prices at save time vs "today": a uniform -20% move, comfortably past both
# ALERTS.portfolio_drift_threshold_pct and HEALTH.degradation_drift_pct.
_PRICE_AT_SAVE = {"AAPL": 100.0, "KO": 50.0}
_PRICE_TODAY = {"AAPL": 80.0, "KO": 40.0}


class _FakePrefs:
    """Enough UserPreferences surface for the page, with no disk I/O."""

    is_onboarded = False
    monthly_savings = 500.0
    annual_savings = 6_000.0
    current_capital = 250_000.0
    primary_horizon_years = 20
    user_name = ""
    profile_key = "moderate"
    active_universe = "default"
    watched_tickers: list = []

    def __init__(self, active_plan_id: str = "") -> None:
        self.active_plan_id = active_plan_id

    def set_active_plan(self, plan_id: str) -> None:
        self.active_plan_id = (plan_id or "").strip()

    def clear_active_plan(self) -> None:
        self.active_plan_id = ""

    def custom_symbols(self):
        return []


def _snap(plan_id: str = "retiro-2045", name: str = "Retiro 2045") -> PlanSnapshot:
    return PlanSnapshot(
        id=plan_id,
        name=name,
        created_at="2026-01-01T09:00:00",
        updated_at="2026-01-01T09:00:00",
        profile_name="Moderado",
        profile_key="moderate",
        universe_key="us_quality",
        universe_name="US Quality",
        n_positions=2,
        allocation=[
            {"symbol": "AAPL", "weight_pct": 40.0, "adjusted_score": 82.0,
             "dividend_yield_pct": 0.5, "sector": "Technology",
             "price_at_save": _PRICE_AT_SAVE["AAPL"]},
            {"symbol": "KO", "weight_pct": 60.0, "adjusted_score": 70.0,
             "dividend_yield_pct": 3.0, "sector": "Consumer Defensive",
             "price_at_save": _PRICE_AT_SAVE["KO"]},
        ],
        core_holdings=[{"symbol": "KO", "suggested_weight_pct": 60.0, "why": "income"}],
        metrics={"expected_return_pct": 7.0, "volatility_pct": 12.0, "sharpe_ratio": 0.58},
        mc_summary={"horizon_years": 20, "initial_value": 250_000,
                    "target_value": 600_000, "median_terminal": 700_000.0},
    )


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """Point both JSON stores at tmp_path and stub every I/O the page does."""
    from dashboard import shared as shared_mod
    from data import plan_health as ph_mod
    from data import plan_store as ps_mod

    monkeypatch.setattr(ps_mod.plan_store, "path", tmp_path / "plans.json")
    monkeypatch.setattr(ph_mod.plan_health_store, "path", tmp_path / "health.json")
    monkeypatch.setattr(shared_mod, "plan_price_lookup", lambda sym: _PRICE_TODAY.get(sym))
    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="none", model="", enabled=False, api_key="",
    ))
    monkeypatch.setattr(shared_mod, "track_record_home_line", lambda: "Sin track record aún.")
    return SimpleNamespace(plans=ps_mod.plan_store, health=ph_mod.plan_health_store)


def _app(prefs: _FakePrefs) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = prefs
    return at.run()


def _all_text(at) -> str:
    chunks = []
    for coll in (at.markdown, at.caption, at.warning, at.info,
                 at.subheader, at.error, at.success, at.toast):
        chunks += [getattr(e, "value", "") or "" for e in coll]
    return "\n".join(chunks)


def _open_snapshot(at, plan_id: str):
    """Click "Ver" so the per-plan detail (health, history, …) renders."""
    at.button(key=f"view_{plan_id}").click().run()
    return at


# --------------------------------------------------------------------------- #
def test_page_runs_with_a_saved_plan(stores):
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs())
    assert not at.exception, [str(e) for e in at.exception]
    assert "Retiro 2045" in _all_text(at)


# --------------------------------------------------------------------------- #
#  U2-5 — the peso figure the page actually prints                            #
# --------------------------------------------------------------------------- #

def _ars_texts(at) -> str:
    return _all_text(at)


def test_the_page_never_prints_a_nominal_terminal_times_todays_rate(stores):
    """Audit U2-5, measured on the shipped page.

    `_snap()` carries a 20-year horizon, a $700k nominal median and **no**
    `inflation_rate` — the shape every plan saved before this fix has. The old
    block multiplied that median by AR$1.000 and printed AR$700.000.000 as if it
    were money you could hold today.
    """
    snap = _snap()
    stores.plans.upsert(snap)
    at = _app(_FakePrefs(active_plan_id="retiro-2045"))
    assert not at.exception, [str(e) for e in at.exception]

    text = _ars_texts(at)
    naive = snap.mc_summary["median_terminal"] * 1000.0        # AR_FX placeholder
    for rendering in (f"{naive:,.0f}", f"{naive:,.0f}".replace(",", ".")):
        assert rendering not in text, f"page printed the spot product {rendering}"
    # ...and it says why, instead of going quiet.
    assert "inflación" in text


def test_a_plan_saved_without_a_horizon_is_not_treated_as_todays_money(stores):
    """`mc_summary["horizon_years"]` can be absent (`enrich_pdf_mc_params` leaves
    it unset when neither the session nor the profile supplies one). Reading that
    as 0 would convert the nominal terminal at spot all over again."""
    snap = _snap()
    snap.mc_summary = {
        k: v for k, v in dict(snap.mc_summary, inflation_rate=3.0).items()
        if k != "horizon_years"
    }
    stores.plans.upsert(snap)
    at = _app(_FakePrefs(active_plan_id="retiro-2045"))
    assert not at.exception, [str(e) for e in at.exception]

    text = _ars_texts(at)
    naive = 700_000.0 * 1000.0
    for rendering in (f"{naive:,.0f}", f"{naive:,.0f}".replace(",", ".")):
        assert rendering not in text
    assert "horizonte" in text


def test_a_plan_that_recorded_its_inflation_gets_pesos_of_today(stores):
    snap = _snap()
    snap.mc_summary = dict(snap.mc_summary, inflation_rate=3.0)
    stores.plans.upsert(snap)
    at = _app(_FakePrefs(active_plan_id="retiro-2045"))
    assert not at.exception, [str(e) for e in at.exception]

    text = _ars_texts(at)
    expected = 700_000.0 / (1.03 ** 20) * 1000.0
    assert f"{expected:,.0f}" in text
    assert "pesos de hoy" in text


# --------------------------------------------------------------------------- #
#  Bugs 1 + 2 — the refresh must outlive the session                          #
# --------------------------------------------------------------------------- #

def test_refresh_button_persists_the_market_delta_to_disk(stores):
    """Before: the result lived only in session_state and died with the tab."""
    stores.plans.upsert(_snap())
    at = _open_snapshot(_app(_FakePrefs()), "retiro-2045")

    at.button(key="refresh_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    saved = stores.plans.get("retiro-2045")
    assert saved.refreshed_metrics is not None, "refresh must be sealed onto the plan"
    assert saved.refreshed_metrics["summary"]["weighted_delta_pct"] == -20.0
    assert saved.last_refreshed_at, "the market-data clock must move on refresh"


def test_refresh_stamps_the_clock_that_home_reads(stores):
    """Home nags off the age of `last_refreshed_at`.

    `shared.next_priority_action` and `build_home_hub_for_prefs` both feed it to
    `_days_since_iso` and warn "hace más de un mes (o nunca) que no comparás tu
    plan con el mercado". Only the AI-narrative button used to write the field,
    so refreshing never cleared the warning — and generating a narrative, which
    fetches no prices at all, silently reset the clock.
    """
    from dashboard.shared import _days_since_iso

    stores.plans.upsert(_snap())
    assert _days_since_iso(stores.plans.get("retiro-2045").last_refreshed_at) is None

    at = _open_snapshot(_app(_FakePrefs(active_plan_id="retiro-2045")), "retiro-2045")
    at.button(key="refresh_retiro-2045").click().run()

    assert _days_since_iso(stores.plans.get("retiro-2045").last_refreshed_at) == 0


def test_narrative_button_does_not_touch_the_market_clock(stores):
    """Generating a narrative fetches no prices, so it must not claim freshness."""
    source = (ROOT / "dashboard" / "pages" / "12_Plan.py").read_text(encoding="utf-8")
    narrative_block = source.split("_render_plan_ai")[-1]
    assert "snap.last_refreshed_at" not in narrative_block


def test_refreshed_plan_unlocks_the_rebalance_action(stores):
    """The payoff of bug 1: "Qué hacer este año" can finally say "Rebalanceá".

    `build_annual_action_list` only escalates when `drift_pct is not None`, and
    the page sources that from `refreshed_metrics` — so the material-drift item
    was unreachable no matter how far the user had drifted.
    """
    stores.plans.upsert(_snap())
    prefs = _FakePrefs(active_plan_id="retiro-2045")

    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["portfolio"] = SimpleNamespace(
        positions={"AAPL": {"shares": 10, "avg_cost": 100.0}},
    )
    at.run()
    assert "Revisá alineación plan vs cartera" in _all_text(at)
    assert "desvío material" not in _all_text(at)

    _open_snapshot(at, "retiro-2045")
    at.button(key="refresh_retiro-2045").click().run()

    assert "Rebalanceá hacia el plan (desvío material)" in _all_text(at)


# --------------------------------------------------------------------------- #
#  Bug 3 — "Registrar salud ahora" had no dedup window                        #
# --------------------------------------------------------------------------- #

def test_recording_health_twice_the_same_day_stores_one_record(stores):
    stores.plans.upsert(_snap())
    at = _open_snapshot(_app(_FakePrefs()), "retiro-2045")

    at.button(key="record_health_retiro-2045").click().run()
    assert len(stores.health.history("retiro-2045")) == 1

    at.button(key="record_health_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(stores.health.history("retiro-2045")) == 1, "second click must dedup"


def test_the_already_recorded_toast_is_reachable(stores):
    """That `else:` branch was dead code that described behaviour we did not have."""
    stores.plans.upsert(_snap())
    at = _open_snapshot(_app(_FakePrefs()), "retiro-2045")

    at.button(key="record_health_retiro-2045").click().run()
    at.button(key="record_health_retiro-2045").click().run()

    assert any("Ya habías registrado" in (t.value or "") for t in at.toast)


def test_clicking_record_repeatedly_cannot_fabricate_plan_degradation(stores):
    """Two clicks a second apart used to raise "deriva sostenida ≥15%"."""
    stores.plans.upsert(_snap())
    at = _open_snapshot(_app(_FakePrefs()), "retiro-2045")

    for _ in range(4):
        at.button(key="record_health_retiro-2045").click().run()

    assert "Plan envejecido" not in _all_text(at)
    assert len(stores.health.history("retiro-2045")) == 1


# --------------------------------------------------------------------------- #
#  Bug 5 — importing must not silently overwrite a local plan                 #
# --------------------------------------------------------------------------- #

def _upload(at, snap: PlanSnapshot):
    payload = json.dumps({"schema": "plan-export/1.0", "snapshot": snap.to_dict()})
    at.file_uploader(key="plan_import_file").set_value(
        ("plan.json", payload.encode("utf-8"), "application/json")
    )
    return at.run()


def test_import_without_collision_keeps_the_plain_flow(stores):
    at = _upload(_app(_FakePrefs()), _snap())
    assert not at.exception, [str(e) for e in at.exception]

    at.button(key="plan_import_btn").click().run()
    assert stores.plans.get("retiro-2045") is not None


def test_import_of_a_colliding_plan_warns_instead_of_overwriting(stores):
    local = _snap()
    local.n_positions = 3
    stores.plans.upsert(local)

    incoming = _snap()
    incoming.n_positions = 99
    at = _upload(_app(_FakePrefs()), incoming)

    assert "Ya existe un plan guardado con este identificador" in _all_text(at)
    # Merely selecting the file must not have touched anything.
    assert stores.plans.get("retiro-2045").n_positions == 3


def test_import_as_a_copy_keeps_both_plans(stores):
    local = _snap()
    local.n_positions = 3
    stores.plans.upsert(local)

    incoming = _snap()
    incoming.n_positions = 99
    at = _upload(_app(_FakePrefs()), incoming)
    at.button(key="plan_import_copy_btn").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert stores.plans.get("retiro-2045").n_positions == 3, "local plan survives"
    copy = stores.plans.get("retiro-2045-2")
    assert copy is not None and copy.n_positions == 99
    assert copy.name == "Retiro 2045 (copia)"


def test_overwriting_is_still_available_but_explicit(stores):
    local = _snap()
    local.n_positions = 3
    stores.plans.upsert(local)

    incoming = _snap()
    incoming.n_positions = 99
    at = _upload(_app(_FakePrefs()), incoming)
    at.button(key="plan_import_overwrite_btn").click().run()

    assert stores.plans.get("retiro-2045").n_positions == 99
    assert stores.plans.get("retiro-2045-2") is None


# --------------------------------------------------------------------------- #
#  Bug 6 — loading a plan must not zero the retirement goal                   #
# --------------------------------------------------------------------------- #

def test_loading_a_plan_without_monte_carlo_keeps_the_users_goal(stores):
    no_mc = _snap()
    no_mc.mc_summary = None
    stores.plans.upsert(no_mc)

    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["target_value"] = 500_000     # what the user set in Simulaciones
    at.run()

    _open_snapshot(at, "retiro-2045")
    at.button(key="load_retiro-2045").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["target_value"] == 500_000


def test_loading_a_plan_with_a_target_still_carries_it_over(stores):
    stores.plans.upsert(_snap())   # mc_summary target_value = 600_000

    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["target_value"] = 500_000
    at.run()

    _open_snapshot(at, "retiro-2045")
    at.button(key="load_retiro-2045").click().run()

    assert at.session_state["target_value"] == 600_000
    assert at.session_state["horizon_years"] == 20
    assert at.session_state["_preset_profile_key"] == "moderate"
