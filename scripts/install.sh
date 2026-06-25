#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPTS_DIR")"
VENV="$ROOT/.venv"

NO_SHORTCUT=0
SHORTCUT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-shortcut) NO_SHORTCUT=1; shift ;;
        --shortcut-dir) SHORTCUT_DIR="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ ! -d "$VENV" ]]; then
    python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip
if [[ "$(uname)" == "Darwin" ]]; then
    "$VENV/bin/python" -m pip install -e "$ROOT[macos]"
else
    "$VENV/bin/python" -m pip install -e "$ROOT"
fi

if [[ "$NO_SHORTCUT" -eq 0 ]]; then
    if [[ -n "$SHORTCUT_DIR" ]]; then
        bash "$SCRIPTS_DIR/create-desktop-shortcut.sh" --shortcut-dir "$SHORTCUT_DIR"
    else
        bash "$SCRIPTS_DIR/create-desktop-shortcut.sh"
    fi
fi

echo ""
echo "Installed Vibemod."
echo "Run: ./scripts/run-overlay.sh"
