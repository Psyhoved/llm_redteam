#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/scripts/phase1_screen_runner.sh"

usage() {
  cat <<'EOF' >&2
Usage: ./run_phase1_in_screen.sh [options] [--] [args forwarded to run_phase1_all_proxy.sh]

Screen-only options (not passed to the orchestrator):
  -S NAME, --session NAME   screen session name (default: phase1_<unix_timestamp>)
  --keep-shell             after the run, keep an interactive shell in the session
  -h, --help               this message

Typical commands (limit and MSK time go straight to the orchestrator; no extra variables):
  ./run_phase1_in_screen.sh 2 -a "2026-05-15 03:00:00"
  ./run_phase1_in_screen.sh -S nightly 50 --at-moscow "2026-05-11 03:00:00"
  ./run_phase1_in_screen.sh --keep-shell 10 -a "2026-05-15 03:00:00"

Full console output is always copied to:
  phase1_inspect/logs/phase1_screen_<SESSION>_<YYYYMMDD_HHMMSS>.log

Model/proxy/judge and PHASE1_MAX_CONNECTIONS: repo root .env (see run_*_proxy.sh).
SQLite run log default: logs/phase1_runs.sqlite.

Attach: screen -r <SESSION>     List: screen -ls
EOF
  exit "${1:-0}"
}

SESSION=""
KEEP_SHELL=false
declare -a ARGS=()

while (($#)); do
  case "$1" in
    -S | --session)
      if [[ ${2+x} ]]; then
        SESSION="$2"
      else
        echo "Error: missing value after $1" >&2
        exit 1
      fi
      shift 2
      ;;
    --keep-shell)
      KEEP_SHELL=true
      shift
      ;;
    -h | --help)
      usage 0
      ;;
    --)
      shift
      while (($#)); do ARGS+=("$1"); shift; done
      break
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$SESSION" ]]; then
  SESSION="phase1_$(date +%s)"
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
LOG_FILE="$SCRIPT_DIR/logs/phase1_screen_${SESSION}_${START_TS}.log"
: >"$LOG_FILE"

KEEP_FLAG=0
[[ "$KEEP_SHELL" == true ]] && KEEP_FLAG=1

set +e
screen -dmS "$SESSION" "$RUNNER" "$LOG_FILE" "$KEEP_FLAG" "$SESSION" "${ARGS[@]}"
sc_ec=$?
set -e
if [[ $sc_ec -ne 0 ]]; then
  echo "Error: screen failed to start (exit $sc_ec). Session name taken? Try: screen -ls" >&2
  exit "$sc_ec"
fi

echo "Started detached screen session: $SESSION"
echo "Streaming log file: $LOG_FILE"
echo "Attach: screen -r $SESSION"
