"""AUDIT-UI-ESTADO (Optimizer) — la explicación de la IA se pide una vez por resultado, no en cada rerun.

``5_Optimizer.py`` llamaba a ``AIAnalyzer.generate_optimizer_advice`` en cada ejecución del script con la
IA activa, sin botón de por medio: cualquier interacción de la página (un slider, un expander, un
checkbox) pagaba otra llamada de hasta 2 500 tokens, y la narrativa podía cambiar bajo los ojos del
usuario. ``generate_optimizer_advice`` no cachea por dentro (medido: dos corridas seguidas, dos llamadas).

Ahora la respuesta se guarda en la sesión con la clave de lo que la determina (resultado, metas, pesos
actuales, proveedor y modelo) y sólo se vuelve a pedir si algo de eso cambia. Una respuesta de respaldo
(error, sin clave) no se guarda: se reintenta. Se recorre la página real con AppTest; sin red.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

PAGE = str(Path(__file__).resolve().parents[1] / "dashboard" / "views" / "5_Optimizer.py")
UNIVERSE = [f"T{i:02d}" for i in range(12)]
ADVICE = {"narrative": "N", "core_source": "ia", "core_holdings": [], "ai_fallback_reason": ""}


def _result(weight: float = 100.0):
    from portfolio.optimizer import OptimizationResult, TickerAllocation

    return OptimizationResult(
        profile_name="Moderado", method="mean-variance",
        tickers=[TickerAllocation("AAPL", weight, 7.0, 20.0, 0.5, 80.0, 5.0, "Technology")],
    )


@pytest.fixture
def optimizer(tmp_path, monkeypatch):
    """``optimizer()`` abre la página con un resultado en sesión y la IA activa; ``.calls`` cuenta las llamadas."""
    from analysis.ai_analyzer import AIAnalyzer
    from dashboard import shared
    from data import preferences as prefs_mod
    from portfolio.tracker import Portfolio

    calls: list[dict] = []
    reply = {"value": ADVICE}
    cfg = {"provider": "claude", "model": "claude-sonnet-4-6"}
    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "user_preferences.json")
    monkeypatch.setattr(shared, "_get_ai_config", lambda *a, **k: SimpleNamespace(
        enabled=True, api_key="k", **cfg))

    def fake(self, result, goals=None, current_weights=None):
        calls.append({"goals": goals, "current_weights": current_weights})
        return dict(reply["value"])

    monkeypatch.setattr(AIAnalyzer, "generate_optimizer_advice", fake)

    def open_page(result=None) -> AppTest:
        at = AppTest.from_file(PAGE, default_timeout=60)
        at.session_state["user_prefs"] = prefs_mod.UserPreferences(default_profile="Moderado", profile_chosen=True)
        at.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
        at.session_state["universe"] = UNIVERSE
        at.session_state["active_universe_key"] = "default"
        at.session_state["optimizer_result"] = result or _result()
        at.session_state["optimizer_result_key"] = ("moderate", tuple(UNIVERSE))
        at.session_state["optimizer_scored"] = []
        at.run()
        assert not at.exception, [str(e)[:300] for e in at.exception]
        return at

    open_page.calls, open_page.reply, open_page.cfg = calls, reply, cfg
    return open_page


def test_a_rerun_does_not_ask_the_model_again(optimizer):
    at = optimizer()
    assert len(optimizer.calls) == 1
    at.run()
    at.run()
    assert len(optimizer.calls) == 1


def test_the_cached_answer_is_still_applied_to_a_fresh_identical_result(optimizer):
    """Una re-optimización idéntica devuelve otro objeto sin narrativa: se le aplica la guardada, sin otra llamada."""
    at = optimizer()
    at.session_state["optimizer_result"] = _result()
    at.run()
    assert len(optimizer.calls) == 1
    assert at.session_state["optimizer_result"].ai_narrative == "N"


def test_a_cached_ai_core_is_applied_too(optimizer):
    optimizer.reply["value"] = {**ADVICE, "core_holdings": [{"symbol": "AAPL", "suggested_weight_pct": 100.0,
                                                              "why": "moat"}]}
    at = optimizer()
    at.session_state["optimizer_result"] = _result()
    at.run()
    assert len(optimizer.calls) == 1
    assert at.session_state["optimizer_result"].core_holdings_ai[0]["symbol"] == "AAPL"


def test_the_same_weights_with_a_different_rebalance_ask_again(optimizer):
    """El prompt lleva ``rebalance_rationale``: mismo objetivo, otra cartera actual, otra explicación."""
    at = optimizer()
    again = _result()
    again.rebalance_rationale = "Vender 10 % de AAPL"
    at.session_state["optimizer_result"] = again
    at.run()
    assert len(optimizer.calls) == 2


def test_a_different_result_asks_again(optimizer):
    at = optimizer()
    at.session_state["optimizer_result"] = _result(weight=60.0)
    at.run()
    assert len(optimizer.calls) == 2


def test_a_different_model_asks_again(optimizer):
    at = optimizer()
    optimizer.cfg["model"] = "claude-opus-4-7"
    at.run()
    assert len(optimizer.calls) == 2


def test_different_goals_ask_again(optimizer):
    at = optimizer()
    at.session_state["optimizer_goals"] = [{"name": "Casa", "horizon_years": 5}]
    at.run()
    assert len(optimizer.calls) == 2


def test_a_fallback_answer_is_not_kept_so_the_next_rerun_retries(optimizer):
    optimizer.reply["value"] = {"narrative": "texto de respaldo", "core_source": "respaldo",
                                "core_holdings": [], "ai_fallback_reason": "api_error"}
    at = optimizer()
    at.run()
    assert len(optimizer.calls) == 2


def test_reanalyzing_the_universe_forgets_the_answer(optimizer):
    at = optimizer()
    next(b for b in at.sidebar.button if b.label == "🔄 Re-analizar universo").click().run()
    assert "optimizer_ai_advice" not in at.session_state


# --------------------------------------------------------------------------- #
#  La clave                                                                    #
# --------------------------------------------------------------------------- #

def test_the_key_ignores_dict_order_and_float_noise_but_not_real_changes():
    from data.product_ux import optimizer_advice_key

    cfg = SimpleNamespace(provider="claude", model="m")
    base = optimizer_advice_key(_result(60.0), [{"a": 1, "b": 2}], {"X": 0.5, "Y": 0.5}, cfg)
    assert base == optimizer_advice_key(_result(60.0 + 1e-9), [{"b": 2, "a": 1}], {"Y": 0.5, "X": 0.5}, cfg)
    assert base != optimizer_advice_key(_result(61.0), [{"a": 1, "b": 2}], {"X": 0.5, "Y": 0.5}, cfg)
    assert base != optimizer_advice_key(_result(60.0), [{"a": 1, "b": 3}], {"X": 0.5, "Y": 0.5}, cfg)
    assert base != optimizer_advice_key(_result(60.0), [{"a": 1, "b": 2}], {"X": 0.4, "Y": 0.6}, cfg)
    assert base != optimizer_advice_key(_result(60.0), [{"a": 1, "b": 2}], None, cfg)
    assert base != optimizer_advice_key(_result(60.0), [{"a": 1, "b": 2}], {"X": 0.5, "Y": 0.5},
                                        SimpleNamespace(provider="openai", model="m"))
