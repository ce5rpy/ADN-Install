#!/usr/bin/env bash
# Remove ADN production install under ADN_ROOT for a fresh adn-deploy install.
# Development source trees (/opt/new-adn-server, /opt/adn-monitor) are kept by default.
set -euo pipefail

ADN_ROOT="${ADN_ROOT:-/opt}"
ADN_PYENV_ROOT="${ADN_PYENV_ROOT:-$ADN_ROOT/.pyenv}"
ADN_SYSROOT="${ADN_SYSROOT:-/opt/test}"
CLEAN_TEST_SYSROOT="${CLEAN_TEST_SYSROOT:-1}"
CLEAN_LOGS="${CLEAN_LOGS:-1}"
CLEAN_DEV_SOURCES="${CLEAN_DEV_SOURCES:-0}"
CLEAN_MARIADB="${CLEAN_MARIADB:-1}"
CLEAN_MARIADB_PURGE="${CLEAN_MARIADB_PURGE:-1}"
# 1 = keep /opt/ADN-Install git tree; always wipe runtime state (deploy.conf, markers, .venv)
CLEAN_KEEP_ADN_DEPLOY="${CLEAN_KEEP_ADN_DEPLOY:-1}"
# 1 = remove adn user pyenv dir (~/.pyenv) and sudoers drop-in from install
CLEAN_USER_RUNTIME="${CLEAN_USER_RUNTIME:-1}"
ASSUME_YES="${CLEAN_ALL_YES:-0}"

MYSQL_DB_NAME="${MYSQL_DB_NAME:-hbmon}"
MYSQL_DB_USER="${MYSQL_DB_USER:-self_service_user}"
MYSQL_DB_PASSWORD="${MYSQL_DB_PASSWORD:-}"

UNITS=(adn-server adn-echo adn-monitor daprs)
SYSTEMCTL_STOP_TIMEOUT="${SYSTEMCTL_STOP_TIMEOUT:-30}"

die() { echo "clean-all: $*" >&2; exit 1; }

unit_exists() {
  systemctl list-unit-files "${1}.service" &>/dev/null 2>&1
}

[[ "${EUID:-0}" -eq 0 ]] || die "run as root (sudo bash $0)"

paths_to_remove() {
  printf '%s\n' \
    "$ADN_ROOT/adn-dmr-server" \
    "$ADN_ROOT/adn-monitor" \
    "$ADN_ROOT/D-APRS"
  if [[ "$CLEAN_KEEP_ADN_DEPLOY" != "1" ]]; then
    printf '%s\n' "$ADN_ROOT/ADN-Install"
  fi
  if [[ "$CLEAN_TEST_SYSROOT" == "1" && -d "$ADN_SYSROOT" && "$ADN_SYSROOT" != "/" ]]; then
    printf '%s\n' "$ADN_SYSROOT"
  fi
  if [[ "$CLEAN_DEV_SOURCES" == "1" ]]; then
    printf '%s\n' /opt/new-adn-server /opt/adn-monitor
  fi
}

show_plan() {
  echo "ADN clean-all plan:"
  echo "  1. stop/disable/mask systemd (first): ${UNITS[*]}"
  echo "     nginx: stop if ADN panel site is present"
  echo "  2. remove unit files: /etc/systemd/system/adn-*.service"
  echo "  3. remove nginx site: /etc/nginx/sites-enabled/adn-monitor (if present)"
  echo "  4. remove logrotate: /etc/logrotate.d/adn-server /etc/logrotate.d/adn-monitor (legacy, if present)"
  echo "  5. remove symlinks: /usr/local/sbin/adn-deploy /usr/local/bin/adn-deploy (if present)"
  if [[ "$CLEAN_USER_RUNTIME" == "1" ]]; then
    echo "  5b. remove install extras: /etc/sudoers.d/adn-deploy, ~adn/.pyenv"
  fi
  if [[ "$CLEAN_MARIADB" == "1" ]]; then
    echo "  6. MariaDB/MySQL: drop DB/user, stop/disable, optional purge"
  fi
  echo "  7. remove ALL deploy runtime state (flags, deploy.conf, markers, plugins, venv):"
  deploy_state_paths | sed 's/^/       /'
  echo "       (plus deploy.conf.* and .*-done under ADN-Install, except *.example templates)"
  echo "  8. remove pyenv (always, not skippable):"
  pyenv_paths_to_remove | sed 's/^/       /'
  if [[ "$CLEAN_KEEP_ADN_DEPLOY" == "1" ]]; then
    echo "  keep toolkit: $ADN_ROOT/ADN-Install (scripts only; config + app trees wiped)"
  fi
  echo "  9. remove bare-metal app trees:"
  paths_to_remove | sed 's/^/    /'
  if [[ "$CLEAN_LOGS" == "1" ]]; then
    echo "    /var/log/adn-server"
    echo "    /var/log/adn-monitor (legacy)"
    echo "    /var/log/adn-deploy (installer/pyenv logs)"
    echo "    */adn-monitor/monitor/log */adn-monitor/proxy/log (dev relative LOGGER paths)"
  fi
  if [[ "$CLEAN_DEV_SOURCES" != "1" ]]; then
    echo "  kept (dev sources): /opt/new-adn-server /opt/adn-monitor"
  fi
  if [[ "$CLEAN_MARIADB" == "1" && "$CLEAN_MARIADB_PURGE" == "1" ]]; then
    echo "     MariaDB purge: remove /var/lib/mysql (fresh apt install on next run)"
  fi
}

