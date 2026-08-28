"""Table selection → next action (audit item 10).

The Screener's footer said, verbatim:

    "💡 Hacé clic en cualquier ticker en la tabla y luego abrí 🔍 Stock Analysis"

but the table was rendered without `on_select`, there was no handoff key, and
Stock Analysis had no idea the Screener existed. The click did nothing: the page
documented a feature that had never been wired. These tests cover the wiring and
guard the promise against drifting back out of sync with the code.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from dashboard.shared import selected_ticker

ROOT = Path(__file__).resolve().parents[1]
SCREENER = (ROOT / "dashboard" / "pages" / "1_Screener.py").read_text(encoding="utf-8")
SHARED = (ROOT / "dashboard" / "shared.py").read_text(encoding="utf-8")
STOCK = (ROOT / "dashboard" / "pages" / "2_Stock_Analysis.py").read_text(encoding="utf-8")
COMITE = (ROOT / "dashboard" / "pages" / "15_Comite.py").read_text(encoding="utf-8")


def _event(rows):
    return SimpleNamespace(selection={"rows": list(rows)})


_DF = pd.DataFrame({
    "Ticker": ["INTU", "META", "GOOGL"],
    "Company": ["Intuit", "Meta", "Alphabet"],
})


# --------------------------------------------------------------------------- #
#  Resolving the selection                                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("idx,expected", [(0, "INTU"), (1, "META"), (2, "GOOGL")])
def test_selection_resolves_to_the_row_ticker(idx, expected):
    assert selected_ticker(_DF, _event([idx])) == expected


def test_no_selection_returns_none():
    assert selected_ticker(_DF, _event([])) is None
    assert selected_ticker(_DF, SimpleNamespace(selection={})) is None
    assert selected_ticker(_DF, SimpleNamespace()) is None
    assert selected_ticker(_DF, None) is None


def test_stale_index_after_a_resort_does_not_blow_up():
    """The table can be re-sorted between reruns; an out-of-range row is not a crash."""
    assert selected_ticker(_DF, _event([99])) is None
    assert selected_ticker(_DF, _event([-1])) is None
    assert selected_ticker(pd.DataFrame({"Ticker": []}), _event([0])) is None


def test_only_the_first_row_is_used():
    """selection_mode is single-row; extra indices are ignored, not concatenated."""
    assert selected_ticker(_DF, _event([1, 2])) == "META"


def test_custom_column():
    assert selected_ticker(_DF, _event([0]), column="Company") == "Intuit"
    assert selected_ticker(_DF, _event([0]), column="Missing") is None


# --------------------------------------------------------------------------- #
#  The page is actually wired                                                 #
# --------------------------------------------------------------------------- #


def test_both_screener_tables_are_selectable():
    """Shortlist and full table — a click has to work wherever the user clicks."""
    assert SCREENER.count('on_select="rerun"') == 2
    assert SCREENER.count('selection_mode="single-row"') == 2
    assert "render_row_actions(_short_df, _short_event" in SCREENER
    assert "render_row_actions(df_view, _all_event" in SCREENER
    # Distinct widget keys, or Streamlit collapses the two tables into one.
    assert 'key="screener_shortlist_select"' in SCREENER
    assert 'key="screener_all_select"' in SCREENER


def test_handoff_uses_the_key_stock_analysis_already_reads():
    """No new protocol: analysis_target is what that page consumes today."""
    assert "st.session_state.analysis_target = symbol" in SHARED
    assert "2_Stock_Analysis.py" in SHARED
    assert 'st.session_state.get("analysis_target")' in STOCK


def test_committee_handoff_uses_that_pages_own_key():
    assert 'st.session_state["comite_last_symbol"] = symbol' in SHARED
    assert 'st.session_state.get("comite_last_symbol")' in COMITE


def test_the_footer_no_longer_promises_a_click_that_does_nothing():
    """The old caption is the exact text audit item 10 quoted."""
    assert "Hacé clic en cualquier ticker en la tabla y luego abrí" not in SCREENER
    assert "Tocá una fila" in SCREENER


def test_actions_offered_are_the_three_that_have_a_destination():
    assert "🔍 Analizar" in SHARED
    assert "📋 Seguir" in SHARED
    assert "🏛️ Comité sobre" in SHARED
