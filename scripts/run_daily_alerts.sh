#!/usr/bin/env bash
# Run a single alert check and exit — designed for cron execution.
#
# Usage:
#   bash scripts/run_daily_alerts.sh            # with INFO logs
#   bash scripts/run_daily_alerts.sh --quiet    # WARNING+ only (recommended for cron)
#
# Crontab example (every day at 9:00 AM):
#   0 9 * * * /path/to/retirement_advisor/scripts/run_daily_alerts.sh --quiet >> /path/to/retirement_advisor/logs/daily_alerts.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

mkdir -p logs

source venv/bin/activate

exec python scripts/run_scheduler.py --once "$@"
