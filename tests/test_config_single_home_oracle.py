"""Oracle for "one number, one home" — backlog U5-9, U5-10 and U5-11.

Three rows of the backlog, one defect wearing three faces: config and code
disagree about where a number lives.

  * **U5-9** — a band the engine grades against is spelled in the middle of the
    branch that uses it, so `config.py` cannot be the source of truth it claims
    to be. Editing the documented knob changes nothing.
  * **U5-10** — the *same* economic quantity (the annual risk-free rate) is
    declared three times in `config.py`, in two units, with two values. Nobody
    chose the discrepancy; it drifted.
  * **U5-11** — the reverse direction: four fields sit in config, are shown to
    the user as "the weighting of the sizing logic", and no decision reads them.

The oracle for all three is the same question, and it is deliberately *not*
"is the literal still in the file". Grepping for `0.18` pins the fix's shape,
not its meaning: a fix that moved the number into config and then ignored it
would pass. So every test here is **differential** — move the knob, and the
engine's answer has to move with it (U5-9, U5-10), or prove the knob moves
nothing at all and therefore must not be described as if it did (U5-11).

No network, no Streamlit.
"""

from __future__ import annotations

import copy

import pandas as pd
import pytest

from analysis.fundamental import FundamentalAnalyzer, FundamentalResult
from config import (
    BACKTEST,
    MOAT,
    MONTE_CARLO,
    OPTIMIZER,
    PERSONAL_BOOK,
    THRESHOLDS,
    VIEW_WEIGHTS,
)
from portfolio.optimizer import PortfolioOptimizer
from portfolio.personal_sizer import analyze_personal_book


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def restore_thresholds():
    """Mutating a module-level singleton must not leak into the next test."""
    saved = copy.deepcopy(THRESHOLDS.__dict__)
    yield THRESHOLDS
    THRESHOLDS.__dict__.update(saved)


@pytest.fixture
def restore_optimizer_cfg():
    saved = copy.deepcopy(OPTIMIZER.__dict__)
    yield OPTIMIZER
    OPTIMIZER.__dict__.update(saved)


def _ticker(symbol="X", *, score=70.0, div=2.0, tailwind=0.0):
    return {
        "symbol": symbol,
        "adjusted_score": score,
        "dividend_yield": div,
        "moat_score": 0.0,
        "tailwind_score": tailwind,
    }


def _health_score(analyzer: FundamentalAnalyzer, quick_ratio: float) -> float:
    """Financial-health points for a company whose ONLY reported metric is the
    quick ratio. Everything else is absent, so it contributes nothing and the
    difference between two calls isolates the quick-ratio band."""
    result = FundamentalResult(symbol="QR", company_name="QR")
    return analyzer._score_financial_health(
        {"quickRatio": quick_ratio},
        pd.DataFrame(),
        pd.DataFrame(),
        result,
    )


def _growth_score(analyzer: FundamentalAnalyzer, fcf_yield_pct: float) -> float:
    """Growth points for a company whose only reported figure is one year of
    free cash flow. One year means `compute_cagr` has nothing to grow from, so
    the FCF-growth half stays at zero and the yield band is isolated."""
    market_cap = 1_000.0
    cashflow = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [market_cap * fcf_yield_pct / 100.0]},
        index=["Free Cash Flow"],
    )
    result = FundamentalResult(symbol="FCF", company_name="FCF")
    result.market_cap = market_cap
    return analyzer._score_growth({}, pd.DataFrame(), cashflow, result)


# --------------------------------------------------------------------------- #
#  U5-9 — the band the engine grades against has to be the one in config       #
# --------------------------------------------------------------------------- #


