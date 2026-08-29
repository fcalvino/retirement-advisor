"""Oracle for the optimizer's expected-return proxy (backlog U5-6 / U6-1).

``PortfolioOptimizer._expected_returns`` builds the Black-Litterman view μ as
``score_ret + div_ret + moat_ret``. But the ``adjusted_score`` feeding
``score_ret`` **already contains** the moat bonus — ``min(moat_total × 0.5,
max_bonus)``, added in ``FundamentalAnalyzer.analyze``. So a moat was paid twice:
once through the score the engine had already decided it was worth, and again
through a term of its own. The optimizer therefore overweighted wide-moat
companies relative to what the rest of the engine says they are worth.

Measured over the 150 cached equities, removing the duplicate term moves μ by
−0.50 pp on average and turns over 2 names in the top 20.

The test that matters is a *differential* one, because it isolates the defect
without depending on any constant: hold ``adjusted_score`` fixed and vary
``moat_score``. If the moat is paid once — through the score — μ cannot move.
If it is paid twice, it does. The anti-cheat sits next to it: a moat that
changes the score still has to change μ, or the fix would have deleted the
signal instead of the duplication.

No network, no Streamlit.
"""

from __future__ import annotations

import pytest

from config import VIEW_WEIGHTS
from portfolio.optimizer import PortfolioOptimizer

SCORE_PROXY_MAX = 0.18   # optimizer._expected_returns: score/100 × 0.18


def _ticker(symbol="X", *, score=70.0, div=2.0, moat=10.0, tailwind=0.0):
    return {
        "symbol": symbol,
        "adjusted_score": score,
        "dividend_yield": div,
        "moat_score": moat,
        "tailwind_score": tailwind,
    }


def oracle_expected_return(score: float, div_pct: float) -> float:
    """Reference: the two things a return proxy is allowed to be built from.

    Written from the definition rather than from the source — a scored view of
    the business plus the cash it actually pays out. The moat is deliberately
    absent: it is not a third source of return, it is one of the reasons the
    score is what it is, and the engine already priced it there.
    """
    return VIEW_WEIGHTS.score * (score / 100.0) * SCORE_PROXY_MAX + (
        VIEW_WEIGHTS.dividend * (div_pct / 100.0)
    )


class TestTheMoatIsPaidOnce:
    """The defect, isolated: μ must not move when only the moat moves."""

    @pytest.mark.parametrize("profile", ["conservative", "moderate", "aggressive"])
    def test_moat_alone_cannot_move_the_expected_return(self, profile):
        opt = PortfolioOptimizer(profile)
        none_moat, wide_moat = opt._expected_returns(
            [_ticker(moat=0.0), _ticker(moat=20.0)]
        )
        assert none_moat == pytest.approx(wide_moat, rel=1e-12)

    def test_a_moat_that_moved_the_score_still_moves_mu(self):
        """Anti-cheat: the fix removes a duplicate, not the signal.

        A wide moat earns a bonus inside ``adjusted_score``. That is the one
        channel it is allowed to use, and it has to still work.
        """
        opt = PortfolioOptimizer("moderate")
        without_bonus, with_bonus = opt._expected_returns(
            [_ticker(score=70.0, moat=0.0), _ticker(score=80.0, moat=20.0)]
        )
        assert with_bonus > without_bonus

    def test_matches_the_reference(self):
        opt = PortfolioOptimizer("moderate")
        for score, div in ((0.0, 0.0), (55.0, 1.5), (100.0, 6.0)):
            (engine,) = opt._expected_returns([_ticker(score=score, div=div)])
            assert engine == pytest.approx(oracle_expected_return(score, div), rel=1e-12)


class TestTheViewStaysProfileIndependent:
    """Audit D3: μ is a property of the asset, not of who is looking at it."""

    def test_every_profile_sees_the_same_expected_return(self):
        rows = [_ticker(score=82.0, div=3.1, moat=17.0)]
        mus = [PortfolioOptimizer(p)._expected_returns(rows)[0]
               for p in ("conservative", "moderate", "aggressive")]
        assert mus[0] == pytest.approx(mus[1]) == pytest.approx(mus[2])


class TestTheWeightsSayWhatTheyAre:
    def test_the_moat_view_weight_is_gone_rather_than_zeroed(self):
        """A weight left at 0.0 reads as a tunable knob that happens to be off.

        It is not: re-enabling it would restore the double count. The field is
        removed so the mistake cannot be made by editing config.
        """
        assert not hasattr(VIEW_WEIGHTS, "moat")

    def test_the_remaining_weights_were_not_renormalised(self):
        """Renormalising would have undone the fix it was cleaning up after.

        Scaling 0.50/0.30 to 0.625/0.375 keeps the sum at 1, but it inflates the
        moat contribution that legitimately survives inside the score along with
        everything else: measured over the cached universe, μ would have RISEN
        by 1.24 pp, against the 0.50 pp the duplicate removal takes off.
        """
        assert VIEW_WEIGHTS.score == pytest.approx(0.50)
        assert VIEW_WEIGHTS.dividend == pytest.approx(0.30)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
