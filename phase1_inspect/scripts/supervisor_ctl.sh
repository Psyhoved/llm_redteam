#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE1_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF="$PHASE1_DIR/deploy/supervisor/phase1_services.conf"
SUPERVISORCTL_BIN="$PHASE1_DIR/.venv/bin/supervisorctl"

if [[ ! -x "$SUPERVISORCTL_BIN" ]]; then
  echo "Error: supervisorctl not found. Run: pip install supervisor" >&2
  exit 1
fi

cmd="${1:-status}"
shift || true

case "$cmd" in
  status|start|stop|restart|shutdown|avail|help)
    exec "$SUPERVISORCTL_BIN" -c "$CONF" "$cmd" "$@"
    ;;
  tail)
    name="${1:-}"
    if [[ -z "$name" ]]; then
      echo "usage: $0 tail <phase1_admin|inspect_view|lms_guard>" >&2
      exit 1
    fi
    exec tail -f "$PHASE1_DIR/logs/supervisor/${name}.log"
    ;;
  *)
    echo "usage: $0 {status|start|stop|restart|shutdown|tail <name>}" >&2
    exit 1
    ;;
esac
