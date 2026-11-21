#!/usr/bin/env bash
# Shared helpers for ADN Docker entrypoints.
set -euo pipefail

adn_docker_wait_tcp() {
  local host="$1" port="$2" timeout="${3:-120}"
  local elapsed=0
  echo "  wait: $host:$port (timeout ${timeout}s) ..."
  while ! (echo >/dev/tcp/"$host"/"$port") 2>/dev/null; do
    sleep 2
    elapsed=$((elapsed + 2))
    if (( elapsed >= timeout )); then
      echo "  wait: timeout connecting to $host:$port" >&2
      return 1
    fi
  done
  echo "  wait: $host:$port is up"
}

adn_docker_test_mysql() {
  local host="$1" port="${2:-3306}"
  local user="${3:-${MYSQL_DB_USER:-self_service_user}}"
  local pass="${4:-${MYSQL_DB_PASSWORD:-${MARIADB_PASSWORD:-}}}"
  local db="${5:-${MYSQL_DB_NAME:-hbmon}}"
  [[ -n "$pass" ]] || return 1
  MYSQL_HOST="$host" MYSQL_PORT="$port" MYSQL_DB_USER="$user" \
    MYSQL_DB_PASSWORD="$pass" MYSQL_DB_NAME="$db" python3 -c "
import os, sys
try:
    import MySQLdb
    MySQLdb.connect(
        host=os.environ['MYSQL_HOST'],
        user=os.environ.get('MYSQL_DB_USER', 'self_service_user'),
        passwd=os.environ.get('MYSQL_DB_PASSWORD', ''),
        db=os.environ.get('MYSQL_DB_NAME', 'hbmon'),
        port=int(os.environ.get('MYSQL_PORT', '3306')),
    ).close()
except Exception:
    sys.exit(1)
" 2>/dev/null
}

adn_docker_mariadb_volume_name() {
  printf '%s' "${ADN_COMPOSE_PROJECT_NAME:-adn}_mariadb_data"
}

adn_docker_mariadb_volume_exists() {
  docker volume inspect "$(adn_docker_mariadb_volume_name)" >/dev/null 2>&1
}

# Prefer real MySQL login (avoids mariadb "Aborted connection … unauthenticated" from raw TCP probes).
adn_docker_wait_mysql() {
  local host="$1" port="${2:-3306}" timeout="${3:-180}"
  local user="${MYSQL_DB_USER:-self_service_user}"
  local pass="${MYSQL_DB_PASSWORD:-${MARIADB_PASSWORD:-}}"
  local db="${MYSQL_DB_NAME:-hbmon}"
  local elapsed=0
  local auth_hint=0
  echo "  wait: MySQL ${user}@${host}:${port}/${db} (timeout ${timeout}s) ..."
  while ! adn_docker_test_mysql "$host" "$port" "$user" "$pass" "$db"; do
    if (( auth_hint == 0 )) && adn_docker_mariadb_volume_exists; then
      if (echo >/dev/tcp/"$host"/"$port") 2>/dev/null; then
        echo "  wait: MariaDB is up but login failed — .env password may not match volume $(adn_docker_mariadb_volume_name)" >&2
        echo "  wait: fix: docker volume rm $(adn_docker_mariadb_volume_name)  (destroys DB) then adn-docker up" >&2
        auth_hint=1
      fi
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    if (( elapsed >= timeout )); then
      echo "  wait: timeout connecting to MySQL ${host}:${port}" >&2
      return 1
    fi
  done
  echo "  wait: MySQL ${host}:${port} is up (authenticated)"
}

adn_docker_wait_db() {
  local host="$1" port="${2:-3306}" timeout="${3:-180}"
  if [[ -n "${MYSQL_DB_PASSWORD:-${MARIADB_PASSWORD:-}}" ]]; then
    adn_docker_wait_mysql "$host" "$port" "$timeout"
  else
    adn_docker_wait_tcp "$host" "$port" "$timeout"
  fi
}

adn_docker_patch_yaml_db() {
  local file="$1" host="${2:-mariadb}"
  [[ -f "$file" ]] || return 0
  sed -i \
    -e "s/DB_SERVER:[[:space:]]*localhost/DB_SERVER: ${host}/" \
    -e "s/DB_SERVER:[[:space:]]*127\\.0\\.0\\.1/DB_SERVER: ${host}/" \
    "$file" 2>/dev/null || true
}

