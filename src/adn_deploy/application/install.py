"""Full install orchestration (foundation → apps → config → systemd → web)."""

from __future__ import annotations

import os
import sys

from adn_deploy.application import config as app_config
from adn_deploy.application import doctor
from adn_deploy.application import preflight
from adn_deploy.application import users
from adn_deploy.application import web
from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.subprocess_runner import require_root_or_exit
from adn_deploy.domain.plugins import is_plugin_enabled, plugin_peer_stack_enabled, topo_order
from adn_deploy.infra import git_repos
from adn_deploy.infra import os_bootstrap
from adn_deploy.infra import systemd
from adn_deploy.infra import templates
from adn_deploy.infra import ufw as ufw_infra

OS_BOOTSTRAP_MARKER = ".os-bootstrap-done"


def os_bootstrap_done(settings: Settings) -> bool:
    return (settings.adn_deploy_home / OS_BOOTSTRAP_MARKER).is_file()


def _phase(name: str) -> None:
    print("")
    print(f"=== Phase: {name} ===")


def install_summary(settings: Settings) -> None:
    print("")
    print("=== Install summary ===")
    try:
        py = settings.pyenv_python()
        py_label = str(py)
    except FileNotFoundError:
        py_label = "?"
    print(f"  Done: OS packages, pyenv ({py_label}), git trees, Python deps")
    if settings.profile == "full":
        print("  Done: MariaDB bootstrap, npm build (if web phase succeeded)")
    print("  Done: systemd units enabled (not started until config is complete)")
    if app_config.mandatory_fields_incomplete(settings):
        print("")
        print("  Next steps:")
        print("    1. adn-deploy wizard — set SERVER_ID, dashboard title, and panel hostname")
        print("    2. adn-deploy service start")
        print("    3. Web menu → Enable SSL when ready (optional)")
    else:
        print("")
        print("  Next: adn-deploy service start  (or adn-deploy menu)")
    print("")


def install_foundation(
    settings: Settings | None = None,
    *,
    skip_os: bool = False,
    skip_pyenv: bool = False,
) -> bool:
    cfg = settings or init_env()
    _phase("Foundation")
    if os_bootstrap_done(cfg):
        print("  os-base: skipped (install.sh already ran — .os-bootstrap-done)")
        skip_os = True
    elif skip_os:
        print("  os-base: skipped by caller")
    if not skip_os and not os_bootstrap.bootstrap_plugin_prereqs(cfg):
        return False
    plugins = cfg.paths.plugins
    order = topo_order(plugins, cfg.profile)
    for pid in order:
        if pid == "os-base" and is_plugin_enabled(plugins, cfg.adn_root, pid):
            if skip_os:
                continue
            if not os_bootstrap.bootstrap_install(cfg):
                return False
        elif pid == "pyenv" and is_plugin_enabled(plugins, cfg.adn_root, pid):
            if skip_pyenv:
                print("  pyenv: skipped by caller")
                continue
            if not os_bootstrap.bootstrap_pyenv(cfg):
                return False
        elif pid == "ufw" and is_plugin_enabled(plugins, cfg.adn_root, pid):
            ufw_infra.install_package(cfg)
    return True


