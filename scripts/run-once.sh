#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPTS_DIR")"
VENV_PYTHON="$ROOT/.venv/bin/python"

if [[ ! -f "$VENV_PYTHON" ]]; then
    echo "Virtual environment not found. Installing first..."
    bash "$SCRIPTS_DIR/install.sh"
fi

exec "$VENV_PYTHON" -m neurogate_usage_overlay --once
