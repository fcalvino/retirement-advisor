#!/usr/bin/env bash
# runsec.sh <section.mjs>  — run a navigation section, then dump NEW error lines
# from both the Streamlit console and the loguru file produced during the run.
set -uo pipefail
cd "$(dirname "$0")"
SEC="$1"
CONSOLE="../logs/streamlit_console.log"
LOGURU="../logs/retirement_advisor.log"

c0=$(wc -l < "$CONSOLE" 2>/dev/null || echo 0)
l0=$(wc -l < "$LOGURU" 2>/dev/null || echo 0)

QA_BASE=http://localhost:8502 node "$SEC"
rc=$?

echo ""
echo "======== NEW LOG LINES (errors/warnings) for $SEC ========"
echo "---- streamlit console (stderr: tracebacks) ----"
tail -n +$((c0+1)) "$CONSOLE" 2>/dev/null | grep -nE "Traceback|Error|Exception|raise |KeyError|ValueError|TypeError|AttributeError|Warning|WARNING" | grep -viE "watchdog|xcode-select|ScriptRunContext|missing ScriptRunContext|bare mode" | head -60
echo "---- loguru file (app ERROR/WARNING) ----"
tail -n +$((l0+1)) "$LOGURU" 2>/dev/null | grep -E "\| (ERROR|WARNING) \|" | head -60
echo "======== END LOG SCAN ($SEC) rc=$rc ========"
exit $rc
