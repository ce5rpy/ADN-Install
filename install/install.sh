#!/usr/bin/env bash
# ADN-Deploy bootstrap — curl | bash
# One-shot install: OS → pyenv (/opt/.pyenv) → stack → wizard → web panel → services.
set -euo pipefail

if [[ "${EUID:-}" -ne 0 ]]; then
  echo "install.sh: run as root (e.g. sudo bash install.sh)." >&2
  exit 1
fi

if [[ ! -f /etc/os-release ]]; then
  echo "install.sh: Debian/Ubuntu required." >&2
  exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "debian" && "${ID:-}" != "ubuntu" ]]; then
  echo "install.sh: unsupported OS ${ID:-?}." >&2
  exit 1
fi

export ADN_ROOT="${ADN_ROOT:-/opt}"
export ADN_DEPLOY_REF="${ADN_DEPLOY_REF:-master}"
export GIT_URL_DEPLOY="${GIT_URL_DEPLOY:-https://github.com/ce5rpy/ADN-Install.git}"
export ADN_DEPLOY_STAGING="${ADN_DEPLOY_STAGING:-0}"
export ADN_DEPLOY_HOME="${ADN_ROOT}/ADN-Install"
export ADN_DEPLOY_BOOTSTRAP_ONLY="${ADN_DEPLOY_BOOTSTRAP_ONLY:-0}"
export ADN_DEPLOY_PROFILE="${ADN_DEPLOY_PROFILE:-full}"

_adn_deploy() {
  "$ADN_DEPLOY_HOME/sbin/adn-deploy" "$@"
}

# Block accidental prod install on reference host layout.
if [[ "$ADN_DEPLOY_STAGING" != "1" && "$ADN_ROOT" == "/opt" ]]; then
  if [[ -d /opt/new-adn-server ]] && systemctl is-active --quiet adn-server 2>/dev/null; then
    echo "install.sh: production stack detected under /opt." >&2
    echo "Use: ADN_DEPLOY_STAGING=1 ADN_ROOT=/opt/adn-staging bash install.sh" >&2
    exit 1
  fi
fi

adn_install_need_bootstrap=0
command -v curl >/dev/null 2>&1 || adn_install_need_bootstrap=1
command -v wget >/dev/null 2>&1 || adn_install_need_bootstrap=1
command -v git >/dev/null 2>&1 || adn_install_need_bootstrap=1
if [[ "$adn_install_need_bootstrap" -eq 1 ]]; then
  echo "install.sh: bootstrapping ca-certificates curl gnupg (+ git) ..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends ca-certificates curl gnupg
  if ! command -v git >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends git
  fi
fi

mkdir -p "$ADN_ROOT"
if [[ -d "$ADN_DEPLOY_HOME/.git" ]]; then
  echo "Updating $ADN_DEPLOY_HOME ..."
  if [[ -n "$ADN_DEPLOY_REF" ]]; then
    git -C "$ADN_DEPLOY_HOME" fetch --depth 1 origin "$ADN_DEPLOY_REF" 2>/dev/null || \
      git -C "$ADN_DEPLOY_HOME" pull --ff-only || true
  else
    git -C "$ADN_DEPLOY_HOME" fetch --depth 1 origin 2>/dev/null || \
      git -C "$ADN_DEPLOY_HOME" pull --ff-only || true
  fi
else
  if [[ -d "$ADN_DEPLOY_HOME" && ! -d "$ADN_DEPLOY_HOME/.git" ]]; then
    echo "Using existing toolkit at $ADN_DEPLOY_HOME (no clone)."
  else
    echo "Cloning ADN-Deploy -> $ADN_DEPLOY_HOME ..."
    if [[ -n "$ADN_DEPLOY_REF" ]]; then
      git clone --depth 1 -b "$ADN_DEPLOY_REF" "$GIT_URL_DEPLOY" "$ADN_DEPLOY_HOME"
    else
      git clone --depth 1 "$GIT_URL_DEPLOY" "$ADN_DEPLOY_HOME"
    fi
  fi
fi

