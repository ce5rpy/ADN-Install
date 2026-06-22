"""System user adn and sudo policy."""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.paths import map_host_path
from adn_deploy.core.subprocess_runner import is_dry_run, run


def user_home_dir(settings: Settings) -> Path:
    if settings.adn_user_home:
        return Path(settings.adn_user_home)
    if str(settings.adn_root) != "/opt" or settings.staging:
        return settings.adn_root / "home" / settings.adn_user
    return Path(f"/home/{settings.adn_user}")


def _host_path(settings: Settings, path: str | Path) -> Path:
    return map_host_path(
        path,
        sysroot=settings.adn_sysroot,
        adn_root=settings.adn_root,
        deploy_home=settings.adn_deploy_home,
    )


def ensure_sudo(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dropin_path = _host_path(cfg, f"/etc/sudoers.d/adn-deploy")

    if not shutil.which("sudo"):
        if cfg.skip_os_packages:
            if not cfg.filegen:
                print("  sudo: not installed (os packages skipped)", file=sys.stderr)
                return False
            print("  filegen: sudo package skipped (no apt)")
        else:
            print("  sudo: installing package ...")
            os.environ.setdefault("DEBIAN_FRONTEND", "noninteractive")
            run(cfg, "apt-get", "update", "-y")
            run(cfg, "apt-get", "install", "-y", "--no-install-recommends", "sudo")

    try:
        pwd.getpwnam(cfg.adn_user)
        if not cfg.filegen and shutil.which("sudo"):
            groups = subprocess.run(
                ["id", "-nG", cfg.adn_user],
                capture_output=True,
                text=True,
                check=False,
            )
            if "sudo" not in (groups.stdout or "").split():
                print(f"  sudo: adding {cfg.adn_user} to group sudo")
                run(cfg, "usermod", "-aG", "sudo", cfg.adn_user)
    except KeyError:
        pass

    if cfg.adn_sudo_nopasswd != "1":
        print("  sudo: NOPASSWD disabled (user must use sudo with password)")
        if cfg.filegen and dropin_path.is_file():
            run(cfg, "rm", "-f", str(dropin_path))
        return True

    try:
        pwd.getpwnam(cfg.adn_user)
    except KeyError:
        print(f"  sudo: skip sudoers drop-in (user {cfg.adn_user} missing)")
        return True

    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write(f"{cfg.adn_user} ALL=(ALL) NOPASSWD:ALL\n")
        tmp_path = tmp.name
    os.chmod(tmp_path, 0o440)

    if is_dry_run(cfg):
        print(f"[dry-run] sudoers {dropin_path}: {cfg.adn_user} NOPASSWD:ALL")
        os.unlink(tmp_path)
        return True

    if shutil.which("visudo"):
        if subprocess.run(["visudo", "-cf", tmp_path], capture_output=True).returncode != 0:
            print("  sudo: visudo validation failed for adn-deploy", file=sys.stderr)
            os.unlink(tmp_path)
            return False

    run(cfg, "mkdir", "-p", str(dropin_path.parent))
    run(cfg, "install", "-m", "0440", "-o", "root", "-g", "root", tmp_path, str(dropin_path))
    os.unlink(tmp_path)
    print(f"  sudo: {dropin_path} ({cfg.adn_user} NOPASSWD:ALL)")
    return True


def set_password(settings: Settings, user: str, password: str) -> bool:
    if is_dry_run(settings):
        print(f"[dry-run] chpasswd for {user}")
        return True
    proc = subprocess.run(
        ["chpasswd"],
        input=f"{user}:{password}\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"  user: failed to set password for {user}", file=sys.stderr)
        return False
    print(f"  user: login password set for {user}")
    return True


def ensure_user_adn(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.filegen:
        cfg.adn_user = cfg.adn_user or os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"
        print(f"  filegen: deploy user {cfg.adn_user} (no system useradd)")
        return ensure_sudo(cfg)

    if cfg.adn_create_user != "1":
        try:
            pwd.getpwnam(cfg.adn_user)
            print(f"  user: {cfg.adn_user} exists (ADN_CREATE_USER=0)")
        except KeyError:
            print(f"  user: {cfg.adn_user} missing and ADN_CREATE_USER=0", file=sys.stderr)
            return False
        return ensure_sudo(cfg)

    home = user_home_dir(cfg)
    try:
        pwd.getpwnam(cfg.adn_user)
        print(f"  user: {cfg.adn_user} exists")
        return ensure_sudo(cfg)
    except KeyError:
        pass

    password = os.environ.get("ADN_USER_PASSWORD", "")
    if not password:
        print("  user: set ADN_USER_PASSWORD for non-interactive install", file=sys.stderr)
        return False

    print(f"  user: creating {cfg.adn_user} (home={home})")
    if subprocess.run(["getent", "group", cfg.adn_user], capture_output=True).returncode != 0:
        run(cfg, "groupadd", cfg.adn_user, check=False)
        run(cfg, "groupadd", "-r", cfg.adn_user, check=False)
    run(cfg, "mkdir", "-p", str(home.parent))
    run(cfg, "useradd", "-m", "-d", str(home), "-s", "/bin/bash", "-g", cfg.adn_user, cfg.adn_user)
    if password:
        set_password(cfg, cfg.adn_user, password)
    return ensure_sudo(cfg)


def opt_adn_paths(settings: Settings) -> list[Path]:
    seen: set[str] = set()
    paths: list[Path] = []
    for p in (
        settings.adn_deploy_home,
        settings.adn_dmr_server_path,
        settings.adn_monitor_path,
        settings.adn_pyenv_root,
    ):
        if p is None:
            continue
        ps = str(p)
        if not Path(ps).exists() or ps in seen:
            continue
        seen.add(ps)
        paths.append(Path(ps))
    return paths


def opt_chown_tree(settings: Settings, dest: Path, user: str) -> bool:
    if is_dry_run(settings):
        print(f"[dry-run] chown -R {user}:{user} {dest}")
        return True
    proc = run(settings, "chown", "-R", f"{user}:{user}", str(dest), check=False)
    if proc.returncode != 0:
        print(f"  WARN: chown -R {user}:{user} {dest} failed", file=sys.stderr)
        return False
    return True


def fix_permissions(settings: Settings | None = None) -> None:
    cfg = settings or init_env()
    user = cfg.adn_user
    if cfg.docker or cfg.dry_run or cfg.filegen:
        return
    try:
        pwd.getpwnam(user)
    except KeyError:
        print(f"  permissions: skip (user {user} missing)", file=sys.stderr)
        return

    print(f"  permissions: ADN_USER={user} ADN_ROOT={cfg.adn_root}")
    for p in opt_adn_paths(cfg):
        print(f"  permissions: chown -R {user}:{user} {p}")
        opt_chown_tree(cfg, p, user)

    home = cfg.adn_deploy_home
    if home.is_dir():
        for pattern in ("*.sh",):
            for f in home.rglob(pattern):
                if "sbin" in f.parts or "scripts" in f.parts or f.suffix == ".sh":
                    run(cfg, "chmod", "u+rx,g+rx", str(f), check=False)

    from adn_deploy.application import config as app_config

    conf = cfg.adn_deploy_conf
    if conf:
        app_config.deploy_conf_fix_perms(cfg, conf)
