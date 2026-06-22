#!/usr/bin/env bash
# Install Docker Engine from download.docker.com on Debian (Trixie/Bookworm).
# Run on the remote server as root (su -). Debian minimal has no sudo by default.
# Ref: https://docs.docker.com/engine/install/debian/
#
# Optional: pass a login name to add to group docker, e.g.:
#   bash install-docker-debian.sh bilson
set -euo pipefail

if [[ "${EUID:-}" -ne 0 ]]; then
  echo "Run as root (e.g. su -), not as an unprivileged user." >&2
  exit 1
fi

# DVD/cdrom installs break apt-get update when no disc is present.
if grep -rqs '^deb cdrom:' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
  echo "  apt: disabling cdrom repository (comment out in sources.list)"
  sed -i '/^deb cdrom:/s/^/# disabled by adn-deploy: /' /etc/apt/sources.list 2>/dev/null || true
  for f in /etc/apt/sources.list.d/*.list; do
    [[ -f "$f" ]] || continue
    sed -i '/^deb cdrom:/s/^/# disabled by adn-deploy: /' "$f" 2>/dev/null || true
  done
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
KEYRING=/etc/apt/keyrings/docker.asc
if ! curl -fsSL https://download.docker.com/linux/debian/gpg -o "$KEYRING"; then
  echo "ERROR: failed to download Docker GPG key to $KEYRING" >&2
  exit 1
fi
chmod a+r "$KEYRING"
if [[ ! -s "$KEYRING" ]]; then
  echo "ERROR: $KEYRING is empty or missing" >&2
  exit 1
fi

CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME:-}")"
ARCH="$(dpkg --print-architecture)"
if [[ -z "$CODENAME" ]]; then
  echo "ERROR: cannot detect Debian VERSION_CODENAME" >&2
  exit 1
fi

tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: ${CODENAME}
Components: stable
Architectures: ${ARCH}
Signed-By: ${KEYRING}
EOF

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

TARGET_USER="${1:-${ADN_DOCKER_USER:-}}"
if [[ -n "$TARGET_USER" && "$TARGET_USER" != root ]]; then
  if id "$TARGET_USER" &>/dev/null; then
    usermod -aG docker "$TARGET_USER"
    echo "  Added user $TARGET_USER to group docker (re-login or: su - $TARGET_USER)"
  else
    echo "  WARN: user $TARGET_USER not found — skip usermod (run as root uses docker directly)" >&2
  fi
fi

docker run --rm hello-world
echo "Docker Engine installed."
