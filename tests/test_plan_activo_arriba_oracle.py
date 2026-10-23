"""PLAN-ACTIVO-ARRIBA: Mi Plan muestra el plan activo guardado en una sesión nueva.

«📍 Plan actual (esta sesión)» se armaba sólo con ``optimizer_result``, que vive en
la sesión del navegador: al recargar, abrir otra pestaña o cambiar de puerto la
página pedía optimizar de nuevo aunque hubiera un plan activo guardado, y el plan
quedaba escondido detrás de «Ver». Estos tests manejan la página real (AppTest)
en una sesión sin ``optimizer_result``.
"""

from __future__ import annotations

from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from tests.test_plan_page_runtime import (  # noqa: F401  (fixture)
    PAGE,
    _all_text,
    _app,
    _FakePrefs,
    _snap,
    stores,
)

EMPTY = "Todavía no hay una cartera optimizada en esta sesión"


def _warnings(at) -> list[str]:
    return [w.value for w in at.warning]


def _button_keys(at) -> list[str]:
    return [b.key for b in at.button]


def test_a_fresh_session_shows_the_active_plan_instead_of_asking_to_optimize(stores):  # noqa: F811
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs(active_plan_id="retiro-2045"))
    assert not at.exception, [str(e) for e in at.exception]
    assert not any(EMPTY in w for w in _warnings(at)), _warnings(at)
    assert any("Tu plan activo" in s.value for s in at.subheader)
    # The snapshot is drawn: its MC line and its per-plan actions are there.
    assert "Mediana $700,000" in _all_text(at).replace("\\$", "$")
    assert "refresh_retiro-2045" in _button_keys(at)


def test_the_active_plan_is_drawn_once_so_its_buttons_keep_unique_keys(stores):  # noqa: F811
    stores.plans.upsert(_snap())
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = _FakePrefs(active_plan_id="retiro-2045")
    at.session_state["plan_view_id"] = "retiro-2045"   # «Ver» left open earlier
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    keys = _button_keys(at)
    assert keys.count("refresh_retiro-2045") == 1
    assert "view_retiro-2045" not in keys


def test_the_refresh_button_of_the_active_plan_on_top_works(stores):  # noqa: F811
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs(active_plan_id="retiro-2045"))
    at.button(key="refresh_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert stores.plans.get("retiro-2045").last_refreshed_at


def test_without_an_active_plan_the_guided_empty_state_stays(stores):  # noqa: F811
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs())
    assert not at.exception, [str(e) for e in at.exception]
    assert any(EMPTY in w for w in _warnings(at))
    assert "view_retiro-2045" in _button_keys(at)


def test_a_session_run_is_still_shown_as_the_draft(stores):  # noqa: F811
    stores.plans.upsert(_snap())
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = _FakePrefs(active_plan_id="retiro-2045")
    at.session_state["optimizer_result"] = SimpleNamespace(
        tickers=["AAPL", "KO"], weights={"AAPL": 0.4, "KO": 0.6}, profile_name="Moderado",
    )
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("Plan actual (esta sesión)" in s.value for s in at.subheader)
    assert not any("Tu plan activo" in s.value for s in at.subheader)
    assert "plan_save_btn" in _button_keys(at)
    assert "view_retiro-2045" in _button_keys(at)


def test_an_active_example_plan_on_top_says_it_is_an_example(stores, monkeypatch):  # noqa: F811
    monkeypatch.setattr("data.plan_context.sample_plan_ids", lambda: {"retiro-2045"})
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs(active_plan_id="retiro-2045"))
    assert not at.exception, [str(e) for e in at.exception]
    assert "un plan de ejemplo, no tuyo" in _all_text(at)
    assert "tu plan guardado" not in _all_text(at)


def test_a_narrative_fallback_on_top_does_not_blank_the_plan_list(stores, monkeypatch):  # noqa: F811
    """The fallback used ``st.stop()``: from the top it cut «Planes guardados»."""
    from dashboard import shared as shared_mod

    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="claude", model="m", enabled=True, api_key="k",
    ))
    monkeypatch.setattr(
        "analysis.ai_analyzer.AIAnalyzer.generate_plan_narrative",
        lambda self, snap, refreshed=None: {"narrative": "", "ai_fallback_reason": "timeout"},
    )
    stores.plans.upsert(_snap())
    at = _app(_FakePrefs(active_plan_id="retiro-2045"))
    at.button(key="ai_narr_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("Planes guardados" in s.value for s in at.subheader)
    assert "deact_retiro-2045" in _button_keys(at)
    assert not stores.plans.get("retiro-2045").narrative


def test_with_a_session_run_the_active_plan_opens_from_ver_and_refresh_reruns(stores):  # noqa: F811
    """«Ver» still opens the active plan when the session has a run, and there
    «Qué hacer este año» is drawn before the refresh: only the rerun after it
    lets the checklist see the drift (the path ``test_plan_page_runtime`` used)."""
    stores.plans.upsert(_snap())
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["user_prefs"] = _FakePrefs(active_plan_id="retiro-2045")
    at.session_state["optimizer_result"] = SimpleNamespace(
        tickers=["AAPL", "KO"], weights={"AAPL": 0.4, "KO": 0.6}, profile_name="Moderado",
    )
    at.session_state["portfolio"] = SimpleNamespace(
        positions={"AAPL": {"shares": 10, "avg_cost": 100.0}},
    )
    at.run()
    at.button(key="view_retiro-2045").click().run()
    at.button(key="refresh_retiro-2045").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert "Rebalanceá hacia el plan (desvío material)" in _all_text(at)
