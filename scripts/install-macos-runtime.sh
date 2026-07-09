#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(dirname "$SCRIPTS_DIR")"
RUNTIME_ROOT="${VIBEMODE_RUNTIME_ROOT:-$HOME/.vibemode/runtime}"
SOURCE_PYTHON="$SOURCE_ROOT/.venv/bin/python"
RUNTIME_PYTHON="$RUNTIME_ROOT/.venv/bin/python"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "macOS runtime installer is only supported on macOS." >&2
    exit 1
fi

SOURCE_REAL="$(cd "$SOURCE_ROOT" && pwd)"
mkdir -p "$(dirname "$RUNTIME_ROOT")"

if [[ -d "$RUNTIME_ROOT" ]]; then
    RUNTIME_REAL="$(cd "$RUNTIME_ROOT" && pwd)"
    if [[ "$SOURCE_REAL" == "$RUNTIME_REAL" ]]; then
        echo "Source and runtime are the same directory: $RUNTIME_ROOT" >&2
        exit 1
    fi
fi

mkdir -p "$RUNTIME_ROOT"

if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
        --exclude ".git/" \
        --exclude ".venv/" \
        --exclude "__pycache__/" \
        --exclude ".pytest_cache/" \
        --exclude "*.pyc" \
        "$SOURCE_ROOT/" "$RUNTIME_ROOT/"
else
    find "$RUNTIME_ROOT" -mindepth 1 -maxdepth 1 ! -name ".venv" -exec rm -rf {} +
    cp -R "$SOURCE_ROOT"/. "$RUNTIME_ROOT"/
    rm -rf "$RUNTIME_ROOT/.git" "$RUNTIME_ROOT/.pytest_cache"
    find "$RUNTIME_ROOT" -name "__pycache__" -type d -prune -exec rm -rf {} +
    find "$RUNTIME_ROOT" -name "*.pyc" -type f -delete
fi

chmod +x "$RUNTIME_ROOT/scripts/"*.sh

venv_needs_rebuild=0
if [[ ! -x "$RUNTIME_PYTHON" ]]; then
    venv_needs_rebuild=1
elif ! "$RUNTIME_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    venv_needs_rebuild=1
fi

if [[ "$venv_needs_rebuild" -eq 1 ]]; then
    rm -rf "$RUNTIME_ROOT/.venv"
    if [[ -x "$SOURCE_PYTHON" ]]; then
        "$SOURCE_PYTHON" -m venv "$RUNTIME_ROOT/.venv"
    else
        python3 -m venv "$RUNTIME_ROOT/.venv"
    fi
fi

"$RUNTIME_PYTHON" -m pip install --upgrade pip
"$RUNTIME_PYTHON" -m pip install -e "$RUNTIME_ROOT[macos]"
bash "$RUNTIME_ROOT/scripts/create-desktop-shortcut.sh" --project-root "$RUNTIME_ROOT"
bash "$RUNTIME_ROOT/scripts/create-desktop-shortcut.sh" --shortcut-dir "$HOME/Applications" --project-root "$RUNTIME_ROOT"

echo "Vibemode runtime installed: $RUNTIME_ROOT"
echo "Desktop app launcher refreshed: $HOME/Desktop/Vibemode.app"
