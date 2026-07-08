#!/usr/bin/env bash
# Shared environment for Phase 1 long-running services (supervisor / watchdog).
set -euo pipefail

SERVICE_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE1_DIR="$(cd "$SERVICE_COMMON_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PHASE1_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

export PHASE1_DIR REPO_ROOT

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

export PATH="${HOME}/.lmstudio/bin:${PATH:-}"
