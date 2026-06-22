#!/usr/bin/env bash
# Per-component Docker tags from latest release tags on each upstream repo.
# shellcheck shell=bash

# Normalize v2.0.0-rc.6 -> 2.0.0-rc.6
adn_version_normalize() {
  local v="${1#v}"
  v="${v#V}"
  printf '%s' "$v"
}

# Semver tag (optional v prefix; optional -alpha.N / -beta.N / -rc.N).
adn_version_is_semver_tag() {
  local v
  v="$(adn_version_normalize "$1")"
  [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta)(\.[0-9]+)?|-rc\.[0-9]+)?$ ]]
}

adn_version_from_ref() {
  local ref="$1"
  [[ -n "$ref" ]] || return 1
  if adn_version_is_semver_tag "$ref"; then
    adn_version_normalize "$ref"
    return 0
  fi
  return 1
}

adn_version_git_ref() {
  local ver
  ver="$(adn_version_normalize "$1")"
  printf 'v%s' "$ver"
}

adn_release_channel_matches() {
  local ver="$1" channel="$2"
  ver="$(adn_version_normalize "$ver")"
  case "$channel" in
    alpha) [[ "$ver" =~ -alpha(\.[0-9]+)?$ ]] ;;
    beta) [[ "$ver" =~ -beta(\.[0-9]+)?$ ]] ;;
    rc) [[ "$ver" =~ -rc\.[0-9]+$ ]] ;;
    final|stable)
      [[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
      ;;
    auto|release|latest|*)
      adn_version_is_semver_tag "$ver"
      ;;
  esac
}

adn_git_list_tags() {
  local url="$1"
  [[ -n "$url" ]] || return 1
  git ls-remote --tags "$url" 2>/dev/null \
    | sed -n 's|.*refs/tags/||p' \
    | grep -v '\^{}$' || true
}

adn_git_url_to_github_slug() {
  local url="$1"
  if [[ "$url" =~ github\.com[:/]([^/]+)/([^/.]+)(\.git)? ]]; then
    printf '%s/%s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return 0
  fi
  return 1
}

# GitHub /releases/latest — same as the "Latest" release in the UI (non-prerelease).
adn_github_latest_release_tag() {
  local slug="$1" json tag
  command -v curl >/dev/null 2>&1 || return 1
  json="$(curl -fsS --max-time 20 \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: ADN-Deploy-resolve' \
    "https://api.github.com/repos/${slug}/releases/latest" 2>/dev/null)" || return 1
  tag="$(printf '%s' "$json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
  [[ -n "$tag" ]] || return 1
  adn_version_normalize "$tag"
}

