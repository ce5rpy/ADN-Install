#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=install-docker/scripts/common.sh
source /usr/local/lib/adn-docker/common.sh

MON_ROOT="${ADN_MONITOR_PATH:-/opt/adn-monitor}"
MON_YAML="$(adn_docker_resolve_monitor_yaml_ws "$MON_ROOT")"
MODE="${1:-monitor}"
shift || true

DB_HOST="${MYSQL_HOST:-mariadb}"
DB_PORT="${MYSQL_PORT:-3306}"
DB_PASS="${MYSQL_DB_PASSWORD:-${MARIADB_PASSWORD:-}}"
APP_PORT="${MONITOR_APP_PORT:-8080}"

if [[ "${ADN_DOCKER_CLONE_ON_START:-0}" == "1" ]]; then
  adn_docker_git_clone "${GIT_URL_MONITOR:-https://github.com/Amateur-Digital-Network/ADN-Monitor.git}" \
    "$MON_ROOT" "${GIT_BRANCH_MONITOR:-}"
fi

if [[ ! -f "$MON_YAML" ]]; then
  adn_docker_seed_monitor_yaml "$MON_ROOT" "$MON_YAML" || exit 1
fi

python3 -c "from adn_deploy.application.config import init_monitor; init_monitor()" 2>/dev/null || true

adn_docker_patch_self_service_db "$MON_YAML" "$DB_HOST" "${MYSQL_DB_NAME:-hbmon}" "$DB_PASS" "${MYSQL_DB_USER:-self_service_user}"
adn_docker_patch_yaml_db "$MON_YAML" "$DB_HOST"
adn_docker_patch_mysql_password "$MON_YAML" "$DB_PASS"
adn_docker_patch_mysql_db_name "$MON_YAML" "${MYSQL_DB_NAME:-hbmon}"
adn_docker_patch_adn_ip "$MON_YAML" "${ADN_SERVER_HOST:-adn-server}"
adn_docker_patch_trusted_proxies "$MON_YAML"
adn_docker_patch_monitor_log_paths "$MON_YAML"
MON_LOG_LEVEL="$(adn_docker_effective_log_level "$MON_YAML")"
mkdir -p "$MON_ROOT/monitor/log"
export ADN_CONFIG_PATH="$MON_YAML"
export MONITOR_APP_PORT="$APP_PORT"

case "$MODE" in
  bootstrap)
    adn_docker_wait_db "$DB_HOST" "$DB_PORT" "${MYSQL_WAIT_TIMEOUT:-180}"
    echo "  monitor: db_bootstrap"
    cd "$MON_ROOT/monitor"
    exec python3 db_bootstrap.py --config "$MON_YAML" --create
    ;;
  monitor)
    adn_docker_wait_db "$DB_HOST" "$DB_PORT" "${MYSQL_WAIT_TIMEOUT:-180}"
    adn_docker_db_bootstrap_if_needed "$MON_YAML"
    echo "  monitor: starting FastAPI :${APP_PORT} + SPA (config=$MON_YAML, LOGGER.LOG_LEVEL=${MON_LOG_LEVEL})"
    exec python3 /usr/local/lib/adn-docker/run-monitor.py --config "$MON_YAML" "$@"
    ;;
  *)
    echo "usage: entrypoint-monitor.sh <bootstrap|monitor>" >&2
    exit 1
    ;;
esac
