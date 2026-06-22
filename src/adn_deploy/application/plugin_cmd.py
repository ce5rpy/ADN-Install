"""Plugin enable/disable commands."""

from __future__ import annotations

from adn_deploy.application import install as app_install
from adn_deploy.core.env import Settings, init_env
from adn_deploy.domain.plugins import is_plugin_enabled, plugin_get, set_plugin_enabled, topo_order
from adn_deploy.infra import os_bootstrap, systemd


def _install_one(settings: Settings, plugin_id: str) -> bool:
    if not is_plugin_enabled(settings.paths.plugins, settings.adn_root, plugin_id):
        print(f"==> plugin {plugin_id} (skipped, disabled)")
        return True
    print(f"==> plugin {plugin_id}")
    if plugin_id == "os-base":
        return os_bootstrap.bootstrap_install(settings)
    if plugin_id == "pyenv":
        return os_bootstrap.bootstrap_pyenv(settings)
    if plugin_id in ("adn-server", "adn-echo", "adn-monitor", "adn-web"):
        print(f"  {plugin_id}: deferred (Apps / Config phases)")
        return True
    if plugin_id == "ufw":
        from adn_deploy.infra import ufw as ufw_infra

        return ufw_infra.install_package(settings)
    if plugin_id == "daprs":
        from adn_deploy.application import config as app_config
        from adn_deploy.infra import git_repos

        ok = git_repos.clone_daprs(settings) and os_bootstrap.pip_daprs(settings)
        app_config.init_daprs(settings)
        return ok
    print(f"  (no install hook for {plugin_id})")
    return True


def run(settings: Settings | None, action: str, plugin_id: str) -> int:
    cfg = settings or init_env()
    if action == "enable":
        if not plugin_id:
            print("usage: plugin enable <id>", file=__import__("sys").stderr)
            return 1
        set_plugin_enabled(cfg.adn_root, plugin_id, enabled=True)
        _install_one(cfg, plugin_id)
        systemd.deploy_all(cfg)
        unit = plugin_get(cfg.paths.plugins, plugin_id, "systemd.unit")
        if unit:
            systemd.systemctl(cfg, "enable", plugin_id)
            systemd.systemctl(cfg, "start", plugin_id)
        return 0
    if action == "disable":
        if not plugin_id:
            print("usage: plugin disable <id>", file=__import__("sys").stderr)
            return 1
        set_plugin_enabled(cfg.adn_root, plugin_id, enabled=False)
        return 0
    print("usage: plugin enable|disable <id>", file=__import__("sys").stderr)
    return 1
