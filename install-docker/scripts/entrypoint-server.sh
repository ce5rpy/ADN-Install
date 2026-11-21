#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=install-docker/scripts/common.sh
source /usr/local/lib/adn-docker/common.sh

PEER_ROOT="${ADN_DMR_SERVER_PATH:-/opt/adn-dmr-server}"
MODE="${1:-server}"
shift || true
STATE_SERVER_YAML="$(adn_docker_peer_yaml)"
STATE_ECHO_YAML="$(adn_docker_echo_yaml)"
SERVER_YAML="$(adn_docker_materialize_yaml "$STATE_SERVER_YAML" "$PEER_ROOT/adn-server.yaml")"
ECHO_RUNTIME_YAML="$PEER_ROOT/adn-echo.yaml"

if [[ "${ADN_DOCKER_CLONE_ON_START:-0}" == "1" ]]; then
  adn_docker_git_clone "${GIT_URL_PEER:-https://github.com/Amateur-Digital-Network/ADN-DMR-Peer-Server.git}" \
    "$PEER_ROOT" "${GIT_BRANCH_PEER:-}"
fi

if [[ ! -f "$STATE_SERVER_YAML" && ! -f "$SERVER_YAML" ]]; then
  for ex in adn-server.example.yaml adn-server.yaml.example; do
    if [[ -f "$PEER_ROOT/$ex" ]]; then
      mkdir -p "$(dirname "$SERVER_YAML")"
      cp "$PEER_ROOT/$ex" "$SERVER_YAML"
      break
    fi
  done
fi
if [[ ! -f "$STATE_ECHO_YAML" && ! -f "$ECHO_RUNTIME_YAML" ]]; then
  for ex in adn-echo.example.yaml adn-echo.yaml.example adn-parrot.example.yaml adn-parrot.yaml.example; do
    if [[ -f "$PEER_ROOT/$ex" ]]; then
      mkdir -p "$(dirname "$ECHO_RUNTIME_YAML")"
      cp "$PEER_ROOT/$ex" "$ECHO_RUNTIME_YAML"
      break
    fi
  done
fi
ECHO_YAML="$(adn_docker_materialize_yaml "$(adn_docker_echo_yaml)" "$ECHO_RUNTIME_YAML")"

DB_HOST="${MYSQL_HOST:-mariadb}"
DB_PASS="${MYSQL_DB_PASSWORD:-${MARIADB_PASSWORD:-}}"
DB_NAME="${MYSQL_DB_NAME:-hbmon}"
DB_USER="${MYSQL_DB_USER:-self_service_user}"

adn_docker_patch_report_clients "$SERVER_YAML"
adn_docker_patch_database_credentials "$SERVER_YAML" "$DB_HOST" "$DB_NAME" "$DB_USER" "$DB_PASS"
adn_docker_patch_yaml_db "$SERVER_YAML" "$DB_HOST"
adn_docker_patch_mysql_password "$SERVER_YAML" "$DB_PASS"
adn_docker_patch_mysql_db_name "$SERVER_YAML" "$DB_NAME"
adn_docker_patch_system_udp_bind "$SERVER_YAML"
adn_docker_patch_system_udp_bind "$ECHO_YAML"
adn_docker_patch_parrot_master_ip "$ECHO_YAML" "${ADN_SERVER_HOST:-adn-server}"
adn_docker_patch_log_paths "$SERVER_YAML" "adn-server.log"
adn_docker_patch_log_paths "$ECHO_YAML" "adn-echo.log"
adn_docker_normalize_passphrases "$SERVER_YAML"
adn_docker_normalize_passphrases "$ECHO_YAML"
adn_docker_sync_echo_passphrase "$SERVER_YAML" "$ECHO_YAML"
SERVER_LOG_LEVEL="$(adn_docker_effective_log_level "$SERVER_YAML")"
ECHO_LOG_LEVEL="$(adn_docker_effective_log_level "$ECHO_YAML")"
mkdir -p /docker-state/logs 2>/dev/null || true

