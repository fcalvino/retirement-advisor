"""Contract of the return/ratio vocabulary shown to a person (U1-1, U1-2).

Two numbers of the optimizer were named after things they are not:

* ``expected_return_pct`` is a **proxy** built from score + dividend + moat
  (``VIEW_WEIGHTS`` → Black-Litterman view). It orders portfolios; it does not
  forecast a return. The Monte Carlo projects wealth from price history and does
  **not** share this model — so the two must never be called the same thing.
* ``sharpe_ratio`` is ``(mu_proxy − Rf) / sigma_historical``: a proxy numerator
  over a historical denominator. It is not a Sharpe ratio, and the Optimizer page
  puts it in the same column as the real Sharpe of SPY / 60-40 / BND.

The canonical vocabulary (one source of truth in ``data/product_ux.py``):

| number                     | comes from                    | label                      |
|----------------------------|-------------------------------|----------------------------|
| optimizer ``mu``           | score + dividend + moat → BL  | "Atractivo estimado (proxy)"|
| optimizer ``sharpe_ratio`` | (mu_proxy − Rf) / sigma_hist  | "Ratio atractivo/vol"      |
| Monte Carlo ``mu``         | price history × mean_haircut  | "retorno histórico"        |
| realized Sharpe            | actual equity curve           | "Sharpe" (unchanged)       |

These tests read the shipped source of the user-facing surfaces, the same way
``tests/test_screener_page_contract.py`` does. The sweep reaches three layers:

* the ``.py`` that render copy (pages, PDF, prompts);
* the living markdown — every ``docs/INDEX.md`` row whose role is read as current
  truth. The historical roles (audits, ROADMAP, brainstorm) are a record of what
  was true when written and are deliberately left alone;
* the optimizer engine itself, so ``portfolio/optimizer.py`` cannot drift back to
  calling its own objective a Sharpe while the UI calls it something else.

They check **labels only** — no number, threshold or formula is in scope here.
"""

from __future__ import annotations

import re
from pathlib import Path

from data.product_ux import (
    MC_RETURN_LABEL,
    PROXY_RATIO_HELP,
    PROXY_RATIO_LABEL,
    PROXY_RETURN_HELP,
    PROXY_RETURN_LABEL,
    PROXY_RETURN_SHORT,
)

# The catalog table is already parsed by the docs guard — reuse its regexes so
# the two never disagree about what a catalog row looks like.
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
    "portfolio/sensitivity.py",
]

#: Surfaces fed by the optimizer proxy — they must never say a bare "Sharpe".
PROXY_FED = [
    "dashboard/pages/10_About.py",
    "dashboard/pages/12_Plan.py",
    "dashboard/pages/5_Optimizer.py",
    "dashboard/pages/7_Simulaciones.py",
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
]

#: Catalog roles whose docs are read as *current* truth. Everything else in
#: ``docs/INDEX.md`` (historical-audit, historical-plan, ideation, archive) is a
#: record of what was true when it was written — renaming inside it would be
#: rewriting history, so the sweep stays out.
LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

#: The engine that produces the proxy ratio. Not user-facing copy, but a
#: docstring saying "minimize negative Sharpe" is how the vocabulary drifts back.
ENGINE_SOURCES = ["portfolio/optimizer.py", "config.py"]


def living_docs() -> list[str]:
    """Markdown catalogued in ``docs/INDEX.md`` under a still-current role.

    Derived from the catalog rather than hardcoded, so a doc added later joins
    the sweep by being catalogued. ``docs/brainstorm/`` is a directory row and
    is filtered out by ``is_file()``.
    """
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


_RETURN_RE = re.compile(r"retorno esp|expected return", re.IGNORECASE)
_QUALIFIER_RE = re.compile(r"proxy|atractivo|históric|historic", re.IGNORECASE)
_SHARPE_RE = re.compile(r"Sharpe")
#: ``realized`` alongside ``realizad``: the sweep covers ``config.py``, whose
#: docstrings are in English, and "the realized Sharpe of the backtest" is the
#: qualifier this contract asks for — it just was not spelled in Spanish. Both
#: stems are listed in full rather than shortened to ``realiz``, which would let
#: an unrelated "se realiza el cálculo" qualify a bare Sharpe by accident.
_SHARPE_QUALIFIER_RE = re.compile(r"ratio|hist|realizad|realized", re.IGNORECASE)
#: "Sharpe Ratio" must not qualify itself, and neither may the identifiers that
#: hold the number (``sharpe_ratio``, ``sortino_ratio``): the qualifier has to be
#: something a person reads ("ratio proxy", "histórico", "REALIZADO").
_SHARPE_SELF_QUALIFIER_RE = re.compile(r"Sharpe\s+ratio", re.IGNORECASE)
_RATIO_IDENT_RE = re.compile(r"\b[a-z_][a-z0-9_]*_ratio\b")
#: A block header ("--- Riesgo/retorno REALIZADO ---") qualifies the lines under it.
_CONTEXT_LINES = 4


