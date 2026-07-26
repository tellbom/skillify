#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLIFY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
UNDERSTAND_ROOT="${SKILLIFY_ROOT}/third_party/understand-anything"

export UA_PORTAL_STATE_DIR="${UA_PORTAL_STATE_DIR:-${SKILLIFY_ROOT}/.runtime/understand-anything}"
export UA_LLM_API_KEY_FILE_HOST="${UA_LLM_API_KEY_FILE_HOST:-${UA_PORTAL_STATE_DIR}/llm-api-key}"
export UA_PORTAL_ENV_FILE="${UA_PORTAL_ENV_FILE:-${UA_PORTAL_STATE_DIR}/portal.env}"

exec "${UNDERSTAND_ROOT}/scripts/understand-portal-docker.sh" "$@"
