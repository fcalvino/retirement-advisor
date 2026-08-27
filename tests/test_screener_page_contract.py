"""Contract of the live Opportunity Screener page (1_Screener.py + row builder).

These tests drive the shipped page source and `_analyse_universe_parallel`.
They document what is already on the page (so an audit cannot treat shipped
work as missing) and what is still a remaining gap (no on_select, first-N
slider, silent drop, cosmetic second-source call).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from analysis.strategy import Decision
from data.product_ux import (
    guided_empty_state,
    second_source_quality_signal,
    universe_quality_summary,
)

ROOT = Path(__file__).resolve().parents[1]
SCREENER = (ROOT / "dashboard" / "pages" / "1_Screener.py").read_text(encoding="utf-8")
STOCK = (ROOT / "dashboard" / "pages" / "2_Stock_Analysis.py").read_text(encoding="utf-8")
SHARED = (ROOT / "dashboard" / "shared.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Page-source contract (observables named in the UX audit)                   #
# --------------------------------------------------------------------------- #


def test_screener_ships_last_run_cache_progress_datos_fuente_sidebar_watchlist():
    """Already-shipped surface — must stay present; not remaining gaps."""
    assert 'st.session_state.get("screener_rows")' in SCREENER
    assert 'st.session_state.get("screener_rows_key")' in SCREENER
    assert 'st.session_state.get("screener_rows_at"' in SCREENER
    assert "Actualizar análisis" in SCREENER
    assert "Máximo de tickers a analizar" in SCREENER
    assert "Agregar a watchlist" in SCREENER
    assert "➕ Agregar" in SCREENER
    assert '"Fuente"' in SCREENER
    assert '"Datos"' in SCREENER
    assert "Calidad de datos (yfinance)" in SCREENER
    # The headline is the funnel now, not a bare buy count (audit item 06).
    assert "_shortlist.steps" in SCREENER
    # The footer used to promise a click that did nothing; it now describes the
    # selection that exists (audit item 10).
    assert "Tocá una fila" in SCREENER
    assert "Analizando…" in SHARED


def test_screener_remaining_gaps_are_still_in_source():
    """Remaining increments the audit ranks — still true on the shipped page."""
    # Stock Analysis still owns its own selector; the Screener deep-links into it
    # rather than that page reaching back into screener state.
    assert "screener_rows" not in STOCK
    assert 'st.session_state.analysis_target' in STOCK

    # 4. The slider no longer slices the raw file order (audit item 17) — it caps
    # a prioritised ordering instead.
    assert "selected = tickers[:max_tickers]" not in SCREENER
    assert "selected = _ordered[:max_tickers]" in SCREENER

    # 9. Guided empty-state helper exists but this page never calls it.
    assert "guided_empty_state" not in SCREENER
    es = guided_empty_state("screener")
    assert es["title"]
    assert "Actualizar análisis" in es["demo_hint"]

    # 17. Company names are hard-truncated in the row builder.
    assert "fund.company_name[:25]" in SHARED

    # 22. Tailwind badge is Spanish now (audit item 25).
    from dashboard.shared import tailwind_badge

    assert "Headwind" not in tailwind_badge("Headwind", -3.0)
    assert "En contra" in tailwind_badge("Headwind", -3.0)


def test_cached_full_analysis_keys_on_engine_version():
    """A scoring rewrite must miss the 1h Streamlit cache of a long-lived process."""
    import inspect

    from config import ENGINE_VERSION
    from dashboard.shared import cached_full_analysis

    params = inspect.signature(cached_full_analysis).parameters
    assert "engine_version" in params
    assert params["engine_version"].default == ENGINE_VERSION
    assert "engine_version: str = ENGINE_VERSION" in SHARED


def test_cached_personal_book_analysis_keys_on_engine_version():
    """A scoring rewrite must miss the 30m Streamlit cache of the personal book."""
    import inspect

    from config import ENGINE_VERSION
    from dashboard.shared import cached_personal_book_analysis

    params = inspect.signature(cached_personal_book_analysis).parameters
    assert "engine_version" in params
    assert params["engine_version"].default == ENGINE_VERSION
    src = SHARED[SHARED.index("def cached_personal_book_analysis") :]
    src = src[: src.index("\ndef ")]
    assert "engine_version: str = ENGINE_VERSION" in src
    assert "_ = engine_version" in src


def test_refresh_clears_only_the_screener_analyses():
    """Audit item 14 — 'Refresh Analysis' must not wipe every cache in the app."""
    refresh_block = SCREENER[SCREENER.index("if refresh:") : SCREENER.index("# Show the last run")]
    code = [ln.strip() for ln in refresh_block.splitlines() if not ln.strip().startswith("#")]
    assert "cached_full_analysis.clear()" in code
    # The global blast survives only as the fallback for older Streamlit builds,
    # i.e. inside the except branch — never on the happy path.
    assert code.index("cached_full_analysis.clear()") < code.index("st.cache_data.clear()")
    assert any(ln.startswith("except Exception") for ln in code)


def test_screener_table_column_order_buries_datos():
    """Banner tells the user to check Datos; Datos is last in the displayed cols."""
    start = SCREENER.index("_all_cols = [")
    end = SCREENER.index("]", SCREENER.index('"Datos",', start))
    cols_block = SCREENER[start:end]
    assert '"Datos"' in cols_block
    assert cols_block.rindex('"Datos"') > cols_block.index('"Ticker"')
    # Quality / decision fields sit after a long fundamental strip.
    assert cols_block.index('"Datos"') > cols_block.index('"P/E"')


def test_second_source_caption_now_derives_its_level_from_the_rows():
    """Audit item 03 — the headline and the per-row column can no longer disagree."""
    # The page must not synthesize a level from the custom-ticker count any more.
    assert '"partial" if _n_custom else "good"' not in SCREENER
    assert "universe_quality_summary(" in SCREENER

    # The universe measured on 2026-08-17: 15 good / 63 partial / 7 poor.
    rollup = universe_quality_summary(
        [{"level": "good", "stale": False}] * 15
        + [{"level": "partial", "stale": False}] * 63
        + [{"level": "poor", "stale": False}] * 7
    )
    assert rollup["level"] == "partial"       # not "good", which is what shipped
    assert rollup["n_total"] == 85
    assert rollup["n_partial"] == 63
    assert rollup["n_poor"] == 7
    assert rollup["degraded_pct"] > 80

    sig = second_source_quality_signal(None, data_quality={"level": rollup["level"]})
    assert sig["status"] == "single_source"
    assert "partial" in sig["message"]
    assert "good" not in sig["message"]


def test_universe_quality_summary_levels_and_empty_case():
    from config import DataQualityConfig

    cfg = DataQualityConfig()

    # Clean universe stays good.
    clean = universe_quality_summary([{"level": "good"}] * 20, config=cfg)
    assert clean["level"] == "good"
    assert clean["degraded_pct"] == 0.0

    # Enough 🔴 on its own tips the whole run to poor.
    poor = universe_quality_summary(
        [{"level": "good"}] * 8 + [{"level": "poor"}] * 2, config=cfg
    )
    assert poor["level"] == "poor"

    # Rows with no dq dict count as not-evaluated, never as good.
    unknown = universe_quality_summary([None] * 5 + [{"level": "good"}] * 5, config=cfg)
    assert unknown["n_unknown"] == 5
    assert unknown["level"] == "partial"

    empty = universe_quality_summary([])
    assert empty["level"] == "unknown"
    assert empty["n_total"] == 0
    assert universe_quality_summary(None)["level"] == "unknown"


def test_universe_quality_summary_accepts_a_pandas_series():
    """The Screener passes df["_dq"] directly — truthiness on a Series raises."""
    import pandas as pd

    series = pd.Series([{"level": "good"}, {"level": "poor"}, None])
    out = universe_quality_summary(series)
    assert out["n_total"] == 3
    assert out["n_good"] == 1
    assert out["n_poor"] == 1
    assert out["n_unknown"] == 1


# --------------------------------------------------------------------------- #
#  Row builder — real `_analyse_universe_parallel`                            #
# --------------------------------------------------------------------------- #


class _FakeBar:
    def progress(self, *_a, **_k):
        return None

    def empty(self):
        return None


class _FakeStatus:
    def __init__(self):
        self.texts: list[str] = []

    def text(self, msg: str):
        self.texts.append(msg)

    def empty(self):
        return None


def _fund(**overrides):
    base = dict(
        company_name="A Very Long Company Name Incorporated",
        sector="Technology",
        adjusted_score=82.0,
        total_score=70.0,
        consistency_score=10.0,
        piotroski_score=7.0,
        moat_score=12.0,
        moat_classification="Wide",
        tailwind_classification="Neutral",
        tailwind_score=0.0,
        pe_ratio=18.0,
        roe=22.0,
        revenue_cagr_5y=8.0,
        dividend_yield=1.2,
        margin_of_safety_pct=5.0,
        current_price=100.0,
        data_quality={"level": "partial", "stale": False},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _tech(signal: str = "NEUTRAL"):
    return SimpleNamespace(signal=signal)


def test_analyse_universe_parallel_builds_shipped_row_and_truncates_name(monkeypatch):
    """Drives the real row builder used by the Screener table."""
    from dashboard import shared as shared_mod

    decision = Decision(symbol="KO", action="HOLD", confidence="MEDIUM")

    def fake_analysis(sym, *_a, **_k):
        return _fund(), _tech("NEUTRAL"), decision

    monkeypatch.setattr(shared_mod, "cached_full_analysis", fake_analysis)
    status = _FakeStatus()
    rows, failures, elapsed = shared_mod._analyse_universe_parallel(
        ["KO"],
        SimpleNamespace(provider="x", model="y", enabled=False, api_key=""),
        _FakeBar(),
        status,
    )
    assert failures == []
    assert elapsed >= 0.0
    assert len(rows) == 1
    row = rows[0]
    assert row["Ticker"] == "KO"
    assert row["Company"] == "A Very Long Company Name "[ :25]
    assert len(row["Company"]) == 25
    assert "HOLD" in row["Signal"]
    assert row["Technical"] == "NEUTRAL"
    assert "Datos" in row
    assert "Viento" in row
    assert row["Clase"] == "equity"
    assert row["_dq"] == {"level": "partial", "stale": False}
    # Item 16 needs to know when each row was measured.
    assert row["_measured_at"]
    assert any("Analizando…" in t and "1/1" in t for t in status.texts)


def test_analyse_universe_parallel_reports_failed_tickers(monkeypatch):
    """Audit item 05 — a failed symbol must leave a named, typed trace."""
    from dashboard import shared as shared_mod

    decision = Decision(symbol="OK", action="BUY", confidence="HIGH")

    def fake_analysis(sym, *_a, **_k):
        if sym == "FAIL":
            raise RuntimeError("yfinance exploded")
        return _fund(company_name="Ok Inc"), _tech("BULLISH"), decision

    monkeypatch.setattr(shared_mod, "cached_full_analysis", fake_analysis)
    rows, failures, _ = shared_mod._analyse_universe_parallel(
        ["OK", "FAIL"],
        SimpleNamespace(provider="x", model="y", enabled=False, api_key=""),
        _FakeBar(),
        _FakeStatus(),
    )
    assert [r["Ticker"] for r in rows] == ["OK"]
    assert len(failures) == 1
    assert failures[0]["Ticker"] == "FAIL"
    assert failures[0]["Tipo"] == "RuntimeError"
    assert "yfinance exploded" in failures[0]["Error"]
    # Asked for 2, measured 1 — the page can now say so instead of showing "1".
    assert len(rows) + len(failures) == 2


def test_screener_page_surfaces_failures_and_offers_retry():
    """The failure payload has to reach the page, not just the log."""
    assert "screener_failures" in SCREENER
    assert "no se pudieron analizar" in SCREENER
    assert "screener_retry" in SCREENER
    # Failed tickers are excluded from the counters, and the page says so.
    assert "no se midieron" in SCREENER


def test_analyse_universe_parallel_tags_funds_and_crypto(monkeypatch):
    """Audit item 01 — the row carries the asset class the page segments on."""
    from dashboard import shared as shared_mod

    decision = Decision(symbol="SPY", action="SELL", confidence="LOW")

    def fake_analysis(sym, *_a, **_k):
        return (
            _fund(company_name="SPDR S&P 500", sector="Index", asset_class="fund",
                  adjusted_score=23.0),
            _tech("BULLISH"),
            decision,
        )

    monkeypatch.setattr(shared_mod, "cached_full_analysis", fake_analysis)
    rows, _, _ = shared_mod._analyse_universe_parallel(
        ["SPY"],
        SimpleNamespace(provider="x", model="y", enabled=False, api_key=""),
        _FakeBar(),
        _FakeStatus(),
    )
    assert rows[0]["Clase"] == "fund"


def test_score_bar_and_custom_fuente_match_table_cells():
    from dashboard.shared import custom_source_badge, score_bar

    bar = score_bar(82)
    assert "82/100" in bar
    assert "█" in bar
    # Without a Streamlit session the custom set is empty → curated (audit item 25).
    assert custom_source_badge("AAPL") == "Curado"


def test_buy_metric_counts_signal_text_not_score():
    """Page metric is Signal.contains('BUY'), so a 82 HOLD does not increment Strong/Buy."""
    import pandas as pd

    df = pd.DataFrame(
        {
            "Signal": ["🟢 BUY", "🟡 HOLD", "🟢 STRONG BUY"],
            "Adj. Score": [99.0, 82.0, 90.0],
        }
    )
    buy_count = int(df["Signal"].str.contains("BUY").sum())
    hold_count = int(df["Signal"].str.contains("HOLD").sum())
    assert buy_count == 2
    assert hold_count == 1
    # High-score HOLD is the visible KO/AMZN case in qa/shots/B_screener_*.png
    assert float(df.loc[df["Signal"].str.contains("HOLD"), "Adj. Score"].iloc[0]) >= 60
