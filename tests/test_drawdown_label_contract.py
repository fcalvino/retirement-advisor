"""Contract of the optimizer's drawdown estimate (U1-10).

``OptimizationResult.max_drawdown_estimate_pct`` is ``−1.5 × annual volatility``:
a rule of thumb and nothing else. No path is simulated, no history of *this*
portfolio is read, and the number is a linear function of the volatility alone —
yet five surfaces printed it as "Max Drawdown est." next to genuinely modelled
figures. The U1-10 ``no_hacer`` is "Presentarlo como dato de modelo".

Two things changed and neither is a number:

* the multiple moved to ``OptimizerConfig.max_dd_vol_multiple`` (still 1.5), so
  the tooltip can quote what the engine is actually applying instead of a
  literal typed next to it;
* every surface names the rule — and in the "vs Benchmarks" table the column is
  renamed, because the benchmark rows hold *realized historical* drawdowns from
  the ``_BENCHMARKS`` constants while the portfolio row holds the rule of thumb.
  That is the third mixed column of the same table, after the two U1-1 / U1-2
  renamed (return and ratio).

The simulated drawdown does exist elsewhere — ``MonteCarloResult.median_max_drawdown_pct``
over market paths — and the help points at it so the two are not confused.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from config import OPTIMIZER, OptimizerConfig
from data.product_ux import (
    MAX_DD_ESTIMATE_LABEL,
    MAX_DD_ESTIMATE_SHORT,
    max_dd_estimate_help,
)
from portfolio.optimizer import OptimizationResult, PortfolioOptimizer

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


#: Every surface that prints the number to a person or to the model.
RENDERING_SURFACES = [
    "dashboard/pages/5_Optimizer.py",
    "dashboard/pages/12_Plan.py",
    "analysis/prompts.py",
]

#: A drawdown figure named without saying it is a rule of thumb.
_DD_RE = re.compile(r"Max\s*(?:Drawdown|DD)", re.IGNORECASE)

#: What makes the claim honest on the same line: the canonical constants, the
#: help function, or the word for the rule itself.
_QUALIFIED_RE = re.compile(
    r"MAX_DD_ESTIMATE_LABEL|MAX_DD_ESTIMATE_SHORT|max_dd_estimate_help"
    r"|regla|rule of thumb|_BENCH_DD_COL",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
#  U1-10 — the oracle: the number never appears as a modelled figure           #
# --------------------------------------------------------------------------- #


def test_no_surface_prints_the_estimate_without_the_rule():
    offenders = [
        f"{rel}:{n}: {line.strip()}"
        for rel in RENDERING_SURFACES
        for n, line in enumerate(_src(rel).splitlines(), start=1)
        if _DD_RE.search(line) and not _QUALIFIED_RE.search(line)
    ]
    assert not offenders, (
        "Un drawdown mostrado sin decir que es una regla empírica sobre la "
        "volatilidad:\n" + "\n".join(offenders)
    )


def test_the_benchmark_column_says_it_mixes_two_measurements():
    """The portfolio row is the rule; the benchmark rows are realized history."""
    page = _src("dashboard/pages/5_Optimizer.py")
    assert '_BENCH_DD_COL = "Max DD hist. / regla %"' in page
    assert '"Max DD %"' not in page, "quedó la columna vieja, que no dice cuál es cuál"
    # The benchmark figures it mixes with are still the hardcoded historical ones.
    assert '"max_dd": -22.8' in page


def test_each_surface_imports_the_canonical_wording():
    optimizer_page = _src("dashboard/pages/5_Optimizer.py")
    assert "MAX_DD_ESTIMATE_LABEL" in optimizer_page
    assert "max_dd_estimate_help" in optimizer_page

    plan_page = _src("dashboard/pages/12_Plan.py")
    assert "MAX_DD_ESTIMATE_SHORT" in plan_page
    assert "max_dd_estimate_help()" in plan_page

    prompts = _src("analysis/prompts.py")
    assert "MAX_DD_ESTIMATE_SHORT" in prompts
    assert "max_dd_estimate_help()" in prompts


# --------------------------------------------------------------------------- #
#  The canonical wording says where the number comes from                      #
# --------------------------------------------------------------------------- #


def test_labels_carry_the_rule():
    assert "regla" in MAX_DD_ESTIMATE_LABEL.lower()
    assert "regla" in MAX_DD_ESTIMATE_SHORT.lower()


def test_help_quotes_the_multiple_from_config_not_from_a_literal():
    text = max_dd_estimate_help(OptimizerConfig(max_dd_vol_multiple=2.5))
    assert "2.5×" in text
    assert "1.5" not in text

    live = max_dd_estimate_help()
    assert f"{OPTIMIZER.max_dd_vol_multiple:.1f}×" in live


def test_help_separates_it_from_the_simulated_drawdown():
    text = max_dd_estimate_help()
    assert "no un modelo" in text.lower()
    assert "Monte Carlo" in text
    # The figure it must not be confused with really exists.
    from portfolio.monte_carlo import MonteCarloResult

    assert "median_max_drawdown_pct" in MonteCarloResult.__dataclass_fields__


# --------------------------------------------------------------------------- #
#  no_hacer — the multiple moved to config; its value did not                  #
# --------------------------------------------------------------------------- #


def test_the_multiple_is_config_and_still_one_point_five():
    assert OPTIMIZER.max_dd_vol_multiple == 1.5
    assert OptimizerConfig().max_dd_vol_multiple == 1.5


def test_the_call_site_reads_config_instead_of_a_literal():
    src = _src("portfolio/optimizer.py")
    assert "self.opt.max_dd_vol_multiple" in src
    assert "volatility_pct * 1.5" not in src


def _reference_estimate(volatility_pct: float, multiple: float) -> float:
    """The rule, spelled out: minus `multiple` times the annual volatility."""
    return round(-volatility_pct * multiple, 1)


def test_the_estimate_still_equals_the_rule():
    """Oracle: the shipped engine reproduces the rule for a range of vols.

    Written from the definition rather than from the production expression, so a
    later change of the rule fails here instead of being frozen in.
    """
    opt = PortfolioOptimizer("conservative")
    tickers = [
        {"symbol": "AAA", "adjusted_score": 70.0, "dividend_yield": 2.0,
         "moat_score": 10.0, "sector": "Technology"},
        {"symbol": "BBB", "adjusted_score": 65.0, "dividend_yield": 3.0,
         "moat_score": 8.0, "sector": "Healthcare"},
    ]
    weights = np.array([0.5, 0.5])
    mu = np.array([0.08, 0.06])

    for sigma in (0.05, 0.12, 0.184, 0.30):
        cov = np.array([[sigma ** 2, 0.0], [0.0, sigma ** 2]])
        result = OptimizationResult(profile_name="conservative", method="test")
        opt._populate_result(result, tickers, weights, mu, cov)

        # Two uncorrelated assets at equal weight: portfolio vol = sigma / sqrt(2).
        expected_vol = round(float(sigma / np.sqrt(2)) * 100, 1)
        assert result.volatility_pct == expected_vol
        assert result.max_drawdown_estimate_pct == _reference_estimate(
            expected_vol, OPTIMIZER.max_dd_vol_multiple
        )


def test_a_zero_volatility_portfolio_reports_no_estimate():
    """The rule is a multiple of vol, so no vol means no number to show."""
    opt = PortfolioOptimizer("conservative")
    tickers = [{"symbol": "AAA", "adjusted_score": 70.0, "dividend_yield": 2.0,
                "moat_score": 10.0, "sector": "Technology"}]
    result = OptimizationResult(profile_name="conservative", method="test")
    opt._populate_result(result, tickers, np.array([1.0]), np.array([0.07]),
                         np.zeros((1, 1)))
    assert result.max_drawdown_estimate_pct == 0.0
