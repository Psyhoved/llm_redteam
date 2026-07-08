#!/usr/bin/env bash
# Invoked by run_hf_import_in_screen.sh inside a detached screen.
# Args: <log_file> <job_id>
set -uo pipefail

LOG_FILE="$1"
JOB_ID="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR" || exit 1

PYTHON="${SCRIPT_DIR}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi

{
  echo "===== hf_import_screen_runner ====="
  echo "started_at_utc=$(date -Is -u)"
  echo "job_id=$JOB_ID"
  echo "log=$LOG_FILE"
  echo "==================================="
  echo
} | tee -a "$LOG_FILE"

set +e
"$PYTHON" -m admin.hf_import_worker --job-id "$JOB_ID" 2>&1 | tee -a "$LOG_FILE"
ec=${PIPESTATUS[0]}
echo "HF_IMPORT_EXIT=$ec" | tee -a "$LOG_FILE"
exit "$ec"
