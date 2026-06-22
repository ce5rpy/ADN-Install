#!/usr/bin/env bash
# Create /opt/adn-docker from registry assets (no full repo clone).
set -euo pipefail

SERVER_ROOT="${ADN_SERVER_ROOT:-/opt/adn-docker}"
GITHUB_RAW="${GITHUB_RAW:-https://raw.githubusercontent.com/ce5rpy/ADN-Install/master}"
ASSET_ROOT="${ASSET_ROOT:-}"

adn_standalone_asset() {
  local rel="$1"
  if [[ -n "$ASSET_ROOT" && -f "$ASSET_ROOT/$rel" ]]; then
    printf '%s' "$ASSET_ROOT/$rel"
    return 0
  fi
  printf '%s/%s' "$GITHUB_RAW" "$rel"
}

adn_standalone_fetch() {
  local rel="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [[ -n "$ASSET_ROOT" && -f "$ASSET_ROOT/$rel" ]]; then
    install -m 644 "$ASSET_ROOT/$rel" "$dest"
  else
    curl -fsSL "$(adn_standalone_asset "$rel")" -o "$dest"
  fi
}

mkdir -p \
  "$SERVER_ROOT/state/peer" \
  "$SERVER_ROOT/state/monitor/monitor" \
  "$SERVER_ROOT/state/daprs" \
  "$SERVER_ROOT/state/traefik/templates"
chmod 700 "$SERVER_ROOT/state" 2>/dev/null || true

adn_standalone_fetch install-docker/compose/compose.registry.yml "$SERVER_ROOT/docker-compose.yml"

for tpl in traefik.http.yml.in traefik.https.yml.in ssl.override.yml.in; do
  adn_standalone_fetch "install-docker/compose/traefik/$tpl" "$SERVER_ROOT/state/traefik/templates/$tpl"
done

cat >"$SERVER_ROOT/.adn-docker-root" <<EOF
# ADN Docker runtime — sourced by /usr/local/sbin/adn-docker
ADN_DOCKER_ROOT="${SERVER_ROOT}"
ADN_SERVER_ROOT="${SERVER_ROOT}"
ADN_DEPLOY_MODE=registry
EOF

echo "  materialize: $SERVER_ROOT/docker-compose.yml (registry)"
echo "  materialize: $SERVER_ROOT/state/traefik/templates/ (Traefik templates for ssl enable)"
