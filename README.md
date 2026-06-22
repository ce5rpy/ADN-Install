# ADN-Install

Public installers for the **ce5rpy** ADN stack (DMR peer server + unified Python monitor).

**Branches:** `develop` (daily work) · `master` (release). Install curl URLs use `master`.

## Bare metal install

On a fresh Debian 13 or Ubuntu 22.04+ VM as **root**:

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo bash
```

The installer runs as root and, by default, creates a Linux account **`adn`** (pyenv, git clones, service ownership). If `adn` already exists, nothing is changed and no password is needed.

**Fresh VM — set login password for new `adn` user** (non-interactive / CI only):

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh \
  | sudo ADN_USER_PASSWORD='your_password' bash
```

Interactive install (normal terminal): if `adn` is missing and `ADN_USER_PASSWORD` is unset, phase `[1/5]` prompts for a password on `/dev/tty`.

Or from a local clone:

```bash
cd /opt/ADN-Install
sudo bash install.sh
```

Pin branch:

```bash
curl -fsSL .../install.sh | sudo ADN_DEPLOY_REF=master bash
```

| Variable | Default | When needed |
|----------|---------|-------------|
| `ADN_USER` | `adn` | Override Linux username |
| `ADN_USER_PASSWORD` | *(unset)* | Only when **creating** `adn` without a TTY prompt |
| `ADN_CREATE_USER=0` | create user | Use existing user; must already exist |
| `ADN_DEPLOY_STAGING=1` | off | Staging path instead of `/opt` prod guard |

After install: `adn-deploy menu`, `adn-deploy doctor`, `adn-deploy service start`.

## Docker install (production)

Does **not** clone this repo on the host. Creates `/opt/adn-docker` and `/usr/local/sbin/adn-docker`. Images from `docker.io/ce5rpy/*:2.0.0`.

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
```

After install:

```bash
adn-docker setup    # if wizard was skipped
adn-docker doctor
adn-docker menu     # ssl enable when ready
```

See [install-docker/README.md](install-docker/README.md) for host layout and troubleshooting.

## Architecture (bare metal)

| Component | Role |
|-----------|------|
| **adn-server** | DMR peer + integrated hotspot proxy |
| **adn-monitor** | FastAPI: REST `/api/*`, WebSocket `/ws` |
| **nginx** | TLS + static SPA |
| **MariaDB** | Self-service login DB |

## Commands

| Command | Description |
|---------|-------------|
| `adn-deploy install` | Full install |
| `adn-deploy menu` | Textual admin menu |
| `adn-deploy doctor` | Health checks |
| `adn-deploy stack` | git, config, systemd, web |

## Layout

- `install.sh` — bare metal bootstrap (`curl | bash`)
- `docker-install.sh` — Docker production install (`curl | bash`)
- `sbin/adn-deploy` — CLI wrapper (pyenv Python)
- `src/adn_deploy/` — Python toolkit
- `install-docker/` — Docker runtime install scripts only (no build)

## Repos cloned under `$ADN_ROOT`

| Path | GitHub |
|------|--------|
| `adn-dmr-server/` | ce5rpy/ADN-DMR-Peer-Server |
| `adn-monitor/` | ce5rpy/ADN-Monitor |
| `ADN-Install/` | ce5rpy/ADN-Install (this repo, installed at `/opt/ADN-Install`) |
