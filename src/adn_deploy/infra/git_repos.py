"""Git clone helpers for peer and monitor application trees."""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from adn_deploy.core.env import Settings, init_env
from adn_deploy.core.subprocess_runner import is_dry_run, run, run_as_adn
from adn_deploy.domain.plugins import is_plugin_enabled, plugin_peer_stack_enabled

# Local config/state kept inside app trees (untracked). Backed up before a git
# ref switch and always restored afterwards, even if upstream starts tracking them.
PEER_PRESERVE = ("adn-server.yaml", "adn-echo.yaml", "adn-parrot.yaml")
MONITOR_PRESERVE = (".env", "backend/.env", "monitor/adn-monitor.yaml")
DAPRS_PRESERVE = (
    "gps_data.cfg",
    "hblink.cfg",
    "user_settings.txt",
    "mailbox.json",
    "bulletin_board.json",
    "locations.json",
)


def daprs_path(settings: Settings) -> Path:
    return settings.adn_root / "D-APRS"


def repo_is_git_dir(dest: Path) -> bool:
    return (dest / ".git").is_dir()


def peer_tree_ok(dest: Path) -> bool:
    if repo_is_git_dir(dest):
        return True
    has_marker = (dest / "adn-server.example.yaml").is_file() or (dest / "adn-server.py").is_file()
    has_deps = (
        (dest / "requirements.txt").is_file()
        or (dest / "pyproject.toml").is_file()
        or (dest / "setup.py").is_file()
    )
    return has_marker and has_deps


def monitor_tree_ok(dest: Path) -> bool:
    if repo_is_git_dir(dest):
        return True
    mon = dest / "monitor"
    has_req = (mon / "requirements.txt").is_file()
    has_example = (
        (mon / "adn-monitor.yaml.example").is_file()
        or (mon / "adn-monitor.example.yaml").is_file()
        or (dest / ".env.example").is_file()
    )
    return has_req and has_example


def remove_incomplete_dest(settings: Settings, dest: Path) -> None:
    if not dest.exists():
        return
    print(f"  removing incomplete tree: {dest}")
    run(settings, "rm", "-rf", str(dest))


def git_clone(
    settings: Settings,
    url: str,
    branch: str,
    dest: Path,
    *,
    depth: int | None = None,
) -> None:
    cmd: list[str] = ["git", "clone"]
    if depth:
        cmd.extend(["--depth", str(depth)])
    if branch:
        cmd.extend(["-b", branch])
        print(f"  git clone{' --depth ' + str(depth) if depth else ''} -b {branch} {url} -> {dest}")
    else:
        print(f"  git clone{' --depth ' + str(depth) if depth else ''} {url} -> {dest} (remote default branch)")
    cmd.extend([url, str(dest)])
    run(settings, *cmd)


def try_shallow_clone(settings: Settings, url: str, branch: str, dest: Path) -> None:
    if repo_is_git_dir(dest):
        return
    if branch:
        print(f"  trying shallow clone: {url} (-b {branch}) -> {dest}")
    else:
        print(f"  trying shallow clone: {url} (remote default) -> {dest}")
    git_clone(settings, url, branch, dest, depth=1)


def chown_app_tree(settings: Settings, dest: Path) -> None:
    if is_dry_run(settings):
        print(f"[dry-run] chown -R {settings.adn_user}:{settings.adn_user} {dest}")
        return
    try:
        pwd.getpwnam(settings.adn_user)
    except KeyError:
        print(f"  WARN: user {settings.adn_user} not found — skip chown on {dest}", file=sys.stderr)
        return
    proc = run(settings, "chown", "-R", f"{settings.adn_user}:{settings.adn_user}", str(dest), check=False)
    if proc.returncode != 0:
        print(f"  WARN: chown on {dest} failed (install continues)", file=sys.stderr)


