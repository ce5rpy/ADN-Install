"""Subprocess helpers with dry-run and ADN user execution."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from adn_deploy.core.env import Settings, init_env


class RootRequiredError(PermissionError):
    """Raised when an operation requires root privileges."""


class HostPathBlockedError(RuntimeError):
    """Raised when a sysroot guard blocks a host path."""


def is_dry_run(settings: Settings) -> bool:
    if settings.filegen:
        return False
    return settings.dry_run


def _guard_host_path(settings: Settings, path: str) -> None:
    if not settings.has_sysroot():
        return
    sysroot = Path(settings.adn_sysroot).resolve()
    adn_root = settings.adn_root.resolve()
    deploy_home = settings.adn_deploy_home.resolve()
    p = Path(path).resolve()

    allowed_prefixes = (sysroot, adn_root, deploy_home)
    if any(str(p).startswith(str(prefix)) for prefix in allowed_prefixes):
        return

    blocked_prefixes = ("/etc", "/var", "/usr")
    for prefix in blocked_prefixes:
        if str(p).startswith(prefix + "/") or str(p) == prefix:
            raise HostPathBlockedError(
                f"blocked host path '{path}' (ADN_SYSROOT={settings.adn_sysroot})"
            )

    if str(p).startswith("/opt/") and not str(p).startswith(str(sysroot / "opt")):
        raise HostPathBlockedError(
            f"blocked host path '{path}' (use ADN_ROOT under sysroot)"
        )


def _user_home(settings: Settings) -> Path:
    if settings.adn_user_home:
        return Path(settings.adn_user_home)
    return Path(f"/home/{settings.adn_user}")


def run(
    settings: Settings | None,
    *args: str | Path,
    check: bool = True,
    capture_output: bool = False,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    text: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command, honoring dry-run mode."""
    cfg = settings or init_env()
    cmd = [str(a) for a in args]

    if is_dry_run(cfg):
        print(f"[dry-run] {' '.join(cmd)}", file=sys.stderr)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    for arg in cmd:
        if arg.startswith("/"):
            _guard_host_path(cfg, arg)

    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        env=dict(env) if env is not None else None,
        cwd=str(cwd) if cwd is not None else None,
        text=text,
    )


def run_as_adn(
    settings: Settings | None,
    command: str,
    *,
    quiet: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[Any] | None:
    """Run a shell command as ``ADN_USER`` (matches ``adn_run_as_adn_c``)."""
    cfg = settings or init_env()
    home = _user_home(cfg)
    wrapped = f"cd {home!s} && {command}"

    if is_dry_run(cfg):
        if not quiet:
            print(
                f"[dry-run] sudo -u {cfg.adn_user} env HOME={home} bash -c {wrapped!r}",
                file=sys.stderr,
            )
        return None

    if cfg.filegen:
        if not quiet:
            print(f"+ env HOME={home} bash -c {wrapped!r}", file=sys.stderr)
        return subprocess.run(
            ["bash", "-c", wrapped],
            check=check,
            env={**os.environ, "HOME": str(home)},
        )

    if not quiet:
        print(
            f"+ sudo -u {cfg.adn_user} env HOME={home} bash -c {wrapped!r}",
            file=sys.stderr,
        )
    return subprocess.run(
        ["sudo", "-u", cfg.adn_user, "env", f"HOME={home}", "bash", "-c", wrapped],
        check=check,
    )


def require_root(settings: Settings | None = None) -> None:
    """Exit or raise if not root (filegen/sysroot writable bypass)."""
    cfg = settings or init_env()
    if cfg.filegen and cfg.has_sysroot():
        sysroot = Path(cfg.adn_sysroot)
        if sysroot.is_dir() and os.access(sysroot, os.W_OK):
            return
    if os.geteuid() != 0:
        raise RootRequiredError("adn-deploy: root required (use sudo).")


def require_root_or_exit(settings: Settings | None = None) -> None:
    try:
        require_root(settings)
    except RootRequiredError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