def _sharpe_is_unqualified(line: str, context: str = "") -> bool:
    """True when a bare "Sharpe" names a number that is not a Sharpe."""
    if not _SHARPE_RE.search(_SHARPE_SELF_QUALIFIER_RE.sub("Sharpe", line)):
        return False
    window = _SHARPE_SELF_QUALIFIER_RE.sub("Sharpe", f"{context}\n{line}")
    return not _SHARPE_QUALIFIER_RE.search(_RATIO_IDENT_RE.sub("", window))


def _unqualified_return_offenders(paths: list[str]) -> list[str]:
    """"retorno esperado" / "expected return" that never says which model."""
    return [
        f"{rel}:{n}: {line.strip()}"
        for rel in paths
        for n, line in enumerate(_src(rel).splitlines(), start=1)
        if _RETURN_RE.search(line) and not _QUALIFIER_RE.search(line)
    ]


def _bare_sharpe_offenders(paths: list[str], context_lines: int = _CONTEXT_LINES) -> list[str]:
    """"Sharpe" over a proxy number, with no qualifier on it or just above it.

    ``context_lines=0`` for prose: in markdown the lines above are a different
    sentence (often a code fence), not a block header that scopes what follows,
    so a paragraph naming the ratio must carry its own qualifier.
    """
    offenders: list[str] = []
    for rel in paths:
        lines = _src(rel).splitlines()
        for n, line in enumerate(lines, start=1):
            context = "\n".join(lines[max(0, n - 1 - context_lines):n - 1])
            if _sharpe_is_unqualified(line, context):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    return offenders


# --------------------------------------------------------------------------- #
#  U1-1 — no unqualified "retorno esperado" anywhere a person can read         #
# --------------------------------------------------------------------------- #


def test_no_unqualified_expected_return_label():
    """The audit oracle: every mention names the model it comes from."""
    offenders = _unqualified_return_offenders(USER_FACING)
    assert not offenders, (
        "«retorno esperado» sin decir de qué modelo sale (proxy del optimizer o "
        "historia del Monte Carlo):\n" + "\n".join(offenders)
    )


def test_canonical_labels_are_defined_once_and_carry_their_qualifier():
    assert "proxy" in PROXY_RETURN_LABEL.lower()
    assert "atractivo" in PROXY_RETURN_SHORT.lower()
    assert "ratio" in PROXY_RATIO_LABEL.lower() and "atractivo" in PROXY_RATIO_LABEL.lower()
    assert "históric" in MC_RETURN_LABEL.lower()
    # The help strings must say *why* the label is not a forecast / not a Sharpe.
    assert "proxy" in PROXY_RETURN_HELP.lower()
    assert "histórica" in PROXY_RATIO_HELP.lower() or "histórico" in PROXY_RATIO_HELP.lower()


def test_plan_pdf_and_prompts_use_the_canonical_return_label():
    """U6-1 movió el vocabulario del proxy de «Atractivo estimado (proxy)» —que
    se renderizaba en puntos porcentuales— a «Índice de atractivo (0–100)». Lo
    que este contrato exige no cambió: que la superficie use la constante
    canónica y no un string suelto. Cambió cuál es la constante."""
    plan = _src("dashboard/pages/12_Plan.py")
    assert '"Retorno esp."' not in plan
    assert "PROXY_INDEX_SHORT" in plan

    ux = _src("data/product_ux.py")
    assert '"Retorno esperado %"' not in ux

    # Either the literal or the constant it comes from — one vocabulary either way.
    for rel in ("reports/investment_plan.py", "analysis/prompts.py",
                "analysis/committee_prompts.py"):
        src = _src(rel)
        assert (
            "índice de atractivo" in src.lower() or "PROXY_INDEX_LABEL" in src
        ), rel


def test_frontier_axis_is_the_proxy_not_a_forecast():
    opt = _src("dashboard/pages/5_Optimizer.py")
    assert '"Retorno Esperado % (anual)"' not in opt
    assert "Atractivo estimado % (anual)" in opt


# --------------------------------------------------------------------------- #
#  U1-2 — the proxy ratio is never called "Sharpe"                             #
# --------------------------------------------------------------------------- #


