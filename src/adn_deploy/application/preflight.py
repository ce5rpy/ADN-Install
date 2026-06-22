"""Preflight checks before install/update."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from adn_deploy.core.env import Settings, init_env


def _read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k] = v.strip().strip('"')
    return data


def blocks_prod_install(settings: Settings) -> bool:
    if settings.staging:
        return False
    if str(settings.adn_root) != "/opt":
        return False
    for legacy in (Path("/opt/new-adn-server"), Path("/opt/adn-dmr-server")):
        if legacy.is_dir():
            proc = subprocess.run(
                ["systemctl", "is-active", "--quiet", "adn-server"],
                capture_output=True,
                check=False,
            )
            if proc.returncode == 0:
                return True
    return False


def run(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    errors = 0
    print("=== ADN-Deploy preflight ===")

    euid = os.geteuid()
    if euid != 0:
        if str(cfg.adn_root) == "/opt" and not cfg.staging:
            print("WARN: production install must run as root (e.g. sudo bash install.sh or sudo adn-deploy install)")
        else:
            print("WARN: not running as root; install/update commands will refuse to continue")
    else:
        print("OK: running as root")

    user = cfg.adn_user
    try:
        import pwd

        pwd.getpwnam(user)
        if not shutil.which("sudo"):
            print(f"NOTE: user {user} exists; install will install and configure sudo")
        else:
            groups = subprocess.run(
                ["id", "-nG", user],
                capture_output=True,
                text=True,
                check=False,
            )
            if "sudo" not in (groups.stdout or "").split():
                print(f"NOTE: user {user} is not in group sudo; install will configure sudo access")
            else:
                print(f"OK: deploy user {user} present")
    except KeyError:
        print(f"NOTE: user {user} not found; install will create it (ADN_CREATE_USER={cfg.adn_create_user})")

    os_release = _read_os_release()
    if not os_release:
        print("FAIL: /etc/os-release missing (need Debian/Ubuntu).", file=sys.stderr)
        errors += 1
    else:
        os_id = os_release.get("ID", "")
        if os_id not in ("debian", "ubuntu"):
            print(f"FAIL: unsupported OS ID={os_id or '?'} (need debian or ubuntu).", file=sys.stderr)
            errors += 1
        else:
            print(f"OK: OS {os_release.get('PRETTY_NAME', os_id)}")

    mem_kb = 0
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        m = re.search(r"MemTotal:\s+(\d+)", meminfo.read_text(encoding="utf-8"))
        mem_kb = int(m.group(1)) if m else 0
    if mem_kb < 3500000:
        print(f"WARN: RAM < 4 GB recommended for pyenv compile ({mem_kb // 1024} MB)")
    else:
        print("OK: RAM sufficient")

    disk_avail = 0
    proc = subprocess.run(["df", "-k", str(cfg.adn_root)], capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        lines = proc.stdout.strip().splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 4:
                disk_avail = int(parts[3])
    if disk_avail < 10485760:
        print(f"WARN: less than 10 GB free on {cfg.adn_root}")
    else:
        print(f"OK: disk space on {cfg.adn_root}")

    if blocks_prod_install(cfg):
        print("FAIL: production ADN stack detected; use ADN_DEPLOY_STAGING=1 and ADN_ROOT≠/opt", file=sys.stderr)
        errors += 1

    if cfg.staging:
        print("OK: staging mode (no system-wide apt/systemd/nginx)")
    if cfg.filegen:
        if cfg.has_sysroot():
            print(f"OK: filegen sysroot (ADN_SYSROOT={cfg.adn_sysroot}, ADN_ROOT={cfg.adn_root})")
        else:
            print(f"OK: filegen mode (writes under ADN_ROOT={cfg.adn_root})")
    if cfg.dry_run:
        print("OK: dry-run mode")

    if shutil.which("curl") or shutil.which("wget"):
        print("OK: curl/wget present")
    elif cfg.skip_os_packages:
        print("OK: curl/wget not required (skip os packages)")
    else:
        print("OK: curl/wget will be installed by os-base")

    if shutil.which("git"):
        print("OK: git present")
    elif cfg.skip_os_packages:
        print("OK: git not required (skip os packages)")
    else:
        print("OK: git will be installed by os-base")

    pyenv_root = cfg.adn_pyenv_root or cfg.adn_root / ".pyenv"
    shim = pyenv_root / "shims" / "python3"
    if shim.is_file() and os.access(shim, os.X_OK):
        print("OK: pyenv python present")
    elif cfg.skip_os_packages:
        print("OK: pyenv optional (filegen/staging)")
    else:
        print("OK: pyenv/Python will be installed during install")

    if errors:
        print(f"Preflight: {errors} error(s)", file=sys.stderr)
        return False
    print("Preflight: passed")
    return True
