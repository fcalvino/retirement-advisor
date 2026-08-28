"""Contract of the offline score harness (backlog U0-2).

``scripts/measure_score_impact.py`` exists so that a change to the scoring
engine can be argued about with numbers instead of opinions. U3-7 needs one
particular measurement from it — how much of a ticker's moat comes from the AI
layer — which means running the same universe twice, with AI off and on.

That is only useful if two promises hold, and both are easy to break silently:

  * **it never goes to the network.** The AI path has three call sites; two are
    cached (moat, tailwind) and one is not (the decision layer). Nothing in the
    old guards covered any of them, because they only touched the price cache.
  * **it says when the AI did not actually run.** ``AIAnalyzer.analyze``
    swallows every exception and falls back to the rule-based decision, so an
    unreachable provider produces a result that looks like a successful AI run
    with nothing to say. A column of unchanged scores would read as "the AI
    changes nothing" when it means "the AI never happened".

These tests pin both. They never touch the real cache or the real universe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.measure_score_impact import (  # noqa: E402
    _OFFLINE_TTL_HOURS,
    _make_offline,
    offline_ai_config,
    render_matrix,
)


@pytest.fixture
def restore_ai_config():
    """Undo the in-process mutations ``_make_offline`` makes to the singletons."""
    from config import MOAT, MULTI_SOURCE, TAILWINDS

    saved = (
        MOAT.ai_cache_ttl_hours, MOAT.ai_cache_only,
        TAILWINDS.ai_cache_ttl_hours, TAILWINDS.ai_cache_only,
        MULTI_SOURCE.attach_in_pipeline,
    )
    yield
    (MOAT.ai_cache_ttl_hours, MOAT.ai_cache_only,
     TAILWINDS.ai_cache_ttl_hours, TAILWINDS.ai_cache_only,
     MULTI_SOURCE.attach_in_pipeline) = saved


# ================================================================== #
#  The guards that keep it offline                                     #
# ================================================================== #

class TestTheOfflineGuards:
    def test_the_ai_caches_are_reached_too(self, restore_ai_config):
        """The analyzers build their OWN DataCache, so the singleton is not enough.

        ``MoatAnalyzer._get_cache`` and ``TailwindAnalyzer._get_cache`` each
        construct a ``DataCache(ttl_hours=self.cfg.ai_cache_ttl_hours)``, which
        the module-level cache's TTL never touched. And ``DataCache.get``
        *deletes* a row it finds expired — so before this guard, the first run
        with AI on would have destroyed the older cached moat entries on disk
        while the docstring promised nothing on disk changes.
        """
        from config import MOAT, TAILWINDS

        _make_offline()
        assert MOAT.ai_cache_ttl_hours == _OFFLINE_TTL_HOURS
        assert TAILWINDS.ai_cache_ttl_hours == _OFFLINE_TTL_HOURS

    def test_a_cache_miss_does_not_call_the_provider(self, restore_ai_config):
        from config import MOAT, TAILWINDS

        _make_offline()
        assert MOAT.ai_cache_only is True
        assert TAILWINDS.ai_cache_only is True

    def test_the_decision_layer_never_fires(self):
        """It is the one AI call with no cache behind it."""
        assert offline_ai_config().enrich_only is True

    def test_the_measured_model_is_the_one_the_cache_was_written_with(self):
        """The moat cache key embeds provider and model.

        Measuring under a different model would miss every row and report "the
        AI changes nothing", when the truth is that we looked in the wrong
        drawer. So the harness reads the same env the app reads.
        """
        from config import AI_CONFIG

        resolved = offline_ai_config()
        assert resolved.provider == AI_CONFIG.provider
        assert resolved.model == AI_CONFIG.model
        assert resolved.enabled is True


class TestEnrichOnlyStillScoresWithAI:
    """enrich_only must silence the decision, not the whole AI layer.

    If it skipped the cached moat enrichment too, the "AI on" leg would be
    identical to the "AI off" leg by construction and the matrix would measure
    nothing at all.
    """

    def test_the_decision_falls_back_but_the_score_does_not(self):
        source = (ROOT / "analysis" / "strategy.py").read_text(encoding="utf-8")
        # The fundamental analyzer still receives ai_config…
        assert "FundamentalAnalyzer().analyze(symbol, ai_config=ai_config)" in source
        # …and only the decision branch consults the flag.
        assert 'not getattr(ai_config, "enrich_only", False)' in source


# ================================================================== #
#  The matrix says what it knows and what it does not                  #
# ================================================================== #

def _row(**over):
    row = {
        "symbol": "X", "adjusted_score": 70.0, "action": "BUY",
        "moat_score": 9.0, "moat_bonus": 4.5, "moat_classification": "Narrow",
        "ai_ran": True,
    }
    row.update(over)
    return row


class TestTheMatrixReportsHonestly:
    def test_a_row_the_ai_never_reached_is_counted_separately(self):
        off = {"A": _row(), "B": _row()}
        on = {"A": _row(adjusted_score=73.0), "B": _row(ai_ran=False)}

        report = render_matrix(off, on)
        assert "1/2" in report
        assert "quant-only" in report

    def test_the_ceiling_of_each_mode_is_reported(self):
        """The whole of U3-7 in two numbers: what each mode can actually reach."""
        off = {"A": _row(moat_score=12.0), "B": _row(moat_score=11.0)}
        on = {"A": _row(moat_score=18.0), "B": _row(moat_score=15.0)}

        report = render_matrix(off, on)
        assert "12.0" in report and "18.0" in report

    def test_the_wide_threshold_is_quoted_from_config(self):
        from config import MOAT

        report = render_matrix({"A": _row()}, {"A": _row()})
        assert str(MOAT.wide_threshold) in report

    def test_a_flipped_signal_is_not_presented_as_the_llm_changing_its_mind(self):
        """With no decision cache, both legs decide rule-based.

        A signal that moves did so because the moat bonus pushed
        ``adjusted_score`` across a threshold. Saying otherwise would credit the
        LLM with an opinion it was never asked for.
        """
        off = {"A": _row(action="HOLD")}
        on = {"A": _row(action="BUY", adjusted_score=80.0)}

        report = render_matrix(off, on)
        assert "HOLD → BUY" in report
        assert "no de que el LLM haya opinado distinto" in report

    def test_an_unmoved_universe_reports_zero_rather_than_an_empty_table(self):
        report = render_matrix({"A": _row()}, {"A": _row()})
        assert "**0**" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
