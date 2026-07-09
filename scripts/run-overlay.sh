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

read_pid_file() {
    [[ -f "$PID_FILE" ]] || return 0
    cat "$PID_FILE" 2>/dev/null | tr -d '[:space:]' || true
}

is_current_overlay_pid() {
    local pid="$1"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1

    local cmdline
    cmdline="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    [[ -n "$cmdline" ]] || return 1
    [[ "$cmdline" == *"$VENV_PYTHON"* ]] || return 1
    [[ "$cmdline" =~ (^|[[:space:]])-m[[:space:]]+neurogate_usage_overlay([[:space:]]|$) ]]
}

current_overlay_pids() {
    pgrep -f '[p]ython.*-m[[:space:]]+neurogate_usage_overlay' 2>/dev/null \
        | while read -r pid; do
            if is_current_overlay_pid "$pid"; then
                echo "$pid"
            fi
        done
}

remove_stale_pid_file() {
    local recorded_pid
    recorded_pid="$(read_pid_file)"
    [[ -n "$recorded_pid" ]] || return 0
    if ! is_current_overlay_pid "$recorded_pid"; then
        rm -f "$PID_FILE"
    fi
}

stop_overlay_pids() {
    local pids="$1"
    local pid
    local self_pids="$$"
    [[ -n "${PPID:-}" ]] && self_pids="$$|$PPID"

    for pid in $pids; do
        [[ "$pid" =~ ^[0-9]+$ ]] || continue
        if [[ "$pid" =~ ^($self_pids)$ ]]; then
            continue
        fi
        kill "$pid" 2>/dev/null || true
    done
    sleep 0.5
}

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

remove_stale_pid_file

if [[ "$LAUNCH_ONLY" == "1" ]]; then
    EXISTING_PIDS="$(current_overlay_pids || true)"
    if [[ -n "$EXISTING_PIDS" ]]; then
        echo "Restarting Vibemode overlay..."
        stop_overlay_pids "$EXISTING_PIDS"
        rm -f "$PID_FILE"
    fi
fi

# Stop a previously recorded overlay instance.
if [[ "$LAUNCH_ONLY" != "1" && -f "$PID_FILE" ]]; then
    RECORDED_PID="$(read_pid_file)"
    if [[ -n "$RECORDED_PID" ]] && is_current_overlay_pid "$RECORDED_PID"; then
        stop_overlay_pids "$RECORDED_PID"
    fi
    rm -f "$PID_FILE"
fi

# Kill any leftover overlay or Chrome processes using this profile.
# Exclude the current process and its parent (update-and-restart.sh) to avoid self-kill.
_self_pids="$$"
[[ -n "${PPID:-}" ]] && _self_pids="$$|$PPID"

if [[ "$LAUNCH_ONLY" != "1" ]]; then
    EXISTING_PIDS="$(current_overlay_pids || true)"
    if [[ -n "$EXISTING_PIDS" ]]; then
        stop_overlay_pids "$EXISTING_PIDS"
    fi
fi

if [[ "$LAUNCH_ONLY" != "1" ]]; then
    pgrep -f "$PROFILE_PATH" \
        | grep -Ev "^($_self_pids)$" \
        | while read -r pid; do kill "$pid" 2>/dev/null || true; done || true
fi

unset _self_pids

exec "$VENV_PYTHON" -m neurogate_usage_overlay --interval 60
