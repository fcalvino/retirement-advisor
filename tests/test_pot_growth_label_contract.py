"""Contract of the Monte Carlo's annualised pot growth (U1-7).

``MonteCarloResult.median_cagr_pct`` is ``(terminal / initial) ** (1/years) - 1``
and nothing else. That expression is a **return** only when no money crosses the
boundary of the portfolio. With cash flows it stops being one, in both
directions:

* **contributions** land in ``terminal`` but never in ``initial``, so the figure
  inflates far above anything the portfolio earned;
* **withdrawals** leave ``terminal`` without ever leaving ``initial``, so it
  deflates below it.

Measured on the deterministic fixture below — one portfolio, one market, three
cash-flow schedules over 20 years — the number moves about **eleven points**
while the market underneath never changes. That is the whole finding: it tracks
the payment calendar, not the return.

There is a third distortion that only shows up with withdrawals. The engine
computes the per-path figure as ``np.where(terminal > 0, terminal, np.nan)``
followed by ``nanmedian``, so **ruined paths are dropped**: with 72 % ruin the
published number is the median of the 28 % that survived, not of the simulation.

The U1-7 ``no_hacer`` is "IRR completo": the money-weighted return that *would*
be honest here is not to be built in this wave. So the fix is the wording plus
the one place where the figure was being consumed as a return — the gap-to-goal
levers fed it into ``compute_gap_to_goal_levers(annual_return=…)``, a closed-form
compounding model that already adds the contributions on its own.

**The engine is not touched.** ``mc_has_cash_flows`` is a pure predicate over the
result object, deliberately living in ``data/product_ux`` rather than on the
dataclass, so this wave adds nothing at all to ``portfolio/monte_carlo.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from data.product_ux import (
    POT_CAGR_LABEL,
    POT_GROWTH_LABEL,
    POT_GROWTH_SHORT,
    mc_has_cash_flows,
    pot_growth_column_label,
    pot_growth_delta,
    pot_growth_help,
    pot_growth_pct,
)
from portfolio.monte_carlo import MonteCarloResult, MonteCarloSimulator

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Fixture — same deterministic weekly history the MC suite uses               #
# --------------------------------------------------------------------------- #

def _fake_history(symbol: str, period: str = "10y", interval: str = "1wk") -> pd.DataFrame:
    n = 260
    rng = np.random.default_rng(seed=42)
    prices = 100.0 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    dates = pd.date_range("2018-01-01", periods=n, freq="W")
    return pd.DataFrame({"close": prices}, index=dates)


def _runs():
    """One portfolio, one market, three cash-flow schedules."""
    sim = MonteCarloSimulator(symbols=["AAPL"], seed=42)
    kw = dict(horizon_years=20, n_sims=2000, initial_value=100_000)
    return (
        sim.run(annual_withdrawal=0.0, **kw),          # no flows
        sim.run(annual_withdrawal=-12_000.0, **kw),    # contributions
        sim.run(annual_withdrawal=6_000.0, **kw),      # withdrawals
    )


# --------------------------------------------------------------------------- #
#  The oracle — the figure follows the payment calendar, not the return        #
# --------------------------------------------------------------------------- #


@patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
def test_the_figure_moves_with_the_cash_flows_while_the_market_does_not(_mock):
    flat, contrib, withdraw = _runs()

    # Same simulator, same seed, same history: the market is identical in all
    # three. Only the flow schedule differs.
    assert flat.symbols_used == contrib.symbols_used == withdraw.symbols_used
    assert flat.n_weeks_history == contrib.n_weeks_history == withdraw.n_weeks_history

    # Contributions push it up, withdrawals push it down, and the spread between
    # the two readings of the SAME portfolio is large enough to invert a verdict.
    assert contrib.median_cagr_pct > flat.median_cagr_pct
    assert withdraw.median_cagr_pct < flat.median_cagr_pct
    assert contrib.median_cagr_pct - withdraw.median_cagr_pct > 5.0


@patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
def test_with_no_flows_it_really_is_the_compound_growth(_mock):
    """Written from the definition, not from the production expression."""
    flat, _, _ = _runs()

    reference = ((flat.median_terminal / flat.initial_value)
                 ** (1.0 / flat.horizon_years) - 1.0) * 100.0
    # The engine takes the median OF the per-path CAGRs while this takes the CAGR
    # OF the median terminal; both are monotone transforms of the same ordering,
    # so with no ruin they agree to well under a tenth of a point.
    assert abs(flat.median_cagr_pct - reference) < 0.1


@patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
def test_with_ruin_the_figure_describes_only_the_survivors(_mock):
    """``nanmedian`` over ``where(terminal > 0)`` drops the ruined paths."""
    _, _, withdraw = _runs()

    assert withdraw.prob_ruin_pct > 50.0
    assert withdraw.median_terminal == 0.0
    # The median pot is zero, yet a finite growth rate is published: it can only
    # be describing the minority of paths that did not run dry.
    assert withdraw.median_cagr_pct != 0.0
    assert np.isfinite(withdraw.median_cagr_pct)


# --------------------------------------------------------------------------- #
#  The predicate that decides which of the two things the number is            #
# --------------------------------------------------------------------------- #


@patch("portfolio.monte_carlo.get_history", side_effect=_fake_history)
def test_the_predicate_recognises_both_flow_directions(_mock):
    flat, contrib, withdraw = _runs()
    assert mc_has_cash_flows(flat) is False
    assert mc_has_cash_flows(contrib) is True
    assert mc_has_cash_flows(withdraw) is True


def test_a_withdrawal_strategy_counts_as_a_cash_flow():
    """Fase H.1 replaces ``annual_withdrawal`` with a strategy — still flows."""
    res = MonteCarloResult(n_sims=1, horizon_years=10, initial_value=1.0,
                           annual_withdrawal=0.0, target_value=0.0)
    assert mc_has_cash_flows(res) is False
    res.withdrawal_strategy_applied = {"kind": "fixed_real", "base_pct": 4.0}
    assert mc_has_cash_flows(res) is True


def test_the_predicate_tolerates_a_plain_mapping():
    """A persisted ``mc_summary`` is a dict, not a dataclass."""
    assert mc_has_cash_flows({"annual_withdrawal": 0.0}) is False
    assert mc_has_cash_flows({"annual_withdrawal": -500.0}) is True
    assert mc_has_cash_flows(None) is False


# --------------------------------------------------------------------------- #
#  Single implementation of the growth expression                              #
# --------------------------------------------------------------------------- #


def test_pot_growth_pct_is_the_definition():
    # A pot that doubles in exactly 10 years grows 7.177%/yr.
    assert abs(pot_growth_pct(200.0, 100.0, 10) - 7.177346) < 1e-5
    assert abs(pot_growth_pct(100.0, 100.0, 5) - 0.0) < 1e-9


def test_pot_growth_pct_refuses_the_undefined_cases():
    """A ruined pot has no growth rate; neither does a zero-length horizon."""
    assert pot_growth_pct(0.0, 100.0, 10) is None
    assert pot_growth_pct(-5.0, 100.0, 10) is None
    assert pot_growth_pct(200.0, 0.0, 10) is None
    assert pot_growth_pct(200.0, 100.0, 0) is None


def test_the_expression_is_not_reimplemented_anywhere_else():
    """§5: the maths lives once. The engine keeps its own; the UI must not."""
    pattern = re.compile(r"\*\*\s*\(\s*1\s*/\s*(?:horizon_years|years|float\()")
    offenders = [
        f"{rel}:{n}: {line.strip()}"
        for rel in ("dashboard/pages/7_Simulaciones.py",
                    "dashboard/pages/12_Plan.py",
                    "dashboard/shared.py",
                    "reports/investment_plan.py")
        for n, line in enumerate(_src(rel).splitlines(), start=1)
        if pattern.search(line)
    ]
    assert not offenders, (
        "El crecimiento del pozo se recalcula a mano en vez de usar "
        "`pot_growth_pct`:\n" + "\n".join(offenders)
    )


# --------------------------------------------------------------------------- #
#  The wording says which of the two it is                                     #
# --------------------------------------------------------------------------- #


def test_the_two_labels_are_not_interchangeable():
    assert "pozo" in POT_GROWTH_LABEL.lower()
    assert "pozo" in POT_GROWTH_SHORT.lower()
    assert "cagr" not in POT_GROWTH_LABEL.lower()
    assert "cagr" not in POT_GROWTH_SHORT.lower()
    # With no flows the figure IS a CAGR and is allowed to say so.
    assert "cagr" in POT_CAGR_LABEL.lower()


def test_every_rendering_helper_switches_on_the_flag():
    for fn in (pot_growth_delta, pot_growth_column_label, pot_growth_help):
        with_flows = fn(True) if fn is not pot_growth_delta else fn(6.3, True)
        without = fn(False) if fn is not pot_growth_delta else fn(6.3, False)
        assert with_flows != without, f"{fn.__name__} no distingue los dos casos"


def test_a_fully_ruined_projection_reports_no_rate_at_all():
    """With every path dry the engine's ``nanmedian`` yields NaN, not a rate."""
    for flows in (True, False):
        text = pot_growth_delta(float("nan"), flows)
        assert "nan" not in text.lower()
        assert "sin tasa" in text
    assert "%" not in pot_growth_delta(float("inf"), True)


