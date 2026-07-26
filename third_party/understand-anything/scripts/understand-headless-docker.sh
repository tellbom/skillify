#!/usr/bin/env bash
set -Eeuo pipefail

# Docker CLI-only launcher for the Understand Anything headless worker.
# It does not invoke Docker Compose and does not contain Claude Code.

ACTION="${1:-help}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE="${UA_WORKER_IMAGE:-understand-anything/headless-worker:0.1.0}"
NODE_IMAGE="${UA_NODE_IMAGE:-node:22.23.1-bookworm-slim}"
ENV_FILE="${UA_WORKER_ENV_FILE:-${REPO_ROOT}/infra/understand-headless/worker.env}"
NETWORK="${UA_DOCKER_NETWORK:-bridge}"

fail() {
  printf '[understand-headless] ERROR: %s\n' "$*" >&2
  exit 1
}

case "$ACTION" in
  build)
    docker build \
      --pull=false \
      --build-arg "UA_NODE_IMAGE=${NODE_IMAGE}" \
      -f "${REPO_ROOT}/infra/understand-headless/Dockerfile" \
      -t "$IMAGE" \
      "$REPO_ROOT"
    ;;
  analyze)
    PROJECT_DIR="${2:-}"
    OUTPUT_DIR="${3:-}"
    [[ -n "$PROJECT_DIR" && -n "$OUTPUT_DIR" ]] || \
      fail "usage: $0 analyze PROJECT_DIR OUTPUT_DIR [worker options]"
    [[ -d "$PROJECT_DIR" ]] || fail "project directory does not exist: $PROJECT_DIR"
    mkdir -p "$OUTPUT_DIR"
    PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
    OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd -P)"
    PROJECT_NAME="${UA_PROJECT_NAME:-$(basename "$PROJECT_DIR")}"
    SOURCE_COMMIT="${UA_SOURCE_COMMIT:-$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || true)}"
    IDENTITY_ARGS=(--project-name "$PROJECT_NAME")
    if [[ -n "$SOURCE_COMMIT" ]]; then
      IDENTITY_ARGS+=(--source-commit "$SOURCE_COMMIT")
    fi
    [[ -f "$ENV_FILE" ]] || fail "environment file does not exist: $ENV_FILE"
    shift 3
    SECRET_ARGS=()
    if [[ -n "${UA_LLM_API_KEY_FILE_HOST:-}" ]]; then
      [[ -f "$UA_LLM_API_KEY_FILE_HOST" ]] || \
        fail "LLM API key file does not exist: $UA_LLM_API_KEY_FILE_HOST"
      SECRET_ARGS=(
        -e UA_LLM_API_KEY_FILE=/run/secrets/ua-llm-api-key
        -v "${UA_LLM_API_KEY_FILE_HOST}:/run/secrets/ua-llm-api-key:ro"
      )
    fi
    OVERRIDE_ARGS=()
    for key in \
      UA_LLM_BASE_URL UA_LLM_MODEL UA_LLM_CONCURRENCY \
      UA_LLM_TIMEOUT_SECONDS UA_LLM_MAX_RETRIES \
      UA_LLM_JSON_MODE UA_LLM_THINKING UA_OUTPUT_LANGUAGE
    do
      if [[ -n "${!key:-}" ]]; then
        OVERRIDE_ARGS+=(-e "${key}=${!key}")
      fi
    done
    docker run --rm \
      --name "understand-worker-$(date +%s)-$$" \
      --network "$NETWORK" \
      --read-only \
      --cap-drop ALL \
      --security-opt no-new-privileges:true \
      --tmpfs /tmp:rw,noexec,nosuid,size=512m \
      --env-file "$ENV_FILE" \
      "${SECRET_ARGS[@]}" \
      "${OVERRIDE_ARGS[@]}" \
      -v "${PROJECT_DIR}:/workspace/source:ro" \
      -v "${OUTPUT_DIR}:/workspace/output:rw" \
      "$IMAGE" analyze \
      --project /workspace/source \
      --output /workspace/output \
      "${IDENTITY_ARGS[@]}" \
      "$@"
    ;;
  status)
    OUTPUT_DIR="${2:-}"
    [[ -n "$OUTPUT_DIR" ]] || fail "usage: $0 status OUTPUT_DIR"
    [[ -f "${OUTPUT_DIR}/status.json" ]] || fail "status file not found"
    sed -n '1,240p' "${OUTPUT_DIR}/status.json"
    ;;
  *)
    printf 'Usage:\n'
    printf '  %s build\n' "$0"
    printf '  %s analyze PROJECT_DIR OUTPUT_DIR [--language zh] [--exclude patterns]\n' "$0"
    printf '  %s status OUTPUT_DIR\n' "$0"
    exit 2
    ;;
esac
