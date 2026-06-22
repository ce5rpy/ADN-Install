"""OS bootstrap: apt packages and pyenv via bootstrap_pyenv.sh."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.subprocess_runner import is_dry_run, run, run_as_adn
from adn_deploy.infra import git_repos


_WEB_SECTION = re.compile(r"^#\s*D\)\s")


def package_list(settings: Settings) -> Path:
    if Path("/etc/os-release").is_file():
        text = Path("/etc/os-release").read_text(encoding="utf-8")
        if re.search(r'^ID=ubuntu', text, re.MULTILINE):
            return settings.adn_deploy_home / "install" / "packages" / "ubuntu-minimal.txt"
    return settings.adn_deploy_home / "install" / "packages" / "debian-minimal.txt"


def read_package_names(list_path: Path, profile: str = "full") -> list[str]:
    if not list_path.is_file():
        return []
    skip_web = profile == "minimal"
    past_web = False
    pkgs: list[str] = []
    for line in list_path.read_text(encoding="utf-8").splitlines():
        if _WEB_SECTION.match(line):
            past_web = True
            continue
        if skip_web and past_web:
            continue
        pkg = line.split("#", 1)[0].strip()
        if pkg:
            pkgs.append(pkg)
    return pkgs


def export_apt_noninteractive() -> dict[str, str]:
    return {
        **os.environ,
        "DEBIAN_FRONTEND": "noninteractive",
        "DEBCONF_NONINTERACTIVE_SEEN": "true",
        "NEEDRESTART_MODE": "a",
    }


def _print_package_list(packages: list[str], width: int = 76) -> None:
    line = ""
    for pkg in packages:
        chunk = f"    {pkg}" if not line else f"{line}, {pkg}"
        if len(chunk) > width:
            if line:
                print(line)
            line = f"    {pkg}"
        else:
            line = chunk
    if line:
        print(line)


def apt_install_verbose(settings: Settings, label: str, packages: list[str]) -> bool:
    if not packages:
        print(f"  {label}: no packages to install", file=sys.stderr)
        return False
    if is_dry_run(settings):
        print(f"[dry-run] apt-get install ({len(packages)} packages): {' '.join(packages)}")
        return True
    print(f"  {label}: will install {len(packages)} package(s):")
    _print_package_list(packages)
    print(f"  {label}: starting apt-get install (live output + status every 5s) ...")
    apt_opts = [
        "install",
        "-y",
        "--no-install-recommends",
        "-o",
        "Dpkg::Options::=--force-confdef",
        "-o",
        "Dpkg::Options::=--force-confold",
    ]
    if sys.stdout.isatty():
        apt_opts.extend(["-o", "Dpkg::Progress-Fancy=1"])
    marks = "|/-\\"
    stop = threading.Event()

    def heartbeat() -> None:
        start = time.monotonic()
        i = 0
        while not stop.wait(5):
            spin = marks[i % 4]
            i += 1
            elapsed = int(time.monotonic() - start)
            print(f"  {label}: [{spin}] still installing... {elapsed}s elapsed")

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()
    print(f"+ apt-get {' '.join(apt_opts)} ({len(packages)} packages)")
    rc = subprocess.run(
        ["apt-get", *apt_opts, *packages],
        env=export_apt_noninteractive(),
        check=False,
    ).returncode
    stop.set()
    hb.join(timeout=1)
    if rc == 0:
        print(f"  {label}: apt install finished ({len(packages)} packages)")
        return True
    print(f"  {label}: apt install failed", file=sys.stderr)
    return False


def bootstrap_plugin_prereqs(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.skip_os_packages:
        return True
    if shutil.which("python3"):
        proc = subprocess.run(["python3", "-c", "import yaml"], capture_output=True, check=False)
        if proc.returncode == 0:
            return True
    print("  os-base: python3-yaml for plugin engine ...")
    run(cfg, "apt-get", "update", "-y")
    return apt_install_verbose(cfg, "os-base", ["python3-yaml", "ca-certificates"])


def bootstrap_install(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    if cfg.skip_os_packages:
        print("  os-base: skipped (ADN_DEPLOY_SKIP_OS_PACKAGES / filegen — no apt)")
        if cfg.filegen:
            from adn_deploy.application import users

            users.ensure_user_adn(cfg)
            run(cfg, "mkdir", "-p", str(cfg.adn_log_dir))
        return True
    list_path = package_list(cfg)
    if not list_path.is_file():
        print(f"  os-base: package list missing: {list_path}", file=sys.stderr)
        return False
    pkgs = read_package_names(list_path, cfg.profile)
    if not pkgs:
        print(f"  os-base: no packages in {list_path}", file=sys.stderr)
        return False
    print(f"  os-base: apt install ({len(pkgs)} packages, profile={cfg.profile}) from {list_path.name}")
    run(cfg, "apt-get", "update", "-y")
    if not apt_install_verbose(cfg, "os-base", pkgs):
        return False
    from adn_deploy.application import users

    users.ensure_sudo(cfg)
    users.ensure_user_adn(cfg)
    run(cfg, "mkdir", "-p", str(cfg.adn_log_dir))
    run(cfg, "chown", f"{cfg.adn_user}:{cfg.adn_user}", str(cfg.adn_log_dir), check=False)
    return True


def pip_install_deploy(settings: Settings | None = None) -> bool:
    """Reinstall adn-deploy package editable after git pull."""
    cfg = settings or init_env()
    home = cfg.adn_deploy_home
    project = home / "pyproject.toml"
    if not project.is_file():
        print(f"  deploy: no pyproject.toml at {home} — skip pip -e")
        return True
    if is_dry_run(cfg):
        print(f"[dry-run] pip install -e {home}")
        return True
    if not pyenv_m_pip(cfg, "install", "-e", str(home)):
        print(f"ERROR: pip install -e {home} failed", file=sys.stderr)
        return False
    print(f"  deploy: pip install -e {home}")
    return True


def bootstrap_pyenv(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    script = cfg.adn_deploy_home / "scripts" / "bootstrap_pyenv.sh"
    if not script.is_file():
        print(f"ERROR: missing {script}", file=sys.stderr)
        return False
    env = os.environ.copy()
    env.update(cfg.to_env_dict())
    env["ADN_PYENV_REINSTALL"] = os.environ.get("ADN_PYENV_REINSTALL", "0")
    env["ADN_DEPLOY_DRY_RUN"] = "1" if cfg.dry_run and not cfg.filegen else "0"
    env["ADN_DEPLOY_FILEGEN"] = "1" if cfg.filegen else "0"
    if cfg.adn_user_home:
        env["ADN_USER_HOME"] = cfg.adn_user_home
    if is_dry_run(cfg) and not cfg.filegen:
        print(f"[dry-run] bash {script}")
        return True
    print(f"+ bash {script}")
    proc = subprocess.run(["bash", str(script)], env=env, check=False)
    if proc.returncode != 0:
        return False
    try:
        cfg.adn_pyenv_python = cfg.pyenv_python()
    except FileNotFoundError:
        pass
    return True


def pyenv_m_pip(settings: Settings, *args: str) -> bool:
    try:
        py = settings.pyenv_python()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return False
    print(f"  pip: {py} -m pip {' '.join(args)}")
    proc = run_as_adn(settings, f"{py} -m pip {' '.join(args)}", check=False)
    return proc is None or proc.returncode == 0


def verify_import(settings: Settings, module: str, *, quiet: bool = False) -> bool:
    try:
        py = settings.pyenv_python()
    except FileNotFoundError:
        return False
    cmd = f"{py} -c 'import {module}'"
    proc = run_as_adn(settings, cmd, quiet=quiet, check=False)
    return proc is None or proc.returncode == 0


def verify_imports(settings: Settings, *modules: str) -> bool:
    if not modules:
        return True
    code = "import " + ", ".join(modules)
    try:
        py = settings.pyenv_python()
    except FileNotFoundError:
        return False
    proc = run_as_adn(settings, f"{py} -c {code!r}", quiet=True, check=False)
    return proc is None or proc.returncode == 0


def mysql_build_deps_ok(settings: Settings) -> bool:
    if settings.skip_os_packages or settings.filegen:
        return True
    if not shutil.which("pkg-config"):
        return False
    for pkg in ("mysqlclient", "mariadb"):
        if subprocess.run(["pkg-config", "--exists", pkg], capture_output=True).returncode == 0:
            return True
    return False


def pip_requirements(settings: Settings, label: str, req: Path, *import_checks: str) -> bool:
    if not req.is_file():
        print(f"  {label}: no requirements at {req} — skip pip")
        return True
    try:
        py = settings.pyenv_python()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return False
    print(f"  {label}: pip install -r {req} (python={py})")
    if not pyenv_m_pip(settings, "install", "-r", str(req)):
        print(f"ERROR: {label} pip install failed ({req})", file=sys.stderr)
        return False
    if import_checks and not verify_imports(settings, *import_checks):
        print(f"ERROR: {label} — import check failed after pip install ({' '.join(import_checks)})", file=sys.stderr)
        return False
    return True


def pip_mysqlclient(settings: Settings) -> bool:
    if not mysql_build_deps_ok(settings):
        print("ERROR: mysqlclient build needs dev headers from os-base", file=sys.stderr)
        return False
    try:
        py = settings.pyenv_python()
    except FileNotFoundError:
        return False
    print(f"  monitor: pip install -v --no-cache-dir mysqlclient>=2.2.0 (python={py})")
    if not pyenv_m_pip(settings, "install", "-v", "--no-cache-dir", "mysqlclient>=2.2.0"):
        return False
    return verify_import(settings, "MySQLdb")


def pip_peer(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dest = cfg.adn_dmr_server_path
    if not dest or not dest.is_dir():
        return True
    return pip_requirements(cfg, "peer", dest / "requirements.txt", "bitarray", "twisted")


def pip_monitor(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    mon = cfg.adn_monitor_path / "monitor"
    if not mon.is_dir():
        return True
    req = mon / "requirements.txt"
    if not mysql_build_deps_ok(cfg):
        print("  WARN: MariaDB dev headers not detected — mysqlclient may fail to build", file=sys.stderr)
    if req.is_file():
        text = req.read_text(encoding="utf-8")
        if not re.search(r"^\s*mysqlclient(\s|>=|==|~=|$)", text, re.MULTILINE):
            print(
                f"  WARN: {req} has no mysqlclient line — installing mysqlclient>=2.2.0 separately",
                file=sys.stderr,
            )
    if not pip_requirements(cfg, "monitor", req, "yaml", "twisted", "fastapi", "uvicorn"):
        if cfg.filegen:
            print("  WARN: monitor requirements failed (filegen — retry without mysqlclient)", file=sys.stderr)
            filtered = req.read_text(encoding="utf-8").splitlines()
            tmp = req.parent / ".requirements-no-mysql.txt"
            tmp.write_text(
                "\n".join(l for l in filtered if not re.match(r"^[[:space:]]*mysqlclient", l)) + "\n",
                encoding="utf-8",
            )
            ok = pip_requirements(cfg, "monitor", tmp, "yaml", "twisted", "fastapi", "uvicorn")
            tmp.unlink(missing_ok=True)
            return ok
        return False
    if not verify_import(cfg, "itsdangerous", quiet=True):
        print("  monitor: installing itsdangerous (FastAPI sessions)")
        if not pyenv_m_pip(cfg, "install", "itsdangerous>=2.0"):
            print("ERROR: monitor — itsdangerous install failed", file=sys.stderr)
            return False
    if verify_import(cfg, "MySQLdb", quiet=True):
        return True
    if cfg.filegen:
        print("  WARN: MySQLdb not importable (filegen — mysqlclient often skipped)")
        return True
    return pip_mysqlclient(cfg)


def pip_daprs(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dest = cfg.adn_root / "D-APRS"
    if not dest.is_dir():
        return True
    return pip_requirements(
        cfg, "daprs", dest / "requirements.txt", "bitarray", "twisted", "aprslib"
    )


def pip_all(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    plugins = cfg.paths.plugins
    err = False
    from adn_deploy.domain.plugins import plugin_peer_stack_enabled, is_plugin_enabled

    if plugin_peer_stack_enabled(plugins, cfg.adn_root):
        err = not pip_peer(cfg) or err
    if is_plugin_enabled(plugins, cfg.adn_root, "adn-monitor"):
        err = not pip_monitor(cfg) or err
    if is_plugin_enabled(plugins, cfg.adn_root, "daprs"):
        err = not pip_daprs(cfg) or err
    return not err
