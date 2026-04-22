#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$ROOT_DIR/.env"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"

LAB_KEY="${1:-}"
LIMIT="${2:-}"
AYA_LANG="${3:-}"

if [[ -z "$LAB_KEY" ]]; then
  echo "Usage: ./run_phase1_lab_proxy.sh <lab_key> [limit] [aya_lang]" >&2
  echo "Lab keys: advbench, xstest, toxicchat, wildjailbreak, do_not_answer, aya" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: .env not found at $ENV_FILE" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: Python from .venv not found at $PYTHON_BIN" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Keep launcher behavior predictable: always use repo-local datasets.
DATASETS_ROOT="$SCRIPT_DIR/datasets"
export DATASETS_DIR="$DATASETS_ROOT"

required_vars=(
  OPENROUTER_API_KEY
  TARGET_MODEL
  GRADER_MODEL
  MYPROXY_BASE_URL
  MYPROXY_API_KEY
)

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Error: required variable $var_name is not set in $ENV_FILE" >&2
    exit 1
  fi
done

TASK_FILE=""
DATASET_PATH=""

case "$LAB_KEY" in
  advbench)
    TASK_FILE="./labs/lab1_advbench/run.py"
    DATASET_PATH="$DATASETS_ROOT/advbench/harmful_behaviors.csv"
    ;;
  xstest)
    TASK_FILE="./labs/lab2_xstest/run.py"
    DATASET_PATH="$DATASETS_ROOT/xstest/xstest_prompts.csv"
    ;;
  toxicchat)
    TASK_FILE="./labs/lab3_toxicchat/run.py"
    DATASET_PATH="$DATASETS_ROOT/toxicchat"
    ;;
  wildjailbreak)
    TASK_FILE="./labs/lab4_wildjailbreak/run.py"
    DATASET_PATH="$DATASETS_ROOT/wildjailbreak"
    ;;
  do_not_answer)
    TASK_FILE="./labs/lab5_do_not_answer/run.py"
    DATASET_PATH="$DATASETS_ROOT/do_not_answer"
    ;;
  aya)
    TASK_FILE="./labs/lab6_aya_redteaming/run.py"
    DATASET_PATH="$DATASETS_ROOT/aya_redteaming"
    ;;
  *)
    echo "Error: unknown lab_key '$LAB_KEY'" >&2
    exit 1
    ;;
esac

if [[ ! -f "$SCRIPT_DIR/${TASK_FILE#./}" ]]; then
  echo "Error: task file not found at $SCRIPT_DIR/${TASK_FILE#./}" >&2
  exit 1
fi

if [[ ! -e "$DATASET_PATH" ]]; then
  echo "Error: dataset prerequisite not found at $DATASET_PATH" >&2
  echo "Run dataset download first from phase1_inspect/." >&2
  if [[ "$LAB_KEY" == "wildjailbreak" ]]; then
    echo "Hint: wildjailbreak is gated on Hugging Face and needs auth (HF_TOKEN/login)." >&2
  fi
  exit 1
fi

if [[ "$LAB_KEY" == "aya" ]]; then
  lang="${AYA_LANG:-en}"
  export TARGET_LANG="$lang"
fi

args=(
  -m inspect_ai eval "$TASK_FILE"
  --model "$TARGET_MODEL"
  --model-role "grader=$GRADER_MODEL"
  --display plain
  --max-connections 1
)

if [[ -n "$LIMIT" ]]; then
  args+=(--limit "$LIMIT")
fi

cd "$SCRIPT_DIR"
"$PYTHON_BIN" "${args[@]}"
