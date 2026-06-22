#!/usr/bin/env bash
# OS bootstrap: apt packages from install/packages/ (+ user adn, deploy.conf).
# Sourced by install.sh as root. Does not install pyenv or run stack install.
set -euo pipefail

: "${ADN_DEPLOY_HOME:?ADN_DEPLOY_HOME required}"
: "${ADN_ROOT:?ADN_ROOT required}"

export DEBIAN_FRONTEND=noninteractive
export DEBCONF_NONINTERACTIVE_SEEN=true
export NEEDRESTART_MODE=a

ADN_USER="${ADN_USER:-adn}"
ADN_USER_HOME="${ADN_USER_HOME:-/home/$ADN_USER}"
ADN_DEPLOY_PROFILE="${ADN_DEPLOY_PROFILE:-full}"
ADN_SUDO_NOPASSWD="${ADN_SUDO_NOPASSWD:-1}"
ADN_CREATE_USER="${ADN_CREATE_USER:-1}"
ADN_LOG_DIR="${ADN_LOG_DIR:-/var/log/adn-server}"
MARKER="$ADN_DEPLOY_HOME/.os-bootstrap-done"

_log() { echo "  os-bootstrap: $*"; }

_package_list() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    if [[ "${ID:-}" == "ubuntu" ]]; then
      printf '%s\n' "$ADN_DEPLOY_HOME/install/packages/ubuntu-minimal.txt"
      return
    fi
  fi
  printf '%s\n' "$ADN_DEPLOY_HOME/install/packages/debian-minimal.txt"
}

_read_packages() {
  local list="$1" profile="$2" line pkg past_web=0
  [[ -f "$list" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^#[[:space:]]*D\) ]] && past_web=1
    if [[ "$profile" == "minimal" && "$past_web" -eq 1 ]]; then
      continue
    fi
    pkg="${line%%#*}"
    pkg="${pkg//[[:space:]]/}"
    [[ -n "$pkg" ]] && printf '%s\n' "$pkg"
  done <"$list"
}

_apt_install() {
  local -a pkgs=("$@")
  [[ ${#pkgs[@]} -gt 0 ]] || { echo "os-bootstrap: no packages to install" >&2; return 1; }
  _log "apt-get update ..."
  apt-get update -y
  _log "apt-get install (${#pkgs[@]} packages, profile=$ADN_DEPLOY_PROFILE) ..."
  apt-get install -y --no-install-recommends \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    "${pkgs[@]}"
  _log "apt-get install done"
}

_ensure_sudoers() {
  local dropin="/etc/sudoers.d/adn-deploy" tmp
  [[ "$ADN_SUDO_NOPASSWD" == "1" ]] || return 0
  id "$ADN_USER" &>/dev/null || return 0
  if ! id -nG "$ADN_USER" 2>/dev/null | tr ' ' '\n' | grep -qx sudo; then
    _log "adding $ADN_USER to group sudo"
    usermod -aG sudo "$ADN_USER" 2>/dev/null || true
  fi
  tmp="$(mktemp)"
  printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$ADN_USER" >"$tmp"
  chmod 0440 "$tmp"
  if command -v visudo >/dev/null 2>&1; then
    visudo -cf "$tmp" >/dev/null
  fi
  install -m 0440 -o root -g root "$tmp" "$dropin"
  rm -f "$tmp"
  _log "sudoers: $dropin"
}

_ensure_user() {
  [[ "$ADN_CREATE_USER" == "1" ]] || {
    id "$ADN_USER" &>/dev/null || { echo "os-bootstrap: user $ADN_USER missing" >&2; return 1; }
    return 0
  }
  if id "$ADN_USER" &>/dev/null; then
    _log "user $ADN_USER exists"
    return 0
  fi
  local pw="${ADN_USER_PASSWORD:-}"
  if [[ -z "$pw" && -r /dev/tty && -w /dev/tty ]]; then
    printf '  os-bootstrap: login password for new Linux user %s: ' "$ADN_USER" >/dev/tty
    read -rs pw </dev/tty
    echo >/dev/tty
  fi
  if [[ -z "$pw" ]]; then
    echo "os-bootstrap: user $ADN_USER does not exist — set ADN_USER_PASSWORD or run from a TTY" >&2
    return 1
  fi
  _log "creating user $ADN_USER (home=$ADN_USER_HOME)"
  getent group "$ADN_USER" >/dev/null 2>&1 || groupadd "$ADN_USER" 2>/dev/null || groupadd -r "$ADN_USER"
  mkdir -p "$(dirname "$ADN_USER_HOME")"
  useradd -m -d "$ADN_USER_HOME" -s /bin/bash -g "$ADN_USER" "$ADN_USER"
  echo "${ADN_USER}:${pw}" | chpasswd
  _log "login password set for $ADN_USER"
}

_deploy_conf_init() {
  local conf="$ADN_DEPLOY_HOME/deploy.conf" ex
  for ex in "$ADN_DEPLOY_HOME/deploy.conf.example" \
            "$ADN_DEPLOY_HOME/templates/deploy.conf.example"; do
    [[ -f "$ex" ]] || continue
    if [[ ! -f "$conf" ]]; then
      cp "$ex" "$conf"
      _log "created $conf from $(basename "$ex")"
    fi
    break
  done
  if [[ -f "$conf" ]]; then
    chown "root:${ADN_USER}" "$conf" 2>/dev/null || chown "${ADN_USER}:${ADN_USER}" "$conf"
    chmod 640 "$conf" 2>/dev/null || chmod 600 "$conf"
  fi
}

if [[ -f "$MARKER" ]]; then
  _log "already done ($MARKER) — skip apt (delete marker to re-run)"
else
  list="$(_package_list)"
  _log "reading $(basename "$list") (profile=$ADN_DEPLOY_PROFILE) ..."
  mapfile -t _PKGS < <(_read_packages "$list" "$ADN_DEPLOY_PROFILE")
  _log "${#_PKGS[@]} packages to install"
  _apt_install "${_PKGS[@]}"
  _ensure_user
  _ensure_sudoers
  mkdir -p "$ADN_LOG_DIR"
  chown "${ADN_USER}:${ADN_USER}" "$ADN_LOG_DIR" 2>/dev/null || true
  _deploy_conf_init
  date -Iseconds >"$MARKER"
  _log "marker written: $MARKER"
fi

chown -R "${ADN_USER}:${ADN_USER}" "$ADN_DEPLOY_HOME" 2>/dev/null || true
_log "complete (profile=$ADN_DEPLOY_PROFILE)"
