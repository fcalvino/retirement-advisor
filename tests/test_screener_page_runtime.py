"""Runtime smoke tests for the Opportunity Screener page (audit items 01/03/05).

Source-grep contracts prove the code says the right thing; these prove the page
actually *runs* and renders it. They drive `1_Screener.py` through Streamlit's
AppTest with the analysis layer stubbed, so no network and no yfinance.

The fixture mirrors what was measured on the US Quality universe on 2026-08-17:
two companies, the six pooled vehicles that came out as the six worst of 85 with
a SELL signal each, one coin, and one symbol that blows up on fetch.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGE = str(ROOT / "dashboard" / "pages" / "1_Screener.py")

# (ticker, company, sector, asset_class, score, action, dq_level)
_FIXTURE = [
    ("INTU",    "Intuit Inc.",      "Technology", "equity", 100.0, "BUY",   "partial"),
    ("GOOGL",   "Alphabet Inc.",    "Communication Services", "equity", 99.0, "BUY", "partial"),
    ("SPY",     "SPDR S&P 500",     "Index",      "fund",   23.0,  "SELL",  "good"),
    ("QQQ",     "Invesco QQQ",      "Index",      "fund",   23.0,  "SELL",  "good"),
    ("VTI",     "Vanguard Total",   "Index",      "fund",   23.0,  "SELL",  "good"),
    ("BND",     "Vanguard Bond",    "Index",      "fund",   25.0,  "SELL",  "good"),
    ("SCHD",    "Schwab Dividend",  "Unknown",    "fund",   25.0,  "SELL",  "poor"),
    ("VGT",     "Vanguard IT ETF",  "Unknown",    "fund",   22.0,  "SELL",  "poor"),
    ("BTC-USD", "Bitcoin",          "Crypto",     "crypto", 37.0,  "REDUCE", "good"),
]
_FAILING = "BROKEN"


def _fake_row_builder():
    """Stand-in for `_analyse_universe_parallel` returning (rows, failures)."""
    from dashboard.shared import data_quality_badge, tailwind_badge

    def _build(symbols, ai_cfg, progress_bar, status_text, eta_per_ticker=None):
        rows = []
        for tk, name, sector, cls, score, action, dq in _FIXTURE:
            if tk not in symbols:
                continue
            rows.append({
                "Ticker": tk,
                "Company": name,
                "Sector": sector,
                "Clase": cls,
                "Signal": f"⚪ {action}",
                "Motivo": f"motivo de {tk}",
                "Conf.": "MEDIUM",
                "_why": [f"razón A de {tk}", f"razón B de {tk}"],
                "_risks": [f"riesgo de {tk}"],
                "_why_headline": f"motivo completo de {tk}",
                "Adj. Score": score,
                "Base Score": score,
                "Consistency": 0.0,
                "Piotroski": 0,
                "Moat Score": 0.0,
                "Moat": ("🏰 Wide" if tk == "INTU" else "⚪ None"),
                "Viento": tailwind_badge("Neutral", 0.0),
                "Technical": "BULLISH",
                "P/E": 20.0,
                "ROE %": 15.0,
                "Rev CAGR %": 5.0,
                "CAGR años": 3,
                "Div Yield %": 1.5,
                "MoS %": 0.0,
                "Price": 100.0,
                "Datos": data_quality_badge({"level": dq, "stale": False}),
                "_dq": {"level": dq, "stale": False},
                "_measured_at": datetime.now().isoformat(timespec="seconds"),
            })
        failures = [
            {"Ticker": _FAILING, "Tipo": "RuntimeError", "Error": "yfinance exploded"}
        ] if _FAILING in symbols else []
        # A thread pool yields in completion order, never request order. Reversing
        # here keeps the page honest about that (it once made the stored-run cache
        # miss on every load and re-analyse the whole universe).
        rows.reverse()
        # Proportional to the work asked for, so a partial rerun that measures one
        # ticker cannot be mistaken for a measurement of the whole run.
        return rows, failures, 0.5 * max(len(symbols), 1)

    return _build


@pytest.fixture
def app(monkeypatch, tmp_path):
    from dashboard import shared as shared_mod
    from data import screener_store

    # Point the run cache at a temp file so these tests never read or clobber a
    # real run sitting in data/screener_last_run.json.
    monkeypatch.setattr(screener_store.screener_run_store, "path", tmp_path / "runs.json")
    monkeypatch.setattr(shared_mod, "_analyse_universe_parallel", _fake_row_builder())
    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="none", model="", enabled=False, api_key=""
    ))

    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["universe"] = [t[0] for t in _FIXTURE] + [_FAILING]
    at.session_state["custom_tickers_in_universe"] = []
    return at.run()


class _FakePrefs:
    watched_tickers: list = []

    def watch(self, _sym):   # pragma: no cover — not exercised here
        return True

    def custom_symbols(self):
        return []


def _all_text(at) -> str:
    chunks = []
    for coll in (at.markdown, at.caption, at.warning, at.info, at.subheader, at.error, at.success):
        chunks += [getattr(e, "value", "") or "" for e in coll]
    return "\n".join(chunks)


def test_page_runs_without_exception(app):
    assert not app.exception, [str(e) for e in app.exception]


def test_funds_and_crypto_are_not_in_the_ranked_table(app):
    """Audit item 01 — the six SELL-flagged vehicles leave the equity ranking."""
    assert not app.exception
    equity_df, other_df = app.dataframe[-2].value, app.dataframe[-1].value

    assert list(equity_df["Ticker"]) == ["INTU", "GOOGL"]
    assert set(other_df["Ticker"]) == {"SPY", "QQQ", "VTI", "BND", "SCHD", "VGT", "BTC-USD"}

    # No score and no signal reach the non-fundamental table.
    for banned in ("Signal", "Score Bar", "Adj. Score", "Moat"):
        assert banned not in other_df.columns

    # And the class label is human, not the internal key.
    assert set(other_df["Clase"]) == {"Fondo / ETF", "Cripto"}


def test_funnel_counts_companies_only(app):
    """Audit item 06 — the headline is a funnel, and it starts at the companies."""
    assert not app.exception
    labels = {m.label: m.value for m in app.metric}
    # 2 companies analyzed; the 6 SELL funds and the coin never enter the funnel.
    assert labels["Analizadas"] == "2"
    assert "Con datos suficientes" in labels
    assert any("top" in l.lower() for l in labels)
    # No step can exceed the number of companies.
    assert all(int(v) <= 2 for v in labels.values())


def test_quality_headline_matches_the_rows(app):
    """Audit item 03 — no more 'calidad good' over a majority-degraded run."""
    assert not app.exception
    text = _all_text(app)
    # 4 good / 2 partial / 2 poor + 1 crypto good = degraded well past threshold.
    assert "calidad partial" in text or "calidad poor" in text
    assert "calidad good" not in text
    assert "🟡 2 parciales" in text
    assert "🔴 2 pobres" in text


def test_failed_ticker_is_named_not_swallowed(app):
    """Audit item 05 — the broken symbol is reported, with a retry offered."""
    assert not app.exception
    text = _all_text(app) + "\n".join(
        (e.label or "") for e in app.expander
    ) + "\n".join((b.label or "") for b in app.button)
    assert _FAILING in "\n".join(
        str(df.value.to_dict()) for df in app.dataframe
    ) or _FAILING in text
    assert "no se pudieron analizar" in text
    assert any("Reintentar" in (b.label or "") for b in app.button)


def test_funnel_does_not_pretend_the_run_was_complete(app):
    """Asked for 10, 9 measured, 1 failed — the page has to say so alongside the funnel."""
    assert not app.exception
    text = _all_text(app)
    assert "fallaron y no entraron en ningún paso" in text


def test_tables_are_selectable_and_prompt_for_a_click(app):
    """Audit item 10 — the click the footer promises now exists."""
    assert not app.exception
    text = _all_text(app)
    assert "Tocá una fila" in text
    # Nothing selected yet, so no action buttons for a ticker are shown.
    assert not any("Analizar" in (b.label or "") for b in app.button)


def test_selecting_a_row_offers_the_three_handoffs(app):
    """With a row selected, the page must offer analyze / watch / committee."""
    assert not app.exception
    app.session_state["screener_shortlist_select"] = {"selection": {"rows": [0], "columns": []}}
    out = app.run()
    assert not out.exception
    labels = [b.label or "" for b in out.button]
    assert any(l.startswith("🔍 Analizar") for l in labels), labels
    assert any(l.startswith("📋 Seguir") for l in labels), labels
    assert any(l.startswith("🏛️ Comité sobre") for l in labels), labels
    # The buttons name the ticker that was actually selected (top of shortlist).
    assert any("INTU" in l or "GOOGL" in l for l in labels), labels


def test_filters_narrow_the_table_without_touching_the_funnel(app):
    """Audit item 09 — filtering is a lens on the table, not a new funnel."""
    assert not app.exception
    before = {m.label: m.value for m in app.metric}

    # Search is a free text input — unlike the multiselects it has no options
    # constraint, so the filter genuinely engages instead of being dropped.
    app.session_state["flt_search"] = "INTU"
    out = app.run()
    assert not out.exception

    after = {m.label: m.value for m in out.metric}
    assert after == before, "the funnel must not react to table filters"
    # 1 of the 2 companies survives the search.
    assert "Mostrando **1** de 2 acciones" in _all_text(out)


def test_clear_filters_button_resets_state_without_raising(app):
    """Streamlit forbids writing a widget's key after it is instantiated.

    Doing this inline (instead of in an on_click callback) raised
    StreamlitAPIException the moment the user pressed the button — the page's
    logic was right and the page was still broken.
    """
    assert not app.exception
    app.session_state["flt_search"] = "INTU"
    out = app.run()
    assert not out.exception

    clear = [b for b in out.button if "Limpiar" in (b.label or "")]
    assert clear, "no clear-filters button while a filter is active"
    cleared = clear[0].click().run()
    assert not cleared.exception, [str(e) for e in cleared.exception]
    assert cleared.session_state["flt_search"] == ""
    assert "Mostrando **" not in _all_text(cleared)


def test_a_filter_matching_nothing_keeps_the_rest_of_the_page(app):
    """An empty result must not st.stop() the funds section off the page."""
    assert not app.exception
    app.session_state["flt_search"] = "no-existe-este-ticker"
    out = app.run()
    assert not out.exception
    text = _all_text(out)
    assert "Ningún ticker cumple estos filtros" in text
    # The funds section still renders below.
    assert "Fondos, ETFs y cripto" in text


def test_shortlist_summary_states_the_narrowing(app):
    """'De N analizadas, M pasan' — the sentence audit item 06 asked for."""
    assert not app.exception
    text = _all_text(app)
    assert "analizadas" in text.lower()
    assert "criterios" in text.lower()


# --------------------------------------------------------------------------- #
#  Persistence + partial refresh (audit items 15/16)                          #
# --------------------------------------------------------------------------- #


def _seed_stored_run(tmp_path, monkeypatch, *, rows, duration_s=46.8,
                     failures=(), measured_n=0, ran_at=None):
    """Put a previous run on disk, as if the user had run the page yesterday."""
    from data import screener_store

    store = screener_store.ScreenerRunStore(tmp_path / "runs.json")
    monkeypatch.setattr(screener_store.screener_run_store, "path", store.path)
    run = screener_store.ScreenerRun(
        universe_key="default", duration_s=duration_s, measured_n=measured_n,
        rows=rows, failures=list(failures),
    )
    if ran_at:
        run.ran_at = ran_at
    store.save(run)
    return store


def _equity_row(ticker: str, *, hours_ago: float = 0.0) -> dict:
    """Minimal equity row the live page can rank without going back to the analyser."""
    from dashboard.shared import data_quality_badge, tailwind_badge

    measured = (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    return {
        "Ticker": ticker,
        "Company": ticker,
        "Sector": "Technology",
        "Clase": "equity",
        "Signal": "🟢 BUY",
        "Motivo": f"motivo de {ticker}",
        "Conf.": "MEDIUM",
        "_why": [f"razón de {ticker}"],
        "_risks": [],
        "_why_headline": f"motivo de {ticker}",
        "Adj. Score": 80.0,
        "Score bruto": 80.0,
        "Base Score": 70.0,
        "Consistency": 0.0,
        "Piotroski": 0,
        "Moat Score": 0.0,
        "Moat": "⚪ None",
        "Viento": tailwind_badge("Neutral", 0.0),
        "Technical": "BULLISH",
        "P/E": 20.0,
        "ROE %": 15.0,
        "Rev CAGR %": 5.0,
        "CAGR años": 3,
        "Div Yield %": 1.5,
        "MoS %": 0.0,
        "Price": 100.0,
        "Datos": data_quality_badge({"level": "good", "stale": False}),
        "_dq": {"level": "good", "stale": False},
        "_measured_at": measured,
    }


def test_subset_of_covered_does_not_overwrite_or_reanalyse(monkeypatch, tmp_path):
    """Slider default (25) against a stored run of 30 must be a hit.

    Equality of selected vs covered used to miss, re-run the 25-ticker prefix,
    and overwrite screener_last_run.json — silent loss of the other names.
    """
    from dashboard import shared as shared_mod
    from data.screener_store import screener_run_store

    tickers = [f"T{i:02d}" for i in range(30)]
    stored_rows = [_equity_row(t) for t in tickers]
    store = _seed_stored_run(tmp_path, monkeypatch, rows=stored_rows, duration_s=90.0,
                             measured_n=30)
    before = [r["Ticker"] for r in store.load("default").rows]

    calls = []

    def _never(symbols, *a, **k):
        calls.append(list(symbols))
        return [], [], 0.0

    monkeypatch.setattr(shared_mod, "_analyse_universe_parallel", _never)
    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="none", model="", enabled=False, api_key=""))
    logged = []
    monkeypatch.setattr(shared_mod, "log_screener_run", lambda rows: logged.append(rows) or 0)

    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["universe"] = tickers
    at.session_state["custom_tickers_in_universe"] = []
    out = at.run()

    assert not out.exception, [str(e) for e in out.exception]
    assert calls == [], f"re-analysed covered tickers: {calls}"
    assert logged == [], "hit path must not re-log the stored run"
    after = [r["Ticker"] for r in screener_run_store.load("default").rows]
    assert after == before
    assert len(after) == 30
    assert "Mostrando la última corrida" in _all_text(out)


def test_uncovered_subset_merges_instead_of_replacing(monkeypatch, tmp_path):
    """Selected 25, stored 20 → analyse only the 5 new names and keep the 20."""
    from dashboard import shared as shared_mod
    from data.screener_store import screener_run_store

    tickers = [f"T{i:02d}" for i in range(30)]
    stored = [_equity_row(t) for t in tickers[:20]]
    _seed_stored_run(tmp_path, monkeypatch, rows=stored, duration_s=80.0, measured_n=20)

    calls = []

    def _build(symbols, *a, **k):
        calls.append(list(symbols))
        return [_equity_row(s) for s in symbols], [], 0.4 * len(symbols)

    monkeypatch.setattr(shared_mod, "_analyse_universe_parallel", _build)
    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="none", model="", enabled=False, api_key=""))
    logged = []
    monkeypatch.setattr(shared_mod, "log_screener_run", lambda rows: logged.append(
        [r["Ticker"] for r in rows]) or 0)

    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["universe"] = tickers
    at.session_state["custom_tickers_in_universe"] = []
    out = at.run()

    assert not out.exception, [str(e) for e in out.exception]
    # Default slider is 25; first 20 are covered, so only T20–T24 are new.
    assert calls and calls[0] == tickers[20:25], calls
    assert logged == [tickers[20:25]], logged
    saved = [r["Ticker"] for r in screener_run_store.load("default").rows]
    assert saved[:20] == tickers[:20]
    assert set(saved) == set(tickers[:25])
    assert len(saved) == 25


def test_stored_run_loads_without_re_analysing(monkeypatch, tmp_path):
    """Audit item 15 — reopening the app must not cost another cold run."""
    from datetime import datetime as _dt

    from dashboard import shared as shared_mod

    calls = []

    def _never(*a, **k):
        calls.append(a)
        return [], [], 0.0

    stored_rows = [
        {**r, "_measured_at": _dt.now().isoformat(timespec="seconds")}
        for r in _fake_row_builder()(["INTU", "GOOGL"], None, _Bar(), _Status())[0]
    ]
    _seed_stored_run(tmp_path, monkeypatch, rows=stored_rows)
    monkeypatch.setattr(shared_mod, "_analyse_universe_parallel", _never)
    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="none", model="", enabled=False, api_key=""))

    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["universe"] = ["INTU", "GOOGL"]
    at.session_state["custom_tickers_in_universe"] = []
    out = at.run()

    assert not out.exception, [str(e) for e in out.exception]
    assert calls == [], "the page re-analysed instead of using the stored run"
    assert "Mostrando la última corrida" in _all_text(out)


def test_stale_rows_offer_a_partial_refresh(monkeypatch, tmp_path):
    """Audit item 16 — refresh the few that aged out, not all of them."""
    from datetime import datetime as _dt, timedelta as _td

    from dashboard import shared as shared_mod

    old = (_dt.now() - _td(hours=99)).isoformat(timespec="seconds")
    stored_rows = _fake_row_builder()(["INTU", "GOOGL"], None, _Bar(), _Status())[0]
    stored_rows[0]["_measured_at"] = old                      # one stale
    stored_rows[1]["_measured_at"] = _dt.now().isoformat(timespec="seconds")

    _seed_stored_run(tmp_path, monkeypatch, rows=stored_rows)
    monkeypatch.setattr(shared_mod, "_analyse_universe_parallel", _fake_row_builder())
    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="none", model="", enabled=False, api_key=""))

    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["universe"] = ["INTU", "GOOGL"]
    at.session_state["custom_tickers_in_universe"] = []
    out = at.run()

    assert not out.exception
    assert "Actualización parcial disponible" in _all_text(out)
    refresh_btns = [b for b in out.button if "Refrescar" in (b.label or "")]
    assert refresh_btns, [b.label for b in out.button]
    # It offers the one stale ticker, not both.
    assert "1" in refresh_btns[0].label
    after = refresh_btns[0].click().run()
    assert not after.exception, [str(e) for e in after.exception]


class _Bar:
    def progress(self, *_a, **_k):
        return None

    def empty(self):
        return None


class _Status:
    def text(self, *_a, **_k):
        return None

    def empty(self):
        return None


# --------------------------------------------------------------------------- #
#  Regressions found auditing the page for bugs (2026-08-18)                  #
# --------------------------------------------------------------------------- #


def _make_app(monkeypatch, universe, builder=None):
    """An AppTest for one universe, with the analysis layer stubbed."""
    from dashboard import shared as shared_mod

    monkeypatch.setattr(shared_mod, "_analyse_universe_parallel", builder or _fake_row_builder())
    monkeypatch.setattr(shared_mod, "_get_ai_config", lambda **_k: SimpleNamespace(
        provider="none", model="", enabled=False, api_key=""))
    at = AppTest.from_file(PAGE, default_timeout=30)
    at.session_state["user_prefs"] = _FakePrefs()
    at.session_state["universe"] = list(universe)
    at.session_state["custom_tickers_in_universe"] = []
    return at


def test_a_universe_with_no_companies_lists_the_funds_instead_of_crashing(monkeypatch, tmp_path):
    """A custom universe of ETFs killed the page with KeyError: 'Score bruto'.

    `attach_percentiles([])` returns `[]`, whose DataFrame has no columns at all,
    so sorting it by "Score bruto" blew up — before the funds table that exists
    precisely for these assets ever got drawn.
    """
    from data import screener_store

    monkeypatch.setattr(screener_store.screener_run_store, "path", tmp_path / "runs.json")
    funds = ["SPY", "QQQ", "VTI", "BND", "SCHD", "VGT", "BTC-USD"]
    out = _make_app(monkeypatch, funds).run()

    assert not out.exception, [str(e) for e in out.exception]
    text = _all_text(out)
    assert "Fondos, ETFs y cripto" in text
    assert "no hay ranking que calcular" in text
    # Every one of them is listed, none of them is scored.
    listed = out.dataframe[-1].value
    assert set(listed["Ticker"]) == set(funds)
    assert "Adj. Score" not in listed.columns


def test_a_failed_ticker_does_not_invalidate_the_stored_run(monkeypatch, tmp_path):
    """Audit item 15 was cancelled by one yfinance hiccup.

    The session cache key came off the stored rows only, so a run that lost a
    ticker produced a key that could never match the requested universe — and
    every reopen paid the full cold run again.
    """
    from dashboard import shared as shared_mod

    calls = []

    def _never(*a, **k):
        calls.append(a)
        return [], [], 0.0

    stored_rows = [
        {**r, "_measured_at": datetime.now().isoformat(timespec="seconds")}
        for r in _fake_row_builder()(["INTU", "GOOGL"], None, _Bar(), _Status())[0]
    ]
    _seed_stored_run(
        tmp_path, monkeypatch, rows=stored_rows,
        failures=[{"Ticker": _FAILING, "Tipo": "RuntimeError", "Error": "yfinance exploded"}],
    )
    at = _make_app(monkeypatch, ["INTU", "GOOGL", _FAILING])
    monkeypatch.setattr(shared_mod, "_analyse_universe_parallel", _never)
    out = at.run()

    assert not out.exception, [str(e) for e in out.exception]
    assert calls == [], "one failed ticker sent the page back into a full cold run"
    assert "Mostrando la última corrida" in _all_text(out)
    # And the failure is still reported (the expander carries its own label).
    assert any("no se pudieron analizar" in (e.label or "") for e in out.expander), \
        [e.label for e in out.expander]


def test_a_partial_refresh_does_not_deflate_the_next_eta(monkeypatch, tmp_path):
    """Audit item 13, reintroduced through the partial-refresh path of item 16.

    Refreshing 3 stale tickers stored *their* seconds against *all* the rows, so
    `seconds_per_ticker` collapsed and the next cold run was announced in seconds.
    """
    from data.screener_store import screener_run_store

    stored_rows = _fake_row_builder()(["INTU", "GOOGL"], None, _Bar(), _Status())[0]
    stored_rows[0]["_measured_at"] = (datetime.now() - timedelta(hours=99)).isoformat(timespec="seconds")
    stored_rows[1]["_measured_at"] = datetime.now().isoformat(timespec="seconds")

    # 170s for 2 tickers = 85 s/ticker, i.e. an expensive universe.
    _seed_stored_run(tmp_path, monkeypatch, rows=stored_rows,
                     duration_s=170.0, measured_n=2)
    before = screener_run_store.load("default").seconds_per_ticker()
    assert before == pytest.approx(85.0)

    out = _make_app(monkeypatch, ["INTU", "GOOGL"]).run()
    assert not out.exception, [str(e) for e in out.exception]
    refresh = [b for b in out.button if "Refrescar" in (b.label or "")]
    assert refresh, [b.label for b in out.button]
    after_click = refresh[0].click().run()
    assert not after_click.exception, [str(e) for e in after_click.exception]

    after = screener_run_store.load("default").seconds_per_ticker()
    assert after == pytest.approx(before), (
        f"refreshing one ticker rewrote the measured throughput ({before} → {after})"
    )


def test_a_partial_refresh_updates_the_timestamp_it_shows(monkeypatch, tmp_path):
    """'Mostrando la última corrida (12/07 08:00)' after refreshing it just now."""
    stored_rows = _fake_row_builder()(["INTU", "GOOGL"], None, _Bar(), _Status())[0]
    stored_rows[0]["_measured_at"] = (datetime.now() - timedelta(hours=99)).isoformat(timespec="seconds")
    stored_rows[1]["_measured_at"] = datetime.now().isoformat(timespec="seconds")
    _seed_stored_run(tmp_path, monkeypatch, rows=stored_rows,
                     ran_at="2026-07-12T08:00:00")

    out = _make_app(monkeypatch, ["INTU", "GOOGL"]).run()
    assert "07-12 08:00" in _all_text(out)          # the stored run, as saved

    refresh = [b for b in out.button if "Refrescar" in (b.label or "")]
    after = refresh[0].click().run()
    assert not after.exception, [str(e) for e in after.exception]
    # One more natural rerun is what shows the cached-run caption again.
    text = _all_text(after.run())
    assert "07-12 08:00" not in text, "the page still claims the pre-refresh time"
    assert datetime.now().strftime("%d/%m") in text


def test_the_moat_preset_actually_filters(monkeypatch, tmp_path):
    """'Foso ancho' asks on an axis the page never wired to a widget.

    `apply_filters` supported it all along, so selecting the preset cleared every
    other filter and applied nothing — the full table under a name promising a
    slice of it.
    """
    from data import screener_store

    monkeypatch.setattr(screener_store.screener_run_store, "path", tmp_path / "runs.json")
    out = _make_app(monkeypatch, [t[0] for t in _FIXTURE]).run()
    assert not out.exception, [str(e) for e in out.exception]

    preset = [s for s in out.selectbox if (s.label or "") == "Preset"][0]
    filtered = preset.select("Foso ancho").run()

    assert not filtered.exception, [str(e) for e in filtered.exception]
    text = _all_text(filtered)
    assert "🔎 Mostrando" in text, "the preset was selected but nothing was filtered"
    # INTU is the only Wide moat in the fixture.
    assert list(filtered.dataframe[-2].value["Ticker"]) == ["INTU"]


def test_a_preset_that_matches_nothing_says_so(monkeypatch, tmp_path):
    """Streamlit drops out-of-options values silently; the page must not.

    'Lo que descarté' asks for HOLD/REDUCE/SELL/AVOID over a run that is all buy
    signals: the multiselect ends up empty and the table shows everything, with
    the preset's name still in the box.
    """
    from data import screener_store

    monkeypatch.setattr(screener_store.screener_run_store, "path", tmp_path / "runs.json")
    out = _make_app(monkeypatch, [t[0] for t in _FIXTURE]).run()
    preset = [s for s in out.selectbox if (s.label or "") == "Preset"][0]
    empty = preset.select("Lo que descarté").run()

    assert not empty.exception, [str(e) for e in empty.exception]
    text = _all_text(empty)
    assert "ese filtro no se aplicó" in text
    assert "Lo que descarté" in text


def test_a_shortlist_without_sectors_does_not_break_the_concentration_warning(
    monkeypatch, tmp_path
):
    """`value_counts()` drops nulls, so an all-null Sector column is empty."""
    from data import screener_store

    monkeypatch.setattr(screener_store.screener_run_store, "path", tmp_path / "runs.json")
    inner = _fake_row_builder()

    def _no_sectors(symbols, *a, **k):
        rows, failures, elapsed = inner(symbols, *a, **k)
        for row in rows:
            row["Sector"] = None
        return rows, failures, elapsed

    out = _make_app(monkeypatch, [t[0] for t in _FIXTURE], builder=_no_sectors).run()
    assert not out.exception, [str(e) for e in out.exception]
    assert "analizadas" in _all_text(out).lower()


def test_a_row_from_an_older_vintage_is_not_filed_as_a_fund(monkeypatch, tmp_path):
    """A null "Clase" is unknown, not "not a company".

    The guard only covered the column being absent from *every* row. Mixed
    vintages leave it present and null for the older ones, and null is falsy for
    `is_fundamentally_scorable` — so real equities dropped into the funds table,
    labelled with the literal string "nan".
    """
    from data import screener_store

    monkeypatch.setattr(screener_store.screener_run_store, "path", tmp_path / "runs.json")
    inner = _fake_row_builder()

    def _mixed(symbols, *a, **k):
        rows, failures, elapsed = inner(symbols, *a, **k)
        for row in rows:
            if row["Ticker"] == "GOOGL":      # as written by the previous version
                row.pop("Clase")
        return rows, failures, elapsed

    out = _make_app(monkeypatch, [t[0] for t in _FIXTURE], builder=_mixed).run()

    assert not out.exception, [str(e) for e in out.exception]
    equity_df, other_df = out.dataframe[-2].value, out.dataframe[-1].value
    assert "GOOGL" in list(equity_df["Ticker"]), "an equity was filed under funds"
    assert "GOOGL" not in list(other_df["Ticker"])
    assert "nan" not in {str(c) for c in other_df["Clase"]}