def test_the_help_names_what_the_number_is_not():
    text = pot_growth_help(True).lower()
    assert "no es un retorno" in text
    # The money-weighted answer is named as the thing the project does NOT
    # compute, so nobody reads the pot growth as a stand-in for it.
    assert "tir" in text or "irr" in text
    assert "aport" in text and "retir" in text


def test_the_help_warns_that_ruined_paths_are_dropped():
    assert "sobrevi" in pot_growth_help(True).lower()


def test_without_flows_the_help_does_not_cry_wolf():
    text = pot_growth_help(False).lower()
    assert "no es un retorno" not in text
    assert "cagr" in text


def test_the_no_hacer_is_respected_no_irr_was_built():
    """U1-7 forbids building the money-weighted return in this wave."""
    for rel in ("data/product_ux.py", "portfolio/monte_carlo.py",
                "dashboard/pages/7_Simulaciones.py"):
        src = _src(rel)
        assert not re.search(r"\bdef\s+\w*(?:irr|tir|xirr)\w*\s*\(", src, re.IGNORECASE), (
            f"{rel} implementa una TIR — el no_hacer de U1-7 lo prohíbe"
        )


# --------------------------------------------------------------------------- #
#  Surface sweep — no MC figure is printed as a bare "CAGR"                    #
# --------------------------------------------------------------------------- #

