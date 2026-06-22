#!/usr/bin/env bash
# Production install — Docker engine, /opt/adn-docker, adn-docker CLI, registry images (no toolkit clone).
#
#   curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DOCKER="$(cd "$SCRIPT_DIR/.." && pwd)"
ASSET_ROOT="$(cd "$INSTALL_DOCKER/.." && pwd)"
GITHUB_RAW="${GITHUB_RAW:-https://raw.githubusercontent.com/ce5rpy/ADN-Install/master}"

export ADN_DOCKER_ROOT="${ADN_DOCKER_ROOT:-/opt/adn-docker}"
export ADN_SERVER_ROOT="${ADN_SERVER_ROOT:-$ADN_DOCKER_ROOT}"
TARGET_USER="${SUDO_USER:-${USER:-}}"

cat <<EOF
==> ADN Docker install (registry — no toolkit on host)
    Runtime:  $ADN_SERVER_ROOT
    Images:   per-component tags from registry (see $ADN_SERVER_ROOT/.env)
    Edge:     HTTP :\${TRAEFIK_HTTP_PORT:-80} only (HTTPS via adn-docker menu later)
EOF

if [[ "${EUID:-}" -ne 0 ]]; then
  echo "Run as root: curl -fsSL .../docker-install.sh | sudo bash" >&2
  exit 1
fi

echo ""
echo "=== [1/5] Docker Engine ==="
export DEBIAN_FRONTEND=noninteractive
command -v curl >/dev/null 2>&1 || apt-get update -y && apt-get install -y --no-install-recommends curl ca-certificates
if ! command -v docker >/dev/null 2>&1; then
  _debian_sh="$(mktemp)"
  if [[ -f "$INSTALL_DOCKER/scripts/install-docker-debian.sh" ]]; then
    bash "$INSTALL_DOCKER/scripts/install-docker-debian.sh" ${TARGET_USER:+"$TARGET_USER"}
  else
    curl -fsSL "$GITHUB_RAW/install-docker/scripts/install-docker-debian.sh" -o "$_debian_sh"
    bash "$_debian_sh" ${TARGET_USER:+"$TARGET_USER"}
    rm -f "$_debian_sh"
  fi
elif [[ -n "$TARGET_USER" && "$TARGET_USER" != root ]]; then
  usermod -aG docker "$TARGET_USER" 2>/dev/null || true
fi

_adn_run_install_script() {
  local name="$1"
  shift
  local path="$SCRIPT_DIR/$name"
  if [[ -f "$path" ]]; then
    bash "$path" "$@"
    return $?
  fi
  local tmp
  tmp="$(mktemp)"
  curl -fsSL "$GITHUB_RAW/install-docker/scripts/$name" -o "$tmp"
  bash "$tmp" "$@"
  local rc=$?
  rm -f "$tmp"
  return "$rc"
}

echo ""
echo "=== [2/5] /opt/adn-docker + minimal config ==="
export ASSET_ROOT
if [[ ! -f "$ADN_SERVER_ROOT/.env" ]]; then
  _adn_run_install_script bootstrap-standalone.sh
else
  _adn_run_install_script materialize-standalone.sh
  echo "  keep existing: $ADN_SERVER_ROOT/.env"
fi

echo ""
echo "=== [3/5] adn-docker CLI ==="
install -d /usr/local/sbin
if [[ -f "$INSTALL_DOCKER/bin/adn-docker-standalone" ]]; then
  install -m 755 "$INSTALL_DOCKER/bin/adn-docker-standalone" /usr/local/sbin/adn-docker
else
  curl -fsSL "$GITHUB_RAW/install-docker/bin/adn-docker-standalone" -o /usr/local/sbin/adn-docker
  chmod 755 /usr/local/sbin/adn-docker
fi
ln -sf /usr/local/sbin/adn-docker /usr/local/bin/adn-docker 2>/dev/null || true
echo "  installed /usr/local/sbin/adn-docker"

export ADN_DEPLOY_CONF="${ADN_DEPLOY_CONF:-$ADN_SERVER_ROOT/deploy.conf}"
export ADN_DOCKER_ENV_FILE="${ADN_DOCKER_ENV_FILE:-$ADN_SERVER_ROOT/.env}"
export ADN_DOCKER_COMPOSE_FILE="${ADN_DOCKER_COMPOSE_FILE:-$ADN_SERVER_ROOT/docker-compose.yml}"
# shellcheck source=/dev/null
source /usr/local/sbin/adn-docker
set -a
# shellcheck disable=SC1090
source "$ADN_DEPLOY_CONF"
# shellcheck disable=SC1090
source "$ADN_DOCKER_ENV_FILE"
set +a

echo ""
echo "=== [4/5] Pull images + config (CLI container) ==="
adn_docker_precompose_setup || echo "  WARN: pre-compose incomplete — adn-docker setup" >&2

echo ""
echo "=== [5/5] Stack up (HTTP) ==="
adn_docker_compose pull
adn_docker_traefik_render || true
adn_docker_compose up -d
adn_docker_compose ps
adn_docker_after_setup 2>/dev/null || true
adn_docker_run_cli doctor || true

_adn_docker_mandatory_incomplete() {
  local out
  out="$(adn_docker_run_cli doctor 2>&1)" || true
  grep -q 'mandatory config incomplete' <<<"$out"
}

echo ""
echo "=== [6/6] Setup wizard ==="
if _adn_docker_mandatory_incomplete; then
  echo "  Complete mandatory setup (SERVER_ID, dashboard title, APRS if shown)."
  if adn_docker_run_mandatory_wizard; then
    adn_docker_after_setup
    adn_docker_run_cli doctor || true
  else
    echo "  WARN: setup wizard not finished — run: adn-docker setup" >&2
    if ! adn_docker_tty_available; then
      echo "  Tip: from SSH run: sudo adn-docker setup </dev/tty >/dev/tty" >&2
    fi
  fi
else
  echo "  Mandatory config already complete."
fi

registry="${DOCKER_REGISTRY:-docker.io/ce5rpy}"
registry="${registry%/}"
http_port="${TRAEFIK_HTTP_PORT:-80}"

cat <<EOF

=== Install complete ===
Runtime:  $ADN_SERVER_ROOT
Panel:    http://127.0.0.1:${http_port}/
CLI:      adn-docker setup | menu | doctor
Images:   ${ADN_IMAGE_SERVER:-${registry}/adn-server:?}
          ${ADN_IMAGE_MONITOR:-${registry}/adn-monitor:?}
          ${ADN_IMAGE_DAPRS:-${registry}/daprs:?}
          ${ADN_IMAGE_DEPLOY_CLI:-${registry}/adn-deploy-cli:?}

HTTPS off by default — enable later: adn-docker menu → ssl enable
EOF
