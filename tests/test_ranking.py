"""Relative ranking + shortlist funnel (audit items 06 and 11).

Measured on US Quality (78 companies, 2026-08-17), before this layer existed:

    señal de compra   67/78 (86 %)      ← presented as the headline answer
    mediana del score 74.8              ← the "Strong Buy ≥75" line, on the median
    topeadas en 100   INTU 107.9 · META 104.0 · GOOGL 103.0, all shown as "100.0"

Item 06 is the first two lines: absolute thresholds calibrated against the whole
market cannot cut a universe that was already filtered for quality, so the screen
approved almost everything. Item 11 is the third: the [0,100] clamp erases
ordering exactly at the top of the ranking.
"""

from __future__ import annotations

import pytest

from analysis.ranking import (
    FilterCriteria,
    FunnelStep,
    apply_filters,
    attach_percentiles,
    build_shortlist,
    filter_preset,
    percentile_ranks,
    preset_gap,
    strip_badge,
)
from config import SCREENER, ScreenerConfig

# --------------------------------------------------------------------------- #
#  Percentiles                                                                #
# --------------------------------------------------------------------------- #


def test_percentile_midrank_definition():
    # 4 distinct values → 12.5 / 37.5 / 62.5 / 87.5 under the mid-rank rule.
    assert percentile_ranks([10, 20, 30, 40]) == [12.5, 37.5, 62.5, 87.5]


def test_ties_share_one_percentile():
    """Item 11's three clamped 100s must not be given three different ranks."""
    out = percentile_ranks([100, 100, 100, 50])
    assert out[0] == out[1] == out[2]
    assert out[3] < out[0]


def test_degenerate_inputs():
    assert percentile_ranks([]) == []
    assert percentile_ranks([42]) == [50.0]
    assert percentile_ranks([7, 7]) == [50.0, 50.0]


def test_percentile_is_relative_to_the_run_not_absolute():
    """The same score means different things in different universes — the point."""
    strong_field = percentile_ranks([95, 92, 90, 88])
    weak_field = percentile_ranks([95, 40, 30, 20])
    assert strong_field[0] == weak_field[0]   # top of its own field either way
    # But a 90 is mid-pack in one and would be top in the other.
    assert percentile_ranks([95, 92, 90, 88])[2] == 37.5


# --------------------------------------------------------------------------- #
#  The uncapped score restores the ordering the clamp destroyed               #
# --------------------------------------------------------------------------- #


_CLAMPED = [
    {"Ticker": "INTU",  "Adj. Score": 100.0, "Score bruto": 107.9},
    {"Ticker": "META",  "Adj. Score": 100.0, "Score bruto": 104.0},
    {"Ticker": "GOOGL", "Adj. Score": 100.0, "Score bruto": 103.0},
    {"Ticker": "ADBE",  "Adj. Score":  99.7, "Score bruto":  99.7},
]


def test_uncapped_score_separates_names_the_clamp_merged():
    ranked = attach_percentiles(_CLAMPED)
    pcts = {r["Ticker"]: r["Percentil"] for r in ranked}
    # All three display 100.0 but are genuinely ordered.
    assert pcts["INTU"] > pcts["META"] > pcts["GOOGL"] > pcts["ADBE"]


def test_falls_back_to_the_capped_score_when_raw_is_absent():
    rows = [{"Ticker": "A", "Adj. Score": 90.0}, {"Ticker": "B", "Adj. Score": 50.0}]
    ranked = attach_percentiles(rows)
    assert ranked[0]["Percentil"] > ranked[1]["Percentil"]


def test_attach_percentiles_does_not_mutate_the_input():
    rows = [{"Ticker": "A", "Adj. Score": 90.0}]
    attach_percentiles(rows)
    assert "Percentil" not in rows[0]


# --------------------------------------------------------------------------- #
#  The funnel                                                                 #
# --------------------------------------------------------------------------- #


def _row(tk, score, signal="🟩 BUY", dq="good", sector="Technology"):
    return {
        "Ticker": tk, "Company": f"{tk} Inc", "Sector": sector,
        "Adj. Score": min(score, 100.0), "Score bruto": score,
        "Signal": signal, "_dq": {"level": dq, "stale": False},
    }


def test_funnel_records_every_narrowing_step():
    rows = attach_percentiles([_row(f"T{i}", 100 - i) for i in range(20)])
    result = build_shortlist(rows)

    labels = [s.label for s in result.steps]
    assert labels[0] == "Analizadas"
    assert result.steps[0].kept == 20
    assert any("datos suficientes" in l for l in labels)
    assert any("señal de compra" in l for l in labels)
    assert any("top" in l.lower() for l in labels)
    # Every step accounts for what it dropped.
    for step in result.steps[1:]:
        assert isinstance(step, FunnelStep)
        assert step.kept + step.dropped == result.steps[result.steps.index(step) - 1].kept


