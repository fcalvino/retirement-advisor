"""Contract of the backtest's gap against the benchmark (U1-8).

``BacktestResult.excess_return_pct`` — and the per-ticker field of the same name
— is ``CAGR_own − CAGR_benchmark``. Nothing else. Alpha is what survives that
gap *after* discounting the part explained by market exposure, which needs a
beta the engine never estimates. The Backtesting page printed the number under
an ``α`` glyph and in a column headed "Alpha %", promising exactly the
adjustment that was missing: a basket of high-beta names in a rising market
shows a large positive gap and no alpha at all.

The U1-8 ``no_hacer`` is "No meter beta en este PR", so the fix is the name.

The other half of U1-8 was not copy. The per-ticker row measured the ticker over
``ticker ∩ benchmark`` and subtracted a benchmark CAGR measured over
``portfolio ∩ benchmark`` — two different windows, so a ticker listed two years
ago was scored against the benchmark's five-year rate. The behavioural oracle
for that lives in ``tests/test_backtesting.py::TestExcessReturnWindow``; the
guard here is on the source, so the two legs cannot drift apart again.

Like U1-1/U1-3/U1-4, the sweep reaches the ``.py`` that render copy and the
**living** markdown — the ``docs/INDEX.md`` rows whose role is read as current
truth. The historical roles (``AUDIT_*``, ``ROADMAP``, ``brainstorm``) are a
record of what was true when written and are deliberately left alone.

Labels only: no number, threshold or formula is in scope here.
"""

from __future__ import annotations

import re
from pathlib import Path

from data.product_ux import (
    EXCESS_RETURN_HELP,
    EXCESS_RETURN_LABEL,
    EXCESS_RETURN_SHORT,
    excess_return_column_label,
)
from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


#: Every file that renders copy a person reads (page, PDF or LLM prompt).
USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
    "data/product_ux.py",
]

#: Same catalog roles the U1-1 sweep uses — a doc added later joins by being
#: catalogued, and the historical roles stay out on purpose.
LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

#: A mention of alpha that is *not* a label for this number: matplotlib opacity
#: (``alpha=0.8``), Wilder smoothing (``alpha=1 / period``), a model id
#: (``owl-alpha``) and the company Alphabet.
_NOT_A_LABEL_RE = re.compile(r"alpha\s*=|[-/]alpha|alphabet|alphanum", re.IGNORECASE)
#: The word, or the glyph the page used to print.
_ALPHA_RE = re.compile(r"\balpha\b|α", re.IGNORECASE)
#: A line that says the number is *not* alpha is the whole point of the wave.
_DENIAL_RE = re.compile(r"no es (un )?alpha|not (an )?alpha|no alpha", re.IGNORECASE)


def living_docs() -> list[str]:
    """Markdown catalogued in ``docs/INDEX.md`` under a still-current role."""
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


#: Quoted runs inside a line of Python. Only what sits in a string literal ever
#: reaches a person; a ``#`` comment explaining the defect, or a local named
#: ``alpha`` in a plotting loop, is not copy and is not swept.
_QUOTED_RE = re.compile(r'"[^"\n]*"|\'[^\'\n]*\'')


def _copy_text(line: str, is_python: bool) -> str:
    """The part of a line a reader can actually see."""
    if not is_python:
        return line
    return " ".join(_QUOTED_RE.findall(line))


def _alpha_offenders(paths: list[str]) -> list[str]:
    """Copy naming a number "alpha" without denying that it is one."""
    offenders: list[str] = []
    for rel in paths:
        is_python = rel.endswith(".py")
        for n, line in enumerate(_src(rel).splitlines(), start=1):
            text = _copy_text(line, is_python)
            if (
                _ALPHA_RE.search(text)
                and not _NOT_A_LABEL_RE.search(text)
                and not _DENIAL_RE.search(line)
            ):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    return offenders


# --------------------------------------------------------------------------- #
#  The canonical label                                                         #
# --------------------------------------------------------------------------- #


