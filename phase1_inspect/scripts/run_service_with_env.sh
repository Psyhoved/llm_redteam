#!/usr/bin/env bash
# Run a Phase 1 service script with repo .env loaded.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/service_common.sh"

TARGET="${1:?usage: run_service_with_env.sh <script.sh>}"
shift

TARGET_PATH="$PHASE1_DIR/$TARGET"
if [[ ! -f "$TARGET_PATH" ]]; then
  echo "Error: script not found: $TARGET_PATH" >&2
  exit 1
fi

cd "$PHASE1_DIR"
exec bash "$TARGET_PATH" "$@"