def test_proxy_ratio_is_never_labelled_a_bare_sharpe():
    """A "Sharpe" on a proxy-fed surface must say it is a ratio / historical."""
    offenders = _bare_sharpe_offenders(PROXY_FED)
    assert not offenders, (
        "«Sharpe» a secas sobre un número que es (mu_proxy − Rf) / vol histórica:\n"
        + "\n".join(offenders)
    )


def test_the_sweep_still_catches_a_bare_sharpe_ratio():
    """Guard on the guard: "Sharpe Ratio" must not qualify itself (review #3)."""
    # Both blind spots the first version of this sweep had: "Ratio" qualifying
    # "Sharpe Ratio", and the ``sharpe_ratio`` identifier qualifying its own label.
    assert _sharpe_is_unqualified('c[2].metric("Sharpe Ratio", f"{x:.2f}")')
    assert _sharpe_is_unqualified('c[2].metric("Sharpe", f"{m.get(\'sharpe_ratio\', 0):.2f}")')
    assert _sharpe_is_unqualified('    "Sharpe": result.sharpe_ratio,')
    # Real qualifiers still pass — on the line, or in the block header above it.
    assert not _sharpe_is_unqualified('_BENCH_RATIO_COL = "Sharpe hist. / ratio proxy"')
    assert not _sharpe_is_unqualified('"riesgo REALIZADO (Sharpe, Sortino, beta vs SPY)"')
    assert not _sharpe_is_unqualified(
        "f\"Sharpe: {_num(rz.get('sharpe_ratio'))}\"",
        context='"--- Riesgo/retorno REALIZADO (histórico de tus tenencias) ---",',
    )


def test_proxy_ratio_label_reaches_every_proxy_surface():
    assert "PROXY_RATIO_LABEL" in _src("dashboard/pages/12_Plan.py")
    assert "PROXY_RATIO_LABEL" in _src("dashboard/pages/5_Optimizer.py")
    assert "PROXY_RATIO_LABEL" in _src("dashboard/pages/7_Simulaciones.py")
    assert "PROXY_RATIO_LABEL" in _src("reports/investment_plan.py")
    assert '"Sharpe Ratio"' not in _src("dashboard/pages/5_Optimizer.py")


# --------------------------------------------------------------------------- #
#  U1-2 — the docs and the engine speak the same vocabulary as the screen      #
# --------------------------------------------------------------------------- #


def test_the_catalog_still_yields_the_living_docs():
    """Guard on the guard: an empty list would make the two sweeps below vacuous."""
    docs = living_docs()
    assert {"README.md", "docs/portfolio_optimizer.md", "docs/architecture.md"} <= set(docs)
    # The historical record is out of scope on purpose.
    assert not any(d.startswith("docs/AUDIT") or d == "docs/ROADMAP.md" for d in docs)


def test_living_docs_name_the_model_behind_a_return():
    """A doc read as current truth cannot say "retorno esperado" unqualified."""
    offenders = _unqualified_return_offenders(living_docs())
    assert not offenders, (
        "doc vivo con «retorno esperado» sin nombrar su modelo (proxy del optimizer "
        "o historia del Monte Carlo):\n" + "\n".join(offenders)
    )


def test_living_docs_never_call_the_proxy_ratio_a_sharpe():
    """The README and the methodology docs described the objective as a Sharpe."""
    offenders = _bare_sharpe_offenders(living_docs(), context_lines=0)
    assert not offenders, (
        "doc vivo llamando «Sharpe» a (μ_proxy − Rf) / σ histórica:\n"
        + "\n".join(offenders)
    )


def test_the_engine_does_not_call_its_own_objective_a_sharpe():
    """SLSQP minimizes −(μ_proxy − Rf)/σ_hist: the shape of a Sharpe, not a Sharpe."""
    offenders = _bare_sharpe_offenders(ENGINE_SOURCES)
    assert not offenders, (
        "el motor del proxy sigue diciendo «Sharpe» — es como la UI vuelve a "
        "driftear:\n" + "\n".join(offenders)
    )


# --------------------------------------------------------------------------- #
#  Guard — a realized Sharpe is a Sharpe and keeps its name                    #
# --------------------------------------------------------------------------- #


def test_realized_sharpe_keeps_its_name():
    """Portfolio / Backtesting measure the actual equity curve — do not rename."""
    assert 'col4.metric("Sharpe Ratio"' in _src("dashboard/pages/3_Portfolio.py")
    assert 'col1.metric("Sharpe Ratio"' in _src("dashboard/pages/6_Backtesting.py")
    committee = _src("analysis/committee_prompts.py")
    assert "Riesgo/retorno REALIZADO" in committee
    assert "Sharpe: {_num(rz.get('sharpe_ratio'))}" in committee
