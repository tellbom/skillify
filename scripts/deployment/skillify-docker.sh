#!/usr/bin/env bash
set -Eeuo pipefail

# Skillify server lifecycle using Docker CLI only. This script never invokes
# Docker Compose and never removes named volumes.

ACTION="${1:-status}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${SKILLIFY_APP_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
ENV_FILE="${SKILLIFY_ENV_FILE:-${APP_ROOT}/infra/.env}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

NETWORK="${SKILLIFY_DOCKER_NETWORK:-skillify_skillify}"
DB_CONTAINER="${SKILLIFY_DB_CONTAINER:-skillify-db-1}"
FORGEJO_CONTAINER="${SKILLIFY_FORGEJO_CONTAINER:-skillify-forgejo-1}"
DEVPI_CONTAINER="${SKILLIFY_DEVPI_CONTAINER:-skillify-devpi-1}"
WEBHOOK_CONTAINER="${SKILLIFY_WEBHOOK_CONTAINER:-skillify-webhook-1}"
WEB_CONTAINER="${SKILLIFY_WEB_CONTAINER:-skillify-skillify-web-1}"
FRONTEND_CONTAINER="${SKILLIFY_FRONTEND_CONTAINER:-skillify-frontend-1}"
DB_VOLUME="${SKILLIFY_DB_VOLUME:-skillify_forgejo-db}"
FORGEJO_VOLUME="${SKILLIFY_FORGEJO_VOLUME:-skillify_forgejo-data}"
DEVPI_VOLUME="${SKILLIFY_DEVPI_VOLUME:-skillify_devpi-data}"

POSTGRES_IMAGE="${SKILLIFY_POSTGRES_IMAGE:-postgres:12}"
FORGEJO_IMAGE="${SKILLIFY_FORGEJO_IMAGE:-codeberg.org/forgejo/forgejo:10}"
WEB_IMAGE="${SKILLIFY_WEB_IMAGE:-skillify-skillify-web:local}"
FRONTEND_IMAGE="${SKILLIFY_FRONTEND_IMAGE:-skillify-frontend:local}"
DEVPI_IMAGE="${SKILLIFY_DEVPI_IMAGE:-skillify-devpi:local}"

log() { printf '[skillify-docker] %s\n' "$*"; }
fail() { printf '[skillify-docker] ERROR: %s\n' "$*" >&2; exit 1; }
container_exists() { docker container inspect "$1" >/dev/null 2>&1; }
container_running() { [[ "$(docker container inspect --format '{{.State.Running}}' "$1" 2>/dev/null || true)" == "true" ]]; }

env_value() {
  local key="$1" default_value="${2:-}" value
  value="$(sed -n -E "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*(.*)$/\\1/p" "$ENV_FILE" | tail -n 1)"
  value="${value%$'\r'}"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then value="${value:1:${#value}-2}"; fi
  if [[ "$value" == \'*\' && "$value" == *\' ]]; then value="${value:1:${#value}-2}"; fi
  printf '%s' "${value:-$default_value}"
}

require_env_file() {
  [[ -f "$ENV_FILE" ]] || fail "environment file not found: ${ENV_FILE}"
}

ensure_docker_objects() {
  docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
  for volume in "$DB_VOLUME" "$FORGEJO_VOLUME" "$DEVPI_VOLUME"; do
    docker volume inspect "$volume" >/dev/null 2>&1 || docker volume create "$volume" >/dev/null
  done
}

health_status() {
  docker container inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1"
}

show_failure() {
  local name="$1"
  docker container inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} error={{.State.Error}}' "$name" >&2 || true
  docker container logs --tail 100 "$name" >&2 || true
}

wait_ready() {
  local name="$1" deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS)) state health
  while (( SECONDS < deadline )); do
    state="$(docker container inspect --format '{{.State.Status}}' "$name" 2>/dev/null || true)"
    health="$(health_status "$name" 2>/dev/null || true)"
    if [[ "$state" == "running" && ( "$health" == "healthy" || "$health" == "none" ) ]]; then
      log "ready: ${name} (health=${health})"
      return 0
    fi
    if [[ "$state" == "exited" || "$state" == "dead" ]]; then
      show_failure "$name"
      return 1
    fi
    sleep 2
  done
  show_failure "$name"
  fail "container did not become ready: ${name}"
}

start_one() {
  local name="$1" required="${2:-required}"
  if ! container_exists "$name"; then
    [[ "$required" == "optional" ]] && { log "skip missing optional container: ${name}"; return; }
    fail "container does not exist: ${name}; run '$0 deploy' first"
  fi
  docker container start "$name" >/dev/null
  wait_ready "$name"
}

stop_one() {
  local name="$1"
  if container_exists "$name" && container_running "$name"; then
    log "stopping ${name}"
    docker container stop --time 30 "$name" >/dev/null
  fi
}

