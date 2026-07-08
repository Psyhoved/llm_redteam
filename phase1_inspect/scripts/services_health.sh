#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE1_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/service_common.sh"

ok=0
fail=0

check_http() {
  local name="$1"
  local url="$2"
  if curl -sf --max-time 3 "$url" >/dev/null; then
    echo "OK   $name  $url"
    ok=$((ok + 1))
  else
    echo "FAIL $name  $url"
    fail=$((fail + 1))
  fi
}

check_port() {
  local name="$1"
  local host="$2"
  local port="$3"
  if python3 - "$host" "$port" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket()
s.settimeout(2)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
  then
    echo "OK   $name  ${host}:${port}"
    ok=$((ok + 1))
  else
    echo "FAIL $name  ${host}:${port}"
    fail=$((fail + 1))
  fi
}

echo "=== Phase 1 services health ==="

if [[ -x "$PHASE1_DIR/.venv/bin/supervisorctl" ]]; then
  "$PHASE1_DIR/.venv/bin/supervisorctl" -c "$PHASE1_DIR/deploy/supervisor/phase1_services.conf" status 2>/dev/null || true
  echo
fi

check_port "phase1_admin" "127.0.0.1" "${PHASE1_ADMIN_PORT:-8080}"
check_http "inspect_view" "http://127.0.0.1:${PHASE1_INSPECT_VIEW_PORT:-7575}/api/log-files"
check_http "lms_api" "http://127.0.0.1:${LMS_PORT:-1234}/v1/models"

if command -v lms >/dev/null 2>&1; then
  if lms ps 2>/dev/null | grep -Fq "${LMS_GUARD_MODEL:-qwen3guard-gen-8b}"; then
    echo "OK   lms_model  ${LMS_GUARD_MODEL:-qwen3guard-gen-8b} loaded"
    ok=$((ok + 1))
  else
    echo "FAIL lms_model  ${LMS_GUARD_MODEL:-qwen3guard-gen-8b} not loaded"
    fail=$((fail + 1))
  fi
else
  echo "SKIP lms_model  lms CLI not in PATH"
fi

echo
echo "Summary: ${ok} ok, ${fail} failed"
exit "$([[ $fail -eq 0 ]] && echo 0 || echo 1)"
