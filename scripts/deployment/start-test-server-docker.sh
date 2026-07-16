#!/usr/bin/env bash
set -Eeuo pipefail

# Start the existing Skillify test-server containers with Docker CLI only.
# Containers, networks and volumes must already exist; this script never creates or
# recreates them. Run as a user allowed to access the Docker daemon.

WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

container_exists() {
  docker container inspect "$1" >/dev/null 2>&1
}

container_state() {
  docker container inspect --format '{{.State.Status}}' "$1"
}

container_health() {
  docker container inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$1"
}

last_health_exit_code() {
  local codes
  codes="$(docker container inspect --format '{{if .State.Health}}{{range .State.Health.Log}}{{.ExitCode}}{{"\n"}}{{end}}{{end}}' "$1" 2>/dev/null || true)"
  if [[ -n "$codes" ]]; then
    printf '%s\n' "$codes" | tail -n 1
  else
    echo -1
  fi
}

show_failure() {
  local name="$1"
  echo "Container ${name} failed to become ready." >&2
  docker container inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} error={{.State.Error}}' "$name" >&2 || true
  docker container logs --tail 100 "$name" >&2 || true
}

start_and_wait() {
  local name="$1"
  if ! container_exists "$name"; then
    echo "Required container does not exist: ${name}" >&2
    return 1
  fi

  echo "Starting ${name}..."
  docker container start "$name" >/dev/null

  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    local state health last_exit_code
    state="$(container_state "$name")"
    health="$(container_health "$name")"
    last_exit_code="$(last_health_exit_code "$name")"

    if [[ "$state" == "running" && ( "$health" == "healthy" || "$health" == "none" || "$last_exit_code" == "0" ) ]]; then
      echo "Ready: ${name} (health=${health})"
      return 0
    fi
    if [[ "$state" == "exited" || "$state" == "dead" ]]; then
      show_failure "$name"
      return 1
    fi
    sleep 2
  done

  show_failure "$name"
  return 1
}

optional_start_and_wait() {
  local name="$1"
  if container_exists "$name"; then
    start_and_wait "$name"
  else
    echo "Skipping optional container: ${name}"
  fi
}

docker info >/dev/null

# Dependencies first, then stateful supporting services, application APIs and UI.
optional_start_and_wait process-redis
optional_start_and_wait process-es
start_and_wait skillify-db-1
optional_start_and_wait skillify-devpi-1
start_and_wait skillify-forgejo-1
optional_start_and_wait skillify-webhook-1
start_and_wait skillify-skillify-web-1
optional_start_and_wait skillify-frontend-1

echo "Skillify test-server containers are ready."
docker container ls --filter 'name=skillify-' --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
