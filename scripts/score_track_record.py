#!/usr/bin/env python3
"""
Score due recommendations for the track record (Gran Salto, Fase 1).

Idempotent — safe to run on a daily cron. For each recommendation whose horizon
has elapsed and lacks an outcome, it computes the return vs the benchmark and a
directional hit, then persists the outcome.

Run from project root:
    ./venv/bin/python3 scripts/score_track_record.py
"""

import sys
from pathlib import Path

_sys_root = Path(__file__).resolve().parent.parent
if str(_sys_root) not in sys.path:
    sys.path.insert(0, str(_sys_root))
from bootstrap import ensure_project_root

ensure_project_root()

from loguru import logger

from analysis.track_record_scorer import score_due_recommendations


def main() -> int:
    logger.info("track_record: starting scoring run")
    result = score_due_recommendations()
    logger.info(f"track_record: done — scored={result['scored']} skipped={result['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
