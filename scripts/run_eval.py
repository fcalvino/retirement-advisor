#!/usr/bin/env python3
"""
Run the AI eval harness (Gran Salto — Fase 2A).

By default runs in deterministic replay mode (no API key, no cost), which is what
CI uses. Pass --live to evaluate the real AI provider configured in the
environment.

Usage:
    ./venv/bin/python3 scripts/run_eval.py            # replay (default)
    ./venv/bin/python3 scripts/run_eval.py --live     # live AI provider
"""

import sys
from pathlib import Path

_sys_root = Path(__file__).resolve().parent.parent
if str(_sys_root) not in sys.path:
    sys.path.insert(0, str(_sys_root))
from bootstrap import ensure_project_root

ensure_project_root()

from loguru import logger

from analysis.eval_harness import LiveProvider, ReplayProvider, run_eval


def _build_provider(live: bool):
    if not live:
        return ReplayProvider()
    from config import AI_CONFIG

    if not getattr(AI_CONFIG, "enabled", False):
        logger.warning("run_eval --live: AI no está habilitada en config; usando replay.")
        return ReplayProvider()
    return LiveProvider(AI_CONFIG)


def main(argv: list[str]) -> int:
    live = "--live" in argv
    provider = _build_provider(live)
    report = run_eval(provider)

    print(f"\nEval [{provider.name}] — {report.n_passed}/{report.n_cases} casos OK "
          f"({report.suite_pass_rate * 100:.0f}%)  -> {'GREEN' if report.is_green else 'RED'}\n")
    for r in report.results:
        mark = "✅" if r.passed else "❌"
        print(f"{mark} {r.case_id:28s} action={r.action:11s} score={r.score * 100:3.0f}%")
        for f in r.failures:
            print(f"      ↳ {f.name}: {f.detail}")

    print("\nPass rate por check:")
    for name, rate in sorted(report.check_pass_rates().items()):
        print(f"  {name:24s} {rate * 100:3.0f}%")

    return 0 if report.is_green else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
