"""Contract of the live Opportunity Screener page (1_Screener.py + row builder).

These tests drive the shipped page source and `_analyse_universe_parallel`.
They document what is already on the page (so an audit cannot treat shipped
work as missing) and what is still a remaining gap (no on_select, first-N
slider, silent drop, cosmetic second-source call).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from analysis.strategy import Decision
from data.product_ux import guided_empty_state, second_source_quality_signal

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
    assert "Refresh Analysis" in SCREENER
    assert "Max tickers to screen" in SCREENER
    assert "Agregar a watchlist" in SCREENER
    assert "➕ Agregar" in SCREENER
    assert '"Fuente"' in SCREENER
    assert '"Datos"' in SCREENER
    assert "Calidad de datos (yfinance)" in SCREENER
    assert "Strong/Buy signals" in SCREENER
    assert "Hold signals" in SCREENER
    assert "Sell/Reduce signals" in SCREENER
    assert "Stocks screened" in SCREENER
    assert "Hacé clic en cualquier ticker" in SCREENER
    assert "Analizando…" in SHARED


def test_screener_remaining_gaps_are_still_in_source():
    """Remaining increments the audit ranks — still true on the shipped page."""
    # 1. Click-through is a caption only: dataframe has no selection API.
    df_block = SCREENER[SCREENER.index("st.dataframe") : SCREENER.index("st.plotly_chart")]
    assert "on_select" not in df_block
    assert "selection_mode" not in df_block
    # Stock Analysis does not consume a screener-clicked ticker.
    assert "screener_rows" not in STOCK
    assert 'st.session_state.analysis_target' in STOCK

    # 4. Slider takes a prefix of the universe, not top-N by score.
    assert "selected = tickers[:max_tickers]" in SCREENER

    # 8. Refresh nukes every Streamlit data cache, not just screener rows.
    assert "st.cache_data.clear()" in SCREENER

    # 9. Guided empty-state helper exists but this page never calls it.
    assert "guided_empty_state" not in SCREENER
    es = guided_empty_state("screener")
    assert es["title"]
    assert "Refresh Analysis" in es["demo_hint"]

    # 16. Second-source call is universe-level and passes reconciliation=None.
    assert "second_source_quality_signal(" in SCREENER
    assert "reconciliation" not in SCREENER.split("second_source_quality_signal", 1)[1][:200]

    # 17. Company names are hard-truncated in the row builder.
    assert "fund.company_name[:25]" in SHARED

    # 22. Headwind badge still leaks English.
    from dashboard.shared import tailwind_badge

    assert "Headwind" in tailwind_badge("Headwind", -3.0)
    assert "frente" not in tailwind_badge("Headwind", -3.0).lower()


def test_screener_table_column_order_buries_datos():
    """Banner tells the user to check Datos; Datos is last in the displayed cols."""
    start = SCREENER.index('df[[')
    end = SCREENER.index("].rename", start)
    cols_block = SCREENER[start:end]
    assert '"Datos"' in cols_block
    assert cols_block.rindex('"Datos"') > cols_block.index('"Ticker"')
    # Quality / decision fields sit after a long fundamental strip.
    assert cols_block.index('"Datos"') > cols_block.index('"P/E"')


def test_second_source_caption_as_the_page_calls_it_ignores_per_row_datos():
    """1_Screener.py synthesizes dq from custom-count, not from the Datos column."""
    # No customs → page passes level=good even if some rows are 🟡.
    good = second_source_quality_signal(
        None,
        data_quality={"level": "good", "stale": False},
    )
    assert good["status"] == "single_source"
    assert "good" in good["message"]
    assert good["n_conflicts"] == 0

    fake_partial = second_source_quality_signal(
        None,
        data_quality={"level": "partial", "stale": False},
    )
    assert fake_partial["status"] == "single_source"
    assert "partial" in fake_partial["message"]


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
    rows = shared_mod._analyse_universe_parallel(
        ["KO"],
        SimpleNamespace(provider="x", model="y", enabled=False, api_key=""),
        _FakeBar(),
        status,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["Ticker"] == "KO"
    assert row["Company"] == "A Very Long Company Name "[ :25]
    assert len(row["Company"]) == 25
    assert "HOLD" in row["Signal"]
    assert row["Technical"] == "NEUTRAL"
    assert "Datos" in row
    assert "Viento" in row
    assert any("Analizando…" in t and "1/1" in t for t in status.texts)


def test_analyse_universe_parallel_silently_drops_failed_tickers(monkeypatch):
    """Failed symbols vanish: no row, no warning payload — audit item #6."""
    from dashboard import shared as shared_mod

    decision = Decision(symbol="OK", action="BUY", confidence="HIGH")

    def fake_analysis(sym, *_a, **_k):
        if sym == "FAIL":
            raise RuntimeError("yfinance exploded")
        return _fund(company_name="Ok Inc"), _tech("BULLISH"), decision

    monkeypatch.setattr(shared_mod, "cached_full_analysis", fake_analysis)
    rows = shared_mod._analyse_universe_parallel(
        ["OK", "FAIL"],
        SimpleNamespace(provider="x", model="y", enabled=False, api_key=""),
        _FakeBar(),
        _FakeStatus(),
    )
    assert [r["Ticker"] for r in rows] == ["OK"]
    # The builder returns only successes; the page then does len(df) as Stocks screened.
    assert len(rows) == 1


def test_score_bar_and_custom_fuente_match_table_cells():
    from dashboard.shared import custom_source_badge, score_bar

    bar = score_bar(82)
    assert "82/100" in bar
    assert "█" in bar
    # Without a Streamlit session the custom set is empty → Default (English).
    assert custom_source_badge("AAPL") == "Default"


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
