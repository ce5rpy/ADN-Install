#!/usr/bin/env bash
# Pyenv bootstrap for ADN-Deploy (extracted from lib/os-bootstrap.sh).
# Called by adn_deploy.infra.os_bootstrap.bootstrap_pyenv with env vars set.
set -euo pipefail

: "${ADN_PYENV_ROOT:?ADN_PYENV_ROOT required}"
: "${ADN_PYTHON_VERSION:?ADN_PYTHON_VERSION required}"
: "${ADN_USER:?ADN_USER required}"
: "${ADN_DEPLOY_HOME:?ADN_DEPLOY_HOME required}"

ADN_PYENV_REINSTALL="${ADN_PYENV_REINSTALL:-0}"
ADN_DEPLOY_DRY_RUN="${ADN_DEPLOY_DRY_RUN:-0}"
ADN_DEPLOY_FILEGEN="${ADN_DEPLOY_FILEGEN:-0}"

_log() { echo "  pyenv: $*"; }
_dry() { [[ "$ADN_DEPLOY_DRY_RUN" == "1" && "$ADN_DEPLOY_FILEGEN" != "1" ]]; }

_adn_home() { printf '%s' "${ADN_USER_HOME:-/home/$ADN_USER}"; }

# sudo preserves the caller cwd; pyenv requires a readable PWD (often fails from /home/$SUDO_USER).
_adn_workdir() {
  local home wd
  home="$(_adn_home)"
  for wd in "$ADN_PYENV_ROOT" "$home" "/tmp"; do
    [[ -d "$wd" && -r "$wd" && -x "$wd" ]] && { printf '%s' "$wd"; return 0; }
  done
  printf '%s' "/tmp"
}

_run_as_adn() {
  local home wd
  home="$(_adn_home)"
  wd="$(_adn_workdir)"
  if _dry; then
    echo "[dry-run] sudo -u $ADN_USER env HOME=$home bash -c 'cd $(printf %q "$wd") && $*'"
    return 0
  fi
  sudo -u "$ADN_USER" env HOME="$home" bash -c "cd $(printf '%q' "$wd") && $*"
}