deploy_state_paths() {
  local toolkit="$ADN_ROOT/ADN-Install"
  printf '%s\n' \
    "$toolkit/deploy.conf" \
    "$toolkit/deploy.conf.local" \
    "$toolkit/.plugins-enabled" \
    "$toolkit/.mandatory-setup-done" \
    "$toolkit/.os-bootstrap-done" \
    "$toolkit/.venv" \
    "$toolkit/deploy.conf.reference.example"
}

remove_toolkit_runtime_globs() {
  local toolkit="$ADN_ROOT/ADN-Install"
  local f base
  [[ -d "$toolkit" ]] || return 0
  for f in "$toolkit"/deploy.conf.*; do
    [[ -e "$f" ]] || continue
    base="$(basename "$f")"
    [[ "$base" == deploy.conf.example ]] && continue
    [[ "$base" == deploy.conf.reference.example ]] && continue
    echo "  rm -f $f"
    rm -f "$f"
  done
  for f in "$toolkit"/.*-done; do
    [[ -e "$f" ]] || continue
    echo "  rm -f $f"
    rm -f "$f"
  done
  for f in "$toolkit"/.plugins-*; do
    [[ -e "$f" ]] || continue
    echo "  rm -f $f"
    rm -f "$f"
  done
}

remove_deploy_state() {
  local f
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    [[ -e "$f" ]] || continue
    echo "  rm -rf $f"
    rm -rf "$f"
  done < <(deploy_state_paths)
  remove_toolkit_runtime_globs
}

remove_user_install_extras() {
  [[ "$CLEAN_USER_RUNTIME" == "1" ]] || return 0
  local adn_home="${ADN_USER_HOME:-/home/adn}"
  if [[ -d "$adn_home/.pyenv" ]]; then
    echo "  rm -rf $adn_home/.pyenv"
    rm -rf "$adn_home/.pyenv"
  fi
  if [[ -f /etc/sudoers.d/adn-deploy ]]; then
    echo "  rm -f /etc/sudoers.d/adn-deploy"
    rm -f /etc/sudoers.d/adn-deploy
  fi
}

load_mysql_names_from_deploy_conf() {
  local conf="$ADN_ROOT/ADN-Install/deploy.conf"
  [[ -f "$conf" ]] || return 0
  # shellcheck disable=SC1090
  source "$conf" 2>/dev/null || true
  MYSQL_DB_NAME="${MYSQL_DB_NAME:-hbmon}"
  MYSQL_DB_USER="${MYSQL_DB_USER:-self_service_user}"
  MYSQL_DB_PASSWORD="${MYSQL_DB_PASSWORD:-}"
}

clean_mariadb() {
  [[ "$CLEAN_MARIADB" == "1" ]] || return 0
  load_mysql_names_from_deploy_conf

  local svc=""
  if systemctl list-unit-files mariadb.service &>/dev/null 2>&1; then
    svc=mariadb
  elif systemctl list-unit-files mysql.service &>/dev/null 2>&1; then
    svc=mysql
  fi

  if [[ -n "$svc" ]] && systemctl is-active --quiet "$svc" 2>/dev/null; then
    if command -v mysql >/dev/null 2>&1; then
      echo "  mysql: drop database ${MYSQL_DB_NAME} and user ${MYSQL_DB_USER}@localhost"
      mysql -e "DROP DATABASE IF EXISTS \`${MYSQL_DB_NAME}\`;" 2>/dev/null || true
      mysql -e "DROP USER IF EXISTS '${MYSQL_DB_USER}'@'localhost';" 2>/dev/null || true
      mysql -e "FLUSH PRIVILEGES;" 2>/dev/null || true
    fi
  fi

  systemctl stop mariadb mysql 2>/dev/null || true
  systemctl disable mariadb mysql 2>/dev/null || true

  if [[ "$CLEAN_MARIADB_PURGE" != "1" ]]; then
    return 0
  fi

  echo "  apt: purge MariaDB/MySQL server packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get purge -y \
    mariadb-server mariadb-server-core mariadb-client mariadb-common \
    mysql-server mysql-server-core mysql-client mysql-common \
    2>/dev/null || true
  apt-get autoremove -y 2>/dev/null || true
  echo "  rm -rf /var/lib/mysql /var/lib/mysql-files /etc/mysql"
  rm -rf /var/lib/mysql /var/lib/mysql-files /etc/mysql
}

