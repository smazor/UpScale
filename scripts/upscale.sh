#!/usr/bin/env bash
# Run the upscaler with the project's virtualenv, from any directory.
#
#   scripts/upscale.sh Liane.png --height-cm 80
#
# All arguments are passed straight through to src/upscale.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
    echo "Virtualenv not found at $ROOT/.venv" >&2
    echo "Create it with:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

exec "$PY" "$ROOT/src/upscale.py" "$@"