adn_docker_patch_mysql_password() {
  local file="$1" pass="${2:-}"
  [[ -f "$file" && -n "$pass" ]] || return 0
  pass="${pass//\\/\\\\}"
  pass="${pass//\"/\\\"}"
  sed -i "s/DB_PASSWORD:.*/DB_PASSWORD: \"${pass}\"/" "$file" 2>/dev/null || true
}

adn_docker_patch_adn_ip() {
  local file="$1" ip="${2:-adn-server}"
  [[ -f "$file" && -n "$ip" ]] || return 0
  sed -i \
    -e "s/ADN_IP:[[:space:]]*\"127\\.0\\.0\\.1\"/ADN_IP: \"${ip}\"/" \
    -e "s/ADN_IP:[[:space:]]*127\\.0\\.0\\.1/ADN_IP: \"${ip}\"/" \
    "$file" 2>/dev/null || true
}

# Docker: ensure MONITOR_APP.TRUSTED_PROXY_IPS covers the Docker bridge subnet
# so login-by-ip resolves the real client IP behind Traefik.
adn_docker_patch_trusted_proxies() {
  local file="$1"
  local proxies="${ADN_TRUSTED_PROXY_IPS:-127.0.0.1,::1,172.16.0.0/12}"
  [[ -f "$file" ]] || return 0
  python3 - "$file" "$proxies" <<'PYEOF' 2>/dev/null || true
import re, sys
path, proxies = sys.argv[1], sys.argv[2]
lines = open(path, encoding="utf-8").read().splitlines()
out = []
in_block = False
active_seen = False
for ln in lines:
    if re.match(r"^MONITOR_APP:\s*$", ln):
        in_block = True
    elif in_block and re.match(r"^[A-Z]", ln):
        in_block = False
    if in_block:
        m = re.match(r"^(\s*)(#?)\s*TRUSTED_PROXY_IPS:\s*(.*)$", ln)
        if m:
            indent, commented, _ = m.groups()
            if commented:
                out.append(f'{indent}TRUSTED_PROXY_IPS: "{proxies}"')
            else:
                active_seen = True
                out.append(ln)
            continue
    out.append(ln)
if not active_seen and not any(re.match(r"^\s*TRUSTED_PROXY_IPS:", l) for l in out):
    for i, ln in enumerate(out):
        if ln.startswith("MONITOR_APP:"):
            out.insert(i + 1, f'  TRUSTED_PROXY_IPS: "{proxies}"')
            break
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PYEOF
}

adn_docker_seed_monitor_yaml() {
  local mon_root="$1" dest="$2"
  for ex in adn-monitor.yaml.example adn-monitor.example.yaml; do
    if [[ -f "$mon_root/monitor/$ex" ]]; then
      mkdir -p "$(dirname "$dest")"
      cp "$mon_root/monitor/$ex" "$dest"
      return 0
    fi
  done
  echo "  docker: missing monitor example yaml under $mon_root/monitor" >&2
  return 1
}

# Empty/truncated YAML (common after failed copy) makes monitor.py exit immediately.
adn_docker_monitor_yaml_valid() {
  local file="$1"
  [[ -f "$file" && -s "$file" ]] || return 1
  python3 -c "
import sys
try:
    import yaml
except ImportError:
    print('  docker: PyYAML missing — cannot validate YAML', file=sys.stderr)
    sys.exit(1)
from pathlib import Path
p = Path(sys.argv[1])
try:
    data = yaml.safe_load(p.read_text(encoding='utf-8'))
except Exception as e:
    print(f'  docker: YAML parse error in {p}: {e}', file=sys.stderr)
    sys.exit(1)
if not isinstance(data, dict) or not data:
    print(f'  docker: YAML root must be a non-empty mapping: {p}', file=sys.stderr)
    sys.exit(1)
" "$file"
}

adn_docker_repair_monitor_yaml() {
  local mon_root="$1" dest="$2"
  echo "  monitor: repairing invalid YAML: $dest" >&2
  adn_docker_seed_monitor_yaml "$mon_root" "$dest"
}

adn_docker_ensure_monitor_yaml() {
  local mon_root="$1" dest="$2"
  if adn_docker_monitor_yaml_valid "$dest"; then
    return 0
  fi
  adn_docker_repair_monitor_yaml "$mon_root" "$dest"
}

