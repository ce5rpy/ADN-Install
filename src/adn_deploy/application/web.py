"""Web stack: MySQL, nginx, certbot, websocket, npm build."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from adn_deploy.application import config as app_config
from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.subprocess_runner import is_dry_run, run, run_as_adn
from adn_deploy.infra import os_bootstrap
from adn_deploy.infra import systemd


def ssl_enabled(settings: Settings) -> bool:
    return settings.web_ssl == "1"


def monitor_app_port(settings: Settings) -> str:
    return settings.monitor_app_port or os.environ.get("WEBSOCKET_PORT", "8080")


def monitor_app_upstream(settings: Settings) -> str:
    return settings.monitor_app_upstream or os.environ.get("WEBSOCKET_UPSTREAM", "127.0.0.1")


def _nginx_configured_hostnames(settings: Settings) -> str:
    """Real panel hostnames from deploy.conf (no catch-all _, no placeholders)."""
    names = settings.nginx_server_names.strip()
    if not names or app_config.is_placeholder_nginx_names(names):
        return ""
    return " ".join(p for p in names.split() if p != "_")


def _nginx_http_server_names(settings: Settings) -> str:
    """HTTP server_name: configured host(s) plus _ for IP/default access."""
    configured = _nginx_configured_hostnames(settings)
    if not configured:
        return "_"
    parts = configured.split()
    if "_" not in parts:
        parts.append("_")
    return " ".join(parts)


def _nginx_ssl_server_names(settings: Settings) -> str:
    """HTTPS server_name: configured host(s) only (cert must match; no _)."""
    configured = _nginx_configured_hostnames(settings)
    return configured or "_"


def _certbot_primary_domain(settings: Settings) -> str:
    primary = str(settings.certbot_primary_domain or "").strip()
    if primary and primary != "_" and not app_config.is_placeholder_nginx_names(primary):
        return primary
    configured = _nginx_configured_hostnames(settings)
    return configured.split()[0] if configured else ""


def _nginx_listen_env(settings: Settings, env: dict) -> None:
    ip = str(settings.nginx_listen_ip or "").strip()
    has_host = bool(_nginx_configured_hostnames(settings))
    # HTTP stays default_server for IP access; HTTPS default only when no real hostname.
    ssl_default = "" if has_host else " default_server"
    if ip:
        env["NGINX_LISTEN_DIRECTIVE"] = f"{ip}:80 default_server"
        env["NGINX_LISTEN_IPV6_DIRECTIVE"] = "[::]:80 default_server"
        env["NGINX_LISTEN_SSL_DIRECTIVE"] = f"{ip}:443 ssl{ssl_default}"
        env["NGINX_LISTEN_SSL_IPV6_DIRECTIVE"] = f"[::]:443 ssl{ssl_default}"
    else:
        env["NGINX_LISTEN_DIRECTIVE"] = "80 default_server"
        env["NGINX_LISTEN_IPV6_DIRECTIVE"] = "[::]:80 default_server"
        env["NGINX_LISTEN_SSL_DIRECTIVE"] = f"443 ssl{ssl_default}"
        env["NGINX_LISTEN_SSL_IPV6_DIRECTIVE"] = f"[::]:443 ssl{ssl_default}"


def _populate_nginx_env(settings: Settings, env: dict) -> None:
    env["NGINX_SERVER_NAMES"] = _nginx_http_server_names(settings)
    env["NGINX_SSL_SERVER_NAMES"] = _nginx_ssl_server_names(settings)
    primary = _certbot_primary_domain(settings)
    if primary:
        env["CERTBOT_PRIMARY_DOMAIN"] = primary
    else:
        env.setdefault("CERTBOT_PRIMARY_DOMAIN", "_")
    _nginx_listen_env(settings, env)


_NGINX_ENVSUBST_VARS = (
    "${ADN_ROOT} ${ADN_MONITOR_PATH} ${NGINX_SERVER_NAMES} ${NGINX_SSL_SERVER_NAMES} "
    "${NGINX_LISTEN_DIRECTIVE} ${NGINX_LISTEN_IPV6_DIRECTIVE} "
    "${NGINX_LISTEN_SSL_DIRECTIVE} ${NGINX_LISTEN_SSL_IPV6_DIRECTIVE} "
    "${MONITOR_APP_UPSTREAM} ${MONITOR_APP_PORT} ${CERTBOT_PRIMARY_DOMAIN}"
)


def _envsubst_snippet(settings: Settings, tpl: Path) -> str:
    env = os.environ.copy()
    env.update(settings.to_env_dict())
    _populate_nginx_env(settings, env)
    with tpl.open(encoding="utf-8") as f:
        content = f.read()
    proc = subprocess.run(
        ["envsubst", _NGINX_ENVSUBST_VARS],
        input=content,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return proc.stdout


def _nginx_host_cmd(settings: Settings, *args: str) -> bool:
    if settings.docker:
        print("  nginx: not used on host in Docker mode", file=sys.stderr)
        return False
    if settings.skip_os_packages or settings.filegen:
        print(f"  nginx: skipped host command ({' '.join(args)})")
        return True
    return run(settings, "nginx", *args, check=False).returncode == 0


def nginx_prune_sites_enabled(settings: Settings) -> bool:
    keep = settings.nginx_site_name or "adn-monitor"
    sites = settings.adn_etc_root / "nginx" / "sites-enabled"
    if not sites.is_dir():
        return False
    removed = False
    for entry in sites.iterdir():
        if entry.name == keep:
            continue
        if is_dry_run(settings):
            print(f"[dry-run] rm -f {entry}")
        else:
            run(settings, "rm", "-f", str(entry))
            print(f"  nginx: removed sites-enabled/{entry.name} (only {keep} is used)")
        removed = True
    return removed


def nginx_ensure_running(settings: Settings) -> bool:
    if settings.staging or settings.dry_run or settings.filegen:
        return True
    if not shutil.which("systemctl"):
        return True
    systemd.systemctl(settings, "enable", "nginx")
    if subprocess.run(["systemctl", "is-active", "--quiet", "nginx"], capture_output=True).returncode == 0:
        return True
    if systemd.systemctl(settings, "start", "nginx").returncode == 0:
        print("  nginx: started")
        return True
    print("  nginx: start failed — journalctl -u nginx -n 30 --no-pager", file=sys.stderr)
    return False


def nginx_render(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.docker:
        print("  docker: nginx render skipped (Traefik)")
        return True
    if app_config.mandatory_fields_incomplete(cfg) and os.environ.get("ADN_DEPLOY_FORCE_NGINX_RENDER") != "1":
        print("  nginx: skipped — set SERVER_ID and panel hostname first (adn-deploy menu)", file=sys.stderr)
        return True

    tpl = cfg.adn_deploy_home / "templates" / "nginx" / "adn-monitor.conf.in"
    if not tpl.is_file():
        print("missing nginx template", file=sys.stderr)
        return False

    snip_dir = cfg.adn_deploy_home / "templates" / "nginx" / "snippets"
    if ssl_enabled(cfg):
        http_inner = _envsubst_snippet(cfg, snip_dir / "http-redirect.conf.in")
        ssl_block = _envsubst_snippet(cfg, snip_dir / "ssl-server.conf.in")
    else:
        http_inner = _envsubst_snippet(cfg, snip_dir / "http-app.conf.in")
        ssl_block = ""

    avail = cfg.adn_etc_root / "nginx" / "sites-available" / cfg.nginx_site_name
    enabled = cfg.adn_etc_root / "nginx" / "sites-enabled" / cfg.nginx_site_name
    run(cfg, "mkdir", "-p", str(avail.parent), str(enabled.parent))

    if is_dry_run(cfg):
        print(f"[dry-run] envsubst nginx -> {avail} (WEB_SSL={cfg.web_ssl})")
        nginx_prune_sites_enabled(cfg)
        return True

    env = os.environ.copy()
    env.update(cfg.to_env_dict())
    _populate_nginx_env(cfg, env)
    env["NGINX_HTTP_INNER"] = http_inner
    env["NGINX_SSL_SERVER_BLOCK"] = ssl_block

    with tpl.open(encoding="utf-8") as f:
        content = f.read()
    proc = subprocess.run(
        ["envsubst", f"{_NGINX_ENVSUBST_VARS} ${{NGINX_HTTP_INNER}} ${{NGINX_SSL_SERVER_BLOCK}}"],
        input=content,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return False
    avail.write_text(proc.stdout, encoding="utf-8")
    if enabled.exists() or enabled.is_symlink():
        enabled.unlink()
    enabled.symlink_to(avail)
    print(f"  nginx site: {avail} (WEB_SSL={cfg.web_ssl}, upstream={monitor_app_upstream(cfg)}:{monitor_app_port(cfg)})")
    nginx_prune_sites_enabled(cfg)
    nginx_ensure_running(cfg)
    if _nginx_host_cmd(cfg, "-t"):
        if subprocess.run(["systemctl", "is-active", "--quiet", "nginx"], capture_output=True).returncode == 0:
            systemd.systemctl(cfg, "reload", "nginx")
    return True


def nginx_cmd(settings: Settings | None, action: str = "reload") -> int:
    cfg = settings or init_env()
    if action == "render":
        return 0 if nginx_render(cfg) else 1
    if action == "test":
        return 0 if _nginx_host_cmd(cfg, "-t") else 1
    if action == "reload":
        nginx_prune_sites_enabled(cfg)
        if _nginx_host_cmd(cfg, "-t"):
            systemd.systemctl(cfg, "reload", "nginx")
            return 0
        return 1
    print("usage: web nginx <render|test|reload>", file=sys.stderr)
    return 1


def certbot_deploy_hook(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    tpl = cfg.adn_deploy_home / "templates" / "letsencrypt" / "renew-hook.sh.in"
    dest = cfg.adn_etc_root / "letsencrypt" / "renewal-hooks" / "deploy" / "adn-deploy.sh"
    if not tpl.is_file():
        return
    run(cfg, "mkdir", "-p", str(dest.parent))
    if is_dry_run(cfg):
        print(f"[dry-run] envsubst certbot hook -> {dest}")
        return
    env = os.environ.copy()
    env.update(cfg.to_env_dict())
    with tpl.open(encoding="utf-8") as f:
        content = f.read()
    proc = subprocess.run(
        ["envsubst", "${ADN_DEPLOY_HOME} ${ADN_ETC_ROOT}"],
        input=content,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode == 0:
        dest.write_text(proc.stdout, encoding="utf-8")
        run(cfg, "chmod", "+x", str(dest))
        print(f"  certbot: deploy hook -> {dest}")


def ssl_set_enabled(settings: Settings) -> None:
    settings.web_ssl = "1"
    if settings.adn_deploy_conf:
        app_config.set_kv(settings, settings.adn_deploy_conf, "WEB_SSL", "1")


def certbot_issue(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.staging:
        print("certbot: skipped in staging")
        return True
    domains = _nginx_configured_hostnames(cfg)
    if not domains:
        print("set a real panel hostname in NGINX_SERVER_NAMES before enabling SSL", file=sys.stderr)
        return False
    if not ssl_enabled(cfg):
        nginx_render(cfg)
    if is_dry_run(cfg):
        print(f"[dry-run] certbot certonly --nginx -d {domains}")
        ssl_set_enabled(cfg)
        cfg.web_ssl = "1"
        nginx_render(cfg)
        return True
    args: list[str] = ["certbot", "certonly", "--nginx"]
    issued = False
    for domain in domains.split():
        if domain == "_" or app_config.is_placeholder_nginx_names(domain):
            continue
        args.extend(["-d", domain])
        issued = True
    if not issued:
        print("set a real panel hostname in NGINX_SERVER_NAMES before enabling SSL", file=sys.stderr)
        return False
    args.extend(["--email", cfg.certbot_email or "admin@localhost", "--agree-tos", "--non-interactive"])
    run(cfg, *args)
    certbot_deploy_hook(cfg)
    ssl_set_enabled(cfg)
    nginx_render(cfg)
    if _nginx_host_cmd(cfg, "-t"):
        systemd.systemctl(cfg, "reload", "nginx")
    return True


def certbot_renew(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    if cfg.staging or is_dry_run(cfg):
        print("[dry-run] certbot renew" if is_dry_run(cfg) else "certbot: skipped in staging")
        return
    run(cfg, "certbot", "renew")


def certbot_status(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    run(cfg, "certbot", "certificates", check=False)


def certbot_cmd(settings: Settings | None, action: str = "status") -> int:
    cfg = settings or init_env()
    if cfg.staging:
        print("certbot: skipped in staging")
        return 0
    if action in ("issue", "enable"):
        return 0 if certbot_issue(cfg) else 1
    if action == "renew":
        certbot_renew(cfg)
        return 0
    if action == "status":
        certbot_status(cfg)
        return 0
    print("usage: web cert|ssl <enable|issue|renew|status>", file=sys.stderr)
    return 1


def ws_sync_yaml(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    yaml = cfg.adn_monitor_path / "monitor" / "adn-monitor.yaml"
    if not yaml.is_file():
        return
    port = monitor_app_port(cfg)
    if is_dry_run(cfg):
        print(f"[dry-run] set MONITOR_APP.LISTEN_PORT={port} in {yaml}")
        return
    app_config.yaml_set_path(cfg, yaml, "MONITOR_APP.LISTEN_PORT", port)
    print(f"  monitor: MONITOR_APP.LISTEN_PORT={port}")


def ws_cmd(settings: Settings | None = None, *, soft: bool = False) -> bool:
    cfg = settings or init_env()
    host = monitor_app_upstream(cfg)
    port = monitor_app_port(cfg)
    if not shutil.which("curl"):
        print("SKIP: curl not installed for WS check")
        return True
    url = f"http://{host}:{port}/api/health"
    proc = subprocess.run(["curl", "-fsS", "-m", "5", url], capture_output=True, check=False)
    if proc.returncode == 0:
        print(f"OK: TCP {host}:{port} (adn-monitor API)")
        return True
    msg = f"{'WARN' if soft else 'FAIL'}: adn-monitor not responding on {host}:{port}"
    print(msg, file=sys.stderr)
    return False


def build_assets(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    if cfg.filegen:
        print("  web build: skipped (filegen — no npm)")
        return
    fe = cfg.adn_monitor_path / "frontend"
    if not fe.is_dir():
        print(f"  web build: skipped — missing {fe}", file=sys.stderr)
        return
    if not shutil.which("npm"):
        print("  web build: skipped — npm not installed", file=sys.stderr)
        return
    print(f"  web build: npm in {fe}")
    run(cfg, "chown", "-R", f"{cfg.adn_user}:{cfg.adn_user}", str(fe), check=False)
    dist_index = fe / "dist" / "index.html"
    for cmd in ("npm ci && npm run build", "npm install && npm run build"):
        proc = run_as_adn(cfg, f"cd '{fe}' && {cmd}", check=False)
        if proc is None:
            continue
        if proc.returncode == 0 and dist_index.is_file():
            print(f"  web build: done ({fe / 'dist'})")
            return
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            if err:
                print(f"  web build: {cmd.split('&&')[0].strip()} failed: {err[:500]}", file=sys.stderr)
    print("  web build: npm build failed (panel frontend may be missing)", file=sys.stderr)


def _mysql_sql_escape(value: str) -> str:
    return value.replace("'", "''")


def _mysql_admin_cmd(settings: Settings) -> bool:
    if not shutil.which("mysql"):
        print("  mysql: client not installed (os-base full profile)", file=sys.stderr)
        return False
    if not settings.docker:
        subprocess.run(["systemctl", "start", "mariadb"], capture_output=True)
        subprocess.run(["systemctl", "start", "mysql"], capture_output=True)
    root_pass = settings.mysql_root_password
    if root_pass:
        env = {**os.environ, "MYSQL_PWD": root_pass}
        if subprocess.run(["mysql", "-uroot", "-e", "SELECT 1"], env=env, capture_output=True).returncode == 0:
            return True
        print("  mysql: root login failed (check MYSQL_ROOT_PASSWORD)", file=sys.stderr)
        return False
    return subprocess.run(["mysql", "-uroot", "-e", "SELECT 1"], capture_output=True).returncode == 0


def _mysql_admin_run(settings: Settings, sql: str) -> bool:
    root_pass = settings.mysql_root_password
    env = os.environ.copy()
    if root_pass:
        env["MYSQL_PWD"] = root_pass
        cmd = ["mysql", "-uroot", "-e", sql]
    else:
        cmd = ["mysql", "-uroot", "-e", sql]
    return subprocess.run(cmd, env=env, capture_output=True).returncode == 0


def mysql_test_app_user(settings: Settings) -> bool:
    if not settings.mysql_db_password:
        return False
    if not shutil.which("mysql"):
        return False
    db = settings.mysql_db_name or "hbmon"
    user = settings.mysql_db_user or "self_service_user"
    env = {**os.environ, "MYSQL_PWD": settings.mysql_db_password}
    return subprocess.run(
        ["mysql", "-h", "localhost", "-u", user, db, "-e", "SELECT 1"],
        env=env,
        capture_output=True,
    ).returncode == 0


def mysql_bootstrap(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.filegen or cfg.skip_os_packages:
        print("  mysql: skipped (filegen / no os packages)")
        return True
    if not cfg.mysql_db_password:
        from adn_deploy.application.config import _mysql_credentials

        _db, _user, existing = _mysql_credentials(cfg)
        if existing:
            cfg.mysql_db_password = existing
            print(f"  mysql: using password from monitor yaml for {_user}@localhost")
        else:
            cfg.mysql_db_password = secrets.token_hex(16)
            print(f"  mysql: generated password for {cfg.mysql_db_user}@localhost (stored in deploy.conf)")
    db = cfg.mysql_db_name or "hbmon"
    user = cfg.mysql_db_user or "self_service_user"
    password = cfg.mysql_db_password
    if not _mysql_admin_cmd(cfg):
        return False
    if is_dry_run(cfg):
        print(f"[dry-run] mysql create database {db} / user {user}")
        return True
    pass_sql = _mysql_sql_escape(password)
    user_sql = _mysql_sql_escape(user)
    if not _mysql_admin_run(cfg, f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"):
        return False
    if not _mysql_admin_run(
        cfg,
        f"CREATE USER IF NOT EXISTS '{user_sql}'@'localhost' IDENTIFIED BY '{pass_sql}';",
    ):
        _mysql_admin_run(
            cfg,
            f"ALTER USER '{user_sql}'@'localhost' IDENTIFIED BY '{pass_sql}';",
        )
    else:
        _mysql_admin_run(cfg, f"ALTER USER '{user_sql}'@'localhost' IDENTIFIED BY '{pass_sql}';")
    _mysql_admin_run(cfg, f"GRANT ALL PRIVILEGES ON `{db}`.* TO '{user_sql}'@'localhost';")
    _mysql_admin_run(cfg, "FLUSH PRIVILEGES;")
    print("  mysql: database and user OK")
    app_config.mysql_persist(cfg)
    app_config.mysql_sync_yaml(cfg)
    bootstrap_py = cfg.adn_monitor_path / "monitor" / "db_bootstrap.py"
    if bootstrap_py.is_file():
        if not os_bootstrap.verify_import(cfg, "MySQLdb", quiet=True):
            os_bootstrap.pip_monitor(cfg)
        py = cfg.pyenv_python()
        run_as_adn(
            cfg,
            f"cd {cfg.adn_monitor_path / 'monitor'} && {py} db_bootstrap.py --config {cfg.adn_monitor_path / 'monitor' / 'adn-monitor.yaml'} --create",
        )
    return True


def finish_panel_setup(settings: Settings | None = None) -> bool:
    """Build frontend + render nginx vhost (after mandatory wizard or install menu)."""
    cfg = settings or init_env()
    if cfg.docker:
        print("  web panel: skipped (Docker uses Traefik)")
        return True
    if app_config.mandatory_fields_incomplete(cfg):
        print(
            "  web panel: skipped — set SERVER_ID, dashboard title, and panel hostname first",
            file=sys.stderr,
        )
        return False
    print("==> Web panel (nginx vhost + frontend)")
    build_assets(cfg)
    ws_sync_yaml(cfg)
    if not nginx_render(cfg):
        return False
    certbot_deploy_hook(cfg)
    return True


def install(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.skip_os_packages or cfg.staging:
        print("  adn-web: skip os packages (render nginx/certbot templates only)")
        return finish_panel_setup(cfg)
    if not mysql_bootstrap(cfg):
        return False
    return finish_panel_setup(cfg)


def update(settings: Settings | None = None) -> None:
    build_assets(settings)


def web_cmd(settings: Settings | None, sub: str, *args: str) -> int:
    cfg = settings or init_env()
    if sub in ("panel", "finish"):
        return 0 if finish_panel_setup(cfg) else 1
    if sub == "mysql":
        return 0 if mysql_bootstrap(cfg) else 1
    if sub == "nginx":
        return nginx_cmd(cfg, args[0] if args else "reload")
    if sub in ("cert", "ssl"):
        return certbot_cmd(cfg, args[0] if args else "status")
    if sub in ("ws", "test-ws"):
        soft = "--soft" in args
        return 0 if ws_cmd(cfg, soft=soft) else 1
    if sub == "build":
        build_assets(cfg)
        return 0
    print("usage: web <panel|mysql|nginx|cert|ws|build> ...", file=sys.stderr)
    return 1
