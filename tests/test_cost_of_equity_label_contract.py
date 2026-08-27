"""Contract of the cost-of-capital vocabulary shown to a person (U1-4).

``MoatAnalyzer._wacc_proxy()`` returns ``risk_free_proxy_pct + sector ERP`` —
4,0 % plus 4,0…6,0 pp. That number is a **cost of equity**: there is no debt in
it, no D/(D+E) weight and no tax shield, and it is not CAPM either, because the
flat sector ERP stands in for ``β × ERP``. Every surface that named it "WACC"
promised a weighted average cost of capital the engine never computed.

U1-4 decided the **name** was wrong, not the number: the ``no_hacer`` of the row
is *"No armar WACC con estructura de capital"*, and the engine has no per-company
capital structure to build one from. So this is a relabel — the hurdle is a
**costo de equity proxy**, and no rate, premium, band or formula moved.

The same sweep caught a second gap in the same sentences: the Stock Analysis
tooltip and the methodology table still described the **legacy absolute bands**
(``≥20 %=2, ≥12 %=1, ≥8 %=0.5``), which only run with
``MOAT.use_roic_wacc_spread=False``. The default has been the spread since P2-D5,
so the copy was quoting a rule the engine does not apply. Both now read from the
canonical constants in ``data/product_ux.py``, and the cuts they name are checked
against ``MOAT`` below so the copy cannot go stale again.

The sweep reaches three layers, like ``tests/test_trend_label_contract.py``:

* the ``.py`` that render copy (pages, PDF, prompts);
* ``analysis/moat.py`` and ``config.py``, where the methodology is written down
  next to the code that applies it;
* the living markdown catalogued in ``docs/INDEX.md``. The historical roles
  (audits, ROADMAP, brainstorm) record what was true when written and are
  deliberately left alone — ``docs/AUDIT_REASONING_QUALITY.md`` still says
  "WACC" on purpose.

Identifiers are out of scope on purpose: ``use_roic_wacc_spread``,
``_wacc_proxy`` and ``risk_free_proxy_pct`` keep their names, the same way U1-3
relabelled the weekly average without renaming ``above_sma200``. U1-4 fixed what
is read, not what is typed.
"""

from __future__ import annotations

import re
from pathlib import Path

from analysis.moat import MoatAnalyzer
from config import MOAT
from data.product_ux import (
    COST_OF_EQUITY_HELP,
    COST_OF_EQUITY_LABEL,
    ROIC_ABSOLUTE_HELP,
    ROIC_SPREAD_HELP,
    ROIC_SPREAD_LABEL,
    roic_sustained_help,
)

# Reuse the docs guard's regexes so the two never disagree about a catalog row.
from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


#: Files that render copy a person reads, plus the two modules that write the
#: methodology down beside the code applying it.
USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
    "analysis/moat.py",
    "config.py",
    "data/product_ux.py",
]

#: Catalog roles read as *current* truth (same set the U1-1/U1-2/U1-3 sweeps use).
LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

#: The claim: a weighted average cost of capital. Case-sensitive on purpose —
#: uppercase ``WACC`` is prose, while the lowercase identifiers that carry the
#: legacy spelling (``_wacc_proxy``, ``use_roic_wacc_spread``) are code.
_WACC_RE = re.compile(r"\bWACC\b")

#: What makes a "WACC" on the page honest: the line either names the equity leg
#: instead, denies the claim outright ("no es un WACC"), or talks about the real
#: WACC as the thing the engine deliberately does *not* build. ``[\s*]`` lets the
#: negation survive markdown emphasis (``**not** a WACC``).
_ABSOLVED_RE = re.compile(
    r"cost of equity|costo de equity|\bKe\b|equity proxy"
    r"|no(?:t)?[\s*]*(?:es[\s*]*)?(?:un[\s*]*|a[\s*]*)?WACC"
    r"|real WACC|WACC real",
    re.IGNORECASE,
)


def living_docs() -> list[str]:
    """Markdown catalogued in ``docs/INDEX.md`` under a still-current role."""
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


def _unqualified_wacc_offenders(paths: list[str]) -> list[str]:
    """A "WACC" with nothing on the same line saying it is only the equity leg."""
    return [
        f"{rel}:{n}: {line.strip()}"
        for rel in paths
        for n, line in enumerate(_src(rel).splitlines(), start=1)
        if _WACC_RE.search(line) and not _ABSOLVED_RE.search(line)
    ]