case "$MODE" in
  server)
    echo "  adn-server: starting ($SERVER_YAML, LOGGER.LOG_LEVEL=${SERVER_LOG_LEVEL})"
    exec python3 "$PEER_ROOT/adn-server.py" -c "$SERVER_YAML" "$@"
    ;;
  echo)
    local_cfg="$ECHO_YAML"
    if [[ ! -f "$local_cfg" ]]; then
      local_cfg="$(adn_docker_materialize_yaml "$(adn_docker_parrot_yaml)" "$PEER_ROOT/adn-parrot.yaml")"
      echo "  adn-echo: fallback adn-parrot.yaml ($local_cfg)" >&2
    fi
    echo "  adn-echo: starting ($local_cfg, LOGGER.LOG_LEVEL=${ECHO_LOG_LEVEL}, MASTER_IP=$(grep -E '^[[:space:]]*MASTER_IP:' "$local_cfg" 2>/dev/null | head -1 | sed 's/^[[:space:]]*//'))"
    exec python3 "$PEER_ROOT/adn-server.py" --echo -c "$local_cfg" "$@"
    ;;
  odtp)
    # ODTP gateway (adn-server >= 2.7): phone apps / IP terminals log in to the MASTER
    # on adn-server as HBP peers. Config: state/peer/adn-odtp.yaml (else the image example).
    ODTP_RUNTIME_YAML="$PEER_ROOT/adn-odtp.yaml"
    STATE_ODTP_YAML="${ADN_DOCKER_STATE:-/docker-state}/peer/adn-odtp.yaml"
    if [[ -f "$STATE_ODTP_YAML" ]]; then
      ODTP_YAML="$(adn_docker_materialize_yaml "$STATE_ODTP_YAML" "$ODTP_RUNTIME_YAML")"
    elif [[ -f "$PEER_ROOT/adn-odtp.example.yaml" ]]; then
      cp "$PEER_ROOT/adn-odtp.example.yaml" "$ODTP_RUNTIME_YAML"
      ODTP_YAML="$ODTP_RUNTIME_YAML"
    else
      echo "  adn-odtp: this adn-server image has no ODTP gateway (needs >= 2.7)" >&2
      exit 1
    fi
    # The MASTER is the adn-server container; the published host port is ADN_ODTP_PORT.
    adn_docker_patch_parrot_master_ip "$ODTP_YAML" "${ADN_SERVER_HOST:-adn-server}"
    adn_docker_yaml_set "$ODTP_YAML" "ODTP.LISTEN_IP" "0.0.0.0"
    adn_docker_yaml_set "$ODTP_YAML" "ODTP.LISTEN_PORT" "54006"
    adn_docker_patch_log_paths "$ODTP_YAML" "adn-odtp.log"
    # Callsigns for the RPTC (required: the MASTER has ALLOW_UNREG_ID: false).
    subs="$(adn_docker_yaml_get "$ODTP_YAML" "ODTP.SUBSCRIBERS_FILE")"
    subs="${subs:-subscriber_ids.json}"
    [[ "$subs" == /* ]] || subs="$PEER_ROOT/$subs"
    if [[ ! -s "$subs" ]]; then
      url="$(adn_docker_yaml_get "$SERVER_YAML" "ALIASES.SUBSCRIBER_URL")"
      url="${url:-https://servers.adn.systems/subscriber_ids.json}"
      echo "  adn-odtp: downloading subscriber IDs ($url)"
      python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$url" "$subs" \
        || echo "  adn-odtp: WARN subscriber IDs download failed — terminals get no callsign" >&2
    fi
    adn_docker_yaml_set "$ODTP_YAML" "ODTP.SUBSCRIBERS_FILE" "$subs"
    echo "  adn-odtp: starting ($ODTP_YAML, MASTER $(adn_docker_yaml_get "$ODTP_YAML" ODTP.MASTER_IP):$(adn_docker_yaml_get "$ODTP_YAML" ODTP.MASTER_PORT), UDP 54006)"
    cd "$PEER_ROOT"
    exec python3 "$PEER_ROOT/adn-server.py" --odtp -c "$ODTP_YAML" "$@"
    ;;
  *)
    echo "usage: entrypoint-server.sh <server|echo|odtp>" >&2
    exit 1
    ;;
esac
