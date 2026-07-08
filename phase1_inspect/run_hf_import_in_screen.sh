#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/scripts/hf_import_screen_runner.sh"

usage() {
  cat <<'EOF' >&2
Usage: ./run_hf_import_in_screen.sh [options] [--] <job_id>

Options:
  -S NAME, --session NAME   screen session name (default: hf_import_<job_prefix>)
  -h, --help                this message

Log file:
  phase1_inspect/logs/hf_import_screen_<SESSION>_<YYYYMMDD_HHMMSS>.log
EOF
  exit "${1:-0}"
}

SESSION=""
JOB_ID=""

while (($#)); do
  case "$1" in
    -S | --session)
      SESSION="$2"
      shift 2
      ;;
    -h | --help)
      usage 0
      ;;
    --)
      shift
      JOB_ID="${1:-}"
      break
      ;;
    *)
      if [[ -z "$JOB_ID" ]]; then
        JOB_ID="$1"
        shift
      else
        echo "Error: unexpected argument: $1" >&2
        exit 1
      fi
      ;;
  esac
done

if [[ -z "$JOB_ID" ]]; then
  echo "Error: job_id is required" >&2
  usage 1
fi

if [[ -z "$SESSION" ]]; then
  SESSION="hf_import_${JOB_ID:0:8}"
fi

if [[ ! -x "$RUNNER" ]] && [[ -f "$RUNNER" ]]; then
  chmod +x "$RUNNER"
fi

if ! command -v screen >/dev/null 2>&1; then
  echo "Error: screen not found in PATH" >&2
  exit 1
fi

mkdir -p "$SCRIPT_DIR/logs"
START_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$SCRIPT_DIR/logs/hf_import_screen_${SESSION}_${START_TS}.log"
: >"$LOG_FILE"

set +e
screen -dmS "$SESSION" "$RUNNER" "$LOG_FILE" "$JOB_ID"
sc_ec=$?
set -e
if [[ $sc_ec -ne 0 ]]; then
  echo "Error: screen failed to start (exit $sc_ec). Session name taken? Try: screen -ls" >&2
  exit "$sc_ec"
fi

echo "Started detached screen session: $SESSION"
echo "Streaming log file: $LOG_FILE"
echo "Attach: screen -r $SESSION"
