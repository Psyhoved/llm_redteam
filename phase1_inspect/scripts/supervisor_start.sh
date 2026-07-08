#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE1_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF="$PHASE1_DIR/deploy/supervisor/phase1_services.conf"
LOG_DIR="$PHASE1_DIR/logs/supervisor"
SUPERVISOR_BIN="$PHASE1_DIR/.venv/bin/supervisord"
SUPERVISORCTL_BIN="$PHASE1_DIR/.venv/bin/supervisorctl"

mkdir -p "$LOG_DIR"

if [[ ! -x "$SUPERVISOR_BIN" ]]; then
  echo "Error: supervisord not found at $SUPERVISOR_BIN" >&2
  echo "Install: cd $PHASE1_DIR && source .venv/bin/activate && pip install supervisor" >&2
  exit 1
fi

if "$SUPERVISORCTL_BIN" -c "$CONF" status >/dev/null 2>&1; then
  echo "supervisord already running"
  "$SUPERVISORCTL_BIN" -c "$CONF" status
  exit 0
fi

# Daemonize supervisord (do not exec from cron — parent would appear dead).
"$SUPERVISOR_BIN" -c "$CONF"
sleep 2
"$SUPERVISORCTL_BIN" -c "$CONF" status
