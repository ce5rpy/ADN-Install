#!/usr/bin/env bash
# Shared paths and helpers for install-docker compose scripts.
# shellcheck shell=bash

INSTALL_DOCKER="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADN_REPO_ROOT="$(cd "$INSTALL_DOCKER/.." && pwd)"

export ADN_DEPLOY_HOME="${ADN_DEPLOY_HOME:-$ADN_REPO_ROOT}"
export INSTALL_DOCKER ADN_REPO_ROOT

ADN_COMPOSE_DIR="${ADN_COMPOSE_DIR:-$INSTALL_DOCKER/compose}"
export ADN_COMPOSE_DIR

ADN_ENV_FILE="${ADN_DOCKER_ENV_FILE:-$ADN_COMPOSE_DIR/.env}"
ADN_COMPOSE_FILE="${ADN_DOCKER_COMPOSE_FILE:-$ADN_COMPOSE_DIR/compose.yml}"
ADN_DOCKER_PROFILE="${ADN_DOCKER_PROFILE:-full}"
ADN_BUILD_CONTEXT="${ADN_BUILD_CONTEXT:-$ADN_REPO_ROOT}"

export ADN_ENV_FILE ADN_COMPOSE_FILE ADN_DOCKER_PROFILE ADN_BUILD_CONTEXT

adn_docker_require_engine() {
  command -v docker >/dev/null 2>&1 || {
    echo "docker: command not found — run install-docker/scripts/install-docker-debian.sh" >&2
    return 1
  }
  docker compose version >/dev/null 2>&1 || {
    echo "docker: compose plugin missing" >&2
    return 1
  }
}

adn_docker_require_env_file() {
  if [[ ! -f "$ADN_ENV_FILE" ]]; then
    echo "Missing $ADN_ENV_FILE — run: $INSTALL_DOCKER/scripts/bootstrap-config.sh" >&2
    return 1
  fi
}

adn_docker_compose_files() {
  local -a files=(-f "$ADN_COMPOSE_FILE")
  [[ -f "$ADN_COMPOSE_DIR/compose.override.yml" ]] && files+=(-f "$ADN_COMPOSE_DIR/compose.override.yml")
  local ports_override="${ADN_DOCKER_STATE:-$ADN_COMPOSE_DIR/state}/${_ADN_DOCKER_PORTS_OVERRIDE:-adn-server-ports.override.yml}"
  [[ -f "$ports_override" ]] && files+=(-f "$ports_override")
  local traefik_override="${ADN_DOCKER_STATE:-$ADN_COMPOSE_DIR/state}/traefik/ssl.override.yml"
  [[ -f "$traefik_override" ]] && files+=(-f "$traefik_override")
  printf '%s\n' "${files[@]}"
}

adn_docker_compose_cmd() {
  local -a files=()
  local f
  while IFS= read -r f; do
    [[ -n "$f" ]] && files+=("$f")
  done < <(adn_docker_compose_files)
  if [[ -f "$ADN_ENV_FILE" ]]; then
    docker compose "${files[@]}" --env-file "$ADN_ENV_FILE" --profile "$ADN_DOCKER_PROFILE" "$@"
  else
    docker compose "${files[@]}" --profile "$ADN_DOCKER_PROFILE" "$@"
  fi
}

adn_docker_compose_down() {
  adn_docker_compose_cmd down "$@" 2>/dev/null || true
}

adn_docker_http_port() {
  local port="${TRAEFIK_HTTP_PORT:-80}"
  if [[ -f "$ADN_ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$ADN_ENV_FILE" && set +a
    port="${TRAEFIK_HTTP_PORT:-$port}"
  fi
  printf '%s' "$port"
}

# shellcheck source=install-docker/lib/docker-tag.sh
source "$INSTALL_DOCKER/lib/docker-tag.sh"

adn_docker_source_env() {
  if [[ -f "$ADN_ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ADN_ENV_FILE"
    set +a
  fi
  adn_docker_resolve_release_vars
}
