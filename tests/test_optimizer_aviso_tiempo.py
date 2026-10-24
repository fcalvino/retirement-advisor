"""OPT-AVISO-TIEMPO: el aviso de «Analizando N tickers» no promete un tiempo falso.

Decía «(primera vez tarda ~15s)», pero la corrida con los 262 tickers del universo
combinado se midió en 121 s (caché de la copia) y 160 s (base vacía). Ahora no da una
cifra: nombra la cantidad y avisa que un universo grande tarda unos minutos.
"""

from __future__ import annotations

from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "dashboard/views/5_Optimizer.py"


def _run_optimizer(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from dashboard import shared
    from data import preferences as prefs_mod
    from portfolio.tracker import Portfolio

    monkeypatch.setattr(prefs_mod, "_PREFS_PATH", tmp_path / "user_preferences.json")
    # Sin red: el fetch devuelve vacío (la página muestra su error y termina), pero el
    # aviso ya se dibujó antes de llamarlo.
    monkeypatch.setattr(shared, "_fetch_universe_parallel", lambda *a, **k: [])
    prefs = prefs_mod.UserPreferences(default_profile="Moderado", profile_chosen=True)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["user_prefs"] = prefs
    at.session_state["portfolio"] = Portfolio(file_path=tmp_path / "portfolio.json")
    at.run()
    at.button[[b.label for b in at.button].index("🚀 Ejecutar Optimización")].click().run()
    return at


def test_the_progress_notice_names_the_count_and_promises_no_time(tmp_path, monkeypatch):
    at = _run_optimizer(tmp_path, monkeypatch)
    notices = [i.value for i in at.info if "Analizando" in i.value]
    assert len(notices) == 1, [i.value for i in at.info]
    assert "tickers en paralelo" in notices[0]
    assert "~15s" not in notices[0] and "15s" not in notices[0]
    assert "unos minutos" in notices[0]


def test_the_page_no_longer_carries_the_15s_promise():
    assert "~15s" not in PAGE.read_text(encoding="utf-8")
