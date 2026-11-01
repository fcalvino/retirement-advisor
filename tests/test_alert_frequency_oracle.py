"""AUDIT-ALERTAS-FRECUENCIA + AUDIT-UI-7 — la pestaña «Configuración» de Alertas no promete lo que no hace.

La pestaña ofrecía siete controles; el aviso de abajo decía «los cambios son visuales»:

* ``frequency_mode`` («daily / weekly / critical_only») se elegía en la página y ningún código lo leía:
  ``critical_only`` no filtraba nada y ``weekly`` tampoco. Un valor fuera de lista en
  ``ALERT_FREQUENCY_MODE`` además hacía fallar la pestaña entera (``list.index`` lanza ``ValueError``).
* ``check_frequency_hours`` era una copia de ``REPORT.alert_check_interval_hours`` (la misma variable de
  entorno), que es lo que el scheduler sí lee.
* Los cinco ajustes restantes (los cuatro umbrales y las explicaciones de IA) sí tienen lector en el motor,
  pero el widget editable no lo cambia: se muestran de sólo lectura con el valor que rige.
* El selector «Perfil de alertas» arrancaba siempre en «Moderado», ignorando el perfil de las preferencias.

Regla: ``critical_only`` manda sólo las críticas por email/Telegram (todas siguen registradas en el
historial); ``weekly`` y cualquier valor desconocido avisan en el log y rigen como ``daily``; la página
muestra el valor que rige.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alerts.engine import AlertEngine, FiredAlert, effective_frequency_mode
from alerts.store import AlertSeverity, AlertType
from config import ALERTS, REPORT
from tests.test_alert_engine import FakeAlertStore

VIEWS = Path(__file__).resolve().parents[1] / "dashboard" / "views"


class _Recorder:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, message: str, title: str = "") -> None:
        self.sent.append((title, message))


def _alert(sev: AlertSeverity, text: str) -> FiredAlert:
    return FiredAlert(symbol="AAPL", alert_type=AlertType.SCORE_DROP, message=text, severity=sev)


@pytest.fixture
def channel(monkeypatch):
    rec = _Recorder()
    engine = AlertEngine(store=FakeAlertStore())
    engine._notifier = rec
    monkeypatch.setattr(ALERTS, "alerts_enabled", True)
    monkeypatch.setattr(ALERTS, "telegram_enabled", True)
    monkeypatch.setattr(ALERTS, "ai_explanations_enabled", False)
    return rec, engine


MIXED = [
    _alert(AlertSeverity.CRITICAL, "SORR crítico"),
    _alert(AlertSeverity.WARNING, "caída de score"),
    _alert(AlertSeverity.INFO, "oportunidad"),
]


# --- el motor ------------------------------------------------------------------------------------

def test_critical_only_sends_only_the_critical_alerts(channel, monkeypatch):
    rec, engine = channel
    monkeypatch.setattr(ALERTS, "frequency_mode", "critical_only")
    engine.dispatch(MIXED)
    [(title, body)] = rec.sent
    assert "SORR crítico" in body
    assert "caída de score" not in body and "oportunidad" not in body     # before the fix: all three
    assert title.startswith("Retirement Advisor — 1 alert")             # the count is what was sent


def test_critical_only_with_nothing_critical_sends_nothing(channel, monkeypatch):
    rec, engine = channel
    monkeypatch.setattr(ALERTS, "frequency_mode", "critical_only")
    engine.dispatch(MIXED[1:])
    assert rec.sent == []


def test_daily_sends_everything_as_before(channel, monkeypatch):
    rec, engine = channel
    monkeypatch.setattr(ALERTS, "frequency_mode", "daily")
    engine.dispatch(MIXED)
    [(title, body)] = rec.sent
    assert all(t in body for t in ("SORR crítico", "caída de score", "oportunidad"))
    assert "3 alertas" in title


def test_the_alerts_are_still_recorded_in_the_history_when_only_criticals_are_sent(channel, monkeypatch):
    """The filter is on the channel, not on the record: the page's history keeps every alert."""
    rec, engine = channel
    monkeypatch.setattr(ALERTS, "frequency_mode", "critical_only")
    engine.run([{"symbol": "AAPL", "adjusted_score": 70.0, "signal": "BUY", "moat_classification": "Wide"}])
    engine.run([{"symbol": "AAPL", "adjusted_score": 60.0, "signal": "BUY", "moat_classification": "Wide"}])
    assert any(r[3] != AlertSeverity.CRITICAL for r in engine._store.recorded), "the run should record a non-critical alert"
    sent_text = " ".join(body for _t, body in rec.sent)
    for rec_row in engine._store.recorded:
        severity = rec_row[3]
        if severity != AlertSeverity.CRITICAL:
            assert rec_row[2] not in sent_text


