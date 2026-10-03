# ADN-Install

**English** · [Español](README.es.md)

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

Interactive install (normal terminal): if `adn` is missing and `ADN_USER_PASSWORD` is unset, phase `[1/6]` prompts for a password on `/dev/tty`.

Or from a local clone:

```bash
cd /opt/ADN-Install
sudo bash install.sh
```

Pin toolkit branch (`ADN-Install` at `/opt/ADN-Install`):

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh \
  | sudo ADN_DEPLOY_REF=master bash
```

`ADN_INSTALL_REF` overrides `ADN_DEPLOY_REF` when both are set.

### Bare metal install (`develop` branch)

Bare metal uses **two independent branch pins**:

| What gets cloned | Path | Branch variable | Default |
|------------------|------|-----------------|---------|
| Installer toolkit | `/opt/ADN-Install` | `ADN_DEPLOY_REF` or `ADN_INSTALL_REF` | `master` |
| DMR peer server | `/opt/adn-dmr-server` | `GIT_BRANCH_PEER` in `deploy.conf` (branch, tag or commit) | remote default (`master`) |
| Monitor | `/opt/adn-monitor` | `GIT_BRANCH_MONITOR` in `deploy.conf` (branch, tag or commit) | remote default (`master`) |

`ADN_DEPLOY_REF=develop` only pins the **toolkit**. The app repos still clone `master` unless you set `GIT_BRANCH_PEER` / `GIT_BRANCH_MONITOR` in `deploy.conf`.

**Recommended — full install on `develop` (3 steps):**

```bash
# 1) Bootstrap toolkit from develop (stops before stack clone)
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/develop/install.sh \
  | sudo env ADN_DEPLOY_REF=develop ADN_DEPLOY_BOOTSTRAP_ONLY=1 bash

# 2) Pin app repos to develop
sudo tee -a /opt/ADN-Install/deploy.conf <<'EOF'
GIT_BRANCH_PEER="develop"
GIT_BRANCH_MONITOR="develop"
EOF

# 3) Complete install (OS, pyenv, stack, wizard, services)
sudo bash /opt/ADN-Install/install/install.sh
```

**Local clone on `develop`:**

```bash
cd /opt/ADN-Install   # git checkout develop
sudo tee -a deploy.conf <<'EOF'
GIT_BRANCH_PEER="develop"
GIT_BRANCH_MONITOR="develop"
EOF
sudo ADN_DEPLOY_REF=develop bash install.sh
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
| `ADN_DEPLOY_REF` | `master` | Pin `ADN-Install` toolkit branch (`develop`, tag, SHA) |
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
