# ADN-Install

**English** · [Español](README.es.md)

Installs an ADN DMR server: the DMR server, the web dashboard and the gateway for phone apps.

Everything you need is below. For version pins, variables and other details, see the [advanced guide](README.advanced.md).

## What you need

- A server or VM with **Debian 13** or **Ubuntu 22.04 or newer**, freshly installed.
- Access as **root** (or a user with `sudo`).
- Your **Server ID** and the **name** you want on the dashboard.

## Install

Choose **one** of the two options. If you are not sure, choose **Docker**.

**Option A — Docker (recommended):**

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
```

**Option B — Bare metal (without Docker):**

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/install.sh | sudo bash
```

The installer asks for your Server ID and dashboard name at the end. If it did not ask (for example, it was run without a terminal), run:

```bash
sudo adn-docker setup     # Docker
sudo adn-deploy wizard    # Bare metal
```

## Check that it works

```bash
sudo adn-docker doctor    # Docker
sudo adn-deploy doctor    # Bare metal
```

It should end with `Doctor: OK`. Then open `http://<your-server-ip>/` in a browser to see the dashboard.

## Open these ports

If your server or your cloud provider has a firewall, open:

| Port | For |
|------|-----|
| `80/tcp`, `443/tcp` | Web dashboard |
| `62031/udp` | Hotspots |
| `62032/udp` | OpenBridge links to other servers |
| `54006/udp` | Phone apps and IP terminals (ODTP) |

## Connect to the ADN panel

So the ADN panel shows your server (version, ports, links, ODTP), on your server's page in the sysop panel generate a **token**; the panel also shows the **endpoint**. Then:

```bash
sudo adn-docker menu      # Docker
sudo adn-deploy menu      # Bare metal
```

Go to **Server (DMR peer) → Configure → Change a variable**, fill in `ADN_PANEL.ENDPOINT` and `ADN_PANEL.TOKEN`, then go back and choose **Restart container** (Docker) or **Reload config** (bare metal). The ODTP port is filled in for you.

## Update

**Docker:**

```bash
sudo adn-docker update
```

**Bare metal:**

```bash
sudo adn-deploy update
```

Your settings are kept.

### Updating from 2.6 to 2.7

Version 2.7 adds the gateway for phone apps (ODTP). Updating from 2.6 needs these steps **once**:

**Docker** — run the installer again (your settings and passwords are kept):

```bash
curl -fsSL https://raw.githubusercontent.com/ce5rpy/ADN-Install/master/docker-install.sh | sudo bash
```

**Bare metal** — run these two commands, in this order:

```bash
sudo adn-deploy update --toolkit
sudo adn-deploy update
```

Then open `54006/udp` in your firewall.

## Admin menu

```bash
sudo adn-docker menu      # Docker
sudo adn-deploy menu      # Bare metal
```

## Something is wrong?

1. Run `doctor` (see above) and read the lines that say `WARN` or `ERROR`.
2. Check that the ports are open.
3. See the [advanced guide](README.advanced.md) and, for Docker, [install-docker/README.md](install-docker/README.md).