remove_stateless() {
  local name
  for name in "$FRONTEND_CONTAINER" "$WEB_CONTAINER" "$WEBHOOK_CONTAINER"; do
    if container_exists "$name"; then
      log "recreating stateless container: ${name}"
      docker container rm --force "$name" >/dev/null
    fi
  done
}

create_stateful_if_missing() {
  local db_user db_password db_name forgejo_domain forgejo_root forgejo_http forgejo_ssh registration devpi_port
  db_user="$(env_value FORGEJO_DB_USER forgejo)"
  db_password="$(env_value FORGEJO_DB_PASSWORD forgejo)"
  db_name="$(env_value FORGEJO_DB_NAME forgejo)"
  forgejo_domain="$(env_value FORGEJO_DOMAIN localhost)"
  forgejo_root="$(env_value FORGEJO_ROOT_URL http://localhost:3000/)"
  forgejo_http="$(env_value FORGEJO_HTTP_PORT 3000)"
  forgejo_ssh="$(env_value FORGEJO_SSH_PORT 2222)"
  registration="$(env_value FORGEJO_DISABLE_REGISTRATION false)"
  devpi_port="$(env_value DEVPI_PORT 3141)"

  if ! container_exists "$DB_CONTAINER"; then
    log "creating ${DB_CONTAINER} with persistent volume ${DB_VOLUME}"
    docker run -d --name "$DB_CONTAINER" --restart unless-stopped \
      --network "$NETWORK" --network-alias db \
      -e "POSTGRES_USER=${db_user}" -e "POSTGRES_PASSWORD=${db_password}" -e "POSTGRES_DB=${db_name}" \
      -v "${DB_VOLUME}:/var/lib/postgresql/data" \
      --health-cmd "pg_isready -U ${db_user}" --health-interval 5s --health-timeout 5s --health-retries 10 \
      "$POSTGRES_IMAGE" >/dev/null
  fi
  start_one "$DB_CONTAINER"

  if ! container_exists "$FORGEJO_CONTAINER"; then
    log "creating ${FORGEJO_CONTAINER} with persistent volume ${FORGEJO_VOLUME}"
    docker run -d --name "$FORGEJO_CONTAINER" --restart unless-stopped \
      --network "$NETWORK" --network-alias forgejo \
      -e USER_UID=1000 -e USER_GID=1000 \
      -e FORGEJO__database__DB_TYPE=postgres -e FORGEJO__database__HOST=db:5432 \
      -e "FORGEJO__database__NAME=${db_name}" -e "FORGEJO__database__USER=${db_user}" \
      -e "FORGEJO__database__PASSWD=${db_password}" -e "FORGEJO__server__DOMAIN=${forgejo_domain}" \
      -e "FORGEJO__server__ROOT_URL=${forgejo_root}" -e FORGEJO__server__HTTP_PORT=3000 \
      -e "FORGEJO__service__DISABLE_REGISTRATION=${registration}" \
      -v "${FORGEJO_VOLUME}:/data" -p "${forgejo_http}:3000" -p "${forgejo_ssh}:22" \
      "$FORGEJO_IMAGE" >/dev/null
  fi
  start_one "$FORGEJO_CONTAINER"

  if ! container_exists "$DEVPI_CONTAINER"; then
    log "creating ${DEVPI_CONTAINER} with persistent volume ${DEVPI_VOLUME}"
    docker run -d --name "$DEVPI_CONTAINER" --restart unless-stopped \
      --network "$NETWORK" --network-alias devpi -v "${DEVPI_VOLUME}:/data" \
      -p "${devpi_port}:3141" "$DEVPI_IMAGE" >/dev/null
  fi
  start_one "$DEVPI_CONTAINER"
}

build_images() {
  require_env_file
  local keycloak_url keycloak_realm keycloak_client rbac_url rbac_project
  POSTGRES_IMAGE="$(env_value SKILLIFY_POSTGRES_IMAGE "$POSTGRES_IMAGE")"
  FORGEJO_IMAGE="$(env_value SKILLIFY_FORGEJO_IMAGE "$FORGEJO_IMAGE")"
  WEB_IMAGE="$(env_value SKILLIFY_WEB_IMAGE "$WEB_IMAGE")"
  FRONTEND_IMAGE="$(env_value SKILLIFY_FRONTEND_IMAGE "$FRONTEND_IMAGE")"
  DEVPI_IMAGE="$(env_value SKILLIFY_DEVPI_IMAGE "$DEVPI_IMAGE")"
  keycloak_url="$(env_value VITE_KEYCLOAK_REALM_URL)"
  rbac_url="$(env_value VITE_RBAC_BASE_URL)"
  [[ -n "$keycloak_url" ]] || fail "VITE_KEYCLOAK_REALM_URL is required in ${ENV_FILE}"
  [[ -n "$rbac_url" ]] || fail "VITE_RBAC_BASE_URL is required in ${ENV_FILE}"
  keycloak_realm="$(env_value VITE_KEYCLOAK_REALM)"
  keycloak_client="$(env_value VITE_KEYCLOAK_CLIENT_ID skillify-web)"
  rbac_project="$(env_value VITE_RBAC_PROJECT skillify)"

  log "building backend image ${WEB_IMAGE}"
  docker build -t "$WEB_IMAGE" -f "$APP_ROOT/Dockerfile" "$APP_ROOT"
  log "building devpi image ${DEVPI_IMAGE}"
  docker build -t "$DEVPI_IMAGE" -f "$APP_ROOT/infra/devpi/Dockerfile" "$APP_ROOT/infra/devpi"
  log "building frontend image ${FRONTEND_IMAGE}"
  docker build -t "$FRONTEND_IMAGE" -f "$APP_ROOT/web/Dockerfile" \
    --build-arg VITE_API_BASE=/api \
    --build-arg "VITE_KEYCLOAK_REALM_URL=${keycloak_url}" \
    --build-arg "VITE_KEYCLOAK_REALM=${keycloak_realm}" \
    --build-arg "VITE_KEYCLOAK_CLIENT_ID=${keycloak_client}" \
    --build-arg "VITE_RBAC_BASE_URL=${rbac_url}" \
    --build-arg "VITE_RBAC_PROJECT=${rbac_project}" \
    "$APP_ROOT/web"
}

