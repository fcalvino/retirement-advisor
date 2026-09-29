#!/usr/bin/env python3
"""
Measure how much the committee verdict changes between runs on the same input (#151).

Six frozen panels (``analysis.eval_cases.stability_cases``: four equities, two
cryptos, the same dated macro and headlines every run) are run N times with no
cache (``EVAL.stability_runs``, 5). Per case: how often the action changes —the
panel's vote and the post-overlay action the user sees—, the spread of the lean
and which voices change their stance. Incomplete panels are kept but left out of
the metrics (see ``analysis/committee_stability.py``).

Without --live it only prints the plan and makes no call. With --live each
record is appended to a JSONL as it arrives, so a run cut by a rate limit keeps
what it paid for and resumes with --resume; the final JSON goes next to it. From
a Conductor worktree, point the runs at the real clone:

    export RETIREMENT_ADVISOR_EVAL_RUNS_DIR=~/retirement_advisor/data/eval_runs
    ./venv/bin/python3 scripts/committee_stability.py            # plan, no calls
    ./venv/bin/python3 scripts/committee_stability.py --live     # paid run
    ./venv/bin/python3 scripts/committee_stability.py --live --resume <file>.jsonl

A live run refuses a dirty tree: a measurement on uncommitted code is not
evidence about any commit (``--allow-dirty`` to override).
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import _bootstrap  # noqa: F401
from loguru import logger

from analysis.committee import _pays_dividend
from analysis.committee_stability import (
    record_from_dict,
    run_stability,
    summarize_stability,
)
from analysis.eval_cases import stability_cases
from analysis.eval_harness import CommitteeProvider, _git_sha
from analysis.llm_usage import USAGE, summarize
from config import COMMITTEE, EVAL
from data.clock import utc_now
from scripts.run_eval import _live_config

_TS = "%Y-%m-%dT%H:%M:%SZ"


def _provider(ai_config) -> CommitteeProvider:
    return CommitteeProvider(ai_config=ai_config)


def _voices(case) -> int:
    """Calls one panel makes: Fundamental, Devil, PM, Coach + Macro and Dividend when convened."""
    return 4 + bool(case.macro_context) + _pays_dividend(case.fund)


def _select(cases, wanted):
    if not wanted:
        return cases
    unknown = set(wanted) - {c.case_id for c in cases}
    if unknown:
        raise SystemExit(f"casos desconocidos: {sorted(unknown)}")
    return [c for c in cases if c.case_id in wanted]


def _print_plan(cases, runs: int, out_dir: Path) -> None:
    per_run = sum(_voices(c) for c in cases)
    print(f"Estabilidad del comité — {len(cases)} casos × {runs} corridas, sin caché")
    for c in cases:
        print(f"  {c.case_id:18s} {c.fund.symbol:9s} {_voices(c)} voces")
    print(f"Llamadas estimadas: {per_run * runs} ({per_run} por corrida)")
    print(f"Destino: {out_dir}")


def _print_summary(summary: dict) -> None:
    for name, prov in summary["by_provider"].items():
        print(f"\n[{name}] casos con cambio de acción: {prov['cases_with_action_change']}/"
              f"{prov['n_cases']} (voto) · {prov['cases_with_final_action_change']}/"
              f"{prov['n_cases']} (final) · completos {prov['n_complete']}/{prov['n_records']}")
        for cid, c in prov["cases"].items():
            a, f, lean = c["action"], c["final_action"], c["lean"]
            rate = "—" if a["change_rate"] is None else f"{a['change_rate']:.0%}"
            frate = "—" if f["change_rate"] is None else f"{f['change_rate']:.0%}"
            sd = "—" if lean["stdev"] is None else f"{lean['stdev']:.3f}"
            print(f"  {cid:18s} voto {a['counts']} cambio {rate} · final {f['counts']} "
                  f"cambio {frate} · lean σ {sd} · incompletos {c['n_incomplete']}")
            moved = [f"{r} ({v['agreement']:.0%})" for r, v in c["roles"].items() if v["distinct"] > 1]
            if moved:
                print(f"      voces que cambian: {', '.join(moved)}")


def _read_jsonl(path: Path):
    header, records, usage = None, [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        kind = row.pop("kind", "record")
        if kind == "header":
            header = row
        elif kind == "usage":
            usage.append(row)
        else:
            records.append(record_from_dict(row))
    if header is None:
        raise SystemExit(f"{path} no tiene encabezado: no es una corrida de estabilidad")
    return header, records, usage


def _append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--live", action="store_true", help="call the configured AI provider")
    parser.add_argument("--runs", type=int, default=EVAL.stability_runs)
    parser.add_argument("--cases", nargs="*", default=None, help="case ids (default: all six)")
    parser.add_argument("--resume", type=Path, default=None, help="JSONL of a cut run")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    if args.resume is not None:
        header, previous, usage_sessions = _read_jsonl(args.resume)
        now = datetime.strptime(header["frozen_at"], _TS)
        runs, wanted = header["runs"], header["cases"]
        jsonl = args.resume
    else:
        header, previous, usage_sessions = None, [], []
        now = utc_now()
        runs, wanted = args.runs, args.cases
        jsonl = None
    cases = _select(stability_cases(now=now), wanted)
    out_dir = args.out_dir or (jsonl.parent if jsonl else EVAL.runs_path())

    if not args.live:
        _print_plan(cases, runs, out_dir)
        print("\nCorrida en seco: ninguna llamada. Pasá --live para correrla.")
        return 0

    ai_config = _live_config()
    if ai_config is None:
        raise SystemExit("--live necesita la IA habilitada (AI_ENABLED) y una key.")
    sha = _git_sha()
    if sha.endswith("-dirty") and not args.allow_dirty:
        raise SystemExit(f"árbol sucio ({sha}): commiteá antes de medir, o --allow-dirty.")
    provider = _provider(ai_config)
    if header is not None:
        for key, value in (("git_sha", sha), ("provider", provider.name)):
            if header[key] != value:
                raise SystemExit(f"--resume: {key} {value} ≠ {header[key]} de la corrida original")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", provider.name)
        jsonl = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}_stability_{slug}.jsonl"
        header = {"frozen_at": now.strftime(_TS), "runs": runs,
                  "cases": [c.case_id for c in cases], "git_sha": sha,
                  "prompt_version": COMMITTEE.prompt_version, "provider": provider.name}
        _append(jsonl, {"kind": "header", **header})

    _print_plan(cases, runs, out_dir)
    print(f"Registro incremental: {jsonl}")
    done = {(r.case_id, r.run) for r in previous}
    with USAGE.capture() as calls:
        try:
            new = run_stability(provider, cases, runs, done=done,
                                on_record=lambda r: _append(jsonl, {"kind": "record", **r.to_dict()}))
        finally:
            # Written even when the run is cut: what was paid is part of the evidence.
            session = summarize(calls)
            if calls:
                _append(jsonl, {"kind": "usage", **session})
                usage_sessions.append(session)

    records = previous + new
    summary = summarize_stability(records)
    _print_summary(summary)
    costs = [u["cost_usd"] for u in usage_sessions]
    report = {
        "bank": "stability",
        "provider": provider.name,
        "run_at": utc_now().strftime(_TS),
        "frozen_at": header["frozen_at"],
        "git_sha": sha,
        "prompt_version": COMMITTEE.prompt_version,
        "eval_config": EVAL.as_dict(),
        "runs": runs,
        "cases": header["cases"],
        "n_records": len(records),
        "summary": summary,
        "usage": {
            "sessions": usage_sessions,
            "n_calls": sum(u["n_calls"] for u in usage_sessions),
            "cost_usd": round(sum(costs), 6) if all(c is not None for c in costs) else None,
        },
        "records": [r.to_dict() for r in records],
    }
    path = jsonl.with_suffix(".json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nUso: {report['usage']['n_calls']} llamadas, costo USD {report['usage']['cost_usd']}")
    print(f"Reporte guardado: {path}")
    logger.info(f"stability: report saved → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
