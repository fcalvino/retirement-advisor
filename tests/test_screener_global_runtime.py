"""The Screener page over the global universe — country filter, currency column
and a ticker without data, driven through AppTest with the analysis stubbed
(no network, no yfinance).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGE = str(ROOT / "dashboard" / "views" / "1_Screener.py")

# (ticker, feed sector, feed country, currency, score). RO.SW's feed returned
# nothing: no sector, no country — the curated universe has to fill them.
_ROWS = [
    ("SAP.DE",  "Technology",        "Germany",       "EUR", 90.0),
    ("SIE.DE",  "Industrials",       "Germany",       "EUR", 80.0),
    ("7203.T",  "Consumer Cyclical", "Japan",         "JPY", 85.0),
    ("SHEL.L",  "Energy",            "United Kingdom", "GBp", 75.0),
    ("AAPL",    "Technology",        "United States", "USD", 95.0),
    ("RO.SW",   "Unknown",           "",              "",    50.0),
]
_NO_DATA = "WALMEX.MX"


def _builder(symbols, ai_cfg, progress_bar, status_text, eta_per_ticker=None):
    from dashboard.shared import data_quality_badge, tailwind_badge

    rows = []
    for tk, sector, country, ccy, score in _ROWS:
        if tk not in symbols:
            continue
        dq = "poor" if tk == "RO.SW" else "good"
        rows.append({
            "Ticker": tk, "Company": tk, "Sector": sector, "País": country,
            "Moneda": ccy, "Clase": "equity", "Signal": "🟩 BUY", "Motivo": "m",
            "Conf.": "MEDIUM", "_why": [], "_risks": [], "_why_headline": "m",
            "Adj. Score": score, "Score bruto": score, "Base Score": score,
            "Consistency": 0.0, "Piotroski": 0, "Moat Score": 0.0, "Moat": "⚪ None",
            "Viento": tailwind_badge("Neutral", 0.0), "Technical": "NEUTRAL",
            "P/E": 20.0, "ROE %": 15.0, "Rev CAGR %": 5.0, "CAGR años": 3,
            "Div Yield %": 1.0, "MoS %": 0.0, "Price": 100.0,
            "Datos": data_quality_badge({"level": dq, "stale": False}),
            "_dq": {"level": dq, "stale": False},
            "_measured_at": datetime.now().isoformat(timespec="seconds"),
        })
    failures = [{"Ticker": _NO_DATA, "Tipo": "ValueError", "Error": "no data"}] \
        if _NO_DATA in symbols else []
    return rows, failures, 1.0


class _Prefs:
    watched_tickers: list = []

    def custom_symbols(self):
        return []


@pytest.fixture
def app(monkeypatch, tmp_path):
    from dashboard import shared as shared_mod
    from data import screener_store

    monkeypatch.setattr(screener_store.screener_run_store, "path", tmp_path / "runs.json")
    monkeypatch.setattr(shared_mod, "_analyse_universe_parallel", _builder)
    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="none", model="", enabled=False, api_key=""
    ))
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["user_prefs"] = _Prefs()
    at.session_state["universe"] = [r[0] for r in _ROWS] + [_NO_DATA]
    at.session_state["active_universe_key"] = "global_quality"
    at.session_state["custom_tickers_in_universe"] = []
    return at.run()


def _full_table(at):
    frames = [d.value for d in at.dataframe if "MoS %" in getattr(d.value, "columns", [])]
    assert frames, "full table not rendered"
    return frames[0]


def test_page_runs_and_shows_country_and_currency(app):
    assert not app.exception, [str(e) for e in app.exception]
    df = _full_table(app)
    assert {"País", "Moneda"} <= set(df.columns)
    got = dict(zip(df["Ticker"], df["Moneda"]))
    assert got["7203.T"] == "JPY" and got["SHEL.L"] == "GBp"


def test_ticker_without_feed_data_is_filled_from_the_curated_universe(app):
    df = _full_table(app)
    ro = df[df["Ticker"] == "RO.SW"].iloc[0]
    assert (ro["País"], ro["Sector"]) == ("Switzerland", "Healthcare")


def test_failed_ticker_is_named_not_dropped(app):
    labels = [e.label for e in app.expander]
    assert any("1 de 7 tickers no se pudieron analizar" in lbl for lbl in labels), labels


def test_country_filter_narrows_the_table(app):
    ms = next(m for m in app.multiselect if m.label == "País")
    assert {"Germany", "Japan", "Switzerland", "United States"} <= set(ms.options)
    app = ms.set_value(["Germany"]).run()
    assert not app.exception
    assert sorted(_full_table(app)["Ticker"]) == ["SAP.DE", "SIE.DE"]


def test_country_and_sector_filters_combine(app):
    next(m for m in app.multiselect if m.label == "País").set_value(["Germany"])
    app = next(m for m in app.multiselect if m.label == "Sector").set_value(["Industrials"]).run()
    assert list(_full_table(app)["Ticker"]) == ["SIE.DE"]
