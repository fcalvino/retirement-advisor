"""Tests for data.product_ux — shipped pure helpers (backlog 1–15 surface)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from data.product_ux import (
    _fv_lump_and_annuity,
    ar_dual_amounts,
    build_annual_action_list,
    build_home_plan_hub,
    chat_missing_context_message,
    chat_suggested_questions,
    coach_should_fire_on_drop,
    compute_gap_to_goal_levers,
    decision_provenance_labels,
    deep_compare_plans,
    format_ar_dual_line,
    guided_empty_state,
    second_source_quality_signal,
    shareable_report_narrative_blocks,
    track_record_one_liner,
)

# --------------------------------------------------------------------------- #
#  Gap levers                                                                 #
# --------------------------------------------------------------------------- #

def test_gap_levers_underfunded_returns_actionable_numbers():
    """Underfunded path must surface more_savings with a positive monthly figure."""
    capital, annual, years, r, target = 50_000.0, 6_000.0, 20.0, 0.05, 500_000.0
    # Sanity: simple FV is below target so levers should fire
    assert _fv_lump_and_annuity(capital, annual, years, r) < target

    levers = compute_gap_to_goal_levers(
        capital=capital,
        annual_contribution=annual,
        years=years,
        annual_return=r,
        target=target,
        prob_achieve_pct=35.0,
    )
    assert levers, "expected at least one lever for an underfunded plan"
    kinds = {lv["kind"] for lv in levers}
    assert "more_savings" in kinds
    savings = next(lv for lv in levers if lv["kind"] == "more_savings")
    assert savings["value"] > 0
    assert savings["unit"] == "usd_per_month"
    # Applying the extra annual should close the gap under the same FV model
    extra_annual = savings["value"] * 12.0
    fv2 = _fv_lump_and_annuity(capital, annual + extra_annual, years, r)
    assert fv2 >= target * 0.99  # allow tiny rounding


def test_gap_levers_empty_when_no_target():
    assert compute_gap_to_goal_levers(
        capital=100_000, annual_contribution=12_000, years=20,
        annual_return=0.06, target=0, prob_achieve_pct=10,
    ) == []


def test_gap_levers_empty_when_already_funded_and_high_prob():
    levers = compute_gap_to_goal_levers(
        capital=400_000, annual_contribution=20_000, years=15,
        annual_return=0.07, target=500_000, prob_achieve_pct=85.0,
    )
    # FV of 400k + 20k/yr @7% 15y is well above 500k
    assert levers == []


# --------------------------------------------------------------------------- #
#  Home hub                                                                   #
# --------------------------------------------------------------------------- #

def test_home_hub_empty_without_plan():
    hub = build_home_plan_hub(
        plan_snapshot=None,
        primary_action={"label": "Definí tu perfil", "page": None},
        sample_plan_available=True,
        track_record_line="Track record: vacío",
    )
    d = hub.as_dict()
    assert d["has_plan"] is False
    assert d["sample_plan_available"] is True
    assert "plan" in d["empty_reason"].lower() or "ejemplo" in d["empty_reason"].lower()


def test_home_hub_reads_mc_and_drift_from_snapshot():
    snap = SimpleNamespace(
        name="Retiro 2045",
        mc_summary={"prob_target_pct": 62.5, "median_terminal": 1_200_000},
        metrics={"expected_return_pct": 9.5},
        refreshed_metrics={"summary": {"weighted_delta_pct": -3.2}},
    )
    hub = build_home_plan_hub(
        plan_snapshot=snap,
        unread_alerts=2,
        data_age_days=5,
        track_record_line="ok",
    )
    assert hub.has_plan is True
    assert hub.plan_name == "Retiro 2045"
    assert hub.prob_target_pct == pytest.approx(62.5)
    assert hub.median_terminal == pytest.approx(1_200_000)
    assert hub.drift_pct == pytest.approx(-3.2)
    assert hub.unread_alerts == 2
    assert hub.data_age_days == 5


# --------------------------------------------------------------------------- #
#  Annual actions                                                             #
# --------------------------------------------------------------------------- #

def test_annual_actions_include_contribute_and_backup():
    snap = SimpleNamespace(
        name="Plan X",
        personal={"monthly_savings": 500, "annual_savings": 6000},
    )
    actions = build_annual_action_list(
        plan_snapshot=snap,
        monthly_savings=500,
        has_portfolio_positions=False,
        last_backup_days=None,
    )
    ids = {a["id"] for a in actions}
    assert "contribute" in ids or "define_savings" in ids
    assert "backup" in ids
    assert "fund_core" in ids  # no positions → fund core
    assert all("title" in a and "cta_page" in a for a in actions)


def test_annual_actions_rebalance_priority_when_drift_high():
    actions = build_annual_action_list(
        plan_snapshot=SimpleNamespace(name="P", personal={}),
        monthly_savings=1000,
        has_portfolio_positions=True,
        drift_pct=12.0,
        drift_threshold_pct=5.0,
        last_backup_days=10,
    )
    reb = next(a for a in actions if a["id"] == "rebalance")
    assert reb["priority"] == 2
    assert "desvío" in reb["title"].lower() or "Deriva" in reb["detail"] or "deriva" in reb["detail"].lower()


# --------------------------------------------------------------------------- #
#  Deep compare                                                               #
# --------------------------------------------------------------------------- #

def test_deep_compare_highlights_differences():
    a = SimpleNamespace(
        name="Conservador",
        profile_name="Conservador",
        n_positions=8,
        metrics={"expected_return_pct": 7.0, "volatility_pct": 10.0, "sharpe_ratio": 0.6},
        mc_summary={"median_terminal": 800_000, "prob_target_pct": 55.0},
        personal={"primary_horizon_years": 25, "current_capital": 100_000},
        allocation=[{"symbol": "MSFT", "weight_pct": 20}, {"symbol": "BND", "weight_pct": 30}],
        drags_at_save={"annual_fee_pct": 0.2},
        withdrawal_strategy={"strategy": "fixed_real"},
        narrative="hola",
    )
    b = SimpleNamespace(
        name="Agresivo",
        profile_name="Agresivo",
        n_positions=12,
        metrics={"expected_return_pct": 11.0, "volatility_pct": 18.0, "sharpe_ratio": 0.7},
        mc_summary={"median_terminal": 1_500_000, "prob_target_pct": 72.0},
        personal={"primary_horizon_years": 25, "current_capital": 100_000},
        allocation=[{"symbol": "NVDA", "weight_pct": 15}, {"symbol": "QQQ", "weight_pct": 25}],
        drags_at_save={"annual_fee_pct": 0.2},
        withdrawal_strategy={"strategy": "guardrails"},
        narrative="hola mundo",
    )
    cmp_ = deep_compare_plans(a, b)
    assert cmp_["name_a"] == "Conservador"
    assert cmp_["name_b"] == "Agresivo"
    assert cmp_["n_differences"] >= 3
    assert cmp_["rows"]
    # delta on expected return should be +4
    er = next(r for r in cmp_["rows"] if r["field"] == "expected_return_pct")
    assert er["differs"] is True
    assert er["delta"] == pytest.approx(4.0)


# --------------------------------------------------------------------------- #
#  Track record one-liner                                                     #
# --------------------------------------------------------------------------- #

def test_track_record_one_liner_empty():
    line = track_record_one_liner({"n": 0})
    assert "no hay" in line.lower() or "todavía" in line.lower()


def test_track_record_one_liner_with_stats():
    line = track_record_one_liner(
        {"n": 40, "overall_hit_rate": 0.55, "mean_excess_pct": 1.2},
        by_action={"BUY": {"n": 20, "hit_rate": 0.6}},
        horizon_label="12m",
        benchmark_label="SPY",
    )
    assert "40" in line
    assert "55%" in line or "55" in line
    assert "BUY" in line
    assert "SPY" in line


# --------------------------------------------------------------------------- #
#  Coach                                                                      #
# --------------------------------------------------------------------------- #

def test_coach_fires_on_drop_when_plan_ok():
    d = coach_should_fire_on_drop(
        portfolio_return_pct=-10.0,
        drop_threshold_pct=8.0,
        plan_prob_target_pct=70.0,
        plan_prob_floor_pct=40.0,
    )
    assert d["should_fire"] is True
    assert d["severity"] == "info"
    assert "plan" in d["message"].lower() or "Caída" in d["message"]


def test_coach_does_not_fire_small_move_or_cooldown():
    assert coach_should_fire_on_drop(portfolio_return_pct=-2.0)["should_fire"] is False
    assert coach_should_fire_on_drop(
        portfolio_return_pct=-12.0, already_on_cooldown=True
    )["should_fire"] is False


def test_coach_warning_when_plan_weak():
    d = coach_should_fire_on_drop(
        portfolio_return_pct=-15.0,
        plan_prob_target_pct=20.0,
        plan_prob_floor_pct=40.0,
    )
    assert d["should_fire"] is True
    assert d["severity"] == "warning"


# --------------------------------------------------------------------------- #
#  AR dual                                                                    #
# --------------------------------------------------------------------------- #

def test_ar_dual_amounts_and_brecha():
    dual = ar_dual_amounts(10_000, usd_ars_oficial=1000, usd_ars_parallel=1200, label="capital")
    assert dual["usd"] == 10_000
    assert dual["ars_oficial"] == 10_000_000
    assert dual["ars_parallel"] == 12_000_000
    assert dual["brecha_pct"] == pytest.approx(20.0)
    line = format_ar_dual_line(dual)
    assert "USD" in line and "ARS" in line and "brecha" in line


def test_ar_dual_rejects_bad_rate():
    with pytest.raises(ValueError):
        ar_dual_amounts(100, usd_ars_oficial=0)


# --------------------------------------------------------------------------- #
#  Chat / empty / quality / PDF blocks                                        #
# --------------------------------------------------------------------------- #

def test_chat_suggestions_and_missing_context():
    qs = chat_suggested_questions(has_active_plan=True, has_portfolio=True)
    assert len(qs) >= 3
    assert any("plan" in q.lower() for q in qs)

    msg = chat_missing_context_message(
        has_active_plan=False, has_goal_target=False, tool_name="retirement_projection"
    )
    assert msg and "0%" in msg and "plan" in msg.lower()

    msg2 = chat_missing_context_message(
        has_active_plan=True, has_goal_target=False, tool_name="retirement_projection"
    )
    assert msg2 and "meta" in msg2.lower()


def test_guided_empty_state_and_provenance():
    es = guided_empty_state("comite")
    assert es["demo_ticker"]
    labels = decision_provenance_labels(has_ai=True, has_calc=True)
    kinds = {x["kind"] for x in labels}
    assert "calc" in kinds and "ai" in kinds


def test_second_source_quality_signal_conflict_and_cross_check():
    sig = second_source_quality_signal(
        {"n_conflicts": 2, "agreement_pct": 50.0, "sources_used": ["sec_edgar", "yfinance"]},
        data_quality={"level": "partial", "stale": False},
    )
    assert sig["status"] == "conflict"
    assert "conflicto" in sig["message"].lower() or "conflict" in sig["message"].lower()

    sig2 = second_source_quality_signal(
        {"n_conflicts": 0, "agreement_pct": 100.0, "sources_used": ["sec_edgar", "yfinance"]},
        data_quality={"level": "good"},
    )
    assert sig2["status"] == "cross_checked"


def test_shareable_report_blocks():
    blocks = shareable_report_narrative_blocks(
        plan_name="FIRE",
        prob_target_pct=61.0,
        median_terminal=900_000,
        horizon_years=20,
        profile="Moderado",
        annual_actions=[{"title": "Aportar $500/mes"}],
    )
    assert len(blocks) >= 3
    assert any("pareja" in b["body"].lower() or "asesor" in b["body"].lower() for b in blocks)


def test_pdf_shareable_section_uses_real_monthly_savings():
    """Shipped PDF path must not always emit 'Definí cuánto podés aportar' when savings exist."""
    from reports import investment_plan as ip
    from reports.investment_plan import InvestmentPlanReport

    report = InvestmentPlanReport()
    elements = report._section_shareable_for_partner(
        ip._styles(),
        goal_plan=None,
        opt_result=SimpleNamespace(profile_name="Moderado", tickers=["AAPL", "MSFT"]),
        mc_result=SimpleNamespace(prob_achieve_target_pct=55.0, median_terminal=800_000),
        mc_params={
            "horizon_years": 20,
            "initial_value": 100_000,
            "monthly_savings": 750,
            "profile_name": "Moderado",
        },
        options=ip.ReportOptions(user_name="Test User"),
    )
    text = " ".join(getattr(e, "text", "") or "" for e in elements)
    assert "Definí cuánto podés aportar" not in text
    assert "750" in text
    assert "Aportar" in text


def test_plan_pdf_params_assembly_from_prefs_without_session_savings():
    """Real Plan/Sim PDF param path: empty session + prefs.monthly_savings → savings in params.

    This is the production gap the skeptic found: call sites used to omit savings
    and only pass sim widget keys. Drive ``assemble_plan_pdf_mc_params`` (the
    shipped helper used by 12_Plan / 7_Simulaciones / 5_Optimizer), then the
    real shareable section — not a hand-built mc_params with monthly_savings.
    """
    from data.product_ux import assemble_plan_pdf_mc_params
    from reports import investment_plan as ip
    from reports.investment_plan import InvestmentPlanReport

    prefs = SimpleNamespace(
        monthly_savings=800.0,
        annual_savings=9600.0,
        current_capital=120_000.0,
        primary_horizon_years=25,
    )
    # Empty session = user never opened Simulaciones (common Plan PDF path)
    params = assemble_plan_pdf_mc_params(
        session={},
        prefs=prefs,
        profile_name="Moderado",
    )
    assert float(params["monthly_savings"]) == pytest.approx(800.0)
    assert float(params["annual_savings"]) == pytest.approx(9600.0)
    assert float(params["initial_value"]) == pytest.approx(120_000.0)
    assert float(params["horizon_years"]) == pytest.approx(25.0)

    elements = InvestmentPlanReport()._section_shareable_for_partner(
        ip._styles(),
        goal_plan=None,
        opt_result=SimpleNamespace(profile_name="Moderado", tickers=["MSFT"]),
        mc_result=SimpleNamespace(prob_achieve_target_pct=48.0, median_terminal=900_000),
        mc_params=params,  # only what assembly produces — no extra monthly_savings key forged later
        options=ip.ReportOptions(user_name="Fer"),
    )
    text = " ".join(getattr(e, "text", "") or "" for e in elements)
    assert "Definí cuánto podés aportar" not in text
    assert "800" in text
    assert "Aportar" in text


def test_enrich_pdf_mc_params_from_personal_dict():
    from data.product_ux import enrich_pdf_mc_params

    out = enrich_pdf_mc_params(
        {"horizon_years": None, "initial_value": None},
        personal={"monthly_savings": 400, "current_capital": 50_000, "primary_horizon_years": 18},
    )
    assert out["monthly_savings"] == pytest.approx(400)
    assert out["initial_value"] == pytest.approx(50_000)
    assert out["horizon_years"] == pytest.approx(18)


def test_ar_fx_config_is_single_dataclass():
    """Regression: ArFxConfig must not have a doubled @dataclass decorator."""
    import inspect

    import config as cfg

    assert hasattr(cfg, "AR_FX")
    assert cfg.AR_FX.usd_ars_oficial > 0
    # Instantiating a fresh copy proves the class is a healthy dataclass
    fresh = cfg.ArFxConfig(usd_ars_oficial=1100, usd_ars_parallel=1400)
    assert fresh.usd_ars_oficial == 1100
    # Exactly one @dataclass immediately above the class is enforced by import;
    # double decoration would still "work" but we assert single decorator in source file.
    config_src = inspect.getsource(cfg)
    # Count consecutive @dataclass lines before class ArFxConfig
    import re
    m = re.search(r"((?:@dataclass\n)+)class ArFxConfig", config_src)
    assert m is not None
    assert m.group(1).count("@dataclass") == 1


def test_dockerfile_healthcheck_no_curl():
    """Docker image HEALTHCHECK must not depend on curl (not in slim base)."""
    from pathlib import Path

    df = Path(__file__).resolve().parents[1] / "Dockerfile"
    text = df.read_text(encoding="utf-8")
    assert "HEALTHCHECK" in text
    assert "curl" not in text.lower() or "curl" not in text.split("HEALTHCHECK", 1)[1]
    health = text.split("HEALTHCHECK", 1)[1]
    assert "urllib" in health or "urllib.request" in health


# --------------------------------------------------------------------------- #
#  Alert engine coach path (shipped entry)                                    #
# --------------------------------------------------------------------------- #

def test_alert_engine_market_drop_coach_fires():
    """Drive the real AlertEngine.check_market_drop_coach entry (FakeAlertStore)."""
    from unittest.mock import MagicMock

    from alerts.engine import AlertEngine
    from alerts.store import AlertSeverity, AlertType
    from tests.test_alert_engine import FakeAlertStore

    store = FakeAlertStore()
    eng = AlertEngine.__new__(AlertEngine)
    eng._store = store
    eng._notifier = MagicMock()
    eng._min_severity = AlertSeverity.INFO

    fired = eng.check_market_drop_coach(
        portfolio_return_pct=-12.0,
        plan_name="Demo",
        plan_prob_target_pct=65.0,
        drop_threshold_pct=8.0,
    )
    assert fired is not None
    assert fired.alert_type == AlertType.MARKET_DROP_COACH
    assert "Caída" in fired.message or "caída" in fired.message.lower()

    # After fire, store should have cooldown set by _fire — set it like production
    store.set_cooldown(AlertType.MARKET_DROP_COACH, "COACH:Demo")
    again = eng.check_market_drop_coach(
        portfolio_return_pct=-12.0,
        plan_name="Demo",
        plan_prob_target_pct=65.0,
        drop_threshold_pct=8.0,
    )
    assert again is None


# --------------------------------------------------------------------------- #
#  plan_load_session_updates — "Cargar plan" seeding (audit bug 6)            #
# --------------------------------------------------------------------------- #

class TestPlanLoadSessionUpdates:
    """The page set ``target_value`` unconditionally when loading a plan.

    A plan saved without running Monte Carlo has ``mc_summary is None`` — a
    supported path the page advertises — so loading it wrote a $0 retirement
    goal over whatever the user had. ``inflation_rate``, two lines below, was
    correctly guarded. The rule is now in one tested place: a key the plan
    cannot answer is omitted, and the user's current value survives.
    """

    @staticmethod
    def _snap(**overrides):
        from data.plan_store import PlanSnapshot

        base = dict(
            id="retiro-2045", name="Retiro 2045", created_at="", updated_at="",
            personal={"current_capital": 250_000.0},
        )
        base.update(overrides)
        return PlanSnapshot(**base)

    def test_plan_without_monte_carlo_omits_the_target(self):
        from data.product_ux import plan_load_session_updates

        out = plan_load_session_updates(self._snap(), horizon_years=20)

        assert "target_value" not in out, "must not overwrite the user's goal with $0"
        assert "inflation_rate" not in out
        assert "goals_list" not in out
        assert out["initial_value"] == 250_000
        assert out["horizon_years"] == 20

    def test_plan_with_a_target_carries_it_over(self):
        from data.product_ux import plan_load_session_updates

        out = plan_load_session_updates(
            self._snap(mc_summary={"target_value": 750_000, "inflation_rate": 3.5}),
            horizon_years=25,
        )
        assert out["target_value"] == 750_000
        assert out["inflation_rate"] == 3.5

    def test_a_zero_target_is_treated_as_absent(self):
        from data.product_ux import plan_load_session_updates

        out = plan_load_session_updates(
            self._snap(mc_summary={"target_value": 0, "inflation_rate": None}),
            horizon_years=20,
        )
        assert "target_value" not in out
        assert "inflation_rate" not in out

    def test_goals_and_profile_are_seeded_only_when_present(self):
        from data.product_ux import plan_load_session_updates

        bare = plan_load_session_updates(self._snap(), horizon_years=20)
        assert "_preset_profile_key" not in bare

        full = plan_load_session_updates(
            self._snap(goals=[{"name": "casa", "target_amount_today": 100_000}]),
            horizon_years=20, profile_key="moderate",
        )
        assert full["_preset_profile_key"] == "moderate"
        assert full["goals_list"] == [{"name": "casa", "target_amount_today": 100_000}]

    def test_capital_falls_back_to_mc_then_to_the_default(self):
        from data.product_ux import plan_load_session_updates

        from_mc = plan_load_session_updates(
            self._snap(personal=None, mc_summary={"initial_value": 80_000}),
            horizon_years=20,
        )
        assert from_mc["optimizer_total_capital"] == 80_000

        empty = plan_load_session_updates(
            self._snap(personal=None), horizon_years=20,
        )
        assert empty["optimizer_total_capital"] == 100_000

    def test_simulaciones_capital_stays_inside_the_widget_bounds(self):
        from data.product_ux import plan_load_session_updates

        huge = plan_load_session_updates(
            self._snap(personal={"current_capital": 99_000_000.0}), horizon_years=20,
        )
        tiny = plan_load_session_updates(
            self._snap(personal={"current_capital": 10.0}), horizon_years=20,
        )
        # number_input in 7_Simulaciones.py: min 1_000, max 10_000_000.
        assert huge["initial_value"] == 10_000_000
        assert tiny["initial_value"] == 1_000


class TestEngineStalenessReasons:
    """A stale plan must be told what actually changed since ITS stamp.

    The warning used to be written once, for tier0, and shown to every stale
    plan. A tier1 plan's withdrawals were already correct, so that copy told it
    something false about its own numbers — the exact defect class the audits
    exist to remove, arriving through the copy instead of the maths.
    """

    def test_the_current_version_is_not_stale_for_any_reason(self):
        from config import ENGINE_VERSION
        from data.product_ux import engine_staleness_reasons

        assert engine_staleness_reasons(ENGINE_VERSION) == []

    def test_a_tier1_plan_is_not_told_its_withdrawals_were_wrong(self):
        from data.product_ux import engine_staleness_reasons

        reasons = engine_staleness_reasons("2026.08-tier1")
        assert len(reasons) == 1
        assert "monto fijo en vez de capital" not in " ".join(reasons)
        assert "aportes" in reasons[0]

    def test_an_older_plan_is_told_everything_that_changed_after_it(self):
        from data.product_ux import engine_staleness_reasons

        assert len(engine_staleness_reasons("2026.08-tier0")) == 2

    def test_an_unsigned_plan_predates_the_changelog_so_all_of_it_applies(self):
        from data.product_ux import ENGINE_CHANGELOG, engine_staleness_reasons

        assert len(engine_staleness_reasons("")) == len(ENGINE_CHANGELOG)

    def test_every_shipped_version_has_an_entry(self):
        """The changelog must name the version the engine currently stamps."""
        from config import ENGINE_VERSION
        from data.product_ux import ENGINE_CHANGELOG

        assert ENGINE_VERSION in [version for version, _ in ENGINE_CHANGELOG]


class TestContributionInputs:
    """One helper owns the ×12, so two screens cannot quote different money."""

    def test_annual_is_exactly_twelve_times_monthly(self):
        from data.product_ux import contribution_inputs

        resolved = contribution_inputs(personal={"monthly_savings": 437.5})
        assert resolved["annual"] == pytest.approx(437.5 * 12)

    def test_an_annual_figure_resolves_back_to_the_same_monthly(self):
        from data.product_ux import contribution_inputs

        assert contribution_inputs(personal={"annual_savings": 6_000.0})["monthly"] == pytest.approx(500.0)

    def test_what_the_user_typed_here_beats_what_their_profile_remembers(self):
        from data.product_ux import contribution_inputs

        class _Prefs:
            monthly_savings = 100.0

        resolved = contribution_inputs({"monthly_savings": 800.0}, prefs=_Prefs())
        assert resolved["monthly"] == pytest.approx(800.0)
        assert resolved["source"] == "session"

    def test_no_savings_anywhere_is_reported_as_no_source(self):
        """Absent is not the same as zero, and the caller has to be able to tell."""
        from data.product_ux import contribution_inputs

        resolved = contribution_inputs()
        assert resolved["annual"] == 0.0
        assert resolved["source"] == ""
