"""Generate deploy.conf.reference.example from read-only host inspection."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from adn_deploy.core.env import Settings, init_env


def dump(settings: Settings | None = None, out: Path | None = None) -> Path:
    cfg = settings or init_env()
    dest = out or (cfg.adn_deploy_home / "deploy.conf.reference.example")
    peer_path = cfg.adn_dmr_server_path if cfg.adn_dmr_server_path and cfg.adn_dmr_server_path.is_dir() else Path("/opt/adn-dmr-server")
    mon_path = cfg.adn_monitor_path if cfg.adn_monitor_path and cfg.adn_monitor_path.is_dir() else Path("/opt/adn-monitor")

    body = f"""# ADN-Deploy reference snapshot (generated {datetime.now().isoformat(timespec="seconds")})
# Read-only inspection — no secrets. Do not copy hostnames/passwords from reference host.
# Template: deploy.conf.example (same keys; values below are illustrative).

ADN_ROOT="/opt"
ADN_DMR_SERVER_PATH="$ADN_ROOT/adn-dmr-server"
ADN_MONITOR_PATH="$ADN_ROOT/adn-monitor"
ADN_PYENV_ROOT="$ADN_ROOT/.pyenv"
ADN_USER="adn"
ADN_CREATE_USER="1"
ADN_SUDO_NOPASSWD="1"
# ADN_USER_HOME="/home/adn"
ADN_PYTHON_VERSION="3.13.14"
# ADN_PYENV_REINSTALL="1"
# ADN_PYENV_PYTHON — written by pyenv install (systemd ExecStart and pip must match)
ADN_LOG_DIR="/var/log/adn-server"

GIT_URL_DEPLOY="https://github.com/ce5rpy/ADN-Install.git"
GIT_URL_PEER="https://github.com/ce5rpy/ADN-DMR-Peer-Server.git"
GIT_URL_MONITOR="https://github.com/ce5rpy/ADN-Monitor.git"
# GIT_BRANCH_DEPLOY=""
# GIT_BRANCH_PEER=""
# GIT_BRANCH_MONITOR=""
# ADN_SKIP_CLONE="1"

# GLOBAL.SERVER_ID: per host in $ADN_DMR_SERVER_PATH/adn-server.yaml (mandatory wizard)
HBP_PASSPHRASE="passw0rd"

NGINX_SITE_NAME="adn-monitor"
NGINX_SERVER_NAMES="example.adn.systems"
NGINX_LISTEN_IP=""
MONITOR_APP_PORT="8080"
MONITOR_APP_UPSTREAM="127.0.0.1"

WEB_SSL="0"
CERTBOT_EMAIL="admin@example.com"
CERTBOT_PRIMARY_DOMAIN="example.adn.systems"

MYSQL_DB_NAME="hbmon"
MYSQL_DB_USER="self_service_user"
# MYSQL_DB_PASSWORD — set on target host only (web mysql / install)
# MYSQL_ROOT_PASSWORD — only if MariaDB root needs a password

UFW_ENABLE="0"
UFW_EXTRA_TCP="80 443"
UFW_EXTRA_UDP=""
UFW_TRUSTED_SOURCES=""

ADN_DEPLOY_STAGING="0"
ADN_DEPLOY_PROFILE="full"
# ADN_INSTALL_WEB_OPTIONAL="0"

# Reference host paths (informational):
# - peer tree on this host: {peer_path}
# - monitor tree: {mon_path}
# - systemd: adn-server, adn-echo, adn-monitor
# - logrotate: /etc/logrotate.d/adn-server (${{ADN_LOG_DIR}}/adn-*.log)
# - nginx: /etc/nginx/sites-enabled/adn-monitor
# - UFW rebuild: adn-deploy ships scripts/ufw_rebuild_safe.py (bundled preferred over peer copy)
"""
    mon_yaml = mon_path / "monitor" / "adn-monitor.yaml"
    if mon_yaml.is_file():
        text = mon_yaml.read_text(encoding="utf-8")
        port_m = re.search(r"^\s*LISTEN_PORT:\s*(\S+)", text, re.MULTILINE)
        ip_m = re.search(r'^\s*ADN_IP:\s*"?([^"\n]+)"?', text, re.MULTILINE)
        if port_m:
            body += f"# Observed monitor MONITOR_APP.LISTEN_PORT={port_m.group(1)} ADN_IP={ip_m.group(1) if ip_m else ''}\n"

    dest.write_text(body, encoding="utf-8")
    print(f"Wrote {dest}")
    return dest
