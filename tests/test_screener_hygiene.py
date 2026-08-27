"""Screener hygiene items 12, 19, 22, 23, 24, 25.

Small defects individually; together they were the page's habit of stating things
it had stopped checking — a stale count, an emoji that inverted a verdict, a
description that had drifted 35 tickers away from its own file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.strategy import Decision
from config import SCREENER, SECTOR_MAP
from data.product_ux import SCREENER_COLUMN_SPECS

ROOT = Path(__file__).resolve().parents[1]
SCREENER_SRC = (ROOT / "dashboard" / "pages" / "1_Screener.py").read_text(encoding="utf-8")
SHARED = (ROOT / "dashboard" / "shared.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  12 — the watchlist is edited here and was invisible in the results          #
# --------------------------------------------------------------------------- #


def test_star_column_reaches_every_table():
    assert 'df["⭐"] = df["Ticker"].apply' in SCREENER_SRC
    for marker in ("_short_cols = [", "_all_cols = [", "_other_cols = ["):
        block = SCREENER_SRC[SCREENER_SRC.index(marker) : SCREENER_SRC.index(marker) + 200]
        assert '"⭐"' in block, marker
    assert "⭐" in SCREENER_COLUMN_SPECS


def test_star_is_computed_from_prefs_not_from_the_cached_rows():
    """Following a ticker must show up without re-running a 5-minute analysis."""
    assert "_watched_set" in SCREENER_SRC
    assert "_prefs.watched_tickers" in SCREENER_SRC
    # The row builder stays free of watchlist state.
    assert "watched" not in SHARED.split("def _analyse_universe_parallel")[1][:3000]


def test_watchlist_write_happens_in_a_callback_so_the_counter_is_current():
    """The count used to render before the add, so it lagged a rerun behind."""
    assert "def _add_to_watchlist()" in SCREENER_SRC
    assert "on_click=_add_to_watchlist" in SCREENER_SRC
    add_at = SCREENER_SRC.index("def _add_to_watchlist()")
    count_at = SCREENER_SRC.index("tickers seguidos")
    assert add_at < count_at, "the counter must render after the write"


def test_watchlist_validates_and_allows_removal():
    assert "_WATCH_RE" in SCREENER_SRC
    assert "no parece un ticker válido" in SCREENER_SRC
    assert "_prefs.unwatch(" in SCREENER_SRC
    assert "➖ Quitar" in SCREENER_SRC


@pytest.mark.parametrize("symbol,ok", [
    ("AAPL", True), ("BRK-B", True), ("BTC-USD", True), ("MELI", True),
    ("", False), ("NOT A TICKER", False), ("!!!", False),
    ("TOOOOOOOOOOLONG", False), (".LEADINGDOT", False),
])
def test_ticker_pattern_accepts_real_symbols_and_rejects_junk(symbol, ok):
    import re

    pattern = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
    assert bool(pattern.match(symbol)) is ok


# --------------------------------------------------------------------------- #
#  19 — 78 bars replaced by something the table cannot show                    #
# --------------------------------------------------------------------------- #


def test_ranking_chart_is_capped_and_paired_with_a_distribution():
    assert "SCREENER.chart_top_n" in SCREENER_SRC
    assert SCREENER.chart_top_n == 15
    assert "px.histogram(" in SCREENER_SRC
    # The old unbounded height is gone.
    assert "len(df_equity) * 22" not in SCREENER_SRC
    assert "len(_chart_df) * 22" not in SCREENER_SRC


def test_histogram_marks_the_thresholds_and_the_median():
    chart = SCREENER_SRC[SCREENER_SRC.index("px.histogram(") :]
    assert "STRATEGY.buy_score" in chart
    assert "STRATEGY.strong_buy_score" in chart
    assert "mediana" in chart


def test_page_explains_the_calibration_when_the_median_clears_the_buy_line():
    """The histogram makes item 06's cause visible; the caption names it."""
    assert "La mediana del universo" in SCREENER_SRC
    assert "no contra una lista ya filtrada por calidad" in SCREENER_SRC


# --------------------------------------------------------------------------- #
#  22 — the harshest verdict drawn as the most neutral emoji                   #
# --------------------------------------------------------------------------- #


def test_avoid_has_its_own_emoji():
    assert Decision(symbol="X", action="AVOID").action_emoji == "⛔"


def test_every_action_is_visually_distinct():
    actions = ["STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL", "AVOID"]
    emojis = [Decision(symbol="X", action=a).action_emoji for a in actions]
    assert len(set(emojis)) == len(actions), dict(zip(actions, emojis))
    # And none of them silently falls through to the unknown-action default.
    assert "⚪" not in emojis
    assert Decision(symbol="X", action="WHAT").action_emoji == "⚪"


# --------------------------------------------------------------------------- #
#  23/24 — curated data that had drifted from reality                          #
# --------------------------------------------------------------------------- #


def test_curated_etf_list_covers_the_shipped_universes():
    """Every fund in a shipped universe should also be in the curated fallback."""
    known_funds = {"SPY", "QQQ", "VTI", "BND", "SCHD", "VGT"}
    assert known_funds <= {s.upper() for s in SECTOR_MAP["ETF"]}


def test_universe_description_matches_its_own_ticker_list():
    """The sidebar promised ~120 companies over a file holding 85 tickers."""
    data = json.loads((ROOT / "data" / "universes" / "us_quality.json").read_text())
    n = len(data["tickers"])
    assert n == 85
    assert "120" not in data["description"]
    # The description names the real split: companies + funds + crypto.
    assert "78" in data["description"]
    non_companies = {"SPY", "QQQ", "VTI", "BND", "SCHD", "VGT", "BTC-USD"}
    assert n - len(non_companies) == 78


# --------------------------------------------------------------------------- #
#  25 — English leaking into a Spanish UI                                      #
# --------------------------------------------------------------------------- #


def test_no_english_labels_left_in_the_screener_chrome():
    from dashboard.shared import custom_source_badge, tailwind_badge

    for leak in ("Refresh Analysis", "Max tickers to screen", "Stocks screened",
                 "Strong/Buy signals", "Hold signals", "Sell/Reduce signals"):
        code = "\n".join(
            ln for ln in SCREENER_SRC.splitlines() if not ln.strip().startswith("#")
        )
        assert leak not in code, leak

    assert custom_source_badge("AAPL") == "Curado"
    assert tailwind_badge("Headwind", -3.0).startswith("🌪️")
    assert "En contra" in tailwind_badge("Headwind", -3.0)


def test_spanish_badges_stay_short_enough_for_a_cell():
    from dashboard.shared import tailwind_badge

    for cls in ("Strong", "Moderate", "Headwind"):
        assert len(tailwind_badge(cls, 4.0)) <= 22, cls


# --------------------------------------------------------------------------- #
#  A small universe used to crash the page outright                           #
# --------------------------------------------------------------------------- #


def test_small_universe_does_not_hit_an_inverted_slider_range():
    """`slider(5, len(tickers))` raises when the universe has 5 or fewer tickers.

    Reachable with a small custom universe, and a hard crash rather than a
    degraded page. Found by a runtime test that happened to seed two tickers.
    """
    assert "_SLIDER_FLOOR = 5" in SCREENER_SRC
    assert "if len(tickers) <= _SLIDER_FLOOR:" in SCREENER_SRC
    assert "Universo chico" in SCREENER_SRC
    # The unguarded call is gone.
    assert '"Máximo de tickers a analizar", 5, len(tickers)' not in SCREENER_SRC
