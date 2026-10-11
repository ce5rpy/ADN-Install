# ADN Docker stack — production install

**English** · [Español](README.es.md)

Production install does **not** clone the toolkit on the host. Only `/opt/adn-docker` plus `/usr/local/sbin/adn-docker`. Python/admin runs in **`adn-deploy-cli`** pulled from the registry.

**Default edge: HTTP only** (`WEB_SSL=0`). HTTPS via `adn-docker menu` → ssl enable.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
```

| Step | Action |
|------|--------|
| 1 | Install Docker Engine (Debian) if missing |
| 2 | Mandatory setup TUI (SERVER_ID, title) |
| 3 | Create `/opt/adn-docker/` — `docker-compose.yml`, `.env`, `deploy.conf`, `state/` |
| 4 | Install `/usr/local/sbin/adn-docker` |
| 5 | Pull stack images, seed config, `compose up -d` (HTTP :80) |

Fixed defaults: `HBP_PASSPHRASE=passw0rd`, `WEB_SSL=0`.

After install:

```bash
adn-docker setup
adn-docker doctor
adn-docker menu
```

Without a terminal (e.g. automation), set the mandatory values instead of `adn-docker setup`:

```bash
sudo adn-docker config set deploy ADN_SERVER_ID 73010
sudo adn-docker config set deploy ADN_DASHTITLE "My server"
sudo adn-docker config set deploy DAPRS_APRS_CALLSIGN N0CALL   # your APRS callsign
sudo adn-docker doctor
```

In Docker, `deploy.conf` is the source of truth for these values: set them with `config set deploy …`. Values written directly to the service YAMLs (`config set adn-server GLOBAL.SERVER_ID`, `config set monitor DASHBOARD.DASHTITLE`) are overwritten by `deploy.conf` on the next sync.

## Host layout

| Path | Purpose |
|------|---------|
| `/opt/adn-docker/docker-compose.yml` | Stack |
| `/opt/adn-docker/.env` | MariaDB passwords, image tags |
| `/opt/adn-docker/deploy.conf` | Runtime config |
| `/opt/adn-docker/state/` | Service YAMLs, traefik, logs |
| `/usr/local/sbin/adn-docker` | Host CLI |

## Images and versions

Images come from `docker.io/ce5rpy/*` and use the `latest` tag, which always points to the newest release of each component:

| Image | Default tag | Pin with |
|-------|-------------|----------|
| `adn-server` | `latest` | `DOCKER_TAG_SERVER` |
| `adn-monitor` | `latest` | `DOCKER_TAG_MONITOR` |
| `daprs` | `latest` | `DOCKER_TAG_DAPRS` |
| `adn-deploy-cli` | `latest` | `DOCKER_TAG_DEPLOY_CLI` |

To update to the newest images: `sudo adn-docker up` (pulls `latest` and recreates the containers that changed).

To pin a version at install time, for example: `sudo DOCKER_TAG_SERVER=2.5.5 bash docker-install.sh`. `DOCKER_REGISTRY` selects another registry namespace.

## Local registry test

If images are in a private registry (e.g. `127.0.0.1:5000/ce5rpy`):

```bash
sudo DOCKER_REGISTRY=127.0.0.1:5000/ce5rpy \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh)"
```

## Services

MariaDB, adn-server, adn-echo, adn-monitor (:8080), Traefik (:80), daprs (profile `full`).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Re-run install | `curl .../docker-install.sh \| sudo bash` |
| Stack unhealthy | `adn-docker ps` / `adn-docker logs adn-monitor` |
| HTTPS | `adn-docker menu` → ssl enable |
| Port 80 already in use | Stop the other service, or set `TRAEFIK_HTTP_PORT` in `/opt/adn-docker/.env` |

**MariaDB password mismatch:** remove volume `adn_mariadb_data` and reinstall if `.env` passwords changed after first init.
