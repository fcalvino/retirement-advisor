"""Screener column presentation (audit items 08 + 18).

Item 08: the table was sorted by `Adj. Score`, but that column was not displayed.
In its place sat `Score Bar` — an ASCII string like "████████░░  82/100". Clicking
that header sorts the *string*, so the resulting order looks reasonable and is
wrong. Worse than a missing feature: a working-looking one that lies.

Item 18: none of the 22 columns had any `column_config`, so numbers printed as
raw floats (P/E "21.6356", ROE "29.8489"), Price had no currency, and no column
carried a tooltip saying what it measures.
"""

from __future__ import annotations

from pathlib import Path

from data.product_ux import SCREENER_COLUMN_SPECS, screener_column_spec

ROOT = Path(__file__).resolve().parents[1]
SCREENER = (ROOT / "dashboard" / "pages" / "1_Screener.py").read_text(encoding="utf-8")
SHARED = (ROOT / "dashboard" / "shared.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  The specs themselves                                                       #
# --------------------------------------------------------------------------- #


def test_every_spec_is_well_formed():
    for col, spec in SCREENER_COLUMN_SPECS.items():
        assert spec["kind"] in {"text", "number", "progress"}, col
        assert spec.get("help"), f"{col} has no tooltip — item 18 is about explaining columns"
        if spec["kind"] == "progress":
            assert "min" in spec and "max" in spec, col
            assert spec["max"] > spec["min"], col
        if spec["kind"] in {"number", "progress"}:
            assert spec.get("format"), col


def test_progress_ranges_match_the_scales_the_labels_promise():
    """A '/15' label with a 0–100 bar would be a new lie, not a fix."""
    assert SCREENER_COLUMN_SPECS["Adj. Score"]["max"] == 100
    assert SCREENER_COLUMN_SPECS["Consist./15"]["max"] == 15
    assert SCREENER_COLUMN_SPECS["Piotroski/9"]["max"] == 9
    assert SCREENER_COLUMN_SPECS["Moat/20"]["max"] == 20


def test_percent_columns_render_a_percent_sign():
    for col in ("ROE %", "Rev CAGR %", "Div Yield %", "MoS %"):
        assert "%%" in SCREENER_COLUMN_SPECS[col]["format"], col


def test_price_is_money_and_counts_are_integers():
    assert SCREENER_COLUMN_SPECS["Price"]["format"].startswith("$")
    assert SCREENER_COLUMN_SPECS["Piotroski/9"]["format"] == "%d"
    assert SCREENER_COLUMN_SPECS["CAGR años"]["format"].startswith("%d")


def test_helps_explain_the_traps_we_already_fixed():
    """The tooltips are where the hard-won caveats live."""
    assert "ESTA corrida" in SCREENER_COLUMN_SPECS["Percentil"]["help"]
    assert "sin el tope" in SCREENER_COLUMN_SPECS["Score bruto"]["help"]
    assert "4 estados anuales" in SCREENER_COLUMN_SPECS["CAGR años"]["help"]
    assert "experimental" in SCREENER_COLUMN_SPECS["Fuente"]["help"]


def test_spec_lookup_copies_and_tolerates_unknown_columns():
    spec = screener_column_spec("Price")
    spec["format"] = "MUTATED"
    assert SCREENER_COLUMN_SPECS["Price"]["format"] == "$%.2f"
    assert screener_column_spec("no existe") is None


# --------------------------------------------------------------------------- #
#  The page uses them                                                         #
# --------------------------------------------------------------------------- #


def test_ascii_score_bar_is_gone_from_the_tables():
    """Audit item 08 — the bar that sorted lexicographically."""
    code = "\n".join(
        ln for ln in SCREENER.splitlines() if not ln.strip().startswith("#")
    )
    assert '"Score Bar"' not in code
    # And the row builder stops producing a field nobody reads.
    assert '"Score Bar"' not in SHARED
    # The helper still exists for plain-text callers, with a warning attached.
    assert "def score_bar(" in SHARED
    assert "sorts the *text*" in SHARED


def test_adj_score_is_displayed_so_the_sort_column_is_visible():
    start = SCREENER.index("_all_cols = [")
    cols = SCREENER[start : SCREENER.index("]", SCREENER.index('"Datos",', start))]
    assert '"Adj. Score"' in cols
    assert '"Score bruto"' in cols
    assert '"Percentil"' in cols


def test_all_three_tables_get_a_column_config():
    """Shortlist, full table and the funds table."""
    assert SCREENER.count("column_config=screener_column_config(") == 3
    assert "screener_column_config(_short_cols)" in SCREENER
    assert "screener_column_config(_all_cols)" in SCREENER
    assert "screener_column_config(_other_cols)" in SCREENER


def test_every_displayed_column_has_a_spec():
    """A column with no spec silently falls back to unformatted output."""
    import re

    for marker in ("_short_cols = [", "_all_cols = [", "_other_cols = ["):
        start = SCREENER.index(marker)
        block = SCREENER[start : SCREENER.index("]", SCREENER.index('"Datos",', start))]
        for col in re.findall(r'"([^"]+)"', block):
            assert col in SCREENER_COLUMN_SPECS, f"{col} (in {marker}) has no spec"


def test_renamed_columns_are_the_ones_specced():
    """The frame is renamed before display; specs must use the displayed names."""
    assert '"Consistency": "Consist./15"' in SCREENER
    assert "Consist./15" in SCREENER_COLUMN_SPECS
    assert "Consistency" not in SCREENER_COLUMN_SPECS
    assert "Moat/20" in SCREENER_COLUMN_SPECS
    assert "Moat Score" not in SCREENER_COLUMN_SPECS
