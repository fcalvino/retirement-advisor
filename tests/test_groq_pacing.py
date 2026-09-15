"""Oráculo: el pacer Groq no dispara más tokens que el presupuesto TPM."""

from __future__ import annotations

from unittest.mock import patch

from analysis.groq_pacing import GroqTpmPacer


def test_under_budget_does_not_sleep():
    pacer = GroqTpmPacer(budget=8000)
    with patch("analysis.groq_pacing.time.sleep") as slept:
        pacer.wait_for(4000)
        pacer.wait_for(4000)
    slept.assert_not_called()


def test_over_budget_sleeps_until_window():
    clock = [1000.0]

    def mono():
        return clock[0]

    def sleep(seconds):
        clock[0] += seconds

    pacer = GroqTpmPacer(budget=8000)
    with (
        patch("analysis.groq_pacing.time.monotonic", side_effect=mono),
        patch("analysis.groq_pacing.time.sleep", side_effect=sleep) as slept,
    ):
        pacer.wait_for(4000)
        pacer.wait_for(4000)
        pacer.wait_for(4000)
    assert slept.called
    assert slept.call_args.args[0] > 0


def test_zero_tokens_or_budget_is_noop():
    pacer = GroqTpmPacer(budget=0)
    with patch("analysis.groq_pacing.time.sleep") as slept:
        pacer.wait_for(4000)
        GroqTpmPacer(8000).wait_for(0)
    slept.assert_not_called()