# Latest release tag on remote. Optional channel filter.
adn_git_latest_tag_for_channel() {
  local url="$1" channel="${2:-auto}"
  local slug ver

  if [[ "$channel" == "auto" || "$channel" == "release" || "$channel" == "latest" ]]; then
    if slug="$(adn_git_url_to_github_slug "$url")"; then
      if ver="$(adn_github_latest_release_tag "$slug")"; then
        printf '%s' "$ver"
        return 0
      fi
    fi
    channel=final
  fi

  local -a tags=()
  local t
  while IFS= read -r t; do
    [[ -n "$t" ]] || continue
    adn_release_channel_matches "$t" "$channel" || continue
    tags+=("$(adn_version_normalize "$t")")
  done < <(adn_git_list_tags "$url")
  ((${#tags[@]})) || return 1
  printf '%s\n' "${tags[@]}" | sort -V | tail -n1
}

# Resolve one component: explicit pin, or latest remote release for channel.
adn_resolve_component_version() {
  local tag_setting="${1:-auto}" branch="${2:-}" url="${3:-}" channel="${4:-auto}"
  local ver=""
  local pin="${ADN_DOCKER_PIN_TAGS:-0}"

  if [[ -n "$tag_setting" && "$tag_setting" != "auto" && "$pin" == "1" ]]; then
    ver="$(adn_version_normalize "$tag_setting")"
    adn_version_is_semver_tag "$ver" || return 1
    printf '%s' "$ver"
    return 0
  fi

  if [[ "$channel" == "auto" || "$channel" == "release" || "$channel" == "latest" ]]; then
    adn_git_latest_tag_for_channel "$url" "$channel"
    return $?
  fi

  if [[ -n "$tag_setting" && "$tag_setting" != "auto" ]]; then
    ver="$(adn_version_normalize "$tag_setting")"
    adn_version_is_semver_tag "$ver" || return 1
    printf '%s' "$ver"
    return 0
  fi

  if [[ -n "$branch" ]]; then
    if ver="$(adn_version_from_ref "$branch" 2>/dev/null)"; then
      printf '%s' "$ver"
      return 0
    fi
    return 1
  fi

  adn_git_latest_tag_for_channel "$url" "$channel"
}

adn_docker_deploy_cli_version() {
  local root="${ADN_REPO_ROOT:-${ADN_DEPLOY_HOME:-}}"
  local pyproject=""
  if [[ -n "$root" && -f "$root/pyproject.toml" ]]; then
    pyproject="$root/pyproject.toml"
  fi
  if [[ -z "$pyproject" ]]; then
    printf '2.0.0'
    return 0
  fi
  local ver
  ver="$(sed -n 's/^version = "\([^"]*\)".*/\1/p' "$pyproject" | head -n1)"
  [[ -n "$ver" ]] || ver="2.0.0"
  printf '%s' "$ver"
}

adn_docker_default_tag() {
  if [[ -n "${DOCKER_TAG_DEFAULT:-}" && "${DOCKER_TAG_DEFAULT}" != "auto" ]]; then
    adn_version_normalize "${DOCKER_TAG_DEFAULT}"
    return 0
  fi
  adn_docker_deploy_cli_version
}

adn_docker_image_tag() {
  case "$1" in
    adn-server|server) printf '%s' "${DOCKER_TAG_SERVER:-}" ;;
    adn-monitor|monitor) printf '%s' "${DOCKER_TAG_MONITOR:-}" ;;
    daprs) printf '%s' "${DOCKER_TAG_DAPRS:-}" ;;
    adn-deploy-cli|deploy-cli) printf '%s' "${DOCKER_TAG_DEPLOY_CLI:-}" ;;
    *)
      echo "adn_docker_image_tag: unknown image $1" >&2
      return 1
      ;;
  esac
}

adn_docker_export_image_refs() {
  local reg="${1:-${DOCKER_REGISTRY:-${LOCAL_REGISTRY:-docker.io/ce5rpy}}}"
  reg="${reg%/}"
  export ADN_IMAGE_SERVER="${reg}/adn-server:${DOCKER_TAG_SERVER}"
  export ADN_IMAGE_MONITOR="${reg}/adn-monitor:${DOCKER_TAG_MONITOR}"
  export ADN_IMAGE_DAPRS="${reg}/daprs:${DOCKER_TAG_DAPRS}"
  export ADN_IMAGE_DEPLOY_CLI="${reg}/adn-deploy-cli:${DOCKER_TAG_DEPLOY_CLI}"
}

