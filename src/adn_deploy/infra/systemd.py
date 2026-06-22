"""systemd units, logrotate, and service orchestration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.paths import map_host_path
from adn_deploy.core.subprocess_runner import is_dry_run, run
from adn_deploy.domain.plugins import is_plugin_enabled, plugin_get
from adn_deploy.infra.yaml_store import yaml_get


_ENVSUBST_UNIT_VARS = (
    "${ADN_ROOT} ${ADN_PYENV_ROOT} ${ADN_PYENV_PYTHON} "
    "${ADN_USER} ${ADN_DMR_SERVER_PATH} ${ADN_MONITOR_PATH}"
)

_SYSTEMD_PLUGINS = ("adn-server", "adn-echo", "adn-monitor", "daprs")


def _host_path(settings: Settings, path: str | Path) -> Path:
    return map_host_path(
        path,
        sysroot=settings.adn_sysroot,
        adn_root=settings.adn_root,
        deploy_home=settings.adn_deploy_home,
    )


def monitor_resolve_log_dir(settings: Settings, cfg: Path | None = None) -> Path:
    cfg = cfg or (settings.adn_monitor_path / "monitor" / "adn-monitor.yaml")
    log_path = "./log"
    if cfg.is_file():
        val = yaml_get(cfg, "LOGGER.LOG_PATH")
        if val:
            log_path = str(val)
    if log_path.startswith("/"):
        return Path(log_path)
    log_path = log_path.removeprefix("./")
    return settings.adn_monitor_path / "monitor" / log_path


def monitor_ensure_runtime_dirs(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    from adn_deploy.infra import git_repos

    if not git_repos.monitor_tree_ok(cfg.adn_monitor_path):
        return
    plugins = cfg.paths.plugins
    if is_plugin_enabled(plugins, cfg.adn_root, "adn-monitor"):
        log_dir = monitor_resolve_log_dir(cfg)
        run(cfg, "mkdir", "-p", str(log_dir))
        run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(log_dir), check=False)
        print(f"  monitor log dir: {log_dir}")


def _envsubst_render(settings: Settings, src: Path, dest: Path, var_list: str) -> None:
    run(settings, "mkdir", "-p", str(dest.parent))
    if is_dry_run(settings):
        print(f"[dry-run] envsubst -> {dest} < {src}")
        return
    env = os.environ.copy()
    env.update(settings.to_env_dict())
    try:
        py = settings.pyenv_python()
        env["ADN_PYENV_PYTHON"] = str(py)
    except FileNotFoundError:
        env.setdefault("ADN_PYENV_PYTHON", "")
    with src.open(encoding="utf-8") as f_in:
        content = f_in.read()
    proc = subprocess.run(
        ["envsubst", var_list],
        input=content,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"envsubst failed: {proc.stderr}")
    dest.write_text(proc.stdout, encoding="utf-8")
    print(f"  rendered {dest}")


def render_unit(settings: Settings, src: Path, dest: Path) -> None:
    if not src.is_file():
        print(f"  missing template: {src}", file=sys.stderr)
        raise FileNotFoundError(src)
    _envsubst_render(settings, src, dest, _ENVSUBST_UNIT_VARS)


def logrotate_render(settings: Settings, tpl_name: str, unit_name: str, var_list: str) -> None:
    src = settings.adn_deploy_home / "templates" / "logrotate" / tpl_name
    dest = settings.adn_etc_root / "logrotate.d" / unit_name
    if not src.is_file():
        return
    run(settings, "mkdir", "-p", str(dest.parent))
    if is_dry_run(settings):
        print(f"[dry-run] envsubst logrotate -> {dest}")
        return
    env = os.environ.copy()
    env.update(settings.to_env_dict())
    with src.open(encoding="utf-8") as f_in:
        content = f_in.read()
    proc = subprocess.run(
        ["envsubst", var_list],
        input=content,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"envsubst failed: {proc.stderr}")
    dest.write_text(proc.stdout, encoding="utf-8")
    print(f"  deployed logrotate: {dest}")


def logrotate_deploy(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    logrotate_render(cfg, "adn-server.in", "adn-server", "${ADN_LOG_DIR}")
    legacy = cfg.adn_etc_root / "logrotate.d" / "adn-monitor"
    if legacy.is_file() or legacy.is_symlink():
        run(cfg, "rm", "-f", str(legacy))
        print(f"  removed legacy logrotate: {legacy}")


def _docker_compose_cmd(settings: Settings, *args: str) -> list[str]:
    compose_file = os.environ.get(
        "ADN_DOCKER_COMPOSE_FILE",
        str(settings.adn_deploy_home / "install-docker" / "compose" / "compose.yml"),
    )
    env_file = os.environ.get(
        "ADN_DOCKER_ENV_FILE",
        str(settings.adn_deploy_home / "install-docker" / "compose" / ".env"),
    )
    cmd = ["docker", "compose", "-f", compose_file]
    if Path(env_file).is_file():
        cmd.extend(["--env-file", env_file])
    cmd.extend(["--profile", os.environ.get("ADN_DOCKER_PROFILE", "full"), *args])
    return cmd


def _docker_service_action(settings: Settings, action: str, unit: str) -> int:
    from adn_deploy.application.config_schema import service_unit

    svc = service_unit(unit.removesuffix(".service"))
    mapping = {
        "adn-server": "adn-server",
        "adn-echo": "adn-echo",
        "adn-monitor": "adn-monitor",
        "daprs": "daprs",
    }
    compose_svc = mapping.get(svc, svc)
    if action == "status":
        proc = subprocess.run(
            _docker_compose_cmd(settings, "ps", compose_svc),
            capture_output=True,
            text=True,
            check=False,
        )
        print(proc.stdout or proc.stderr)
        return proc.returncode
    if action not in ("start", "stop", "restart"):
        print(f"  docker: unsupported compose action {action}", file=sys.stderr)
        return 1
    proc = subprocess.run(_docker_compose_cmd(settings, action, compose_svc), check=False)
    if proc.returncode == 0:
        print(f"  docker: {action} {compose_svc}")
    return proc.returncode


def systemctl(settings: Settings, *args: str) -> subprocess.CompletedProcess[str]:
    if cfg := settings:
        if cfg.docker:
            cmd = args[0] if args else ""
            unit = args[1] if len(args) > 1 else ""
            if unit:
                rc = _docker_service_action(cfg, cmd, unit)
                return subprocess.CompletedProcess(list(args), rc)
            print(f"  docker: systemctl {cmd} (use compose service name)")
            return subprocess.CompletedProcess(list(args), 0)
        if cfg.filegen or cfg.staging:
            print(f"  systemctl: skipped ({' '.join(args)})")
            return subprocess.CompletedProcess(list(args), 0)
    return run(settings, "systemctl", *args, check=False)


def deploy_sbin_symlink(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    link_src = cfg.adn_deploy_home / "sbin" / "adn-deploy"
    if cfg.filegen:
        if cfg.has_sysroot():
            dest = Path(cfg.adn_sysroot) / "usr/local/sbin/adn-deploy"
        else:
            dest = cfg.adn_root / "usr/local/sbin/adn-deploy"
        run(cfg, "mkdir", "-p", str(dest.parent))
        run(cfg, "ln", "-sf", str(link_src), str(dest))
        print(f"  symlink: {dest}")
    elif not cfg.staging:
        dest = Path("/usr/local/sbin/adn-deploy")
        run(cfg, "mkdir", "-p", str(dest.parent))
        run(cfg, "ln", "-sf", str(link_src), str(dest))
        print(f"  symlink: {dest}")


def disable_legacy_hotspot_proxy(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    if cfg.staging or cfg.dry_run or cfg.filegen:
        return
    for unit in ("hotspot-proxy", "adn-proxy"):
        proc = subprocess.run(
            ["systemctl", "is-enabled", "--quiet", unit],
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            print(f"  systemd: disabling legacy {unit}.service")
            systemctl(cfg, "disable", "--now", unit)


def deploy_systemd_plugins(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    plugins_dir = cfg.paths.plugins
    for pid in _SYSTEMD_PLUGINS:
        if not is_plugin_enabled(plugins_dir, cfg.adn_root, pid):
            continue
        unit = plugin_get(plugins_dir, pid, "systemd.unit")
        tpl = plugin_get(plugins_dir, pid, "systemd.template")
        if not unit or not tpl:
            continue
        src = cfg.adn_deploy_home / "templates" / "systemd" / str(tpl)
        dest = cfg.adn_etc_root / "systemd" / "system" / str(unit)
        render_unit(cfg, src, dest)
    logrotate_deploy(cfg)


def deploy_all(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    if cfg.docker:
        print("  docker: systemd deploy skipped (use compose services)")
        return
    run(cfg, "mkdir", "-p", str(cfg.adn_log_dir))
    run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(cfg.adn_log_dir), check=False)
    monitor_ensure_runtime_dirs(cfg)
    deploy_systemd_plugins(cfg)
    disable_legacy_hotspot_proxy(cfg)
    deploy_sbin_symlink(cfg)
    if cfg.staging or cfg.dry_run:
        print(f"  systemd: templates rendered under {cfg.adn_etc_root} (no daemon-reload in dry-run/staging)")
        return
    systemctl(cfg, "daemon-reload")
    for u in _SYSTEMD_PLUGINS:
        if not is_plugin_enabled(cfg.paths.plugins, cfg.adn_root, u):
            continue
        listed = subprocess.run(
            ["systemctl", "list-unit-files", f"{u}.service"],
            capture_output=True,
            check=False,
        )
        if listed.returncode != 0:
            continue
        systemctl(cfg, "enable", u)


def start_all(settings: Settings | None = None, *, mandatory_incomplete: bool = False) -> bool:
    cfg = settings or init_env()
    if cfg.docker:
        if mandatory_incomplete:
            print("  docker: stack not started — mandatory config incomplete.", file=sys.stderr)
            return False
        proc = subprocess.run(_docker_compose_cmd(cfg, "up", "-d"), check=False)
        if proc.returncode == 0:
            print("  docker: stack started (compose up -d)")
            return True
        print("  docker: compose up failed", file=sys.stderr)
        return False
    if cfg.staging or cfg.dry_run:
        return True
    if mandatory_incomplete:
        print("  systemd: units not started — mandatory config incomplete.", file=sys.stderr)
        return False
    started = False
    for u in _SYSTEMD_PLUGINS:
        if not is_plugin_enabled(cfg.paths.plugins, cfg.adn_root, u):
            continue
        if subprocess.run(["systemctl", "list-unit-files", f"{u}.service"], capture_output=True).returncode != 0:
            continue
        if subprocess.run(["systemctl", "is-active", "--quiet", u], capture_output=True).returncode == 0:
            continue
        if systemctl(cfg, "start", u).returncode == 0:
            started = True
    if started:
        print("  systemd: started enabled ADN units")
    else:
        print("  systemd: enabled ADN units already running")
    return True


def install_all(settings: Settings | None = None, *, mandatory_incomplete: bool = False) -> None:
    deploy_all(settings)
    start_all(settings, mandatory_incomplete=mandatory_incomplete)


def services_cmd(
    settings: Settings | None,
    action: str,
    unit: str = "",
) -> int:
    cfg = settings or init_env()
    if action not in ("start", "stop", "restart", "status", "enable", "disable"):
        print("usage: service <start|stop|restart|status|enable|disable> [unit]", file=sys.stderr)
        return 1
    if action == "start" and not unit and not cfg.docker and not cfg.staging and not cfg.dry_run:
        from adn_deploy.application import config as app_config

        if app_config.mandatory_fields_incomplete(cfg):
            missing = app_config.mandatory_missing_labels(cfg)
            print(
                "  systemd: units not started — mandatory config incomplete "
                f"({', '.join(missing)}). Run: adn-deploy wizard",
                file=sys.stderr,
            )
            return 1
    if unit:
        return systemctl(cfg, action, unit).returncode
    rc = 0
    for u in _SYSTEMD_PLUGINS:
        if not is_plugin_enabled(cfg.paths.plugins, cfg.adn_root, u):
            continue
        if not cfg.filegen and not cfg.staging:
            if subprocess.run(["systemctl", "list-unit-files", f"{u}.service"], capture_output=True).returncode != 0:
                continue
        proc = systemctl(cfg, action, u)
        if proc.returncode != 0:
            rc = proc.returncode
    return rc


def service_action_message(action: str, unit: str, rc: int, *, docker: bool = False) -> str:
    """Human-readable result for start/stop/restart in the menu."""
    label = unit.removesuffix(".service") if unit.endswith(".service") else unit
    verbs = {
        "start": ("started", "start"),
        "stop": ("stopped", "stop"),
        "restart": ("restarted", "restart"),
    }
    past, inf = verbs.get(action, ("completed", action))
    if rc != 0:
        if docker:
            return (
                f"Could not {inf} container {label}.\n\n"
                f"Check logs: docker logs {label} --tail 50"
            )
        return (
            f"Could not {inf} {label}.\n\n"
            f"Check logs: journalctl -u {label} -n 50 --no-pager"
        )
    if docker:
        return f"Container {label} {past} successfully."
    return f"{label} {past} successfully."