def test_the_label_names_the_quantity_and_denies_the_other_one():
    assert "exceso" in EXCESS_RETURN_LABEL.lower()
    assert "exceso" in EXCESS_RETURN_SHORT.lower()
    # The help has to say why it is not alpha, not merely avoid the word.
    assert _DENIAL_RE.search(EXCESS_RETURN_HELP)
    assert "beta" in EXCESS_RETURN_HELP.lower()
    # And it has to promise the thing U1-8 actually repaired.
    assert "misma ventana" in EXCESS_RETURN_HELP.lower()


def test_the_column_header_names_the_benchmark_it_compares_against():
    """A gap is meaningless without saying against what."""
    assert "SPY" in excess_return_column_label("SPY")
    # No benchmark supplied → still not called alpha.
    assert not _ALPHA_RE.search(excess_return_column_label(""))


# --------------------------------------------------------------------------- #
#  The sweep                                                                   #
# --------------------------------------------------------------------------- #


def test_no_user_facing_surface_calls_this_number_alpha():
    offenders = _alpha_offenders(USER_FACING)
    assert not offenders, (
        "«alpha»/«α» sobre un número que es CAGR propio − CAGR del benchmark, "
        "sin ajuste por beta:\n" + "\n".join(offenders)
    )


def test_no_living_doc_calls_this_number_alpha():
    offenders = _alpha_offenders(living_docs())
    assert not offenders, (
        "markdown vivo llamando «alpha» a un exceso de retorno:\n" + "\n".join(offenders)
    )


def _is_offender(line: str, is_python: bool = True) -> bool:
    text = _copy_text(line, is_python)
    return bool(
        _ALPHA_RE.search(text)
        and not _NOT_A_LABEL_RE.search(text)
        and not _DENIAL_RE.search(line)
    )


def test_the_sweep_still_catches_the_labels_that_were_there():
    """Guard on the guard: the two forms the page actually shipped."""
    assert _is_offender('    f"α {bt_result.alpha_pct:+.1f}% vs {bt_result.benchmark}",')
    assert _is_offender('                "Alpha %":       t.alpha_pct,')
    assert _is_offender("| Backtesting | equity curve, alpha vs SPY |", is_python=False)


def test_the_sweep_leaves_alone_what_is_not_copy():
    """Opacity, Wilder smoothing, a model id, a company — and code comments."""
    assert not _is_offender('        ax.hist(scores, bins=20, alpha=0.8)')
    assert not _is_offender('            avg_gain = gain.ewm(alpha=1 / period).mean()')
    assert not _is_offender('        for lo, hi, color, alpha in bands:')
    assert not _is_offender('    "Hermes": ["openrouter/owl-alpha"],')
    assert not _is_offender('    ("GOOGL", "Alphabet Inc.", "Communication Services"),')
    assert not _is_offender('    # the ``α`` glyph the page used to print promised too much')
    # A denial is the point of the wave, in either language.
    assert not _is_offender('    "**No es alpha**: no se descuenta la beta."')


# --------------------------------------------------------------------------- #
#  The engine                                                                  #
# --------------------------------------------------------------------------- #


def test_the_engine_field_is_named_after_what_it_holds():
    engine = _src("analysis/backtesting.py")
    assert "excess_return_pct" in engine
    # No field, no keyword, no attribute read carries the old name any more.
    for shape in ("alpha_pct:", "alpha_pct=", ".alpha_pct"):
        assert shape not in engine, shape
    # It survives in exactly one place: the migration map that keeps
    # already-saved backtests loadable.
    assert '"alpha_pct": "excess_return_pct"' in engine


def test_the_per_ticker_benchmark_leg_comes_from_the_aligned_window():
    """The U1-8 window fix, guarded at the source so it cannot drift back.

    ``bm`` is the benchmark over the *portfolio's* overlap. Subtracting it from
    a ticker measured over its own overlap is the defect; the behavioural proof
    is ``TestExcessReturnWindow``.
    """
    engine = _src("analysis/backtesting.py")
    assert "bm_same_window = self._metrics(b_aligned)" in engine
    assert 'tm["cagr"] - bm_same_window["cagr"]' in engine
    assert 'tm["cagr"] - bm["cagr"]' not in engine


def test_the_backtesting_page_reads_the_label_from_the_one_source():
    page = _src("dashboard/pages/6_Backtesting.py")
    assert "EXCESS_RETURN_LABEL" in page or "excess_return_column_label" in page
    assert "alpha_pct" not in page


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