_adn_sync_toolkit_ref() {
  local ref="${ADN_INSTALL_SHA:-${ADN_DEPLOY_REF:-}}"
  [[ -n "$ref" ]] || return 0
  [[ -d "$ADN_DEPLOY_HOME/.git" ]] || return 0
  echo "  toolkit: checkout ${ref} in ${ADN_DEPLOY_HOME}"
  git -C "$ADN_DEPLOY_HOME" fetch --depth 1 origin "$ref" 2>/dev/null || true
  git -C "$ADN_DEPLOY_HOME" checkout -f "$ref" 2>/dev/null || \
    git -C "$ADN_DEPLOY_HOME" checkout -f "origin/$ref" 2>/dev/null || true
}

_adn_sync_toolkit_ref

chmod +x "$ADN_DEPLOY_HOME/sbin/adn-deploy" "$ADN_DEPLOY_HOME/install.sh" \
  "$ADN_DEPLOY_HOME/install/scripts/bootstrap_os.sh" \
  "$ADN_DEPLOY_HOME/install/scripts/bootstrap_pyenv.sh" \
  "$ADN_DEPLOY_HOME/install/scripts/run_pyenv_bootstrap.sh" 2>/dev/null || true

# Always run the toolkit copy (post git pull) — curl|bash may start from an older cached script.
if [[ "${ADN_INSTALL_REEXECED:-0}" != "1" && -f "$ADN_DEPLOY_HOME/install/install.sh" ]]; then
  export ADN_INSTALL_REEXECED=1
  exec bash "$ADN_DEPLOY_HOME/install/install.sh" "$@"
fi

if [[ "$ADN_DEPLOY_STAGING" != "1" ]]; then
  install -d /usr/local/sbin
  ln -sf "$ADN_DEPLOY_HOME/sbin/adn-deploy" /usr/local/sbin/adn-deploy
  echo "Symlink: /usr/local/sbin/adn-deploy"
fi

if [[ "$ADN_DEPLOY_BOOTSTRAP_ONLY" == "1" ]]; then
  echo "Bootstrap only — toolkit ready at $ADN_DEPLOY_HOME"
  exit 0
fi

_adn_source_deploy_conf() {
  local conf="${ADN_DEPLOY_CONF:-$ADN_DEPLOY_HOME/deploy.conf}"
  [[ -f "$conf" && -r "$conf" ]] || return 0
  set -a
  # shellcheck disable=SC1090
  source "$conf"
  set +a
  export ADN_PYENV_ROOT="${ADN_PYENV_ROOT:-$ADN_ROOT/.pyenv}"
  export ADN_PYTHON_VERSION="${ADN_PYTHON_VERSION:-3.13.14}"
  export ADN_USER="${ADN_USER:-adn}"
  export ADN_USER_HOME="${ADN_USER_HOME:-/home/$ADN_USER}"
}

_adn_pyenv_python() {
  _adn_source_deploy_conf
  local py="${ADN_PYENV_PYTHON:-}"
  if [[ -z "$py" || ! -x "$py" ]]; then
    py="${ADN_PYENV_ROOT:-$ADN_ROOT/.pyenv}/versions/${ADN_PYTHON_VERSION:-3.13.14}/bin/python3"
  fi
  [[ -x "$py" ]] && printf '%s' "$py"
}

_adn_mandatory_incomplete() {
  local py
  py="$(_adn_pyenv_python)" || true
  if [[ -n "$py" ]]; then
    if ADN_DEPLOY_NON_INTERACTIVE=1 ADN_DEPLOY_HOME="$ADN_DEPLOY_HOME" "$py" -c \
      'from adn_deploy.application.config import mandatory_fields_incomplete, init_env; raise SystemExit(0 if mandatory_fields_incomplete(init_env()) else 1)'; then
      return 0
    fi
  fi
  local out
  out="$(ADN_DEPLOY_NON_INTERACTIVE=1 _adn_deploy doctor 2>&1)" || true
  grep -Fq 'mandatory config incomplete' <<<"$out"
}

_adn_log_mandatory_state() {
  local py
  py="$(_adn_pyenv_python)" || return 0
  ADN_DEPLOY_HOME="$ADN_DEPLOY_HOME" "$py" -c \
    'from adn_deploy.application.config import mandatory_missing_labels, init_env; m=mandatory_missing_labels(init_env()); print("  mandatory:", ", ".join(m) if m else "(none — looks complete)")' \
    2>/dev/null || true
}