def test_shortlist_actually_excludes():
    """The whole complaint: 86% approved. A screen has to cut."""
    rows = attach_percentiles([_row(f"T{i}", 100 - i) for i in range(78)])
    result = build_shortlist(rows)
    assert result.n_analyzed == 78
    assert result.n_selected <= SCREENER.shortlist_max_names
    assert result.n_selected < 78 * 0.5


def test_poor_data_and_non_buy_signals_are_dropped():
    rows = attach_percentiles([
        _row("GOOD", 99),
        _row("POOR", 98, dq="poor"),
        _row("HOLD", 97, signal="🟡 HOLD"),
        _row("SELL", 96, signal="🔴 SELL"),
    ])
    result = build_shortlist(rows)
    assert [r["Ticker"] for r in result.rows] == ["GOOD"]


def test_cap_is_applied_and_reported():
    rows = attach_percentiles([_row(f"T{i}", 100 - i * 0.1) for i in range(40)])
    cfg = ScreenerConfig(shortlist_max_names=5, shortlist_percentile=50.0)
    result = build_shortlist(rows, config=cfg)
    assert result.n_selected == 5
    assert result.truncated_by_cap > 0
    assert any("Top 5" in s.label for s in result.steps)


def test_shortlist_is_ordered_by_the_uncapped_score():
    """INTU/META/GOOGL all show 100.0; the shortlist must still order them."""
    rows = attach_percentiles([
        _row("INTU", 107.9), _row("META", 104.0), _row("GOOGL", 103.0), _row("LOW", 40.0),
    ])
    assert {r["Adj. Score"] for r in rows if r["Ticker"] != "LOW"} == {100.0}
    result = build_shortlist(rows, config=ScreenerConfig(shortlist_percentile=0.0))
    assert [r["Ticker"] for r in result.rows][:3] == ["INTU", "META", "GOOGL"]


def test_a_row_with_no_signal_is_not_shortlisted():
    """Defensive: absence of a verdict is not a buy verdict."""
    rows = attach_percentiles([
        {"Ticker": "NOSIG", "Adj. Score": 99.0, "Score bruto": 99.0, "Sector": "Tech"},
    ])
    assert build_shortlist(rows).n_selected == 0


def test_empty_shortlist_is_a_valid_answer_and_says_so():
    rows = attach_percentiles([_row("A", 90, signal="🟡 HOLD")])
    result = build_shortlist(rows)
    assert result.n_selected == 0
    assert "ninguna" in result.summary()
    assert "resultado válido" in result.summary()


def test_summary_states_the_funnel_honestly():
    rows = attach_percentiles([_row(f"T{i}", 100 - i) for i in range(78)])
    result = build_shortlist(rows)
    summary = result.summary()
    assert "78" in summary
    assert str(result.n_selected) in summary


def test_no_rows_does_not_crash():
    result = build_shortlist([])
    assert result.n_selected == 0
    assert result.steps and result.steps[0].kept == 0


def test_funnel_labels_stay_short_enough_for_a_metric_column():
    """st.metric truncates long labels in narrow columns ('En el top 25% del u…')."""
    rows = attach_percentiles([_row(f"T{i}", 100 - i) for i in range(20)])
    for step in build_shortlist(rows).steps:
        assert len(step.label) <= 22, f"label too long for st.metric: {step.label!r}"
        # The detail carries the explanation instead.
        assert step.label != step.detail


def test_thresholds_come_from_config():
    rows = attach_percentiles([_row(f"T{i}", 100 - i) for i in range(20)])
    strict = build_shortlist(rows, config=ScreenerConfig(shortlist_percentile=95.0,
                                                        shortlist_max_names=0))
    loose = build_shortlist(rows, config=ScreenerConfig(shortlist_percentile=10.0,
                                                       shortlist_max_names=0))
    assert strict.n_selected < loose.n_selected
    assert SCREENER.shortlist_percentile == 75.0
    assert SCREENER.shortlist_max_names == 10


# --------------------------------------------------------------------------- #
#  The page wires it up                                                       #
# --------------------------------------------------------------------------- #


