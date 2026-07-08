#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/.venv/bin/python}"
HOST="${PHASE1_INSPECT_VIEW_HOST:-0.0.0.0}"
PORT="${PHASE1_INSPECT_VIEW_PORT:-7575}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: Python not found at $PYTHON_BIN" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m inspect_ai view start \
  --host "$HOST" \
  --port "$PORT" \
  --log-dir "${PHASE1_INSPECT_LOG_DIR:-logs}" \
  --recursive
