#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$ROOT_DIR/.env"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
TASK_FILE="$SCRIPT_DIR/labs/lab1_owasp_top10/run.py"

ATTACKS_PER_TYPE="${1:-1}"
MAX_CONCURRENT="${2:-1}"
PURPOSE="${3:-}"
OWASP_CATEGORIES="${4:-${OWASP_CATEGORIES:-}}"
SMOKE_ONE="${PHASE2_SMOKE_ONE:-0}"

if [[ ! "$ATTACKS_PER_TYPE" =~ ^[0-9]+$ ]] || [[ "$ATTACKS_PER_TYPE" -lt 1 ]]; then
  echo "Error: attacks_per_type must be a positive integer" >&2
  exit 1
fi

if [[ ! "$MAX_CONCURRENT" =~ ^[0-9]+$ ]] || [[ "$MAX_CONCURRENT" -lt 1 ]]; then
  echo "Error: max_concurrent must be a positive integer" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: .env not found at $ENV_FILE" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: Python from .venv not found at $PYTHON_BIN" >&2
  echo "Run setup from phase2_deepteam/: python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f "$TASK_FILE" ]]; then
  echo "Error: task file not found at $TASK_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "Error: required variable OPENROUTER_API_KEY is not set in $ENV_FILE" >&2
  exit 1
fi

TARGET_MODEL_ARG="${OPENROUTER_MODEL:-${TARGET_MODEL:-}}"
if [[ -z "$TARGET_MODEL_ARG" ]]; then
  echo "Error: set OPENROUTER_MODEL or TARGET_MODEL in $ENV_FILE" >&2
  exit 1
fi

JUDGE_MODEL_ARG="${JUDGE_MODEL:-${GRADER_MODEL:-${OPENROUTER_MODEL:-${TARGET_MODEL_ARG}}}}"
ATTACKER_MODEL_ARG="${ATTACKER_MODEL:-${OPENROUTER_MODEL:-${JUDGE_MODEL_ARG}}}"

OPENROUTER_ENDPOINT="${OPENROUTER_BASE_URL:-https://openrouter.ai/api/v1}"
ATTACKER_BASE_URL_ARG="${ATTACKER_BASE_URL:-$OPENROUTER_ENDPOINT}"
JUDGE_BASE_URL_ARG="${JUDGE_BASE_URL:-$OPENROUTER_ENDPOINT}"

if [[ -n "${TARGET_BASE_URL:-}" ]]; then
  TARGET_BASE_URL_ARG="$TARGET_BASE_URL"
elif [[ -n "${OPENROUTER_MODEL:-}" ]]; then
  TARGET_BASE_URL_ARG="$OPENROUTER_ENDPOINT"
elif [[ -n "${MYPROXY_BASE_URL:-}" ]]; then
  TARGET_BASE_URL_ARG="$MYPROXY_BASE_URL"
else
  TARGET_BASE_URL_ARG="$OPENROUTER_ENDPOINT"
fi

if [[ -z "${TARGET_API_KEY:-}" && "$TARGET_BASE_URL_ARG" == "${MYPROXY_BASE_URL:-}" && -n "${MYPROXY_API_KEY:-}" ]]; then
  export TARGET_API_KEY="$MYPROXY_API_KEY"
fi

"$PYTHON_BIN" - <<'PY'
import importlib.util
import sys

missing = [
    module
    for module in ("deepteam", "deepeval", "openai", "dotenv")
    if importlib.util.find_spec(module) is None
]

if missing:
    print("Error: missing Python packages: " + ", ".join(missing), file=sys.stderr)
    print("Install them from phase2_deepteam/: ./.venv/bin/python -m pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1)
PY

args=(
  "$TASK_FILE"
  --target-model "$TARGET_MODEL_ARG"
  --attacker-model "$ATTACKER_MODEL_ARG"
  --judge-model "$JUDGE_MODEL_ARG"
  --target-base-url "$TARGET_BASE_URL_ARG"
  --attacker-base-url "$ATTACKER_BASE_URL_ARG"
  --judge-base-url "$JUDGE_BASE_URL_ARG"
  --attacks-per-type "$ATTACKS_PER_TYPE"
  --max-concurrent "$MAX_CONCURRENT"
)

case "$SMOKE_ONE" in
  1|true|TRUE|yes|YES)
    args+=(--smoke-one)
    ;;
  0|false|FALSE|no|NO|"")
    ;;
  *)
    echo "Error: PHASE2_SMOKE_ONE must be 0/1, true/false, or yes/no" >&2
    exit 1
    ;;
esac

if [[ -n "$PURPOSE" ]]; then
  args+=(--purpose "$PURPOSE")
fi

if [[ -n "$OWASP_CATEGORIES" && "$SMOKE_ONE" != "1" && "$SMOKE_ONE" != "true" && "$SMOKE_ONE" != "TRUE" && "$SMOKE_ONE" != "yes" && "$SMOKE_ONE" != "YES" ]]; then
  IFS=',' read -ra categories <<< "$OWASP_CATEGORIES"
  for category in "${categories[@]}"; do
    category="${category//[[:space:]]/}"
    if [[ -n "$category" ]]; then
      args+=(--owasp-category "$category")
    fi
  done
fi

cd "$SCRIPT_DIR"
"$PYTHON_BIN" "${args[@]}"
