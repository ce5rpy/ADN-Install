# ADN-Install — advanced

**English** · [Español](README.advanced.es.md)

Full reference for the ADN installers: version pins, variables, commands and layout. For a quick install, see [README.md](README.md).

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

### Versions

By default everything installs from `master`, which always holds the latest release, the same as the Docker install. There are three independent pins, all optional:

| What gets cloned | Path | Pin | Default |
|------------------|------|-----|---------|
| Installer toolkit | `/opt/ADN-Install` | `ADN_DEPLOY_REF` or `ADN_INSTALL_REF` (environment) | `master` |
| DMR peer server | `/opt/adn-dmr-server` | `GIT_BRANCH_PEER` in `deploy.conf` (branch, tag or commit) | remote default (`master`) |
| Monitor | `/opt/adn-monitor` | `GIT_BRANCH_MONITOR` in `deploy.conf` (branch, tag or commit) | remote default (`master`) |

`ADN_INSTALL_REF` overrides `ADN_DEPLOY_REF` when both are set.

**Install specific app versions** (2 steps):

```bash
# 1) Bootstrap the toolkit only (stops before cloning the apps)
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh \
  | sudo env ADN_DEPLOY_BOOTSTRAP_ONLY=1 bash

# 2) Pin the app versions, then complete the install (OS, pyenv, stack, wizard, services)
sudo tee -a /opt/ADN-Install/deploy.conf <<'EOF'
GIT_BRANCH_PEER="v2.7.0"
GIT_BRANCH_MONITOR="v2.7.0"
EOF
sudo bash /opt/ADN-Install/install/install.sh
```

**Already installed — update or switch versions:**

`adn-deploy update` (or re-running the installer) updates the app repos in place to the ref in `deploy.conf`: a branch, a release tag, or a commit. Without `GIT_BRANCH_*` they follow `master`.

```bash
sudo tee -a /opt/ADN-Install/deploy.conf <<'EOF'
GIT_BRANCH_PEER="v2.5.6"
GIT_BRANCH_MONITOR="v2.5.3"
EOF
sudo adn-deploy update    # fetch + checkout, pip, restart services
```

- Local config is kept: `adn-server.yaml`, `adn-echo.yaml`, `adn-monitor.yaml`, `.env` and the D-APRS config/data files are backed up to `/opt/adn-backups/<repo>-<date>/` (root only) before each switch and restored afterwards. `SERVER_ID` and security settings are never reset by an update.
- If tracked files in an app repo were edited by hand, the update stops for that repo — commit or stash those changes first.

| Variable | Default | When needed |
|----------|---------|-------------|
| `ADN_DEPLOY_REF` | `master` | Pin the `ADN-Install` toolkit to a branch, tag (`v2.7.0`) or commit |
| `ADN_INSTALL_REF` | *(falls back to `ADN_DEPLOY_REF`)* | Same as above; wins if both set |
| `GIT_BRANCH_PEER` | *(unset → remote default)* | Set in `deploy.conf` to install/update `adn-dmr-server` at a branch, tag (`v2.5.6`) or commit |
| `GIT_BRANCH_MONITOR` | *(unset → remote default)* | Set in `deploy.conf` to install/update `adn-monitor` at a branch, tag (`v2.5.3`) or commit |
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

## Development version (`develop`)

`develop` is the integration branch of ADN-DMR-Peer-Server and ADN-Monitor: what will go into their next release. Use it to test; production servers should stay on the stable version (the default).

Only the DMR server and the monitor change. The toolkit (`/opt/ADN-Install`) and the `adn-deploy-cli` and `daprs` images are the same in both cases.

| | Stable (default) | Development |
|---|---|---|
| Bare metal: `GIT_BRANCH_PEER`, `GIT_BRANCH_MONITOR` in `deploy.conf` | unset (`master`) | `develop` |
| Docker: images in `/opt/adn-docker/.env` | `adn-server:latest`, `adn-monitor:latest` | `adn-server:develop`, `adn-monitor:develop` |

The `:develop` images are rebuilt on every change to `develop`. Each build also stays available as `:develop-<commit>` (for example `adn-server:develop-c0f9f64`), to keep a server on one specific build.

### Bare metal

**New install:**

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo env ADN_DEPLOY_BOOTSTRAP_ONLY=1 bash
printf 'GIT_BRANCH_PEER="develop"\nGIT_BRANCH_MONITOR="develop"\n' | sudo tee -a /opt/ADN-Install/deploy.conf
sudo bash /opt/ADN-Install/install/install.sh
```

**Existing server → `develop`:**

```bash
sudo adn-deploy config set deploy GIT_BRANCH_PEER develop
sudo adn-deploy config set deploy GIT_BRANCH_MONITOR develop
sudo adn-deploy update
```

From then on, each `sudo adn-deploy update` moves to the newest commit on `develop`.

**Back to the stable version:** the same commands with `master` (or a release tag such as `v2.7.0`) instead of `develop`. The configuration is kept, as described in [Versions](#versions).

### Docker

**New install:**

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo env DOCKER_TAG_SERVER=develop DOCKER_TAG_MONITOR=develop bash
```

**Existing server → `develop`:** running the installer again keeps the current `.env`, so change the two images there:

```bash
sudo sed -i -E 's#^(DOCKER_TAG_(SERVER|MONITOR))=.*#\1=develop#; s#^(ADN_IMAGE_SERVER=.*/adn-server):.*#\1:develop#; s#^(ADN_IMAGE_MONITOR=.*/adn-monitor):.*#\1:develop#' /opt/adn-docker/.env
sudo adn-docker update
```

From then on, each `sudo adn-docker update` pulls the newest `develop` image.

**Back to the stable version:**

```bash
sudo sed -i -E 's#^(DOCKER_TAG_(SERVER|MONITOR))=.*#\1=latest#; s#^(ADN_IMAGE_SERVER=.*/adn-server):.*#\1:latest#; s#^(ADN_IMAGE_MONITOR=.*/adn-monitor):.*#\1:latest#' /opt/adn-docker/.env
sudo adn-docker update
```

To check which images are running: `docker ps --format '{{.Names}} {{.Image}}'`.

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
| `adn-deploy update` | Update toolkit and app repos to the configured refs, keep config, restart |
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
| `adn-dmr-server/` | Amateur-Digital-Network/ADN-DMR-Peer-Server | `GIT_BRANCH_PEER` |
| `adn-monitor/` | Amateur-Digital-Network/ADN-Monitor | `GIT_BRANCH_MONITOR` |
| `ADN-Install/` | ce5rpy/ADN-Install (toolkit at `/opt/ADN-Install`) | `ADN_DEPLOY_REF` at install time |