#: Files that may print Monte Carlo output to a person or to the model. The
#: fundamental Revenue/EPS CAGR, the crypto 4-year price CAGR and the
#: backtesting CAGR are genuinely CAGRs of a flow-free series and are a
#: different metric — their files are deliberately out of scope.
#: ``12_Plan.py`` shows no growth figure today; it is swept so that adding one
#: without the vocabulary fails here.
MC_RENDERING_SURFACES = [
    "dashboard/pages/7_Simulaciones.py",
    "dashboard/pages/12_Plan.py",
    "reports/investment_plan.py",
    "analysis/committee_prompts.py",
]

#: The subset that actually prints it today, and therefore must import the
#: vocabulary rather than merely avoid the word.
SURFACES_THAT_PRINT_IT = [
    "dashboard/pages/7_Simulaciones.py",
    "reports/investment_plan.py",
    "analysis/committee_prompts.py",
]

#: The Monte Carlo growth fields, wherever they are read.
_GROWTH_FIELD_RE = re.compile(r"median_cagr_pct|p10_cagr_pct")

#: What makes it honest: the canonical vocabulary, which decides per cash flow.
_QUALIFIED_RE = re.compile(
    r"POT_GROWTH_LABEL|POT_GROWTH_SHORT|POT_CAGR_LABEL"
    r"|pot_growth_delta|pot_growth_column_label|pot_growth_help|pot_growth_pct"
)

