#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

LIMIT=800
AT_MOSCOW=""
SLEEP_BEFORE_SEC=""
LOG_DB=""
LOG_DB_EXPLICIT_OVERRIDE=""
DISABLE_LOG_DB=false
DEFAULT_LOG_DB_REL="logs/phase1_runs.sqlite"
RUN_ID=""
SCREEN_SESSION="${PHASE1_SCREEN_SESSION:-}"
BENCHMARKS_FILTER=""

FULL_ARGV_JSON="[]"
if [[ -n "$PYTHON_BIN" ]] && command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
  FULL_ARGV_JSON=$("$PYTHON_BIN" -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@") || FULL_ARGV_JSON="[]"
fi

usage() {
  cat <<EOF >&2
Usage: ./run_phase1_all_proxy.sh [limit] [options]

  limit                      Optional sample limit per benchmark (default: 800)
  --at-moscow | -a "when"     Wait once until Moscow wall-clock time (GNU date, TZ=Europe/Moscow).
                              This is the normal way to schedule a deferred Phase 1 run.
                              Examples: "2026-05-11 03:00:00", "tomorrow 03:00"
  --no-log-db                 Disable SQLite logging (by default logs are written).
  --log-db PATH               Override default SQLite path (normally you do not need this).
  --sleep-before SECONDS      Optional extra sleep in seconds AFTER the MSK wait (rare/debug only).
  --benchmarks LIST           Comma-separated benchmark keys to run (default: all).
                              Keys: advbench,xstest,toxicchat,wildjailbreak,do_not_answer,
                              aya_en,aya_ru,ukrf,fin_oil,pii_bench
  --labs LIST                 Deprecated alias for --benchmarks.

Examples:
  ./run_phase1_all_proxy.sh 2 -a "2026-05-15 03:00:00"
  ./run_phase1_all_proxy.sh 50 --at-moscow "2026-05-11 03:00:00"
  ./run_phase1_all_proxy.sh 200 -a "tomorrow 09:30"
  ./run_phase1_all_proxy.sh 50 --benchmarks advbench,xstest,fin_oil

Model / proxy / judge API (TARGET_MODEL, GRADER_MODEL, MYPROXY_*, OPENROUTER_API_KEY, etc.):
  Set in the repo root .env (see run_phase1_lab_proxy.sh and run_*_proxy.sh). No need to pass them on this command line.
  Inspect concurrency: PHASE1_MAX_CONNECTIONS in .env (default: 1).

SQLite (MVP, automatic):
  Default file: $SCRIPT_DIR/$DEFAULT_LOG_DB_REL
  Override path: env PHASE1_LOG_DB, or flag --log-db PATH. Disable: --no-log-db.

Notes:
  - Failure policy is continue-and-report (one failing benchmark does not abort the rest — e.g. missing wildjailbreak data).
  - If both --at-moscow and --sleep-before are set, MSK wait runs first, then the extra sleep.
EOF
  exit "${1:-0}"
}

sleep_until_moscow() {
  local target="$1"
  local target_epoch now_epoch delay

  if ! target_epoch=$(TZ=Europe/Moscow date -d "$target" +%s 2>/dev/null); then
    echo "Error: could not parse MSK datetime '$target'" >&2
    echo "Try a GNU date form, e.g. '2026-05-11 03:00:00' or 'tomorrow 09:00'" >&2
    exit 1
  fi
  now_epoch=$(date +%s)
  delay=$((target_epoch - now_epoch))
  if ((delay <= 0)); then
    echo "Error: Moscow time '$target' is not in the future (now epoch=$now_epoch, target epoch=$target_epoch)" >&2
    exit 1
  fi
  echo "Waiting ${delay}s until MSK \"$target\" (Europe/Moscow)..."
  sleep "$delay"
}

json_field() {
  local json_file="$1"
  local field="$2"
  "$PYTHON_BIN" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2], ""))' "$json_file" "$field"
}

VALID_BENCHMARK_KEYS=(
  advbench xstest toxicchat wildjailbreak do_not_answer
  aya_en aya_ru ukrf fin_oil pii_bench
)

load_custom_benchmark_keys() {
  if [[ -z "$PYTHON_BIN" ]] || ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
    return 0
  fi
  local keys
  keys=$(
    cd "$SCRIPT_DIR" && "$PYTHON_BIN" -c 'from admin.datasets import custom_benchmark_keys; print(" ".join(custom_benchmark_keys()))' \
      2>/dev/null || true
  )
  if [[ -n "$keys" ]]; then
    # shellcheck disable=SC2206
    local extra=($keys)
    VALID_BENCHMARK_KEYS+=("${extra[@]}")
  fi
}

