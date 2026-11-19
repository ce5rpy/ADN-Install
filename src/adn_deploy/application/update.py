"""Update flow: git pull, pip, redeploy units."""

from __future__ import annotations

import os
import subprocess
import sys

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


def update_one(settings: Settings, plugin_id: str) -> bool:
    """Update a single plugin (git fetch/checkout configured ref + pip)."""
    return _update_one(settings, plugin_id)


def _update_one(settings: Settings, plugin_id: str) -> bool:
    plugins = settings.paths.plugins
    if not is_plugin_enabled(plugins, settings.adn_root, plugin_id):
        return True
    if plugin_id == "os-base":
        print("  os-base: apt update (optional)")
    elif plugin_id == "pyenv":
        os_bootstrap.bootstrap_pyenv(settings)
    elif plugin_id in ("adn-server", "adn-echo", "adn-odtp"):
        if not git_repos.git_pull_peer(settings):
            return False
        os_bootstrap.pip_peer(settings)
    elif plugin_id == "adn-monitor":
        if not git_repos.git_pull_monitor(settings):
            return False
        os_bootstrap.pip_monitor(settings)
    elif plugin_id == "adn-web":
        web.update(settings)
    elif plugin_id == "daprs":
        if not git_repos.git_pull_daprs(settings):
            return False
        os_bootstrap.pip_daprs(settings)
        app_config.init_daprs(settings)
    elif plugin_id == "ufw":
        pass
    return True


# Set when the update re-runs itself after the toolkit changed (skip the toolkit step).
_REEXEC_ENV = "ADN_UPDATE_REEXEC"


def _continue_with_new_toolkit(cfg: Settings, *, replace_process: bool) -> bool:
    """The toolkit changed on disk, but this process still runs the old modules:
    run the rest of the update with the new code (new plugins such as adn-odtp)."""
    wrapper = str(cfg.adn_deploy_home / "sbin" / "adn-deploy")
    env = {**os.environ, _REEXEC_ENV: "1"}
    print("  deploy: toolkit changed — continuing the update with the new code")
    sys.stdout.flush()
    sys.stderr.flush()
    if replace_process:
        os.execve(wrapper, [wrapper, *sys.argv[1:]], env)
    proc = subprocess.run([wrapper, "update"], env=env, capture_output=True, text=True, check=False)
    print(proc.stdout, end="")
    print(proc.stderr, end="", file=sys.stderr)
    return proc.returncode == 0


def run(settings: Settings | None = None, *, reexec: bool = False) -> bool:
    """reexec=True (CLI): replace this process after a toolkit change; else run a child."""
    cfg = settings or init_env()
    require_root_or_exit(cfg)
    if os.environ.get(_REEXEC_ENV) != "1":
        before = git_repos.deploy_head(cfg)
        if not update_deploy_toolkit(cfg):
            return False
        if git_repos.deploy_head(cfg) != before:
            return _continue_with_new_toolkit(cfg, replace_process=reexec)
    order = topo_order(cfg.paths.plugins, cfg.profile)
    peer_done = False
    for pid in order:
        if pid in ("adn-server", "adn-echo", "adn-odtp"):
            if peer_done:  # same clone: update once
                continue
            peer_done = True
        if not _update_one(cfg, pid):
            print(f"  update: {pid} failed — services left unchanged", file=sys.stderr)
            return False
    app_config.init_peer(cfg)
    app_config.init_echo(cfg)
    app_config.init_odtp(cfg)
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