stop_one_unit() {
  local u="$1"
  unit_exists "$u" || return 0
  systemctl unmask "$u.service" 2>/dev/null || true
  echo "  systemctl stop $u.service (timeout ${SYSTEMCTL_STOP_TIMEOUT}s)"
  timeout "$SYSTEMCTL_STOP_TIMEOUT" systemctl stop "$u.service" 2>/dev/null || true
  if systemctl is-active --quiet "$u.service" 2>/dev/null; then
    echo "  systemctl kill $u.service (still active after stop)"
    timeout "$SYSTEMCTL_STOP_TIMEOUT" systemctl kill "$u.service" 2>/dev/null || true
    timeout 5 systemctl stop "$u.service" 2>/dev/null || true
  fi
  systemctl disable "$u.service" 2>/dev/null || true
  systemctl mask "$u.service" 2>/dev/null || true
}

stop_nginx_if_adn_site() {
  [[ -f /etc/nginx/sites-enabled/adn-monitor || -f /etc/nginx/sites-available/adn-monitor ]] || return 0
  unit_exists nginx || return 0
  echo "  systemctl stop nginx.service (ADN panel site; timeout ${SYSTEMCTL_STOP_TIMEOUT}s)"
  timeout "$SYSTEMCTL_STOP_TIMEOUT" systemctl stop nginx.service 2>/dev/null || true
}

stop_services() {
  local u
  echo "clean-all: stopping ADN services (step 1)..."
  for u in "${UNITS[@]}"; do
    stop_one_unit "$u"
  done
  stop_nginx_if_adn_site
  systemctl daemon-reload 2>/dev/null || true
}

remove_system_files() {
  local u f
  for u in "${UNITS[@]}"; do
    f="/etc/systemd/system/${u}.service"
    systemctl unmask "$u.service" 2>/dev/null || true
    systemctl disable "$u.service" 2>/dev/null || true
    [[ -f "$f" ]] && rm -f "$f"
  done
  rm -f /etc/nginx/sites-enabled/adn-monitor /etc/nginx/sites-available/adn-monitor 2>/dev/null || true
  rm -f /etc/logrotate.d/adn-server /etc/logrotate.d/adn-monitor 2>/dev/null || true
  rm -f /usr/local/sbin/adn-deploy /usr/local/bin/adn-deploy 2>/dev/null || true
  systemctl daemon-reload 2>/dev/null || true
  command -v nginx >/dev/null 2>&1 && nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
}

# Always removed on every clean run (no env flag to skip).
pyenv_paths_to_remove() {
  printf '%s\n' \
    /opt/.pyenv \
    "$ADN_PYENV_ROOT" \
    "$ADN_ROOT/.pyenv" \
    "$ADN_SYSROOT/opt/.pyenv" \
    | awk 'NF && !seen[$0]++'
}

remove_pyenv() {
  local p
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    [[ -e "$p" || -L "$p" ]] || continue
    case "$p" in
      /|/opt|/usr|/etc|/var|/home) die "refusing to remove protected path: $p" ;;
    esac
    echo "  rm -rf $p"
    rm -rf "$p"
  done < <(pyenv_paths_to_remove)
}

remove_trees() {
  local p
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    [[ -e "$p" || -L "$p" ]] || continue
    case "$p" in
      /|/opt|/usr|/etc|/var|/home) die "refusing to remove protected path: $p" ;;
    esac
    echo "  rm -rf $p"
    rm -rf "$p"
  done < <(paths_to_remove | sort -u)
  if [[ "$CLEAN_LOGS" == "1" ]]; then
    if [[ -d /var/log/adn-server ]]; then
      echo "  rm -rf /var/log/adn-server"
      rm -rf /var/log/adn-server
    fi
    if [[ -d /var/log/adn-monitor ]]; then
      echo "  rm -rf /var/log/adn-monitor"
      rm -rf /var/log/adn-monitor
    fi
    if [[ -d /var/log/adn-deploy ]]; then
      echo "  rm -rf /var/log/adn-deploy"
      rm -rf /var/log/adn-deploy
    fi
  fi
  if [[ "$CLEAN_LOGS" == "1" ]]; then
    local logd
    for logd in \
      "$ADN_ROOT/adn-monitor/monitor/log" \
      "$ADN_ROOT/adn-monitor/proxy/log" \
      /opt/adn-monitor/monitor/log \
      /opt/adn-monitor/proxy/log; do
      [[ -d "$logd" ]] || continue
      echo "  rm -rf $logd"
      rm -rf "$logd"
    done
  fi
}

main() {
  show_plan
  if [[ "$ASSUME_YES" != "1" ]]; then
    echo
    read -r -p "Proceed? Type 'yes' to continue: " confirm
    [[ "$confirm" == "yes" ]] || die "aborted"
  fi
  # 1. Stop/disable/mask units before any rm -rf (prevents restart during clean).
  stop_services
  # 2–5. Drop systemd/nginx/logrotate/symlink definitions.
  remove_system_files
  # 6. MariaDB (after app services are down).
  clean_mariadb
  # 7. Deploy toolkit runtime state (all install flags / generated config).
  remove_deploy_state
  remove_user_install_extras
  # 8–9. pyenv and install trees/logs.
  remove_pyenv
  remove_trees
  echo "clean-all: done. Run a fresh install:"
  echo "  curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/develop/install.sh | sudo env ADN_DEPLOY_REF=develop bash"
}

main "$@"