adn_docker_patch_mysql_db_name() {
  local file="$1" db="${2:-hbmon}"
  [[ -f "$file" && -n "$db" ]] || return 0
  sed -i "s/DB_NAME:.*/DB_NAME: ${db}/" "$file" 2>/dev/null || true
}

# Safe scalar updates (passwords/special chars) — requires adn_deploy in the image.
adn_docker_yaml_set() {
  local file="$1" key="$2" val="${3:-}"
  [[ -f "$file" ]] || return 0
  python3 -m adn_deploy.infra.yaml_store set --config "$file" --key "$key" --value "$val" >/dev/null 2>&1 || true
}

adn_docker_yaml_get() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  python3 -m adn_deploy.infra.yaml_store get --config "$file" --key "$key" 2>/dev/null || true
}

# Optional compose/.env override — patches yaml when the runtime copy is writable.
adn_docker_apply_log_level_env() {
  local file="$1"
  [[ -f "$file" && -w "$file" && -n "${ADN_LOG_LEVEL:-}" ]] || return 0
  adn_docker_yaml_set "$file" "LOGGER.LOG_LEVEL" "$ADN_LOG_LEVEL"
}

adn_docker_effective_log_level() {
  local file="$1" level
  adn_docker_apply_log_level_env "$file"
  level="$(adn_docker_yaml_get "$file" "LOGGER.LOG_LEVEL")"
  printf '%s' "${level:-INFO}"
}

adn_docker_patch_self_service_db() {
  local file="$1" host="${2:-mariadb}" db="${3:-hbmon}" pass="${4:-}"
  local user="${5:-${MYSQL_DB_USER:-self_service_user}}"
  [[ -f "$file" ]] || return 0
  adn_docker_yaml_set "$file" "SELF_SERVICE.DB_SERVER" "$host"
  adn_docker_yaml_set "$file" "SELF_SERVICE.DB_NAME" "$db"
  adn_docker_yaml_set "$file" "SELF_SERVICE.DB_USERNAME" "$user"
  adn_docker_yaml_set "$file" "SELF_SERVICE.DB_PORT" "3306"
  if [[ -n "$pass" ]]; then
    adn_docker_yaml_set "$file" "SELF_SERVICE.DB_PASSWORD" "$pass"
  fi
}

# adn-server.yaml uses DATABASE.* (not top-level DB_*).
adn_docker_patch_database_credentials() {
  local file="$1" host="${2:-mariadb}" db="${3:-hbmon}" user="${4:-${MYSQL_DB_USER:-self_service_user}}" pass="${5:-}"
  [[ -f "$file" ]] || return 0
  adn_docker_yaml_set "$file" "DATABASE.DB_SERVER" "$host"
  adn_docker_yaml_set "$file" "DATABASE.DB_NAME" "$db"
  adn_docker_yaml_set "$file" "DATABASE.DB_USERNAME" "$user"
  adn_docker_yaml_set "$file" "DATABASE.DB_PORT" "3306"
  if [[ -n "$pass" ]]; then
    adn_docker_yaml_set "$file" "DATABASE.DB_PASSWORD" "$pass"
  fi
}

adn_docker_normalize_passphrases() {
  local file="$1" pass="${2:-${HBP_PASSPHRASE:-passw0rd}}"
  [[ -f "$file" && -n "$pass" ]] || return 0
  python3 -m adn_deploy.infra.yaml_store normalize-passphrases --config "$file" --value "$pass" >/dev/null 2>&1 || true
}

adn_docker_sync_echo_passphrase() {
  local server="$1" echo="$2"
  [[ -f "$server" && -f "$echo" ]] || return 0
  python3 -m adn_deploy.infra.yaml_store sync-echo-passphrase --server "$server" --echo "$echo" >/dev/null 2>&1 || true
}
adn_docker_db_bootstrap_if_needed() {
  local mon_yaml="$1"
  local mon_root="${ADN_MONITOR_PATH:-/opt/adn-monitor}"
  local state="${ADN_DOCKER_STATE:-/docker-state}"
  local marker="$state/.db-bootstrap-done"
  [[ -f "$mon_yaml" ]] || return 1
  if [[ -f "$marker" ]]; then
    echo "  monitor: db bootstrap already done"
    return 0
  fi
  echo "  monitor: db_bootstrap (first run)"
  cd "$mon_root/monitor"
  python3 db_bootstrap.py --config "$mon_yaml" --create
  mkdir -p "$state"
  date -Iseconds >"$marker"
}

