#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIMIT="${1:-800}"

declare -a RUNS=(
  "advbench|$SCRIPT_DIR/run_advbench_proxy.sh $LIMIT"
  "xstest|$SCRIPT_DIR/run_xstest_proxy.sh $LIMIT"
  "toxicchat|$SCRIPT_DIR/run_toxicchat_proxy.sh $LIMIT"
  "wildjailbreak|$SCRIPT_DIR/run_wildjailbreak_proxy.sh $LIMIT"
  "do_not_answer|$SCRIPT_DIR/run_do_not_answer_proxy.sh $LIMIT"
  "aya_en|$SCRIPT_DIR/run_aya_proxy.sh $LIMIT en"
  "aya_ru|$SCRIPT_DIR/run_aya_proxy.sh $LIMIT ru"
)

declare -a FAILURES=()
declare -a SUCCESSES=()

echo "Starting Phase 1 sequential run with limit=$LIMIT"
echo "Failure policy: continue-and-report"
echo

for run_spec in "${RUNS[@]}"; do
  name="${run_spec%%|*}"
  cmd="${run_spec#*|}"

  echo "=== RUN: $name ==="
  echo "Command: $cmd"

  bash -lc "$cmd"
  exit_code=$?

  if [[ $exit_code -eq 0 ]]; then
    SUCCESSES+=("$name")
    echo "=== RESULT: $name OK ==="
  else
    FAILURES+=("$name (exit_code=$exit_code)")
    echo "=== RESULT: $name FAILED (exit_code=$exit_code) ==="
  fi

  echo
done

echo "===== Phase 1 summary ====="
echo "Successful runs: ${#SUCCESSES[@]}"
for s in "${SUCCESSES[@]}"; do
  echo "  - $s"
done

echo "Failed runs: ${#FAILURES[@]}"
for f in "${FAILURES[@]}"; do
  echo "  - $f"
done

if [[ ${#FAILURES[@]} -gt 0 ]]; then
  exit 1
fi

exit 0
