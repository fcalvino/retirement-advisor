"""AUDIT-NUMB-4 (PR-1) — el coach «Caída de cartera» dice contra qué mide.

El coach (`coach_should_fire_on_drop`, `check_market_drop_coach`) mide el retorno ACUMULADO de la cartera
contra el costo promedio de las posiciones (`run_scheduler._check_market_drop_coach`: valor / costo − 1) o,
sin posiciones, contra los precios con que se guardó el plan (`weighted_delta_pct`). Pero el mensaje decía
«📉 Caída de cartera −8,0 %»: se lee como una caída reciente, y quien está −8 % desde hace meses lo recibía
cada 72 h sin saber que no cayó nada. Además el tipo `market_drop_coach` no figuraba en las etiquetas del
historial ni entre los tipos que se pueden silenciar (se mostraba el identificador crudo y no había cómo
silenciarlo), y el prompt de explicación del LLM no lo conocía.

Regla de este PR: el texto dice «por debajo de tu costo promedio» (o «de los precios con que guardaste tu plan»)
y que es el resultado acumulado, no una caída reciente; el tipo se rotula y se puede silenciar; el prompt le dice
al modelo la base de la cifra. Sin red, sin LLM.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alerts.store import AlertType
from data.product_ux import (
    ALERT_TYPE_LABELS,
    coach_should_fire_on_drop,
)

VIEWS = Path(__file__).resolve().parents[1] / "dashboard" / "views"


def _coach(**over):
    args = {"portfolio_return_pct": -12.0, "drop_threshold_pct": 8.0, "plan_prob_target_pct": 70.0}
    args.update(over)
    return coach_should_fire_on_drop(**args)


# --- el texto --------------------------------------------------------------------------------------

def test_the_message_says_it_is_below_the_average_cost_not_a_recent_drop():
    d = _coach()
    assert d["should_fire"] is True
    assert "12.0% por debajo de tu costo promedio" in d["message"]
    assert "acumulado" in d["message"] and "no una caída reciente" in d["message"]
    assert "Caída de cartera" not in d["message"]          # the prefix that read as a recent move


def test_the_fallback_basis_names_the_prices_the_plan_was_saved_at():
    d = _coach(basis="plan_saved")
    assert "12.0% por debajo de los precios con que guardaste tu plan" in d["message"]
    assert "costo promedio" not in d["message"]
    assert d["context"]["basis"] == "plan_saved"


def test_the_default_basis_is_the_cost_and_travels_in_the_context():
    assert _coach()["context"]["basis"] == "cost"


def test_the_warning_branch_is_just_as_honest():
    d = _coach(portfolio_return_pct=-15.0, plan_prob_target_pct=20.0)
    assert d["severity"] == "warning"
    assert "15.0% por debajo de tu costo promedio" in d["message"]
    assert "Caída de cartera" not in d["message"]


def test_no_branch_of_the_message_calls_the_accumulated_result_a_recent_fall():
    """The warning branch kept «La cartera cayó…» and the no-probability one «desvío de corto plazo»."""
    for kw in ({}, {"plan_prob_target_pct": 20.0}, {"plan_prob_target_pct": None}):
        msg = _coach(**kw)["message"]
        assert "cayó" not in msg and "corto plazo" not in msg and "Caída" not in msg, msg
        assert "no una caída reciente" in msg


def test_a_nan_return_does_not_fire_a_coach_that_says_nan():
    assert _coach(portfolio_return_pct=float("nan"))["should_fire"] is False
    assert _coach(portfolio_return_pct=float("-inf"))["should_fire"] is False


def test_the_alert_type_labels_are_unique_so_the_mute_form_loses_no_type():
    assert len(set(ALERT_TYPE_LABELS.values())) == len(ALERT_TYPE_LABELS)


def test_the_threshold_is_still_what_decides_and_a_gain_never_fires():
    assert _coach(portfolio_return_pct=-7.9)["should_fire"] is False
    assert _coach(portfolio_return_pct=-8.0)["should_fire"] is True
    assert _coach(portfolio_return_pct=+12.0)["should_fire"] is False


def test_an_unknown_basis_is_refused_and_not_worded_as_cost():
    with pytest.raises(ValueError):
        _coach(basis="whatever")


# --- el motor y el scheduler ------------------------------------------------------------------------

def test_the_engine_passes_the_basis_through():
    from unittest.mock import MagicMock

    from alerts.engine import AlertEngine
    from alerts.store import AlertSeverity
    from tests.test_alert_engine import FakeAlertStore

    eng = AlertEngine.__new__(AlertEngine)
    eng._store, eng._notifier, eng._min_severity = FakeAlertStore(), MagicMock(), AlertSeverity.INFO
    fired = eng.check_market_drop_coach(
        portfolio_return_pct=-12.0, plan_name="Demo", plan_prob_target_pct=65.0, basis="plan_saved"
    )
    assert fired is not None and "precios con que guardaste tu plan" in fired.message


class _Plan:
    name = "Demo"
    mc_summary = {"prob_target_pct": 65.0}
    refreshed_metrics = {"summary": {"weighted_delta_pct": -18.5}}


class _Engine:
    def __init__(self):
        self.calls = []

    def check_market_drop_coach(self, **kw):
        self.calls.append(kw)
        return None


def _scheduler(monkeypatch):
    import types

    import scripts.run_scheduler as sched

    mod = types.ModuleType("data.plan_context")
    mod.get_active_plan = lambda: _Plan()
    monkeypatch.setitem(__import__("sys").modules, "data.plan_context", mod)
    return sched


def test_the_scheduler_says_cost_when_it_measured_positions_and_plan_saved_when_it_fell_back(monkeypatch):
    sched = _scheduler(monkeypatch)
    drift = ({"A": {"shares": 10, "avg_cost": 200.0}}, {"A": 150.0}, {}, "l")
    e1 = _Engine()
    sched._check_market_drop_coach(e1, drift)
    assert e1.calls[0]["basis"] == "cost" and e1.calls[0]["portfolio_return_pct"] == pytest.approx(-25.0)
    e2 = _Engine()
    sched._check_market_drop_coach(e2, None)
    assert e2.calls[0]["basis"] == "plan_saved" and e2.calls[0]["portfolio_return_pct"] == pytest.approx(-18.5)


def test_a_book_with_no_quote_at_all_falls_back_to_the_plan_basis(monkeypatch):
    sched = _scheduler(monkeypatch)
    engine = _Engine()
    sched._check_market_drop_coach(engine, ({"A": {"shares": 10, "avg_cost": 100.0}}, {}, {}, "l"))
    assert engine.calls[0]["basis"] == "plan_saved"


# --- el tipo en la pantalla --------------------------------------------------------------------------

def test_every_alert_type_has_a_label_so_none_is_shown_as_a_raw_identifier():
    missing = [t.value for t in AlertType if t.value not in ALERT_TYPE_LABELS]
    assert missing == []
    assert ALERT_TYPE_LABELS[AlertType.MARKET_DROP_COACH.value] == "Coach de cartera"


def _alertas(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from alerts import store as alert_store_mod

    store = alert_store_mod.AlertStore(db_path=tmp_path / "alerts.db")
    store.record(
        AlertType.MARKET_DROP_COACH, "COACH:Demo", "📉 Tu cartera está 12.0% por debajo de tu costo promedio",
        alert_store_mod.AlertSeverity.INFO,
    )
    monkeypatch.setattr(alert_store_mod, "alert_store", store)
    app = AppTest.from_file(str(VIEWS / "8_Alertas.py"), default_timeout=60)
    app.run()
    assert not app.exception
    return app


def test_the_history_filter_and_the_mute_form_know_the_coach(tmp_path, monkeypatch):
    app = _alertas(tmp_path, monkeypatch)
    type_filter = next(s for s in app.selectbox if s.label == "Tipo")
    assert "Coach de cartera" in type_filter.options          # not «market_drop_coach»
    assert "market_drop_coach" not in type_filter.options
    mute_type = next(s for s in app.selectbox if s.label == "Tipo de alerta")
    assert "Coach de cartera" in mute_type.options


# --- el prompt de explicación -----------------------------------------------------------------------

def test_the_explanation_prompt_tells_the_model_what_the_figure_is_measured_against():
    from analysis.prompts import alert_explanation_prompt

    ctx = {"portfolio_return_pct": -12.0, "threshold_pct": -8.0, "basis": "cost", "plan_name": "Demo"}
    text = alert_explanation_prompt("market_drop_coach", "COACH:Demo", ctx)
    assert "costo promedio" in text and "no una caída reciente" in text
    other = alert_explanation_prompt("market_drop_coach", "COACH:Demo", {**ctx, "basis": "plan_saved"})
    assert "precios con que se guardó tu plan" in other
    # Other alert types are not touched.
    assert "no una caída reciente" not in alert_explanation_prompt("score_drop", "AAPL", {"prev_score": 80})
