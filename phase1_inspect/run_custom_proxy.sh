#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIMIT="${1:-}"
SLUG="${2:-}"

if [[ -z "$SLUG" ]]; then
  echo "Usage: ./run_custom_proxy.sh <limit> <dataset_slug>" >&2
  exit 1
fi

export CUSTOM_DATASET_SLUG="$SLUG"
exec "$SCRIPT_DIR/run_phase1_lab_proxy.sh" custom "$LIMIT"
