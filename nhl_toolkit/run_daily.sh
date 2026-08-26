#!/usr/bin/env bash
# Wrapper for cron: cron jobs run with a minimal environment (no shell rc
# files, no activated venv), so this resolves everything by absolute path
# instead of relying on inherited PATH/cwd.
#
# Install with `crontab -e` and a line like:
#   0 9 * * * /Users/babruzi/Documents/VSCODE/GITHUB/hockey-web/nhl_toolkit/run_daily.sh
set -euo pipefail

REPO_ROOT="/Users/babruzi/Documents/VSCODE/GITHUB/hockey-web"
TOOLKIT_DIR="$REPO_ROOT/nhl_toolkit"
LOG_FILE="$TOOLKIT_DIR/logs/run_daily_$(date +%Y-%m-%d).log"

cd "$TOOLKIT_DIR"

if [ -f "$REPO_ROOT/.env" ]; then
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
fi

"$REPO_ROOT/.venv/bin/python" run_daily.py >> "$LOG_FILE" 2>&1
