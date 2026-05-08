#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIMIT="${1:-}"
LANGUAGE="${2:-en}"
"$SCRIPT_DIR/run_phase1_lab_proxy.sh" aya "$LIMIT" "$LANGUAGE"
