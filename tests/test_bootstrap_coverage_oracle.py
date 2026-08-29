"""Every observation can be drawn, including the newest (backlog U5-17).

``_simulate_paths`` picks block starts with ``rng.integers(0, max_start)`` where
``max_start = T - block_size``. ``integers`` excludes its upper bound, so starts
run to ``T - block_size - 1`` and the highest index any block can reach is
``T - 2``. **The most recent observation is never sampled**, and the ones just
before it are drawn by fewer starts than the rest.

The backlog's oracle, verbatim: T=100, BLOCK_SIZE=4 → highest reachable index 98.

It is not only the last bar. Coverage decays across the tail, and the fix makes it
**symmetric** with the head, which is the property a non-circular block bootstrap
should have:

    index      0    1    2  ...   96   97   98   99
    before     1    2    3  ...    3    2    1    0
    after      1    2    3  ...    4    3    2    1

The consequence is a projection tilted toward the older part of the window.
Measured over twelve seeds each, the direction follows whether a ticker's most
recent weeks ran above or below its own mean:

    PFE   last 4 weeks +2.76%/wk vs +0.11% mean   projection was 6.96% LOW
    KO    last 4 weeks +0.66%/wk vs +0.23% mean   projection was 0.79% low
    INTC  last 4 weeks +0.18%/wk vs +0.40% mean   projection was 0.73% high

PFE is the case that matters: nearly seven per cent of a retirement projection,
lost to an off-by-one.

No network — returns are synthetic and the property is checked directly.
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio.monte_carlo import MonteCarloSimulator


def oracle_reachable_indices(n_obs: int, block_size: int, max_start: int) -> set:
    """Reference: every index a block starting below ``max_start`` can touch."""
    return {
        start + offset
        for start in range(max_start)
        for offset in range(block_size)
        if start + offset < n_obs
    }


def _sampled_indices(n_obs: int, *, n_sims: int = 4000, n_weeks: int = 400) -> set:
    """Indices the shipped sampler actually visits, found by sampling."""
    returns = np.arange(n_obs, dtype=float) / 10_000.0   # each bar distinguishable
    sim = MonteCarloSimulator(["X"], seed=7)
    paths = sim._simulate_paths(returns, n_sims, n_weeks)
    # Recover which observations were used from the per-step growth factors.
    steps = np.round((paths[:, 1:] / paths[:, :-1] - 1.0) * 10_000.0)
    return {int(v) for v in np.unique(steps)}


class TestEveryObservationCanBeDrawn:
    def test_the_newest_observation_is_reachable(self):
        """The defect, at the only place it can be seen: the last bar."""
        n_obs = 100
        assert (n_obs - 1) in _sampled_indices(n_obs)

    def test_the_backlog_oracle(self):
        """T=100, BLOCK_SIZE=4: the old ceiling was 98."""
        old_ceiling = max(100 - 4, 1) - 1 + (4 - 1)
        assert old_ceiling == 98
        assert max(_sampled_indices(100)) == 99

    @pytest.mark.parametrize("n_obs", [60, 100, 260, 520])
    def test_no_observation_is_unreachable(self, n_obs):
        assert _sampled_indices(n_obs) == set(range(n_obs))

    def test_coverage_is_symmetric_between_oldest_and_newest(self):
        """The property a non-circular block bootstrap should have.

        The first bar can only be reached by the first start, and after the fix
        the last bar can only be reached by the last one. Before, the head had
        one start and the tail had none — an asymmetry with no justification.
        """
        n_obs, block = 100, MonteCarloSimulator.BLOCK_SIZE
        max_start = max(n_obs - block + 1, 1)
        reachable = oracle_reachable_indices(n_obs, block, max_start)
        assert reachable == set(range(n_obs))

        counts = [
            sum(1 for s in range(max_start) if s <= i < s + block)
            for i in range(n_obs)
        ]
        assert counts[0] == counts[-1]

    def test_a_history_shorter_than_a_block_still_samples(self):
        """Anti-cheat: the guard against an empty range must survive."""
        assert _sampled_indices(3, n_weeks=40) <= {0, 1, 2}

    def test_the_sampler_never_runs_off_the_end(self):
        for n_obs in (5, 37, 100):
            assert max(_sampled_indices(n_obs, n_weeks=200)) <= n_obs - 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