class TestTheReturnProxySpanLivesInConfig:
    """`score/100 × 0.18` — the span that turns a 0–100 score into an annual
    return proxy. It is the single largest lever in μ (it *is* μ's scale) and it
    was the one number in the expression with no name and no home."""

    def test_the_span_is_a_named_knob(self):
        assert hasattr(OPTIMIZER, "score_return_span")

    def test_mu_matches_the_reference_at_the_shipped_span(self):
        """Reference written from the definition: a scored view of the business,
        weighted, plus the cash it pays out, weighted."""
        opt = PortfolioOptimizer("moderate")
        span = OPTIMIZER.score_return_span
        for score, div in ((0.0, 0.0), (55.0, 1.5), (100.0, 6.0)):
            (engine,) = opt._expected_returns([_ticker(score=score, div=div)])
            expected = (
                VIEW_WEIGHTS.score * (score / 100.0) * span
                + VIEW_WEIGHTS.dividend * (div / 100.0)
            )
            assert engine == pytest.approx(expected, rel=1e-12)

    def test_moving_the_knob_moves_mu(self, restore_optimizer_cfg):
        """The differential that a grep for `0.18` cannot make: a fix that put
        the number in config and kept reading the literal would pass a grep and
        fail this."""
        opt = PortfolioOptimizer("moderate")
        OPTIMIZER.er_absolute_cap = 0.0          # uncap, so the span is visible
        OPTIMIZER.score_return_span = 0.18
        (at_shipped,) = opt._expected_returns([_ticker(score=100.0, div=0.0)])
        OPTIMIZER.score_return_span = 0.36
        (at_double,) = opt._expected_returns([_ticker(score=100.0, div=0.0)])
        assert at_double == pytest.approx(at_shipped * 2, rel=1e-12)

    def test_the_shipped_value_did_not_move(self):
        """A hygiene move that quietly recalibrates μ is not a hygiene move."""
        assert OPTIMIZER.score_return_span == pytest.approx(0.18)


class TestTheQuickRatioBandsLiveInConfig:
    """`qr >= 1.5 → 3 pts, qr >= 1.0 → 2 pts` — two literals inside
    `_score_financial_health`, next to seven sibling bands that all read
    `THRESHOLDS`."""

    def test_the_bands_are_named_knobs(self):
        assert hasattr(THRESHOLDS, "min_quick_ratio_good")
        assert hasattr(THRESHOLDS, "min_quick_ratio_ok")

    def test_raising_the_top_band_demotes_a_company_that_used_to_clear_it(
        self, restore_thresholds
    ):
        analyzer = FundamentalAnalyzer()
        at_shipped = _health_score(analyzer, 1.6) - _health_score(analyzer, 0.5)
        assert at_shipped == pytest.approx(2.0)   # 3 pts vs 1 pt

        THRESHOLDS.min_quick_ratio_good = 2.5
        raised = _health_score(analyzer, 1.6) - _health_score(analyzer, 0.5)
        assert raised == pytest.approx(1.0)       # 1.6 falls to the 2-pt band

    def test_the_shipped_values_did_not_move(self):
        assert THRESHOLDS.min_quick_ratio_good == pytest.approx(1.5)
        assert THRESHOLDS.min_quick_ratio_ok == pytest.approx(1.0)


class TestTheFcfYieldBandsLiveInConfig:
    """`fcf_yield >= 4 → 3 pts, >= 2 → 2 pts` in `_score_growth`, three lines
    above `T.fcf_growth_excellent` — the same dimension reading config for its
    growth half and a literal for its yield half."""

    def test_the_bands_are_named_knobs(self):
        assert hasattr(THRESHOLDS, "fcf_yield_excellent")
        assert hasattr(THRESHOLDS, "fcf_yield_good")

    def test_raising_the_top_band_demotes_a_company_that_used_to_clear_it(
        self, restore_thresholds
    ):
        analyzer = FundamentalAnalyzer()
        at_shipped = _growth_score(analyzer, 5.0) - _growth_score(analyzer, 3.0)
        assert at_shipped == pytest.approx(1.0)   # 3 pts vs 2 pts

        THRESHOLDS.fcf_yield_excellent = 8.0
        raised = _growth_score(analyzer, 5.0) - _growth_score(analyzer, 3.0)
        assert raised == pytest.approx(0.0)       # both land in the 2-pt band

    def test_the_shipped_values_did_not_move(self):
        assert THRESHOLDS.fcf_yield_excellent == pytest.approx(4.0)
        assert THRESHOLDS.fcf_yield_good == pytest.approx(2.0)


