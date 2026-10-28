"""AUDIT-UI-VERDAD (A) — tres pantallas decían «IA» sin que la IA hubiera hecho nada.

1. Stock Analysis rotulaba la fuente del track record por la configuración (``ai_cfg.enabled``) y no por
   lo que pasó: con la IA activa pero un veredicto del motor por reglas (respaldo, ``enrich_only``), el
   registro decía «ai». ``Decision.ai_used`` existe para esto y la pantalla no lo leía.
2. Mi Plan caía a ``st.session_state["last_plan_narrative"]`` —la que escribe Simulaciones, sin ligarla a
   un plan ni a una corrida— cuando el resultado vivo no traía narrativa, y la mostraba con la insignia de
   IA. El Optimizer deja ``ai_narrative = ""`` a propósito cuando la narrativa era el texto de respaldo.
3. Settings ponía ``ai_enabled = True`` en cada render al elegir Hermes/xAI, sin «Guardar»: el resto de
   las páginas de la sesión activaba la IA con el proveedor viejo (y su clave vacía) antes de guardar.

Se recorren las páginas reales con AppTest; sin red.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analysis.strategy import RetirementStrategy
from analysis.technical import TechnicalResult
from tests.test_currency_metric_surfaces import fund_fixture
from tests.test_nucleo_procedencia_oracle import _snapshot_opt
from tests.test_plan_page_runtime import stores  # noqa: F401  (fixture)

VIEWS = Path(__file__).resolve().parents[1] / "dashboard" / "views"
STOCK_ANALYSIS = str(VIEWS / "2_Stock_Analysis.py")
SETTINGS = str(VIEWS / "9_Settings.py")


# --------------------------------------------------------------------------- #
#  1 — la fuente del track record es lo que decidió, no lo que estaba prendido  #
# --------------------------------------------------------------------------- #

@pytest.fixture
def logged_source(monkeypatch):
    """``logged_source(ai_used)`` corre Stock Analysis con la IA activada y devuelve la ``source`` registrada."""
    import yfinance as yf

    from analysis.track_record import TrackRecordStore
    from config import MULTI_SOURCE
    from dashboard import shared

    def no_network(*args, **kwargs):
        raise AssertionError("This page test must not access yfinance")

    seen: list[str] = []
    monkeypatch.setattr(yf, "Ticker", no_network)
    monkeypatch.setattr(MULTI_SOURCE, "enabled", False)
    monkeypatch.setattr(TrackRecordStore, "log_recommendation",
                        lambda self, decision, *, source="rule_based", **kw: seen.append(source))
    monkeypatch.setattr(shared, "ensure_session_defaults", lambda: None)
    monkeypatch.setattr(shared, "get_price_history", lambda *a, **kw: pd.DataFrame())
    monkeypatch.setattr(shared, "_get_ai_config", lambda *a, **kw: SimpleNamespace(
        provider="claude", model="claude-sonnet-4-6", enabled=True, api_key="k",
    ))

    def run(ai_used: bool) -> list[str]:
        fund, tech = fund_fixture(), TechnicalResult("TEST")
        decision = RetirementStrategy().decide(fund, tech)
        decision.ai_used = ai_used
        monkeypatch.setattr(shared, "cached_full_analysis", lambda *a: (fund, tech, decision))
        app = AppTest.from_file(STOCK_ANALYSIS, default_timeout=30)
        app.session_state["analysis_target"] = "TEST"
        app.session_state["universe"] = ["TEST"]
        app.session_state["user_prefs"] = SimpleNamespace(watched_tickers=[])
        app.session_state["portfolio"] = SimpleNamespace(positions=[])
        seen.clear()
        app.run()
        assert not app.exception, [e.message for e in app.exception]
        return list(seen)

    return run


def test_a_verdict_the_rules_engine_gave_is_logged_rule_based_even_with_the_ai_on(logged_source):
    assert logged_source(ai_used=False) == ["rule_based"]


def test_a_verdict_the_model_gave_is_logged_ai(logged_source):
    assert logged_source(ai_used=True) == ["ai"]


# --------------------------------------------------------------------------- #
#  2 — Mi Plan no muestra la narrativa de otra corrida                         #
# --------------------------------------------------------------------------- #

OTHER_RUN = "Narrativa de OTRA corrida de Simulaciones"
OWN = "Narrativa de este plan"


def test_the_plan_page_does_not_show_the_narrative_of_another_run(stores):  # noqa: F811
    """El resultado vivo no trae narrativa: lo que quedó en la sesión es de otra corrida."""
    opt = _snapshot_opt()
    opt.ai_narrative = ""
    at = AppTest.from_file(str(VIEWS / "12_Plan.py"), default_timeout=60)
    from tests.test_plan_page_runtime import _FakePrefs

    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["optimizer_result"] = opt
    at.session_state["last_plan_narrative"] = OTHER_RUN
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert not [e for e in at.expander if "Narrativa del plan" in e.label]
    assert OTHER_RUN not in "\n".join(m.value for m in at.markdown)


def test_the_plan_page_shows_the_narrative_the_result_carries(stores):  # noqa: F811
    opt = _snapshot_opt()
    opt.ai_narrative = OWN
    at = AppTest.from_file(str(VIEWS / "12_Plan.py"), default_timeout=60)
    from tests.test_plan_page_runtime import _FakePrefs

    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["optimizer_result"] = opt
    at.session_state["last_plan_narrative"] = OTHER_RUN
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    texts = "\n".join(m.value for m in at.markdown)
    assert OWN in texts and OTHER_RUN not in texts


# --------------------------------------------------------------------------- #
#  3 — elegir Hermes en Settings no prende la IA hasta guardar                 #
# --------------------------------------------------------------------------- #

@pytest.fixture
def settings(monkeypatch):
    """``settings(provider)`` abre Settings con la IA apagada y ese proveedor ya elegido; no toca el ``.env``."""
    from dashboard import shared

    monkeypatch.setattr(shared, "_save_ai_config_to_env", lambda *a, **kw: None)
    monkeypatch.setattr(shared, "usd_ars_quote", lambda *a, **kw: None)   # sin red

    def open_page(provider: str) -> AppTest:
        from data.preferences import UserPreferences

        at = AppTest.from_file(SETTINGS, default_timeout=60)
        at.session_state["user_prefs"] = UserPreferences()
        at.session_state["universe"] = ["AAPL"]
        at.session_state["active_universe_key"] = "default"
        at.session_state["ai_provider"] = provider
        at.session_state["ai_enabled"] = False
        at.run()
        assert not at.exception, [str(e) for e in at.exception]
        return at

    return open_page


@pytest.mark.parametrize("provider", ["nous", "xai"])
def test_choosing_a_local_provider_does_not_turn_the_ai_on_before_saving(settings, provider):
    assert settings(provider).session_state["ai_enabled"] is False


@pytest.mark.parametrize("provider", ["nous", "xai"])
def test_saving_a_local_provider_turns_the_ai_on(settings, provider):
    at = settings(provider)
    save = [b for b in at.button if b.label == "Guardar configuración AI"]
    assert save, [b.label for b in at.button]
    save[0].click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["ai_enabled"] is True
