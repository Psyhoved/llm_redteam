#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PHASE2_SMOKE_ONE=1 "$SCRIPT_DIR/run_owasp_top10_proxy.sh" "${1:-1}" "${2:-1}" "${3:-}"