create_stateless() {
  local webhook_port http_port
  webhook_port="$(env_value WEBHOOK_PORT 8088)"
  http_port="$(env_value SKILLIFY_HTTP_PORT 8080)"

  docker run -d --name "$WEBHOOK_CONTAINER" --restart unless-stopped \
    --network "$NETWORK" --network-alias webhook --env-file "$ENV_FILE" \
    -p "${webhook_port}:8088" "$WEB_IMAGE" skillify-webhook >/dev/null
  start_one "$WEBHOOK_CONTAINER"

  docker run -d --name "$WEB_CONTAINER" --restart unless-stopped \
    --network "$NETWORK" --network-alias skillify-web --env-file "$ENV_FILE" \
    -e SKILLIFY_WEB_UPLOAD_GIT_ENABLED=true \
    --health-cmd "uv run python -c \"import requests; requests.get('http://127.0.0.1:8089/healthz', timeout=2).raise_for_status()\"" \
    --health-interval 10s --health-timeout 5s --health-retries 10 \
    "$WEB_IMAGE" skillify-web >/dev/null
  start_one "$WEB_CONTAINER"

  docker run -d --name "$FRONTEND_CONTAINER" --restart unless-stopped \
    --network "$NETWORK" --network-alias frontend --add-host host.docker.internal:host-gateway \
    -p "${http_port}:80" "$FRONTEND_IMAGE" >/dev/null
  start_one "$FRONTEND_CONTAINER"
}

start_external_dependencies() {
  local name
  for name in kc-postgres keycloak process-redis process-es; do
    if container_exists "$name"; then start_one "$name" optional; fi
  done
  if command -v systemctl >/dev/null 2>&1; then
    for name in rbac-api.service rbac-worker.service; do
      if systemctl cat "$name" >/dev/null 2>&1; then
        log "starting ${name}"
        systemctl start "$name"
      fi
    done
  fi
}

start_stack() {
  start_external_dependencies
  start_one "$DB_CONTAINER"
  start_one "$DEVPI_CONTAINER" optional
  start_one "$FORGEJO_CONTAINER"
  start_one "$WEBHOOK_CONTAINER" optional
  start_one "$WEB_CONTAINER"
  start_one "$FRONTEND_CONTAINER" optional
}

stop_stack() {
  stop_one "$FRONTEND_CONTAINER"
  stop_one "$WEB_CONTAINER"
  stop_one "$WEBHOOK_CONTAINER"
  stop_one "$FORGEJO_CONTAINER"
  stop_one "$DEVPI_CONTAINER"
  stop_one "$DB_CONTAINER"
}

status_stack() {
  local name
  printf '%-30s %-12s %-12s\n' CONTAINER STATE HEALTH
  for name in kc-postgres keycloak process-redis process-es "$DB_CONTAINER" "$DEVPI_CONTAINER" "$FORGEJO_CONTAINER" "$WEBHOOK_CONTAINER" "$WEB_CONTAINER" "$FRONTEND_CONTAINER"; do
    if container_exists "$name"; then
      printf '%-30s %-12s %-12s\n' "$name" \
        "$(docker container inspect --format '{{.State.Status}}' "$name")" "$(health_status "$name")"
    else
      printf '%-30s %-12s %-12s\n' "$name" missing -
    fi
  done
}

docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"

case "$ACTION" in
  deploy)
    build_images
    ensure_docker_objects
    start_external_dependencies
    create_stateful_if_missing
    remove_stateless
    create_stateless
    status_stack
    ;;
  start) start_stack; status_stack ;;
  restart) stop_stack; start_stack; status_stack ;;
  stop) stop_stack; status_stack ;;
  status) status_stack ;;
  *) fail "usage: $0 {deploy|start|restart|stop|status}" ;;
esac
