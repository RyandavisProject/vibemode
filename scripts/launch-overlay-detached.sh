#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPTS_DIR")"
STATE_DIR="$HOME/.neurogate-usage-overlay"
LOG_PATH="$STATE_DIR/launcher.log"
SESSION_NAME="vibemode"

mkdir -p "$STATE_DIR"

start_in_screen() {
    screen -wipe >/dev/null 2>&1 || true
    screen -S "$SESSION_NAME" -X quit >/dev/null 2>&1 || true
    screen -dmS "$SESSION_NAME" bash -lc \
        'cd "$1" && export VIBEMODE_LAUNCH_ONLY=1 && exec bash scripts/run-overlay.sh >> "$HOME/.neurogate-usage-overlay/launcher.log" 2>&1' \
        _ "$ROOT"
}

start_with_nohup() {
    (
        cd "$ROOT"
        export VIBEMODE_LAUNCH_ONLY=1
        nohup bash scripts/run-overlay.sh >> "$LOG_PATH" 2>&1 &
    )
}

if command -v screen >/dev/null 2>&1; then
    start_in_screen
else
    start_with_nohup
fi

echo "Vibemode overlay is starting in the menu bar."
