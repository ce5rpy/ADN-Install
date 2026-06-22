"""Resolve ADN-Deploy filesystem paths from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def deploy_home_from_env() -> Path | None:
    raw = os.environ.get("ADN_DEPLOY_HOME", "").strip()
    if not raw:
        return None
    return _resolve(raw)


def default_deploy_home() -> Path:
    """Repository root when ``ADN_DEPLOY_HOME`` is unset."""
    # src/adn_deploy/core/paths.py -> repo root
    return Path(__file__).resolve().parents[3]


def get_deploy_home() -> Path:
    return deploy_home_from_env() or default_deploy_home()


@dataclass(frozen=True)
class DeployPaths:
    """Canonical ADN-Deploy path layout."""

    home: Path
    plugins: Path
    templates: Path
    lib: Path
    config_schemas: Path
    sbin: Path
    docker: Path

    @classmethod
    def from_home(cls, home: Path | None = None) -> DeployPaths:
        root = home or get_deploy_home()
        return cls(
            home=root,
            plugins=root / "plugins",
            templates=root / "templates",
            lib=root / "lib",
            config_schemas=root / "config" / "schemas",
            sbin=root / "sbin",
            docker=root / "docker",
        )


def deploy_conf_path(*, adn_root: Path | None = None, deploy_home: Path | None = None) -> Path:
    env_conf = os.environ.get("ADN_DEPLOY_CONF", "").strip()
    if env_conf:
        return _resolve(env_conf)
    root = adn_root or Path(os.environ.get("ADN_ROOT", "/opt"))
    home = deploy_home or (root / "ADN-Install")
    return home / "deploy.conf"


def plugins_enabled_state(adn_root: Path) -> Path:
    return adn_root / "ADN-Install" / ".plugins-enabled"


def mandatory_setup_done_marker(home: Path | None = None) -> Path:
    return (home or get_deploy_home()) / ".mandatory-setup-done"


def deploy_overrides_manifest(home: Path | None = None) -> Path:
    return (home or get_deploy_home()) / "templates" / "config" / "deploy-overrides.yaml"


def monitor_arrays_schema(home: Path | None = None) -> Path:
    return (home or get_deploy_home()) / "config" / "schemas" / "adn-monitor-arrays.yaml"


def map_host_path(
    path: str | Path,
    *,
    sysroot: str = "",
    adn_root: Path | None = None,
    deploy_home: Path | None = None,
) -> Path:
    """Map absolute host paths into ``ADN_SYSROOT`` when active (``lib/env.sh`` ``adn_path``)."""
    p = str(path)
    if not sysroot:
        return Path(p)
    root = Path(sysroot)
    adn_root = adn_root or (root / "opt")
    deploy_home = deploy_home or (adn_root / "ADN-Install")
    if p.startswith(str(root) + "/") or p == str(root):
        return Path(p)
    if p.startswith("/etc/"):
        return root / "etc" / p[5:]
    if p.startswith("/var/"):
        return root / "var" / p[5:]
    if p.startswith("/usr/"):
        return root / "usr" / p[5:]
    if p.startswith("/opt/"):
        return root / "opt" / p[5:]
    return Path(p)