def test_screener_shows_the_funnel_not_a_bare_buy_count():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "1_Screener.py").read_text()
    assert "build_shortlist" in src
    assert "attach_percentiles" in src
    assert "_shortlist.summary()" in src
    # The old headline counter is gone.
    assert '"Strong/Buy signals"' not in src
    assert '"Hold signals"' not in src
    # Percentile and the uncapped score reach the table.
    assert '"Percentil"' in src
    assert '"Score bruto"' in src
    # Concentration warning (item 07) rides on the shortlist.
    assert "concentration_warn_pct" in src


# --------------------------------------------------------------------------- #
#  Filters (audit item 09)                                                    #
# --------------------------------------------------------------------------- #


def _frow(tk, score=80.0, signal="🟩 BUY", dq="good", sector="Technology",
          moat="🏰 Wide", pct=50.0, company=None):
    return {
        "Ticker": tk, "Company": company or f"{tk} Corporation", "Sector": sector,
        "Adj. Score": score, "Score bruto": score, "Signal": signal, "Moat": moat,
        "Percentil": pct, "_dq": {"level": dq, "stale": False},
    }


_ROWS = [
    _frow("AAPL", 90, sector="Technology", pct=90),
    _frow("JNJ", 70, sector="Healthcare", signal="🟡 HOLD", moat="🟢 Narrow", pct=50),
    _frow("XOM", 55, sector="Energy", signal="🔴 SELL", dq="poor", moat="⚪ None", pct=20),
    _frow("KO", 78, sector="Consumer Staples", signal="🟢 STRONG BUY", dq="partial", pct=70),
]


def test_no_criteria_returns_everything():
    crit = FilterCriteria()
    assert not crit.is_active()
    assert len(apply_filters(_ROWS, crit)) == len(_ROWS)


def test_search_matches_ticker_or_company_case_insensitively():
    assert [r["Ticker"] for r in apply_filters(_ROWS, FilterCriteria(search="aapl"))] == ["AAPL"]
    assert [r["Ticker"] for r in apply_filters(_ROWS, FilterCriteria(search="Corporation"))] == \
        ["AAPL", "JNJ", "XOM", "KO"]
    assert apply_filters(_ROWS, FilterCriteria(search="zzz")) == []


def test_signal_filter_does_not_match_on_substring():
    """Selecting BUY must not drag in STRONG BUY — the emoji-prefixed trap."""
    only_buy = apply_filters(_ROWS, FilterCriteria(signals=("BUY",)))
    assert [r["Ticker"] for r in only_buy] == ["AAPL"]
    only_strong = apply_filters(_ROWS, FilterCriteria(signals=("STRONG BUY",)))
    assert [r["Ticker"] for r in only_strong] == ["KO"]
    both = apply_filters(_ROWS, FilterCriteria(signals=("BUY", "STRONG BUY")))
    assert {r["Ticker"] for r in both} == {"AAPL", "KO"}


def test_sector_moat_quality_and_percentile_filters():
    assert [r["Ticker"] for r in apply_filters(_ROWS, FilterCriteria(sectors=("Energy",)))] == ["XOM"]
    assert [r["Ticker"] for r in apply_filters(_ROWS, FilterCriteria(moats=("Wide",)))] == ["AAPL", "KO"]
    assert [r["Ticker"] for r in apply_filters(_ROWS, FilterCriteria(quality_levels=("poor",)))] == ["XOM"]
    assert [r["Ticker"] for r in apply_filters(_ROWS, FilterCriteria(min_percentile=70))] == ["AAPL", "KO"]
    assert [r["Ticker"] for r in apply_filters(_ROWS, FilterCriteria(min_score=80))] == ["AAPL"]


def test_criteria_combine_as_and():
    crit = FilterCriteria(sectors=("Technology", "Consumer Staples"), min_percentile=80)
    assert [r["Ticker"] for r in apply_filters(_ROWS, crit)] == ["AAPL"]


def test_watchlist_filter_uses_the_injected_list():
    crit = FilterCriteria(only_watchlist=True)
    assert [r["Ticker"] for r in apply_filters(_ROWS, crit, watchlist=["ko", " jnj "])] == \
        ["JNJ", "KO"]
    assert apply_filters(_ROWS, crit, watchlist=[]) == []


def test_filters_preserve_order_and_do_not_mutate():
    out = apply_filters(_ROWS, FilterCriteria(min_percentile=40))
    assert [r["Ticker"] for r in out] == ["AAPL", "JNJ", "KO"]
    out[0]["Ticker"] = "MUTATED"
    assert _ROWS[0]["Ticker"] == "AAPL"


