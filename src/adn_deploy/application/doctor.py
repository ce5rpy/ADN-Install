"""Health checks: pyenv, units, paths, web."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from adn_deploy.application import config as app_config
from adn_deploy.application import users
from adn_deploy.application import web
from adn_deploy.core.env import Settings, init_env
from adn_deploy.domain.plugins import is_plugin_enabled, plugin_peer_stack_enabled
from adn_deploy.infra import os_bootstrap
from adn_deploy.infra import yaml_store


def _check_import(settings: Settings, service: str, mod: str, req: str = "") -> bool:
    if os_bootstrap.verify_import(settings, mod, quiet=True):
        print(f"OK:   {service} — {mod}")
        return True
    try:
        py = settings.pyenv_python()
    except FileNotFoundError:
        py = Path("?")
    print(f"FAIL: {service} — cannot import {mod}")
    print(f"      python: {py}")
    if req:
        print(f"      pip:    sudo -u {settings.adn_user} {py} -m pip install -r {req}")
    print("      or:     adn-deploy update  |  menu → Reinstall Python dependencies")
    return False


def python_deps(settings: Settings) -> int:
    fails = 0
    peer_req = settings.adn_dmr_server_path / "requirements.txt"
    mon_req = settings.adn_monitor_path / "monitor" / "requirements.txt"
    print("")
    print("--- Python libraries (shared pyenv for all systemd units) ---")
    try:
        print(f"Interpreter: {settings.pyenv_python()}")
    except FileNotFoundError as exc:
        print(str(exc))
        fails += 1
        return fails

    plugins = settings.paths.plugins
    if plugin_peer_stack_enabled(plugins, settings.adn_root):
        print("")
        print("adn-server / adn-echo (DMR peer)")
        print(f"  requirements: {peer_req}")
        fails += 0 if _check_import(settings, "adn-server", "bitarray", str(peer_req)) else 1
        fails += 0 if _check_import(settings, "adn-server", "twisted", str(peer_req)) else 1
    if is_plugin_enabled(plugins, settings.adn_root, "adn-monitor"):
        print("")
        print("adn-monitor (FastAPI panel + reports)")
        print(f"  requirements: {mon_req}")
        for mod in ("yaml", "fastapi", "uvicorn", "twisted", "itsdangerous", "MySQLdb"):
            fails += 0 if _check_import(settings, "adn-monitor", mod, str(mon_req)) else 1
    return fails


def mysql_check(settings: Settings) -> bool:
    mon = settings.adn_monitor_path / "monitor" / "adn-monitor.yaml"
    if not shutil.which("mysql"):
        print("SKIP: mysql client not installed")
        return True
    mon_user = ""
    if mon.is_file():
        val = yaml_store.yaml_get(mon, "SELF_SERVICE.DB_USERNAME")
        mon_user = str(val or "").strip()
    deploy_user = settings.mysql_db_user or "self_service_user"
    if deploy_user and mon_user and deploy_user != mon_user:
        print(f"WARN: deploy.conf MYSQL_DB_USER={deploy_user} but adn-monitor.yaml DB_USERNAME={mon_user}")
        return False
    peer = settings.adn_dmr_server_path / "adn-server.yaml"
    if peer.is_file():
        peer_user = str(yaml_store.yaml_get(peer, "DATABASE.DB_USERNAME") or "").strip()
        peer_pass = str(yaml_store.yaml_get(peer, "DATABASE.DB_PASSWORD") or "").strip()
        if deploy_user and peer_user and deploy_user != peer_user:
            print(
                f"WARN: deploy.conf MYSQL_DB_USER={deploy_user} but adn-server.yaml DATABASE.DB_USERNAME={peer_user}"
            )
            print("  fix: adn-deploy web mysql")
            return False
        if not peer_pass or "<" in peer_pass:
            print("WARN: adn-server.yaml DATABASE.DB_PASSWORD unset — run: adn-deploy web mysql")
            return False
    if not settings.mysql_db_password:
        print("WARN: MYSQL_DB_PASSWORD unset in deploy.conf — run: adn-deploy web mysql")
        return False
    if web.mysql_test_app_user(settings):
        print(f"OK: MySQL {settings.mysql_db_user}@{settings.mysql_db_name}")
        return True
    print(f"FAIL: MySQL login failed for {settings.mysql_db_user}@localhost")
    return False


def passphrase_check(settings: Settings) -> bool:
    server = settings.adn_dmr_server_path / "adn-server.yaml"
    echo_cfg = settings.adn_dmr_server_path / "adn-echo.yaml"
    if not server.is_file():
        print("SKIP: passphrase check (no adn-server.yaml)")
        return True
    rc = True
    sys_pp = yaml_store.yaml_get(server, "SYSTEMS.SYSTEM.PASSPHRASE")
    echo_pp = yaml_store.yaml_get(server, "SYSTEMS.ECHO.PASSPHRASE")
    if app_config.passphrase_is_placeholder(str(sys_pp or "")):
        print("WARN: SYSTEMS.SYSTEM.PASSPHRASE unset or example placeholder")
        rc = False
    if app_config.passphrase_is_placeholder(str(echo_pp or "")):
        print("WARN: SYSTEMS.ECHO.PASSPHRASE unset or example placeholder")
        rc = False
    if echo_cfg.is_file():
        echo_peer = yaml_store.yaml_get(echo_cfg, "SYSTEMS.ECHO.PASSPHRASE")
        if app_config.passphrase_is_placeholder(str(echo_peer or "")):
            print("WARN: adn-echo.yaml SYSTEMS.ECHO.PASSPHRASE unset or example placeholder")
            rc = False
        elif echo_pp and echo_peer and str(echo_peer).strip() != str(echo_pp).strip():
            print("WARN: echo peer passphrase != server ECHO")
            rc = False
    if rc:
        print("OK: HBP passphrases (SYSTEM/ECHO)")
    return rc


def opt_permissions(settings: Settings) -> bool:
    user = settings.adn_user
    if os.geteuid() == 0:
        users.fix_permissions(settings)
    fails = 0
    paths = [
        settings.adn_deploy_conf,
        settings.adn_monitor_path / "monitor" / "monitor.py",
    ]
    for p in paths:
        if p is None or not Path(p).exists():
            continue
        proc = subprocess.run(["sudo", "-u", user, "test", "-r", str(p)], capture_output=True)
        if proc.returncode == 0:
            print(f"OK: readable by {user} — {p}")
        else:
            print(f"FAIL: not readable by {user} — {p}")
            fails += 1
    return fails == 0


def _traefik_http_ok(http_port: str) -> bool:
    health_url = f"http://127.0.0.1:{http_port}/api/health"
    if subprocess.run(
        ["curl", "-fsS", "-m", "5", health_url], capture_output=True, check=False
    ).returncode == 0:
        return True
    return (
        subprocess.run(
            ["curl", "-fsS", "-m", "5", f"http://127.0.0.1:{http_port}/"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _traefik_ws_ok(http_port: str) -> bool:
    ws_url = f"http://127.0.0.1:{http_port}/ws"
    ws_proc = subprocess.run(
        [
            "curl",
            "-sS",
            "-i",
            "-N",
            "-m",
            "5",
            "-H",
            "Connection: Upgrade",
            "-H",
            "Upgrade: websocket",
            "-H",
            "Sec-WebSocket-Version: 13",
            "-H",
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==",
            ws_url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(
        ws_proc.stdout.startswith("HTTP/")
        and " 101 " in ws_proc.stdout.splitlines()[0]
    )


def _docker_doctor_retry_traefik(
    http_port: str,
    *,
    attempts: int = 3,
    delay_sec: float = 2.0,
) -> tuple[bool, bool]:
    """Return (http_ok, ws_ok) after retrying while Traefik/monitor warm up."""
    http_ok = False
    ws_ok = False
    for attempt in range(1, attempts + 1):
        http_ok = _traefik_http_ok(http_port)
        ws_ok = _traefik_ws_ok(http_port)
        if http_ok and ws_ok:
            break
        if attempt < attempts:
            time.sleep(delay_sec)
    return http_ok, ws_ok


def docker_doctor(settings: Settings) -> bool:
    """Health checks for Docker Compose stack."""
    fails = 0
    print("=== adn-docker doctor ===")
    print(f"Ports (host): traefik :{os.environ.get('TRAEFIK_HTTP_PORT', '80')} -> adn-monitor:{settings.monitor_app_port}")

    compose_file = os.environ.get("ADN_DOCKER_COMPOSE_FILE", "")
    env_file = os.environ.get("ADN_DOCKER_ENV_FILE", "")
    if not compose_file or not Path(compose_file).is_file():
        compose_file = str(settings.adn_deploy_home / "install-docker" / "compose" / "compose.yml")
    if not env_file or not Path(env_file).is_file():
        env_file = str(settings.adn_deploy_home / "install-docker" / "compose" / ".env")

    if not Path(compose_file).is_file():
        print(f"FAIL: missing compose file: {compose_file}")
        return False

    cmd = ["docker", "compose", "-f", compose_file]
    if Path(env_file).is_file():
        cmd.extend(["--env-file", env_file])
    cmd.extend(["--profile", os.environ.get("ADN_DOCKER_PROFILE", "full"), "ps", "--format", "json"])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"FAIL: docker compose ps failed — is the stack running?")
        print(f"      {proc.stderr.strip() or proc.stdout.strip()}")
        fails += 1
    else:
        running: set[str] = set()
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                name = row.get("Service") or row.get("Name", "")
                state = (row.get("State") or row.get("Status") or "").lower()
                if "running" in state:
                    running.add(name)
            except Exception:
                continue
        expected = {"mariadb", "adn-server", "adn-echo", "adn-monitor", "traefik"}
        if app_config.daprs_plugin_enabled(settings):
            expected.add("daprs")
        for svc in sorted(expected):
            if svc in running:
                print(f"OK:   compose service {svc} running")
            else:
                print(f"WARN: compose service {svc} not running")
                fails += 1

    http_port = os.environ.get("TRAEFIK_HTTP_PORT", "80")
    if shutil.which("curl"):
        health_url = f"http://127.0.0.1:{http_port}/api/health"
        retry_attempts = int(os.environ.get("DOCTOR_TRAEFIK_RETRIES", "3"))
        retry_delay = float(os.environ.get("DOCTOR_TRAEFIK_RETRY_SEC", "2"))
        http_ok, ws_ok = _docker_doctor_retry_traefik(
            http_port, attempts=retry_attempts, delay_sec=retry_delay
        )
        if http_ok:
            if subprocess.run(
                ["curl", "-fsS", "-m", "5", health_url], capture_output=True, check=False
            ).returncode == 0:
                print(f"OK:   traefik -> adn-monitor health ({health_url})")
            else:
                print(f"OK:   traefik HTTP :{http_port} (health endpoint unavailable)")
        else:
            print(f"WARN: traefik not responding on :{http_port}")
            fails += 1
        ws_url = f"http://127.0.0.1:{http_port}/ws"
        if ws_ok:
            print(f"OK:   traefik WebSocket upgrade ({ws_url})")
        else:
            print(f"WARN: traefik WebSocket /ws upgrade failed ({ws_url})")
            fails += 1
    else:
        print("SKIP: curl not installed for HTTP check")

    if app_config.mandatory_fields_incomplete(settings):
        missing = app_config.mandatory_missing_labels(settings)
        print(f"WARN: mandatory config incomplete ({', '.join(missing)})")
        fails += 1

    if fails:
        print(f"Doctor: {fails} warning(s)")
        return False
    print("Doctor: OK")
    return True


def run(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.docker:
        return docker_doctor(cfg)

    fails = 0
    print("=== adn-deploy doctor ===")
    print(f"Ports: 4321/TCP adn-server; {cfg.monitor_app_port}/TCP adn-monitor; 80/443 nginx")

    if not opt_permissions(cfg):
        fails += 1
    if app_config.mandatory_fields_incomplete(cfg):
        missing = app_config.mandatory_missing_labels(cfg)
        print(f"WARN: mandatory config incomplete ({', '.join(missing)})")
        fails += 1

    try:
        py = cfg.pyenv_python()
        exe_ver = subprocess.run([str(py), "-V"], capture_output=True, text=True).stdout.strip()
        print(f"OK: ADN_PYENV_PYTHON — {exe_ver} ({py})")
    except FileNotFoundError:
        print("WARN: no python at ADN_PYENV_PYTHON / versions")
        fails += 1

    fails += python_deps(cfg)
    print("")

    for p in (
        cfg.adn_dmr_server_path / "adn-server.yaml",
        cfg.adn_monitor_path / "monitor" / "adn-monitor.yaml",
    ):
        if p.is_file():
            print(f"OK: config {p}")
        else:
            print(f"WARN: missing {p}")
            fails += 1

    server_yaml = cfg.adn_dmr_server_path / "adn-server.yaml"
    if server_yaml.is_file() and re.search(r'^\s*SERVER_ID:\s*"', server_yaml.read_text(encoding="utf-8"), re.MULTILINE):
        print("WARN: SERVER_ID is a quoted YAML string — use an integer")
        fails += 1

    plugins = cfg.paths.plugins
    units = ["adn-server", "adn-monitor", "adn-echo"]
    if app_config.daprs_plugin_enabled(cfg):
        units.append("daprs")
    for u in units:
        if not is_plugin_enabled(plugins, cfg.adn_root, u):
            print(f"SKIP: unit {u} (plugin disabled)")
            continue
        if subprocess.run(["systemctl", "is-active", "--quiet", u], capture_output=True).returncode == 0:
            print(f"OK: unit {u} active")
        elif cfg.staging:
            print(f"SKIP: unit {u} (staging)")
        elif subprocess.run(["systemctl", "list-unit-files", f"{u}.service"], capture_output=True).returncode != 0:
            print(f"WARN: {u}.service not installed — run: adn-deploy install or adn-deploy update")
            fails += 1
        else:
            print(f"WARN: unit {u} not active — journalctl -u {u} -n 50 --no-pager")
            fails += 1

    dist = cfg.adn_monitor_path / "frontend" / "dist"
    if dist.is_dir():
        print("OK: frontend dist built")
    else:
        print("WARN: frontend/dist missing")

    if shutil.which("nginx") or cfg.filegen:
        nginx_dir = cfg.adn_etc_root / "nginx" / "sites-enabled"
        keep = cfg.nginx_site_name
        if nginx_dir.is_dir():
            for entry in nginx_dir.iterdir():
                if entry.name != keep:
                    print(f"WARN: extra nginx site enabled ({entry}) — run: adn-deploy web nginx render")
                    fails += 1
                    break
        if cfg.skip_os_packages or cfg.filegen:
            print("SKIP: nginx -t (filegen/staging)")
        elif subprocess.run(["nginx", "-t"], capture_output=True).returncode == 0:
            print("OK: nginx -t")
        else:
            print("FAIL: nginx -t")
            fails += 1

    if not mysql_check(cfg):
        fails += 1
    if not passphrase_check(cfg):
        fails += 1

    if app_config.daprs_plugin_enabled(cfg):
        login = app_config.daprs_aprs_default(cfg)
        if app_config.daprs_aprs_incomplete(cfg):
            print("WARN: D-APRS APRS login unset (N0CALL) — complete setup wizard or set DAPRS_APRS_CALLSIGN")
            fails += 1
        else:
            print(f"OK: D-APRS APRS login {login}")

    if fails:
        print(f"Doctor: {fails} warning(s)")
        return False
    print("Doctor: OK")
    return True
