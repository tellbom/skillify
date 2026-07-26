#!/usr/bin/env bash
set -Eeuo pipefail

# Standalone GitNexus lifecycle using Docker CLI only. This script never invokes
# Docker Compose and never removes the persistent GitNexus data volume.

ACTION="${1:-status}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${SKILLIFY_APP_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
ENV_FILE="${GITNEXUS_ENV_FILE:-${APP_ROOT}/infra/gitnexus-standalone/.env}"
IMPORT_HELPER="${APP_ROOT}/scripts/gitnexus/import_source.py"

env_value() {
  local key="$1" default_value="${2:-}" value
  if [[ ! -f "$ENV_FILE" ]]; then
    printf '%s' "$default_value"
    return
  fi
  value="$(sed -n -E "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*(.*)$/\\1/p" "$ENV_FILE" | tail -n 1)"
  value="${value%$'\r'}"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then value="${value:1:${#value}-2}"; fi
  if [[ "$value" == \'*\' && "$value" == *\' ]]; then value="${value:1:${#value}-2}"; fi
  printf '%s' "${value:-$default_value}"
}

config_value() {
  local key="$1" default_value="${2:-}" override
  override="${!key:-}"
  if [[ -n "$override" ]]; then
    printf '%s' "$override"
  else
    env_value "$key" "$default_value"
  fi
}

WAIT_TIMEOUT_SECONDS="$(config_value GITNEXUS_WAIT_TIMEOUT_SECONDS 180)"

NETWORK="$(config_value GITNEXUS_DOCKER_NETWORK skillify-gitnexus-standalone)"
INGRESS_NETWORK="$(config_value GITNEXUS_INGRESS_NETWORK skillify-gitnexus-ingress)"
SERVER_CONTAINER="$(config_value GITNEXUS_SERVER_CONTAINER skillify-gitnexus-server)"
WEB_CONTAINER="$(config_value GITNEXUS_WEB_CONTAINER skillify-gitnexus-web)"
GATEWAY_CONTAINER="$(config_value GITNEXUS_GATEWAY_CONTAINER skillify-gitnexus-gateway)"
DATA_VOLUME="$(config_value GITNEXUS_DATA_VOLUME skillify-gitnexus-data)"

SERVER_BASE_IMAGE="$(config_value GITNEXUS_SERVER_BASE_IMAGE ghcr.io/abhigyanpatwari/gitnexus:1.6.9)"
SERVER_IMAGE="$(config_value GITNEXUS_SERVER_IMAGE skillify/gitnexus:1.6.9-unlimited)"
WEB_IMAGE="$(config_value GITNEXUS_WEB_IMAGE ghcr.io/abhigyanpatwari/gitnexus-web:1.6.9)"
GATEWAY_IMAGE="$(config_value GITNEXUS_GATEWAY_IMAGE nginx:1.27.5-alpine)"
GATEWAY_CONFIG="$(config_value GITNEXUS_GATEWAY_CONFIG "${APP_ROOT}/infra/gitnexus-standalone/nginx.conf")"
STATE_ROOT="$(config_value GITNEXUS_STATE_ROOT /srv/skillify/gitnexus)"
SOURCE_ROOT="$(config_value GITNEXUS_SOURCE_ROOT "${STATE_ROOT}/sources")"

BIND_HOST="$(config_value GITNEXUS_BIND_HOST 127.0.0.1)"
SERVER_PORT="$(config_value GITNEXUS_SERVER_PORT 4747)"
WEB_PORT="$(config_value GITNEXUS_WEB_PORT 4173)"
PUBLIC_URL="$(config_value GITNEXUS_PUBLIC_URL "http://${BIND_HOST}:${WEB_PORT}")"
BACKEND_URL="$(config_value GITNEXUS_BACKEND_URL "$PUBLIC_URL")"
SKIP_PULL="$(config_value GITNEXUS_SKIP_PULL 1)"
ALLOWED_GIT_HOSTS="$(config_value GITNEXUS_ALLOWED_GIT_HOSTS '')"
GIT_TIMEOUT_SECONDS="$(config_value GITNEXUS_GIT_TIMEOUT_SECONDS 300)"

SERVER_MEMORY="$(config_value GITNEXUS_SERVER_MEMORY 0)"
WEB_MEMORY="$(config_value GITNEXUS_WEB_MEMORY 0)"
GATEWAY_MEMORY="$(config_value GITNEXUS_GATEWAY_MEMORY 0)"
SERVER_CPUS="$(config_value GITNEXUS_SERVER_CPUS 0)"
WEB_CPUS="$(config_value GITNEXUS_WEB_CPUS 0)"
GATEWAY_CPUS="$(config_value GITNEXUS_GATEWAY_CPUS 0)"
PIDS_LIMIT="$(config_value GITNEXUS_PIDS_LIMIT 0)"
LIMIT_ARGS=(--label com.skillify.resource-limits=unlimited)

log() { printf '[gitnexus-docker] %s\n' "$*"; }
fail() { printf '[gitnexus-docker] ERROR: %s\n' "$*" >&2; exit 1; }
container_exists() { docker container inspect "$1" >/dev/null 2>&1; }
container_running() {
  [[ "$(docker container inspect --format '{{.State.Running}}' "$1" 2>/dev/null || true)" == "true" ]]
}
health_status() {
  docker container inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

set_limit_args() {
  local memory="$1" cpus="$2"
  LIMIT_ARGS=(--label com.skillify.resource-limits=unlimited)
  [[ "$PIDS_LIMIT" == "0" ]] || LIMIT_ARGS+=(--pids-limit "$PIDS_LIMIT")
  [[ "$memory" == "0" ]] || LIMIT_ARGS+=(--memory "$memory" --memory-swap "$memory")
  [[ "$cpus" == "0" ]] || LIMIT_ARGS+=(--cpus "$cpus")
}

validate_settings() {
  [[ -n "$BIND_HOST" ]] || fail "GITNEXUS_BIND_HOST must not be empty"
  [[ "$SERVER_PORT" =~ ^[0-9]+$ && "$SERVER_PORT" -ge 1024 && "$SERVER_PORT" -le 65535 ]] || fail \
    "GITNEXUS_SERVER_PORT must be between 1024 and 65535"
  [[ "$WEB_PORT" =~ ^[0-9]+$ && "$WEB_PORT" -ge 1024 && "$WEB_PORT" -le 65535 ]] || fail \
    "GITNEXUS_WEB_PORT must be between 1024 and 65535"
  [[ "$SERVER_PORT" != "$WEB_PORT" ]] || fail "server and web ports must differ"
  [[ "$STATE_ROOT" = /* && "$SOURCE_ROOT" = /* ]] || fail "state and source roots must be absolute"
  [[ "$SOURCE_ROOT" == "$STATE_ROOT/"* ]] || fail "source root must be contained by state root"
  [[ -f "$GATEWAY_CONFIG" ]] || fail "gateway config is unavailable: ${GATEWAY_CONFIG}"
}

require_docker() {
  require_command docker
  docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
}

pull_images() {
  if [[ "$SKIP_PULL" == "1" ]]; then
    docker image inspect "$SERVER_IMAGE" >/dev/null 2>&1 || fail "server image is not loaded: ${SERVER_IMAGE}"
    docker image inspect "$WEB_IMAGE" >/dev/null 2>&1 || fail "web image is not loaded: ${WEB_IMAGE}"
    docker image inspect "$GATEWAY_IMAGE" >/dev/null 2>&1 || fail "gateway image is not loaded: ${GATEWAY_IMAGE}"
    log "offline image check passed; no registry pull was attempted"
    return
  fi
  log "pulling pinned server image ${SERVER_IMAGE}"
  docker image pull "$SERVER_IMAGE" >/dev/null
  log "pulling pinned web image ${WEB_IMAGE}"
  docker image pull "$WEB_IMAGE" >/dev/null
  log "pulling pinned gateway image ${GATEWAY_IMAGE}"
  docker image pull "$GATEWAY_IMAGE" >/dev/null
}

prepare_server_image() {
  require_docker
  docker image inspect "$SERVER_BASE_IMAGE" >/dev/null 2>&1 || fail \
    "base image is not loaded: ${SERVER_BASE_IMAGE}"
  log "building upload-unlimited server image without network or registry pulls"
  docker build --pull=false --network=none \
    --build-arg "GITNEXUS_BASE_IMAGE=${SERVER_BASE_IMAGE}" \
    -t "$SERVER_IMAGE" \
    -f "${APP_ROOT}/infra/gitnexus-standalone/Dockerfile.server-unlimited" \
    "${APP_ROOT}/infra/gitnexus-standalone"
}

ensure_objects() {
  install -d -m 0750 "$SOURCE_ROOT"
  docker network inspect "$NETWORK" >/dev/null 2>&1 || \
    docker network create --internal "$NETWORK" >/dev/null
  docker network inspect "$INGRESS_NETWORK" >/dev/null 2>&1 || \
    docker network create "$INGRESS_NETWORK" >/dev/null
  docker volume inspect "$DATA_VOLUME" >/dev/null 2>&1 || \
    docker volume create "$DATA_VOLUME" >/dev/null
}

show_failure() {
  local name="$1"
  docker container inspect \
    --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} error={{.State.Error}}' \
    "$name" >&2 || true
  docker container logs --tail 100 "$name" >&2 || true
}

wait_ready() {
  local name="$1" deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS)) state health
  while (( SECONDS < deadline )); do
    state="$(docker container inspect --format '{{.State.Status}}' "$name" 2>/dev/null || true)"
    health="$(health_status "$name" 2>/dev/null || true)"
    if [[ "$state" == "running" && "$health" == "healthy" ]]; then
      log "ready: ${name}"
      return
    fi
    if [[ "$state" == "exited" || "$state" == "dead" ]]; then
      show_failure "$name"
      fail "container exited before becoming ready: ${name}"
    fi
    sleep 2
  done
  show_failure "$name"
  fail "container did not become ready: ${name}"
}

stop_one() {
  local name="$1"
  if container_exists "$name" && container_running "$name"; then
    log "stopping ${name}"
    docker container stop --time 30 "$name" >/dev/null
  fi
}

remove_container() {
  local name="$1"
  if container_exists "$name"; then
    stop_one "$name"
    log "removing container ${name}; persistent volume is retained"
    docker container rm "$name" >/dev/null
  fi
}

create_server() {
  set_limit_args "$SERVER_MEMORY" "$SERVER_CPUS"
  docker run -d --name "$SERVER_CONTAINER" --restart unless-stopped \
    --label com.skillify.component=gitnexus-standalone \
    --network "$NETWORK" --network-alias gitnexus-server \
    --read-only --cap-drop ALL --security-opt no-new-privileges:true \
    "${LIMIT_ARGS[@]}" --tmpfs /tmp:rw,noexec,nosuid,size=128m \
    -e GITNEXUS_HOME=/data/gitnexus \
    -v "${DATA_VOLUME}:/data/gitnexus" -v "${SOURCE_ROOT}:/workspace:ro" \
    --health-cmd "curl -fsS http://127.0.0.1:4747/api/health >/dev/null" \
    --health-interval 10s --health-timeout 5s --health-retries 12 --health-start-period 20s \
    "$SERVER_IMAGE" >/dev/null
  wait_ready "$SERVER_CONTAINER"
}

create_web() {
  set_limit_args "$WEB_MEMORY" "$WEB_CPUS"
  docker run -d --name "$WEB_CONTAINER" --restart unless-stopped \
    --label com.skillify.component=gitnexus-standalone \
    --network "$NETWORK" --network-alias gitnexus-web \
    --read-only --cap-drop ALL --security-opt no-new-privileges:true \
    "${LIMIT_ARGS[@]}" --tmpfs /tmp:rw,noexec,nosuid,size=32m \
    -e "GITNEXUS_BACKEND_URL=${BACKEND_URL}" \
    --health-cmd "curl -fsS http://127.0.0.1:4173/ >/dev/null" \
    --health-interval 10s --health-timeout 5s --health-retries 12 --health-start-period 10s \
    "$WEB_IMAGE" >/dev/null
  wait_ready "$WEB_CONTAINER"
}

create_gateway() {
  set_limit_args "$GATEWAY_MEMORY" "$GATEWAY_CPUS"
  docker create --name "$GATEWAY_CONTAINER" --restart unless-stopped \
    --label com.skillify.component=gitnexus-standalone \
    --network "$INGRESS_NETWORK" --network-alias gitnexus-gateway \
    --user 101:101 \
    --read-only --cap-drop ALL --security-opt no-new-privileges:true \
    "${LIMIT_ARGS[@]}" \
    --tmpfs /var/cache/nginx:rw,noexec,nosuid,size=16m,uid=101,gid=101 \
    --tmpfs /var/run:rw,noexec,nosuid,size=4m,uid=101,gid=101 \
    --tmpfs /tmp:rw,noexec,nosuid,size=4m,uid=101,gid=101 \
    -v "${GATEWAY_CONFIG}:/etc/nginx/conf.d/default.conf:ro" \
    -p "${BIND_HOST}:${SERVER_PORT}:4747" -p "${BIND_HOST}:${WEB_PORT}:8080" \
    --health-cmd "wget -qO- http://127.0.0.1:8080/api/health >/dev/null" \
    --health-interval 10s --health-timeout 5s --health-retries 12 --health-start-period 10s \
    "$GATEWAY_IMAGE" >/dev/null
  docker network connect "$NETWORK" "$GATEWAY_CONTAINER"
  docker container start "$GATEWAY_CONTAINER" >/dev/null
  wait_ready "$GATEWAY_CONTAINER"
}

deploy() {
  require_docker
  pull_images
  ensure_objects
  remove_container "$GATEWAY_CONTAINER"
  remove_container "$WEB_CONTAINER"
  remove_container "$SERVER_CONTAINER"
  create_server
  create_web
  create_gateway
  status
}

start() {
  require_docker
  container_exists "$SERVER_CONTAINER" || fail "server container is missing; run '$0 deploy'"
  container_exists "$WEB_CONTAINER" || fail "web container is missing; run '$0 deploy'"
  container_exists "$GATEWAY_CONTAINER" || fail "gateway container is missing; run '$0 deploy'"
  docker container start "$SERVER_CONTAINER" >/dev/null
  wait_ready "$SERVER_CONTAINER"
  docker container start "$WEB_CONTAINER" >/dev/null
  wait_ready "$WEB_CONTAINER"
  docker container start "$GATEWAY_CONTAINER" >/dev/null
  wait_ready "$GATEWAY_CONTAINER"
}

stop() {
  require_docker
  stop_one "$GATEWAY_CONTAINER"
  stop_one "$WEB_CONTAINER"
  stop_one "$SERVER_CONTAINER"
}

status() {
  require_docker
  local name
  printf '%-32s %-12s %-12s\n' CONTAINER STATE HEALTH
  for name in "$SERVER_CONTAINER" "$WEB_CONTAINER" "$GATEWAY_CONTAINER"; do
    if container_exists "$name"; then
      printf '%-32s %-12s %-12s\n' "$name" \
        "$(docker container inspect --format '{{.State.Status}}' "$name")" \
        "$(health_status "$name")"
    else
      printf '%-32s %-12s %-12s\n' "$name" missing -
    fi
  done
  printf 'web=%s backend=%s sources=%s\n' \
    "http://${BIND_HOST}:${WEB_PORT}" "$BACKEND_URL" "$SOURCE_ROOT"
}

index_repository() {
  local repository_id="$1" repository_path index_path
  require_docker
  container_running "$SERVER_CONTAINER" || fail "GitNexus server is not running"
  [[ "$repository_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || fail "invalid repository ID"
  repository_path="${SOURCE_ROOT}/${repository_id}"
  index_path="${repository_path}/.gitnexus"
  [[ -d "$repository_path" ]] || fail "source does not exist: ${repository_id}"
  [[ ! -L "$repository_path" ]] || fail "source directory must not be a symbolic link"
  [[ ! -L "$index_path" ]] || fail "reserved index path must not be a symbolic link"
  if [[ -e "$index_path" && ! -d "$index_path" ]]; then
    fail "reserved index path is not a directory: ${index_path}"
  fi
  install -d -m 0770 "$index_path"
  log "analyzing read-only source /workspace/${repository_id} in an isolated container"
  set_limit_args "$SERVER_MEMORY" "$SERVER_CPUS"
  docker run --rm \
    --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true \
    "${LIMIT_ARGS[@]}" --tmpfs /tmp:rw,noexec,nosuid,size=256m \
    -e GITNEXUS_HOME=/tmp/gitnexus-home \
    -v "${repository_path}:/workspace/${repository_id}:ro" \
    -v "${index_path}:/workspace/${repository_id}/.gitnexus:rw" \
    "$SERVER_IMAGE" \
    gitnexus analyze "/workspace/${repository_id}" \
    --skip-git --index-only --skip-skills --skip-agents-md --no-stats
  log "registering completed index with the running GitNexus server"
  docker container exec "$SERVER_CONTAINER" \
    gitnexus index --allow-non-git "/workspace/${repository_id}"
}

import_zip() {
  local repository_id="${2:-}" archive="${3:-}"
  [[ -n "$repository_id" && -n "$archive" ]] || fail "usage: $0 import-zip <repository-id> <archive.zip>"
  require_command python3
  python3 "$IMPORT_HELPER" --source-root "$SOURCE_ROOT" zip "$repository_id" "$archive"
  index_repository "$repository_id"
}

import_git() {
  local repository_id="${2:-}" url="${3:-}" branch="${4:-}"
  [[ -n "$repository_id" && -n "$url" ]] || fail \
    "usage: $0 import-git <repository-id> <http(s)-url> [branch]"
  require_command python3
  require_command git
  local arguments=(
    "$IMPORT_HELPER" --source-root "$SOURCE_ROOT" git "$repository_id" "$url"
    --allowed-hosts "$ALLOWED_GIT_HOSTS" --timeout "$GIT_TIMEOUT_SECONDS"
  )
  if [[ -n "$branch" ]]; then arguments+=(--branch "$branch"); fi
  python3 "${arguments[@]}"
  index_repository "$repository_id"
}

doctor() {
  require_docker
  validate_settings
  docker image inspect "$SERVER_IMAGE" >/dev/null 2>&1 || fail "server image is not loaded: ${SERVER_IMAGE}"
  docker image inspect "$WEB_IMAGE" >/dev/null 2>&1 || fail "web image is not loaded: ${WEB_IMAGE}"
  docker image inspect "$GATEWAY_IMAGE" >/dev/null 2>&1 || fail "gateway image is not loaded: ${GATEWAY_IMAGE}"
  log "server image ID: $(docker image inspect --format '{{.Id}}' "$SERVER_IMAGE")"
  log "web image ID: $(docker image inspect --format '{{.Id}}' "$WEB_IMAGE")"
  log "gateway image ID: $(docker image inspect --format '{{.Id}}' "$GATEWAY_IMAGE")"
  log "configuration and pinned images are available"
}

mvp_test() {
  require_docker
  require_command curl
  container_running "$SERVER_CONTAINER" || fail "GitNexus server is not running"
  container_running "$WEB_CONTAINER" || fail "GitNexus web is not running"
  container_running "$GATEWAY_CONTAINER" || fail "GitNexus gateway is not running"
  curl --fail --silent --show-error \
    --connect-timeout 3 --max-time 10 "http://${BIND_HOST}:${SERVER_PORT}/api/health" >/dev/null
  curl --fail --silent --show-error \
    --connect-timeout 3 --max-time 10 "http://${BIND_HOST}:${WEB_PORT}/" >/dev/null
  log "MVP health check passed: server API and web UI are reachable"
}

validate_settings

case "$ACTION" in
  deploy) deploy ;;
  start) start; status ;;
  restart) stop; start; status ;;
  stop) stop; status ;;
  status) status ;;
  logs)
    require_docker
    docker container logs --tail 200 "$SERVER_CONTAINER"
    docker container logs --tail 200 "$WEB_CONTAINER"
    docker container logs --tail 200 "$GATEWAY_CONTAINER"
    ;;
  doctor) doctor ;;
  prepare-image) prepare_server_image ;;
  mvp-test) mvp_test ;;
  index)
    [[ -n "${2:-}" ]] || fail "usage: $0 index <repository-id>"
    index_repository "$2"
    ;;
  import-zip) import_zip "$@" ;;
  import-git) import_git "$@" ;;
  *) fail "usage: $0 {prepare-image|deploy|start|restart|stop|status|logs|doctor|mvp-test|index|import-zip|import-git}" ;;
esac
