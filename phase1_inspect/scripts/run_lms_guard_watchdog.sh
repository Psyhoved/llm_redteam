#!/usr/bin/env bash
# Keep LM Studio API server and qwen3guard-gen-8b loaded (user-level, no systemd).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/service_common.sh"

LMS_BIN="${LMS_BIN:-$(command -v lms || true)}"
LMS_PORT="${LMS_PORT:-1234}"
LMS_BIND="${LMS_BIND:-0.0.0.0}"
LMS_GUARD_MODEL="${LMS_GUARD_MODEL:-qwen3guard-gen-8b}"
LMS_CHECK_INTERVAL="${LMS_CHECK_INTERVAL:-30}"
LMS_LOAD_PARALLEL="${LMS_LOAD_PARALLEL:-4}"
LMS_CONTEXT_LENGTH="${LMS_CONTEXT_LENGTH:-4096}"

log() {
  echo "$(date -Is) [lms-guard] $*"
}

if [[ -z "$LMS_BIN" || ! -x "$LMS_BIN" ]]; then
  log "ERROR: lms not found; install LM Studio CLI (~/.lmstudio/bin/lms)"
  exit 1
fi

server_running() {
  if "$LMS_BIN" server status 2>/dev/null | grep -qi 'server is running'; then
    return 0
  fi
  curl -sf "http://127.0.0.1:${LMS_PORT}/v1/models" >/dev/null 2>&1
}

model_loaded() {
  "$LMS_BIN" ps 2>/dev/null | grep -Fq "$LMS_GUARD_MODEL"
}

ensure_server() {
  if server_running; then
    return 0
  fi
  log "starting lms server on ${LMS_BIND}:${LMS_PORT}"
  if ! "$LMS_BIN" server start -p "$LMS_PORT" --bind "$LMS_BIND"; then
    log "WARN: lms server start failed"
    return 1
  fi
  sleep 2
  server_running
}

ensure_model() {
  if model_loaded; then
    return 0
  fi
  log "loading model ${LMS_GUARD_MODEL}"
  if ! "$LMS_BIN" load "$LMS_GUARD_MODEL" -y \
    --parallel "$LMS_LOAD_PARALLEL" \
    -c "$LMS_CONTEXT_LENGTH"; then
    log "WARN: model load failed"
    return 1
  fi
  model_loaded
}

trap 'log "received stop signal"; exit 0' TERM INT

log "watchdog started (model=${LMS_GUARD_MODEL}, port=${LMS_PORT}, interval=${LMS_CHECK_INTERVAL}s)"

while true; do
  ensure_server || true
  if server_running; then
    ensure_model || true
  fi
  sleep "$LMS_CHECK_INTERVAL"
done