@pytest.mark.parametrize("badge,expected", [
    ("🟢 STRONG BUY", "STRONG BUY"), ("🟩 BUY", "BUY"), ("🏰 Wide", "Wide"),
    ("⚪ None", "None"), ("—", ""), ("", ""), (None, ""), ("Wide", "Wide"),
])
def test_strip_badge(badge, expected):
    assert strip_badge(badge) == expected


def test_every_preset_is_a_valid_criteria():
    for name in SCREENER.filter_presets:
        crit = filter_preset(name)
        assert isinstance(crit, FilterCriteria)
        assert crit.is_active(), f"preset {name!r} filters nothing"
        # And it runs against real-shaped rows without blowing up.
        apply_filters(_ROWS, crit, watchlist=["KO"])


def test_unknown_preset_is_a_no_op_not_a_crash():
    assert filter_preset("no existe") == FilterCriteria()


def test_filters_never_touch_the_funnel():
    """Item 09 must not silently redefine what 'top 25%' means (item 06)."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "1_Screener.py").read_text()
    funnel_at = src.index("build_shortlist(_ranked)")
    filters_at = src.index("apply_filters(")
    assert funnel_at < filters_at, "the funnel must be computed before any filtering"
    assert "_visible" not in src[:funnel_at]
    # The page says so out loud.
    assert "Los filtros afectan solo esta tabla" in src


# --------------------------------------------------------------------------- #
#  A preset that cannot be applied has to say so                              #
# --------------------------------------------------------------------------- #
# Streamlit *drops* multiselect values that are not among the options instead of
# raising. So "Lo que descarté" (HOLD/REDUCE/SELL/AVOID) over a run that is 86 %
# buy signals seeded nothing, and the page showed all 78 rows with the preset's
# name still in the box — a filter doing the exact opposite of what it says.


def test_preset_gap_names_what_the_run_could_not_offer():
    requested = FilterCriteria(signals=("SELL", "AVOID"), quality_levels=("good",))
    effective = FilterCriteria(quality_levels=("good",))       # signals were dropped
    assert preset_gap(requested, effective) == {"Señal": ("SELL", "AVOID")}


def test_preset_gap_is_empty_when_the_preset_landed_whole():
    crit = FilterCriteria(signals=("BUY",), quality_levels=("good",))
    assert preset_gap(crit, crit) == {}


def test_preset_gap_reports_only_the_values_that_were_dropped():
    requested = FilterCriteria(signals=("STRONG BUY", "BUY"))
    effective = FilterCriteria(signals=("BUY",))
    assert preset_gap(requested, effective) == {"Señal": ("STRONG BUY",)}


def test_preset_gap_covers_the_moat_axis_that_motivated_it():
    """'Foso ancho' asks on `moats` — the axis the page never wired to a widget."""
    requested = filter_preset("Foso ancho")
    assert requested.moats == ("Wide",)
    assert preset_gap(requested, FilterCriteria()) == {"Foso": ("Wide",)}
    assert preset_gap(requested, FilterCriteria(moats=("Wide",))) == {}


def test_preset_gap_ignores_axes_that_cannot_be_dropped():
    """A search string and a percentile floor are typed, not chosen from options."""
    requested = FilterCriteria(search="AAPL", min_percentile=75.0, only_watchlist=True)
    assert preset_gap(requested, FilterCriteria()) == {}


def test_preset_gap_does_not_fire_when_the_user_unchecks_a_value_the_run_has():
    """U7-1: widgets ≠ available. SELL is in the run; the user dropped it by hand."""
    requested = FilterCriteria(signals=("SELL", "HOLD"))
    available = FilterCriteria(signals=("SELL", "HOLD", "BUY"))
    assert preset_gap(requested, available) == {}


def test_preset_gap_still_names_a_value_no_ticker_in_the_run_carries():
    """The original lie: preset asks SELL, this run has none."""
    requested = FilterCriteria(signals=("SELL", "AVOID"))
    available = FilterCriteria(signals=("BUY", "STRONG BUY"))
    assert preset_gap(requested, available) == {"Señal": ("SELL", "AVOID")}


def test_apply_filters_honours_the_moat_axis():
    """The engine side always worked; only the UI wiring was missing."""
    rows = [
        {"Ticker": "MSFT", "Moat": "🏰 Wide"},
        {"Ticker": "HD", "Moat": "🟢 Narrow"},
        {"Ticker": "X", "Moat": "⚪ None"},
    ]
    kept = apply_filters(rows, FilterCriteria(moats=("Wide",)))
    assert [r["Ticker"] for r in kept] == ["MSFT"]
