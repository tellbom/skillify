#!/usr/bin/env bash
set -Eeuo pipefail

ACTION="${1:-help}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE="${UA_VIEWER_IMAGE:-understand-anything/viewer:0.1.0}"
NODE_IMAGE="${UA_NODE_IMAGE:-node:22.23.1-bookworm-slim}"
CONTAINER="${UA_VIEWER_CONTAINER:-understand-anything-viewer}"
PORT="${UA_VIEWER_PORT:-5173}"
BIND_HOST="${UA_VIEWER_BIND_HOST:-0.0.0.0}"
STATE_DIR="${UA_VIEWER_STATE_DIR:-${REPO_ROOT}/.runtime/understand-viewer}"
TOKEN_FILE="${UA_VIEWER_TOKEN_FILE:-${STATE_DIR}/access-token}"

fail() {
  printf '[understand-viewer] ERROR: %s\n' "$*" >&2
  exit 1
}

ensure_token() {
  mkdir -p "$STATE_DIR"
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
      -f "${REPO_ROOT}/infra/understand-viewer/Dockerfile" \
      -t "$IMAGE" \
      "$REPO_ROOT"
    ;;
  start)
    PROJECT_DIR="${2:-}"
    GRAPH_DIR="${3:-}"
    [[ -d "$PROJECT_DIR" ]] || fail "project directory does not exist: $PROJECT_DIR"
    [[ -f "${GRAPH_DIR}/knowledge-graph.json" ]] || \
      fail "knowledge graph does not exist: ${GRAPH_DIR}/knowledge-graph.json"
    PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
    GRAPH_DIR="$(cd "$GRAPH_DIR" && pwd -P)"
    ensure_token
    if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
      fail "container already exists: $CONTAINER (run '$0 stop' first)"
    fi
    docker run -d \
      --name "$CONTAINER" \
      --restart unless-stopped \
      --read-only \
      --cap-drop ALL \
      --security-opt no-new-privileges:true \
      --tmpfs /tmp:rw,noexec,nosuid,size=64m \
      -e UNDERSTAND_ACCESS_TOKEN_FILE=/run/secrets/viewer-token \
      -e UNDERSTAND_GRAPH_DIR=/workspace/graph \
      -p "${BIND_HOST}:${PORT}:5173" \
      -v "${TOKEN_FILE}:/run/secrets/viewer-token:ro" \
      -v "${PROJECT_DIR}:/workspace/project:ro" \
      -v "${GRAPH_DIR}:/workspace/graph:ro" \
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
    DISPLAY_HOST="${UA_VIEWER_PUBLIC_HOST:-127.0.0.1}"
    ensure_token
    printf 'http://%s:%s/?token=%s\n' "$DISPLAY_HOST" "$PORT" "$(tr -d '\r\n' < "$TOKEN_FILE")"
    ;;
  logs)
    docker logs --tail "${UA_VIEWER_LOG_LINES:-200}" "$CONTAINER"
    ;;
  export)
    ARCHIVE="${2:-understand-anything-viewer-0.1.0.tar}"
    docker save -o "$ARCHIVE" "$IMAGE"
    printf '%s\n' "$ARCHIVE"
    ;;
  *)
    printf 'Usage:\n'
    printf '  %s build\n' "$0"
    printf '  %s start PROJECT_DIR GRAPH_DIR\n' "$0"
    printf '  %s stop | status | url | logs\n' "$0"
    printf '  %s export [ARCHIVE.tar]\n' "$0"
    exit 2
    ;;
esac