validate_benchmarks_filter() {
  load_custom_benchmark_keys
  local key
  local -a requested=()
  local -a invalid=()
  IFS=',' read -ra requested <<<"$BENCHMARKS_FILTER"
  for key in "${requested[@]}"; do
    key="${key// /}"
    [[ -z "$key" ]] && continue
    local found=0
    for valid in "${VALID_BENCHMARK_KEYS[@]}"; do
      if [[ "$key" == "$valid" ]]; then
        found=1
        break
      fi
    done
    if [[ $found -eq 0 ]]; then
      invalid+=("$key")
    fi
  done
  if [[ ${#invalid[@]} -gt 0 ]]; then
    echo "Error: unknown benchmark key(s): ${invalid[*]}" >&2
    echo "Valid keys: ${VALID_BENCHMARK_KEYS[*]}" >&2
    exit 1
  fi
  if [[ ${#requested[@]} -eq 0 ]]; then
    echo "Error: --benchmarks requires at least one benchmark key" >&2
    exit 1
  fi
}

benchmark_in_filter() {
  local name="$1"
  [[ -z "$BENCHMARKS_FILTER" ]] && return 0
  local key
  IFS=',' read -ra keys <<<"$BENCHMARKS_FILTER"
  for key in "${keys[@]}"; do
    key="${key// /}"
    [[ "$key" == "$name" ]] && return 0
  done
  return 1
}

while (($#)); do
  case "$1" in
    --at-moscow | -a)
      if [[ ${2+x} ]]; then AT_MOSCOW="$2"; else echo "Error: missing value after $1" >&2; usage 2; fi
      shift 2
      ;;
    --sleep-before)
      if [[ ${2+x} ]]; then SLEEP_BEFORE_SEC="$2"; else echo "Error: missing value after --sleep-before" >&2; usage 2; fi
      shift 2
      ;;
    --log-db)
      if [[ ${2+x} ]]; then LOG_DB_EXPLICIT_OVERRIDE="$2"; else echo "Error: missing value after --log-db" >&2; usage 2; fi
      shift 2
      ;;
    --no-log-db)
      DISABLE_LOG_DB=true
      shift
      ;;
    --benchmarks)
      if [[ ${2+x} ]]; then BENCHMARKS_FILTER="$2"; else echo "Error: missing value after --benchmarks" >&2; usage 2; fi
      shift 2
      ;;
    --labs)
      echo "Warning: --labs is deprecated; use --benchmarks instead" >&2
      if [[ ${2+x} ]]; then BENCHMARKS_FILTER="$2"; else echo "Error: missing value after --labs" >&2; usage 2; fi
      shift 2
      ;;
    -h | --help)
      usage 0
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        LIMIT="$1"
      else
        echo "Error: unexpected argument '$1'" >&2
        usage 2
      fi
      shift
      ;;
  esac
done

if [[ -n "$BENCHMARKS_FILTER" ]]; then
  validate_benchmarks_filter
fi

if [[ -n "$AT_MOSCOW" ]]; then
  sleep_until_moscow "$AT_MOSCOW"
fi

if [[ -n "$SLEEP_BEFORE_SEC" ]]; then
  if ! [[ "$SLEEP_BEFORE_SEC" =~ ^[0-9]+$ ]] || [[ "$SLEEP_BEFORE_SEC" -eq 0 ]]; then
    echo "Error: --sleep-before must be a positive integer (seconds)." >&2
    exit 1
  fi
  if [[ -n "$AT_MOSCOW" ]]; then
    echo "Extra delay: ${SLEEP_BEFORE_SEC}s (--sleep-before) after reaching MSK schedule time..."
  else
    echo "Sleeping ${SLEEP_BEFORE_SEC}s (--sleep-before) before benchmarks..."
  fi
  sleep "$SLEEP_BEFORE_SEC"
fi

if [[ "$DISABLE_LOG_DB" == true ]]; then
  LOG_DB=""
elif [[ -n "$LOG_DB_EXPLICIT_OVERRIDE" ]]; then
  LOG_DB="$LOG_DB_EXPLICIT_OVERRIDE"
elif [[ -n "${PHASE1_LOG_DB:-}" ]]; then
  LOG_DB="$PHASE1_LOG_DB"
else
  LOG_DB="$SCRIPT_DIR/$DEFAULT_LOG_DB_REL"
fi

if [[ -n "$LOG_DB" ]]; then
  if [[ -z "$PYTHON_BIN" ]] || ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Error: python interpreter required for SQLite logging (set PYTHON_BIN or install python3)" >&2
    exit 1
  fi
  start_args=(
    "$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_log.py" start-run
    --db "$LOG_DB"
    --hostname "$(hostname)"
    --limit-val "$LIMIT"
    --argv-json "$FULL_ARGV_JSON"
  )
  if [[ -n "$AT_MOSCOW" ]]; then
    start_args+=(--at-moscow "$AT_MOSCOW")
  else
    start_args+=(--at-moscow "")
  fi
  if [[ -n "$SLEEP_BEFORE_SEC" ]]; then
    start_args+=(--sleep-before-sec "$SLEEP_BEFORE_SEC")
  fi
  if [[ -n "$SCREEN_SESSION" ]]; then
    start_args+=(--screen-session "$SCREEN_SESSION")
  else
    start_args+=(--screen-session "")
  fi
  RUN_ID="$("${start_args[@]}")" || RUN_ID=""
  if [[ -z "$RUN_ID" ]]; then
    echo "Error: failed to allocate SQLite run row" >&2
    exit 1
  fi
fi

declare -a RUNS=(
  "advbench|$SCRIPT_DIR/run_advbench_proxy.sh $LIMIT"
  "xstest|$SCRIPT_DIR/run_xstest_proxy.sh $LIMIT"
  "toxicchat|$SCRIPT_DIR/run_toxicchat_proxy.sh $LIMIT"
  "wildjailbreak|$SCRIPT_DIR/run_wildjailbreak_proxy.sh $LIMIT"
  "do_not_answer|$SCRIPT_DIR/run_do_not_answer_proxy.sh $LIMIT"
  "aya_en|$SCRIPT_DIR/run_aya_proxy.sh $LIMIT en"
  "aya_ru|$SCRIPT_DIR/run_aya_proxy.sh $LIMIT ru"
  "ukrf|$SCRIPT_DIR/run_ukrf_proxy.sh $LIMIT"
  "fin_oil|$SCRIPT_DIR/run_fin_oil_proxy.sh $LIMIT"
  "pii_bench|$SCRIPT_DIR/run_pii_bench_proxy.sh $LIMIT"
)

if [[ -n "$PYTHON_BIN" ]] && command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
  while IFS= read -r custom_key; do
    [[ -z "$custom_key" ]] && continue
    custom_slug="${custom_key#custom_}"
    RUNS+=("${custom_key}|$SCRIPT_DIR/run_custom_proxy.sh $LIMIT ${custom_slug}")
  done < <(
    cd "$SCRIPT_DIR" && "$PYTHON_BIN" -c 'from admin.datasets import custom_benchmark_keys; print("\n".join(custom_benchmark_keys()))' \
      2>/dev/null || true
  )
fi

declare -a FAILURES=()
declare -a SUCCESSES=()

echo "Starting Phase 1 sequential run with limit=$LIMIT"
if [[ -n "$AT_MOSCOW" ]]; then
  echo "Scheduled start MSK was: $AT_MOSCOW"
fi
if [[ -n "$SLEEP_BEFORE_SEC" ]]; then
  if [[ -n "$AT_MOSCOW" ]]; then
    echo "Extra delay after MSK time was: ${SLEEP_BEFORE_SEC}s (--sleep-before)"
  else
    echo "Lead-in delay was: ${SLEEP_BEFORE_SEC}s (--sleep-before)"
  fi
fi
if [[ -n "$LOG_DB" ]]; then
  echo "SQLite log DB: $LOG_DB (run_id=$RUN_ID)"
fi
if [[ -n "$BENCHMARKS_FILTER" ]]; then
  echo "Benchmark filter: $BENCHMARKS_FILTER"
fi
echo "Failure policy: continue-and-report — one failing benchmark (e.g. wildjailbreak without data) does not stop the remaining benchmarks."
echo

for run_spec in "${RUNS[@]}"; do
  name="${run_spec%%|*}"
  cmd="${run_spec#*|}"

  if ! benchmark_in_filter "$name"; then
    echo "=== SKIP: $name (not in --benchmarks filter) ==="
    echo
    continue
  fi

  echo "=== RUN: $name ==="
  echo "Command: $cmd"

  raw_exit_code=0
  effective_exit_code=0
  status_reason=""
  status_value=""
  eval_log_path=""
  progress_pid=""

  tmp_out="$(mktemp)"
  tmp_err="$(mktemp)"
  tmp_meta="$(mktemp)"
  : >"$tmp_err"
  lab_started="$(date -Is -u)"

  if [[ -n "$LOG_DB" ]]; then
    "$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_log.py" start-benchmark \
      --db "$LOG_DB" \
      --run-id "$RUN_ID" \
      --lab-name "$name" \
      --samples-total "$LIMIT" || true
    (
      while true; do
        progress_json="$("$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_progress.py" \
          --db "$LOG_DB" \
          --run-id "$RUN_ID" \
          --benchmark-name "$name" \
          --base-dir "$SCRIPT_DIR" \
          --limit "$LIMIT" 2>/dev/null || echo '{}')"
        samples_done="$("$PYTHON_BIN" -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("samples_done", 0))' "$progress_json")"
        samples_total="$("$PYTHON_BIN" -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("samples_total", 0))' "$progress_json")"
        if [[ -n "$samples_done" && -n "$samples_total" ]]; then
          "$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_log.py" update-benchmark-progress \
            --db "$LOG_DB" \
            --run-id "$RUN_ID" \
            --lab-name "$name" \
            --samples-done "$samples_done" \
            --samples-total "$samples_total" 2>/dev/null || true
        fi
        sleep 15
      done
    ) &
    progress_pid=$!
  fi

  bash -lc "$cmd" 2>&1 | tee "$tmp_out" || raw_exit_code=$?
  cp "$tmp_out" "$tmp_err"
  lab_finished="$(date -Is -u)"

  if [[ -n "$progress_pid" ]]; then
    kill "$progress_pid" 2>/dev/null || true
    wait "$progress_pid" 2>/dev/null || true
  fi

  echo "--- stdout (${name}) ---"
  cat "$tmp_out"
  echo "--- stderr (${name}) ---" >&2
  cat "$tmp_err" >&2

  "$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_inspect_status.py" \
    --lab-name "$name" \
    --stdout-file "$tmp_out" \
    --stderr-file "$tmp_err" \
    --raw-exit-code "$raw_exit_code" \
    --base-dir "$SCRIPT_DIR" \
    --metadata-file "$tmp_meta"
  effective_exit_code=$?
  status_reason="$(json_field "$tmp_meta" reason)"
  status_value="$(json_field "$tmp_meta" status)"
  eval_log_path="$(json_field "$tmp_meta" eval_log)"

  final_samples_done=""
  final_samples_total=""
  if [[ -n "$LOG_DB" ]]; then
    progress_json="$("$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_progress.py" \
      --db "$LOG_DB" \
      --run-id "$RUN_ID" \
      --benchmark-name "$name" \
      --base-dir "$SCRIPT_DIR" \
      --limit "$LIMIT" 2>/dev/null || echo '{}')"
    final_samples_done="$("$PYTHON_BIN" -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("samples_done", ""))' "$progress_json")"
    final_samples_total="$("$PYTHON_BIN" -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("samples_total", ""))' "$progress_json")"
  fi

  if [[ -n "$LOG_DB" ]]; then
    finish_args=(
      "$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_log.py" finish-benchmark
      --db "$LOG_DB"
      --run-id "$RUN_ID"
      --lab-name "$name"
      --started-at "$lab_started"
      --finished-at "$lab_finished"
      --exit-code "$effective_exit_code"
      --raw-exit-code "$raw_exit_code"
      --status "$status_value"
      --reason "$status_reason"
      --eval-log "$eval_log_path"
      --stdout-file "$tmp_out"
      --stderr-file "$tmp_err"
    )
    if [[ -n "$final_samples_done" ]]; then
      finish_args+=(--samples-done "$final_samples_done")
    fi
    if [[ -n "$final_samples_total" ]]; then
      finish_args+=(--samples-total "$final_samples_total")
    fi
    "${finish_args[@]}"
  fi

  rm -f "$tmp_out" "$tmp_err" "$tmp_meta"

  if [[ "$effective_exit_code" -eq 0 ]]; then
    SUCCESSES+=("$name")
    echo "=== RESULT: $name OK ==="
  else
    FAILURES+=("$name (raw_exit=$raw_exit_code, effective_exit=$effective_exit_code, reason=$status_reason)")
    echo "=== RESULT: $name FAILED (raw_exit=$raw_exit_code, effective_exit=$effective_exit_code, reason=$status_reason) ==="
  fi

  echo
done

FINAL_EXIT=0
if [[ ${#FAILURES[@]} -gt 0 ]]; then
  FINAL_EXIT=1
fi

if [[ -n "$LOG_DB" && -n "$RUN_ID" ]]; then
  "$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_log.py" finish-run \
    --db "$LOG_DB" --run-id "$RUN_ID" --exit-code "$FINAL_EXIT"
fi

if [[ -n "$LOG_DB" && -n "$RUN_ID" ]]; then
  METRICS_OUT_DIR="$SCRIPT_DIR/reports/phase1_metrics/run_${RUN_ID}"
  if "$PYTHON_BIN" "$SCRIPT_DIR/scripts/phase1_metrics.py" \
    --sqlite "$LOG_DB" \
    --run-id "$RUN_ID" \
    --base-dir "$SCRIPT_DIR" \
    --out-dir "$METRICS_OUT_DIR"; then
    echo "Metrics report: $METRICS_OUT_DIR/report.html"
  else
    echo "Warning: failed to generate Phase 1 metrics report" >&2
  fi
fi

echo "===== Phase 1 summary ====="
echo "Successful runs: ${#SUCCESSES[@]}"
for s in "${SUCCESSES[@]}"; do
  echo "  - $s"
done

echo "Failed runs: ${#FAILURES[@]}"
for f in "${FAILURES[@]}"; do
  echo "  - $f"
done

exit "$FINAL_EXIT"