_adn_wizard_needed() {
  local marker="$ADN_DEPLOY_HOME/.mandatory-setup-done"
  if [[ ! -f "$marker" ]]; then
    return 0
  fi
  _adn_mandatory_incomplete
}

_adn_tty_available() {
  [[ -t 0 && -t 1 ]] && return 0
  [[ -r /dev/tty && -w /dev/tty ]] && return 0
  return 1
}

_adn_pip_refresh_editable() {
  local py pip_bin
  py="$(_adn_pyenv_python)" || return 0
  pip_bin="${py%python3}pip"
  echo "  refresh: pip install -e $ADN_DEPLOY_HOME"
  if [[ -x "$pip_bin" ]]; then
    "$pip_bin" install -q -e "$ADN_DEPLOY_HOME" >/dev/null 2>&1 || true
  else
    "$py" -m pip install -q -e "$ADN_DEPLOY_HOME" >/dev/null 2>&1 || true
  fi
  if id "${ADN_USER:-adn}" &>/dev/null; then
    sudo -u "${ADN_USER:-adn}" env HOME="${ADN_USER_HOME:-/home/${ADN_USER:-adn}}" \
      "$py" -m pip install -q -e "$ADN_DEPLOY_HOME" >/dev/null 2>&1 || true
  fi
}

_adn_run_wizard() {
  local rc=0 wiz_cmd
  unset ADN_DEPLOY_NON_INTERACTIVE
  export TERM="${TERM:-xterm-256color}"
  export ADN_DEPLOY_INSTALL_WIZARD=1
  if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
    echo "  ERROR: no /dev/tty for wizard — use SSH and run: sudo adn-deploy wizard" >&2
    unset ADN_DEPLOY_INSTALL_WIZARD
    return 1
  fi
  wiz_cmd="$ADN_DEPLOY_HOME/sbin/adn-deploy wizard"
  echo "  launching: adn-deploy wizard (attached to /dev/tty)"
  if command -v script >/dev/null 2>&1; then
    script -q -e -c "$wiz_cmd" /dev/null </dev/tty >/dev/tty 2>&1 || rc=$?
  else
    ADN_DEPLOY_NON_INTERACTIVE=0 $wiz_cmd </dev/tty >/dev/tty 2>&1 || rc=$?
  fi
  unset ADN_DEPLOY_INSTALL_WIZARD
  stty sane </dev/tty 2>/dev/null || true
  return "$rc"
}

_adn_npm_build() {
  local fe="${ADN_MONITOR_PATH:-/opt/adn-monitor}/frontend"
  local user="${ADN_USER:-adn}" home="${ADN_USER_HOME:-/home/${ADN_USER:-adn}}"
  if [[ ! -d "$fe" ]]; then
    echo "  WARN: $fe missing — stack clone may have failed" >&2
    return 1
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "  WARN: npm not installed (os-base full profile)" >&2
    return 1
  fi
  chown -R "$user:$user" "$fe" 2>/dev/null || true
  echo "  npm build in $fe"
  ADN_DEPLOY_NON_INTERACTIVE=1 _adn_deploy web build || true
  if [[ -f "$fe/dist/index.html" ]]; then
    echo "  npm build: OK ($fe/dist)"
    return 0
  fi
  echo "  npm build: retry as $user (npm ci || npm install && npm run build)"
  if ! sudo -u "$user" env HOME="$home" TERM="${TERM:-xterm-256color}" \
      bash -lc "cd '$fe' && (npm ci || npm install) && npm run build"; then
    echo "  ERROR: npm build failed — check $fe/package.json" >&2
    return 1
  fi
  [[ -f "$fe/dist/index.html" ]]
}

export PATH="/usr/local/sbin:$PATH"
rm -rf "$ADN_DEPLOY_HOME/.venv" 2>/dev/null || true
rm -f /usr/local/bin/adn-deploy 2>/dev/null || true

