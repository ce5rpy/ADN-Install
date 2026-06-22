"""Idempotent template render for staging sysroot (filegen render-all)."""

from __future__ import annotations

import os

from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.subprocess_runner import require_root_or_exit, run
from adn_deploy.infra import systemd


def render_all(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    require_root_or_exit(cfg)
    print(f"==> render-all (templates -> ADN_ETC_ROOT={cfg.adn_etc_root})")

    from adn_deploy.application import config as app_config
    from adn_deploy.application import web

    app_config.init_all(cfg)
    if cfg.filegen and os.environ.get("ADN_DEPLOY_NON_INTERACTIVE") == "1":
        app_config.wizard_filegen_defaults(cfg)

    run(cfg, "mkdir", "-p", str(cfg.adn_log_dir))
    run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(cfg.adn_log_dir), check=False)
    systemd.monitor_ensure_runtime_dirs(cfg)
    systemd.deploy_systemd_plugins(cfg)
    systemd.deploy_sbin_symlink(cfg)
    web.nginx_render(cfg)
    web.certbot_deploy_hook(cfg)

    print("==> render-all complete")
