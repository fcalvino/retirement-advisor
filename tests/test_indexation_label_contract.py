"""Contract of the spending-indexation vocabulary shown to a person (N8).

The tornado lever bumps ``withdrawal_growth_rate`` — how much spending or
deposits grow each year. Calling it "Inflación" promised a real-return shock
the Monte Carlo does not compute. For an accumulator the sign is inverted:
more "inflation" grows deposits and P10 rises.

U4-3 already marked a lever that does not reach the plan as «no aplica». N8
is the name of the lever that *does* reach it. Identifiers
(``inflation``, ``inflation_hot``, ``inflation_delta_pct``) keep their names,
the same way U1-3 left ``above_sma200``. This is a relabel: no number, band
or formula moved. ``portfolio/monte_carlo.py`` is out of scope on purpose.

The sweep reaches:

* the specs the lab actually ships (runtime, not a grep of comments);
* the ``.py`` that render the tornado/scenario copy;
* the living markdown catalogued in ``docs/INDEX.md``. Historical roles
  (audits, ROADMAP, brainstorm) record what was true when written.

The sidebar slider «Inflación esperada» is a different knob (the user's
inflation assumption for real purchasing power) and is not this contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from config import SENSITIVITY
from data.product_ux import (
    INDEXATION_HELP_ACCUMULATION,
    INDEXATION_HELP_WITHDRAWAL,
    INDEXATION_LABEL,
    INDEXATION_SCENARIO_DESCRIPTION,
    indexation_help,
    indexation_scenario_label,
)
from portfolio.sensitivity import _factor_specs, _scenario_specs
from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


USER_FACING = [
    "portfolio/sensitivity.py",
    "dashboard/pages/7_Simulaciones.py",
    "data/product_ux.py",
]

LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

# A tornado/scenario label that is "Inflación" a secas, or "Inflación +Npp".
# The sidebar "Inflación esperada" and the PDF "Inflación estimada" are other
# knobs; they keep the word because they *are* the user's inflation assumption.
# Shipped labels, not comments that narrate the old name.
_LEVER_LIE_RE = re.compile(
    r'"label": "Inflación"|f"Inflación \+|label=f?"Inflación"'
)


def living_docs() -> list[str]:
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


class TestIndexationLabel:
    def test_canonical_label_does_not_say_inflacion(self):
        assert "Inflación" not in INDEXATION_LABEL
        assert INDEXATION_LABEL == "Indexación del gasto"

    def test_tornado_factor_ships_the_canonical_label(self):
        spec = next(s for s in _factor_specs(SENSITIVITY) if s["key"] == "inflation")
        assert spec["label"] == INDEXATION_LABEL
        assert "Inflación" not in spec["label"]
        assert spec["param"] == "withdrawal_growth_rate"

    def test_scenario_ships_the_canonical_label(self):
        spec = next(
            s for s in _scenario_specs(SENSITIVITY) if s["key"] == "inflation_hot"
        )
        assert spec["label"] == indexation_scenario_label(SENSITIVITY.inflation_delta_pct)
        assert spec["label"].startswith(INDEXATION_LABEL)
        assert not spec["label"].startswith("Inflación")
        assert spec["description"] == INDEXATION_SCENARIO_DESCRIPTION
        assert "retorno real" in spec["description"]

    def test_help_splits_accumulation_from_withdrawal(self):
        acc = indexation_help(has_contribution=True, has_withdrawal=False)
        wd = indexation_help(has_contribution=False, has_withdrawal=True)
        assert acc == INDEXATION_HELP_ACCUMULATION
        assert wd == INDEXATION_HELP_WITHDRAWAL
        assert acc != wd
        assert "depósitos" in acc
        assert "gasto" in wd

    def test_user_facing_copy_does_not_relabel_the_lever_inflacion(self):
        for rel in USER_FACING:
            src = _src(rel)
            for i, line in enumerate(src.splitlines(), 1):
                if _LEVER_LIE_RE.search(line):
                    raise AssertionError(
                        f"{rel}:{i} vuelve a llamar «Inflación» a la palanca "
                        f"de withdrawal_growth_rate: {line.strip()}"
                    )


class TestLivingDocsDoNotReopenTheLie:
    def test_living_markdown_does_not_name_the_lever_inflacion(self):
        # CONTEXT and BACKLOG describe N8; after the close they must not
        # present the shipped lever as «Inflación» without saying it was renamed.
        forbidden = re.compile(
            r'palanca[^.\n]{0,40}"Inflación"|palanca del tornado se llama «Inflación»'
        )
        for rel in living_docs():
            src = _src(rel)
            # Historical present in a "Antes:" changelog is the record of the
            # lie, not the current claim. Skip those lines.
            for i, line in enumerate(src.splitlines(), 1):
                if "Antes:" in line or "N8" in line:
                    continue
                if forbidden.search(line):
                    raise AssertionError(
                        f"{rel}:{i} presenta la palanca del tornado como "
                        f"«Inflación» después de N8: {line.strip()}"
                    )
