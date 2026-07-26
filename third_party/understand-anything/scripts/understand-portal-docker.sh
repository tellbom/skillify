#!/usr/bin/env bash
set -Eeuo pipefail

ACTION="${1:-help}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE="${UA_PORTAL_IMAGE:-understand-anything/portal:0.1.0}"
NODE_IMAGE="${UA_NODE_IMAGE:-node:22.23.1-bookworm-slim}"
CONTAINER="${UA_PORTAL_CONTAINER:-understand-anything-portal}"
PORT="${UA_PORTAL_PORT:-5173}"
BIND_HOST="${UA_PORTAL_BIND_HOST:-0.0.0.0}"
NETWORK="${UA_DOCKER_NETWORK:-bridge}"
STATE_DIR="${UA_PORTAL_STATE_DIR:-${REPO_ROOT}/.runtime/understand-portal}"
PROJECTS_DIR="${UA_PORTAL_PROJECTS_DIR:-${STATE_DIR}/projects}"
TOKEN_FILE="${UA_PORTAL_TOKEN_FILE:-${STATE_DIR}/access-token}"
ENV_FILE="${UA_PORTAL_ENV_FILE:-${REPO_ROOT}/infra/understand-portal/portal.env}"

fail() {
  printf '[understand-portal] ERROR: %s\n' "$*" >&2
  exit 1
}

ensure_state() {
  mkdir -p "$STATE_DIR" "$PROJECTS_DIR"
  chmod 700 "$STATE_DIR"
  if [[ ! -f "$TOKEN_FILE" ]]; then
    openssl rand -hex 16 > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
  fi
  [[ -s "$TOKEN_FILE" ]] || fail "token file is empty: $TOKEN_FILE"
}

case "$ACTION" in
  build)
    docker build \
      --pull=false \
      --build-arg "UA_NODE_IMAGE=${NODE_IMAGE}" \
      -f "${REPO_ROOT}/infra/understand-portal/Dockerfile" \
      -t "$IMAGE" \
      "$REPO_ROOT"
    ;;
  start)
    ensure_state
    [[ -f "$ENV_FILE" ]] || fail "environment file does not exist: $ENV_FILE"
    [[ -n "${UA_LLM_API_KEY_FILE_HOST:-}" ]] || \
      fail "UA_LLM_API_KEY_FILE_HOST must point to a readable API key file"
    [[ -f "$UA_LLM_API_KEY_FILE_HOST" ]] || \
      fail "LLM API key file does not exist: $UA_LLM_API_KEY_FILE_HOST"
    if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
      fail "container already exists: $CONTAINER (run '$0 stop' first)"
    fi
    RUNTIME_UID="${UA_PORTAL_RUNTIME_UID:-$(id -u)}"
    RUNTIME_GID="${UA_PORTAL_RUNTIME_GID:-$(id -g)}"
    if [[ "$RUNTIME_UID" == "0" ]]; then
      RUNTIME_UID=1000
      RUNTIME_GID=1000
    fi
    OPTIONAL_SECRETS=()
    if [[ -n "${UA_GIT_TOKEN_FILE_HOST:-}" ]]; then
      [[ -f "$UA_GIT_TOKEN_FILE_HOST" ]] || \
        fail "Git token file does not exist: $UA_GIT_TOKEN_FILE_HOST"
      OPTIONAL_SECRETS+=(
        -e UA_GIT_TOKEN_FILE=/run/secrets/git-token
        -v "${UA_GIT_TOKEN_FILE_HOST}:/run/secrets/git-token:ro"
      )
    fi
    docker run -d \
      --name "$CONTAINER" \
      --restart unless-stopped \
      --network "$NETWORK" \
      --user "${RUNTIME_UID}:${RUNTIME_GID}" \
      --read-only \
      --cap-drop ALL \
      --security-opt no-new-privileges:true \
      --tmpfs /tmp:rw,noexec,nosuid,size=256m \
      --env-file "$ENV_FILE" \
      -e UNDERSTAND_ACCESS_TOKEN_FILE=/run/secrets/portal-token \
      -e UA_LLM_API_KEY_FILE=/run/secrets/llm-api-key \
      -p "${BIND_HOST}:${PORT}:5173" \
      -v "${TOKEN_FILE}:/run/secrets/portal-token:ro" \
      -v "${UA_LLM_API_KEY_FILE_HOST}:/run/secrets/llm-api-key:ro" \
      -v "${PROJECTS_DIR}:/data/projects:rw" \
      ${OPTIONAL_SECRETS[@]+"${OPTIONAL_SECRETS[@]}"} \
      "$IMAGE"
    ;;
  stop)
    docker rm -f "$CONTAINER"
    ;;
  status)
    docker ps --filter "name=^/${CONTAINER}$" \
      --format '{{.Names}} {{.Status}} {{.Ports}}'
    ;;
  url)
    ensure_state
    DISPLAY_HOST="${UA_PORTAL_PUBLIC_HOST:-127.0.0.1}"
    printf 'http://%s:%s/?portal=1&token=%s\n' \
      "$DISPLAY_HOST" "$PORT" "$(tr -d '\r\n' < "$TOKEN_FILE")"
    ;;
  logs)
    docker logs --tail "${UA_PORTAL_LOG_LINES:-200}" "$CONTAINER"
    ;;
  export)
    ARCHIVE="${2:-understand-anything-portal-0.1.0.tar}"
    docker save -o "$ARCHIVE" "$IMAGE"
    printf '%s\n' "$ARCHIVE"
    ;;
  *)
    printf 'Usage:\n'
    printf '  %s build\n' "$0"
    printf '  %s start\n' "$0"
    printf '  %s stop | status | url | logs\n' "$0"
    printf '  %s export [ARCHIVE.tar]\n' "$0"
    exit 2
    ;;
esac
