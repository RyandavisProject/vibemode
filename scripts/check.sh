#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPTS_DIR")"

if [[ -f "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON="python3"
fi

cd "$ROOT"
"$PYTHON" -m compileall src tests
PYTHONPATH="$ROOT/src" "$PYTHON" -m unittest discover -s tests -v

echo ""
echo "All checks passed."
