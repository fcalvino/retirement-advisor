"""What the F-Score measures, wherever it is shown (backlog U5-1).

Piotroski's F-Score is nine **year-over-year** checks: is this company more
profitable, less levered and more efficient *than it was last year*. It was built
to separate winners from losers among cheap stocks over a **one-year** holding
period. It is a change signal, not a level, and not a durability claim.

The engine pays up to **12** points for it — more than the **10** it pays for a
durable competitive moat — inside a score whose whole purpose is judging a
retirement holding. Measured on the 150 cached equities, 31 % collect the strong
bonus and **24 cross the BUY threshold on it alone**.

Recalibrating that is deliberately **not** this row: the track record holds 22
outcomes, all at 30 days, which cannot settle what a year-over-year improvement
is worth to someone holding for twenty. What this row fixes is that the number
was described as "salud contable" — a level, and a durable-sounding one — on the
screen where most people meet it. The weights are written down next to each other
in config so whoever does the calibration starts from the comparison rather than
rediscovering it.

Same shape as the six vocabulary contracts already in this suite: a name that
promises more than the formula delivers is the defect, independently of whether
the formula is right.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.check_doc_catalog import CATALOG_TABLE_RE, ROW_RE

ROOT = Path(__file__).resolve().parents[1]

LIVING_DOC_ROLES = frozenset({"living-guide", "how-to", "methodology", "ai-context"})

#: Surfaces that render the F-Score to a person.
USER_FACING = [
    "data/product_ux.py",
    "dashboard/pages/1_Screener.py",
    "dashboard/pages/2_Stock_Analysis.py",
    "dashboard/pages/10_About.py",
    "analysis/scoring.py",
    "config.py",
]

_PIOTROSKI_RE = re.compile(r"piotroski|f-score", re.IGNORECASE)

#: What turns the name into an honest claim: saying it measures change, not level.
_QUALIFIER_RE = re.compile(
    r"yoy|year-over-year|año contra año|interanual|mejora|improvement|cambio", re.IGNORECASE
)

#: Only lines that DESCRIBE the score are guarded — not the many that merely name
#: it. "Piotroski" is also a dict key, a dataclass, a field and an import, and a
#: guard that demanded "año contra año" beside every one of those would force the
#: qualifier into places it means nothing. What is being protected is the claim a
#: reader takes away, so the trigger is a line calling it health or quality.
_DESCRIBES_RE = re.compile(
    r"salud|calidad|health|quality|chequeos|checks|mide|measures", re.IGNORECASE
)

_WINDOW = 2


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def living_docs() -> list[str]:
    table = CATALOG_TABLE_RE.search(_src("docs/INDEX.md"))
    assert table, "docs/INDEX.md perdió los marcadores <!-- catalog-table -->"
    return [
        m["path"]
        for m in ROW_RE.finditer(table.group(1))
        if m["role"] in LIVING_DOC_ROLES and (ROOT / m["path"]).is_file()
    ]


def _offenders(paths: list[str]) -> list[str]:
    """Where the F-Score is described without saying it measures change."""
    out = []
    for rel in paths:
        lines = _src(rel).splitlines()
        for n, line in enumerate(lines):
            if not (_PIOTROSKI_RE.search(line) and _DESCRIBES_RE.search(line)):
                continue
            window = "\n".join(lines[max(0, n - _WINDOW): n + _WINDOW + 1])
            if not _QUALIFIER_RE.search(window):
                out.append(f"{rel}:{n + 1}: {line.strip()}")
    return out


class TestTheScoreSaysItMeasuresChange:
    def test_the_screener_help_does_not_call_it_a_level(self):
        """Where most people meet it: "9 chequeos de salud contable" reads durable."""
        help_text = _src("data/product_ux.py")
        assert "9 chequeos de salud contable (0–9)." not in help_text

    def test_a_shared_caveat_exists_and_names_the_horizon(self):
        from data.product_ux import PIOTROSKI_HELP

        low = PIOTROSKI_HELP.lower()
        assert _QUALIFIER_RE.search(low)
        assert "1 año" in low or "un año" in low

    def test_the_screener_uses_it(self):
        assert "PIOTROSKI_HELP" in _src("data/product_ux.py")

    def test_no_user_surface_describes_it_as_a_level(self):
        offenders = _offenders(USER_FACING)
        assert not offenders, (
            "Se describe el F-Score sin decir que mide cambio interanual:\n"
            + "\n".join(offenders)
        )

    def test_no_living_doc_describes_it_as_a_level(self):
        offenders = _offenders(living_docs())
        assert not offenders, (
            "Documentación viva que presenta el F-Score como un nivel:\n"
            + "\n".join(offenders)
        )

    def test_the_catalog_still_yields_the_living_docs(self):
        """Guard on the guard: an empty list would make the sweep vacuous."""
        assert len(living_docs()) >= 4


class TestTheWeightsAreWrittenDownTogether:
    def test_config_states_what_it_outweighs(self):
        """So the calibration starts from the comparison, not from scratch."""
        src = _src("config.py")
        block = src.split("class PiotroskiConfig")[1].split("@dataclass")[0]
        assert "moat" in block.lower()
        assert "U5-1" in block

    def test_the_bonus_is_unchanged(self):
        """This row relabels; recalibrating needs outcomes it does not have."""
        from config import PIOTROSKI

        assert PIOTROSKI.bonus_strong == 12.0
        assert PIOTROSKI.bonus_good == 6.0