adn_docker_should_tag_latest() {
  local tag="$1"
  local enabled="${BUILD_LATEST_TAG:-1}"
  [[ "$enabled" == "1" ]] || return 1
  adn_version_is_semver_tag "$tag" || return 1
  tag="$(adn_version_normalize "$tag")"
  [[ "$tag" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

# Highest final release semver (x.y.z only — no rc/beta) from tag names (args or stdin).
adn_pick_highest_final_semver() {
  local -a finals=()
  local t
  if ((${#@})); then
    for t in "$@"; do
      [[ -n "$t" ]] || continue
      adn_docker_should_tag_latest "$t" || continue
      finals+=("$(adn_version_normalize "$t")")
    done
  else
    while IFS= read -r t; do
      [[ -n "$t" ]] || continue
      adn_docker_should_tag_latest "$t" || continue
      finals+=("$(adn_version_normalize "$t")")
    done
  fi
  ((${#finals[@]})) || return 1
  printf '%s\n' "${finals[@]}" | sort -V | tail -n1
}

adn_registry_is_local() {
  local reg_prefix="${1%/}"
  local reg_host="${reg_prefix%%/*}"
  local host="${reg_host%%:*}"
  case "$host" in
    127.0.0.1|localhost) return 0 ;;
    *) return 1 ;;
  esac
}

adn_registry_hub_namespace() {
  local reg_prefix="${1%/}"
  local host="${reg_prefix%%/*}"
  case "$host" in
    docker.io|index.docker.io|registry-1.docker.io)
      printf '%s' "${reg_prefix#*/}"
      return 0
      ;;
  esac
  return 1
}

adn_registry_list_tags_local() {
  local reg_prefix="$1" image_name="$2"
  reg_prefix="${reg_prefix%/}"
  local reg_host="${reg_prefix%%/*}"
  local repo="${reg_prefix#*/}/${image_name}"
  local tags_json
  command -v jq >/dev/null 2>&1 || return 1
  tags_json="$(curl -fsS "http://${reg_host}/v2/${repo}/tags/list" 2>/dev/null || true)"
  [[ -n "$tags_json" ]] || return 1
  echo "$tags_json" | jq -r '.tags[]?' 2>/dev/null
}

adn_registry_list_tags_hub() {
  local namespace="$1" image_name="$2"
  local url="https://hub.docker.com/v2/repositories/${namespace}/${image_name}/tags/?page_size=100"
  local json next
  command -v jq >/dev/null 2>&1 || return 1
  while [[ -n "$url" ]]; do
    json="$(curl -fsS --max-time 30 -H 'User-Agent: ADN-Deploy' "$url" 2>/dev/null)" || return 1
    echo "$json" | jq -r '.results[]?.name // empty'
    next="$(echo "$json" | jq -r '.next // empty')"
    [[ -n "$next" && "$next" != "null" ]] || break
    url="$next"
  done
}

adn_registry_list_tags() {
  local reg_prefix="$1" image_name="$2"
  local ns
  if adn_registry_is_local "$reg_prefix"; then
    adn_registry_list_tags_local "$reg_prefix" "$image_name"
  elif ns="$(adn_registry_hub_namespace "$reg_prefix")"; then
    adn_registry_list_tags_hub "$ns" "$image_name"
  else
    return 1
  fi
}

# Highest final semver tag present on a registry for one image.
adn_registry_highest_final_semver() {
  local reg_prefix="$1" image_name="$2"
  local -a tags=()
  mapfile -t tags < <(adn_registry_list_tags "$reg_prefix" "$image_name" 2>/dev/null || true)
  ((${#tags[@]})) || return 1
  adn_pick_highest_final_semver "${tags[@]}"
}

# Pick highest final semver on REG, merging registry tags with optional fallback candidate(s).
adn_docker_resolve_latest_semver() {
  local reg_prefix="$1" image_name="$2"
  shift 2
  local -a candidates=()
  local t
  while IFS= read -r t; do
    [[ -n "$t" ]] || continue
    candidates+=("$t")
  done < <(adn_registry_list_tags "$reg_prefix" "$image_name" 2>/dev/null || true)
  for t in "$@"; do
    [[ -n "$t" ]] && candidates+=("$t")
  done
  ((${#candidates[@]})) || return 1
  adn_pick_highest_final_semver "${candidates[@]}"
}

adn_imagetools_digest() {
  local ref="$1"
  command -v jq >/dev/null 2>&1 || return 1
  docker buildx imagetools inspect "$ref" --format '{{json .}}' 2>/dev/null \
    | jq -r '.manifest.digest // empty' 2>/dev/null
}

# True when :latest on REG already references the same manifest as SEMVER_TAG.
adn_docker_latest_matches_semver() {
  local reg_prefix="$1" image_name="$2" semver_tag="$3" latest_name="${4:-latest}"
  reg_prefix="${reg_prefix%/}"
  semver_tag="$(adn_version_normalize "$semver_tag")"
  [[ "$semver_tag" == "$latest_name" ]] && return 1
  local latest_digest semver_digest
  latest_digest="$(adn_imagetools_digest "${reg_prefix}/${image_name}:${latest_name}")" || return 1
  semver_digest="$(adn_imagetools_digest "${reg_prefix}/${image_name}:${semver_tag}")" || return 1
  [[ -n "$latest_digest" && "$latest_digest" == "$semver_digest" ]]
}

# Point :latest at the highest final semver on REG (no-op when already correct).
adn_docker_refresh_latest_tag() {
  local reg_prefix="$1" image_name="$2" latest_name="${3:-latest}"
  shift 3
  local -a extra=("$@")
  local highest ref latest_ref
  highest="$(adn_docker_resolve_latest_semver "$reg_prefix" "$image_name" "${extra[@]}")" || return 0
  adn_docker_should_tag_latest "$highest" || return 0
  ref="${reg_prefix%/}/${image_name}:${highest}"
  latest_ref="${reg_prefix%/}/${image_name}:${latest_name}"
  if adn_docker_latest_matches_semver "$reg_prefix" "$image_name" "$highest" "$latest_name"; then
    echo "==> latest ${image_name} already -> ${highest}"
    return 0
  fi
  echo "==> latest ${image_name} -> ${latest_ref} (semver ${highest})"
  docker buildx imagetools create -t "$latest_ref" "$ref"
}

# Resolve per-component tags + git refs; export ADN_IMAGE_* when registry is set.
adn_docker_resolve_release_vars() {
  local channel="${ADN_RELEASE_CHANNEL:-auto}"
  local mon_url="${GIT_URL_MONITOR:-https://github.com/ce5rpy/ADN-Monitor.git}"
  local peer_url="${GIT_URL_PEER:-https://github.com/ce5rpy/ADN-DMR-Peer-Server.git}"
  local daprs_url="${GIT_URL_DAPRS:-https://gitlab.com/C31AG/hbnet.git}"
  local mon_ver="" peer_ver="" daprs_ver="" cli_ver=""

  peer_ver="$(adn_resolve_component_version \
    "${DOCKER_TAG_SERVER:-auto}" "${GIT_BRANCH_PEER:-}" "$peer_url" "$channel")" || {
    echo "adn_docker_resolve_release: could not resolve server tag (DOCKER_TAG_SERVER=${DOCKER_TAG_SERVER:-auto} GIT_BRANCH_PEER=${GIT_BRANCH_PEER:-<unset>})" >&2
    return 1
  }
  mon_ver="$(adn_resolve_component_version \
    "${DOCKER_TAG_MONITOR:-auto}" "${GIT_BRANCH_MONITOR:-}" "$mon_url" "$channel")" || {
    echo "adn_docker_resolve_release: could not resolve monitor tag (DOCKER_TAG_MONITOR=${DOCKER_TAG_MONITOR:-auto} GIT_BRANCH_MONITOR=${GIT_BRANCH_MONITOR:-<unset>})" >&2
    return 1
  }

  if daprs_ver="$(adn_resolve_component_version \
      "${DOCKER_TAG_DAPRS:-auto}" "${GIT_BRANCH_DAPRS:-}" "$daprs_url" "$channel" 2>/dev/null)" \
      && adn_version_is_semver_tag "$daprs_ver"; then
    :
  else
    daprs_ver="$(adn_docker_default_tag)"
  fi

  if [[ "${DOCKER_TAG_DEPLOY_CLI:-auto}" == "auto" || -z "${DOCKER_TAG_DEPLOY_CLI:-}" ]]; then
    cli_ver="$(adn_docker_deploy_cli_version)"
  else
    cli_ver="$(adn_version_normalize "${DOCKER_TAG_DEPLOY_CLI}")"
  fi

  export DOCKER_TAG_SERVER="$peer_ver"
  export DOCKER_TAG_MONITOR="$mon_ver"
  export DOCKER_TAG_DAPRS="$daprs_ver"
  export DOCKER_TAG_DEPLOY_CLI="$cli_ver"

  if [[ -z "${GIT_BRANCH_PEER:-}" ]] || adn_version_from_ref "${GIT_BRANCH_PEER}" >/dev/null 2>&1; then
    export GIT_BRANCH_PEER="$(adn_version_git_ref "$peer_ver")"
  fi
  if [[ -z "${GIT_BRANCH_MONITOR:-}" ]] || adn_version_from_ref "${GIT_BRANCH_MONITOR}" >/dev/null 2>&1; then
    export GIT_BRANCH_MONITOR="$(adn_version_git_ref "$mon_ver")"
  fi

  if [[ -n "${DOCKER_REGISTRY:-}" || -n "${LOCAL_REGISTRY:-}" ]]; then
    adn_docker_export_image_refs
  fi

  if ! adn_docker_should_tag_latest "$peer_ver" \
      || ! adn_docker_should_tag_latest "$mon_ver" \
      || ! adn_docker_should_tag_latest "$daprs_ver" \
      || ! adn_docker_should_tag_latest "$cli_ver"; then
    export BUILD_LATEST_TAG=0
  else
    export BUILD_LATEST_TAG=1
  fi

  if [[ "${ADN_DOCKER_RESOLVE_VERBOSE:-0}" == "1" ]]; then
    echo "docker release: channel=$channel"
    echo "  server=${DOCKER_TAG_SERVER} (${GIT_BRANCH_PEER})"
    echo "  monitor=${DOCKER_TAG_MONITOR} (${GIT_BRANCH_MONITOR})"
    echo "  daprs=${DOCKER_TAG_DAPRS}"
    echo "  deploy-cli=${DOCKER_TAG_DEPLOY_CLI}"
  fi
}
