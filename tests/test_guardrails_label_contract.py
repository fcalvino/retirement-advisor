"""Contract of the guardrails withdrawal vocabulary (U1-6).

``apply_withdrawal_strategy`` implements **two** of the four Guyton-Klinger
decision rules — capital preservation (the withdrawal rate breaches the ceiling
band → cut spending) and prosperity (it falls below the floor band → raise it).
Three pieces of the canonical method are absent:

* the **inflation rule** — GK freezes the inflation raise after a year with a
  negative portfolio return; the engine applies it every year unconditionally;
* the **portfolio management rule** — which sleeve funds the withdrawal; the
  engine sells the portfolio pro rata;
* the **time bound on the cut** — GK suspends capital preservation in the last
  15 years of the plan; the engine applies it at every horizon year.

Only ``config.py`` and the ``decumulation`` docstring said "modified"; the four
surfaces a person actually reads (selector, badge, PDF, plan prompt) said
"Guyton-Klinger" flat, which is a claim to a published method the code does not
implement. The U1-6 ``no_hacer`` is "Reimplementar GK canonico", so the fix is
the copy: the strategy is "simplificado" everywhere and the omissions travel
with the name.

Nothing in the engine moved. The last section is the guard for that: the two
rules that do run are checked against a reference loop written from their
definition, and the unconditional inflation raise is asserted to still be there
— fixing *that* is U5 territory, and this wave must not spend it.

Note on the CSV: U1-6's ``evidencia`` reads "faltan no-inflate y prosperity",
but prosperity **is** implemented (``portfolio/decumulation.py``, the
``rate < floor_rate`` branch). The omissions text below describes the code.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from config import WITHDRAWAL, WithdrawalConfig
from data.product_ux import (
    GUARDRAILS_LABEL,
    GUARDRAILS_LABEL_LONG,
    GUARDRAILS_OMISSIONS,
    guardrails_help,
)
from portfolio.decumulation import WithdrawalStrategy, apply_withdrawal_strategy

# Reuse the docs guard's regexes so the two never disagree about a catalog row.
from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


#: Surfaces that render copy, plus the two modules that define the strategy and
#: are read as the source of truth for what it does.
USER_FACING = [
    *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "dashboard").rglob("*.py")),
    "reports/investment_plan.py",
    "analysis/prompts.py",
    "analysis/committee_prompts.py",
    "portfolio/decumulation.py",
    "data/product_ux.py",
    "config.py",
]

#: Catalog roles read as *current* truth (same set the U1-1/U1-2 sweep uses).
LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

_GK_RE = re.compile(r"Guyton", re.IGNORECASE)

#: What turns the name of a published method into an honest claim: saying that
#: only part of it runs. Any of these within two lines of the name is enough,
#: so a wrapped string or a comment block is not forced onto one line.
_QUALIFIER_RE = re.compile(
    r"simplif|two\b.{0,4}of the four|2 de las 4|dos de las cuatro"
    r"|no implementa|does not implement|only part",
    re.IGNORECASE,
)

_WINDOW = 2


def living_docs() -> list[str]:
    """Markdown catalogued in ``docs/INDEX.md`` under a still-current role."""
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


def _unqualified_gk_offenders(paths: list[str]) -> list[str]:
    """The Guyton-Klinger name with no "only part of it runs" nearby."""
    offenders = []
    for rel in paths:
        lines = _src(rel).splitlines()
        for n, line in enumerate(lines):
            if not _GK_RE.search(line):
                continue
            window = "\n".join(lines[max(0, n - _WINDOW): n + _WINDOW + 1])
            if not _QUALIFIER_RE.search(window):
                offenders.append(f"{rel}:{n + 1}: {line.strip()}")
    return offenders


# --------------------------------------------------------------------------- #
#  U1-6 — the oracle: the method's name never travels alone                    #
# --------------------------------------------------------------------------- #


def test_no_unqualified_guyton_klinger_in_user_surfaces():
    offenders = _unqualified_gk_offenders(USER_FACING)
    assert not offenders, (
        "Se invoca Guyton-Klinger sin decir que solo corren 2 de sus 4 reglas:\n"
        + "\n".join(offenders)
    )


def test_no_unqualified_guyton_klinger_in_living_docs():
    offenders = _unqualified_gk_offenders(living_docs())
    assert not offenders, (
        "Documentación viva que promete el GK completo:\n" + "\n".join(offenders)
    )


def test_every_rendered_surface_carries_the_omissions():
    """Selector, badge, tooltip, PDF and plan prompt all name what is missing."""
    shared = _src("dashboard/shared.py")
    assert "GUARDRAILS_LABEL" in shared           # strategy selector
    assert "GUARDRAILS_OMISSIONS" in shared       # badge under the controls
    assert "guardrails_help(WITHDRAWAL)" in shared  # tooltip on the base rate

    pdf = _src("reports/investment_plan.py")
    assert "GUARDRAILS_LABEL_LONG" in pdf
    assert "GUARDRAILS_OMISSIONS" in pdf

    prompts = _src("analysis/prompts.py")
    assert "GUARDRAILS_OMISSIONS" in prompts
    assert "SIMPLIFICADO" in prompts


# --------------------------------------------------------------------------- #
#  The canonical wording names the two rules that run and the three that don't  #
# --------------------------------------------------------------------------- #


def test_labels_carry_the_qualifier():
    assert "simplificado" in GUARDRAILS_LABEL
    assert "simplificado" in GUARDRAILS_LABEL_LONG
    assert "Guyton-Klinger" in GUARDRAILS_LABEL_LONG
    # The short label is the one on the selector: it must stand on its own
    # without the GK name, since that is where a reader picks the strategy.
    assert "Guyton" not in GUARDRAILS_LABEL


def test_omissions_name_all_three_missing_rules():
    text = GUARDRAILS_OMISSIONS.lower()
    assert "2 de las 4" in text
    # implemented
    assert "preservación de capital" in text
    assert "prosperidad" in text
    # omitted
    assert "inflación" in text
    assert "manejo de cartera" in text
    assert "15 años" in text


def test_help_quotes_the_bands_from_config_not_from_a_literal():
    """A tooltip that hardcodes a band is the defect this wave removes."""
    doubled = WithdrawalConfig(
        guardrail_ceiling_band=0.30,
        guardrail_floor_band=0.25,
        guardrail_cut_pct=0.15,
        guardrail_raise_pct=0.05,
    )
    text = guardrails_help(doubled)
    assert "30%" in text and "25%" in text and "15%" in text and "5%" in text
    assert GUARDRAILS_OMISSIONS in text

    # And with the shipped config it quotes the shipped bands.
    live = guardrails_help()
    assert f"{WITHDRAWAL.guardrail_ceiling_band * 100:.0f}%" in live
    assert f"{WITHDRAWAL.guardrail_cut_pct * 100:.0f}%" in live


def test_generated_strategy_labels_carry_the_qualifier():
    assert "simplificado" in WithdrawalStrategy.guardrails(0.04).label


# --------------------------------------------------------------------------- #
#  no_hacer — the copy moved, the engine did not                               #
# --------------------------------------------------------------------------- #


def _reference_guardrails(
    path: np.ndarray,
    strategy: WithdrawalStrategy,
    horizon_years: int,
    inflation: float,
) -> list[float]:
    """The two rules, spelled out from their definition, one path at a time.

    Written from the rules rather than from the production expression, so a
    later change of behaviour fails here instead of being frozen in (the D4
    lesson: comparing new code against old code freezes the bug).
    """
    wr0 = strategy.pct
    ceiling = wr0 * (1.0 + strategy.guardrail_ceiling_band)
    floor = wr0 * (1.0 - strategy.guardrail_floor_band)

    value = float(path[0])
    spend = wr0
    withdrawals: list[float] = []
    for yr in range(1, horizon_years + 1):
        # Market move over the whole year (the path is weekly), applied to what
        # is still invested after the previous withdrawal.
        value *= float(path[yr * 52]) / float(path[(yr - 1) * 52])
        if yr > 1:
            spend *= 1.0 + inflation          # unconditional: no no-inflate rule
        rate = spend / value if value > 0 else float("inf")
        if rate > ceiling:
            spend *= 1.0 - strategy.guardrail_cut_pct     # capital preservation
        elif rate < floor:
            spend *= 1.0 + strategy.guardrail_raise_pct   # prosperity
        taken = min(spend, max(value, 0.0))
        withdrawals.append(taken)
        value -= taken
    return withdrawals


def _engine_withdrawals(
    path: np.ndarray, strategy: WithdrawalStrategy, horizon_years: int, inflation: float
) -> list[float]:
    """What the engine actually took out each year, read off the paths."""
    paths = path.reshape(1, -1)
    after = apply_withdrawal_strategy(
        paths, initial_value=1.0, strategy=strategy,
        n_horizon_weeks=horizon_years * 52, inflation_rate=inflation,
    )
    # At each 52-week mark the engine scales the remainder by (value - w)/value,
    # so the amount taken is the gap between the pre- and post-withdrawal level.
    out = []
    for yr in range(1, horizon_years + 1):
        idx = yr * 52
        before = float(after[0, idx - 1]) * (float(path[idx]) / float(path[idx - 1]))
        out.append(before - float(after[0, idx]))
    return out


def _weekly_path(annual_returns: list[float]) -> np.ndarray:
    """A relative path (start 1.0) that delivers `annual_returns` year by year."""
    values = [1.0]
    for r in annual_returns:
        step = (1.0 + r) ** (1.0 / 52)
        for _ in range(52):
            values.append(values[-1] * step)
    return np.array(values, dtype=float)


def test_the_two_rules_that_run_still_match_their_definition():
    """Oracle: cut on a crash, raise on a boom — same numbers as the reference."""
    strategy = WithdrawalStrategy.guardrails(0.04)
    inflation = 0.03
    for label, annual in (
        ("crash", [-0.35, -0.10, 0.05, 0.02, 0.01]),
        ("boom", [0.30, 0.25, 0.20, 0.15, 0.10]),
        ("flat", [0.0, 0.0, 0.0, 0.0, 0.0]),
    ):
        path = _weekly_path(annual)
        expected = _reference_guardrails(path, strategy, len(annual), inflation)
        got = _engine_withdrawals(path, strategy, len(annual), inflation)
        assert np.allclose(got, expected, rtol=1e-9, atol=1e-12), (label, got, expected)


def test_the_bands_and_steps_are_the_shipped_ones():
    """±20% bands with ±10% steps — U1-6 renames, it does not recalibrate."""
    assert WITHDRAWAL.guardrail_ceiling_band == 0.20
    assert WITHDRAWAL.guardrail_floor_band == 0.20
    assert WITHDRAWAL.guardrail_cut_pct == 0.10
    assert WITHDRAWAL.guardrail_raise_pct == 0.10


def test_the_inflation_rule_is_still_absent():
    """The omission is real, and fixing it is U5 — not this wave.

    If someone implements the no-inflate rule, this test fails and
    ``GUARDRAILS_OMISSIONS`` must stop claiming it is missing.
    """
    src = _src("portfolio/decumulation.py")
    assert "spend = spend * (1.0 + inflation_rate)" in src

    # Behaviour, not just source: after a losing year the spending base still
    # grows with inflation. Two horizons of one bad year, one with inflation and
    # one without — the withdrawal in year 2 differs by exactly the inflation.
    strategy = WithdrawalStrategy.guardrails(0.04)
    path = _weekly_path([-0.05, -0.05])
    with_infl = _engine_withdrawals(path, strategy, 2, 0.03)
    without = _engine_withdrawals(path, strategy, 2, 0.0)
    assert with_infl[1] > without[1]
    assert np.isclose(with_infl[1] / without[1], 1.03, rtol=1e-9)


def test_the_cut_still_applies_at_every_horizon_year():
    """GK suspends capital preservation in the last 15 years; here it does not."""
    src = _src("portfolio/decumulation.py")
    body = src.split('if strategy.kind == "guardrails":', 1)[1]
    assert "for yr in range(1, horizon_years + 1):" in body
    # No year-based gate around the cut — the branch is unconditional on `yr`.
    cut_line = [ln for ln in body.splitlines() if "guardrail_cut_pct" in ln and "np.where" in ln]
    assert len(cut_line) == 1
    assert "yr" not in cut_line[0]
