#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPTS_DIR")"
VENV="$ROOT/.venv"
VENV_PYTHON="$VENV/bin/python"
STATE_DIR="$HOME/.neurogate-usage-overlay"
PROFILE_PATH="$STATE_DIR/browser-profile"
PID_FILE="$STATE_DIR/overlay.pid"
LAUNCH_ONLY="${VIBEMODE_LAUNCH_ONLY:-0}"
MAX_LOG_BYTES=$((256 * 1024))
TRIM_LOG_BYTES=$((128 * 1024))

prune_log_file() {
    local path="$1"
    [[ -f "$path" ]] || return 0
    local size
    size="$(wc -c < "$path" 2>/dev/null || echo 0)"
    [[ "$size" =~ ^[0-9]+$ ]] || return 0
    if (( size > MAX_LOG_BYTES )); then
        local tmp="${path}.tmp"
        tail -c "$TRIM_LOG_BYTES" "$path" > "$tmp" 2>/dev/null && mv "$tmp" "$path"
        rm -f "$tmp"
    fi
}

mkdir -p "$STATE_DIR"
prune_log_file "$STATE_DIR/restart.log"
prune_log_file "$STATE_DIR/launcher.log"

# Install if venv is missing.
if [[ ! -f "$VENV_PYTHON" ]]; then
    echo "Virtual environment not found. Installing first..."
    bash "$SCRIPTS_DIR/install.sh"
fi

if [[ "$LAUNCH_ONLY" == "1" ]]; then
    if pgrep -f '[p]ython.*-m[[:space:]]+neurogate_usage_overlay' >/dev/null; then
        echo "Vibemode overlay is already running."
        exit 0
    fi
fi

# Stop a previously recorded overlay instance.
if [[ "$LAUNCH_ONLY" != "1" && -f "$PID_FILE" ]]; then
    RECORDED_PID="$(cat "$PID_FILE" 2>/dev/null | tr -d '[:space:]')"
    if [[ -n "$RECORDED_PID" ]] && kill -0 "$RECORDED_PID" 2>/dev/null; then
        CMDLINE="$(ps -p "$RECORDED_PID" -o args= 2>/dev/null || true)"
        if echo "$CMDLINE" | grep -qE '(^|[[:space:]])(-m[[:space:]]+neurogate_usage_overlay|neurogate-api|vibemode-overlay|neurogate-usage-overlay)([[:space:]]|$)'; then
            kill "$RECORDED_PID" 2>/dev/null || true
            sleep 0.5
        fi
    fi
    rm -f "$PID_FILE"
fi

# Kill any leftover overlay or Chrome processes using this profile.
# Exclude the current process and its parent (update-and-restart.sh) to avoid self-kill.
_self_pids="$$"
[[ -n "${PPID:-}" ]] && _self_pids="$$|$PPID"

if [[ "$LAUNCH_ONLY" != "1" ]]; then
    pgrep -f '[p]ython.*-m[[:space:]]+neurogate_usage_overlay' \
        | grep -Ev "^($_self_pids)$" \
        | while read -r pid; do kill "$pid" 2>/dev/null || true; done || true
fi

if [[ "$LAUNCH_ONLY" != "1" ]]; then
    pgrep -f "$PROFILE_PATH" \
        | grep -Ev "^($_self_pids)$" \
        | while read -r pid; do kill "$pid" 2>/dev/null || true; done || true
fi

unset _self_pids

exec "$VENV_PYTHON" -m neurogate_usage_overlay --interval 60
