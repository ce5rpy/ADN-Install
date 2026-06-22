# ADN bare-metal install

One-shot installer for Debian/Ubuntu hosts without Docker. Uses pyenv, systemd, and nginx.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo bash
```

Or from a checkout:

```bash
sudo ./install.sh
```

The root `install.sh` delegates to `install/install.sh`.

## What it installs

| Phase | Action |
|-------|--------|
| 1 | OS packages (`install/scripts/bootstrap_os.sh`, `install/packages/`) |
| 2 | Python via pyenv at `/opt/.pyenv` |
| 3 | Git clone peer + monitor, config, systemd units, nginx |
| 4 | Setup wizard (SERVER_ID, dashboard title, hostname) |
| 5 | Start services + `adn-deploy doctor` |

## Layout

- `install/install.sh` — main bootstrap
- `install/scripts/` — OS/pyenv helpers
- `install/packages/` — apt package lists (debian/ubuntu)

Admin CLI after install: `adn-deploy menu`

## Docker alternative

For containerized deployment use `./docker-install.sh` (registry pull, Traefik edge, no PHP/nginx on host). See `install-docker/README.md`.