adn_docker_git_clone() {
  local url="$1" dest="$2" ref="${3:-}"
  if [[ -d "$dest/.git" ]] || [[ -f "$dest/adn-server.py" ]] || [[ -f "$dest/monitor/monitor.py" ]]; then
    echo "  git: using existing tree at $dest"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  if [[ -n "$ref" ]]; then
    git clone --depth 1 -b "$ref" "$url" "$dest"
  else
    git clone --depth 1 "$url" "$dest"
  fi
}

# Config paths: prefer /docker-state bind mounts (written by monitor-core / setup wizard).
adn_docker_peer_yaml() {
  local state="${ADN_DOCKER_STATE:-}" root="${ADN_DMR_SERVER_PATH:-/opt/adn-dmr-server}"
  if [[ -n "$state" && -f "$state/peer/adn-server.yaml" ]]; then
    printf '%s' "$state/peer/adn-server.yaml"
  else
    printf '%s' "$root/adn-server.yaml"
  fi
}

adn_docker_echo_yaml() {
  local state="${ADN_DOCKER_STATE:-}" root="${ADN_DMR_SERVER_PATH:-/opt/adn-dmr-server}"
  if [[ -n "$state" && -f "$state/peer/adn-echo.yaml" ]]; then
    printf '%s' "$state/peer/adn-echo.yaml"
  elif [[ -n "$state" && -f "$state/peer/adn-parrot.yaml" ]]; then
    printf '%s' "$state/peer/adn-parrot.yaml"
  elif [[ -f "$root/adn-echo.yaml" ]]; then
    printf '%s' "$root/adn-echo.yaml"
  else
    printf '%s' "$root/adn-parrot.yaml"
  fi
}

# Legacy alias — prefer adn_docker_echo_yaml().
adn_docker_parrot_yaml() {
  adn_docker_echo_yaml
}

adn_docker_monitor_yaml() {
  local state="${ADN_DOCKER_STATE:-}" root="${ADN_MONITOR_PATH:-/opt/adn-monitor}"
  if [[ -n "$state" && -f "$state/monitor/monitor/adn-monitor.yaml" ]]; then
    printf '%s' "$state/monitor/monitor/adn-monitor.yaml"
  else
    printf '%s' "$root/monitor/adn-monitor.yaml"
  fi
}

# Docker: bind HBP/MASTER UDP on all interfaces (127.0.0.1 rejects proxy from another container).
adn_docker_patch_system_udp_bind() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  sed -i \
    -e 's/^\([[:space:]]*IP:\)[[:space:]]*"127\.0\.0\.1"/\1 ""/' \
    -e 's/^\([[:space:]]*IP:\)[[:space:]]*127\.0\.0\.1/\1 ""/' \
    "$file" 2>/dev/null || true
}

# Parrot runs in its own container; 127.0.0.1 points at itself, not adn-server ECHO master.
adn_docker_patch_parrot_master_ip() {
  local file="$1" master="${2:-${ADN_SERVER_HOST:-adn-server}}"
  [[ -f "$file" && -n "$master" ]] || return 0
  sed -i \
    -e "s/^\([[:space:]]*MASTER_IP:\)[[:space:]]*\"127\\.0\\.0\\.1\"/\1 \"${master}\"/" \
    -e "s/^\([[:space:]]*MASTER_IP:\)[[:space:]]*127\\.0\\.0\\.1/\1 \"${master}\"/" \
    "$file" 2>/dev/null || true
}

# monitor-core connects from the Docker network; default 127.0.0.1 rejects the client.
adn_docker_patch_report_clients() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  if grep -qE 'REPORT_CLIENTS:[[:space:]]*"\*"' "$file" 2>/dev/null \
      || grep -qE 'REPORT_CLIENTS:[[:space:]]*\*' "$file" 2>/dev/null; then
    :
  else
    sed -i \
      -e 's/REPORT_CLIENTS:[[:space:]]*"127\.0\.0\.1"/REPORT_CLIENTS: "*"/' \
      -e 's/REPORT_CLIENTS:[[:space:]]*127\.0\.0\.1/REPORT_CLIENTS: "*"/' \
      "$file" 2>/dev/null || true
  fi
  sed -i \
    -e 's/REPORT:[[:space:]]*false/REPORT: true/' \
    "$file" 2>/dev/null || true
}

