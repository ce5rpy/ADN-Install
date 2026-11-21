"""`adn-deploy version`: show or change the adn-server / adn-monitor versions (bare metal).

Same command, variables and values as `adn-docker version` (see domain/versions.py).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from adn_deploy.application.config import set_kv
from adn_deploy.core.env import Settings, parse_deploy_conf
from adn_deploy.domain.versions import effective_version, git_ref, normalize_version

# Replaced by ADN_*_VERSION: removed from deploy.conf when a version is set.
_LEGACY_KEYS = {"server": "GIT_BRANCH_PEER", "monitor": "GIT_BRANCH_MONITOR"}
_SPECIFIC_KEYS = {"server": "ADN_SERVER_VERSION", "monitor": "ADN_MONITOR_VERSION"}


def _conf(settings: Settings) -> Path:
    conf = settings.adn_deploy_conf
    if conf is None:
        raise RuntimeError("deploy.conf path is not set")
    return conf


def _remove_keys(settings: Settings, keys: list[str]) -> None:
    conf = _conf(settings)
    if not conf.is_file():
        return
    lines = conf.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not any(ln.startswith(f"{k}=") for k in keys)]
    if kept != lines:
        conf.write_text("\n".join(kept) + "\n", encoding="utf-8")


def current(settings: Settings) -> dict[str, tuple[str, str]]:
    """{component: (version or '', git ref or '')} as configured."""
    out: dict[str, tuple[str, str]] = {}
    for comp, specific in (("server", settings.adn_server_version), ("monitor", settings.adn_monitor_version)):
        try:
            v = effective_version(specific, settings.adn_version)
        except ValueError:
            v = ""
        ref = settings.peer_ref if comp == "server" else settings.monitor_ref
        out[comp] = (v, ref)
    return out


def show(settings: Settings) -> None:
    for comp, (v, ref) in current(settings).items():
        if v:
            label = v
        elif ref:
            label = f"{ref} (from {_LEGACY_KEYS[comp]})"
        else:
            label = "stable"
        print(f"  adn-{comp}: {label}  [git {ref or 'master'}]")
    print("Change with: adn-deploy version stable|develop|X.Y.Z [--server V] [--monitor V]")


def ref_exists(url: str, ref: str) -> bool:
    proc = subprocess.run(
        ["git", "ls-remote", "--exit-code", url, f"refs/heads/{ref}", f"refs/tags/{ref}"],
        capture_output=True, text=True, check=False, timeout=60,
    )
    return proc.returncode == 0


def set_versions(
    settings: Settings, *, both: str = "", server: str = "", monitor: str = "", check_remote: bool = True
) -> bool:
    """Write the versions to deploy.conf (both = ADN_VERSION; server/monitor = per app)."""
    try:
        both_v = normalize_version(both) if both else ""
        wanted = {
            "server": normalize_version(server) if server else both_v,
            "monitor": normalize_version(monitor) if monitor else both_v,
        }
    except ValueError as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        return False
    urls = {"server": settings.git_url_peer, "monitor": settings.git_url_monitor}
    if check_remote:
        for comp, v in wanted.items():
            if v and not ref_exists(urls[comp], git_ref(v)):
                print(f"  ERROR: adn-{comp} {v}: {git_ref(v)} not found in {urls[comp]}", file=sys.stderr)
                return False
    conf = _conf(settings)
    if both_v:
        set_kv(settings, conf, "ADN_VERSION", both_v)
    for comp, v in wanted.items():
        if not v:
            continue
        explicit = server if comp == "server" else monitor
        if explicit:
            set_kv(settings, conf, _SPECIFIC_KEYS[comp], v)
        else:
            _remove_keys(settings, [_SPECIFIC_KEYS[comp]])
        _remove_keys(settings, [_LEGACY_KEYS[comp]])
    # Keys removed from deploy.conf must not survive in the settings already loaded.
    settings.adn_version = settings.adn_server_version = settings.adn_monitor_version = ""
    settings.git_branch_peer = settings.git_branch_monitor = ""
    settings.apply_deploy_conf(parse_deploy_conf(conf))
    for comp, (v, ref) in current(settings).items():
        print(f"  adn-{comp} -> {v or 'stable'} (git {ref or 'master'})")
    return True
