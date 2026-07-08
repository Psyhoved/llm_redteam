#!/usr/bin/env bash
# Idempotent repair: start supervisord and restart failed Phase 1 services.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE1_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF="$PHASE1_DIR/deploy/supervisor/phase1_services.conf"
LOG_DIR="$PHASE1_DIR/logs/supervisor"
SUPERVISOR_BIN="$PHASE1_DIR/.venv/bin/supervisord"
SUPERVISORCTL_BIN="$PHASE1_DIR/.venv/bin/supervisorctl"
ENSURE_LOG="$LOG_DIR/ensure.log"

mkdir -p "$LOG_DIR"

log() {
  echo "$(date -Is) [ensure] $*" | tee -a "$ENSURE_LOG"
}

if [[ ! -x "$SUPERVISOR_BIN" ]]; then
  log "ERROR: supervisord missing at $SUPERVISOR_BIN"
  exit 1
fi

supervisor_up() {
  "$SUPERVISORCTL_BIN" -c "$CONF" status >/dev/null 2>&1
}

start_supervisord() {
  log "starting supervisord"
  "$SUPERVISOR_BIN" -c "$CONF"
  sleep 3
}

restart_failed_programs() {
  local status_line name state
  while IFS= read -r status_line; do
    [[ -z "$status_line" ]] && continue
    name="${status_line%% *}"
    state="$(echo "$status_line" | awk '{print $2}')"
    case "$state" in
      FATAL|BACKOFF|EXITED|STOPPED|UNKNOWN)
        log "restarting $name (state=$state)"
        "$SUPERVISORCTL_BIN" -c "$CONF" start "$name" || \
          "$SUPERVISORCTL_BIN" -c "$CONF" restart "$name" || true
        ;;
    esac
  done < <("$SUPERVISORCTL_BIN" -c "$CONF" status 2>/dev/null | grep -E '^phase1_services:' || true)
}

if ! supervisor_up; then
  start_supervisord
fi

if supervisor_up; then
  restart_failed_programs
else
  log "ERROR: supervisord still unreachable after start attempt"
  exit 1
fi

# Only log health; restart is handled by supervisor autorestart + restart_failed_programs above.
bash "$SCRIPT_DIR/services_health.sh" >>"$ENSURE_LOG" 2>&1 || \
  log "WARN: health check reported failures (no mass-restart; check logs)"

exit 0
