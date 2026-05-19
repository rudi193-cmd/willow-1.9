#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
GROVE_ROOT="${WILLOW_GROVE_ROOT:-${HOME}/github/safe-app-willow-grove}"

export PYTHONPATH="${REPO_ROOT}:${GROVE_ROOT}"
export WILLOW_ROOT="${REPO_ROOT}"
export WILLOW_AGENT_NAME="${WILLOW_AGENT_NAME:-heimdallr}"
export WILLOW_PG_DB="${WILLOW_PG_DB:-willow_19}"
export WILLOW_PG_HOST="${WILLOW_PG_HOST:-192.168.12.189}"

exec "${REPO_ROOT}/.venv-dev/bin/python3" "${REPO_ROOT}/tools/nest_watcher.py" "$@"
