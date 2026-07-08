#!/usr/bin/env bash
# Optional one-time migration from legacy screen sessions to supervisor.
# By default does NOT kill anything — use --replace-screens to stop old admin/inspect screens.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE1_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

REPLACE_SCREENS=0
for arg in "$@"; do
  case "$arg" in
    --replace-screens) REPLACE_SCREENS=1 ;;
    -h|--help)
      echo "Usage: $0 [--replace-screens]"
      echo "  --replace-screens  stop legacy phase1_admin / inspect_view / inspect_ai screens"
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

stop_screen_if_exists() {
  local name="$1"
  if screen -ls 2>/dev/null | grep -q "[0-9]*\.${name}[[:space:]]"; then
    echo "Stopping screen session: $name"
    screen -S "$name" -X quit || true
    sleep 1
  fi
}

echo "=== Phase 1 supervisor setup ==="

if [[ "$REPLACE_SCREENS" -eq 1 ]]; then
  echo "Stopping legacy screen sessions (admin/inspect only)..."
  for session in phase1_admin inspect_view inspect_ai; do
    stop_screen_if_exists "$session"
  done
else
  echo "Keeping existing screen sessions (pass --replace-screens to stop legacy admin/inspect screens)."
fi

echo "Ensuring supervisord and services..."
bash "$SCRIPT_DIR/supervisor_ensure.sh"

echo
bash "$SCRIPT_DIR/services_health.sh"