@pytest.mark.parametrize("raw, expected", [
    ("daily", "daily"),
    ("critical_only", "critical_only"),
    ("  Critical_Only ", "critical_only"),      # normalised, like the severities
    ("weekly", "daily"),                         # retired: it never did anything
    ("monthly", "daily"),
    ("", "daily"),
])
def test_effective_mode_normalises_and_falls_back_to_daily(monkeypatch, raw, expected):
    monkeypatch.setattr(ALERTS, "frequency_mode", raw)
    assert effective_frequency_mode() == expected


def test_a_value_that_falls_back_is_reported_in_the_log(monkeypatch):
    from loguru import logger

    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level="WARNING")
    try:
        monkeypatch.setattr(ALERTS, "frequency_mode", "weekly")
        effective_frequency_mode()
    finally:
        logger.remove(sink)
    assert any("weekly" in m and "daily" in m for m in seen)


def test_the_duplicate_interval_setting_is_gone():
    assert not hasattr(ALERTS, "check_frequency_hours")


# --- la página -----------------------------------------------------------------------------------

def _page(monkeypatch, tmp_path, *, mode="daily", profile=None):
    from streamlit.testing.v1 import AppTest

    import alerts.store as alert_store_mod
    from data.preferences import UserPreferences

    store = alert_store_mod.AlertStore(db_path=tmp_path / "alerts.db")
    monkeypatch.setattr(alert_store_mod, "alert_store", store)
    monkeypatch.setattr(ALERTS, "frequency_mode", mode)
    at = AppTest.from_file(str(VIEWS / "8_Alertas.py"), default_timeout=60)
    prefs = UserPreferences()
    if profile:
        prefs.default_profile = profile
        prefs.profile_chosen = True
    at.session_state["user_prefs"] = prefs
    at.run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    return at


def _text(at) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [i.value for i in at.info]
    parts += [str(x.value) for x in at.metric] + [str(t.value) for t in at.table]
    for df in at.dataframe:
        parts.append(df.value.to_string())
    return "\n".join(parts)


def test_the_settings_tab_has_no_editable_control_that_does_nothing(monkeypatch, tmp_path):
    at = _page(monkeypatch, tmp_path)
    labels = {w.label for w in at.selectbox} | {w.label for w in at.number_input}
    assert "Modo de frecuencia" not in labels                       # read-only now
    assert "Intervalo entre chequeos (horas)" not in labels
    assert list(at.slider) == []                                    # the four thresholds
    assert not any(c.label == "Explicaciones AI" for c in at.checkbox)
    assert "son visuales" not in _text(at)


def test_the_settings_tab_shows_the_values_that_actually_apply(monkeypatch, tmp_path):
    monkeypatch.setattr(REPORT, "alert_check_interval_hours", 7)      # not the default: a hardcoded 24 would pass
    at = _page(monkeypatch, tmp_path, mode="critical_only")
    text = _text(at)
    assert "Solo críticas" in text
    assert "cada 7 h" in text
    for value in (ALERTS.score_change_threshold, ALERTS.portfolio_loss_threshold_pct,
                  ALERTS.portfolio_drift_threshold_pct, ALERTS.portfolio_rebalance_threshold_pct):
        assert f"{value:g}" in text


@pytest.mark.parametrize("mode", ["weekly", "monthly"])
def test_a_retired_or_invalid_mode_does_not_break_the_tab_and_is_shown_as_daily(monkeypatch, tmp_path, mode):
    """«monthly» is the one the old selector could not place (``list.index`` raised ``ValueError``);
    «weekly» was in its list, so it rendered but did nothing."""
    at = _page(monkeypatch, tmp_path, mode=mode)
    assert "Todas las alertas" in _text(at)
    assert any(mode in w.value and "daily" in w.value for w in at.warning)


def test_the_page_does_not_claim_email_or_ai_that_will_not_work(monkeypatch, tmp_path):
    import config

    monkeypatch.setattr(ALERTS, "email_enabled", True)
    monkeypatch.setattr(ALERTS, "email_from", "yo@example.com")
    monkeypatch.setattr(ALERTS, "smtp_password", "")                  # enabled, but nothing would be sent
    monkeypatch.setattr(ALERTS, "ai_explanations_enabled", True)
    monkeypatch.setattr(config.AI_CONFIG, "enabled", False)
    text = _text(_page(monkeypatch, tmp_path))
    assert "configuración incompleta" in text
    assert "la IA está apagada o falta la clave" in text


def test_the_profile_selector_starts_on_the_saved_profile(monkeypatch, tmp_path):
    at = _page(monkeypatch, tmp_path, profile="Agresivo")
    sel = next(s for s in at.selectbox if s.label == "Perfil de alertas")
    assert sel.value == "Agresivo"                                    # before the fix: always «Moderado»


def test_the_profile_selector_without_a_saved_profile_stays_on_moderado(monkeypatch, tmp_path):
    at = _page(monkeypatch, tmp_path)
    sel = next(s for s in at.selectbox if s.label == "Perfil de alertas")
    assert sel.value == "Moderado"