def _git(settings: Settings, dest: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in dest as ADN_USER when root (repo owner; avoids safe.directory errors)."""
    cmd = ["git", "-C", str(dest), *args]
    if os.geteuid() == 0 and not settings.filegen:
        try:
            pwd.getpwnam(settings.adn_user)
        except KeyError:
            pass
        else:
            home = settings.adn_user_home or f"/home/{settings.adn_user}"
            cmd = ["sudo", "-u", settings.adn_user, "env", f"HOME={home}", *cmd]
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _git_fail(label: str, what: str, proc: subprocess.CompletedProcess[str]) -> None:
    detail = (proc.stderr or proc.stdout or "").strip()
    print(f"  ERROR: {label}: {what}" + (f"\n    {detail}" if detail else ""), file=sys.stderr)


def _copy_preserving_owner(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    shutil.copy2(src, dest, follow_symlinks=False)
    st = src.lstat()
    try:
        os.lchown(dest, st.st_uid, st.st_gid)
    except PermissionError:
        pass


def backup_local_config(
    settings: Settings, dest: Path, rel_paths: tuple[str, ...], label: str
) -> Path | None:
    """Copy existing config files under dest to ADN_ROOT/adn-backups/<label>-<stamp>/."""
    present = [r for r in rel_paths if (dest / r).is_symlink() or (dest / r).is_file()]
    if not present:
        return None
    root = settings.adn_root / "adn-backups"
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)  # configs hold DB passwords
    bdir = root / f"{label}-{datetime.now():%Y%m%d-%H%M%S}"
    for rel in present:
        _copy_preserving_owner(dest / rel, bdir / rel)
    print(f"  {label}: config backup -> {bdir} ({', '.join(present)})")
    return bdir


def restore_local_config(dest: Path, bdir: Path, label: str) -> None:
    restored = []
    for src in sorted(p for p in bdir.rglob("*") if p.is_symlink() or p.is_file()):
        rel = src.relative_to(bdir)
        _copy_preserving_owner(src, dest / rel)
        restored.append(str(rel))
    print(f"  {label}: config restored ({', '.join(restored)})")


def _remote_default_branch(settings: Settings, dest: Path) -> str:
    proc = _git(settings, dest, "ls-remote", "--symref", "origin", "HEAD")
    for line in proc.stdout.splitlines():
        if line.startswith("ref: refs/heads/"):
            return line.split()[1].removeprefix("refs/heads/")
    return ""


def _checkout_ref(settings: Settings, dest: Path, target: str, label: str) -> bool:
    is_branch = _git(settings, dest, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{target}")
    if is_branch.returncode == 0:
        proc = _git(settings, dest, "checkout", target)
        if proc.returncode != 0:
            _git_fail(label, f"git checkout {target} failed", proc)
            return False
        proc = _git(settings, dest, "merge", "--ff-only", f"origin/{target}")
        if proc.returncode != 0:
            _git_fail(label, f"local branch {target} diverged from origin/{target} (not fast-forward)", proc)
            return False
        return True
    for ref in (f"refs/tags/{target}", target):
        if _git(settings, dest, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}").returncode == 0:
            proc = _git(settings, dest, "checkout", "--detach", ref)
            if proc.returncode != 0:
                _git_fail(label, f"git checkout {target} failed", proc)
                return False
            return True
    print(f"  ERROR: {label}: '{target}' is not a branch, tag or commit on origin", file=sys.stderr)
    return False


def sync_repo_ref(
    settings: Settings, dest: Path, ref: str, label: str, preserve: tuple[str, ...]
) -> bool:
    """Update an existing clone to ref (branch/tag/SHA; empty = remote default branch).

    Refuses when tracked files have local edits. Config files in ``preserve`` are
    backed up first and restored after checkout (also when checkout fails).
    """
    if not repo_is_git_dir(dest):
        print(f"  {label}: {dest} is not a git repo — skip update")
        return True
    want = ref.strip()
    if is_dry_run(settings):
        print(f"[dry-run] {label}: git fetch + checkout {want or '<remote default>'} in {dest}")
        return True

    status = _git(settings, dest, "status", "--porcelain", "--untracked-files=no")
    if status.returncode != 0:
        _git_fail(label, f"git status failed in {dest}", status)
        return False
    if status.stdout.strip():
        print(
            f"  ERROR: {label}: local changes to tracked files in {dest} — commit or stash them first:\n"
            + "\n".join(f"    {ln}" for ln in status.stdout.splitlines()),
            file=sys.stderr,
        )
        return False

    before = _git(settings, dest, "rev-parse", "--short", "HEAD").stdout.strip()
    proc = _git(settings, dest, "fetch", "--tags", "--force", "--prune", "origin")
    if proc.returncode != 0:
        _git_fail(label, "git fetch origin failed", proc)
        return False
    target = want or _remote_default_branch(settings, dest)
    if not target:
        print(f"  ERROR: {label}: cannot resolve remote default branch for {dest}", file=sys.stderr)
        return False

    bdir = backup_local_config(settings, dest, preserve, label)
    try:
        if bdir:
            # Untracked copies would block checkout if upstream starts tracking them.
            for rel in preserve:
                if (dest / rel).is_symlink() or (dest / rel).is_file():
                    (dest / rel).unlink()
        ok = _checkout_ref(settings, dest, target, label)
    finally:
        if bdir:
            restore_local_config(dest, bdir, label)
    if not ok:
        return False
    after = _git(settings, dest, "rev-parse", "--short", "HEAD").stdout.strip()
    state = "already at" if before == after else f"{before} ->"
    print(f"  {label}: {state} {after} ({target})")
    return True


def _skip_clone(settings: Settings) -> bool:
    return os.environ.get("ADN_SKIP_CLONE", "0") == "1"


def _copy_fixture(src: Path, dest: Path, label: str) -> bool:
    if not src.is_dir():
        return False
    print(f"  {label}: copy fixture {src} -> {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    return True


def clone_peer_fixture(settings: Settings) -> bool:
    for src in (Path("/opt/new-adn-server"), Path("/opt/adn-dmr-server")):
        if _copy_fixture(src, settings.adn_dmr_server_path, "peer"):
            return True
    print("  peer: no local fixture under /opt/new-adn-server or /opt/adn-dmr-server", file=sys.stderr)
    return False


def clone_monitor_fixture(settings: Settings) -> bool:
    src = Path("/opt/adn-monitor")
    if _copy_fixture(src, settings.adn_monitor_path, "monitor"):
        return True
    print("  monitor: no local fixture /opt/adn-monitor", file=sys.stderr)
    return False


def clone_peer(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dest = cfg.adn_dmr_server_path
    assert dest is not None

    if _skip_clone(cfg):
        if not peer_tree_ok(dest):
            print(f"ERROR: ADN_SKIP_CLONE=1 but peer tree is missing at {dest}", file=sys.stderr)
            return False
        print("  peer: clone skipped (ADN_SKIP_CLONE=1)")
        return True

    if peer_tree_ok(dest):
        if repo_is_git_dir(dest) and not cfg.filegen:
            print(f"  peer: git repo at {dest} — updating")
            return sync_repo_ref(cfg, dest, cfg.git_branch_peer, "peer", PEER_PRESERVE)
        print(f"  peer: tree present at {dest}")
        return True

    remove_incomplete_dest(cfg, dest)
    run(cfg, "mkdir", "-p", str(dest.parent))

    if cfg.filegen:
        if clone_peer_fixture(cfg) and peer_tree_ok(dest):
            chown_app_tree(cfg, dest)
            return True
        try_shallow_clone(cfg, cfg.git_url_peer, cfg.git_branch_peer, dest)
        if peer_tree_ok(dest):
            chown_app_tree(cfg, dest)
            return True
        remove_incomplete_dest(cfg, dest)
        if not clone_peer_fixture(cfg) or not peer_tree_ok(dest):
            print(f"ERROR: filegen peer fixture and git clone both failed for {dest}", file=sys.stderr)
            return False
        chown_app_tree(cfg, dest)
        return True

    print(f"Cloning ADN-DMR-Peer-Server -> {dest} ...")
    if is_dry_run(cfg):
        print(f"[dry-run] git clone {cfg.git_url_peer} -> {dest}")
    else:
        git_clone(cfg, cfg.git_url_peer, cfg.git_branch_peer, dest)
    if not peer_tree_ok(dest):
        print(f"ERROR: peer clone finished but tree at {dest} is incomplete", file=sys.stderr)
        return False
    chown_app_tree(cfg, dest)
    return True


def clone_monitor(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dest = cfg.adn_monitor_path
    assert dest is not None

    if _skip_clone(cfg):
        if not monitor_tree_ok(dest):
            print(f"ERROR: ADN_SKIP_CLONE=1 but monitor tree is missing at {dest}", file=sys.stderr)
            return False
        print("  monitor: clone skipped (ADN_SKIP_CLONE=1)")
        return True

    if monitor_tree_ok(dest):
        if repo_is_git_dir(dest) and not cfg.filegen:
            print(f"  monitor: git repo at {dest} — updating")
            return sync_repo_ref(cfg, dest, cfg.git_branch_monitor, "monitor", MONITOR_PRESERVE)
        print(f"  monitor: tree present at {dest}")
        return True

    remove_incomplete_dest(cfg, dest)
    run(cfg, "mkdir", "-p", str(dest.parent))

    if cfg.filegen:
        if clone_monitor_fixture(cfg) and monitor_tree_ok(dest):
            chown_app_tree(cfg, dest)
            return True
        try_shallow_clone(cfg, cfg.git_url_monitor, cfg.git_branch_monitor, dest)
        if monitor_tree_ok(dest):
            chown_app_tree(cfg, dest)
            return True
        remove_incomplete_dest(cfg, dest)
        if not clone_monitor_fixture(cfg) or not monitor_tree_ok(dest):
            print(f"ERROR: filegen monitor fixture and git clone both failed for {dest}", file=sys.stderr)
            return False
        chown_app_tree(cfg, dest)
        return True

    print(f"Cloning ADN-Monitor -> {dest} ...")
    if is_dry_run(cfg):
        print(f"[dry-run] git clone {cfg.git_url_monitor} -> {dest}")
    else:
        git_clone(cfg, cfg.git_url_monitor, cfg.git_branch_monitor, dest)
    if not monitor_tree_ok(dest):
        print(f"ERROR: monitor clone finished but tree at {dest} is incomplete", file=sys.stderr)
        return False
    chown_app_tree(cfg, dest)
    return True



def daprs_tree_ok(dest: Path) -> bool:
    if repo_is_git_dir(dest):
        return True
    return (dest / "gps_data.py").is_file() and (dest / "requirements.txt").is_file()


def clone_daprs(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dest = daprs_path(cfg)

    if _skip_clone(cfg):
        if not daprs_tree_ok(dest):
            print(f"ERROR: ADN_SKIP_CLONE=1 but daprs tree is missing at {dest}", file=sys.stderr)
            return False
        print("  daprs: clone skipped (ADN_SKIP_CLONE=1)")
        return True

    if daprs_tree_ok(dest):
        if repo_is_git_dir(dest) and not cfg.filegen:
            print(f"  daprs: git repo at {dest} — updating")
            return sync_repo_ref(cfg, dest, cfg.git_branch_daprs, "daprs", DAPRS_PRESERVE)
        print(f"  daprs: tree present at {dest}")
        return True

    remove_incomplete_dest(cfg, dest)
    run(cfg, "mkdir", "-p", str(dest.parent))

    print(f"Cloning D-APRS (hbnet) -> {dest} ...")
    if is_dry_run(cfg):
        print(f"[dry-run] git clone {cfg.git_url_daprs} -> {dest}")
    else:
        git_clone(cfg, cfg.git_url_daprs, cfg.git_branch_daprs, dest)
    if not daprs_tree_ok(dest):
        print(f"ERROR: daprs clone finished but tree at {dest} is incomplete", file=sys.stderr)
        return False
    chown_app_tree(cfg, dest)
    return True


def verify_pyenv_import(settings: Settings, module: str) -> bool:
    try:
        py = settings.pyenv_python()
    except FileNotFoundError:
        return False
    if is_dry_run(settings):
        return True
    proc = subprocess.run(
        [str(py), "-c", f"import {module}"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def assert_install_trees(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    err = 0
    peer = cfg.adn_dmr_server_path
    mon = cfg.adn_monitor_path
    assert peer is not None and mon is not None

    if not peer_tree_ok(peer):
        print(f"ERROR: peer application tree missing at {peer}", file=sys.stderr)
        err = 1
    elif not (peer / "adn-server.example.yaml").is_file():
        print(f"ERROR: missing {peer}/adn-server.example.yaml after clone", file=sys.stderr)
        err = 1
    elif not (peer / "adn-echo.example.yaml").is_file():
        print(f"ERROR: missing {peer}/adn-echo.example.yaml after clone", file=sys.stderr)
        err = 1

    if not monitor_tree_ok(mon):
        print(f"ERROR: monitor application tree missing at {mon}", file=sys.stderr)
        err = 1
    else:
        mon_ex = None
        for candidate in (
            mon / "monitor" / "adn-monitor.yaml.example",
            mon / "monitor" / "adn-monitor.example.yaml",
        ):
            if candidate.is_file():
                mon_ex = candidate
                break
        if mon_ex is None:
            print(f"ERROR: missing monitor example yaml under {mon}/monitor/ after clone", file=sys.stderr)
            err = 1
        if not (mon / ".env.example").is_file():
            print(f"ERROR: missing {mon}/.env.example after clone", file=sys.stderr)
            err = 1

    if is_plugin_enabled(cfg.paths.plugins, cfg.adn_root, "daprs"):
        daprs = daprs_path(cfg)
        if not daprs_tree_ok(daprs):
            print(f"ERROR: daprs application tree missing at {daprs}", file=sys.stderr)
            err = 1

    plugins_dir = cfg.paths.plugins
    adn_root = cfg.adn_root
    if err == 0 and plugin_peer_stack_enabled(plugins_dir, adn_root):
        if not verify_pyenv_import(cfg, "bitarray"):
            try:
                py = cfg.pyenv_python()
            except FileNotFoundError:
                py = Path("?")
            print(f"ERROR: bitarray not importable ({py}) — run: adn-deploy pip", file=sys.stderr)
            err = 1

    return err == 0


def git_pull_deploy(settings: Settings | None = None) -> bool:
    """Pull latest ADN-Deploy toolkit (run as ADN_USER)."""
    cfg = settings or init_env()
    dest = cfg.adn_deploy_home
    if not (dest / ".git").is_dir():
        print(f"  deploy: not a git repo at {dest} — skip git pull (use rsync to update)")
        return True
    branch = str(cfg.git_branch_deploy or "").strip()
    if branch:
        print(f"  deploy: git pull origin {branch} at {dest}")
        cmd = f"cd {dest} && git pull --ff-only origin {branch}"
    else:
        print(f"  deploy: git pull at {dest}")
        cmd = f"cd {dest} && git pull --ff-only"
    proc = run_as_adn(cfg, cmd, check=False)
    if proc is not None and proc.returncode != 0:
        print(
            "  ERROR: deploy git pull failed — resolve conflicts or pull manually",
            file=sys.stderr,
        )
        return False
    return True


def git_pull_peer(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dest = cfg.adn_dmr_server_path
    if not dest:
        return True
    return sync_repo_ref(cfg, dest, cfg.git_branch_peer, "peer", PEER_PRESERVE)


def git_pull_monitor(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dest = cfg.adn_monitor_path
    if not dest:
        return True
    return sync_repo_ref(cfg, dest, cfg.git_branch_monitor, "monitor", MONITOR_PRESERVE)


def git_pull_daprs(settings: Settings | None = None) -> bool:
    cfg = settings or init_env()
    dest = daprs_path(cfg)
    if not dest.is_dir():
        return True
    return sync_repo_ref(cfg, dest, cfg.git_branch_daprs, "daprs", DAPRS_PRESERVE)