#: How far the label may sit from the value it labels. A PDF table row and a
#: ``st.metric`` call both split the two across lines, so a per-line sweep would
#: miss exactly the case this wave is about (verified by mutation).
_WINDOW = 4


def test_no_surface_prints_the_growth_as_a_bare_cagr():
    offenders = []
    for rel in MC_RENDERING_SURFACES:
        lines = _src(rel).splitlines()
        for i, line in enumerate(lines):
            if not _GROWTH_FIELD_RE.search(line):
                continue
            window = "\n".join(lines[max(0, i - _WINDOW):i + 2])
            if "CAGR" in window and not _QUALIFIED_RE.search(window):
                offenders.append(f"{rel}:{i + 1}: {line.strip()}")
    assert not offenders, (
        "Un crecimiento del pozo rotulado «CAGR» sin pasar por el vocabulario "
        "canónico (con flujos no es un retorno):\n" + "\n".join(offenders)
    )


def test_each_surface_imports_the_canonical_vocabulary():
    for rel in SURFACES_THAT_PRINT_IT:
        src = _src(rel)
        assert _QUALIFIED_RE.search(src), f"{rel} no importa el vocabulario de U1-7"


def test_the_committee_prompt_tells_the_model_which_one_it_is():
    """U1-3's lesson: the LLM reasons about whatever the string names."""
    ctx_builder = _src("analysis/committee.py")
    assert '"mc_has_cash_flows"' in ctx_builder, (
        "el contexto del comité no lleva el flag, así que el prompt no puede "
        "elegir la etiqueta correcta"
    )
    prompt = _src("analysis/committee_prompts.py")
    assert "mc_has_cash_flows" in prompt


def test_the_persisted_plan_carries_the_qualifier():
    """The exported bundle holds the number; it must hold the flag too."""
    store = _src("data/plan_store.py")
    # The *key* in the summary dict, not merely the import at the top of the file.
    assert '"mc_has_cash_flows": mc_has_cash_flows(' in store
    # Additive only: the existing key stays so plans already on disk still load.
    assert '"median_cagr_pct"' in store


# --------------------------------------------------------------------------- #
#  The numeric consumption — the one that was not a label                      #
# --------------------------------------------------------------------------- #


def test_the_gap_levers_no_longer_feed_the_growth_in_as_a_return():
    """``compute_gap_to_goal_levers`` compounds the contributions itself.

    Feeding it a pot growth that already contains them double-counts; feeding it
    one deflated by withdrawals understates the shortfall. Either way the levers
    print numbers that are wrong in a direction the user cannot see.
    """
    page = _src("dashboard/pages/7_Simulaciones.py")
    # Anchor on the call site (``annual_return=_er``), not on the import above it.
    idx = page.index("annual_return=_er")
    window = page[max(0, idx - 1200):idx]
    assert "median_cagr_pct" in window, "cambió la forma del call site; revisar"
    assert "mc_has_cash_flows" in window, (
        "la rama de palancas sigue tomando `median_cagr_pct` sin preguntar si "
        "hubo flujos"
    )


def test_the_levers_model_still_compounds_the_contributions_itself():
    """Guard for the premise above: if this stops being true, revisit the fix."""
    from data.product_ux import compute_gap_to_goal_levers

    without = compute_gap_to_goal_levers(
        capital=100_000, annual_contribution=0, years=20,
        annual_return=0.05, target=1_000_000,
    )
    with_contrib = compute_gap_to_goal_levers(
        capital=100_000, annual_contribution=12_000, years=20,
        annual_return=0.05, target=1_000_000,
    )
    # The contribution changes the projection, so it is being applied on top of
    # `annual_return` rather than assumed to be inside it.
    assert without != with_contrib