echo ""
echo "=== ADN-Deploy install ==="
echo "  This script runs 5 phases automatically:"
echo "    [1] OS packages (apt, user adn, deploy.conf)"
echo "    [2] Python via pyenv at ${ADN_PYENV_ROOT:-$ADN_ROOT/.pyenv}"
echo "    [3] Stack (git clone, config, systemd, web)"
echo "    [4] Frontend build (npm)"
echo "    [5] Setup wizard — SERVER_ID, title, APRS, hostname"
echo "    [6] Nginx vhost + start services"
echo ""
echo "  During [5]: enter SERVER_ID (digits only), dashboard title, APRS callsign (D-APRS),"
echo "  then panel hostname. [4] builds the frontend; [6] renders nginx and starts units."
echo "  First run: allow ~15–30 minutes total (pyenv compiles Python)."
echo ""
echo "=== [1/6] OS packages (profile=$ADN_DEPLOY_PROFILE) ==="
# shellcheck disable=SC1091
source "$ADN_DEPLOY_HOME/install/scripts/bootstrap_os.sh"
_adn_source_deploy_conf

echo ""
echo "=== [2/6] Python — pyenv at ${ADN_PYENV_ROOT:-$ADN_ROOT/.pyenv} (~10–20 min first time) ==="
_adn_deploy pyenv || { echo "install.sh: pyenv failed" >&2; exit 1; }

echo ""
echo "=== [3/6] Stack — git, config, systemd, web ==="
ADN_DEPLOY_NON_INTERACTIVE=1 _adn_deploy stack --profile "$ADN_DEPLOY_PROFILE" --yes || { echo "install.sh: stack failed" >&2; exit 1; }

echo ""
echo "=== [4/6] Frontend build (npm) — before wizard ==="
_adn_npm_build || echo "  WARN: frontend build failed — finalize will retry" >&2

echo ""
echo "=== [5/6] Setup wizard ==="
_adn_pip_refresh_editable
if _adn_mandatory_incomplete && [[ -f "$ADN_DEPLOY_HOME/.mandatory-setup-done" ]]; then
  echo "  removing stale .mandatory-setup-done (config still incomplete)"
  rm -f "$ADN_DEPLOY_HOME/.mandatory-setup-done"
fi
wizard_ran_ok=0
if _adn_wizard_needed; then
  _adn_log_mandatory_state
  echo "  Complete all mandatory steps (SERVER_ID, title, hostname, APRS if shown)."
  if _adn_run_wizard && ! _adn_mandatory_incomplete; then
    wizard_ran_ok=1
  else
    echo "  WARN: setup wizard not finished" >&2
    _adn_log_mandatory_state
    if ! _adn_tty_available; then
      echo "  Tip: use SSH (not cron/nohup) and run: sudo adn-deploy wizard </dev/tty >/dev/tty" >&2
    fi
  fi
else
  echo "  Skipping wizard (.mandatory-setup-done present and config complete)."
  wizard_ran_ok=1
fi

echo ""
if _adn_mandatory_incomplete; then
  echo "=== [6/6] Nginx + services — skipped (wizard incomplete) ==="
  echo "  Finish: sudo adn-deploy wizard"
else
  echo "=== [6/6] Nginx vhost + services ==="
  ADN_DEPLOY_NON_INTERACTIVE=1 _adn_deploy finalize || {
    echo "  WARN: finalize failed — adn-deploy finalize" >&2
  }
fi

_adn_deploy doctor || true

if _adn_mandatory_incomplete; then
  echo ""
  echo "=== Setup wizard (final retry) ==="
  if _adn_run_wizard && ! _adn_mandatory_incomplete; then
    ADN_DEPLOY_NON_INTERACTIVE=1 _adn_deploy finalize || true
    _adn_npm_build || true
    _adn_deploy doctor || true
  fi
fi

echo ""
if _adn_mandatory_incomplete; then
  echo "=== INCOMPLETE — mandatory setup still required ==="
  echo "  Run: sudo adn-deploy wizard"
  echo "  (Use SSH with a real terminal; curl|bash needs an open session on /dev/tty)"
  exit 1
fi

echo ""
echo "=== install.sh complete ==="
echo "  Admin menu anytime: adn-deploy menu  (or adn-deploy wizard for setup only)"
echo "  If something looks wrong after apt upgrades: sudo reboot"
echo "  Then check: adn-deploy doctor && adn-deploy service status"
echo ""