class TestTheHalfOfU59ThatAlreadyClosed:
    """U5-9 enumerated eight literals; five of them were centralised by later
    rows before this one was worked. Pinned so the row cannot silently reopen.
    """

    def test_the_tax_rate_is_per_jurisdiction(self):
        """U3-8: `0.21`/`0.79` were the United States' rate applied to every
        issuer. They live in `TAXES.corporate_tax_rate_pct` now."""
        from analysis.utils import corporate_tax_rate_pct

        assert corporate_tax_rate_pct("Argentina") == pytest.approx(35.0)
        assert corporate_tax_rate_pct("United States") == pytest.approx(21.0)
        assert corporate_tax_rate_pct("Ireland") == pytest.approx(12.5)

    def test_the_dilution_tolerance_is_a_knob(self):
        """U5-3: F6's `shares[0] <= shares[1] * 1.02`."""
        from config import PIOTROSKI

        assert PIOTROSKI.max_dilution_pct == pytest.approx(2.0)

    def test_the_drawdown_multiple_is_a_knob(self):
        """U1-10: `−1.5 × annual vol`."""
        assert OPTIMIZER.max_dd_vol_multiple == pytest.approx(1.5)

    def test_the_payout_cut_is_a_knob_and_depends_on_the_basis(self):
        """U5-4: a literal `80` graded REITs on an earnings payout."""
        from analysis.fundamental import max_payout_for

        assert max_payout_for("earnings") == pytest.approx(THRESHOLDS.max_payout_ratio)
        assert max_payout_for("ffo") == pytest.approx(THRESHOLDS.reit_max_payout_ratio)
        assert max_payout_for("ffo") != max_payout_for("earnings")

    def test_the_tailwind_tilt_is_a_knob(self):
        """The `0.05` U5-9 lists next to `0.18` is `TAILWINDS.optimizer_er_tilt`."""
        from config import TAILWINDS

        assert TAILWINDS.optimizer_er_tilt == pytest.approx(0.05)


# --------------------------------------------------------------------------- #
#  U5-10 — one economic quantity, one declaration                              #
# --------------------------------------------------------------------------- #


class TestTheRiskFreeRateHasOneHome:
    """Three declarations, two units, two values:

      * `BACKTEST.risk_free_rate = 0.045`   (fraction) — Sharpe of the backtest
      * `OPTIMIZER.risk_free_rate = 0.045`  (fraction) — the attractiveness/vol ratio
      * `MOAT.risk_free_proxy_pct = 4.0`    (percent)  — the cost-of-equity hurdle

    The third is the same rate as the other two and disagrees with them by 50 bp.
    Whichever value is right, three of them cannot be.
    """

    def test_there_is_a_canonical_declaration(self):
        import config

        assert hasattr(config, "RISK_FREE")

    def test_the_three_consumers_agree_on_the_number(self):
        assert BACKTEST.risk_free_rate * 100 == pytest.approx(
            OPTIMIZER.risk_free_rate * 100
        )
        assert MOAT.risk_free_proxy_pct == pytest.approx(OPTIMIZER.risk_free_rate * 100)

    def test_the_units_are_stated_by_the_name(self):
        """`risk_free_rate` is a fraction and `risk_free_proxy_pct` a percent —
        the 100× that separates them is exactly the kind of thing that turns a
        4.5 % hurdle into a 450 % one when someone unifies them by hand."""
        import config

        assert config.RISK_FREE.annual_pct == pytest.approx(
            config.RISK_FREE.annual_fraction * 100
        )

    def test_the_shipped_value_is_the_one_both_calibrations_used(self):
        """4.5 %, not 4.0 %: two of the three sites already said 4.5, and the
        moat's ROIC spread bands were calibrated against a hurdle, not against
        this particular half-point. The measured effect is reported in the PR."""
        import config

        assert config.RISK_FREE.annual_pct == pytest.approx(4.5)


