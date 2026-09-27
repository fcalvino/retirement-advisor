#!/usr/bin/env python3
"""
Run the AI eval harness (Gran Salto — Fase 2A; committee and AI-moat banks, LLM-4).

By default runs every bank in deterministic replay mode (no API key, no cost),
which is what CI uses. Pass --live to evaluate the real AI provider configured
in the environment; each live bank's report is saved as JSON under
``EVAL.runs_path()`` (``data/eval_runs/``, outside git), stamped with the
``COMMITTEE.prompt_version`` and the commit it ran on.

Usage:
    ./venv/bin/python3 scripts/run_eval.py                     # all banks, replay
    ./venv/bin/python3 scripts/run_eval.py --live              # all banks, live + saved
    ./venv/bin/python3 scripts/run_eval.py --live --bank moat  # one bank

Cost of a live run: one call per decision case, one per moat case, and 4–6 per
committee case (one per convened voice).
"""

import argparse
import sys

import _bootstrap  # noqa: F401
from loguru import logger

from analysis.eval_harness import (
    CommitteeProvider,
    LiveProvider,
    MoatLiveProvider,
    MoatReplayProvider,
    ReplayProvider,
    run_committee_eval,
    run_eval,
    run_moat_eval,
    save_report,
)

BANKS = ("decision", "committee", "moat")


def _live_config():
    from config import AI_CONFIG

    if not getattr(AI_CONFIG, "enabled", False):
        logger.warning("run_eval --live: AI no está habilitada en config; usando replay.")
        return None
    return AI_CONFIG


def _run_bank(bank: str, ai_config):
    if bank == "decision":
        provider = LiveProvider(ai_config) if ai_config else ReplayProvider()
        return provider.name, run_eval(provider)
    if bank == "committee":
        provider = CommitteeProvider(ai_config=ai_config)
        return provider.name, run_committee_eval(provider)
    provider = MoatLiveProvider(ai_config) if ai_config else MoatReplayProvider()
    return provider.name, run_moat_eval(provider)


def _print(bank: str, name: str, report) -> None:
    print(f"\nEval {bank} [{name}] — {report.n_passed}/{report.n_cases} casos OK "
          f"({report.suite_pass_rate * 100:.0f}%)  -> {'GREEN' if report.is_green else 'RED'}\n")
    for r in report.results:
        mark = "✅" if r.passed else "❌"
        print(f"{mark} {r.case_id:32s} action={r.action:11s} score={r.score * 100:3.0f}%")
        for f in r.failures:
            print(f"      ↳ {f.name}: {f.detail}")

    print("\nPass rate por check:")
    for check, rate in sorted(report.check_pass_rates().items()):
        print(f"  {check:26s} {rate * 100:3.0f}%")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--live", action="store_true", help="call the configured AI provider")
    parser.add_argument("--bank", choices=(*BANKS, "all"), default="all")
    args = parser.parse_args(argv)

    ai_config = _live_config() if args.live else None
    banks = BANKS if args.bank == "all" else (args.bank,)

    green = True
    for bank in banks:
        name, report = _run_bank(bank, ai_config)
        _print(bank, name, report)
        if ai_config is not None:
            path = save_report(report, bank=bank, provider_name=name)
            print(f"\nReporte guardado: {path}")
        green = green and report.is_green

    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
