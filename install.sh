#!/usr/bin/env bash
# ADN bare-metal install entry point.
#
# Production (GitHub):
#   curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo bash
#
# Local checkout:
#   sudo bash install.sh
set -euo pipefail

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

if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  _here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$_here/install/install.sh" ]]; then
    exec bash "$_here/install/install.sh" "$@"
  fi
fi

if [[ "${EUID:-}" -ne 0 ]]; then
  echo "Run as root: curl -fsSL .../install.sh | sudo bash" >&2
  exit 1
fi

ADN_INSTALL_REPO="${ADN_INSTALL_REPO:-ce5rpy/ADN-Install}"
_install_ref="${ADN_INSTALL_REF:-${ADN_DEPLOY_REF:-master}}"
GITHUB_RAW="${GITHUB_RAW:-https://raw.githubusercontent.com/${ADN_INSTALL_REPO}/${_install_ref}}"
GITHUB_RAW="$(_adn_github_raw_resolve "$GITHUB_RAW")"
export ADN_INSTALL_SHA="${GITHUB_RAW##*/}"
_inst="$(mktemp -t adn-install.XXXXXX.sh)"
trap 'rm -f "$_inst"' EXIT
curl -fsSL --retry 2 -H 'Cache-Control: no-cache' "$GITHUB_RAW/install/install.sh" -o "$_inst"
chmod +x "$_inst"
export GITHUB_RAW
exec bash "$_inst" "$@"