class TestTheDeadBootstrapKnob:
    """`MONTE_CARLO.block_size_weeks = 4` is read by nothing: the simulator uses
    its own class constant `MonteCarloSimulator.BLOCK_SIZE = 4`. A config field
    that looks tunable and is not is worse than no field — editing it is a
    silent no-op."""

    def test_the_simulator_reads_the_config_field(self):
        from portfolio.monte_carlo import MonteCarloSimulator

        assert MonteCarloSimulator(["SPY"]).block_size == MONTE_CARLO.block_size_weeks

    def test_moving_the_knob_moves_the_block(self):
        saved = MONTE_CARLO.block_size_weeks
        try:
            from portfolio.monte_carlo import MonteCarloSimulator

            MONTE_CARLO.block_size_weeks = 9
            assert MonteCarloSimulator(["SPY"]).block_size == 9
        finally:
            MONTE_CARLO.block_size_weeks = saved

    def test_the_shipped_value_did_not_move(self):
        assert MONTE_CARLO.block_size_weeks == 4


class TestTheDividendYieldCeilingHasOneHome:
    """Two ceilings for "this yield cannot be real", 15 % apart:

      * `THRESHOLDS.max_plausible_dividend_yield_pct = 30.0`, used by
        `normalize_dividend_yield_pct` — which *logs* the discard;
      * a literal `15.0` inside `PortfolioOptimizer._clean_div_yield`, which
        silently rewrites the yield to 0.0.

    A yield of 20 % is therefore simultaneously plausible (scored) and
    implausible (dropped from μ), depending on which surface is asking.
    """

    def test_the_optimizer_reads_the_configured_ceiling(self):
        opt = PortfolioOptimizer("moderate")
        ceiling = THRESHOLDS.max_plausible_dividend_yield_pct
        assert opt._clean_div_yield(ceiling - 0.1) == pytest.approx(ceiling - 0.1)
        assert opt._clean_div_yield(ceiling + 0.1) == 0.0

    def test_a_yield_the_scorer_accepts_is_not_dropped_by_the_optimizer(
        self, restore_thresholds
    ):
        """The defect, stated as the contradiction it is."""
        from analysis.fundamental import normalize_dividend_yield_pct

        opt = PortfolioOptimizer("moderate")
        scored = normalize_dividend_yield_pct({"dividendYield": 20.0})
        assert scored == pytest.approx(20.0)
        assert opt._clean_div_yield(scored) == pytest.approx(20.0)


# --------------------------------------------------------------------------- #
#  U5-11 — a weighting that weights nothing                                    #
# --------------------------------------------------------------------------- #


def _book_fixture():
    positions = {
        "AAA": {"symbol": "AAA", "shares": 10.0, "avg_cost": 100.0,
                "current_price": 100.0, "market_value": 1_000.0, "weight_pct": 10.0},
        "BBB": {"symbol": "BBB", "shares": 10.0, "avg_cost": 100.0,
                "current_price": 100.0, "market_value": 3_000.0, "weight_pct": 30.0},
        "CCC": {"symbol": "CCC", "shares": 10.0, "avg_cost": 100.0,
                "current_price": 100.0, "market_value": 6_000.0, "weight_pct": 60.0},
    }
    views = {
        "AAA": {"adjusted_score": 84.0, "moat_classification": "Wide",
                "tailwind_classification": "Strong", "has_margin_of_safety": True,
                "margin_of_safety_pct": 12.0, "data_quality_level": "good",
                "rsi_weekly": 55.0, "above_sma200": True, "price_vs_52w_high_pct": -3.0},
        "BBB": {"adjusted_score": 64.0, "moat_classification": "Narrow",
                "tailwind_classification": "Neutral", "has_margin_of_safety": False,
                "margin_of_safety_pct": None, "data_quality_level": "good",
                "rsi_weekly": 48.0, "above_sma200": True, "price_vs_52w_high_pct": -8.0},
        "CCC": {"adjusted_score": 35.0, "moat_classification": "None",
                "tailwind_classification": "Headwind", "has_margin_of_safety": False,
                "margin_of_safety_pct": None, "data_quality_level": "partial",
                "rsi_weekly": 32.0, "above_sma200": False, "price_vs_52w_high_pct": -25.0},
    }
    convictions = {"AAA": "HIGH", "BBB": "MEDIUM", "CCC": "HIGH"}
    return positions, convictions, lambda s: views[s]