# --------------------------------------------------------------------------- #
#  U1-4 — the oracle: no bare "WACC" anywhere a person reads                   #
# --------------------------------------------------------------------------- #


def test_no_bare_wacc_in_user_surfaces():
    offenders = _unqualified_wacc_offenders(USER_FACING)
    assert not offenders, (
        "«WACC» sin decir que es solo el costo de equity (rf + ERP, sin deuda ni "
        "escudo fiscal):\n" + "\n".join(offenders)
    )


def test_no_bare_wacc_in_living_docs():
    offenders = _unqualified_wacc_offenders(living_docs())
    assert not offenders, (
        "Documentación viva que todavía llama WACC a un costo de equity:\n"
        + "\n".join(offenders)
    )


def test_historical_audits_are_left_alone():
    """History is a record of what was true, not copy to be corrected."""
    audit = _src("docs/AUDIT_REASONING_QUALITY.md")
    assert "WACC" in audit


# --------------------------------------------------------------------------- #
#  The canonical labels say what the number is — and what it is not            #
# --------------------------------------------------------------------------- #


def test_canonical_labels_name_the_equity_leg():
    for label in (COST_OF_EQUITY_LABEL, ROIC_SPREAD_LABEL):
        assert "equity" in label, label
    assert "proxy" in COST_OF_EQUITY_LABEL

    # The help must say *why* the old name was wrong, in both directions:
    # it is not a WACC (no capital structure) and not CAPM (no beta).
    assert "No es un WACC" in COST_OF_EQUITY_HELP
    assert "deuda" in COST_OF_EQUITY_HELP
    assert "beta" in COST_OF_EQUITY_HELP.lower()

    # The disclaimer has to reach the tooltip a person actually opens, not just
    # live in a constant nothing renders.
    assert COST_OF_EQUITY_HELP in ROIC_SPREAD_HELP


def test_copy_quotes_the_cuts_the_engine_actually_applies():
    """The bug being fixed: a tooltip quoting bands the default mode never uses.

    Written against ``MOAT`` rather than against literals, so moving a threshold
    fails here instead of silently leaving the copy behind again.
    """
    assert MOAT.use_roic_wacc_spread is True, (
        "el default cambió: la copy de la UI describe el modo spread"
    )
    for cut in (
        MOAT.roic_spread_excellent,
        MOAT.roic_spread_good,
        MOAT.roic_spread_min,
    ):
        assert f"{cut:g}pp" in ROIC_SPREAD_HELP, (
            f"el corte {cut:g}pp no aparece en ROIC_SPREAD_HELP"
        )

    # The rate and the sector premia the hurdle is built from.
    assert f"{MOAT.risk_free_proxy_pct:g} %" in COST_OF_EQUITY_HELP
    erps = MOAT.sector_erp_pct.values()
    assert f"{min(erps):g}–{max(erps):g} pp" in COST_OF_EQUITY_HELP


def test_stock_analysis_tooltip_comes_from_the_constant():
    page = _src("dashboard/pages/2_Stock_Analysis.py")
    assert "roic_sustained_help()" in page
    # The stale tooltip quoted the legacy absolute bands as if they were live.
    assert "ROIC promedio histórico (≥20%=2, ≥12%=1)" not in page


class _Cfg:
    """A MoatConfig stand-in — the help must follow the flag, not the singleton."""

    def __init__(self, spread: bool):
        self.use_roic_wacc_spread = spread


def test_tooltip_follows_the_mode_the_engine_is_actually_in():
    """Both texts quote thresholds; only one set of them is ever applied.

    Pinning the tooltip to the spread text would re-create the defect U1-4
    removed, with the polarity flipped: copy describing a rule that is not
    running. So the opt-out branch is checked too.
    """
    assert roic_sustained_help(_Cfg(spread=True)) == ROIC_SPREAD_HELP
    assert roic_sustained_help(_Cfg(spread=False)) == ROIC_ABSOLUTE_HELP

    # The legacy mode compares the ROIC against nothing, so it must not borrow
    # the cost-of-equity wording — and must not quote the spread cuts.
    assert COST_OF_EQUITY_LABEL not in ROIC_ABSOLUTE_HELP
    assert "10pp" not in ROIC_ABSOLUTE_HELP
    # ...and the spread mode must not quote the absolute bands.
    assert "≥20 %=2" not in ROIC_SPREAD_HELP

    # Default: no argument reads the live singleton.
    expected = ROIC_SPREAD_HELP if MOAT.use_roic_wacc_spread else ROIC_ABSOLUTE_HELP
    assert roic_sustained_help() == expected