_pyenv_cmd_ok() { [[ -x "$ADN_PYENV_ROOT/bin/pyenv" ]]; }
_version_ok() {
  local ver="${1:-$ADN_PYTHON_VERSION}"
  [[ -x "$ADN_PYENV_ROOT/versions/$ver/bin/python3" ]]
}
_tree_empty() {
  [[ -d "$ADN_PYENV_ROOT" ]] || return 1
  [[ -z "$(find "$ADN_PYENV_ROOT" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]
}
_has_versions() {
  [[ -d "$ADN_PYENV_ROOT/versions" ]] && \
    [[ -n "$(find "$ADN_PYENV_ROOT/versions" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]
}
_tree_broken() {
  [[ -e "$ADN_PYENV_ROOT" ]] || return 1
  _tree_empty && return 0
  _pyenv_cmd_ok && return 1
  _has_versions && return 1
  return 0
}

_remove_tree() {
  local reason="$1"
  _log "removing $ADN_PYENV_ROOT ($reason)"
  if _dry; then echo "[dry-run] rm -rf $ADN_PYENV_ROOT"; return 0; fi
  rm -rf "$ADN_PYENV_ROOT"
}

_ensure_dirs() {
  if _dry; then echo "[dry-run] mkdir -p $ADN_PYENV_ROOT/{versions,shims}"; return 0; fi
  mkdir -p "$ADN_PYENV_ROOT/versions" "$ADN_PYENV_ROOT/shims"
}

_run_installer() {
  if _pyenv_cmd_ok; then
    _log "CLI present at $ADN_PYENV_ROOT/bin/pyenv"
    return 0
  fi
  if _dry; then
    echo "[dry-run] curl https://pyenv.run | bash (PYENV_ROOT=$ADN_PYENV_ROOT)"
    return 0
  fi
  _log "curl https://pyenv.run | bash (PYENV_ROOT=$ADN_PYENV_ROOT)"
  mkdir -p "$(dirname "$ADN_PYENV_ROOT")"
  chown "$ADN_USER:$ADN_USER" "$(dirname "$ADN_PYENV_ROOT")" 2>/dev/null || true
  if [[ -e "$ADN_PYENV_ROOT" ]] && ! _pyenv_cmd_ok; then
    _remove_tree "no pyenv CLI (re-run installer)"
  fi
  _run_as_adn \
    "export PYENV_ROOT=$(printf '%q' "$ADN_PYENV_ROOT"); export PATH=\"\$PYENV_ROOT/bin:\$PATH\"; curl -fsSL https://pyenv.run | bash" || {
    echo "ERROR: pyenv.run installer failed" >&2
    return 1
  }
  chown -R "$ADN_USER:$ADN_USER" "$ADN_PYENV_ROOT"
  _pyenv_cmd_ok || {
    echo "ERROR: pyenv.run finished but $ADN_PYENV_ROOT/bin/pyenv is missing" >&2
    return 1
  }
}

_shell_init() {
  printf 'export PYENV_ROOT=%q; export PATH="$PYENV_ROOT/bin:$PATH"; eval "$(pyenv init - bash)"' \
    "$ADN_PYENV_ROOT"
}

_ensure_install() {
  mkdir -p "$(dirname "$ADN_PYENV_ROOT")"
  if [[ "$ADN_PYENV_REINSTALL" == "1" && -e "$ADN_PYENV_ROOT" ]]; then
    _remove_tree "ADN_PYENV_REINSTALL=1"
  elif [[ -e "$ADN_PYENV_ROOT" ]]; then
    if _tree_broken; then
      _remove_tree "incomplete or empty install"
    elif _pyenv_cmd_ok || _version_ok; then
      _log "using existing install at $ADN_PYENV_ROOT"
    fi
  fi
  if _pyenv_cmd_ok || _version_ok; then
    _ensure_dirs
    return 0
  fi
  if [[ ! -e "$ADN_PYENV_ROOT" ]]; then
    _run_installer || return 1
    _ensure_dirs
    return 0
  fi
  if _has_versions; then
    echo "ERROR: $ADN_PYENV_ROOT has versions/ but no pyenv CLI" >&2
    return 1
  fi
  _remove_tree "incomplete install"
  _run_installer || return 1
  _ensure_dirs
}

_install_version() {
  local ver="${1:-$ADN_PYTHON_VERSION}"
  local log init rc=0
  if _version_ok "$ver"; then return 0; fi
  if _dry; then echo "[dry-run] pyenv install -s $ver"; return 0; fi
  if ! _pyenv_cmd_ok; then
    echo "ERROR: pyenv CLI missing" >&2
    return 1
  fi
  init="$(_shell_init)"
  log="/var/log/adn-deploy/pyenv-install-${ver}.log"
  mkdir -p "$(dirname "$log")"
  chown "$ADN_USER:$ADN_USER" "$(dirname "$log")" 2>/dev/null || true
  _log "pyenv install -s $ver (log: $log)..."
  _run_as_adn "${init}; pyenv install -s ${ver} 2>&1 | tee $(printf '%q' "$log")" || rc=$?
  chown -R "$ADN_USER:$ADN_USER" "$ADN_PYENV_ROOT/versions/$ver" 2>/dev/null || true
  if _version_ok "$ver"; then
    _log "installed $ver at $ADN_PYENV_ROOT/versions/$ver/bin/python3"
    return 0
  fi
  echo "ERROR: pyenv install failed for $ver (see $log)" >&2
  tail -40 "$log" 2>/dev/null >&2 || true
  return 1
}

_sync_shims() {
  local ver="${1:-$ADN_PYTHON_VERSION}"
  local py="$ADN_PYENV_ROOT/versions/$ver/bin/python3"
  if ! _version_ok "$ver"; then return 1; fi
  if _dry; then echo "[dry-run] pyenv shims -> $py"; return 0; fi
  _ensure_dirs
  ln -sfn "$py" "$ADN_PYENV_ROOT/shims/python3"
  ln -sfn "$py" "$ADN_PYENV_ROOT/shims/python"
  chown -h "$ADN_USER:$ADN_USER" \
    "$ADN_PYENV_ROOT/shims/python3" "$ADN_PYENV_ROOT/shims/python" 2>/dev/null || true
}

_set_global_version() {
  local ver="${1:-$ADN_PYTHON_VERSION}"
  if _dry; then echo "[dry-run] pyenv global $ver"; return 0; fi
  echo "$ver" >"$ADN_PYENV_ROOT/version"
  if [[ -n "${ADN_USER_HOME:-}" ]]; then
    mkdir -p "$ADN_USER_HOME/.pyenv"
    echo "$ver" >"$ADN_USER_HOME/.pyenv/version"
    chown "$ADN_USER:$ADN_USER" "$ADN_USER_HOME/.pyenv" "$ADN_USER_HOME/.pyenv/version" 2>/dev/null || true
  fi
  _log "pyenv global $ver"
}

_filegen_seed() {
  local ver="${1:-3.11.8}"
  local host_py="/opt/.pyenv/versions/$ver/bin/python3"
  [[ -x "$host_py" ]] || return 1
  _log "filegen shims -> host $host_py"
  mkdir -p "$ADN_PYENV_ROOT/shims" "$ADN_PYENV_ROOT/versions/$ver/bin"
  ln -sf "$host_py" "$ADN_PYENV_ROOT/shims/python3"
  ln -sf "$host_py" "$ADN_PYENV_ROOT/shims/python"
  ln -sf "$host_py" "$ADN_PYENV_ROOT/versions/$ver/bin/python3"
  export ADN_PYTHON_VERSION="$ver"
}

_m_pip() {
  local py="$ADN_PYENV_ROOT/versions/$ADN_PYTHON_VERSION/bin/python3"
  if ! [[ -x "$py" ]]; then
    py="$ADN_PYENV_ROOT/shims/python3"
  fi
  [[ -x "$py" ]] || { echo "ERROR: no python for pip" >&2; return 1; }
  if _dry; then echo "[dry-run] $py -m pip $*"; return 0; fi
  _run_as_adn "$(printf '%q' "$py") -m pip $(printf '%q ' "$@")"
}

_ensure_install || exit 1
if ! _dry; then
  chown -R "$ADN_USER:$ADN_USER" "$ADN_PYENV_ROOT"
  ver_dir="$ADN_PYENV_ROOT/versions/$ADN_PYTHON_VERSION"
  if [[ -d "$ver_dir" && ! -x "$ver_dir/bin/python3" ]]; then
    _log "removing incomplete install at $ver_dir"
    rm -rf "$ver_dir"
  fi
  if _version_ok; then
    _log "Python $ADN_PYTHON_VERSION already installed"
  elif ! _install_version "$ADN_PYTHON_VERSION"; then
    if [[ "$ADN_DEPLOY_FILEGEN" == "1" && "$ADN_PYTHON_VERSION" != "3.11.8" ]]; then
      ADN_PYTHON_VERSION=3.11.8
      _install_version 3.11.8 || _filegen_seed 3.11.8 || exit 1
    elif [[ "$ADN_DEPLOY_FILEGEN" == "1" ]]; then
      _filegen_seed 3.11.8 || exit 1
    else
      exit 1
    fi
  fi
  _sync_shims "$ADN_PYTHON_VERSION" || true
  _set_global_version "$ADN_PYTHON_VERSION" || true
  _log "upgrading pip/setuptools..."
  _m_pip install --upgrade pip setuptools || exit 1
fi

if [[ -f "$ADN_DEPLOY_HOME/pyproject.toml" ]]; then
  _m_pip install -e "$ADN_DEPLOY_HOME" || exit 1
fi

echo "  pyenv: bootstrap complete ($ADN_PYENV_ROOT/versions/$ADN_PYTHON_VERSION/bin/python3)"