class TestTheSizingWeightsAreNotAWeighting:
    """`weight_quality_moat_tailwind = 45` and its three siblings were shown to
    the user as *"Ponderación de la lógica de sizing"*. `_decide_sizing` is a
    cascade of hard gates — `score < sell_all_score`, `weight >= max_practical`,
    `is_core`, … — with no weighted sum anywhere. The four axes are real; the
    45/20/20/15 split describing how they combine is not.
    """

    def test_the_four_fields_are_gone(self):
        """Left at their values they read as a knob; set to 0 they read as a
        disabled feature. Neither is true — there is nothing to tune."""
        for field in (
            "weight_quality_moat_tailwind",
            "weight_valuation_technical",
            "weight_user_conviction",
            "weight_book_context_risk",
        ):
            assert not hasattr(PERSONAL_BOOK, field), field
            assert field not in PERSONAL_BOOK.as_dict(), field

    def test_every_number_it_cites_is_a_number_a_gate_reads(self):
        """The oracle for "promete lo que no calcula", stated so it survives a
        rewrite of the prose: whatever figures the justification shows the user,
        each one has to be a threshold some gate actually compares against.

        45/20/20/15 fails this — no gate reads them. 40 (`sell_all_score`),
        40 (`max_practical_concentration_single_name`) and 72
        (`min_score_for_core_concentration`) pass, because `_decide_sizing`
        branches on all three.
        """
        import re

        positions, convictions, enrich = _book_fixture()
        analysis = analyze_personal_book(positions, convictions, enrich)
        text = analysis.concentration_justification_overall

        readable = {
            round(float(v), 1)
            for v in PERSONAL_BOOK.as_dict().values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        cited = {round(float(m), 1) for m in re.findall(r"\d+(?:[.,]\d+)?", text)}
        orphans = cited - readable
        assert not orphans, (
            f"the justification cites {sorted(orphans)}, which no sizing gate reads: {text}"
        )

    def test_the_justification_still_names_the_axes_that_do_decide(self):
        """Anti-cheat: the fix deletes a false proportion, not the explanation.
        The four axes really are what the gates read."""
        positions, convictions, enrich = _book_fixture()
        analysis = analyze_personal_book(positions, convictions, enrich)
        text = analysis.concentration_justification_overall.lower()
        for axis in ("calidad", "moat", "convicción", "riesgo"):
            assert axis in text, axis

    def test_the_decisions_never_depended_on_them(self):
        """The measurement behind the row, kept as a test: with the four fields
        set to any split at all, every recommendation is byte-identical. That is
        what makes the 45/20/20/15 claim false rather than merely undocumented.

        Skipped once the fields are gone — there is nothing left to mutate, and
        that absence is what `test_the_four_fields_are_gone` pins.
        """
        if not hasattr(PERSONAL_BOOK, "weight_quality_moat_tailwind"):
            pytest.skip("fields removed — inertness is now structural")

        positions, convictions, enrich = _book_fixture()
        before = analyze_personal_book(positions, convictions, enrich).to_dict()

        saved = copy.deepcopy(PERSONAL_BOOK.__dict__)
        try:
            PERSONAL_BOOK.weight_quality_moat_tailwind = 90
            PERSONAL_BOOK.weight_valuation_technical = 5
            PERSONAL_BOOK.weight_user_conviction = 3
            PERSONAL_BOOK.weight_book_context_risk = 2
            after = analyze_personal_book(positions, convictions, enrich).to_dict()
        finally:
            PERSONAL_BOOK.__dict__.update(saved)

        assert [r["action"] for r in before["recommendations"]] == [
            r["action"] for r in after["recommendations"]
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
