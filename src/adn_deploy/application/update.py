"""Update flow: git pull, pip, redeploy units."""

from __future__ import annotations

from adn_deploy.application import config as app_config
from adn_deploy.application import users
from adn_deploy.application import web
from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.subprocess_runner import require_root_or_exit
from adn_deploy.domain.plugins import is_plugin_enabled, topo_order
from adn_deploy.infra import git_repos
from adn_deploy.infra import os_bootstrap
from adn_deploy.infra import systemd


def update_deploy_toolkit(settings: Settings | None = None) -> bool:
    """git pull ADN-Deploy + pip install -e + refresh CLI symlink."""
    cfg = settings or init_env()
    require_root_or_exit(cfg)
    print("==> Update ADN-Deploy toolkit")
    if not git_repos.git_pull_deploy(cfg):
        return False
    if not os_bootstrap.pip_install_deploy(cfg):
        return False
    systemd.deploy_sbin_symlink(cfg)
    app_config.deploy_conf_fix_perms(cfg)
    print("  deploy: toolkit updated (restart menu/CLI to load new Python code)")
    return True


def update_one(settings: Settings, plugin_id: str) -> None:
    """Update a single plugin (git pull + pip)."""
    _update_one(settings, plugin_id)


def _update_one(settings: Settings, plugin_id: str) -> None:
    plugins = settings.paths.plugins
    if not is_plugin_enabled(plugins, settings.adn_root, plugin_id):
        return
    if plugin_id == "os-base":
        print("  os-base: apt update (optional)")
    elif plugin_id == "pyenv":
        os_bootstrap.bootstrap_pyenv(settings)
    elif plugin_id in ("adn-server", "adn-echo"):
        git_repos.git_pull_peer(settings)
        os_bootstrap.pip_peer(settings)
    elif plugin_id == "adn-monitor":
        git_repos.git_pull_monitor(settings)
        os_bootstrap.pip_monitor(settings)
    elif plugin_id == "adn-web":
        web.update(settings)
    elif plugin_id == "daprs":
        git_repos.git_pull_daprs(settings)
        os_bootstrap.pip_daprs(settings)
        app_config.init_daprs(settings)
    elif plugin_id == "ufw":
        pass


def run(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    require_root_or_exit(cfg)
    if not update_deploy_toolkit(cfg):
        return False
    order = topo_order(cfg.paths.plugins, cfg.profile)
    for pid in order:
        _update_one(cfg, pid)
    app_config.init_peer(cfg)
    app_config.init_echo(cfg)
    app_config.init_daprs(cfg)
    systemd.deploy_all(cfg)
    incomplete = app_config.mandatory_fields_incomplete(cfg)
    systemd.start_all(cfg, mandatory_incomplete=incomplete)
    users.fix_permissions(cfg)
    if incomplete:
        print("  update: units not restarted — complete mandatory config (adn-deploy menu)")
    else:
        systemd.services_cmd(cfg, "restart")
    return True