def test_legacy_help_quotes_the_bands_the_legacy_branch_applies(monkeypatch):
    """Same drift guard as the spread text, on the other branch.

    The absolute ladder is hardcoded in ``_score_roic_sustained`` (it predates
    ``MoatConfig``), so the oracle is the scorer itself, not a config field: each
    band the copy quotes has to be the ROIC that actually earns those points.
    """
    monkeypatch.setattr(MOAT, "use_roic_wacc_spread", False)
    ma = MoatAnalyzer()
    for band, pts in ((20.0, 2.0), (12.0, 1.0), (8.0, 0.5)):
        assert ma._score_roic_sustained(band, sector="Energy") == pts, band
        assert f"≥{band:g} %={pts:g}" in ROIC_ABSOLUTE_HELP, band
    # And the page follows the flag down to the legacy text.
    assert roic_sustained_help() is ROIC_ABSOLUTE_HELP


def test_methodology_documents_the_spread_not_the_legacy_bands():
    doc = _src("docs/moat_methodology.md")
    assert "costo de equity proxy" in doc

    #: The ROIC ladder of the legacy mode — ``≥12`` and ``≥8`` in one breath is
    #: what tells it apart from the FCF rows, which also open at ``≥20%``.
    lines = doc.splitlines()
    for n, line in enumerate(lines, start=1):
        if "≥12" in line and "≥8" in line:
            # It may only appear as what it is: the opt-out, not the live rule.
            window = " ".join(lines[max(0, n - 3) : n])
            assert "legacy" in window, f"docs/moat_methodology.md:{n}: {line.strip()}"


# --------------------------------------------------------------------------- #
#  no_hacer — U1-4 relabels; it does not build a WACC                          #
# --------------------------------------------------------------------------- #


def test_hurdle_is_still_risk_free_plus_sector_erp():
    """Oracle: the hurdle equals rf + ERP exactly, for every mapped sector.

    Written from the definition, not from the production expression, so adding a
    debt weight, a tax shield or a beta fails here rather than being frozen in.
    """
    ma = MoatAnalyzer()
    rf = MOAT.risk_free_proxy_pct
    for sector, erp in MOAT.sector_erp_pct.items():
        assert ma._wacc_proxy(sector) == rf + erp, sector
    # An unmapped sector falls back to the default premium — still rf + ERP.
    assert ma._wacc_proxy("Not A Sector") == rf + MOAT.default_sector_erp_pct
    assert ma._wacc_proxy("") == rf + MOAT.default_sector_erp_pct


def test_no_capital_structure_entered_the_hurdle():
    """The CSV's ``no_hacer``: no debt weighting, no tax shield, no beta."""
    src = _src("analysis/moat.py")
    start = src.index("def _wacc_proxy")
    body = src[start : src.index("def _score_roic_sustained", start)]
    # Drop the docstring: it names debt, tax shield and beta precisely to say
    # none of them are in the number. What must stay clean is the code.
    parts = body.split('"""')
    code = parts[-1] if len(parts) >= 3 else body
    for banned in ("debt", "tax", "beta", "leverage"):
        assert banned not in code.lower(), banned


def test_spread_bands_are_untouched():
    """The relabel moved no cut: the 0–2 pts ladder is byte-for-byte the shipped one."""
    ma = MoatAnalyzer()
    ke = ma._wacc_proxy("Technology")
    assert ma._score_roic_sustained(ke + MOAT.roic_spread_excellent, "Technology") == 2.0
    assert ma._score_roic_sustained(ke + MOAT.roic_spread_good, "Technology") == 1.0
    assert ma._score_roic_sustained(ke + MOAT.roic_spread_min, "Technology") == 0.5
    assert ma._score_roic_sustained(ke - 0.1, "Technology") == 0.0
