# ADN-Install — advanced

**English** · [Español](README.advanced.es.md)

Full reference for the ADN installers: version pins, variables, commands and layout. For a quick install, see [README.md](README.md).

## Versions: stable, develop or a specific release

**Always update the toolkit first.** The `version` command and the variables below need a recent toolkit; with an old one they do nothing:

```bash
sudo adn-deploy update --toolkit   # bare metal
sudo adn-docker update             # Docker (also updates adn-docker itself)
```

The DMR server (`adn-server`) and the monitor (`adn-monitor`) use **the same variables and values on bare metal and Docker**:

| Variable | Applies to |
|----------|------------|
| `ADN_VERSION` | both apps |
| `ADN_SERVER_VERSION` | adn-server only (wins over `ADN_VERSION`) |
| `ADN_MONITOR_VERSION` | adn-monitor only (wins over `ADN_VERSION`) |

| Value | Meaning | Bare metal (git) | Docker (image) |
|-------|---------|------------------|----------------|
| `stable` (default) | latest release | `master` | `:latest` |
| `develop` | next version, **for testing only** | `develop` | `:develop` |
| `X.Y.Z`, e.g. `2.7.0` | a specific release, to upgrade or downgrade | tag `vX.Y.Z` | `:X.Y.Z` |

They are saved in `/opt/ADN-Install/deploy.conf` (bare metal) or `/opt/adn-docker/.env` (Docker).

**New install at a version** — add the variable to the install command:

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo env ADN_VERSION=develop bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo env ADN_VERSION=develop bash
```

**Installed server** — the same command and values on both.

**Bare metal:**

```bash
sudo adn-deploy version                  # show the current versions
sudo adn-deploy version develop          # both apps to develop
sudo adn-deploy version 2.6.1            # both apps to 2.6.1 (downgrade)
sudo adn-deploy version --server 2.7.0   # one app only (or --monitor)
sudo adn-deploy version stable           # back to the latest release
```

**Docker:**

```bash
sudo adn-docker version                  # show the current versions
sudo adn-docker version develop          # both apps to develop
sudo adn-docker version 2.6.1            # both apps to 2.6.1 (downgrade)
sudo adn-docker version --server 2.7.0   # one app only (or --monitor)
sudo adn-docker version stable           # back to the latest release
```

The command checks that the version exists (git tag or branch, or Docker image) before changing anything, saves it and runs the update. From then on, each `update` stays on that version (`develop` moves to its newest commit or image).

- **Configuration is kept.** On bare metal, `adn-server.yaml`, `adn-echo.yaml`, `adn-monitor.yaml`, `.env` and the D-APRS config/data files are backed up to `/opt/adn-backups/<repo>-<date>/` (root only) before each switch and restored afterwards. `SERVER_ID` and security settings are never reset. If tracked files in an app repo were edited by hand, the update stops for that repo — commit or stash those changes first.
- **ODTP** (`adn-odtp`) exists from adn-server 2.7.0. With an older server it is stopped, and `doctor` warns that it is not running.
- **`develop` images** are rebuilt on every change to `develop`; each build also stays available as `:develop-<commit>` (for example `adn-server:develop-c0f9f64`).
- **Older settings** — `GIT_BRANCH_PEER` / `GIT_BRANCH_MONITOR` (bare metal) and `DOCKER_TAG_SERVER` / `DOCKER_TAG_MONITOR` (Docker) — still work while no `ADN_*_VERSION` is set. The `version` command replaces them.
- **The toolkit** (`/opt/ADN-Install`) always follows `master`. To pin it at install time: `ADN_DEPLOY_REF` (branch, tag or commit).

## Updating from 2.6 to 2.7

Version 2.7 adds the ODTP gateway (`adn-odtp`, UDP `54006`) for phone apps and IP terminals.

**Bare metal** — update the toolkit first, then the rest, so the second command already runs the 2.7 toolkit:

```bash
sudo adn-deploy update --toolkit   # toolkit only
sudo adn-deploy update             # adn-server / adn-monitor 2.7, adds adn-odtp
sudo adn-deploy doctor
```

If `deploy.conf` pins `GIT_BRANCH_PEER` / `GIT_BRANCH_MONITOR` to older versions, set them to `v2.7.0` (or remove them) before the second command.

**Docker** — run the installer again. It refreshes `docker-compose.yml` and `adn-docker` (which add the `adn-odtp` service), keeps `.env`, passwords and `state/`, and pulls the 2.7 images:

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
sudo adn-docker doctor
```

In both cases, open `54006/udp` in the firewall so the apps can connect.

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

Interactive install (normal terminal): if `adn` is missing and `ADN_USER_PASSWORD` is unset, phase `[1/6]` prompts for a password on `/dev/tty`.

Or from a local clone:

```bash
cd /opt/ADN-Install
sudo bash install.sh
```

### Variables

| Variable | Default | When needed |
|----------|---------|-------------|
| `ADN_DEPLOY_REF` | `master` | Pin the `ADN-Install` toolkit to a branch, tag (`v2.7.0`) or commit |
| `ADN_INSTALL_REF` | *(falls back to `ADN_DEPLOY_REF`)* | Same as above; wins if both set |
| `ADN_VERSION`, `ADN_SERVER_VERSION`, `ADN_MONITOR_VERSION` | `stable` | App versions: `stable`, `develop` or `X.Y.Z` — see [Versions](#versions-stable-develop-or-a-specific-release) |
| `ADN_DEPLOY_BOOTSTRAP_ONLY` | `0` | `1` = clone toolkit only, then edit `deploy.conf` before re-running install |
| `ADN_USER` | `adn` | Override Linux username |
| `ADN_USER_PASSWORD` | *(unset)* | Only when **creating** `adn` without a TTY prompt |
| `ADN_CREATE_USER=0` | create user | Use existing user; must already exist |
| `ADN_DEPLOY_STAGING=1` | off | Staging install under another `ADN_ROOT` (no system-wide apt/systemd/nginx) |

After install: `adn-deploy menu`, `adn-deploy doctor`, `adn-deploy service start`.

## Docker install (production)

Does **not** clone this repo on the host. Creates `/opt/adn-docker` and `/usr/local/sbin/adn-docker`. Images from `docker.io/ce5rpy/*`, each at the latest release of its component.

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
| **adn-odtp** | ODTP gateway (server ≥ 2.7): phone apps and IP terminals log in as peers. UDP `54006` (`ODTP.LISTEN_PORT` in `adn-odtp.yaml`); open it in the firewall |
| **adn-monitor** | FastAPI: REST `/api/*`, WebSocket `/ws` |
| **nginx** | TLS + static SPA |
| **MariaDB** | Self-service login DB |

## Commands

| Command | Description |
|---------|-------------|
| `adn-deploy install` | Full install |
| `adn-deploy update` | Update toolkit and app repos to the configured versions, keep config, restart |
| `adn-deploy update --toolkit` | Update the toolkit only (do this first) |
| `adn-deploy version [stable\|develop\|X.Y.Z]` | Show or change the app versions, then update ([Versions](#versions-stable-develop-or-a-specific-release)) |
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

| Path | GitHub | Branch (`deploy.conf`) |
|------|--------|------------------------|
| `adn-dmr-server/` | Amateur-Digital-Network/ADN-DMR-Peer-Server | `ADN_SERVER_VERSION` |
| `adn-monitor/` | Amateur-Digital-Network/ADN-Monitor | `ADN_MONITOR_VERSION` |
| `ADN-Install/` | ce5rpy/ADN-Install (toolkit at `/opt/ADN-Install`) | `ADN_DEPLOY_REF` at install time |
