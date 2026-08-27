"""Contract of the moving-average vocabulary shown to a person (U1-3).

``TechnicalAnalyzer`` fetches ``period="10y", interval="1wk"`` and then takes
``price.rolling(200).mean()``. Those 200 bars are 200 **weeks** — 1400 days,
~3,8 years — while every surface called the number "SMA200", which a reader
resolves to the classic 200 *days* (~9,5 months). Two different indicators, one
name. The 100- and 50-bar averages carried the same gap, and the Golden Cross
note names two of them in a single sentence.

U1-3 decided the **name** was wrong, not the window: a ~3,8-year trend filter is
the right length for a 5–30 year retirement horizon, and moving it to the
classic weekly window would flip signals across the universe and force a
recalibration of the 25 points ``_derive_signal`` pays for ``above_sma200`` and
of the ``require_technical_uptrend`` gate in ``analysis/strategy.py``.

So this is a relabel: **no window, threshold, formula or signal moved.** The
canonical labels live once in ``data/product_ux.py``, the same way U1-1/U1-2 put
the return vocabulary there.

The sweep reaches three layers, like ``tests/test_return_label_contract.py``:

* the ``.py`` that render copy (pages, PDF, prompts);
* the two engine modules whose ``notes`` / ``warnings`` / ``rationale`` / ``risks``
  are rendered verbatim by Stock Analysis and injected into the LLM prompts;
* the living markdown catalogued in ``docs/INDEX.md``. The historical roles
  (audits, ROADMAP, brainstorm) record what was true when written and are
  deliberately left alone — ``docs/AUDIT_REASONING_QUALITY.md`` still says
  "SMA200" on purpose.

The last test guards the other direction: the CSV's ``no_hacer`` for U1-3 is
"relabel + cambiar ventana en el mismo PR", and U3-1 (``above_sma200`` should be
``None``, not ``False``, when the history is too short) must stay unspent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from analysis.technical import TechnicalAnalyzer, TechnicalResult
from data.product_ux import (
    FAST_MA_LABEL,
    FAST_MA_LABEL_EN,
    FAST_MA_SHORT,
    MID_MA_LABEL,
    MID_MA_SHORT,
    TREND_MA_HELP,
    TREND_MA_LABEL,
    TREND_MA_LABEL_EN,
    TREND_MA_SHORT,
)

# Reuse the docs guard's regexes so the two never disagree about a catalog row.
from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


#: Files that render copy a person reads, plus the two engines that emit strings
#: straight onto the page and into the prompts.
USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
    "analysis/technical.py",
    "analysis/strategy.py",
    "data/product_ux.py",
]

#: Catalog roles read as *current* truth (same set the U1-1/U1-2 sweep uses).
LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

#: A bare bar-count average: ``SMA200``, ``SMA 200``, ``SMA-200``, ``EMA 200``.
#: Case-sensitive on purpose — uppercase ``SMA`` is copy, while the lowercase
#: identifiers that hold the number (``sma200``, ``above_sma200``) are code and
#: are deliberately out of scope: U1-3 renamed what is read, not what is typed.
_BARE_MA_RE = re.compile(r"\bE?SMA[\s\-]*(?:200|100|50)\b")

#: What turns a bar count into an indicator: the unit of the bar.
_UNIT_RE = re.compile(r"seman|week|sem\.", re.IGNORECASE)


def living_docs() -> list[str]:
    """Markdown catalogued in ``docs/INDEX.md`` under a still-current role."""
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


def _unqualified_ma_offenders(paths: list[str]) -> list[str]:
    """A moving average named by bar count with no unit on the same line."""
    return [
        f"{rel}:{n}: {line.strip()}"
        for rel in paths
        for n, line in enumerate(_src(rel).splitlines(), start=1)
        if _BARE_MA_RE.search(line) and not _UNIT_RE.search(line)
    ]


# --------------------------------------------------------------------------- #
#  U1-3 — the oracle: no bar count without its unit, anywhere a person reads   #
# --------------------------------------------------------------------------- #


def test_no_bare_moving_average_in_user_surfaces():
    offenders = _unqualified_ma_offenders(USER_FACING)
    assert not offenders, (
        "Una media móvil nombrada por cantidad de barras sin decir que son "
        "semanas — un lector entiende días:\n" + "\n".join(offenders)
    )


def test_no_bare_moving_average_in_living_docs():
    offenders = _unqualified_ma_offenders(living_docs())
    assert not offenders, (
        "Documentación viva que todavía rotula la media semanal como diaria:\n"
        + "\n".join(offenders)
    )


def test_historical_audits_are_left_alone():
    """History is a record of what was true, not copy to be corrected."""
    audit = _src("docs/AUDIT_REASONING_QUALITY.md")
    assert "SMA200" in audit


# --------------------------------------------------------------------------- #
#  The canonical labels carry the unit and say what they are not               #
# --------------------------------------------------------------------------- #


def test_canonical_labels_are_defined_once_and_carry_their_unit():
    for label in (TREND_MA_LABEL, MID_MA_LABEL, FAST_MA_LABEL):
        assert "semanas" in label or "semana" in label, label
    for short in (TREND_MA_SHORT, MID_MA_SHORT, FAST_MA_SHORT):
        assert "sem." in short, short
    for en in (TREND_MA_LABEL_EN, FAST_MA_LABEL_EN):
        assert "week" in en, en

    # The years the window actually spans: 200 * 7 / 365.25 = 3.83.
    assert "3,8" in TREND_MA_LABEL
    assert "1,9" in MID_MA_LABEL

    # The help must say *why* the label is not what it looks like.
    assert "200 días" in TREND_MA_HELP
    assert "semanales" in TREND_MA_HELP


def test_prompts_tell_the_model_the_window_is_weekly():
    """The LLM read "SMA200" and reasoned about a 200-day filter that never ran."""
    prompts = _src("analysis/prompts.py")
    assert "TREND_MA_LABEL" in prompts
    # Equity and crypto decision prompts both carry the trend line.
    assert prompts.count("de la {TREND_MA_LABEL}") == 2
    assert "Slope 26w" not in prompts


def test_stock_analysis_labels_come_from_the_constants():
    page = _src("dashboard/pages/2_Stock_Analysis.py")
    for name in ("TREND_MA_SHORT", "MID_MA_SHORT", "FAST_MA_SHORT", "TREND_MA_HELP"):
        assert name in page, name
    assert '"Above SMA200"' not in page
    assert '"SMA200 Slope (26w)"' not in page


# --------------------------------------------------------------------------- #
#  no_hacer — U1-3 relabels; it does not spend U3-1                            #
# --------------------------------------------------------------------------- #


def test_window_and_nan_handling_are_untouched():
    """The CSV forbids relabel + window change in one PR, and U3-1 stays open."""
    tech = _src("analysis/technical.py")
    assert "price.rolling(200).mean()" in tech, "la ventana de 200 barras se movió"
    # U3-1 will make this `Optional[bool]` so a short history reads "unknown"
    # instead of "below trend". Until then the default must stay as shipped.
    assert "above_sma200: bool = False" in tech
    assert TechnicalResult(symbol="X").above_sma200 is False


def _reference_sma_at(values: list[float], window: int, pos: int) -> float:
    """The definition, spelled out: mean of the `window` bars ending at `pos`."""
    bars = values[pos - window + 1 : pos + 1]
    assert len(bars) == window
    return sum(bars) / window


def test_trend_flags_still_measure_200_weekly_bars():
    """Oracle: the flag matches a slow mean over the last 200 bars, not 200 days.

    Written from the definition rather than from the production expression, so a
    later change of window fails here instead of being frozen in.

    Note on the slope: the product counts **bars** everywhere — ``rolling(200)``
    is 200 bars, and the lookback spans 26 bars counted inclusively (25 steps
    between the two ends). That is the same convention the "26 semanas" label
    uses, so the reference below indexes bars, not calendar arithmetic.
    """
    n = 400
    # A gentle uptrend: the last bar sits above the trailing 200-bar mean.
    closes = [100.0 + 0.5 * i for i in range(n)]
    idx = pd.date_range("2018-01-07", periods=n, freq="W")
    df = pd.DataFrame({"close": closes}, index=idx)
    price = df["close"]

    result = TechnicalResult(symbol="TEST")
    TechnicalAnalyzer()._compute_trend(df, price, result)

    sma_now = _reference_sma_at(closes, 200, n - 1)
    assert result.above_sma200 is (closes[-1] > sma_now)

    # Same 200-bar mean as of 26 bars ago (the current bar counted as the first).
    sma_then = _reference_sma_at(closes, 200, n - 26)
    expected_slope = (sma_now - sma_then) / sma_then * 100
    assert result.sma200_slope_pct == round(expected_slope, 2)

    # 200 weekly bars is ~3,8 years — the number the label promises.
    assert round(200 * 7 / 365.25, 1) == 3.8