def install_apps(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    _phase("Apps")
    plugins = cfg.paths.plugins
    err = False
    if plugin_peer_stack_enabled(plugins, cfg.adn_root):
        err = not git_repos.clone_peer(cfg) or err
    if is_plugin_enabled(plugins, cfg.adn_root, "adn-monitor"):
        err = not git_repos.clone_monitor(cfg) or err
    if is_plugin_enabled(plugins, cfg.adn_root, "daprs"):
        err = not git_repos.clone_daprs(cfg) or err
    if err:
        return False
    if plugin_peer_stack_enabled(plugins, cfg.adn_root):
        err = not os_bootstrap.pip_peer(cfg) or err
    if is_plugin_enabled(plugins, cfg.adn_root, "adn-monitor"):
        err = not os_bootstrap.pip_monitor(cfg) or err
    if is_plugin_enabled(plugins, cfg.adn_root, "daprs"):
        err = not os_bootstrap.pip_daprs(cfg) or err
    return not err and git_repos.assert_install_trees(cfg)


def install_fix_permissions(settings: Settings | None = None) -> None:
    _phase("Permissions")
    users.fix_permissions(settings)


def setup_pyenv(settings: Settings | None = None) -> bool:
    """Install pyenv Python, pip install -e adn-deploy, persist ADN_PYENV_PYTHON."""
    cfg = settings or init_env()
    require_root_or_exit(cfg)
    if not os_bootstrap_done(cfg):
        print(
            "  pyenv: run install.sh first (OS packages — .os-bootstrap-done missing)",
            file=sys.stderr,
        )
        return False
    app_config.deploy_conf_init(cfg)
    if not os_bootstrap.bootstrap_pyenv(cfg):
        return False
    if not app_config.persist_pyenv_python(cfg):
        return False
    if not os_bootstrap.pip_all(cfg):
        return False
    users.fix_permissions(cfg)
    print("  pyenv: ready — systemd and pip use ADN_PYENV_PYTHON from deploy.conf")
    return True


def install_stack(settings: Settings | None = None) -> bool:
    """Apps, config, systemd, web — after install.sh (OS) and pyenv."""
    cfg = settings or init_env()
    require_root_or_exit(cfg)
    if not os_bootstrap_done(cfg):
        print(
            "  stack: run install.sh first (.os-bootstrap-done missing)",
            file=sys.stderr,
        )
        return False
    try:
        cfg.pyenv_python()
    except FileNotFoundError:
        print("  stack: run adn-deploy pyenv or menu → Python environment first", file=sys.stderr)
        return False
    if not preflight.run(cfg):
        return False
    app_config.deploy_conf_init(cfg)
    print(f"  stack: starting (profile={cfg.profile}) ...")
    if not install_apps(cfg):
        return False
    _phase("Config")
    app_config.init_all(cfg)
    app_config.install_first_run_setup(cfg)
    if cfg.profile == "full" and not cfg.skip_os_packages:
        _phase("MySQL")
        if not web.mysql_bootstrap(cfg):
            print(
                "  WARN: MySQL setup failed — adn-server needs DATABASE; run: adn-deploy web mysql",
                file=sys.stderr,
            )
    _phase("Systemd")
    systemd.deploy_all(cfg)
    if cfg.profile == "full":
        _phase("Web")
        if is_plugin_enabled(cfg.paths.plugins, cfg.adn_root, "adn-web"):
            print("  web: mysql/bootstrap during stack; npm/nginx after install wizard")
    incomplete = app_config.mandatory_fields_incomplete(cfg)
    if incomplete:
        print("  stack: services not started — complete mandatory config (adn-deploy wizard)")
    else:
        systemd.start_all(cfg, mandatory_incomplete=False)
    if cfg.filegen:
        templates.render_all(cfg)
    install_fix_permissions(cfg)
    doctor.run(cfg)
    install_summary(cfg)
    return True


def post_mandatory_wizard_setup(settings: Settings | None = None) -> bool:
    """After mandatory wizard: nginx vhost and restart ADN units (npm build is install phase)."""
    return finalize_bare_metal_install(settings)


def finalize_bare_metal_install(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.filegen:
        return True
    if app_config.mandatory_fields_incomplete(cfg):
        print("  finalize: mandatory config still incomplete", file=sys.stderr)
        return False
    if cfg.docker:
        app_config.sync_docker_wizard_config(cfg)
        return systemd.start_all(cfg, mandatory_incomplete=False)
    ok = True
    print("")
    print("==> Finalize: DMR alias files")
    app_config.ensure_alias_files(cfg)
    dist = cfg.adn_monitor_path / "frontend" / "dist"
    if not dist.is_dir():
        print("==> Finalize: frontend build (npm)")
        web.build_assets(cfg)
        if not dist.is_dir():
            print("  WARN: frontend/dist still missing after npm build", file=sys.stderr)
            ok = False
    else:
        print("  finalize: frontend dist present")
    print("==> Finalize: nginx vhost")
    if not web.nginx_render(cfg):
        ok = False
    print("")
    print("==> Finalize: restart services")
    if systemd.services_cmd(cfg, "restart") != 0:
        ok = False
    return ok


def run(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    require_root_or_exit(cfg)
    if not preflight.run(cfg):
        return False
    app_config.deploy_conf_init(cfg)
    if not app_config.wizard_user(cfg):
        return False
    print(f"  install: starting (profile={cfg.profile}) ...")
    skip_os = os_bootstrap_done(cfg)
    if not install_foundation(cfg, skip_os=skip_os):
        return False
    if not setup_pyenv(cfg):
        return False
    return install_stack(cfg)
