# ADN Docker stack (2.0.0) — production install

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

## Host layout

| Path | Purpose |
|------|---------|
| `/opt/adn-docker/docker-compose.yml` | Stack |
| `/opt/adn-docker/.env` | MariaDB passwords, image tags |
| `/opt/adn-docker/deploy.conf` | Runtime config |
| `/opt/adn-docker/state/` | Service YAMLs, traefik, logs |
| `/usr/local/sbin/adn-docker` | Host CLI |

Images: `docker.io/ce5rpy/*:2.0.0` (override with `DOCKER_REGISTRY` / `DOCKER_TAG`).

## Local registry test

If images are in a private registry (e.g. `127.0.0.1:5000/ce5rpy`):

```bash
sudo DOCKER_REGISTRY=127.0.0.1:5000/ce5rpy DOCKER_TAG=2.0.0 \
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

**MariaDB password mismatch:** remove volume `adn_mariadb_data` and reinstall if `.env` passwords changed after first init.
