#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
HOST="${PHASE1_ADMIN_HOST:-0.0.0.0}"
PORT="${PHASE1_ADMIN_PORT:-8080}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: Python not found at $PYTHON_BIN" >&2
  echo "Create venv: uv venv && uv pip install -r requirements.txt" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m uvicorn admin.app:app --host "$HOST" --port "$PORT" --app-dir "$SCRIPT_DIR"
