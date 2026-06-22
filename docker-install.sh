#!/usr/bin/env bash
# ADN Docker install entry point.
#
# Production (GitHub — no toolkit clone):
#   curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
#
# Dev build (full repo checkout):
#   sudo ./docker-install.sh --dev
set -euo pipefail

install_dev=0
args=()
for arg in "$@"; do
  case "$arg" in
    --dev) install_dev=1 ;;
    *) args+=("$arg") ;;
  esac
done

_adn_github_raw_resolve() {
  local raw="${1:-}"
  [[ -n "$raw" ]] || return 0
  if [[ "$raw" =~ ^https://raw\.githubusercontent\.com/([^/]+/[^/]+)/([^/?#]+)$ ]]; then
    local repo="${BASH_REMATCH[1]}" ref="${BASH_REMATCH[2]}"
    if [[ "$ref" =~ ^[0-9a-f]{7,40}$ ]]; then
      printf '%s' "$raw"
      return 0
    fi
    local sha
    sha="$(curl -fsSL "https://api.github.com/repos/${repo}/commits/${ref}" \
      | sed -n 's/.*"sha"[[:space:]]*:[[:space:]]*"\([0-9a-f]\{40\}\)".*/\1/p' | head -1)"
    if [[ -n "$sha" ]]; then
      printf 'https://raw.githubusercontent.com/%s/%s' "$repo" "$sha"
      return 0
    fi
  fi
  printf '%s' "$raw"
}

_adn_fetch_curl_bundle() {
  local raw="$1" stage="$2" rel
  local -a files=(
    install-docker/scripts/install-standalone.sh
    install-docker/scripts/bootstrap-standalone.sh
    install-docker/scripts/materialize-standalone.sh
    install-docker/scripts/install-docker-debian.sh
    install-docker/lib/compose-env.sh
    install-docker/lib/docker-tag.sh
    install-docker/bin/adn-docker-standalone
    install-docker/compose/compose.registry.yml
    install-docker/compose/traefik/traefik.http.yml.in
    install-docker/compose/traefik/traefik.https.yml.in
    install-docker/compose/traefik/ssl.override.yml.in
  )
  for rel in "${files[@]}"; do
    mkdir -p "$stage/$(dirname "$rel")"
    curl -fsSL --retry 2 -H 'Cache-Control: no-cache' "$raw/$rel" -o "$stage/$rel"
  done
  chmod +x "$stage/install-docker/scripts/"*.sh "$stage/install-docker/bin/"* 2>/dev/null || true
}

# Local checkout (real file on disk — not curl | bash stdin)
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  _here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$_here/install-docker/scripts/install-standalone.sh" ]]; then
    if [[ "$install_dev" -eq 1 ]]; then
      if [[ -f "$_here/install-docker/docker-install.sh" ]]; then
        exec bash "$_here/install-docker/docker-install.sh" --dev "${args[@]}"
      fi
      echo "Dev install requires ADN-Deploy private repo checkout." >&2
      exit 1
    fi
    export ASSET_ROOT="$_here"
    exec bash "$_here/install-docker/scripts/install-standalone.sh" "${args[@]}"
  fi
fi

# curl | bash — download scripts to a temp tree (process substitution breaks BASH_SOURCE paths)
if [[ "${EUID:-}" -ne 0 ]]; then
  echo "Run as root: curl -fsSL .../docker-install.sh | sudo bash" >&2
  exit 1
fi
GITHUB_RAW="${GITHUB_RAW:-https://raw.githubusercontent.com/ce5rpy/ADN-Install/master}"
GITHUB_RAW="$(_adn_github_raw_resolve "$GITHUB_RAW")"
STAGE="$(mktemp -d -t adn-docker-install.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
_adn_fetch_curl_bundle "$GITHUB_RAW" "$STAGE"
export ASSET_ROOT="$STAGE"
export GITHUB_RAW
exec bash "$STAGE/install-docker/scripts/install-standalone.sh" "${args[@]}"
