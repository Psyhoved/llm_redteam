#!/usr/bin/env bash
# Invoked by run_phase1_in_screen.sh inside a detached screen.
# Args: <log_file> <keep_shell_0_or_1> <session_name_for_env> [orchestrator_args...]
set -uo pipefail

LOG_FILE="$1"
KEEP_FLAG="$2"
SESSION_NAME="$3"
shift 3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR" || exit 1

export PHASE1_SCREEN_SESSION="$SESSION_NAME"

{
  echo "===== phase1_screen_runner ====="
  echo "started_at_utc=$(date -Is -u)"
  echo "session=$SESSION_NAME"
  echo "log=$LOG_FILE"
  echo "orchestrator_cmd=./run_phase1_all_proxy.sh $*"
  echo "================================"
  echo
} | tee -a "$LOG_FILE"

set +e
./run_phase1_all_proxy.sh "$@" 2>&1 | tee -a "$LOG_FILE"
ec=${PIPESTATUS[0]}
echo "ORCHESTRATOR_EXIT=$ec" | tee -a "$LOG_FILE"

if [[ "$KEEP_FLAG" == "1" ]]; then
  echo "[keep-shell] Orchestrator finished; dropping into interactive shell (detach: Ctrl-A D)" | tee -a "$LOG_FILE"
  exec bash -il
fi

exit "$ec"