# Shared state YAML uses container paths (/docker-state/...) — same file is bind-mounted in services.
adn_docker_patch_log_paths() {
  local file="$1" log_name="${2:-adn-server.log}"
  [[ -f "$file" ]] || return 0
  sed -i \
    -e "s|LOG_FILE:[[:space:]]*.*|LOG_FILE: \"/docker-state/logs/${log_name}\"|" \
    -e 's|LOG_PATH:[[:space:]]*.*|LOG_PATH: "/docker-state/logs"|' \
    -e 's|LOG_HANDLERS:[[:space:]]*.*|LOG_HANDLERS: console-timed,file-timed|' \
    "$file" 2>/dev/null || true
}

# Monitor LOGGER uses LOG_FILE (not PROXY_LOG_FILE). Writable path inside the container.
adn_docker_patch_monitor_log_paths() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  sed -i \
    -e 's|LOG_PATH:[[:space:]]*.*|LOG_PATH: "/opt/adn-monitor/monitor/log"|' \
    "$file" 2>/dev/null || true
}

# Resolve monitor YAML: docker-state (source of truth) -> runtime copy under /opt (writable).
adn_docker_resolve_monitor_yaml() {
  local mon_root="${1:-/opt/adn-monitor}"
  local state_yaml runtime_yaml
  runtime_yaml="$mon_root/monitor/adn-monitor.yaml"
  state_yaml="$(adn_docker_monitor_yaml)"
  if [[ -f "$state_yaml" ]]; then
    if adn_docker_monitor_yaml_valid "$state_yaml"; then
      adn_docker_materialize_yaml "$state_yaml" "$runtime_yaml"
    else
      echo "  monitor: invalid docker-state YAML (using example): $state_yaml" >&2
      adn_docker_ensure_monitor_yaml "$mon_root" "$runtime_yaml" || return 1
      printf '%s' "$runtime_yaml"
    fi
  elif [[ -f "$runtime_yaml" ]]; then
    adn_docker_ensure_monitor_yaml "$mon_root" "$runtime_yaml" || return 1
    printf '%s' "$runtime_yaml"
  else
    adn_docker_ensure_monitor_yaml "$mon_root" "$runtime_yaml" || return 1
    printf '%s' "$runtime_yaml"
  fi
}

# monitor-core reads/writes docker-state directly (rw mount); fall back to seed under /opt.
adn_docker_resolve_monitor_yaml_ws() {
  local mon_root="${1:-/opt/adn-monitor}"
  local state="${ADN_DOCKER_STATE:-}" yaml
  if [[ -n "$state" ]]; then
    yaml="$state/monitor/monitor/adn-monitor.yaml"
    mkdir -p "$(dirname "$yaml")"
    adn_docker_ensure_monitor_yaml "$mon_root" "$yaml" || return 1
    printf '%s' "$yaml"
    return 0
  fi
  yaml="$(adn_docker_monitor_yaml)"
  if [[ -f "$yaml" ]]; then
    adn_docker_ensure_monitor_yaml "$mon_root" "$yaml" || return 1
    printf '%s' "$yaml"
  else
    yaml="$mon_root/monitor/adn-monitor.yaml"
    adn_docker_ensure_monitor_yaml "$mon_root" "$yaml" || return 1
    printf '%s' "$yaml"
  fi
}

# /docker-state is often :ro; copy config to a writable runtime path before patching.
adn_docker_materialize_yaml() {
  local src="$1" dest="$2"
  if [[ "$src" == /docker-state/* && "$src" != "$dest" ]]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
    printf '%s' "$dest"
  else
    printf '%s' "$src"
  fi
}

# PHP backend (and Dotenv) expect ADN_CONFIG_PATH in project root .env — same as bare-metal.
adn_docker_write_config_env() {
  local mon_root="$1" yaml="$2"
  printf 'ADN_CONFIG_PATH=%s\n' "$yaml" >"$mon_root/.env"
  printf 'ADN_CONFIG_PATH=%s\n' "$yaml" >"$mon_root/backend/.env"
}
